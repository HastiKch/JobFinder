"""Shared Google Sheets authentication and addressing helpers."""

from __future__ import annotations

import os
from contextlib import suppress
from pathlib import Path
from typing import Any

from jobfinder.paths import (
    GOOGLE_CLIENT_SECRET_FILE,
    GOOGLE_SERVICE_ACCOUNT_FILE,
    GOOGLE_TOKEN_FILE,
)

GOOGLE_SHEETS_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
"""OAuth scopes required to read and write Google Sheets."""

GOOGLE_SCOPES = GOOGLE_SHEETS_SCOPES
"""Backward-compatible alias for the Google Sheets scopes."""

DEFAULT_GOOGLE_API_TIMEOUT_SECONDS = 120
DEFAULT_GOOGLE_API_RETRIES = 3


def write_private_text_file(path: Path, text: str) -> None:
    """Write a local credential-like file with restrictive permissions."""
    path.write_text(text, encoding="utf-8")
    with suppress(OSError):
        os.chmod(path, 0o600)


def google_api_timeout_seconds() -> int:
    """Return the per-request Google API timeout in seconds."""
    raw_value = os.environ.get(
        "GOOGLE_API_TIMEOUT_SECONDS",
        str(DEFAULT_GOOGLE_API_TIMEOUT_SECONDS),
    )
    try:
        return max(1, int(float(raw_value)))
    except ValueError:
        return DEFAULT_GOOGLE_API_TIMEOUT_SECONDS


def google_api_retries() -> int:
    """Return the Google client retry count for transient API errors."""
    raw_value = os.environ.get("GOOGLE_API_RETRIES", str(DEFAULT_GOOGLE_API_RETRIES))
    try:
        return max(0, int(raw_value))
    except ValueError:
        return DEFAULT_GOOGLE_API_RETRIES


def google_execute(request: Any, *, retries: int | None = None) -> Any:
    """Execute one Google API request with bounded transient retries."""
    retry_count = google_api_retries() if retries is None else max(0, retries)
    try:
        return request.execute(num_retries=retry_count)
    except TypeError as exc:
        if "num_retries" not in str(exc):
            raise
        return request.execute()


def build_authorized_http(creds: Any, *, error_cls: type[RuntimeError]) -> Any:
    """Build a Google-authorized HTTP client with an explicit socket timeout."""
    try:
        import google_auth_httplib2
        import httplib2
    except ImportError as exc:
        raise error_cls(
            "Missing Google HTTP transport packages. Install dependencies with: "
            "python -m pip install -r requirements.txt"
        ) from exc

    return google_auth_httplib2.AuthorizedHttp(
        creds,
        http=httplib2.Http(timeout=google_api_timeout_seconds()),
    )


def build_google_service(
    build_func: Any,
    service_name: str,
    version: str,
    creds: Any,
    *,
    error_cls: type[RuntimeError],
) -> Any:
    """Build a Google API service that cannot hang indefinitely on HTTP I/O."""
    return build_func(
        service_name,
        version,
        http=build_authorized_http(creds, error_cls=error_cls),
        cache_discovery=False,
    )


def build_google_api_service(
    service_name: str,
    version: str,
    *,
    error_cls: type[RuntimeError],
    service_account_file: Path = GOOGLE_SERVICE_ACCOUNT_FILE,
    token_file: Path = GOOGLE_TOKEN_FILE,
    client_secret_file: Path = GOOGLE_CLIENT_SECRET_FILE,
    scopes: list[str],
    prefer_service_account: bool = True,
) -> Any:
    """Build an authenticated Google API service."""
    try:
        from google.auth.transport.requests import Request
        from google.oauth2 import service_account
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise error_cls(
            "Missing Google API packages. Install dependencies with: "
            "python -m pip install -r requirements.txt"
        ) from exc

    if prefer_service_account and service_account_file.exists():
        creds = service_account.Credentials.from_service_account_file(
            str(service_account_file), scopes=scopes
        )
        return build_google_service(
            build,
            service_name,
            version,
            creds,
            error_cls=error_cls,
        )

    creds = None
    if token_file.exists():
        creds = Credentials.from_authorized_user_file(str(token_file), scopes)
        if not creds.has_scopes(scopes):
            creds = None

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not client_secret_file.exists():
                if not prefer_service_account and service_account_file.exists():
                    creds = service_account.Credentials.from_service_account_file(
                        str(service_account_file), scopes=scopes
                    )
                    return build_google_service(
                        build,
                        service_name,
                        version,
                        creds,
                        error_cls=error_cls,
                    )
                raise error_cls(
                    f"Missing {service_account_file.name}. Create a Google service "
                    "account, download its JSON key, save it in this folder, and "
                    "share the target spreadsheet or Drive folder with the "
                    "service-account email. "
                    f"For local OAuth fallback, create {client_secret_file.name} "
                    "instead."
                )
            try:
                from google_auth_oauthlib.flow import InstalledAppFlow
            except ImportError as exc:
                raise error_cls(
                    "Missing Google OAuth packages for local browser auth. Install "
                    "dependencies with: python -m pip install -r requirements.txt"
                ) from exc

            flow = InstalledAppFlow.from_client_secrets_file(
                str(client_secret_file), scopes
            )
            creds = flow.run_local_server(port=0)

        write_private_text_file(token_file, creds.to_json())

    return build_google_service(
        build,
        service_name,
        version,
        creds,
        error_cls=error_cls,
    )


def build_google_sheets_service(
    *,
    error_cls: type[RuntimeError],
    service_account_file: Path = GOOGLE_SERVICE_ACCOUNT_FILE,
    token_file: Path = GOOGLE_TOKEN_FILE,
    client_secret_file: Path = GOOGLE_CLIENT_SECRET_FILE,
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
        scopes=scopes,
    )


def quote_sheet_name(name: str) -> str:
    """Quote a Google Sheet tab name for A1 notation."""
    return "'" + name.replace("'", "''") + "'"
