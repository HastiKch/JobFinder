"""Stepstone provider integration for ``memo23/stepstone-search-cheerio-ppr``."""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urljoin

from jobfinder.providers import normalization as provider_normalization
from jobfinder.providers.apify_client import run_actor
from jobfinder.scraper.settings import ScraperSettings

STEPSTONE_BASE_URL = "https://www.stepstone.de"
STEPSTONE_POSTED_WITHIN_DAYS = (1, 3, 7)
STEPSTONE_RESULT_RUNNER = Callable[
    [ScraperSettings, str, dict[str, Any], int],
    list[dict[str, Any]],
]
WHITESPACE_RE = re.compile(r"\s+")
JOB_TYPE_WORDS = (
    "full-time",
    "part-time",
    "teilzeit",
    "vollzeit",
    "contract",
    "permanent",
    "internship",
    "praktikum",
    "freelance",
)
REMOTE_WORDS = ("remote", "home office", "home-office", "work from home")
HYBRID_WORDS = ("hybrid", "teilweise remote")
ONSITE_WORDS = ("onsite", "on-site", "vor ort", "praesenz", "präsenz")
unique = provider_normalization.unique


@dataclass(frozen=True)
class StepstoneActorInput:
    """Typed input for the Stepstone Apify actor."""

    keyword: str
    location: str
    category: str
    start_urls: tuple[str, ...]
    posted_within: str
    max_items: int
    max_concurrency: int
    min_concurrency: int
    max_request_retries: int
    use_apify_proxy: bool
    proxy_groups: tuple[str, ...]

    def as_payload(self) -> dict[str, Any]:
        """Return the JSON payload accepted by the Apify actor."""
        payload: dict[str, Any] = {
            "maxItems": self.max_items,
            "maxConcurrency": self.max_concurrency,
            "minConcurrency": min(self.min_concurrency, self.max_concurrency),
            "maxRequestRetries": self.max_request_retries,
            "proxy": {"useApifyProxy": self.use_apify_proxy},
        }

        if self.proxy_groups:
            payload["proxy"]["apifyProxyGroups"] = list(self.proxy_groups)

        if self.start_urls:
            payload["startUrls"] = [{"url": url} for url in self.start_urls]
            return payload

        if self.keyword:
            payload["keyword"] = self.keyword
            if self.location:
                payload["location"] = self.location
            if self.posted_within != "all":
                payload["postedWithin"] = self.posted_within
            return payload

        if self.category:
            payload["category"] = self.category

        if self.posted_within != "all":
            payload["postedWithin"] = self.posted_within
        return payload


@dataclass(frozen=True)
class StepstoneMetadata:
    """Structured Stepstone metadata kept inside the normalized job dict."""

    salary: str = ""
    work_mode: str = ""
    labels: tuple[str, ...] = ()
    skills: tuple[str, ...] = ()
    category: str = ""
    company_id: str = ""
    company_url: str = ""
    is_sponsored: bool = False
    is_highlighted: bool = False
    is_top_job: bool = False
    is_partnership_job: bool = False

    def as_dict(self) -> dict[str, Any]:
        """Return only populated metadata values."""
        values: dict[str, Any] = {}
        for key, value in self.__dict__.items():
            if value:
                values[key] = list(value) if isinstance(value, tuple) else value
        return values

    def description_lines(self) -> list[str]:
        """Return concise metadata lines that help AI evaluation."""
        lines: list[str] = []
        if self.salary:
            lines.append(f"Salary: {self.salary}")
        if self.work_mode:
            lines.append(f"Work mode: {self.work_mode}")
        if self.skills:
            lines.append(f"Skills: {', '.join(self.skills)}")
        if self.category:
            lines.append(f"Category: {self.category}")
        if self.labels:
            lines.append(f"Labels: {', '.join(self.labels)}")
        return lines


def posted_within_filter(settings: ScraperSettings) -> str:
    """Map scraper posted windows to Stepstone's supported age facet."""
    seconds = seconds_from_published_at(settings.published_at)
    if seconds is None:
        return "all"

    days = max(1, math.ceil(seconds / 86_400))
    for supported_days in STEPSTONE_POSTED_WITHIN_DAYS:
        if days <= supported_days:
            return str(supported_days)
    return "all"


def seconds_from_published_at(value: str) -> int | None:
    """Parse LinkedIn-style ``rSECONDS`` windows used by scraper settings."""
    text = (value or "").strip().casefold()
    if not text.startswith("r"):
        return None
    try:
        seconds = int(text[1:])
    except ValueError:
        return None
    return seconds if seconds > 0 else None


def build_actor_input(settings: ScraperSettings, keyword: str) -> dict[str, Any]:
    """Build the Apify actor payload for one Stepstone search."""
    actor_input = StepstoneActorInput(
        keyword=slugify_segment(keyword) if not settings.stepstone_start_urls else "",
        location=slugify_segment(settings.stepstone_location),
        category=slugify_segment(settings.stepstone_category),
        start_urls=tuple(settings.stepstone_start_urls),
        posted_within=posted_within_filter(settings),
        max_items=settings.stepstone_max_results_per_search,
        max_concurrency=settings.stepstone_max_concurrency,
        min_concurrency=settings.stepstone_min_concurrency,
        max_request_retries=settings.stepstone_max_request_retries,
        use_apify_proxy=settings.stepstone_use_apify_proxy,
        proxy_groups=tuple(settings.stepstone_proxy_groups),
    )
    return actor_input.as_payload()


def build_direct_actor_input(settings: ScraperSettings) -> dict[str, Any]:
    """Build a single actor payload for configured Stepstone URLs."""
    return build_actor_input(settings, "")


def run_actor_search(
    settings: ScraperSettings,
    actor_id: str,
    payload: dict[str, Any],
    max_items: int,
    *,
    actor_runner: STEPSTONE_RESULT_RUNNER = run_actor,
) -> list[dict[str, Any]]:
    """Run the Stepstone actor and normalize actor-specific output."""
    items = actor_runner(settings, actor_id, payload, max_items)
    return normalize_actor_output(items)


def normalize_actor_output(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize all actor items into the scraper's stable raw-job contract."""
    return [normalize_actor_item(item) for item in items if isinstance(item, dict)]


def normalize_actor_item(item: dict[str, Any]) -> dict[str, Any]:
    """Normalize one actor result into fields consumed by the shared pipeline."""
    metadata = build_metadata(item)
    job_url = absolute_stepstone_url(first_text(item, "url", "jobUrl", "link"))
    company_url = absolute_stepstone_url(first_text(item, "companyUrl"))
    job_id = first_text(item, "id", "jobId", "job_id", "harmonisedId")
    description = description_with_metadata(item, metadata)

    normalized = {
        "jobId": job_id,
        "job_id": job_id,
        "id": job_id,
        "stepstoneId": job_id,
        "harmonisedId": first_text(item, "harmonisedId"),
        "title": first_text(item, "title", "jobTitle", "name"),
        "companyName": first_text(item, "companyName", "company"),
        "companyDetails": company_details(item, company_url),
        "location": first_text(item, "location", "formattedLocation"),
        "jobType": format_job_type(item),
        "employmentType": format_job_type(item),
        "description": description,
        "textSnippet": first_text(item, "textSnippet"),
        "postedAt": first_text(
            item,
            "datePosted",
            "publishFromDate",
            "periodPostedDate",
            "postedAt",
        ),
        "datePosted": first_text(item, "datePosted"),
        "jobUrl": job_url,
        "url": job_url,
        "applyUrl": absolute_stepstone_url(
            first_text(item, "applyUrl", "applicationUrl", "applicationLink")
        ),
        "_jobfinder_stepstone_metadata": metadata.as_dict(),
    }

    return {
        key: value
        for key, value in normalized.items()
        if value not in ("", None, {}, [])
    }


def slugify_segment(value: str) -> str:
    """Prepare a user setting for Stepstone URL path segments."""
    text = WHITESPACE_RE.sub("-", (value or "").strip().casefold())
    return quote(text, safe="-_")


def absolute_stepstone_url(value: str) -> str:
    """Return an absolute Stepstone URL from relative actor output."""
    if not value:
        return ""
    if value.startswith("http://") or value.startswith("https://"):
        return value
    return urljoin(STEPSTONE_BASE_URL, value)


def first_text(item: dict[str, Any], *keys: str) -> str:
    """Return the first non-empty scalar value for the given keys."""
    return provider_normalization.first_text(item, *keys, strip_html=True)


def clean_scalar_text(value: Any) -> str:
    """Normalize one scalar output value."""
    return provider_normalization.clean_scalar_text(value, strip_html=True)


def values_from_shape(value: Any) -> list[str]:
    """Flatten actor dict/list/string metadata shapes into human labels."""
    return provider_normalization.values_from_shape(
        value,
        strip_html=True,
        prefer_label_keys=("label", "name", "value"),
    )


def company_details(item: dict[str, Any], company_url: str) -> dict[str, Any]:
    """Map Stepstone employer fields without leaking source-specific names."""
    details: dict[str, Any] = {}
    for source_key, target_key in (
        ("companyName", "name"),
        ("companyId", "id"),
        ("companyLogoUrl", "logoUrl"),
        ("isAnonymous", "isAnonymous"),
    ):
        value = item.get(source_key)
        if value not in (None, "", [], {}):
            details[target_key] = value
    if company_url:
        details["url"] = company_url
    return details


def format_job_type(item: dict[str, Any]) -> str:
    """Return employment/job-type text when Stepstone exposes it."""
    explicit_values = unique(
        [
            *values_from_shape(item.get("employmentType")),
            *values_from_shape(item.get("jobType")),
            *values_from_shape(item.get("jobTypes")),
            *values_from_shape(item.get("contractType")),
        ]
    )
    if explicit_values:
        return ", ".join(explicit_values)

    text = " ".join(
        [
            first_text(item, "title"),
            first_text(item, "textSnippet"),
            *values_from_shape(item.get("labels")),
        ]
    ).casefold()
    matches = [word for word in JOB_TYPE_WORDS if word in text]
    return ", ".join(unique(matches))


def build_metadata(item: dict[str, Any]) -> StepstoneMetadata:
    """Extract richer Stepstone metadata useful to evaluation and future filtering."""
    partnership = item.get("partnership")
    partnership = partnership if isinstance(partnership, dict) else {}
    labels = unique(
        [
            *values_from_shape(item.get("labels")),
            *values_from_shape(item.get("topLabels")),
        ],
        limit=12,
    )
    skills = unique(values_from_shape(item.get("skills")), limit=16)
    company_url = absolute_stepstone_url(first_text(item, "companyUrl"))

    return StepstoneMetadata(
        salary=format_salary(item),
        work_mode=classify_work_mode(item),
        labels=labels,
        skills=skills,
        category=first_text(item, "category", "industry", "section"),
        company_id=first_text(item, "companyId"),
        company_url=company_url,
        is_sponsored=bool(item.get("isSponsored")),
        is_highlighted=bool(item.get("isHighlighted")),
        is_top_job=bool(item.get("isTopJob")),
        is_partnership_job=bool(partnership.get("isPartnershipJob")),
    )


def format_salary(item: dict[str, Any]) -> str:
    """Normalize Stepstone salary fields into compact display text."""
    salary = first_text(item, "salary")
    if salary:
        return salary

    unified = item.get("unifiedSalary")
    if not isinstance(unified, dict):
        return ""

    min_value = parse_salary_number(unified.get("min"))
    max_value = parse_salary_number(unified.get("max"))
    currency = first_text(unified, "currency")
    period = first_text(unified, "period")

    if min_value is not None and max_value is not None and min_value != max_value:
        amount = f"{format_money(min_value)}-{format_money(max_value)}"
    elif min_value is not None:
        amount = format_money(min_value)
    elif max_value is not None:
        amount = format_money(max_value)
    else:
        return ""

    prefix = f"{currency} " if currency else ""
    suffix = f" / {period}" if period else ""
    return f"{prefix}{amount}{suffix}"


def parse_salary_number(value: Any) -> float | None:
    """Parse numeric salary values from actor output."""
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        number = float(str(value).replace(",", "").strip())
    except ValueError:
        return None
    return number if number >= 0 else None


def format_money(value: float) -> str:
    """Format a salary number without unnecessary decimals."""
    if value.is_integer():
        return f"{int(value):,}"
    return f"{value:,.2f}".rstrip("0").rstrip(".")


def classify_work_mode(item: dict[str, Any]) -> str:
    """Classify Stepstone work-from-home hints conservatively."""
    values = [
        first_text(item, "workFromHome"),
        first_text(item, "location"),
        first_text(item, "title"),
        first_text(item, "textSnippet"),
        *values_from_shape(item.get("labels")),
    ]
    text = " ".join(values).casefold()
    if any(word in text for word in HYBRID_WORDS):
        return "Hybrid"
    if any(word in text for word in REMOTE_WORDS):
        return "Remote"
    if first_text(item, "workFromHome") not in {"", "0", "false", "False"}:
        return "Work from home available"
    if any(word in text for word in ONSITE_WORDS):
        return "On-site"
    return ""


def description_with_metadata(
    item: dict[str, Any],
    metadata: StepstoneMetadata,
) -> str:
    """Append concise structured Stepstone metadata to the base description."""
    description = first_text(
        item,
        "description",
        "jobDescription",
        "details",
        "textSnippet",
        "summary",
    )
    metadata_lines = metadata.description_lines()
    if not metadata_lines:
        return description

    metadata_block = "\n".join(f"- {line}" for line in metadata_lines)
    if description:
        return f"{description}\n\nStepstone structured metadata:\n{metadata_block}"
    return f"Stepstone structured metadata:\n{metadata_block}"
