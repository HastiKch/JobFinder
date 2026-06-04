"""Resume helpers for partially completed scrape/evaluate pipeline runs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from jobfinder.env import EnvSettings
from jobfinder.evaluator.parsing import (
    ensure_output_columns,
    extract_job_records,
    trim_trailing_blank_headers,
)
from jobfinder.evaluator.storage import build_evaluator_google_sheets_service
from jobfinder.integrations.google.client import google_execute
from jobfinder.integrations.google.sheets import quote_sheet_name
from jobfinder.paths import GOOGLE_SPREADSHEET_ID_FILE
from jobfinder.scraper.run_history import parse_run_sheet_started_at
from jobfinder.scraper.settings import load_timezone


@dataclass(frozen=True)
class IncompleteEvaluationSheet:
    """A Google Sheet tab whose scraped rows still need evaluator work."""

    spreadsheet_id: str
    sheet_name: str
    queued_count: int
    skipped_existing_count: int


def pipeline_timezone(env: EnvSettings) -> ZoneInfo:
    """Return the timezone used to decide which run tabs belong to today."""
    value = env.get_alias(
        "JOBFINDER_PIPELINE_TIMEZONE",
        "JOBFINDER_SCRAPER_TIMEZONE",
        "JOBSCRAPER_TIMEZONE",
        default="Europe/Berlin",
    )
    return load_timezone(value, "JOBFINDER_PIPELINE_TIMEZONE")


def read_pipeline_google_spreadsheet_id(env: EnvSettings) -> str:
    """Resolve the Google spreadsheet ID available to the pipeline."""
    spreadsheet_id = (
        env.get("JOB_EVAL_GOOGLE_SPREADSHEET_ID")
        or env.get("GOOGLE_SPREADSHEET_ID")
    )
    if spreadsheet_id:
        return spreadsheet_id
    if GOOGLE_SPREADSHEET_ID_FILE.exists():
        return GOOGLE_SPREADSHEET_ID_FILE.read_text(encoding="utf-8").strip()
    return ""


def visible_sheet_names(service: Any, spreadsheet_id: str) -> list[str]:
    """Return non-hidden Google Sheet tab names in workbook order."""
    metadata = google_execute(
        service.spreadsheets().get(
            spreadsheetId=spreadsheet_id,
            fields="sheets(properties(title,hidden))",
        )
    )
    names: list[str] = []
    for sheet in metadata.get("sheets", []):
        properties = sheet.get("properties", {})
        title = str(properties.get("title") or "").strip()
        if title and not properties.get("hidden", False):
            names.append(title)
    return names


def same_day_timestamped_run_sheets(
    sheet_names: list[str],
    *,
    now: datetime,
    timezone: ZoneInfo,
) -> list[str]:
    """Return today's timestamped run tabs, newest first."""
    local_now = now.astimezone(timezone)
    today = local_now.date()
    candidates: list[tuple[datetime, str]] = []
    for sheet_name in sheet_names:
        started_at = parse_run_sheet_started_at(sheet_name, timezone)
        if started_at is None:
            continue
        local_started_at = started_at.astimezone(timezone)
        if local_started_at.date() != today or local_started_at > local_now:
            continue
        candidates.append((local_started_at, sheet_name))

    return [
        sheet_name
        for _, sheet_name in sorted(
            candidates,
            key=lambda item: (item[0], item[1]),
            reverse=True,
        )
    ]


def read_sheet_values(
    service: Any,
    spreadsheet_id: str,
    sheet_name: str,
) -> tuple[list[str], list[list[Any]]]:
    """Read one Google Sheet tab into evaluator-style headers and rows."""
    response = google_execute(
        service.spreadsheets()
        .values()
        .get(spreadsheetId=spreadsheet_id, range=quote_sheet_name(sheet_name))
    )
    values = response.get("values", [])
    if not values:
        return [], []

    headers = trim_trailing_blank_headers(values[0])
    rows = [list(row) for row in values[1:]]
    return headers, rows


def queued_evaluation_count(
    headers: list[str],
    rows: list[list[Any]],
) -> tuple[int, int]:
    """Return queued and skipped row counts using evaluator queue rules."""
    if not headers:
        return 0, 0
    headers, _ = ensure_output_columns(headers)
    records, skipped_existing = extract_job_records(headers, rows)
    return len(records), skipped_existing


def find_incomplete_evaluation_sheet(
    env: EnvSettings,
    *,
    service: Any | None = None,
    now: datetime | None = None,
) -> IncompleteEvaluationSheet | None:
    """Find the newest same-day run tab that still needs evaluation."""
    spreadsheet_id = read_pipeline_google_spreadsheet_id(env)
    if not spreadsheet_id:
        return None

    service = service or build_evaluator_google_sheets_service()
    timezone = pipeline_timezone(env)
    current_time = now or datetime.now(UTC)
    sheet_names = visible_sheet_names(service, spreadsheet_id)

    for sheet_name in same_day_timestamped_run_sheets(
        sheet_names,
        now=current_time,
        timezone=timezone,
    ):
        headers, rows = read_sheet_values(service, spreadsheet_id, sheet_name)
        queued_count, skipped_existing_count = queued_evaluation_count(headers, rows)
        if queued_count:
            return IncompleteEvaluationSheet(
                spreadsheet_id=spreadsheet_id,
                sheet_name=sheet_name,
                queued_count=queued_count,
                skipped_existing_count=skipped_existing_count,
            )

    return None
