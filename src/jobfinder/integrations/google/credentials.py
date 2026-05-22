"""Configuration for Google API credential files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from jobfinder.env import EnvSettings
from jobfinder.paths import (
    GOOGLE_DRIVE_TOKEN_FILE,
    GOOGLE_SHARED_SERVICE_ACCOUNT_FILE,
    PROJECT_ROOT,
)

GOOGLE_SHARED_SERVICE_ACCOUNT_FILE_ENV = "GOOGLE_SERVICE_ACCOUNT_FILE"
GOOGLE_DRIVE_TOKEN_FILE_ENV = "GOOGLE_DRIVE_TOKEN_FILE"


@dataclass(frozen=True)
class GoogleAuthConfig:
    """Resolved local credential files for Google API clients."""

    service_account_file: Path
    drive_token_file: Path

    def service_account_file_for(self, service_name: str) -> Path:
        """Return the configured Google Sheets service-account key."""
        return self.service_account_file


@dataclass(frozen=True)
class GoogleCredentialFiles:
    """Credential files used to initialize one Google API client."""

    service_account_file: Path
    drive_token_file: Path


def resolve_google_credential_path(value: str, *, root: Path = PROJECT_ROOT) -> Path:
    """Resolve a credential path from configuration."""
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return root / path


def default_google_auth_config(env: EnvSettings | None = None) -> GoogleAuthConfig:
    """Return Google credential file settings from env and repository defaults."""
    settings = env or EnvSettings()
    shared_service_account_value = settings.get(GOOGLE_SHARED_SERVICE_ACCOUNT_FILE_ENV)
    drive_token_value = settings.get(GOOGLE_DRIVE_TOKEN_FILE_ENV)

    return GoogleAuthConfig(
        service_account_file=(
            resolve_google_credential_path(shared_service_account_value)
            if shared_service_account_value
            else GOOGLE_SHARED_SERVICE_ACCOUNT_FILE
        ),
        drive_token_file=(
            resolve_google_credential_path(drive_token_value)
            if drive_token_value
            else GOOGLE_DRIVE_TOKEN_FILE
        ),
    )


def google_credential_files_for(
    service_name: str,
    *,
    auth_config: GoogleAuthConfig | None = None,
    service_account_file: Path | None = None,
    drive_token_file: Path | None = None,
) -> GoogleCredentialFiles:
    """Resolve credential files for one Google API service."""
    config = auth_config or default_google_auth_config()
    return GoogleCredentialFiles(
        service_account_file=service_account_file
        or config.service_account_file_for(service_name),
        drive_token_file=drive_token_file or config.drive_token_file,
    )
