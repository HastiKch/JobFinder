"""Compatibility facade for Google API client helpers.

New code should import from ``jobfinder.integrations.google.client``.
"""

from __future__ import annotations

from jobfinder.integrations.google.client import (
    DEFAULT_GOOGLE_API_RETRIES,
    DEFAULT_GOOGLE_API_TIMEOUT_SECONDS,
    authorize_google_oauth,
    build_authorized_http,
    build_google_api_service,
    build_google_drive_oauth_service,
    build_google_oauth_service,
    build_google_service,
    google_api_error_message,
    google_api_retries,
    google_api_timeout_seconds,
    google_execute,
    load_google_oauth_credentials,
    write_private_text_file,
)

__all__ = [
    "DEFAULT_GOOGLE_API_RETRIES",
    "DEFAULT_GOOGLE_API_TIMEOUT_SECONDS",
    "authorize_google_oauth",
    "build_authorized_http",
    "build_google_api_service",
    "build_google_drive_oauth_service",
    "build_google_oauth_service",
    "build_google_service",
    "google_api_error_message",
    "google_api_retries",
    "google_api_timeout_seconds",
    "google_execute",
    "load_google_oauth_credentials",
    "write_private_text_file",
]


def main() -> int:
    """Authorize Google OAuth locally and save google_token.json."""
    try:
        token_path = authorize_google_oauth()
    except RuntimeError as exc:
        print(exc)
        return 1
    print(f"Created {token_path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
