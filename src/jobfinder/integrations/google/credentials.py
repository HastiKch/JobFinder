"""Configuration for Google OAuth credential files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from jobfinder.env import EnvSettings
from jobfinder.paths import (
    GOOGLE_CLIENT_SECRET_FILE,
    GOOGLE_TOKEN_FILE,
    PROJECT_ROOT,
)

GOOGLE_CLIENT_SECRET_FILE_ENV = "GOOGLE_CLIENT_SECRET_FILE"
GOOGLE_TOKEN_FILE_ENV = "GOOGLE_TOKEN_FILE"

GOOGLE_DRIVE_TOKEN_FILE_ENV = "GOOGLE_DRIVE_TOKEN_FILE"
"""Deprecated token-file env var kept as a fallback for older local setups."""

GOOGLE_OAUTH_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]
"""Scopes required for Google Sheets reads/writes and Drive PDF uploads."""


@dataclass(frozen=True)
class GoogleAuthConfig:
    """Resolved local OAuth credential files for Google API clients."""

    client_secret_file: Path
    token_file: Path


@dataclass(frozen=True)
class GoogleCredentialFiles:
    """Credential files used to initialize one Google API client."""

    client_secret_file: Path
    token_file: Path


def resolve_google_credential_path(value: str, *, root: Path = PROJECT_ROOT) -> Path:
    """Resolve a credential path from configuration."""
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return root / path


def default_google_auth_config(env: EnvSettings | None = None) -> GoogleAuthConfig:
    """Return Google credential file settings from env and repository defaults."""
    settings = env or EnvSettings()
    client_secret_value = settings.get(GOOGLE_CLIENT_SECRET_FILE_ENV)
    token_value = settings.get(GOOGLE_TOKEN_FILE_ENV) or settings.get(
        GOOGLE_DRIVE_TOKEN_FILE_ENV
    )

    return GoogleAuthConfig(
        client_secret_file=(
            resolve_google_credential_path(client_secret_value)
            if client_secret_value
            else GOOGLE_CLIENT_SECRET_FILE
        ),
        token_file=(
            resolve_google_credential_path(token_value)
            if token_value
            else GOOGLE_TOKEN_FILE
        ),
    )


def google_credential_files_for(
    service_name: str,
    *,
    auth_config: GoogleAuthConfig | None = None,
    client_secret_file: Path | None = None,
    token_file: Path | None = None,
) -> GoogleCredentialFiles:
    """Resolve credential files for one Google API service."""
    config = auth_config or default_google_auth_config()
    return GoogleCredentialFiles(
        client_secret_file=client_secret_file or config.client_secret_file,
        token_file=token_file or config.token_file,
    )
