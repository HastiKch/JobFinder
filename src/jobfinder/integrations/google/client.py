"""Shared Google API authentication and execution helpers."""

from __future__ import annotations

import os
from contextlib import suppress
from pathlib import Path
from typing import Any

from jobfinder.env import EnvSettings
from jobfinder.integrations.google.credentials import (
    GoogleAuthConfig,
    google_credential_files_for,
)

DEFAULT_GOOGLE_API_TIMEOUT_SECONDS = 120
DEFAULT_GOOGLE_API_RETRIES = 3


def write_private_text_file(path: Path, text: str) -> None:
    """Write a local credential-like file with restrictive permissions."""
    path.write_text(text, encoding="utf-8")
    with suppress(OSError):
        os.chmod(path, 0o600)


def google_api_timeout_seconds(env: EnvSettings | None = None) -> int:
    """Return the per-request Google API timeout in seconds."""
    settings = env or EnvSettings()
    timeout = settings.get_float(
        "GOOGLE_API_TIMEOUT_SECONDS",
        float(DEFAULT_GOOGLE_API_TIMEOUT_SECONDS),
    )
    return max(1, int(timeout))


def google_api_retries(env: EnvSettings | None = None) -> int:
    """Return the Google client retry count for transient API errors."""
    settings = env or EnvSettings()
    return max(0, settings.get_int("GOOGLE_API_RETRIES", DEFAULT_GOOGLE_API_RETRIES))


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
    service_account_file: Path | None = None,
    auth_config: GoogleAuthConfig | None = None,
    scopes: list[str],
) -> Any:
    """Build a service-account-authenticated Google API service."""
    credential_files = google_credential_files_for(
        service_name,
        auth_config=auth_config,
        service_account_file=service_account_file,
    )
    service_account_path = credential_files.service_account_file

    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise error_cls(
            "Missing Google API packages. Install dependencies with: "
            "python -m pip install -r requirements.txt"
        ) from exc

    if not service_account_path.exists():
        raise error_cls(
            f"Missing {service_account_path.name}. Create a Google service account, "
            "download its JSON key, save it as google_service_account.json or set "
            "GOOGLE_SERVICE_ACCOUNT_FILE, then share the target Google Sheet with "
            "the service-account email as Editor."
        )

    creds = service_account.Credentials.from_service_account_file(
        str(service_account_path), scopes=scopes
    )

    return build_google_service(
        build,
        service_name,
        version,
        creds,
        error_cls=error_cls,
    )


def build_google_drive_oauth_service(
    version: str,
    *,
    error_cls: type[RuntimeError],
    token_file: Path | None = None,
    auth_config: GoogleAuthConfig | None = None,
    scopes: list[str],
) -> Any:
    """Build a Google Drive API service from an authorized-user token."""
    credential_files = google_credential_files_for(
        "drive",
        auth_config=auth_config,
        drive_token_file=token_file,
    )
    drive_token_path = credential_files.drive_token_file

    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise error_cls(
            "Missing Google API packages. Install dependencies with: "
            "python -m pip install -r requirements.txt"
        ) from exc

    if not drive_token_path.exists():
        raise error_cls(
            f"Missing {drive_token_path.name}. Create a Google Drive authorized-user "
            "token once, save it as google_token.json or set GOOGLE_DRIVE_TOKEN_FILE, "
            "and use GOOGLE_DRIVE_TOKEN_JSON in GitHub Actions."
        )

    creds = Credentials.from_authorized_user_file(str(drive_token_path), scopes)
    if not creds.has_scopes(scopes):
        raise error_cls(
            f"{drive_token_path.name} does not include the required Google Drive "
            "scope. Recreate the token with Drive access."
        )

    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            write_private_text_file(drive_token_path, creds.to_json())
        else:
            raise error_cls(
                f"{drive_token_path.name} is not a refreshable Google Drive token. "
                "Recreate it as an authorized-user token with offline access."
            )

    return build_google_service(
        build,
        "drive",
        version,
        creds,
        error_cls=error_cls,
    )
