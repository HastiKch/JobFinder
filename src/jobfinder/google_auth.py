"""Compatibility facade for Google API client helpers.

New code should import from ``jobfinder.integrations.google.client``.
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

__all__ = [
    "DEFAULT_GOOGLE_API_RETRIES",
    "DEFAULT_GOOGLE_API_TIMEOUT_SECONDS",
    "build_authorized_http",
    "build_google_api_service",
    "build_google_drive_oauth_service",
    "build_google_service",
    "google_api_retries",
    "google_api_timeout_seconds",
    "google_execute",
    "write_private_text_file",
]
