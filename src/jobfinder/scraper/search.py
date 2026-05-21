"""Search construction and Apify execution for scraper runs."""

from __future__ import annotations

import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any

import requests

from jobfinder.providers import indeed, linkedin, stepstone
from jobfinder.providers.apify_client import (
    ApifyAccountUnavailableError,
    ApifyConfigurationError,
    ApifyRunError,
    ApifyRunTimeoutError,
    ApifyTransientError,
    apify_error_message,
    apify_http_timeout,
    retry_delay_seconds,
    run_actor,
)
from jobfinder.providers.registry import provider_adapter
from jobfinder.scraper.settings import (
    SOURCE_ALIASES,
    SOURCE_ORDER,
    ScraperSettings,
    source_label,
)

LOGGER = logging.getLogger("jobfinder.scraper")

__all__ = [
    "ApifyConfigurationError",
    "ApifyAccountUnavailableError",
    "ApifyRunError",
    "ApifyRunTimeoutError",
    "ApifyTransientError",
    "SearchExecutionError",
    "SearchRequest",
    "apify_error_message",
    "apify_http_timeout",
    "build_indeed_actor_input",
    "build_linkedin_actor_input",
    "build_linkedin_search_url",
    "build_stepstone_actor_input",
    "fetch_jobs_for_search",
    "get_searches",
    "indeed_base_url",
    "parse_job_sources",
    "run_actor",
    "run_all_searches",
]


class SearchExecutionError(RuntimeError):
    """Raised when one keyword search cannot be completed."""


@dataclass(frozen=True)
class SearchRequest:
    """A single source/keyword search to run through Apify."""

    source: str
    source_label: str
    keyword: str
    display_label: str
    actor_id: str
    payload: dict[str, Any]
    max_items: int


@dataclass(frozen=True)
class SearchBatch:
    """One execution unit that may contain several compatible searches."""

    searches: tuple[tuple[int, SearchRequest], ...]

    @property
    def source(self) -> str:
        """Return the shared source for the batch."""
        return self.searches[0][1].source

    @property
    def source_label(self) -> str:
        """Return the shared display source for the batch."""
        return self.searches[0][1].source_label

    @property
    def display_label(self) -> str:
        """Return a concise label for log output."""
        if len(self.searches) == 1:
            return self.searches[0][1].display_label
        first_keyword = self.searches[0][1].keyword
        last_keyword = self.searches[-1][1].keyword
        return (
            f"{self.source_label} batch: {first_keyword} ... {last_keyword} "
            f"({len(self.searches)} searches)"
        )


def indeed_base_url(settings: ScraperSettings) -> str:
    """Return the public Indeed base URL for the configured country."""
    return indeed.base_url(settings)


def build_linkedin_search_url(settings: ScraperSettings, keyword: str) -> str:
    """Build a LinkedIn job-search URL for one keyword."""
    return linkedin.build_search_url(settings, keyword)


def build_linkedin_actor_input(
    settings: ScraperSettings, search_url: str
) -> dict[str, Any]:
    """Build the Apify actor payload for LinkedIn searches."""
    return linkedin.build_actor_input(settings, search_url)


def build_indeed_actor_input(settings: ScraperSettings, keyword: str) -> dict[str, Any]:
    """Build the Apify actor payload for Indeed searches."""
    return indeed.build_actor_input(settings, keyword)


def build_stepstone_actor_input(
    settings: ScraperSettings,
    keyword: str,
) -> dict[str, Any]:
    """Build the Apify actor payload for Stepstone searches."""
    return stepstone.build_actor_input(settings, keyword)


def build_actor_input(
    settings: ScraperSettings, source: str, keyword: str
) -> dict[str, Any]:
    """Build a source-specific Apify actor payload."""
    return provider_adapter(source).build_actor_input(settings, keyword)


def build_search(settings: ScraperSettings, source: str, keyword: str) -> SearchRequest:
    """Build a typed search request for one source and keyword."""
    label = source_label(source)
    return SearchRequest(
        source=source,
        source_label=label,
        keyword=keyword,
        display_label=f"{label} / {keyword}",
        actor_id=settings.source_actor_ids[source],
        payload=build_actor_input(settings, source, keyword),
        max_items=settings.source_max_items[source],
    )


def parse_job_sources(settings: ScraperSettings) -> list[str]:
    """Resolve selected job sources from environment aliases."""
    selected: set[str] = set()
    raw_parts = re.split(r"[\s,]+", settings.source_mode.strip().casefold())
    parts = [part for part in raw_parts if part]
    for part in parts:
        selected.update(SOURCE_ALIASES.get(part, set()))

    if not selected:
        LOGGER.warning(
            "Unknown JOBSCRAPER_SOURCES %r; using LinkedIn only.",
            settings.source_mode,
        )
        selected = {"linkedin"}

    return [source for source in SOURCE_ORDER if source in selected]


def get_searches(
    settings: ScraperSettings, sources: list[str]
) -> tuple[str, list[SearchRequest]]:
    """Build all source/keyword searches for a scraper run."""
    searches = []
    for source in sources:
        if source not in settings.source_actor_ids:
            continue
        searches.extend(build_source_searches(settings, source))

    source_labels = ", ".join(source_label(source) for source in sources)
    return f"generated {source_labels} searches", searches


def build_source_searches(
    settings: ScraperSettings,
    source: str,
) -> list[SearchRequest]:
    """Build source-specific searches without changing provider internals."""
    if source == "stepstone" and settings.stepstone_start_urls:
        label = source_label(source)
        return [
            SearchRequest(
                source=source,
                source_label=label,
                keyword="Configured URLs",
                display_label=f"{label} / configured URLs",
                actor_id=settings.source_actor_ids[source],
                payload=provider_adapter(source).build_direct_input(settings),
                max_items=settings.source_max_items[source],
            )
        ]

    return [build_search(settings, source, keyword) for keyword in settings.keywords]


def annotate_jobs(
    jobs: list[dict[str, Any]], source: str, label: str
) -> list[dict[str, Any]]:
    """Attach source metadata to raw jobs returned by Apify."""
    return [dict(job, _source=source, _source_label=label) for job in jobs]


def search_url(search: SearchRequest) -> str:
    """Return the single search URL from a LinkedIn search request."""
    urls = search.payload.get("urls")
    if isinstance(urls, list) and urls:
        return str(urls[0])
    return ""


def candidate_source_urls(job: dict[str, Any]) -> set[str]:
    """Return possible actor input/search URL fields from one raw job."""
    candidates: set[str] = set()
    for key in (
        "inputUrl",
        "input_url",
        "searchUrl",
        "search_url",
        "startUrl",
        "start_url",
        "requestUrl",
        "request_url",
    ):
        value = job.get(key)
        if value and str(value).startswith("http"):
            candidates.add(str(value))
    return candidates


def group_batched_linkedin_jobs(
    batch: SearchBatch,
    jobs: list[dict[str, Any]],
) -> list[tuple[int, str, list[dict[str, Any]]]] | None:
    """Group batched LinkedIn results by original keyword when attribution is clear."""
    url_to_search = {
        search_url(search): (idx, search)
        for idx, search in batch.searches
        if search_url(search)
    }
    grouped: dict[int, list[dict[str, Any]]] = {idx: [] for idx, _ in batch.searches}

    for job in jobs:
        matching_urls = candidate_source_urls(job) & url_to_search.keys()
        if len(matching_urls) != 1:
            return None
        idx, search = url_to_search[matching_urls.pop()]
        grouped[idx].append(
            dict(job, _source=search.source, _source_label=search.source_label)
        )

    return [(idx, search.keyword, grouped[idx]) for idx, search in batch.searches]


def build_search_batches(
    settings: ScraperSettings,
    searches: list[SearchRequest],
) -> list[SearchBatch]:
    """Build execution units, batching only sources with safe attribution fallback."""
    if settings.apify_batch_size <= 1:
        return [
            SearchBatch(((idx, search),))
            for idx, search in enumerate(searches, start=1)
        ]

    batches: list[SearchBatch] = []
    pending_linkedin: list[tuple[int, SearchRequest]] = []

    def flush_linkedin() -> None:
        nonlocal pending_linkedin
        if pending_linkedin:
            batches.append(SearchBatch(tuple(pending_linkedin)))
            pending_linkedin = []

    for idx, search in enumerate(searches, start=1):
        if search.source == "linkedin":
            pending_linkedin.append((idx, search))
            if len(pending_linkedin) >= settings.apify_batch_size:
                flush_linkedin()
            continue

        flush_linkedin()
        batches.append(SearchBatch(((idx, search),)))

    flush_linkedin()
    return batches


def fetch_jobs_for_batch(
    settings: ScraperSettings,
    batch: SearchBatch,
) -> list[tuple[int, str, list[dict[str, Any]]]]:
    """Fetch one execution batch, falling back when attribution is not safe."""
    if len(batch.searches) == 1:
        idx, search = batch.searches[0]
        return [(idx, search.keyword, fetch_jobs_for_search(settings, search))]

    first_search = batch.searches[0][1]
    search_urls = [search_url(search) for _, search in batch.searches]
    if first_search.source != "linkedin" or not all(search_urls):
        return [
            (idx, search.keyword, fetch_jobs_for_search(settings, search))
            for idx, search in batch.searches
        ]

    payload = linkedin.build_batch_actor_input(settings, search_urls)
    batch_search = SearchRequest(
        source=first_search.source,
        source_label=first_search.source_label,
        keyword=", ".join(search.keyword for _, search in batch.searches),
        display_label=batch.display_label,
        actor_id=first_search.actor_id,
        payload=payload,
        max_items=sum(search.max_items for _, search in batch.searches),
    )
    jobs = fetch_jobs_for_search(settings, batch_search)
    grouped = group_batched_linkedin_jobs(batch, jobs)
    if grouped is not None:
        return grouped

    LOGGER.warning(
        "LinkedIn batch result attribution was not available for %s. "
        "Re-running those searches individually to preserve keyword matching.",
        batch.display_label,
    )
    return [
        (idx, search.keyword, fetch_jobs_for_search(settings, search))
        for idx, search in batch.searches
    ]


def search_failure_message(label: str, exc: Exception) -> str:
    """Build a concise fatal error message for one failed keyword search."""
    return f"Search {label!r} could not be completed: {exc}"


def fetch_jobs_for_search(
    settings: ScraperSettings, search: SearchRequest
) -> list[dict[str, Any]]:
    """Call Apify for one search and return annotated job dictionaries."""
    label = search.display_label
    total_attempts = settings.apify_transient_error_retries + 1
    for attempt in range(1, total_attempts + 1):
        try:
            jobs = run_provider_actor(settings, search)
            return annotate_jobs(jobs, search.source, search.source_label)
        except ApifyConfigurationError:
            raise
        except ApifyRunTimeoutError as exc:
            raise SearchExecutionError(search_failure_message(label, exc)) from exc
        except requests.exceptions.HTTPError as exc:
            response = exc.response
            details = (
                f" {apify_error_message(response)}" if response is not None else ""
            )
            raise SearchExecutionError(
                f"Search {label!r} could not be completed: {exc}.{details}"
            ) from exc
        except (
            ApifyTransientError,
            ApifyRunError,
            requests.exceptions.Timeout,
            requests.exceptions.ConnectionError,
        ) as exc:
            if attempt >= total_attempts:
                raise SearchExecutionError(search_failure_message(label, exc)) from exc

            delay = retry_delay_seconds(settings, attempt)
            LOGGER.warning(
                "Temporary Apify issue for search %r on attempt %s/%s: %s. "
                "Retrying in %ss.",
                label,
                attempt,
                total_attempts,
                exc,
                delay,
            )
            if delay:
                time.sleep(delay)
        except Exception as exc:
            raise SearchExecutionError(search_failure_message(label, exc)) from exc

    raise SearchExecutionError(f"Search {label!r} ended without a result.")


def run_provider_actor(
    settings: ScraperSettings,
    search: SearchRequest,
) -> list[dict[str, Any]]:
    """Run a provider search through the correct actor adapter."""
    return provider_adapter(search.source).run_actor_search(
        settings,
        search.actor_id,
        search.payload,
        search.max_items,
        run_actor,
    )


def source_concurrency_limit(settings: ScraperSettings, source: str) -> int:
    """Return the source-specific execution limit for actor runs."""
    if source == "indeed":
        return max(1, settings.indeed_max_concurrency)
    if source == "stepstone":
        return max(1, settings.stepstone_max_concurrency)
    return max(1, settings.search_concurrency)


def run_all_searches(
    settings: ScraperSettings,
    searches: list[SearchRequest],
) -> tuple[
    list[tuple[str, list[dict[str, Any]]]], list[str], dict[str, str], list[str]
]:
    """Run searches concurrently while preserving the original result order."""
    all_results: list[tuple[int, str, list[dict[str, Any]]]] = []
    zero_searches: list[str] = []
    failed_sources: dict[str, str] = {}
    skipped_searches: list[str] = []
    search_batches = build_search_batches(settings, searches)
    if not search_batches:
        return [], zero_searches, failed_sources, skipped_searches
    max_workers = min(settings.search_concurrency, len(search_batches))
    submitted_count = 0
    in_flight_by_source: dict[str, int] = {}
    next_batch_idx = 0

    LOGGER.info(
        "Running up to %s search execution unit(s) in parallel.",
        max_workers,
    )

    def submit_next(
        executor: ThreadPoolExecutor,
        in_flight: dict[Any, SearchBatch],
    ) -> None:
        """Submit searches until the concurrency window is full."""
        nonlocal next_batch_idx, submitted_count
        while len(in_flight) < max_workers and next_batch_idx < len(search_batches):
            batch = search_batches[next_batch_idx]

            source_limit = source_concurrency_limit(settings, batch.source)
            if in_flight_by_source.get(batch.source, 0) >= source_limit:
                return

            label = batch.display_label
            next_batch_idx += 1
            if batch.source in failed_sources:
                for idx, search in batch.searches:
                    LOGGER.info(
                        "[%02d/%s] Skipping %s because %s failed earlier in this run.",
                        idx,
                        len(searches),
                        search.display_label,
                        search.source_label,
                    )
                    skipped_searches.append(search.display_label)
                continue

            if settings.delay_between_requests and submitted_count:
                time.sleep(settings.delay_between_requests)

            LOGGER.info(
                "[%02d/%s] Searching %s with Apify actor %s.",
                batch.searches[0][0],
                len(searches),
                label,
                batch.searches[0][1].actor_id,
            )
            future = executor.submit(fetch_jobs_for_batch, settings, batch)
            in_flight[future] = batch
            in_flight_by_source[batch.source] = (
                in_flight_by_source.get(batch.source, 0) + 1
            )
            submitted_count += 1

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        in_flight: dict[Any, SearchBatch] = {}
        submit_next(executor, in_flight)

        while in_flight:
            for future in as_completed(tuple(in_flight)):
                batch = in_flight.pop(future)
                in_flight_by_source[batch.source] = max(
                    0,
                    in_flight_by_source.get(batch.source, 1) - 1,
                )

                try:
                    batch_results = future.result()
                except ApifyConfigurationError as exc:
                    if batch.source not in failed_sources:
                        LOGGER.error("%s", exc)
                        LOGGER.warning(
                            "Continuing with other sources. Remaining %s searches "
                            "will be skipped.",
                            batch.source_label,
                        )
                        failed_sources[batch.source] = str(exc)
                    skipped_searches.extend(
                        search.display_label for _, search in batch.searches
                    )
                except SearchExecutionError as exc:
                    if batch.source == "stepstone":
                        if batch.source not in failed_sources:
                            LOGGER.error("%s", exc)
                            LOGGER.warning(
                                "Continuing with other sources. Remaining %s "
                                "searches will be skipped.",
                                batch.source_label,
                            )
                            failed_sources[batch.source] = str(exc)
                        skipped_searches.extend(
                            search.display_label for _, search in batch.searches
                        )
                        submit_next(executor, in_flight)
                        break
                    LOGGER.error("%s", exc)
                    raise
                else:
                    for idx, keyword, jobs in batch_results:
                        search = next(
                            search
                            for search_idx, search in batch.searches
                            if search_idx == idx
                        )
                        all_results.append((idx, keyword, jobs))
                        if jobs:
                            LOGGER.info(
                                "Completed %s: %s job(s) found.",
                                search.display_label,
                                len(jobs),
                            )
                        else:
                            LOGGER.info(
                                "Completed %s: 0 results.", search.display_label
                            )
                            zero_searches.append(search.display_label)

                submit_next(executor, in_flight)
                break

    ordered_results = [
        (keyword, jobs)
        for _, keyword, jobs in sorted(all_results, key=lambda item: item[0])
    ]
    return ordered_results, zero_searches, failed_sources, skipped_searches
