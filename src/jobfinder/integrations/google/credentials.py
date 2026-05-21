"""Configuration for Google API credential files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from jobfinder.env import EnvSettings
from jobfinder.paths import (
    GOOGLE_DRIVE_SERVICE_ACCOUNT_FILE,
    GOOGLE_OAUTH_CLIENT_SECRET_FILE,
    GOOGLE_OAUTH_TOKEN_FILE,
    GOOGLE_SHARED_SERVICE_ACCOUNT_FILE,
    GOOGLE_SHEETS_SERVICE_ACCOUNT_FILE,
    PROJECT_ROOT,
)

GOOGLE_SHARED_SERVICE_ACCOUNT_FILE_ENV = "GOOGLE_SERVICE_ACCOUNT_FILE"
GOOGLE_SHEETS_SERVICE_ACCOUNT_FILE_ENV = "GOOGLE_SHEETS_SERVICE_ACCOUNT_FILE"
GOOGLE_DRIVE_SERVICE_ACCOUNT_FILE_ENV = "GOOGLE_DRIVE_SERVICE_ACCOUNT_FILE"
GOOGLE_OAUTH_CLIENT_SECRET_FILE_ENV = "GOOGLE_OAUTH_CLIENT_SECRET_FILE"
GOOGLE_OAUTH_TOKEN_FILE_ENV = "GOOGLE_OAUTH_TOKEN_FILE"


@dataclass(frozen=True)
class GoogleAuthConfig:
    """Resolved local credential files for Google API clients."""

    sheets_service_account_file: Path
    drive_service_account_file: Path
    oauth_client_secret_file: Path
    oauth_token_file: Path
    shared_service_account_file: Path = GOOGLE_SHARED_SERVICE_ACCOUNT_FILE

    def service_account_file_for(self, service_name: str) -> Path:
        """Return the configured service-account key for a Google API service."""
        service_account_files = {
            "drive": self.drive_service_account_file,
            "sheets": self.sheets_service_account_file,
        }
        return service_account_files.get(
            service_name.strip().lower(),
            self.shared_service_account_file,
        )


@dataclass(frozen=True)
class GoogleCredentialFiles:
    """Credential files used to initialize one Google API client."""

    service_account_file: Path
    oauth_client_secret_file: Path
    oauth_token_file: Path


def resolve_google_credential_path(value: str, *, root: Path = PROJECT_ROOT) -> Path:
    """Resolve a credential path from configuration."""
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return root / path


def _configured_path(
    env: EnvSettings,
    setting_name: str,
    default_path: Path,
) -> Path:
    configured_value = env.get(setting_name)
    if configured_value:
        return resolve_google_credential_path(configured_value)
    return default_path


def _service_account_path(
    env: EnvSettings,
    *,
    specific_setting_name: str,
    specific_default_path: Path,
    shared_setting_value: str,
    shared_default_path: Path,
) -> Path:
    specific_value = env.get(specific_setting_name)
    if specific_value:
        return resolve_google_credential_path(specific_value)
    if shared_setting_value:
        return resolve_google_credential_path(shared_setting_value)
    if specific_default_path.exists():
        return specific_default_path
    return shared_default_path


def default_google_auth_config(env: EnvSettings | None = None) -> GoogleAuthConfig:
    """Return Google credential file settings from env and repository defaults."""
    settings = env or EnvSettings()
    shared_service_account_value = settings.get(GOOGLE_SHARED_SERVICE_ACCOUNT_FILE_ENV)
    shared_service_account_file = (
        resolve_google_credential_path(shared_service_account_value)
        if shared_service_account_value
        else GOOGLE_SHARED_SERVICE_ACCOUNT_FILE
    )

    return GoogleAuthConfig(
        sheets_service_account_file=_service_account_path(
            settings,
            specific_setting_name=GOOGLE_SHEETS_SERVICE_ACCOUNT_FILE_ENV,
            specific_default_path=GOOGLE_SHEETS_SERVICE_ACCOUNT_FILE,
            shared_setting_value=shared_service_account_value,
            shared_default_path=shared_service_account_file,
        ),
        drive_service_account_file=_service_account_path(
            settings,
            specific_setting_name=GOOGLE_DRIVE_SERVICE_ACCOUNT_FILE_ENV,
            specific_default_path=GOOGLE_DRIVE_SERVICE_ACCOUNT_FILE,
            shared_setting_value=shared_service_account_value,
            shared_default_path=shared_service_account_file,
        ),
        oauth_client_secret_file=_configured_path(
            settings,
            GOOGLE_OAUTH_CLIENT_SECRET_FILE_ENV,
            GOOGLE_OAUTH_CLIENT_SECRET_FILE,
        ),
        oauth_token_file=_configured_path(
            settings,
            GOOGLE_OAUTH_TOKEN_FILE_ENV,
            GOOGLE_OAUTH_TOKEN_FILE,
        ),
        shared_service_account_file=shared_service_account_file,
    )


def google_credential_files_for(
    service_name: str,
    *,
    auth_config: GoogleAuthConfig | None = None,
    service_account_file: Path | None = None,
    oauth_client_secret_file: Path | None = None,
    oauth_token_file: Path | None = None,
) -> GoogleCredentialFiles:
    """Resolve credential files for one Google API service."""
    config = auth_config or default_google_auth_config()
    return GoogleCredentialFiles(
        service_account_file=(
            service_account_file or config.service_account_file_for(service_name)
        ),
        oauth_client_secret_file=(
            oauth_client_secret_file or config.oauth_client_secret_file
        ),
        oauth_token_file=oauth_token_file or config.oauth_token_file,
    )
