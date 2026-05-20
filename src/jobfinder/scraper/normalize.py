"""Normalize raw job dictionaries into stable spreadsheet values."""

from __future__ import annotations

import html
import json
import re
from datetime import UTC, datetime
from typing import Any

from jobfinder.dedupe.matching import deduplicate_search_results
from jobfinder.scraper.search import indeed_base_url
from jobfinder.scraper.settings import ScraperSettings

APPLICANT_COUNT_KEYS = (
    "applicantsCount",
    "applicants_count",
    "applicantCount",
    "applicant_count",
    "numberOfApplicants",
    "number_of_applicants",
    "numApplicants",
    "num_applicants",
    "formattedApplicantsCount",
    "applicantsLabel",
    "applicants",
)
DESCRIPTION_KEYS = (
    "descriptionText",
    "description_text",
    "jobDescriptionText",
    "job_description_text",
    "descriptionPlainText",
    "description_plain_text",
    "jobDescriptionPlainText",
    "job_description_plain_text",
    "aboutTheJob",
    "about_the_job",
    "jobDescription",
    "job_description",
    "description",
    "descriptionHtml",
    "description_html",
    "jobDescriptionHtml",
    "job_description_html",
    "jobDetails",
    "job_details",
    "details",
    "summary",
    "snippet",
)
POSTED_KEYS = (
    "postedAt",
    "posted_at",
    "publishedAt",
    "published_at",
    "datePublished",
    "date_published",
    "dateOnIndeed",
    "date_on_indeed",
    "datePosted",
    "date_posted",
    "posted",
    "listedAt",
    "listed_at",
)

APPLICANT_NUMBER_RE = re.compile(
    r"(?P<number>\d[\d,.]*)\s*(?P<unit>k)?\s*(?P<plus>\+)?",
    re.IGNORECASE,
)
HTML_BREAK_RE = re.compile(r"<\s*br\s*/?\s*>", re.IGNORECASE)
HTML_BLOCK_END_RE = re.compile(
    r"</\s*(p|div|li|ul|ol|h[1-6]|tr|section|article)\s*>",
    re.IGNORECASE,
)
HTML_LIST_ITEM_RE = re.compile(r"<\s*li[^>]*>", re.IGNORECASE)
HTML_TAG_RE = re.compile(r"<[^>]+>")
MAX_CELL_CHARS = 49_000


def sheet_safe(value: Any) -> str:
    """Convert a value to a spreadsheet-safe string."""
    if value is None or value == "":
        return "N/A"
    if isinstance(value, list):
        text = ", ".join(
            str(item) for item in value if item is not None and str(item).strip()
        )
    elif isinstance(value, dict):
        text = json.dumps(value, ensure_ascii=False)
    else:
        text = str(value)

    text = text.strip()
    if not text:
        return "N/A"
    if len(text) > MAX_CELL_CHARS:
        return text[: MAX_CELL_CHARS - 20] + " ... [truncated]"
    if text[0] in "=+-@":
        return "'" + text
    return text


def field(job: dict[str, Any], *keys: str) -> str:
    """Return the first non-empty spreadsheet-safe field from a job dict."""
    for key in keys:
        value = job.get(key)
        if value is not None and sheet_safe(value) != "N/A":
            return sheet_safe(value)
    return "N/A"


def safe(job: dict[str, Any], *keys: str) -> str:
    """Try multiple key names and return the first non-empty raw value."""
    for key in keys:
        value = job.get(key)
        if value and str(value).strip():
            return str(value).strip()
    return "N/A"


def nested(job: dict[str, Any], *keys: str) -> str:
    """Read a nested dictionary value and return it in spreadsheet-safe form."""
    value: Any = job
    for key in keys:
        if not isinstance(value, dict):
            return "N/A"
        value = value.get(key)
    if value is None or value == "":
        return "N/A"
    return sheet_safe(value)


def first_value(*values: str) -> str:
    """Return the first meaningful value from a list of normalized strings."""
    for value in values:
        if value and value != "N/A":
            return value
    return "N/A"


def get_source_label(job: dict[str, Any]) -> str:
    """Return the display source label for a job."""
    return safe(job, "_source_label")


def get_title(job: dict[str, Any]) -> str:
    """Return a normalized job title."""
    return safe(job, "title", "positionName", "jobTitle", "job_title", "name")


def get_company(job: dict[str, Any]) -> str:
    """Return a normalized company name."""
    company = field(job, "companyName", "company", "organization", "jobSourceName")
    employer = nested(job, "employer", "name")
    if "companyDetails" not in job:
        return first_value(employer, company)
    return first_value(nested(job, "companyDetails", "name"), employer, company)


def get_location(job: dict[str, Any]) -> str:
    """Return a normalized job location."""
    if isinstance(job.get("location"), dict):
        return first_value(
            nested(job, "location", "formatted", "long"),
            nested(job, "location", "formatted"),
            nested(job, "location", "fullAddress"),
            nested(job, "location", "city"),
            ", ".join(
                part
                for part in (
                    nested(job, "location", "admin1Code"),
                    nested(job, "location", "countryName"),
                )
                if part != "N/A"
            ),
        )
    return field(job, "location", "formattedLocation", "jobLocation", "place")


def get_job_url(settings: ScraperSettings, job: dict[str, Any]) -> str:
    """Return the best available public job URL."""
    if job.get("_source") in {"indeed", "stepstone"}:
        url = (
            job.get("url")
            or job.get("link")
            or job.get("jobUrl")
            or job.get("job_url")
            or ""
        )
    else:
        url = (
            job.get("jobUrl")
            or job.get("job_url")
            or job.get("linkedinUrl")
            or job.get("linkedin_url")
            or job.get("url")
            or job.get("link")
            or ""
        )
    if url:
        return str(url)

    view_job_link = job.get("viewJobLink") or ""
    if view_job_link:
        if str(view_job_link).startswith("http"):
            return str(view_job_link)
        return f"{indeed_base_url(settings)}{view_job_link}"

    job_id = job.get("jobId") or job.get("job_id") or job.get("id") or ""
    if job_id:
        if job.get("_source") == "indeed":
            return f"{indeed_base_url(settings)}/viewjob?jk={job_id}"
        if job.get("_source") == "linkedin":
            return f"https://www.linkedin.com/jobs/view/{job_id}/"
    return "N/A"


def get_posted(settings: ScraperSettings, job: dict[str, Any]) -> str:
    """Return the posted timestamp as a formatted local string when possible."""
    fallback = ""
    for key in POSTED_KEYS:
        value = job.get(key)
        if value and str(value).strip():
            posted_at = parse_datetime_value(settings, value)
            if posted_at:
                return format_posted_datetime(posted_at)
            if not fallback:
                fallback = sheet_safe(value)

    pub_date = job.get("pubDate")
    posted_at = parse_datetime_value(settings, pub_date)
    if posted_at:
        return format_posted_datetime(posted_at)
    if fallback:
        return fallback
    return format_posted_value(settings, pub_date)


def get_posted_datetime(
    settings: ScraperSettings, job: dict[str, Any]
) -> datetime | None:
    """Return a parsed posted timestamp when the raw job includes one."""
    for key in POSTED_KEYS:
        value = job.get(key)
        if value and str(value).strip():
            posted_at = parse_datetime_value(settings, value)
            if posted_at:
                return posted_at
    return parse_datetime_value(settings, job.get("pubDate"))


def get_job_type(job: dict[str, Any]) -> str:
    """Return the normalized employment type."""
    return field(
        job,
        "employmentType",
        "employment_type",
        "jobType",
        "job_type",
        "contractType",
        "contract_type",
        "type",
        "jobTypes",
    )


def get_job_description(job: dict[str, Any]) -> str:
    """Return the best available plain-text job description."""
    for key in DESCRIPTION_KEYS:
        if key not in job:
            continue
        description = clean_job_description(job.get(key))
        if description != "N/A":
            return description
    return "N/A"


def clean_job_description(value: Any) -> str:
    """Normalize HTML, nested, and list description values into text."""
    if value in (None, "", "N/A"):
        return "N/A"

    if isinstance(value, dict):
        for key in (*DESCRIPTION_KEYS, "text", "html", "content", "value"):
            if key not in value:
                continue
            description = clean_job_description(value.get(key))
            if description != "N/A":
                return description
        return sheet_safe(value)

    if isinstance(value, list):
        parts = [
            description
            for item in value
            if (description := clean_job_description(item)) != "N/A"
        ]
        return sheet_safe("\n".join(parts)) if parts else "N/A"

    text = str(value).strip()
    if not text:
        return "N/A"

    text = HTML_BREAK_RE.sub("\n", text)
    text = HTML_LIST_ITEM_RE.sub("\n* ", text)
    text = HTML_BLOCK_END_RE.sub("\n", text)
    text = HTML_TAG_RE.sub(" ", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{2,}", "\n", text).strip()

    return sheet_safe(text)


def get_apply_url(job: dict[str, Any]) -> str:
    """Return the best available application URL."""
    return field(
        job,
        "applyUrl",
        "apply_url",
        "originalApplyUrl",
        "thirdPartyApplyUrl",
        "externalApplyLink",
    )


def get_applicants(job: dict[str, Any]) -> str:
    """Return the applicant-count text visible in a raw job."""
    return field(job, *APPLICANT_COUNT_KEYS)


def parse_applicant_number(number_text: str, unit: str | None) -> int | None:
    """Parse one numeric applicant-count match."""
    if unit:
        normalized = number_text.replace(",", ".")
        try:
            return int(float(normalized) * 1000)
        except ValueError:
            return None

    normalized = re.sub(r"[,.]", "", number_text)
    try:
        return int(normalized)
    except ValueError:
        return None


def parse_applicant_count_value(value: Any) -> int | None:
    """Parse an applicant count from common actor output shapes."""
    if value in (None, "", "N/A"):
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return int(value) if value >= 0 else None
    if isinstance(value, dict):
        dict_counts: list[int] = []
        for key in (*APPLICANT_COUNT_KEYS, "count", "value", "text", "label"):
            if key not in value:
                continue
            count = parse_applicant_count_value(value[key])
            if count is not None:
                dict_counts.append(count)
        return max(dict_counts) if dict_counts else None
    if isinstance(value, list):
        list_counts: list[int] = []
        for item in value:
            count = parse_applicant_count_value(item)
            if count is not None:
                list_counts.append(count)
        return max(list_counts) if list_counts else None

    text = str(value).strip()
    if not text or text == "N/A":
        return None

    text_counts: list[int] = []
    for match in APPLICANT_NUMBER_RE.finditer(text):
        count = parse_applicant_number(match.group("number"), match.group("unit"))
        if count is None:
            continue

        prefix = text[max(0, match.start() - 20) : match.start()].casefold()
        if (
            match.group("plus")
            or "over" in prefix
            or "more than" in prefix
            or ">" in prefix
        ):
            count += 1

        text_counts.append(count)

    return max(text_counts) if text_counts else None


def get_applicant_count(job: dict[str, Any]) -> int | None:
    """Return the parsed applicant count from a job when available."""
    for key in APPLICANT_COUNT_KEYS:
        if key not in job:
            continue
        applicant_count = parse_applicant_count_value(job.get(key))
        if applicant_count is not None:
            return applicant_count
    return None


def parse_datetime_value(settings: ScraperSettings, value: Any) -> datetime | None:
    """Parse timestamps and ISO strings into the configured posted timezone."""
    if value in (None, ""):
        return None
    try:
        timestamp = float(value)
    except (TypeError, ValueError):
        timestamp = None

    if timestamp is not None:
        if timestamp > 10_000_000_000:
            timestamp = timestamp / 1000
        return datetime.fromtimestamp(timestamp, UTC).astimezone(settings.posted_tz)

    text = str(value).strip()
    if not text or text == "N/A":
        return None

    iso_text = text
    if iso_text.endswith("Z"):
        iso_text = iso_text[:-1] + "+00:00"

    try:
        parsed = datetime.fromisoformat(iso_text)
    except ValueError:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=settings.posted_tz)
    return parsed.astimezone(settings.posted_tz)


def format_posted_datetime(posted_at: datetime) -> str:
    """Format a posted datetime for spreadsheet output."""
    return posted_at.strftime("%Y-%m-%d %H:%M:%S")


def format_posted_value(settings: ScraperSettings, value: Any) -> str:
    """Format a raw posted value, parsing it first when possible."""
    posted_at = parse_datetime_value(settings, value)
    if posted_at:
        return format_posted_datetime(posted_at)
    return sheet_safe(value)


def make_dedup_key(job: dict[str, Any]) -> str:
    """Build a stable deduplication key for a normalized job."""
    source = str(job.get("_source") or "unknown").lower().strip()
    job_id = (
        job.get("jobId")
        or job.get("job_id")
        or job.get("indeedKey")
        or job.get("stepstoneId")
        or job.get("harmonisedId")
        or job.get("key")
        or job.get("jobKey")
        or job.get("id")
        or ""
    )
    if job_id:
        return f"{source}|{str(job_id).strip()}"

    title = get_title(job).lower().strip()
    company = get_company(job).lower().strip()
    location = get_location(job).lower().strip()
    return f"{source}|{title}|{company}|{location}"


def merge_and_deduplicate(
    all_results: list[tuple[str, list[dict[str, Any]]]],
) -> list[dict[str, Any]]:
    """Merge search results with the production cross-provider dedupe pipeline."""
    return deduplicate_search_results(all_results).jobs
