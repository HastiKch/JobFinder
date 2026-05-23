"""Xing provider integration for ``shahidirfan/Xing-Jobs-Scraper``."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlparse

from jobfinder.providers import normalization as provider_normalization
from jobfinder.providers.apify_client import run_actor
from jobfinder.scraper.settings import ScraperSettings

XING_BASE_URL = "https://www.xing.com"
XING_JOB_ID_RE = re.compile(r"/jobs/[^/?#]*-(?P<id>\d+)(?:[/?#]|$)")
XingActorRunner = Callable[
    [ScraperSettings, str, dict[str, Any], int],
    list[dict[str, Any]],
]
XING_RESULT_RUNNER = XingActorRunner
"""Backward-compatible alias for the Xing actor runner type."""

REMOTE_WORDS = ("remote", "home office", "home-office", "work from home")
HYBRID_WORDS = ("hybrid", "teilweise remote")
ONSITE_WORDS = ("onsite", "on-site", "vor ort", "praesenz", "präsenz")


@dataclass(frozen=True)
class XingActorInput:
    """Typed input for the Xing Apify actor."""

    keyword: str
    location: str
    discipline: str
    remote: str
    start_url: str
    results_wanted: int
    max_pages: int
    use_apify_proxy: bool
    proxy_groups: tuple[str, ...]

    def as_payload(self) -> dict[str, Any]:
        """Return the JSON payload accepted by the Apify actor."""
        payload: dict[str, Any] = {
            "results_wanted": self.results_wanted,
            "max_pages": self.max_pages,
            "proxyConfiguration": {"useApifyProxy": self.use_apify_proxy},
        }

        if self.proxy_groups:
            payload["proxyConfiguration"]["apifyProxyGroups"] = list(self.proxy_groups)

        if self.start_url:
            payload["startUrl"] = self.start_url
            return payload

        if self.keyword:
            payload["keyword"] = self.keyword
        if self.location:
            payload["location"] = self.location
        if self.discipline:
            payload["discipline"] = self.discipline
        if self.remote:
            payload["remote"] = self.remote
        return payload


@dataclass(frozen=True)
class XingMetadata:
    """Structured Xing metadata kept inside the normalized job dict."""

    salary: str = ""
    work_mode: str = ""
    discipline: str = ""
    job_category: str = ""
    keywords: tuple[str, ...] = ()
    matching_facts: tuple[str, ...] = ()
    company_size: str = ""
    company_industry: str = ""
    language: str = ""
    application_type: str = ""
    active_until: str = ""
    company_public_profile: str = ""
    paid: bool = False
    top_job: bool = False
    redirects_to_third_party: bool = False
    detail_error: str = ""

    def as_dict(self) -> dict[str, Any]:
        """Return only populated metadata values."""
        return provider_normalization.populated_metadata_dict(self)

    def description_lines(self) -> list[str]:
        """Return concise metadata lines that help AI evaluation."""
        lines: list[str] = []
        scalar_fields = (
            ("Salary", self.salary),
            ("Work mode", self.work_mode),
            ("Discipline", self.discipline),
            ("Category", self.job_category),
            ("Company size", self.company_size),
            ("Company industry", self.company_industry),
            ("Language", self.language),
            ("Application method", self.application_type),
            ("Active until", self.active_until),
        )
        for label, value in scalar_fields:
            if value:
                lines.append(f"{label}: {value}")

        if self.keywords:
            lines.append(f"Keywords: {', '.join(self.keywords)}")
        if self.matching_facts:
            lines.append(f"Matching facts: {', '.join(self.matching_facts)}")

        flags = []
        if self.paid:
            flags.append("Paid listing")
        if self.top_job:
            flags.append("Top job")
        if self.redirects_to_third_party:
            flags.append("Redirects to third party")
        if flags:
            lines.append(f"Listing flags: {', '.join(flags)}")
        if self.detail_error:
            lines.append(f"Detail error: {self.detail_error}")
        return lines


def build_actor_input(settings: ScraperSettings, keyword: str) -> dict[str, Any]:
    """Build the Apify actor payload for one Xing keyword search."""
    actor_input = XingActorInput(
        keyword=keyword,
        location=settings.xing_location,
        discipline=settings.xing_discipline,
        remote=settings.xing_remote,
        start_url=settings.xing_start_url,
        results_wanted=settings.xing_max_results_per_search,
        max_pages=settings.xing_max_pages,
        use_apify_proxy=settings.xing_use_apify_proxy,
        proxy_groups=tuple(settings.xing_proxy_groups),
    )
    return actor_input.as_payload()


def build_direct_actor_input(settings: ScraperSettings) -> dict[str, Any]:
    """Build a single actor payload for a configured Xing search URL."""
    return build_actor_input(settings, "")


def run_actor_search(
    settings: ScraperSettings,
    actor_id: str,
    payload: dict[str, Any],
    max_items: int,
    *,
    actor_runner: XingActorRunner = run_actor,
) -> list[dict[str, Any]]:
    """Run the Xing actor and normalize actor-specific output."""
    items = actor_runner(settings, actor_id, payload, max_items)
    return normalize_actor_output(items)


def normalize_actor_output(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize all actor items into the scraper's stable raw-job contract."""
    return [normalize_actor_item(item) for item in items if isinstance(item, dict)]


def normalize_actor_item(item: dict[str, Any]) -> dict[str, Any]:
    """Normalize one actor result into fields consumed by the shared pipeline."""
    metadata = build_metadata(item)
    job_id = xing_job_key(item)
    job_url = absolute_xing_url(first_text(item, "url"))
    description = description_with_metadata(item, metadata)

    normalized = {
        "jobId": job_id,
        "job_id": job_id,
        "id": job_id,
        "xingId": job_id,
        "slug": first_text(item, "slug"),
        "globalId": first_text(item, "global_id", "globalId"),
        "title": first_text(item, "title"),
        "companyName": first_text(item, "company"),
        "companyDetails": company_details(item),
        "location": format_location(item),
        "jobType": first_text(item, "job_type", "employment_type"),
        "employmentType": first_text(item, "job_type", "employment_type"),
        "description": description,
        "descriptionText": description,
        "descriptionHtml": first_text(item, "description_html"),
        "postedAt": first_text(item, "date_posted", "activated_at"),
        "datePosted": first_text(item, "date_posted"),
        "activatedAt": first_text(item, "activated_at"),
        "activeUntil": first_text(item, "active_until"),
        "jobUrl": job_url,
        "url": job_url,
        "applyUrl": absolute_xing_url(first_text(item, "apply_url")),
        "applyEmail": first_text(item, "apply_email"),
        "_jobfinder_xing_metadata": metadata.as_dict(),
    }

    return {
        key: value
        for key, value in normalized.items()
        if value not in ("", None, {}, [])
    }


def xing_job_key(item: dict[str, Any]) -> str:
    """Return the most stable Xing-native job identifier."""
    job_id = first_text(item, "job_id", "jobId", "id", "global_id", "globalId")
    if job_id:
        return job_id

    slug = first_text(item, "slug")
    if slug:
        return slug

    url = first_text(item, "url")
    parsed = urlparse(url)
    match = XING_JOB_ID_RE.search(parsed.path)
    return match.group("id") if match else ""


def absolute_xing_url(value: str) -> str:
    """Return an absolute Xing URL from relative actor output."""
    if not value:
        return ""
    if value.startswith(("http://", "https://")):
        return value
    return urljoin(XING_BASE_URL, value)


def first_text(item: dict[str, Any], *keys: str, strip_html: bool = False) -> str:
    """Return the first non-empty scalar value for the given keys."""
    return provider_normalization.first_text(item, *keys, strip_html=strip_html)


def values_from_shape(value: Any) -> list[str]:
    """Flatten actor dict/list/string metadata shapes into human labels."""
    return provider_normalization.values_from_shape(
        value,
        strip_html=True,
        prefer_label_keys=("label", "name", "title", "value", "text"),
    )


def format_location(item: dict[str, Any]) -> str:
    """Return a concise Xing location string."""
    parts = [
        first_text(item, "location"),
        first_text(item, "location_region"),
        first_text(item, "location_country"),
    ]
    return ", ".join(provider_normalization.unique([part for part in parts if part]))


def company_details(item: dict[str, Any]) -> dict[str, Any]:
    """Map Xing company fields without leaking source-specific names."""
    details: dict[str, Any] = {}
    for source_key, target_key in (
        ("company", "name"),
        ("company_id", "id"),
        ("company_logo", "logoUrl"),
        ("company_size", "size"),
        ("company_industry", "industry"),
        ("company_city", "city"),
        ("company_country", "country"),
        ("company_public_profile", "url"),
    ):
        value = item.get(source_key)
        if value not in (None, "", [], {}):
            details[target_key] = value
    return details


def build_metadata(item: dict[str, Any]) -> XingMetadata:
    """Extract richer Xing metadata useful to evaluation and future filtering."""
    return XingMetadata(
        salary=first_text(item, "salary"),
        work_mode=classify_work_mode(item),
        discipline=first_text(item, "discipline"),
        job_category=first_text(item, "job_category"),
        keywords=provider_normalization.unique(
            values_from_shape(item.get("keywords")),
            limit=20,
        ),
        matching_facts=provider_normalization.unique(
            values_from_shape(item.get("matching_facts")),
            limit=12,
        ),
        company_size=first_text(item, "company_size"),
        company_industry=first_text(item, "company_industry"),
        language=first_text(item, "language"),
        application_type=first_text(item, "application_type"),
        active_until=first_text(item, "active_until"),
        company_public_profile=first_text(item, "company_public_profile"),
        paid=bool(item.get("paid")),
        top_job=bool(item.get("top_job")),
        redirects_to_third_party=bool(item.get("redirects_to_third_party")),
        detail_error=first_text(item, "detail_error"),
    )


def classify_work_mode(item: dict[str, Any]) -> str:
    """Classify Xing remote/hybrid/on-site hints conservatively."""
    explicit = first_text(item, "remote")
    text = " ".join(
        [
            explicit,
            first_text(item, "title"),
            first_text(item, "location"),
            first_text(item, "description_text"),
            first_text(item, "description_html", strip_html=True),
            *values_from_shape(item.get("matching_facts")),
            *values_from_shape(item.get("non_matching_facts")),
        ]
    ).casefold()
    if any(word in text for word in HYBRID_WORDS):
        return "Hybrid"
    if any(word in text for word in REMOTE_WORDS):
        return "Remote"
    if any(word in text for word in ONSITE_WORDS):
        return "On-site"
    return explicit


def description_with_metadata(
    item: dict[str, Any],
    metadata: XingMetadata,
) -> str:
    """Append concise structured Xing metadata to the base description."""
    description = first_text(item, "description_text") or first_text(
        item,
        "description_html",
        strip_html=True,
    )
    return provider_normalization.append_metadata_block(
        description,
        "Xing",
        metadata.description_lines(),
    )
