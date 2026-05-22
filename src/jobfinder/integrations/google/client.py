"""Shared Google API authentication and execution helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jobfinder.env import EnvSettings
from jobfinder.integrations.google.credentials import (
    GoogleAuthConfig,
    google_credential_files_for,
)

DEFAULT_GOOGLE_API_TIMEOUT_SECONDS = 120
DEFAULT_GOOGLE_API_RETRIES = 3


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
            "GOOGLE_SERVICE_ACCOUNT_FILE, then share the target Google Sheet and "
            "Drive folder with the service-account email as Editor."
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
