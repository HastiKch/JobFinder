"""Application service for running scraper workflows outside the CLI."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

from jobfinder.dedupe.matching import deduplicate_search_results
from jobfinder.scraper.export_excel import export_to_excel
from jobfinder.scraper.export_google_sheets import (
    build_scraper_google_sheets_service,
    export_to_google_sheets,
)
from jobfinder.scraper.filters import (
    filter_applicant_count,
    filter_excluded_companies,
    filter_excluded_titles,
)
from jobfinder.scraper.normalize import get_posted
from jobfinder.scraper.run_history import (
    GoogleSpreadsheetContext,
    apply_configured_posted_time_window,
    filter_jobs_to_previous_run_window,
    load_google_spreadsheet_context,
    remove_jobs_seen_in_history,
)
from jobfinder.scraper.search import get_searches, parse_job_providers, run_all_searches
from jobfinder.scraper.settings import (
    OUTPUT_MODE_ALIASES,
    ScraperSettings,
    source_label,
)

LOGGER = logging.getLogger("jobfinder.scraper")


class ScraperServiceError(RuntimeError):
    """Raised when the scraper workflow cannot be completed."""


@dataclass(frozen=True)
class ScrapeResult:
    """Summary of a completed scraper run."""

    output_destinations: list[tuple[str, str]]
    search_count: int
    unique_job_count: int
    runtime_seconds: float
    zero_searches: list[str]
    failed_sources: dict[str, str]
    skipped_searches: list[str]
    excluded_title_count: int
    excluded_company_count: int
    excluded_applicant_count: int
    outside_window_count: int
    unknown_posted_count: int
    historical_duplicate_count: int

    @property
    def failed_providers(self) -> dict[str, str]:
        """Return provider failures keyed by provider name."""
        return self.failed_sources


def parse_output_mode(settings: ScraperSettings) -> set[str]:
    """Resolve requested output modes from environment aliases."""
    modes = OUTPUT_MODE_ALIASES.get(settings.output_mode)
    if modes:
        return modes

    LOGGER.warning(
        "Unknown JOBSCRAPER_OUTPUT_MODE %r; using local Excel output.",
        settings.output_mode,
    )
    return {"excel"}


def format_duration(seconds: float) -> str:
    """Format elapsed seconds as a compact human-readable duration."""
    total_seconds = int(round(seconds))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    if hours:
        return f"{hours}h {minutes}m {seconds}s"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def sort_key(settings: ScraperSettings, job: dict[str, Any]) -> str:
    """Return the posted-date sort key, keeping missing dates at the bottom."""
    posted = get_posted(settings, job)
    return posted if posted != "N/A" else "0000"


def run_scrape(settings: ScraperSettings) -> ScrapeResult:
    """Run the full scraper workflow using already-resolved settings."""
    run_started = time.perf_counter()

    output_modes = parse_output_mode(settings)
    google_sheets_service = None
    google_context = GoogleSpreadsheetContext("", "", [], None, set())
    if "google_sheets" in output_modes:
        LOGGER.info("Checking Google Sheets access.")
        google_sheets_service = build_scraper_google_sheets_service()
        google_context = load_google_spreadsheet_context(
            settings,
            google_sheets_service,
        )
        LOGGER.info("Google Sheets access is ready.")

    settings, posted_window_seconds, filter_to_previous_run_window = (
        apply_configured_posted_time_window(
            settings,
            google_context.previous_run_started_at,
        )
    )

    job_providers = parse_job_providers(settings)
    search_plan_summary, searches = get_searches(settings, job_providers)
    if not searches:
        raise ScraperServiceError(
            "No searches configured. Add keywords to configs/keywords.txt."
        )

    LOGGER.info(
        "JobScraper started at %s.",
        settings.run_started_at.strftime("%Y-%m-%d %H:%M %Z"),
    )
    LOGGER.info(
        "Sources: %s.", ", ".join(source_label(source) for source in job_providers)
    )
    if "linkedin" in job_providers:
        LOGGER.info("LinkedIn actor: %s.", settings.provider_actor_ids["linkedin"])
    if "indeed" in job_providers:
        LOGGER.info("Indeed actor: %s.", settings.provider_actor_ids["indeed"])
    if "stepstone" in job_providers:
        LOGGER.info("Stepstone actor: %s.", settings.provider_actor_ids["stepstone"])
    LOGGER.info("Search plan: %s.", search_plan_summary)
    LOGGER.info("Output mode: %s.", ", ".join(sorted(output_modes)))
    LOGGER.info("Timezone: %s.", settings.scraper_timezone)
    LOGGER.info("Posted timezone: %s.", settings.posted_timezone)
    LOGGER.info("Posted-time window: %s.", settings.posted_time_window)
    if google_context.previous_run_started_at:
        LOGGER.info(
            "Previous Google Sheets posted anchor: %s.",
            google_context.previous_run_started_at.strftime("%Y-%m-%d %H:%M:%S %Z"),
        )
    if posted_window_seconds:
        LOGGER.info(
            "Provider posted search window: %s second(s).",
            posted_window_seconds,
        )
    LOGGER.info("Searches: %s.", len(searches))
    LOGGER.info("Search concurrency: %s.", settings.search_concurrency)
    if len(settings.apify_api_tokens) > 1:
        LOGGER.info(
            "Apify token fallbacks configured: %s.",
            len(settings.apify_api_tokens),
        )
    if settings.max_applicants > 0:
        LOGGER.info("Max applicants/job: %s.", settings.max_applicants)
    else:
        LOGGER.info("Max applicants/job: no limit.")
    LOGGER.info("Apify child run memory: %s MB.", settings.apify_run_memory_mb)
    LOGGER.info("Apify child run timeout: %ss.", settings.apify_run_timeout_seconds)
    LOGGER.info(
        "Apify transient error retries: %s.",
        settings.apify_transient_error_retries,
    )
    LOGGER.info(
        "Apify retry base delay: %ss.",
        settings.apify_retry_delay_seconds,
    )
    if settings.delay_between_requests:
        LOGGER.info(
            "Delay between starting searches: %ss.",
            settings.delay_between_requests,
        )
    if "linkedin" in job_providers:
        LOGGER.info("LinkedIn job types: %s.", ", ".join(settings.contract_types))
        LOGGER.info(
            "LinkedIn experience levels: %s.",
            ", ".join(settings.experience_levels),
        )
        LOGGER.info("LinkedIn max results/search: %s.", settings.max_results_per_search)
        LOGGER.info(
            "LinkedIn scrape company details: %s.",
            settings.scrape_company_details,
        )
    if "indeed" in job_providers:
        LOGGER.info(
            "Indeed country/location: %s / %s.",
            settings.indeed_country.upper(),
            settings.indeed_location,
        )
        LOGGER.info(
            "Indeed max results/search: %s.",
            settings.indeed_max_results_per_search,
        )
        LOGGER.info("Indeed max concurrency: %s.", settings.indeed_max_concurrency)
        LOGGER.info(
            "Indeed save unique only: %s.",
            settings.indeed_save_only_unique_items,
        )
    if "stepstone" in job_providers:
        LOGGER.info("Stepstone location: %s.", settings.stepstone_location)
        if settings.stepstone_start_urls:
            LOGGER.info(
                "Stepstone direct URL searches: %s.",
                len(settings.stepstone_start_urls),
            )
        elif settings.stepstone_category:
            LOGGER.info("Stepstone category fallback: %s.", settings.stepstone_category)
        LOGGER.info(
            "Stepstone max results/search: %s.",
            settings.stepstone_max_results_per_search,
        )
        LOGGER.info(
            "Stepstone actor concurrency: %s.",
            settings.stepstone_max_concurrency,
        )

    all_results, zero_searches, failed_sources, skipped_searches = run_all_searches(
        settings, searches
    )

    LOGGER.info("Deduplicating results.")
    dedupe_result = deduplicate_search_results(
        all_results,
        include_debug=LOGGER.isEnabledFor(logging.DEBUG),
    )
    unique_jobs = dedupe_result.jobs
    LOGGER.info(
        "%s unique job(s) after deduplication (%s scraped row(s) collapsed).",
        len(unique_jobs),
        dedupe_result.input_count - dedupe_result.output_count,
    )

    LOGGER.info("Applying title filters.")
    unique_jobs, excluded_title_count = filter_excluded_titles(settings, unique_jobs)
    terms = ", ".join(settings.excluded_title_terms)
    LOGGER.info(
        "Removed %s job(s) containing excluded title terms: %s.",
        excluded_title_count,
        terms,
    )

    LOGGER.info("Applying company filters.")
    unique_jobs, excluded_company_count = filter_excluded_companies(
        settings,
        unique_jobs,
    )
    company_terms = ", ".join(settings.excluded_company_terms)
    LOGGER.info(
        "Removed %s job(s) matching excluded company terms: %s.",
        excluded_company_count,
        company_terms,
    )

    LOGGER.info("Applying applicant count filter.")
    unique_jobs, excluded_applicant_count = filter_applicant_count(
        settings, unique_jobs
    )
    if settings.max_applicants > 0:
        LOGGER.info(
            "Removed %s job(s) with more than %s applicant(s).",
            excluded_applicant_count,
            settings.max_applicants,
        )
    else:
        LOGGER.info("Applicant count filter disabled.")

    if filter_to_previous_run_window:
        LOGGER.info("Filtering jobs to the exact historical posted window.")
        unique_jobs, outside_window_count, unknown_posted_count = (
            filter_jobs_to_previous_run_window(
                settings,
                unique_jobs,
                google_context.previous_run_started_at,
            )
        )
        LOGGER.info(
            "Removed %s job(s) outside the historical posted window.",
            outside_window_count,
        )
        if unknown_posted_count:
            LOGGER.info(
                "Kept %s job(s) with no parseable posted timestamp.",
                unknown_posted_count,
            )
    else:
        outside_window_count = 0
        unknown_posted_count = 0

    if google_context.historical_job_keys:
        LOGGER.info("Removing jobs already present in previous Google Sheet tabs.")
        unique_jobs, historical_duplicate_count = remove_jobs_seen_in_history(
            settings,
            unique_jobs,
            google_context.historical_job_keys,
        )
        LOGGER.info(
            "Removed %s duplicate job(s) already present in the spreadsheet.",
            historical_duplicate_count,
        )
    else:
        historical_duplicate_count = 0

    LOGGER.info("Sorting results.")
    unique_jobs.sort(key=lambda job: sort_key(settings, job), reverse=True)

    outputs = []
    if "excel" in output_modes:
        LOGGER.info("Saving local Excel file %s.", settings.excel_output_file.name)
        outputs.append(
            (
                "Excel file",
                export_to_excel(settings, unique_jobs, settings.excel_output_file),
            )
        )

    if "google_sheets" in output_modes:
        LOGGER.info("Creating Google Sheet tab.")
        spreadsheet_url = export_to_google_sheets(
            settings,
            google_sheets_service,
            unique_jobs,
        )
        outputs.append(("Google Sheet", spreadsheet_url))

    runtime_seconds = time.perf_counter() - run_started
    LOGGER.info(
        "Searched %s search URL(s); found %s unique job posting(s).",
        len(searches),
        len(unique_jobs),
    )
    LOGGER.info("Total runtime: %s.", format_duration(runtime_seconds))
    if excluded_title_count:
        LOGGER.info("Excluded by title rule: %s.", excluded_title_count)
    if excluded_company_count:
        LOGGER.info("Excluded by company rule: %s.", excluded_company_count)
    if excluded_applicant_count:
        LOGGER.info("Excluded by applicant count: %s.", excluded_applicant_count)
    if outside_window_count:
        LOGGER.info("Excluded by historical posted window: %s.", outside_window_count)
    if historical_duplicate_count:
        LOGGER.info(
            "Excluded because already present in Google Sheets: %s.",
            historical_duplicate_count,
        )
    if zero_searches:
        LOGGER.info("Searches with 0 results: %s.", len(zero_searches))
        for label in zero_searches:
            LOGGER.info("No results: %s.", label)
    if failed_sources:
        LOGGER.warning("Failed source(s): %s.", len(failed_sources))
        for source, message in failed_sources.items():
            LOGGER.warning("%s: %s.", source_label(source), message[:180])
    if skipped_searches:
        LOGGER.warning(
            "Skipped searches after source failure: %s.",
            len(skipped_searches),
        )
    for label, destination in outputs:
        LOGGER.info("%s: %s.", label, destination)

    return ScrapeResult(
        output_destinations=outputs,
        search_count=len(searches),
        unique_job_count=len(unique_jobs),
        runtime_seconds=runtime_seconds,
        zero_searches=zero_searches,
        failed_sources=failed_sources,
        skipped_searches=skipped_searches,
        excluded_title_count=excluded_title_count,
        excluded_company_count=excluded_company_count,
        excluded_applicant_count=excluded_applicant_count,
        outside_window_count=outside_window_count,
        unknown_posted_count=unknown_posted_count,
        historical_duplicate_count=historical_duplicate_count,
    )
