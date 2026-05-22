"""Compatibility facade for Google Sheets helpers.

New code should import from ``jobfinder.integrations.google.sheets``.
"""

from __future__ import annotations

from jobfinder.integrations.google.client import (
    DEFAULT_GOOGLE_API_RETRIES,
    DEFAULT_GOOGLE_API_TIMEOUT_SECONDS,
    build_authorized_http,
    build_google_api_service,
    build_google_drive_oauth_service,
    build_google_service,
    google_api_retries,
    google_api_timeout_seconds,
    google_execute,
    write_private_text_file,
)
from jobfinder.integrations.google.sheets import (
    GOOGLE_SHEETS_SCOPES,
    build_google_sheets_service,
    quote_sheet_name,
)

GOOGLE_SCOPES = GOOGLE_SHEETS_SCOPES
"""Backward-compatible alias for the Google Sheets scopes."""

__all__ = [
    "DEFAULT_GOOGLE_API_RETRIES",
    "DEFAULT_GOOGLE_API_TIMEOUT_SECONDS",
    "GOOGLE_SCOPES",
    "GOOGLE_SHEETS_SCOPES",
    "build_authorized_http",
    "build_google_api_service",
    "build_google_drive_oauth_service",
    "build_google_service",
    "build_google_sheets_service",
    "google_api_retries",
    "google_api_timeout_seconds",
    "google_execute",
    "quote_sheet_name",
    "write_private_text_file",
]
