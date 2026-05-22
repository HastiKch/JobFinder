"""Compatibility facade for Google credential configuration.

New code should import from ``jobfinder.integrations.google.credentials``.
"""

from __future__ import annotations

from jobfinder.integrations.google.credentials import (
    GOOGLE_DRIVE_TOKEN_FILE_ENV,
    GOOGLE_SHARED_SERVICE_ACCOUNT_FILE_ENV,
    GoogleAuthConfig,
    GoogleCredentialFiles,
    default_google_auth_config,
    google_credential_files_for,
    resolve_google_credential_path,
)

__all__ = [
    "GOOGLE_DRIVE_TOKEN_FILE_ENV",
    "GOOGLE_SHARED_SERVICE_ACCOUNT_FILE_ENV",
    "GoogleAuthConfig",
    "GoogleCredentialFiles",
    "default_google_auth_config",
    "google_credential_files_for",
    "resolve_google_credential_path",
]
