"""Tests for pipeline resume detection."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from jobfinder.env import EnvSettings
from jobfinder.pipeline.resume import (
    find_incomplete_evaluation_sheet,
    same_day_timestamped_run_sheets,
)


class FakeRequest:
    """Minimal executable request object for fake Google Sheets calls."""

    def __init__(self, result: dict[str, Any]) -> None:
        self.result = result

    def execute(self, num_retries: int = 0) -> dict[str, Any]:
        return self.result


class FakeValuesResource:
    """Fake values resource that returns configured sheet values."""

    def __init__(self, service: FakeGoogleService) -> None:
        self.service = service

    def get(self, *, spreadsheetId: str, range: str) -> FakeRequest:
        self.service.value_gets.append((spreadsheetId, range))
        sheet_name = unquote_sheet_range(range)
        return FakeRequest({"values": self.service.values_by_sheet.get(sheet_name, [])})


class FakeSpreadsheetsResource:
    """Fake spreadsheets resource for resume detection."""

    def __init__(self, service: FakeGoogleService) -> None:
        self.service = service

    def get(self, *, spreadsheetId: str, fields: str) -> FakeRequest:
        self.service.metadata_gets.append((spreadsheetId, fields))
        return FakeRequest({"sheets": self.service.sheets})

    def values(self) -> FakeValuesResource:
        return FakeValuesResource(self.service)


class FakeGoogleService:
    """Small fake for the Google Sheets service surface used by resume."""

    def __init__(
        self,
        *,
        sheets: list[dict[str, Any]],
        values_by_sheet: dict[str, list[list[Any]]],
    ) -> None:
        self.sheets = sheets
        self.values_by_sheet = values_by_sheet
        self.metadata_gets: list[tuple[str, str]] = []
        self.value_gets: list[tuple[str, str]] = []

    def spreadsheets(self) -> FakeSpreadsheetsResource:
        return FakeSpreadsheetsResource(self)


def unquote_sheet_range(value: str) -> str:
    """Undo the simple quoted-sheet form used by the resume reader."""
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1].replace("''", "'")
    return value


def sheet(title: str, *, hidden: bool = False) -> dict[str, Any]:
    """Build fake Google Sheets metadata for one tab."""
    return {"properties": {"title": title, "hidden": hidden}}


def test_same_day_timestamped_run_sheets_returns_newest_today_first():
    """Resume detection should only consider timestamped tabs from today."""
    berlin = ZoneInfo("Europe/Berlin")
    now = datetime(2026, 6, 4, 16, 0, tzinfo=berlin)

    candidates = same_day_timestamped_run_sheets(
        [
            "Notes",
            "2026-06-03 15-00-00",
            "2026-06-04 07-17-00",
            "2026-06-04 11-37-00",
            "2026-06-04 17-17-00",
        ],
        now=now,
        timezone=berlin,
    )

    assert candidates == ["2026-06-04 11-37-00", "2026-06-04 07-17-00"]


def test_find_incomplete_evaluation_sheet_returns_newest_unfinished_today_tab():
    """A same-day partially evaluated tab should make the pipeline skip scraping."""
    berlin = ZoneInfo("Europe/Berlin")
    service = FakeGoogleService(
        sheets=[
            sheet("2026-06-03 15-00-00"),
            sheet("_jobfinder_seen_jobs", hidden=True),
            sheet("2026-06-04 07-17-00"),
            sheet("2026-06-04 11-37-00"),
        ],
        values_by_sheet={
            "2026-06-04 11-37-00": [
                ["Job Title", "Company", "AI Verdict", "AI Tailored CV", "AI CV PDF"],
                ["Evaluated row", "Acme", "Not Suitable", "", ""],
            ],
            "2026-06-04 07-17-00": [
                ["Job Title", "Company", "AI Verdict", "AI Tailored CV", "AI CV PDF"],
                ["GIS Analyst", "Acme Analytics", "", "", ""],
                ["Existing row", "Beta GmbH", "Not Suitable", "", ""],
            ],
        },
    )

    resume_sheet = find_incomplete_evaluation_sheet(
        EnvSettings(
            {
                "GOOGLE_SPREADSHEET_ID": "spreadsheet-id",
                "JOBFINDER_PIPELINE_TIMEZONE": "Europe/Berlin",
            }
        ),
        service=service,
        now=datetime(2026, 6, 4, 16, 0, tzinfo=berlin),
    )

    assert resume_sheet is not None
    assert resume_sheet.sheet_name == "2026-06-04 07-17-00"
    assert resume_sheet.queued_count == 1
    assert resume_sheet.skipped_existing_count == 1
    assert service.value_gets == [
        ("spreadsheet-id", "'2026-06-04 11-37-00'"),
        ("spreadsheet-id", "'2026-06-04 07-17-00'"),
    ]


def test_find_incomplete_evaluation_sheet_ignores_previous_day_incomplete_tabs():
    """A new day should not be blocked by an older unfinished tab."""
    berlin = ZoneInfo("Europe/Berlin")
    service = FakeGoogleService(
        sheets=[sheet("2026-06-03 15-00-00")],
        values_by_sheet={
            "2026-06-03 15-00-00": [
                ["Job Title", "Company", "AI Verdict"],
                ["GIS Analyst", "Acme Analytics", ""],
            ],
        },
    )

    resume_sheet = find_incomplete_evaluation_sheet(
        EnvSettings({"GOOGLE_SPREADSHEET_ID": "spreadsheet-id"}),
        service=service,
        now=datetime(2026, 6, 4, 8, 0, tzinfo=berlin),
    )

    assert resume_sheet is None
    assert service.value_gets == []
