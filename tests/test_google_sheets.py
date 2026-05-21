"""Tests for Google Sheets authentication helpers."""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from jobfinder.env import EnvSettings
from jobfinder.integrations.google.client import build_google_api_service
from jobfinder.integrations.google.credentials import (
    GOOGLE_DRIVE_SERVICE_ACCOUNT_FILE_ENV,
    GOOGLE_OAUTH_CLIENT_SECRET_FILE_ENV,
    GOOGLE_OAUTH_TOKEN_FILE_ENV,
    GOOGLE_SHARED_SERVICE_ACCOUNT_FILE_ENV,
    GOOGLE_SHEETS_SERVICE_ACCOUNT_FILE_ENV,
    GoogleAuthConfig,
    default_google_auth_config,
)
from jobfinder.integrations.google.drive import build_google_drive_service
from jobfinder.integrations.google.sheets import build_google_sheets_service
from jobfinder.paths import PROJECT_ROOT


def install_fake_google_modules(
    monkeypatch,
    *,
    service_account_loader=None,
    user_credentials_loader=None,
    build_func=None,
):
    """Install fake Google modules so auth tests do not need network packages."""
    google = types.ModuleType("google")
    google_auth = types.ModuleType("google.auth")
    google_transport = types.ModuleType("google.auth.transport")
    google_requests = types.ModuleType("google.auth.transport.requests")
    google_oauth2 = types.ModuleType("google.oauth2")
    service_account = types.ModuleType("google.oauth2.service_account")
    user_credentials = types.ModuleType("google.oauth2.credentials")
    google_auth_oauthlib = types.ModuleType("google_auth_oauthlib")
    google_auth_flow = types.ModuleType("google_auth_oauthlib.flow")
    google_auth_httplib2 = types.ModuleType("google_auth_httplib2")
    httplib2 = types.ModuleType("httplib2")
    googleapiclient = types.ModuleType("googleapiclient")
    discovery = types.ModuleType("googleapiclient.discovery")

    class Request:
        pass

    class ServiceAccountCredentials:
        pass

    class UserCredentials:
        pass

    class InstalledAppFlow:
        @classmethod
        def from_client_secrets_file(cls, filename, scopes):
            return cls()

        def run_local_server(self, port):
            return None

    class Http:
        def __init__(self, timeout):
            self.timeout = timeout

    class AuthorizedHttp:
        def __init__(self, credentials, http):
            self.credentials = credentials
            self.http = http

    def default_service_account_loader(filename, scopes):
        return "service-account-creds"

    def default_user_credentials_loader(filename, scopes):
        pytest.fail("OAuth token auth should not run.")

    def default_build(
        service_name, version, credentials=None, http=None, cache_discovery=False
    ):
        credentials = credentials or getattr(http, "credentials", None)
        return {
            "service_name": service_name,
            "version": version,
            "credentials": credentials,
            "cache_discovery": cache_discovery,
        }

    ServiceAccountCredentials.from_service_account_file = staticmethod(
        service_account_loader or default_service_account_loader
    )
    UserCredentials.from_authorized_user_file = staticmethod(
        user_credentials_loader or default_user_credentials_loader
    )
    google_requests.Request = Request
    service_account.Credentials = ServiceAccountCredentials
    user_credentials.Credentials = UserCredentials
    google_auth_flow.InstalledAppFlow = InstalledAppFlow
    google_auth_httplib2.AuthorizedHttp = AuthorizedHttp
    httplib2.Http = Http
    discovery.build = build_func or default_build

    google.auth = google_auth
    google_auth.transport = google_transport
    google_transport.requests = google_requests
    google.oauth2 = google_oauth2
    google_oauth2.service_account = service_account
    google_oauth2.credentials = user_credentials
    google_auth_oauthlib.flow = google_auth_flow
    googleapiclient.discovery = discovery

    modules = {
        "google": google,
        "google.auth": google_auth,
        "google.auth.transport": google_transport,
        "google.auth.transport.requests": google_requests,
        "google.oauth2": google_oauth2,
        "google.oauth2.service_account": service_account,
        "google.oauth2.credentials": user_credentials,
        "google_auth_oauthlib": google_auth_oauthlib,
        "google_auth_oauthlib.flow": google_auth_flow,
        "google_auth_httplib2": google_auth_httplib2,
        "httplib2": httplib2,
        "googleapiclient": googleapiclient,
        "googleapiclient.discovery": discovery,
    }

    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)


def test_build_google_sheets_service_prefers_service_account(tmp_path, monkeypatch):
    """A service-account key should bypass the old OAuth token path."""
    service_account_file = tmp_path / "google_service_account.json"
    token_file = tmp_path / "google_token.json"
    service_account_file.write_text("{}", encoding="utf-8")
    token_file.write_text("old oauth token", encoding="utf-8")

    calls: dict[str, object] = {}

    def fake_from_service_account_file(filename, scopes):
        calls["service_account_file"] = Path(filename)
        calls["scopes"] = scopes
        return "service-account-creds"

    def fail_from_authorized_user_file(filename, scopes):
        pytest.fail("OAuth token auth should not run when service account exists.")

    def fake_build(
        service_name,
        version,
        credentials=None,
        http=None,
        cache_discovery=False,
    ):
        credentials = credentials or getattr(http, "credentials", None)
        calls["build"] = (service_name, version, credentials, cache_discovery)
        return "sheets-service"

    install_fake_google_modules(
        monkeypatch,
        service_account_loader=fake_from_service_account_file,
        user_credentials_loader=fail_from_authorized_user_file,
        build_func=fake_build,
    )

    service = build_google_sheets_service(
        error_cls=RuntimeError,
        service_account_file=service_account_file,
        token_file=token_file,
        client_secret_file=tmp_path / "google_client_secret.json",
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )

    assert service == "sheets-service"
    assert calls["service_account_file"] == service_account_file
    assert calls["build"] == (
        "sheets",
        "v4",
        "service-account-creds",
        False,
    )


def test_build_google_api_service_uses_requested_api_for_service_account(
    tmp_path, monkeypatch
):
    """Shared service-account auth should build the requested Google API."""
    service_account_file = tmp_path / "google_service_account.json"
    service_account_file.write_text("{}", encoding="utf-8")
    calls: dict[str, object] = {}

    def fake_build(
        service_name,
        version,
        credentials=None,
        http=None,
        cache_discovery=False,
    ):
        credentials = credentials or getattr(http, "credentials", None)
        calls["build"] = (service_name, version, credentials, cache_discovery)
        return "drive-service"

    install_fake_google_modules(monkeypatch, build_func=fake_build)

    service = build_google_api_service(
        "drive",
        "v3",
        error_cls=RuntimeError,
        service_account_file=service_account_file,
        token_file=tmp_path / "google_token.json",
        client_secret_file=tmp_path / "google_client_secret.json",
        scopes=["https://www.googleapis.com/auth/drive"],
    )

    assert service == "drive-service"
    assert calls["build"] == (
        "drive",
        "v3",
        "service-account-creds",
        False,
    )


def test_build_google_api_service_can_prefer_oauth_token_over_service_account(
    tmp_path, monkeypatch
):
    """Drive uploads for personal accounts should be able to use user OAuth."""
    service_account_file = tmp_path / "google_service_account.json"
    token_file = tmp_path / "google_token.json"
    service_account_file.write_text("{}", encoding="utf-8")
    token_file.write_text("{}", encoding="utf-8")
    calls: dict[str, object] = {}

    class ValidCredentials:
        valid = True

        def has_scopes(self, scopes):
            calls["scopes"] = scopes
            return True

    def fail_from_service_account_file(filename, scopes):
        pytest.fail("OAuth token should be preferred for this Drive service.")

    def fake_from_authorized_user_file(filename, scopes):
        calls["token_file"] = Path(filename)
        return ValidCredentials()

    def fake_build(
        service_name,
        version,
        credentials=None,
        http=None,
        cache_discovery=False,
    ):
        credentials = credentials or getattr(http, "credentials", None)
        calls["build"] = (service_name, version, credentials, cache_discovery)
        return "drive-service"

    install_fake_google_modules(
        monkeypatch,
        service_account_loader=fail_from_service_account_file,
        user_credentials_loader=fake_from_authorized_user_file,
        build_func=fake_build,
    )

    service = build_google_api_service(
        "drive",
        "v3",
        error_cls=RuntimeError,
        service_account_file=service_account_file,
        token_file=token_file,
        client_secret_file=tmp_path / "google_client_secret.json",
        scopes=["https://www.googleapis.com/auth/drive"],
        prefer_service_account=False,
    )

    assert service == "drive-service"
    assert calls["token_file"] == token_file
    service_name, version, credentials, cache_discovery = calls["build"]
    assert (service_name, version, cache_discovery) == ("drive", "v3", False)
    assert isinstance(credentials, ValidCredentials)


def test_build_google_sheets_service_missing_credentials_message(tmp_path, monkeypatch):
    """Missing Google auth files should point users at service-account setup."""
    install_fake_google_modules(monkeypatch)
    with pytest.raises(RuntimeError, match="service account"):
        build_google_sheets_service(
            error_cls=RuntimeError,
            service_account_file=tmp_path / "google_service_account.json",
            token_file=tmp_path / "google_token.json",
            client_secret_file=tmp_path / "google_client_secret.json",
        )


def test_build_google_sheets_service_rewrites_oauth_token_privately(
    tmp_path, monkeypatch
):
    """Refreshed OAuth tokens should be saved with restrictive permissions."""
    token_file = tmp_path / "google_token.json"
    token_file.write_text("old oauth token", encoding="utf-8")

    class RefreshableCredentials:
        valid = False
        expired = True
        refresh_token = "refresh-token"

        def has_scopes(self, scopes):
            return True

        def refresh(self, request):
            self.valid = True

        def to_json(self):
            return '{"token": "new"}'

    def fake_from_authorized_user_file(filename, scopes):
        return RefreshableCredentials()

    install_fake_google_modules(
        monkeypatch,
        user_credentials_loader=fake_from_authorized_user_file,
    )

    build_google_sheets_service(
        error_cls=RuntimeError,
        service_account_file=tmp_path / "google_service_account.json",
        token_file=token_file,
        client_secret_file=tmp_path / "google_client_secret.json",
    )

    assert token_file.read_text(encoding="utf-8") == '{"token": "new"}'
    assert token_file.stat().st_mode & 0o777 == 0o600


def test_build_google_sheets_service_uses_configured_sheets_credentials(
    tmp_path, monkeypatch
):
    """Sheets should use its configured service-account key."""
    sheets_service_account_file = tmp_path / "google_sheets_service_account.json"
    drive_service_account_file = tmp_path / "google_drive_service_account.json"
    sheets_service_account_file.write_text("{}", encoding="utf-8")
    auth_config = GoogleAuthConfig(
        sheets_service_account_file=sheets_service_account_file,
        drive_service_account_file=drive_service_account_file,
        oauth_client_secret_file=tmp_path / "google_client_secret.json",
        oauth_token_file=tmp_path / "google_token.json",
    )
    calls: dict[str, object] = {}

    def fake_from_service_account_file(filename, scopes):
        calls["service_account_file"] = Path(filename)
        return "sheets-service-account-creds"

    install_fake_google_modules(
        monkeypatch,
        service_account_loader=fake_from_service_account_file,
    )

    build_google_sheets_service(error_cls=RuntimeError, auth_config=auth_config)

    assert calls["service_account_file"] == sheets_service_account_file


def test_build_google_drive_service_uses_configured_drive_credentials_fallback(
    tmp_path, monkeypatch
):
    """Drive should fall back to its configured service-account key."""
    sheets_service_account_file = tmp_path / "google_sheets_service_account.json"
    drive_service_account_file = tmp_path / "google_drive_service_account.json"
    drive_service_account_file.write_text("{}", encoding="utf-8")
    auth_config = GoogleAuthConfig(
        sheets_service_account_file=sheets_service_account_file,
        drive_service_account_file=drive_service_account_file,
        oauth_client_secret_file=tmp_path / "google_client_secret.json",
        oauth_token_file=tmp_path / "google_token.json",
    )
    calls: dict[str, object] = {}

    def fake_from_service_account_file(filename, scopes):
        calls["service_account_file"] = Path(filename)
        calls["scopes"] = scopes
        return "drive-service-account-creds"

    install_fake_google_modules(
        monkeypatch,
        service_account_loader=fake_from_service_account_file,
    )

    build_google_drive_service(error_cls=RuntimeError, auth_config=auth_config)

    assert calls["service_account_file"] == drive_service_account_file
    assert calls["scopes"] == ["https://www.googleapis.com/auth/drive"]


def test_default_google_auth_config_resolves_service_specific_env_paths(
    tmp_path, monkeypatch
):
    """Credential path settings should live in one typed config object."""
    env_names = [
        GOOGLE_SHARED_SERVICE_ACCOUNT_FILE_ENV,
        GOOGLE_SHEETS_SERVICE_ACCOUNT_FILE_ENV,
        GOOGLE_DRIVE_SERVICE_ACCOUNT_FILE_ENV,
        GOOGLE_OAUTH_CLIENT_SECRET_FILE_ENV,
        GOOGLE_OAUTH_TOKEN_FILE_ENV,
    ]
    for name in env_names:
        monkeypatch.delenv(name, raising=False)

    settings = EnvSettings(
        local_values={
            GOOGLE_SHARED_SERVICE_ACCOUNT_FILE_ENV: str(
                tmp_path / "shared-service-account.json"
            ),
            GOOGLE_SHEETS_SERVICE_ACCOUNT_FILE_ENV: str(
                tmp_path / "sheets-service-account.json"
            ),
            GOOGLE_DRIVE_SERVICE_ACCOUNT_FILE_ENV: "drive-service-account.json",
            GOOGLE_OAUTH_CLIENT_SECRET_FILE_ENV: str(tmp_path / "oauth-client.json"),
            GOOGLE_OAUTH_TOKEN_FILE_ENV: str(tmp_path / "oauth-token.json"),
        }
    )

    auth_config = default_google_auth_config(settings)

    assert auth_config.sheets_service_account_file == (
        tmp_path / "sheets-service-account.json"
    )
    assert auth_config.drive_service_account_file == (
        PROJECT_ROOT / "drive-service-account.json"
    )
    assert auth_config.oauth_client_secret_file == tmp_path / "oauth-client.json"
    assert auth_config.oauth_token_file == tmp_path / "oauth-token.json"
    assert auth_config.shared_service_account_file == (
        tmp_path / "shared-service-account.json"
    )
