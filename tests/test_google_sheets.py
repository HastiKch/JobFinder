"""Tests for Google OAuth authentication helpers."""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from unittest.mock import ANY

import pytest

from jobfinder.env import EnvSettings
from jobfinder.integrations.google.client import (
    authorize_google_oauth,
    build_google_api_service,
    google_api_error_message,
    load_google_oauth_credentials,
)
from jobfinder.integrations.google.credentials import (
    GOOGLE_CLIENT_SECRET_FILE_ENV,
    GOOGLE_DRIVE_TOKEN_FILE_ENV,
    GOOGLE_OAUTH_SCOPES,
    GOOGLE_TOKEN_FILE_ENV,
    GoogleAuthConfig,
    default_google_auth_config,
)
from jobfinder.integrations.google.drive import build_google_drive_service
from jobfinder.integrations.google.sheets import build_google_sheets_service
from jobfinder.paths import PROJECT_ROOT


def install_fake_google_modules(
    monkeypatch,
    *,
    user_credentials_loader=None,
    build_func=None,
    flow_factory=None,
):
    """Install fake Google modules so auth tests do not need network packages."""
    google = types.ModuleType("google")
    google_auth = types.ModuleType("google.auth")
    google_transport = types.ModuleType("google.auth.transport")
    google_requests = types.ModuleType("google.auth.transport.requests")
    google_oauth2 = types.ModuleType("google.oauth2")
    user_credentials = types.ModuleType("google.oauth2.credentials")
    google_auth_httplib2 = types.ModuleType("google_auth_httplib2")
    httplib2 = types.ModuleType("httplib2")
    googleapiclient = types.ModuleType("googleapiclient")
    discovery = types.ModuleType("googleapiclient.discovery")
    google_auth_oauthlib = types.ModuleType("google_auth_oauthlib")
    flow_module = types.ModuleType("google_auth_oauthlib.flow")

    class UserCredentials:
        valid = True
        expired = False
        refresh_token = "refresh"

        def has_scopes(self, scopes):
            return True

        def refresh(self, request):
            self.valid = True

        def to_json(self):
            return '{"type":"authorized_user","scopes":[]}'

    class Request:
        pass

    class Http:
        def __init__(self, timeout):
            self.timeout = timeout

    class AuthorizedHttp:
        def __init__(self, credentials, http):
            self.credentials = credentials
            self.http = http

    class Flow:
        @staticmethod
        def from_client_secrets_file(filename, scopes):
            if flow_factory is None:
                pytest.fail("OAuth browser flow should not run.")
            return flow_factory(filename, scopes)

    def default_user_credentials_loader(filename, scopes):
        return UserCredentials()

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

    UserCredentials.from_authorized_user_file = staticmethod(
        user_credentials_loader or default_user_credentials_loader
    )
    google_requests.Request = Request
    user_credentials.Credentials = UserCredentials
    google_auth_httplib2.AuthorizedHttp = AuthorizedHttp
    httplib2.Http = Http
    discovery.build = build_func or default_build
    flow_module.InstalledAppFlow = Flow

    google.auth = google_auth
    google_auth.transport = google_transport
    google_transport.requests = google_requests
    google.oauth2 = google_oauth2
    google_oauth2.credentials = user_credentials
    googleapiclient.discovery = discovery
    google_auth_oauthlib.flow = flow_module

    modules = {
        "google": google,
        "google.auth": google_auth,
        "google.auth.transport": google_transport,
        "google.auth.transport.requests": google_requests,
        "google.oauth2": google_oauth2,
        "google.oauth2.credentials": user_credentials,
        "google_auth_httplib2": google_auth_httplib2,
        "httplib2": httplib2,
        "googleapiclient": googleapiclient,
        "googleapiclient.discovery": discovery,
        "google_auth_oauthlib": google_auth_oauthlib,
        "google_auth_oauthlib.flow": flow_module,
    }

    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)


def write_token(path: Path, scopes: list[str] | None = None) -> None:
    """Write a minimal authorized-user token file."""
    scopes = scopes if scopes is not None else GOOGLE_OAUTH_SCOPES
    path.write_text(
        json.dumps(
            {
                "type": "authorized_user",
                "client_id": "id",
                "client_secret": "secret",
                "refresh_token": "refresh",
                "scopes": scopes,
            }
        ),
        encoding="utf-8",
    )


def test_build_google_sheets_service_uses_shared_oauth_token(tmp_path, monkeypatch):
    """Sheets should authenticate with the shared authorized-user token."""
    token_file = tmp_path / "google_token.json"
    write_token(token_file)
    auth_config = GoogleAuthConfig(
        client_secret_file=tmp_path / "google_client_secret.json",
        token_file=token_file,
    )
    calls: dict[str, object] = {}

    class ValidCredentials:
        valid = True
        expired = False
        refresh_token = "refresh"

        def has_scopes(self, scopes):
            calls["scopes"] = scopes
            return True

    def fake_from_authorized_user_file(filename, scopes):
        calls["token_file"] = Path(filename)
        calls["loader_scopes"] = scopes
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
        return "sheets-service"

    install_fake_google_modules(
        monkeypatch,
        user_credentials_loader=fake_from_authorized_user_file,
        build_func=fake_build,
    )

    service = build_google_sheets_service(
        error_cls=RuntimeError,
        auth_config=auth_config,
    )

    assert service == "sheets-service"
    assert calls["token_file"] == token_file
    assert calls["scopes"] == GOOGLE_OAUTH_SCOPES
    assert calls["loader_scopes"] == GOOGLE_OAUTH_SCOPES
    assert calls["build"] == ("sheets", "v4", ANY, False)


def test_build_google_api_service_uses_requested_api_with_oauth(
    tmp_path, monkeypatch
):
    """Shared OAuth auth should build the requested Google API."""
    token_file = tmp_path / "google_token.json"
    write_token(token_file)
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
        token_file=token_file,
        scopes=GOOGLE_OAUTH_SCOPES,
    )

    assert service == "drive-service"
    assert calls["build"] == ("drive", "v3", ANY, False)


def test_missing_token_and_credentials_message(tmp_path, monkeypatch):
    """Missing OAuth files should point users at browser authorization setup."""
    install_fake_google_modules(monkeypatch)
    auth_config = GoogleAuthConfig(
        client_secret_file=tmp_path / "google_client_secret.json",
        token_file=tmp_path / "google_token.json",
    )

    with pytest.raises(RuntimeError, match="google_client_secret.json"):
        build_google_sheets_service(error_cls=RuntimeError, auth_config=auth_config)


def test_missing_token_runs_browser_authorization_when_credentials_exist(
    tmp_path, monkeypatch
):
    """The one-time OAuth flow should create google_token.json."""
    client_secret_file = tmp_path / "google_client_secret.json"
    token_file = tmp_path / "google_token.json"
    client_secret_file.write_text("{}", encoding="utf-8")
    calls: dict[str, object] = {}

    class CreatedCredentials:
        def to_json(self):
            return '{"type":"authorized_user","scopes":["scope"]}'

    class FakeFlow:
        def run_local_server(self, **kwargs):
            calls["run_local_server"] = kwargs
            return CreatedCredentials()

    def fake_flow_factory(filename, scopes):
        calls["client_secret_file"] = Path(filename)
        calls["scopes"] = scopes
        return FakeFlow()

    install_fake_google_modules(monkeypatch, flow_factory=fake_flow_factory)

    created = authorize_google_oauth(
        client_secret_file=client_secret_file,
        token_file=token_file,
        scopes=["scope"],
    )

    assert created == token_file
    assert calls["client_secret_file"] == client_secret_file
    assert calls["scopes"] == ["scope"]
    assert calls["run_local_server"] == {
        "port": 0,
        "access_type": "offline",
        "prompt": "consent",
    }
    assert token_file.read_text(encoding="utf-8") == (
        '{"type":"authorized_user","scopes":["scope"]}'
    )


def test_expired_token_refreshes_and_rewrites_file(tmp_path, monkeypatch):
    """Expired tokens should refresh automatically and persist the new token."""
    token_file = tmp_path / "google_token.json"
    write_token(token_file)

    class ExpiredCredentials:
        valid = False
        expired = True
        refresh_token = "refresh"

        def has_scopes(self, scopes):
            return True

        def refresh(self, request):
            self.valid = True

        def to_json(self):
            return '{"type":"authorized_user","refreshed":true}'

    install_fake_google_modules(
        monkeypatch,
        user_credentials_loader=lambda filename, scopes: ExpiredCredentials(),
    )

    creds = load_google_oauth_credentials(
        error_cls=RuntimeError,
        token_file=token_file,
    )

    assert creds.valid is True
    assert token_file.read_text(encoding="utf-8") == (
        '{"type":"authorized_user","refreshed":true}'
    )


def test_token_missing_required_scope_has_clear_error(tmp_path, monkeypatch):
    """Tokens created with too few scopes should fail before API calls."""
    token_file = tmp_path / "google_token.json"
    write_token(token_file, scopes=["https://www.googleapis.com/auth/drive"])
    install_fake_google_modules(monkeypatch)

    with pytest.raises(RuntimeError, match="missing required Google OAuth scope"):
        build_google_sheets_service(error_cls=RuntimeError, token_file=token_file)


def test_google_api_error_message_mentions_disabled_apis():
    """Disabled Sheets/Drive APIs should have a setup-oriented error."""

    class HttpError(Exception):
        def __str__(self):
            return "accessNotConfigured: API has not been used or is disabled"

    message = google_api_error_message(HttpError())

    assert "required API appears disabled" in message
    assert "Google Sheets API and Google Drive API" in message


def test_google_api_error_message_mentions_runtime_scope_failures():
    """Runtime 403 scope errors should tell users to recreate the token."""

    class HttpError(Exception):
        def __str__(self):
            return "Request had insufficient authentication scopes"

    message = google_api_error_message(HttpError())

    assert "google_token.json does not have sufficient Google OAuth scopes" in message
    assert "authorize again" in message


def test_build_google_drive_service_uses_shared_oauth_token(tmp_path, monkeypatch):
    """Drive should use the same authorized-user token as Sheets."""
    token_file = tmp_path / "google_token.json"
    write_token(token_file)
    auth_config = GoogleAuthConfig(
        client_secret_file=tmp_path / "google_client_secret.json",
        token_file=token_file,
    )
    calls: dict[str, object] = {}

    class ValidCredentials:
        valid = True
        expired = False
        refresh_token = "refresh"

        def has_scopes(self, scopes):
            calls["scopes"] = scopes
            return True

    def fake_from_authorized_user_file(filename, scopes):
        calls["token_file"] = Path(filename)
        return ValidCredentials()

    install_fake_google_modules(
        monkeypatch,
        user_credentials_loader=fake_from_authorized_user_file,
    )

    build_google_drive_service(error_cls=RuntimeError, auth_config=auth_config)

    assert calls["token_file"] == token_file
    assert calls["scopes"] == GOOGLE_OAUTH_SCOPES


def test_default_google_auth_config_resolves_oauth_env_paths(tmp_path, monkeypatch):
    """Credential path settings should resolve OAuth files."""
    monkeypatch.delenv(GOOGLE_CLIENT_SECRET_FILE_ENV, raising=False)
    monkeypatch.delenv(GOOGLE_TOKEN_FILE_ENV, raising=False)
    monkeypatch.delenv(GOOGLE_DRIVE_TOKEN_FILE_ENV, raising=False)
    settings = EnvSettings(
        local_values={
            GOOGLE_CLIENT_SECRET_FILE_ENV: str(tmp_path / "client-secret.json"),
            GOOGLE_TOKEN_FILE_ENV: str(tmp_path / "token.json"),
        }
    )

    auth_config = default_google_auth_config(settings)

    assert auth_config.client_secret_file == tmp_path / "client-secret.json"
    assert auth_config.token_file == tmp_path / "token.json"


def test_default_google_auth_config_accepts_legacy_drive_token_env(
    tmp_path, monkeypatch
):
    """The old Drive token env var should still point at the shared token."""
    monkeypatch.delenv(GOOGLE_CLIENT_SECRET_FILE_ENV, raising=False)
    monkeypatch.delenv(GOOGLE_TOKEN_FILE_ENV, raising=False)
    monkeypatch.delenv(GOOGLE_DRIVE_TOKEN_FILE_ENV, raising=False)
    settings = EnvSettings(
        local_values={
            GOOGLE_CLIENT_SECRET_FILE_ENV: str(tmp_path / "client-secret.json"),
            GOOGLE_DRIVE_TOKEN_FILE_ENV: str(tmp_path / "drive-token.json"),
        }
    )

    auth_config = default_google_auth_config(settings)

    assert auth_config.client_secret_file == tmp_path / "client-secret.json"
    assert auth_config.token_file == tmp_path / "drive-token.json"


def test_default_google_auth_config_resolves_relative_path(monkeypatch):
    """Relative OAuth paths should resolve from the project root."""
    monkeypatch.delenv(GOOGLE_CLIENT_SECRET_FILE_ENV, raising=False)
    monkeypatch.delenv(GOOGLE_TOKEN_FILE_ENV, raising=False)
    monkeypatch.delenv(GOOGLE_DRIVE_TOKEN_FILE_ENV, raising=False)
    settings = EnvSettings(
        local_values={
            GOOGLE_CLIENT_SECRET_FILE_ENV: "credentials/client-secret.json",
            GOOGLE_TOKEN_FILE_ENV: "credentials/google-token.json",
        }
    )

    auth_config = default_google_auth_config(settings)

    assert auth_config.client_secret_file == (
        PROJECT_ROOT / "credentials/client-secret.json"
    )
    assert auth_config.token_file == PROJECT_ROOT / "credentials/google-token.json"
