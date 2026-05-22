"""Shared Google API authentication and execution helpers."""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from contextlib import suppress
from pathlib import Path
from typing import Any

from jobfinder.env import EnvSettings
from jobfinder.integrations.google.credentials import (
    GOOGLE_OAUTH_SCOPES,
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
    except Exception as exc:
        message = google_api_error_message(exc)
        if not message:
            raise
        raise RuntimeError(message) from exc


def google_api_error_message(exc: Exception) -> str:
    """Return a user-facing message for common Google API failures."""
    if exc.__class__.__name__ != "HttpError":
        return ""

    status = getattr(getattr(exc, "resp", None), "status", None)
    details = str(exc).strip()
    lower_details = details.casefold()

    if (
        "accessnotconfigured" in lower_details
        or "api has not been used" in lower_details
        or "disabled" in lower_details
    ):
        return (
            "Google API request failed because a required API appears disabled. "
            "Enable both the Google Sheets API and Google Drive API in the Google "
            "Cloud project that owns google_client_secret.json, then retry. "
            f"Details: {details}"
        )

    if (
        "insufficient authentication scopes" in lower_details
        or "insufficientpermissions" in lower_details
        or "request had insufficient authentication scopes" in lower_details
    ):
        return (
            "google_token.json does not have sufficient Google OAuth scopes. "
            "Delete google_token.json and authorize again with both Google Sheets "
            "and Google Drive access. "
            f"Details: {details}"
        )

    if status in {401, 403}:
        return (
            "Google API authorization failed. Confirm google_token.json belongs to "
            "the Google account that owns the target Sheet/Drive folder and that "
            "the token has Sheets and Drive scopes. "
            f"Details: {details}"
        )

    return f"Google API request failed. Details: {details}"


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


def oauth_scope_set(scopes: Iterable[str]) -> set[str]:
    """Return a normalized scope set."""
    return {scope.strip() for scope in scopes if scope.strip()}


def token_declared_scopes(token_path: Path) -> set[str]:
    """Return scopes declared in a saved authorized-user token JSON."""
    try:
        token_info = json.loads(token_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError) as exc:
        raise RuntimeError(
            f"Could not read {token_path.name}. Delete it and authorize again. "
            f"Details: {exc}"
        ) from exc

    raw_scopes = token_info.get("scopes") or token_info.get("scope") or []
    if isinstance(raw_scopes, str):
        return oauth_scope_set(raw_scopes.split())
    if isinstance(raw_scopes, list):
        return oauth_scope_set(str(scope) for scope in raw_scopes)
    return set()


def validate_token_scopes(token_path: Path, scopes: list[str]) -> None:
    """Fail fast when a saved token clearly lacks required scopes."""
    declared_scopes = token_declared_scopes(token_path)
    if not declared_scopes:
        return

    missing_scopes = sorted(oauth_scope_set(scopes) - declared_scopes)
    if missing_scopes:
        missing = ", ".join(missing_scopes)
        raise RuntimeError(
            f"{token_path.name} is missing required Google OAuth scope(s): {missing}. "
            f"Delete {token_path.name} and authorize again with the shared Sheets "
            "and Drive scopes."
        )


def run_google_oauth_flow(
    *,
    client_secret_file: Path,
    token_file: Path,
    scopes: list[str],
    error_cls: type[RuntimeError],
) -> Any:
    """Run the desktop OAuth flow once and persist the authorized-user token."""
    if not client_secret_file.exists():
        raise error_cls(
            f"Missing {token_file.name} and {client_secret_file.name}. Download an "
            "OAuth client JSON for a Desktop app from Google Cloud, save it as "
            "google_client_secret.json or set GOOGLE_CLIENT_SECRET_FILE, then "
            "rerun to authorize in the browser and create google_token.json."
        )

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError as exc:
        raise error_cls(
            "Missing Google OAuth browser-flow support. Install dependencies with: "
            "python -m pip install -r requirements.txt"
        ) from exc

    try:
        flow = InstalledAppFlow.from_client_secrets_file(
            str(client_secret_file),
            scopes,
        )
        creds = flow.run_local_server(
            port=0,
            access_type="offline",
            prompt="consent",
        )
    except Exception as exc:
        raise error_cls(f"Google OAuth browser authorization failed: {exc}") from exc

    write_private_text_file(token_file, creds.to_json())
    return creds


def load_google_oauth_credentials(
    *,
    error_cls: type[RuntimeError],
    token_file: Path | None = None,
    client_secret_file: Path | None = None,
    auth_config: GoogleAuthConfig | None = None,
    scopes: list[str] = GOOGLE_OAUTH_SCOPES,
) -> Any:
    """Load, refresh, or create the shared authorized-user Google credentials."""
    credential_files = google_credential_files_for(
        "google",
        auth_config=auth_config,
        client_secret_file=client_secret_file,
        token_file=token_file,
    )
    client_secret_path = credential_files.client_secret_file
    token_path = credential_files.token_file

    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
    except ImportError as exc:
        raise error_cls(
            "Missing Google API packages. Install dependencies with: "
            "python -m pip install -r requirements.txt"
        ) from exc

    if token_path.exists():
        try:
            validate_token_scopes(token_path, scopes)
            creds = Credentials.from_authorized_user_file(str(token_path), scopes)
        except Exception as exc:
            if isinstance(exc, RuntimeError):
                raise error_cls(str(exc)) from exc
            raise error_cls(
                f"Could not read {token_path.name}. Delete it and authorize again. "
                f"Details: {exc}"
            ) from exc

        if not creds.has_scopes(scopes):
            missing_scopes = sorted(oauth_scope_set(scopes))
            raise error_cls(
                f"{token_path.name} does not include the required Google OAuth "
                f"scope(s): {', '.join(missing_scopes)}. Delete {token_path.name} "
                "and authorize again with both Google Sheets and Google Drive access."
            )

        if creds.valid:
            return creds

        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as exc:
                raise error_cls(
                    f"Could not refresh {token_path.name}. Delete it and authorize "
                    f"again. Details: {exc}"
                ) from exc
            write_private_text_file(token_path, creds.to_json())
            return creds

        if not client_secret_path.exists():
            raise error_cls(
                f"{token_path.name} is not refreshable, and {client_secret_path.name} "
                "is missing. Download an OAuth Desktop client JSON, save it as "
                "google_client_secret.json or set GOOGLE_CLIENT_SECRET_FILE, then "
                "authorize again."
            )

    return run_google_oauth_flow(
        client_secret_file=client_secret_path,
        token_file=token_path,
        scopes=scopes,
        error_cls=error_cls,
    )


def build_google_api_service(
    service_name: str,
    version: str,
    *,
    error_cls: type[RuntimeError],
    token_file: Path | None = None,
    client_secret_file: Path | None = None,
    auth_config: GoogleAuthConfig | None = None,
    scopes: list[str] = GOOGLE_OAUTH_SCOPES,
) -> Any:
    """Build an OAuth-authenticated Google API service."""
    try:
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise error_cls(
            "Missing Google API packages. Install dependencies with: "
            "python -m pip install -r requirements.txt"
        ) from exc

    creds = load_google_oauth_credentials(
        error_cls=error_cls,
        token_file=token_file,
        client_secret_file=client_secret_file,
        auth_config=auth_config,
        scopes=scopes,
    )

    return build_google_service(
        build,
        service_name,
        version,
        creds,
        error_cls=error_cls,
    )


def build_google_oauth_service(
    service_name: str,
    version: str,
    *,
    error_cls: type[RuntimeError],
    token_file: Path | None = None,
    client_secret_file: Path | None = None,
    auth_config: GoogleAuthConfig | None = None,
    scopes: list[str] = GOOGLE_OAUTH_SCOPES,
) -> Any:
    """Backward-compatible OAuth service builder."""
    return build_google_api_service(
        service_name,
        version,
        error_cls=error_cls,
        token_file=token_file,
        client_secret_file=client_secret_file,
        auth_config=auth_config,
        scopes=scopes,
    )


def build_google_drive_oauth_service(
    version: str,
    *,
    error_cls: type[RuntimeError],
    token_file: Path | None = None,
    client_secret_file: Path | None = None,
    auth_config: GoogleAuthConfig | None = None,
    scopes: list[str] = GOOGLE_OAUTH_SCOPES,
) -> Any:
    """Build a Google Drive API service from the shared OAuth token."""
    return build_google_oauth_service(
        "drive",
        version,
        error_cls=error_cls,
        token_file=token_file,
        client_secret_file=client_secret_file,
        auth_config=auth_config,
        scopes=scopes,
    )


def authorize_google_oauth(
    *,
    error_cls: type[RuntimeError] = RuntimeError,
    token_file: Path | None = None,
    client_secret_file: Path | None = None,
    auth_config: GoogleAuthConfig | None = None,
    scopes: list[str] = GOOGLE_OAUTH_SCOPES,
) -> Path:
    """Run browser authorization and return the token path."""
    credential_files = google_credential_files_for(
        "google",
        auth_config=auth_config,
        client_secret_file=client_secret_file,
        token_file=token_file,
    )
    run_google_oauth_flow(
        client_secret_file=credential_files.client_secret_file,
        token_file=credential_files.token_file,
        scopes=scopes,
        error_cls=error_cls,
    )
    return credential_files.token_file
