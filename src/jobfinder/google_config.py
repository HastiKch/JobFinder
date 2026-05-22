"""Compatibility facade for Google credential configuration.

New code should import from ``jobfinder.integrations.google.credentials``.
"""

from __future__ import annotations

from jobfinder.integrations.google.credentials import (
    GOOGLE_CLIENT_SECRET_FILE_ENV,
    GOOGLE_DRIVE_TOKEN_FILE_ENV,
    GOOGLE_OAUTH_SCOPES,
    GOOGLE_TOKEN_FILE_ENV,
    GoogleAuthConfig,
    GoogleCredentialFiles,
    default_google_auth_config,
    google_credential_files_for,
    resolve_google_credential_path,
)

__all__ = [
    "GOOGLE_CLIENT_SECRET_FILE_ENV",
    "GOOGLE_DRIVE_TOKEN_FILE_ENV",
    "GOOGLE_OAUTH_SCOPES",
    "GOOGLE_TOKEN_FILE_ENV",
    "GoogleAuthConfig",
    "GoogleCredentialFiles",
    "default_google_auth_config",
    "google_credential_files_for",
    "resolve_google_credential_path",
]
