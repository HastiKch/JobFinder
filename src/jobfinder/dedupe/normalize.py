"""Canonicalization helpers for deterministic job deduplication."""

from __future__ import annotations

import re
import unicodedata
from datetime import UTC, datetime
from typing import Any
from urllib.parse import (
    parse_qs,
    parse_qsl,
    quote,
    unquote,
    urlencode,
    urlsplit,
    urlunsplit,
)

from jobfinder.dedupe.models import NormalizedJob, Provenance, SalaryRange

MISSING_VALUES = {"", "n/a", "na", "none", "null", "open job", "open apply"}
KNOWN_SOURCE_LABELS = {
    "linkedin": "LinkedIn",
    "indeed": "Indeed",
    "stepstone": "Stepstone",
}
SOURCE_ALIASES = {
    "linked in": "linkedin",
    "linkedin": "linkedin",
    "indeed": "indeed",
    "stepstone": "stepstone",
    "stepstone de": "stepstone",
}
LEGAL_SUFFIXES = {
    "ab",
    "ag",
    "bv",
    "co",
    "company",
    "corp",
    "corporation",
    "gbr",
    "gmbh",
    "group",
    "holding",
    "holdings",
    "inc",
    "kg",
    "limited",
    "llc",
    "ltd",
    "mbh",
    "nv",
    "oy",
    "plc",
    "sarl",
    "se",
    "ug",
}
TITLE_NOISE_TOKENS = {
    "all",
    "contract",
    "d",
    "div",
    "f",
    "full",
    "fulltime",
    "gender",
    "genders",
    "gn",
    "home",
    "homeoffice",
    "hybrid",
    "job",
    "jobs",
    "m",
    "office",
    "onsite",
    "part",
    "parttime",
    "permanent",
    "remote",
    "site",
    "teilzeit",
    "time",
    "vollzeit",
    "w",
    "x",
}
LOCATION_COUNTRY_TOKENS = {"de", "deu", "deutschland", "germany"}
LOCATION_NOISE_TOKENS = {
    "home",
    "homeoffice",
    "hybrid",
    "office",
    "on",
    "onsite",
    "remote",
    "site",
    "work",
}
LOCATION_ALIASES = {
    "cologne": "koln",
    "koeln": "koln",
    "köln": "koln",
    "munich": "munchen",
    "muenchen": "munchen",
    "münchen": "munchen",
    "nuremberg": "nurnberg",
    "nuernberg": "nurnberg",
    "nürnberg": "nurnberg",
}
JOB_TYPE_PHRASES = {
    "full time": "fulltime",
    "full-time": "fulltime",
    "vollzeit": "fulltime",
    "part time": "parttime",
    "part-time": "parttime",
    "teilzeit": "parttime",
    "internship": "internship",
    "praktikum": "internship",
    "contract": "contract",
    "contractor": "contract",
    "freelance": "freelance",
    "permanent": "permanent",
}
REMOTE_WORDS = {"remote", "home office", "home-office", "homeoffice", "work from home"}
HYBRID_WORDS = {"hybrid", "teilweise remote"}
ONSITE_WORDS = {"onsite", "on-site", "vor ort", "praesenz", "präsenz"}
TRACKING_QUERY_PREFIXES = ("utm_",)
TRACKING_QUERY_KEYS = {
    "from",
    "ref",
    "refid",
    "rltr",
    "src",
    "trk",
    "trackingid",
}
TOKEN_RE = re.compile(r"[a-z0-9]+(?:[+#][a-z0-9]+)?")
HYPERLINK_RE = re.compile(
    r'^=HYPERLINK\("(?P<url>(?:[^"]|"")*)"\s*[,;]\s*"',
    re.IGNORECASE,
)
LINKEDIN_JOB_ID_RE = re.compile(r"/jobs/view/(?P<id>\d+)", re.IGNORECASE)
STEPSTONE_JOB_ID_RE = re.compile(
    r"--(?P<id>\d+)(?:-inline)?\.html",
    re.IGNORECASE,
)
SALARY_TEXT_KEYS = (
    "salary",
    "salaryText",
    "salary_text",
    "salarySnippet",
    "salary_snippet",
    "salaryRange",
    "salary_range",
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
    "pubDate",
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
    "jobDetails",
    "job_details",
    "details",
    "summary",
    "snippet",
)
JOB_ID_KEYS = (
    "jobId",
    "job_id",
    "indeedKey",
    "stepstoneId",
    "harmonisedId",
    "key",
    "jobKey",
    "id",
)


def is_meaningful(value: Any) -> bool:
    """Return true when a value carries usable data."""
    if value is None or isinstance(value, bool):
        return False
    if isinstance(value, dict | list):
        return bool(value)
    return normalize_space(str(value)).casefold() not in MISSING_VALUES


def normalize_space(value: str) -> str:
    """Collapse whitespace and trim."""
    return re.sub(r"\s+", " ", value).strip()


def ascii_fold(value: str) -> str:
    """Casefold and remove accents for stable comparisons."""
    folded = unicodedata.normalize("NFKD", value.casefold())
    return "".join(char for char in folded if not unicodedata.combining(char))


def token_list(value: str) -> list[str]:
    """Return normalized alphanumeric tokens."""
    return TOKEN_RE.findall(ascii_fold(value))


def unique_ordered(values: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    """Return non-empty values in first-seen order."""
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = normalize_space(str(value or ""))
        if not text or text.casefold() in MISSING_VALUES:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    return tuple(result)


def first_text(item: dict[str, Any], *keys: str) -> str:
    """Return the first meaningful scalar field as text."""
    for key in keys:
        value = item.get(key)
        if value is None or isinstance(value, bool | dict | list):
            continue
        text = normalize_space(str(value))
        if is_meaningful(text):
            return text
    return ""


def nested_text(item: dict[str, Any], *keys: str) -> str:
    """Return a nested scalar field as text."""
    value: Any = item
    for key in keys:
        if not isinstance(value, dict):
            return ""
        value = value.get(key)
    if value is None or isinstance(value, bool | dict | list):
        return ""
    text = normalize_space(str(value))
    return text if is_meaningful(text) else ""


def source_key(value: Any) -> str:
    """Normalize a provider/source label into a compact key."""
    text = ascii_fold(normalize_space(str(value or "")))
    text = re.sub(r"[^a-z0-9]+", " ", text).strip()
    return SOURCE_ALIASES.get(text, text.replace(" ", "_") or "unknown")


def source_label(value: Any) -> str:
    """Return a stable display label for a source value."""
    key = source_key(value)
    return KNOWN_SOURCE_LABELS.get(key, normalize_space(str(value or "")) or "Unknown")


def source_from_job(job: dict[str, Any]) -> str:
    """Extract the provider key from a raw job."""
    return source_key(
        job.get("_source")
        or job.get("source")
        or job.get("provider")
        or job.get("_source_label")
        or "unknown"
    )


def source_label_from_job(job: dict[str, Any]) -> str:
    """Extract the provider display label from a raw job."""
    explicit = first_text(job, "_source_label", "sourceLabel", "source_label")
    if explicit and "|" not in explicit:
        return source_label(explicit)
    return source_label(source_from_job(job))


def normalize_company(value: Any) -> str:
    """Normalize company names while preserving discriminative tokens."""
    tokens = token_list(str(value or ""))
    filtered = [token for token in tokens if token not in LEGAL_SUFFIXES]
    return " ".join(filtered or tokens)


def normalize_title(value: Any) -> str:
    """Normalize title variants such as gender tags and work-mode suffixes."""
    tokens = token_list(str(value or ""))
    filtered = [token for token in tokens if token not in TITLE_NOISE_TOKENS]
    return " ".join(filtered or tokens)


def remote_mode_from_text(value: Any) -> str:
    """Extract a deterministic remote/hybrid/onsite hint from text."""
    text = ascii_fold(str(value or ""))
    if any(word in text for word in HYBRID_WORDS):
        return "hybrid"
    if any(word in text for word in REMOTE_WORDS):
        return "remote"
    if any(word in text for word in ONSITE_WORDS):
        return "onsite"
    return ""


def normalize_location(value: Any) -> str:
    """Normalize common location formats without geocoding."""
    raw_tokens = token_list(str(value or ""))
    tokens = [
        LOCATION_ALIASES.get(token, token)
        for token in raw_tokens
        if token not in LOCATION_NOISE_TOKENS
    ]
    specific = [token for token in tokens if token not in LOCATION_COUNTRY_TOKENS]
    if specific:
        return " ".join(specific)
    if tokens:
        return " ".join(tokens)
    if remote_mode_from_text(value):
        return "remote"
    return ""


def normalize_job_type(value: Any) -> str:
    """Normalize employment type labels into stable comparable tokens."""
    if not is_meaningful(value):
        return ""
    text = ascii_fold(str(value or ""))
    normalized_tokens: list[str] = []
    for phrase, token in JOB_TYPE_PHRASES.items():
        if phrase in text:
            normalized_tokens.append(token)

    raw_tokens = token_list(text)
    for token in raw_tokens:
        if token in {"full", "time"} and "fulltime" in normalized_tokens:
            continue
        if token in {"part", "time"} and "parttime" in normalized_tokens:
            continue
        if token not in {"m", "f", "d", "w", "x", "all", "gender", "genders"}:
            normalized_tokens.append(JOB_TYPE_PHRASES.get(token, token))

    return " ".join(unique_ordered(normalized_tokens))


def extract_hyperlink_url(value: Any) -> str:
    """Extract a URL from a Sheets HYPERLINK formula or return the text URL."""
    if not isinstance(value, str):
        return ""
    text = value.strip()
    match = HYPERLINK_RE.match(text)
    if match:
        return match.group("url").replace('""', '"').strip()
    return text


def canonical_url(value: Any) -> str:
    """Return a canonical deterministic URL key."""
    url = extract_hyperlink_url(value)
    if not url or not is_meaningful(url):
        return ""
    parsed = urlsplit(url)
    if not parsed.scheme or not parsed.netloc:
        return ""

    host = parsed.netloc.casefold()
    if host.startswith("www."):
        host = host[4:]
    path = quote(unquote(parsed.path), safe="/:@")
    path = re.sub(r"/+", "/", path).rstrip("/")

    if "linkedin.com" in host:
        match = LINKEDIN_JOB_ID_RE.search(path)
        if match:
            return f"linkedin:job:{match.group('id')}"

    if "indeed." in host:
        job_keys = parse_qs(parsed.query).get("jk", [])
        if job_keys and job_keys[0]:
            return f"indeed:job:{job_keys[0].casefold()}"

    if "stepstone." in host:
        match = STEPSTONE_JOB_ID_RE.search(path)
        if match:
            return f"stepstone:job:{match.group('id')}"

    query_pairs = []
    for key, value_text in parse_qsl(parsed.query, keep_blank_values=False):
        key_lower = key.casefold()
        if key_lower in TRACKING_QUERY_KEYS:
            continue
        if any(key_lower.startswith(prefix) for prefix in TRACKING_QUERY_PREFIXES):
            continue
        query_pairs.append((key_lower, value_text))

    query = urlencode(sorted(query_pairs), doseq=True)
    return urlunsplit(("", host, path.casefold(), query, ""))


def is_platform_url_key(url_key: str) -> bool:
    """Return true for provider-owned public job URL keys."""
    return url_key.startswith(("linkedin:job:", "indeed:job:", "stepstone:job:"))


def canonical_external_apply_url(value: Any) -> str:
    """Return a strong cross-provider apply URL key when it is not a job-board URL."""
    key = canonical_url(value)
    if not key or is_platform_url_key(key):
        return ""
    if any(host in key for host in ("linkedin.com", "indeed.", "stepstone.")):
        return ""
    return key


def job_url_from_job(job: dict[str, Any], source: str) -> str:
    """Extract the public job URL using source-specific field priority."""
    if source in {"indeed", "stepstone"}:
        return first_text(job, "url", "link", "jobUrl", "job_url")
    return first_text(
        job,
        "jobUrl",
        "job_url",
        "linkedinUrl",
        "linkedin_url",
        "url",
        "link",
    )


def apply_url_from_job(job: dict[str, Any]) -> str:
    """Extract an application URL."""
    return first_text(
        job,
        "applyUrl",
        "apply_url",
        "originalApplyUrl",
        "thirdPartyApplyUrl",
        "externalApplyLink",
        "applicationUrl",
        "applicationLink",
    )


def company_url_from_job(job: dict[str, Any]) -> str:
    """Extract a company URL from top-level or nested metadata."""
    return (
        first_text(job, "companyUrl", "company_url")
        or nested_text(job, "companyDetails", "url")
        or nested_text(job, "employer", "url")
    )


def job_id_from_job(job: dict[str, Any], job_url_key: str = "") -> str:
    """Extract a provider-native job id from fields or URL keys."""
    job_id = first_text(job, *JOB_ID_KEYS)
    if job_id:
        return job_id
    if job_url_key.startswith(("linkedin:job:", "indeed:job:", "stepstone:job:")):
        return job_url_key.rsplit(":", 1)[-1]
    return ""


def parse_datetime_value(value: Any) -> datetime | None:
    """Parse common timestamp values for deterministic date proximity."""
    if value in (None, ""):
        return None
    try:
        timestamp = float(value)
    except (TypeError, ValueError):
        timestamp = None

    if timestamp is not None:
        if timestamp > 10_000_000_000:
            timestamp = timestamp / 1000
        return datetime.fromtimestamp(timestamp, UTC)

    text = str(value).strip()
    if not text or text.casefold() in MISSING_VALUES:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def posted_at_from_job(job: dict[str, Any]) -> datetime | None:
    """Return the first parseable posted timestamp."""
    for key in POSTED_KEYS:
        posted_at = parse_datetime_value(job.get(key))
        if posted_at:
            return posted_at
    return None


def description_from_job(job: dict[str, Any]) -> str:
    """Return a plain scalar description candidate."""
    for key in DESCRIPTION_KEYS:
        value = job.get(key)
        if value is None or isinstance(value, bool):
            continue
        if isinstance(value, dict | list):
            text = normalize_space(str(value))
        else:
            text = normalize_space(str(value))
        if is_meaningful(text):
            return text
    return ""


def salary_text_from_job(job: dict[str, Any]) -> str:
    """Collect salary text from raw and provider metadata fields."""
    candidates = [first_text(job, *SALARY_TEXT_KEYS)]
    for metadata_key in ("_jobfinder_indeed_metadata", "_jobfinder_stepstone_metadata"):
        metadata = job.get(metadata_key)
        if isinstance(metadata, dict):
            candidates.append(first_text(metadata, "salary"))
    return next((text for text in candidates if is_meaningful(text)), "")


def parse_salary_number(value: str) -> float | None:
    """Parse salary numbers with common US/EU thousand separators."""
    text = value.strip()
    if not text:
        return None
    multiplier = 1000 if text.casefold().endswith("k") else 1
    text = text[:-1] if multiplier == 1000 else text
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif re.search(r"[.,]\d{3}$", text):
        text = text.replace(".", "").replace(",", "")
    else:
        text = text.replace(",", ".")
    try:
        return float(text) * multiplier
    except ValueError:
        return None


def parse_salary(value: str) -> SalaryRange:
    """Parse a deterministic comparable salary range from text."""
    text = normalize_space(value)
    if not text:
        return SalaryRange()

    lowered = ascii_fold(text)
    currency = ""
    if "€" in text or "eur" in lowered:
        currency = "EUR"
    elif "$" in text or "usd" in lowered:
        currency = "USD"
    elif "£" in text or "gbp" in lowered:
        currency = "GBP"

    period = "year"
    if any(word in lowered for word in ("hour", "hourly", "stunde", "stunden")):
        period = "hour"
    elif any(word in lowered for word in ("month", "monthly", "monat")):
        period = "month"

    numbers = [
        parsed
        for match in re.finditer(r"\d+(?:[.,]\d+)?\s*k?", lowered)
        if (parsed := parse_salary_number(match.group(0).replace(" ", ""))) is not None
    ]
    plausible_numbers = [
        number
        for number in numbers
        if (
            (period == "hour" and 5 <= number <= 1000)
            or (period == "month" and 100 <= number <= 100_000)
            or (period == "year" and 1_000 <= number <= 1_000_000)
        )
    ]
    if not plausible_numbers:
        return SalaryRange(raw=text)

    return SalaryRange(
        minimum=min(plausible_numbers),
        maximum=max(plausible_numbers),
        currency=currency,
        period=period,
        raw=text,
    )


def title_signature(tokens: frozenset[str]) -> str:
    """Return a compact stable title signature for blocking."""
    useful = sorted(token for token in tokens if token not in TITLE_NOISE_TOKENS)
    return " ".join(useful[:4])


def build_blocking_keys(
    *,
    apply_url_key: str,
    normalized_company: str,
    normalized_title: str,
    normalized_location: str,
    normalized_job_type: str,
    title_tokens: frozenset[str],
    company_tokens: frozenset[str],
) -> frozenset[str]:
    """Build candidate lookup keys that avoid full pairwise comparisons."""
    keys: set[str] = set()
    if apply_url_key:
        keys.add(f"apply|{apply_url_key}")
    if normalized_company and normalized_title and normalized_location:
        keys.add(
            "profile|"
            f"{normalized_company}|{normalized_title}|"
            f"{normalized_location}|{normalized_job_type}"
        )
    if normalized_company and title_tokens:
        keys.add(f"company_title|{normalized_company}|{title_signature(title_tokens)}")
        for token in sorted(title_tokens)[:8]:
            keys.add(f"company_role|{normalized_company}|{token}")
    if company_tokens and normalized_title:
        company_signature = " ".join(sorted(company_tokens)[:3])
        keys.add(f"title_company|{normalized_title}|{company_signature}")
    return frozenset(keys)


def normalize_job(
    job: dict[str, Any],
    *,
    keyword: str = "",
    index: int = 0,
) -> NormalizedJob:
    """Build cached deterministic matching features for one raw scraped job."""
    source = source_from_job(job)
    label = source_label_from_job(job)
    title = first_text(job, "title", "positionName", "jobTitle", "job_title", "name")
    company = (
        nested_text(job, "companyDetails", "name")
        or nested_text(job, "employer", "name")
        or first_text(job, "companyName", "company", "organization", "jobSourceName")
    )
    location = first_text(job, "location", "formattedLocation", "jobLocation", "place")
    if not location and isinstance(job.get("location"), dict):
        location = (
            nested_text(job, "location", "formatted", "long")
            or nested_text(job, "location", "formatted")
            or nested_text(job, "location", "fullAddress")
            or nested_text(job, "location", "city")
        )
    job_url = job_url_from_job(job, source)
    job_url_key = canonical_url(job_url)
    apply_url = apply_url_from_job(job)
    apply_url_key = canonical_external_apply_url(apply_url)
    company_url = company_url_from_job(job)
    company_url_key = canonical_url(company_url)
    job_id = job_id_from_job(job, job_url_key)
    normalized_title = normalize_title(title)
    normalized_company = normalize_company(company)
    normalized_location = normalize_location(location)
    job_type = first_text(
        job,
        "employmentType",
        "employment_type",
        "jobType",
        "job_type",
        "contractType",
        "contract_type",
        "type",
    )
    normalized_job_type = normalize_job_type(job_type)
    title_tokens = frozenset(token_list(normalized_title))
    company_tokens = frozenset(token_list(normalized_company))
    location_tokens = frozenset(token_list(normalized_location))
    job_type_tokens = frozenset(token_list(normalized_job_type))
    keywords = unique_ordered(
        [
            *(str(value) for value in job.get("keywords_matched", []) or []),
            keyword,
        ]
    )
    salary = parse_salary(salary_text_from_job(job))
    remote_mode = remote_mode_from_text(
        " ".join([title, location, description_from_job(job)])
    )
    blocking_keys = build_blocking_keys(
        apply_url_key=apply_url_key,
        normalized_company=normalized_company,
        normalized_title=normalized_title,
        normalized_location=normalized_location,
        normalized_job_type=normalized_job_type,
        title_tokens=title_tokens,
        company_tokens=company_tokens,
    )

    provenance = Provenance(
        source=source,
        label=label,
        job_id=job_id,
        job_url=job_url,
        job_url_key=job_url_key,
        apply_url=apply_url,
        apply_url_key=apply_url_key,
        company_url=company_url,
        company_url_key=company_url_key,
        title=title,
        company=company,
        location=location,
        keywords=keywords,
    )
    return NormalizedJob(
        index=index,
        raw=job,
        keywords=keywords,
        source=source,
        source_label=label,
        job_id=job_id,
        title=title,
        company=company,
        location=location,
        job_type=job_type,
        description=description_from_job(job),
        posted_at=posted_at_from_job(job),
        salary=salary,
        remote_mode=remote_mode,
        normalized_title=normalized_title,
        normalized_company=normalized_company,
        normalized_location=normalized_location,
        normalized_job_type=normalized_job_type,
        title_tokens=title_tokens,
        company_tokens=company_tokens,
        location_tokens=location_tokens,
        job_type_tokens=job_type_tokens,
        job_url=job_url,
        job_url_key=job_url_key,
        apply_url=apply_url,
        apply_url_key=apply_url_key,
        company_url=company_url,
        company_url_key=company_url_key,
        blocking_keys=blocking_keys,
        provenance=provenance,
    )
