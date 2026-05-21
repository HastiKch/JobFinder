"""Google Sheets export support for scraper results."""

from __future__ import annotations

from typing import Any

from jobfinder.google_sheets import (
    build_google_sheets_service,
    google_execute,
    quote_sheet_name,
)
from jobfinder.scraper.export_rows import HEADER, make_job_rows, unique_name
from jobfinder.scraper.run_history import append_seen_job_keys, job_identity_keys
from jobfinder.scraper.settings import SPREADSHEET_TITLE, ScraperSettings


class GoogleSheetsExportError(RuntimeError):
    """Raised when Google Sheets export is not configured correctly."""


def build_scraper_google_sheets_service() -> Any:
    """Build a Google Sheets service for scraper exports."""
    return build_google_sheets_service(error_cls=GoogleSheetsExportError)


def update_values(
    service: Any, spreadsheet_id: str, sheet_name: str, rows: list[list[Any]]
) -> None:
    """Write all scraper rows to a Google Sheet tab."""
    google_execute(
        service.spreadsheets()
        .values()
        .update(
            spreadsheetId=spreadsheet_id,
            range=f"{quote_sheet_name(sheet_name)}!A1",
            valueInputOption="USER_ENTERED",
            body={"values": rows},
        )
    )


def header_index(name: str) -> int:
    """Return the zero-based output column index for a header name."""
    return HEADER.index(name)


def column_range(sheet_id: int, column_name: str, end_row_index: int) -> dict[str, Any]:
    """Build a Google Sheets API range object for one output column."""
    column_idx = header_index(column_name)
    return {
        "sheetId": sheet_id,
        "startRowIndex": 1,
        "endRowIndex": end_row_index,
        "startColumnIndex": column_idx,
        "endColumnIndex": column_idx + 1,
    }


def dropdown_validation_request(
    sheet_id: int, column_name: str, options: list[str], end_row_index: int
) -> dict[str, Any]:
    """Build a data-validation request for a dropdown column."""
    return {
        "setDataValidation": {
            "range": column_range(sheet_id, column_name, end_row_index),
            "rule": {
                "condition": {
                    "type": "ONE_OF_LIST",
                    "values": [{"userEnteredValue": option} for option in options],
                },
                "showCustomUi": True,
                "strict": True,
            },
        }
    }


def date_time_format_request(
    sheet_id: int, column_name: str, end_row_index: int
) -> dict[str, Any]:
    """Build a date-time format request for a column."""
    return {
        "repeatCell": {
            "range": column_range(sheet_id, column_name, end_row_index),
            "cell": {
                "userEnteredFormat": {
                    "numberFormat": {
                        "type": "DATE_TIME",
                        "pattern": "yyyy-mm-dd hh:mm",
                    }
                }
            },
            "fields": "userEnteredFormat.numberFormat",
        }
    }


def format_spreadsheet(
    settings: ScraperSettings,
    service: Any,
    spreadsheet_id: str,
    sheet_id: int,
    job_row_count: int,
) -> None:
    """Apply formatting, filters, and validation to an exported sheet."""
    editable_row_count = max(job_row_count, 1000)
    requests_body = [
        {
            "updateSheetProperties": {
                "properties": {
                    "sheetId": sheet_id,
                    "gridProperties": {"frozenRowCount": 1},
                },
                "fields": "gridProperties.frozenRowCount",
            }
        },
        {
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 0,
                    "endRowIndex": 1,
                },
                "cell": {
                    "userEnteredFormat": {
                        "backgroundColor": {
                            "red": 0.063,
                            "green": 0.173,
                            "blue": 0.325,
                        },
                        "horizontalAlignment": "CENTER",
                        "textFormat": {
                            "bold": True,
                            "foregroundColor": {"red": 1, "green": 1, "blue": 1},
                        },
                    }
                },
                "fields": (
                    "userEnteredFormat(backgroundColor,horizontalAlignment,textFormat)"
                ),
            }
        },
        {
            "setBasicFilter": {
                "filter": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 0,
                        "endRowIndex": max(job_row_count, 1),
                        "startColumnIndex": 0,
                        "endColumnIndex": len(HEADER),
                    }
                }
            }
        },
        {
            "autoResizeDimensions": {
                "dimensions": {
                    "sheetId": sheet_id,
                    "dimension": "COLUMNS",
                    "startIndex": 0,
                    "endIndex": len(HEADER),
                }
            }
        },
        dropdown_validation_request(
            sheet_id,
            "Application Status",
            settings.application_status_options,
            editable_row_count,
        ),
        date_time_format_request(sheet_id, "Posted", editable_row_count),
    ]

    google_execute(
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": requests_body},
        )
    )


def read_google_spreadsheet_id(settings: ScraperSettings) -> str:
    """Read the configured or cached Google spreadsheet ID."""
    if settings.google_spreadsheet_id:
        return settings.google_spreadsheet_id
    if settings.spreadsheet_id_file.exists():
        return settings.spreadsheet_id_file.read_text(encoding="utf-8").strip()
    return ""


def get_google_spreadsheet(service: Any, spreadsheet_id: str) -> dict[str, Any]:
    """Fetch basic spreadsheet metadata for an existing spreadsheet."""
    return google_execute(
        service.spreadsheets().get(
            spreadsheetId=spreadsheet_id,
            fields="spreadsheetId,spreadsheetUrl,sheets(properties(sheetId,title))",
        )
    )


def create_google_spreadsheet(
    settings: ScraperSettings, service: Any
) -> tuple[dict[str, Any], str, int]:
    """Create the default Google spreadsheet and initial run sheet."""
    spreadsheet = google_execute(
        service.spreadsheets().create(
            body={
                "properties": {"title": SPREADSHEET_TITLE},
                "sheets": [{"properties": {"title": settings.run_sheet_name}}],
            },
            fields="spreadsheetId,spreadsheetUrl,sheets(properties(sheetId,title))",
        ),
        retries=0,
    )
    settings.spreadsheet_id_file.write_text(
        spreadsheet["spreadsheetId"], encoding="utf-8"
    )
    sheet_id = spreadsheet["sheets"][0]["properties"]["sheetId"]
    return spreadsheet, settings.run_sheet_name, sheet_id


def add_google_run_sheet(
    settings: ScraperSettings,
    service: Any,
    spreadsheet_id: str,
    existing_names: set[str],
) -> tuple[str, int]:
    """Add a new timestamped worksheet to an existing spreadsheet."""
    sheet_name = unique_name(existing_names, settings.run_sheet_name)
    response = google_execute(
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": [{"addSheet": {"properties": {"title": sheet_name}}}]},
        ),
        retries=0,
    )
    sheet_id = response["replies"][0]["addSheet"]["properties"]["sheetId"]
    return sheet_name, sheet_id


def get_or_create_google_run_sheet(
    settings: ScraperSettings, service: Any
) -> tuple[str, str, str, int, list[str]]:
    """Return spreadsheet and sheet metadata for the current scraper run."""
    spreadsheet_id = read_google_spreadsheet_id(settings)
    if not spreadsheet_id:
        spreadsheet, sheet_name, sheet_id = create_google_spreadsheet(settings, service)
        return (
            spreadsheet["spreadsheetId"],
            spreadsheet["spreadsheetUrl"],
            sheet_name,
            sheet_id,
            [sheet_name],
        )

    try:
        spreadsheet = get_google_spreadsheet(service, spreadsheet_id)
    except Exception as exc:
        raise GoogleSheetsExportError(
            f"Could not open Google spreadsheet ID '{spreadsheet_id}'. "
            f"Check {settings.spreadsheet_id_file.name}, or delete it to create a new "
            f"'jobs' spreadsheet. Details: {exc}"
        ) from exc

    existing_names = {
        sheet["properties"]["title"] for sheet in spreadsheet.get("sheets", [])
    }
    sheet_name, sheet_id = add_google_run_sheet(
        settings, service, spreadsheet_id, existing_names
    )
    return (
        spreadsheet_id,
        spreadsheet["spreadsheetUrl"],
        sheet_name,
        sheet_id,
        list(existing_names),
    )


def export_to_google_sheets(
    settings: ScraperSettings, service: Any, jobs: list[dict[str, Any]]
) -> str:
    """Write jobs to a new timestamped tab in Google Sheets."""
    spreadsheet_id, spreadsheet_url, sheet_name, sheet_id, existing_sheet_names = (
        get_or_create_google_run_sheet(settings, service)
    )
    job_rows = make_job_rows(settings, jobs)

    update_values(service, spreadsheet_id, sheet_name, job_rows)
    format_spreadsheet(settings, service, spreadsheet_id, sheet_id, len(job_rows))
    seen_keys: set[str] = set()
    for job in jobs:
        seen_keys.update(job_identity_keys(settings, job))
    append_seen_job_keys(service, spreadsheet_id, existing_sheet_names, seen_keys)

    return f"{spreadsheet_url} (sheet: {sheet_name})"
