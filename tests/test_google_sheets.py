"""Tests for Google service-account authentication helpers."""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from jobfinder.env import EnvSettings
from jobfinder.integrations.google.client import build_google_api_service
from jobfinder.integrations.google.credentials import (
    GOOGLE_SHARED_SERVICE_ACCOUNT_FILE_ENV,
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
    build_func=None,
):
    """Install fake Google modules so auth tests do not need network packages."""
    google = types.ModuleType("google")
    google_oauth2 = types.ModuleType("google.oauth2")
    service_account = types.ModuleType("google.oauth2.service_account")
    google_auth_httplib2 = types.ModuleType("google_auth_httplib2")
    httplib2 = types.ModuleType("httplib2")
    googleapiclient = types.ModuleType("googleapiclient")
    discovery = types.ModuleType("googleapiclient.discovery")

    class ServiceAccountCredentials:
        pass

    class Http:
        def __init__(self, timeout):
            self.timeout = timeout

    class AuthorizedHttp:
        def __init__(self, credentials, http):
            self.credentials = credentials
            self.http = http

    def default_service_account_loader(filename, scopes):
        return "service-account-creds"

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
    service_account.Credentials = ServiceAccountCredentials
    google_auth_httplib2.AuthorizedHttp = AuthorizedHttp
    httplib2.Http = Http
    discovery.build = build_func or default_build

    google.oauth2 = google_oauth2
    google_oauth2.service_account = service_account
    googleapiclient.discovery = discovery

    modules = {
        "google": google,
        "google.oauth2": google_oauth2,
        "google.oauth2.service_account": service_account,
        "google_auth_httplib2": google_auth_httplib2,
        "httplib2": httplib2,
        "googleapiclient": googleapiclient,
        "googleapiclient.discovery": discovery,
    }

    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)


def test_build_google_sheets_service_uses_service_account(tmp_path, monkeypatch):
    """Sheets should authenticate with the shared service-account key."""
    service_account_file = tmp_path / "google_service_account.json"
    service_account_file.write_text("{}", encoding="utf-8")
    calls: dict[str, object] = {}

    def fake_from_service_account_file(filename, scopes):
        calls["service_account_file"] = Path(filename)
        calls["scopes"] = scopes
        return "service-account-creds"

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
        build_func=fake_build,
    )

    service = build_google_sheets_service(
        error_cls=RuntimeError,
        service_account_file=service_account_file,
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )

    assert service == "sheets-service"
    assert calls["service_account_file"] == service_account_file
    assert calls["scopes"] == ["https://www.googleapis.com/auth/spreadsheets"]
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
        scopes=["https://www.googleapis.com/auth/drive"],
    )

    assert service == "drive-service"
    assert calls["build"] == (
        "drive",
        "v3",
        "service-account-creds",
        False,
    )


def test_build_google_sheets_service_missing_credentials_message(tmp_path, monkeypatch):
    """Missing Google auth files should point users at service-account setup."""
    install_fake_google_modules(monkeypatch)
    with pytest.raises(RuntimeError, match="google_service_account.json"):
        build_google_sheets_service(
            error_cls=RuntimeError,
            service_account_file=tmp_path / "google_service_account.json",
        )


def test_build_google_sheets_service_uses_configured_shared_credentials(
    tmp_path, monkeypatch
):
    """Sheets should use the configured shared service-account key."""
    service_account_file = tmp_path / "google_service_account.json"
    service_account_file.write_text("{}", encoding="utf-8")
    auth_config = GoogleAuthConfig(service_account_file=service_account_file)
    calls: dict[str, object] = {}

    def fake_from_service_account_file(filename, scopes):
        calls["service_account_file"] = Path(filename)
        return "service-account-creds"

    install_fake_google_modules(
        monkeypatch,
        service_account_loader=fake_from_service_account_file,
    )

    build_google_sheets_service(error_cls=RuntimeError, auth_config=auth_config)

    assert calls["service_account_file"] == service_account_file


def test_build_google_drive_service_uses_configured_shared_credentials(
    tmp_path, monkeypatch
):
    """Drive should use the same configured service-account key."""
    service_account_file = tmp_path / "google_service_account.json"
    service_account_file.write_text("{}", encoding="utf-8")
    auth_config = GoogleAuthConfig(service_account_file=service_account_file)
    calls: dict[str, object] = {}

    def fake_from_service_account_file(filename, scopes):
        calls["service_account_file"] = Path(filename)
        calls["scopes"] = scopes
        return "service-account-creds"

    install_fake_google_modules(
        monkeypatch,
        service_account_loader=fake_from_service_account_file,
    )

    build_google_drive_service(error_cls=RuntimeError, auth_config=auth_config)

    assert calls["service_account_file"] == service_account_file
    assert calls["scopes"] == ["https://www.googleapis.com/auth/drive"]


def test_default_google_auth_config_resolves_shared_env_path(tmp_path, monkeypatch):
    """Credential path settings should resolve through one shared service account."""
    monkeypatch.delenv(GOOGLE_SHARED_SERVICE_ACCOUNT_FILE_ENV, raising=False)
    settings = EnvSettings(
        local_values={
            GOOGLE_SHARED_SERVICE_ACCOUNT_FILE_ENV: str(
                tmp_path / "shared-service-account.json"
            ),
        }
    )

    auth_config = default_google_auth_config(settings)

    assert auth_config.service_account_file == (
        tmp_path / "shared-service-account.json"
    )


def test_default_google_auth_config_resolves_relative_path(monkeypatch):
    """Relative service-account paths should resolve from the project root."""
    monkeypatch.delenv(GOOGLE_SHARED_SERVICE_ACCOUNT_FILE_ENV, raising=False)
    settings = EnvSettings(
        local_values={
            GOOGLE_SHARED_SERVICE_ACCOUNT_FILE_ENV: "credentials/google.json",
        }
    )

    auth_config = default_google_auth_config(settings)

    assert auth_config.service_account_file == PROJECT_ROOT / "credentials/google.json"
