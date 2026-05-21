"""Google Sheets run-history helpers for scraper windows and duplicate checks."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

import jobfinder.dedupe.normalize as dedupe_normalize
from jobfinder.integrations.google.client import google_execute
from jobfinder.integrations.google.sheets import quote_sheet_name
from jobfinder.scraper.normalize import (
    get_apply_url,
    get_company,
    get_job_type,
    get_location,
    get_posted,
    get_posted_datetime,
    get_source_label,
    get_title,
)
from jobfinder.scraper.normalize import (
    parse_datetime_value as parse_scraper_datetime_value,
)
from jobfinder.scraper.settings import (
    POSTED_TIME_WINDOW_BACKFILL,
    POSTED_TIME_WINDOW_LAST_7D,
    POSTED_TIME_WINDOW_LAST_24H,
    POSTED_TIME_WINDOW_SINCE_PREVIOUS_RUN,
    ScraperSettings,
)

RUN_SHEET_NAME_RE = re.compile(
    r"^(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}-\d{2}-\d{2})(?: \(\d+\))?$"
)
LINKEDIN_JOB_ID_RE = re.compile(r"/jobs/view/(?P<id>\d+)", re.IGNORECASE)
STEPSTONE_JOB_ID_RE = re.compile(
    r"--(?P<id>\d+)(?:-inline)?\.html",
    re.IGNORECASE,
)
HYPERLINK_RE = re.compile(
    r'^=HYPERLINK\("(?P<url>(?:[^"]|"")*)"\s*[,;]\s*"',
    re.IGNORECASE,
)
HISTORICAL_IDENTITY_HEADERS = (
    "App",
    "Job Title",
    "Company",
    "Location",
    "Job Type",
    "Posted",
    "Apply URL",
)
POSTED_HEADER_ALIASES = ("Posted", "Posted Date", "Date Posted")
SEEN_JOBS_SHEET_NAME = "_jobfinder_seen_jobs"
SEEN_JOBS_HEADER = ["Job Key"]


@dataclass(frozen=True)
class GoogleSpreadsheetContext:
    """Historical spreadsheet data needed before a scraper run is exported."""

    spreadsheet_id: str
    spreadsheet_url: str
    sheet_names: list[str]
    # Lower bound for since_previous_run. Prefer the newest historical Posted
    # value; fall back to timestamped run-tab names for older sheets.
    previous_run_started_at: datetime | None
    historical_job_keys: set[str]


def parse_run_sheet_started_at(sheet_name: str, timezone: ZoneInfo) -> datetime | None:
    """Parse a timestamped run sheet name into a timezone-aware datetime."""
    match = RUN_SHEET_NAME_RE.match(sheet_name.strip())
    if not match:
        return None

    try:
        parsed = datetime.strptime(match.group("timestamp"), "%Y-%m-%d %H-%M-%S")
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone)


def find_previous_run_started_at(
    sheet_names: list[str],
    current_run_started_at: datetime,
    timezone: ZoneInfo,
) -> datetime | None:
    """Return the newest timestamped sheet before the current run."""
    current = current_run_started_at.astimezone(timezone)
    previous_runs = [
        started_at
        for sheet_name in sheet_names
        if (started_at := parse_run_sheet_started_at(sheet_name, timezone))
        and started_at < current
    ]
    return max(previous_runs) if previous_runs else None


def find_posted_header_index(headers: list[Any]) -> int | None:
    """Return the zero-based index for the historical posted-date column."""
    normalized_headers = {
        normalize_header(header): idx for idx, header in enumerate(headers)
    }
    for alias in POSTED_HEADER_ALIASES:
        idx = normalized_headers.get(normalize_header(alias))
        if idx is not None:
            return idx
    return None


def read_latest_google_posted_at(
    settings: ScraperSettings,
    service: Any,
    spreadsheet_id: str,
    sheet_names: list[str],
) -> datetime | None:
    """Return the newest parseable Posted value from historical Google tabs."""
    header_ranges = [
        f"{quote_sheet_name(sheet_name)}!1:1" for sheet_name in sheet_names
    ]
    header_responses = batch_get_values(service, spreadsheet_id, header_ranges)

    posted_ranges: list[str] = []
    for sheet_name, value_range in zip(sheet_names, header_responses, strict=False):
        values = value_range.get("values", [])
        headers = values[0] if values else []
        posted_idx = find_posted_header_index(headers)
        if posted_idx is None:
            continue
        column = a1_column_name(posted_idx + 1)
        posted_ranges.append(f"{quote_sheet_name(sheet_name)}!{column}2:{column}")

    latest: datetime | None = None
    current_run_started_at = settings.run_started_at.astimezone(settings.posted_tz)
    for value_range in batch_get_values(service, spreadsheet_id, posted_ranges):
        for row in value_range.get("values", []):
            if not row:
                continue
            posted_at = parse_scraper_datetime_value(settings, row[0])
            if not posted_at or posted_at > current_run_started_at:
                continue
            if latest is None or posted_at > latest:
                latest = posted_at

    return latest


def resolve_previous_run_started_at(
    settings: ScraperSettings,
    service: Any,
    spreadsheet_id: str,
    sheet_names: list[str],
) -> datetime | None:
    """Resolve the lower-bound anchor for since_previous_run searches."""
    latest_posted_at = read_latest_google_posted_at(
        settings,
        service,
        spreadsheet_id,
        sheet_names,
    )
    if latest_posted_at is not None:
        return latest_posted_at

    return find_previous_run_started_at(
        sheet_names,
        settings.run_started_at,
        settings.scraper_tz,
    )


def apply_previous_run_search_window(
    settings: ScraperSettings,
    previous_run_started_at: datetime | None,
) -> tuple[ScraperSettings, int | None]:
    """Use the historical lower-bound anchor for the provider posted window."""
    if previous_run_started_at is None:
        return settings, None

    elapsed_seconds = math.ceil(
        (
            settings.run_started_at
            - previous_run_started_at.astimezone(settings.scraper_tz)
        ).total_seconds()
    )
    if elapsed_seconds <= 0:
        return settings, None

    search_seconds = max(1, elapsed_seconds + settings.search_window_buffer_seconds)
    return replace(settings, published_at=f"r{search_seconds}"), search_seconds


def apply_configured_posted_time_window(
    settings: ScraperSettings,
    previous_run_started_at: datetime | None,
) -> tuple[ScraperSettings, int | None, bool]:
    """Apply the selected posted-time window before building provider searches."""
    if settings.posted_time_window == POSTED_TIME_WINDOW_SINCE_PREVIOUS_RUN:
        updated, search_seconds = apply_previous_run_search_window(
            settings,
            previous_run_started_at,
        )
        return updated, search_seconds, previous_run_started_at is not None

    if settings.posted_time_window == POSTED_TIME_WINDOW_LAST_24H:
        return replace(settings, published_at="r86400"), 24 * 60 * 60, False

    if settings.posted_time_window == POSTED_TIME_WINDOW_LAST_7D:
        return replace(settings, published_at="r604800"), 7 * 24 * 60 * 60, False

    if settings.posted_time_window == POSTED_TIME_WINDOW_BACKFILL:
        return replace(settings, published_at=""), None, False

    return settings, None, False


def filter_jobs_to_previous_run_window(
    settings: ScraperSettings,
    jobs: list[dict[str, Any]],
    previous_run_started_at: datetime | None,
) -> tuple[list[dict[str, Any]], int, int]:
    """Keep jobs posted within the historical-anchor/current-run interval."""
    if previous_run_started_at is None:
        return jobs, 0, 0

    window_start = previous_run_started_at.astimezone(settings.posted_tz)
    window_end = settings.run_started_at.astimezone(settings.posted_tz)
    kept: list[dict[str, Any]] = []
    outside_window_count = 0
    unknown_posted_count = 0

    for job in jobs:
        posted_at = get_posted_datetime(settings, job)
        if posted_at is None:
            kept.append(job)
            unknown_posted_count += 1
            continue

        posted_at = posted_at.astimezone(settings.posted_tz)
        if window_start <= posted_at <= window_end:
            kept.append(job)
        else:
            outside_window_count += 1

    return kept, outside_window_count, unknown_posted_count


def normalize_identity_value(value: Any) -> str:
    """Normalize spreadsheet/job text for stable identity comparisons."""
    if value is None:
        return ""
    text = re.sub(r"\s+", " ", str(value).strip())
    if not text or text in {"N/A", "Open Job", "Open Apply"}:
        return ""
    return text.casefold()


def hyperlink_formula_url(value: Any) -> str:
    """Extract the URL from a Google Sheets HYPERLINK formula when present."""
    if not isinstance(value, str):
        return ""
    match = HYPERLINK_RE.match(value.strip())
    if not match:
        return value.strip()
    return match.group("url").replace('""', '"').strip()


def canonical_job_url(value: Any) -> str:
    """Return a canonical URL token for duplicate comparisons."""
    url = hyperlink_formula_url(value)
    if not url or normalize_identity_value(url) == "":
        return ""

    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return ""

    host = parsed.netloc.lower()
    path = parsed.path.rstrip("/")
    if "linkedin.com" in host:
        match = LINKEDIN_JOB_ID_RE.search(path)
        if match:
            return f"linkedin:{match.group('id')}"
        return f"{host}{path}".casefold()

    if "indeed." in host:
        job_keys = parse_qs(parsed.query).get("jk", [])
        if job_keys and job_keys[0]:
            return f"indeed:{job_keys[0].casefold()}"

    if "stepstone." in host:
        match = STEPSTONE_JOB_ID_RE.search(path)
        if match:
            return f"stepstone:{match.group('id')}"
        return f"{host}{path}".casefold()

    return f"{host}{path}".casefold()


def job_id_from_url(value: Any) -> str:
    """Extract a source-native job ID from a job URL when possible."""
    canonical_url = canonical_job_url(value)
    if ":" not in canonical_url:
        return ""
    source, job_id = canonical_url.split(":", 1)
    if source in {"linkedin", "indeed", "stepstone"}:
        return job_id
    return ""


def split_source_values(source: Any) -> list[str]:
    """Split the App column into individual provider labels."""
    text = normalize_identity_value(source)
    if not text:
        return ["unknown"]
    values = [
        normalize_identity_value(part)
        for part in re.split(r"\s*\|\s*", text)
        if normalize_identity_value(part)
    ]
    return values or ["unknown"]


def normalize_posted_identity(value: Any) -> str:
    """Normalize posted values to a day-level identity token."""
    text = normalize_identity_value(value)
    if not text:
        return ""
    match = re.search(r"\d{4}-\d{2}-\d{2}", text)
    if match:
        return match.group(0)
    posted_at = dedupe_normalize.parse_datetime_value(value)
    if posted_at:
        return posted_at.date().isoformat()
    return text


def source_agnostic_profile_key(
    title: Any,
    company: Any,
    location: Any,
    job_type: Any = "",
    posted: Any = "",
) -> str:
    """Build a cross-provider exact profile key from canonical field forms."""
    title_key = dedupe_normalize.normalize_title(title)
    company_key = dedupe_normalize.normalize_company(company)
    location_key = dedupe_normalize.normalize_location(location)
    job_type_key = dedupe_normalize.normalize_job_type(job_type)
    posted_key = normalize_posted_identity(posted)
    if not title_key or not company_key or not location_key:
        return ""
    return (
        "profile|any|"
        f"{company_key}|{title_key}|{location_key}|{job_type_key}|{posted_key}"
    )


def expand_historical_job_key(key: str) -> set[str]:
    """Add source-agnostic equivalents for legacy seen-job index keys."""
    text = str(key or "").strip()
    expanded = {text} if text else set()
    parts = text.split("|")
    if len(parts) == 5 and parts[0] == "profile" and parts[1] != "any":
        _, _source, title, company, location = parts
        profile_key = source_agnostic_profile_key(title, company, location)
        if profile_key:
            expanded.add(profile_key)
    return expanded


def job_identity_keys_from_values(
    *,
    source: Any,
    title: Any,
    company: Any,
    location: Any,
    job_url: Any = "",
    job_id: Any = "",
    apply_url: Any = "",
    job_type: Any = "",
    posted: Any = "",
) -> set[str]:
    """Build all useful duplicate keys from normalized row/job values."""
    source_keys = split_source_values(source)
    keys: set[str] = set()

    external_apply_key = dedupe_normalize.canonical_external_apply_url(apply_url)
    if external_apply_key:
        keys.add(f"apply|{external_apply_key}")

    title_key = normalize_identity_value(title)
    company_key = normalize_identity_value(company)
    location_key = normalize_identity_value(location)
    if title_key and company_key and location_key:
        job_type_key = dedupe_normalize.normalize_job_type(job_type)
        posted_key = normalize_posted_identity(posted)
        for source_key in source_keys:
            keys.add(
                "profile|"
                f"{source_key}|{title_key}|{company_key}|{location_key}|"
                f"{job_type_key}|{posted_key}"
            )
        profile_key = source_agnostic_profile_key(
            title,
            company,
            location,
            job_type,
            posted,
        )
        if profile_key:
            keys.add(profile_key)

    return keys


def job_identity_keys(settings: ScraperSettings, job: dict[str, Any]) -> set[str]:
    """Build duplicate keys for one raw scraped job."""
    keys = job_identity_keys_from_values(
        source=get_source_label(job),
        title=get_title(job),
        company=get_company(job),
        location=get_location(job),
        job_type=get_job_type(job),
        posted=get_posted(settings, job),
        apply_url=get_apply_url(job),
    )
    provenance = job.get("_jobfinder_provenance", [])
    if isinstance(provenance, list):
        for item in provenance:
            if not isinstance(item, dict):
                continue
            apply_key = dedupe_normalize.canonical_external_apply_url(
                item.get("apply_url") or ""
            )
            if apply_key:
                keys.add(f"apply|{apply_key}")
    return keys


def remove_jobs_seen_in_history(
    settings: ScraperSettings,
    jobs: list[dict[str, Any]],
    historical_job_keys: set[str],
) -> tuple[list[dict[str, Any]], int]:
    """Drop newly scraped jobs that already appear in previous run sheets."""
    if not historical_job_keys:
        return jobs, 0

    kept: list[dict[str, Any]] = []
    duplicate_count = 0
    for job in jobs:
        if job_identity_keys(settings, job) & historical_job_keys:
            duplicate_count += 1
        else:
            kept.append(job)
    return kept, duplicate_count


def normalize_header(value: Any) -> str:
    """Normalize a spreadsheet header for duplicate-column lookup."""
    return re.sub(r"\s+", " ", str(value or "").strip()).casefold()


def a1_column_name(column_number: int) -> str:
    """Return a one-based spreadsheet column number as A1 letters."""
    letters = ""
    while column_number:
        column_number, remainder = divmod(column_number - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def batch_get_values(
    service: Any,
    spreadsheet_id: str,
    ranges: list[str],
    *,
    value_render_option: str = "FORMATTED_VALUE",
) -> list[dict[str, Any]]:
    """Read Google Sheets ranges, preserving response order."""
    if not ranges:
        return []

    value_ranges: list[dict[str, Any]] = []
    chunk_size = 50
    for start_idx in range(0, len(ranges), chunk_size):
        response = google_execute(
            service.spreadsheets()
            .values()
            .batchGet(
                spreadsheetId=spreadsheet_id,
                ranges=ranges[start_idx : start_idx + chunk_size],
                valueRenderOption=value_render_option,
            )
        )
        value_ranges.extend(response.get("valueRanges", []))
    return value_ranges


def seen_jobs_index_exists(sheet_names: list[str]) -> bool:
    """Return true when the spreadsheet has the maintained seen-jobs index tab."""
    return SEEN_JOBS_SHEET_NAME in sheet_names


def read_seen_jobs_index(service: Any, spreadsheet_id: str) -> set[str]:
    """Read canonical job keys from the maintained seen-jobs index tab."""
    response = google_execute(
        service.spreadsheets()
        .values()
        .get(
            spreadsheetId=spreadsheet_id,
            range=f"{quote_sheet_name(SEEN_JOBS_SHEET_NAME)}!A2:A",
        )
    )
    values = response.get("values", [])
    keys: set[str] = set()
    for row in values:
        if not row or not str(row[0]).strip():
            continue
        keys.update(expand_historical_job_key(str(row[0]).strip()))
    return keys


def ensure_seen_jobs_index_sheet(
    service: Any,
    spreadsheet_id: str,
    sheet_names: list[str],
) -> None:
    """Create the hidden seen-jobs index tab when it does not exist."""
    if seen_jobs_index_exists(sheet_names):
        return

    google_execute(
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={
                "requests": [
                    {
                        "addSheet": {
                            "properties": {
                                "title": SEEN_JOBS_SHEET_NAME,
                                "hidden": True,
                            }
                        }
                    }
                ]
            },
        ),
        retries=0,
    )
    google_execute(
        service.spreadsheets()
        .values()
        .update(
            spreadsheetId=spreadsheet_id,
            range=f"{quote_sheet_name(SEEN_JOBS_SHEET_NAME)}!A1",
            valueInputOption="RAW",
            body={"values": [SEEN_JOBS_HEADER]},
        )
    )


def append_seen_job_keys(
    service: Any,
    spreadsheet_id: str,
    sheet_names: list[str],
    job_keys: set[str],
) -> None:
    """Append newly seen canonical job keys to the maintained index tab."""
    if not job_keys:
        return

    ensure_seen_jobs_index_sheet(service, spreadsheet_id, sheet_names)
    existing_keys = read_seen_jobs_index(service, spreadsheet_id)
    new_keys = sorted(job_keys - existing_keys)
    if not new_keys:
        return

    google_execute(
        service.spreadsheets()
        .values()
        .append(
            spreadsheetId=spreadsheet_id,
            range=f"{quote_sheet_name(SEEN_JOBS_SHEET_NAME)}!A:A",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": [[key] for key in new_keys]},
        ),
        retries=0,
    )


def sheet_header_indexes(headers: list[Any]) -> dict[str, int]:
    """Return duplicate-relevant header indexes for one sheet."""
    normalized_headers = {
        normalize_header(header): idx for idx, header in enumerate(headers)
    }
    return {
        header: normalized_headers[normalize_header(header)]
        for header in HISTORICAL_IDENTITY_HEADERS
        if normalize_header(header) in normalized_headers
    }


def read_historical_google_job_keys(
    service: Any,
    spreadsheet_id: str,
    sheet_names: list[str],
) -> set[str]:
    """Read previous Google Sheet tabs and return all known job identity keys."""
    header_ranges = [
        f"{quote_sheet_name(sheet_name)}!1:1" for sheet_name in sheet_names
    ]
    header_responses = batch_get_values(service, spreadsheet_id, header_ranges)
    sheet_columns: dict[str, dict[str, int]] = {}

    for sheet_name, value_range in zip(sheet_names, header_responses, strict=False):
        values = value_range.get("values", [])
        headers = values[0] if values else []
        indexes = sheet_header_indexes(headers)
        has_profile = {"App", "Job Title", "Company", "Location"} <= indexes.keys()
        has_url = {"App", "Job URL"} <= indexes.keys()
        if has_profile or has_url:
            sheet_columns[sheet_name] = indexes

    column_range_specs: list[tuple[str, str, str]] = []
    for sheet_name, indexes in sheet_columns.items():
        for header, zero_based_idx in indexes.items():
            column = a1_column_name(zero_based_idx + 1)
            range_name = f"{quote_sheet_name(sheet_name)}!{column}2:{column}"
            column_range_specs.append((sheet_name, header, range_name))

    column_responses = batch_get_values(
        service,
        spreadsheet_id,
        [range_name for _, _, range_name in column_range_specs],
        value_render_option="FORMULA",
    )
    sheet_values: dict[str, dict[str, list[Any]]] = {
        sheet_name: {} for sheet_name in sheet_columns
    }

    for (sheet_name, header, _), value_range in zip(
        column_range_specs,
        column_responses,
        strict=False,
    ):
        values = value_range.get("values", [])
        sheet_values[sheet_name][header] = [row[0] if row else "" for row in values]

    historical_keys: set[str] = set()
    for columns in sheet_values.values():
        row_count = max((len(values) for values in columns.values()), default=0)
        for row_idx in range(row_count):
            row = {
                header: values[row_idx] if row_idx < len(values) else ""
                for header, values in columns.items()
            }
            historical_keys.update(
                job_identity_keys_from_values(
                    source=row.get("App", ""),
                    title=row.get("Job Title", ""),
                    company=row.get("Company", ""),
                    location=row.get("Location", ""),
                    job_url=row.get("Job URL", ""),
                    apply_url=row.get("Apply URL", ""),
                )
            )

    return historical_keys


def load_google_spreadsheet_context(
    settings: ScraperSettings,
    service: Any,
    *,
    seed_seen_jobs_index: bool = True,
) -> GoogleSpreadsheetContext:
    """Load existing run metadata and duplicate keys from Google Sheets."""
    from jobfinder.scraper.export_google_sheets import (
        GoogleSheetsExportError,
        get_google_spreadsheet,
        read_google_spreadsheet_id,
    )

    spreadsheet_id = read_google_spreadsheet_id(settings)
    if not spreadsheet_id:
        return GoogleSpreadsheetContext("", "", [], None, set())

    try:
        spreadsheet = get_google_spreadsheet(service, spreadsheet_id)
        sheet_names = [
            sheet["properties"]["title"] for sheet in spreadsheet.get("sheets", [])
        ]
        previous_run_started_at = resolve_previous_run_started_at(
            settings,
            service,
            spreadsheet_id,
            sheet_names,
        )
        if seen_jobs_index_exists(sheet_names):
            historical_job_keys = read_seen_jobs_index(service, spreadsheet_id)
        else:
            historical_job_keys = read_historical_google_job_keys(
                service,
                spreadsheet_id,
                sheet_names,
            )
            if seed_seen_jobs_index:
                append_seen_job_keys(
                    service,
                    spreadsheet_id,
                    sheet_names,
                    historical_job_keys,
                )
    except Exception as exc:
        raise GoogleSheetsExportError(
            f"Could not read run history from Google spreadsheet ID "
            f"'{spreadsheet_id}'. Details: {exc}"
        ) from exc

    return GoogleSpreadsheetContext(
        spreadsheet_id=spreadsheet_id,
        spreadsheet_url=spreadsheet["spreadsheetUrl"],
        sheet_names=sheet_names,
        previous_run_started_at=previous_run_started_at,
        historical_job_keys=historical_job_keys,
    )
