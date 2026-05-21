"""Google Sheets service construction and addressing helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jobfinder.integrations.google.client import build_google_api_service
from jobfinder.integrations.google.credentials import GoogleAuthConfig

GOOGLE_SHEETS_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
"""OAuth scopes required to read and write Google Sheets."""


def build_google_sheets_service(
    *,
    error_cls: type[RuntimeError],
    service_account_file: Path | None = None,
    token_file: Path | None = None,
    client_secret_file: Path | None = None,
    auth_config: GoogleAuthConfig | None = None,
    scopes: list[str] = GOOGLE_SHEETS_SCOPES,
) -> Any:
    """Build an authenticated Google Sheets API service."""
    return build_google_api_service(
        "sheets",
        "v4",
        error_cls=error_cls,
        service_account_file=service_account_file,
        token_file=token_file,
        client_secret_file=client_secret_file,
        auth_config=auth_config,
        scopes=scopes,
    )


def quote_sheet_name(name: str) -> str:
    """Quote a Google Sheet tab name for A1 notation."""
    return "'" + name.replace("'", "''") + "'"
