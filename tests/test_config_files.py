"""Tests for user-editable configuration file loading."""

from __future__ import annotations

import pytest

from jobfinder.config_files import (
    ConfigFileError,
    config_int,
    config_list,
    config_str,
    load_filter_config,
    load_keywords,
)
from jobfinder.env import EnvSettings


def test_load_keywords_ignores_blank_lines_and_comments(tmp_path):
    """Keywords files should accept comments and blank lines."""
    path = tmp_path / "keywords.txt"
    path.write_text("\n# comment\nGIS\n remote sensing \n", encoding="utf-8")

    assert load_keywords(path) == ["GIS", "remote sensing"]


def test_load_keywords_rejects_empty_file(tmp_path):
    """Empty keyword files should fail with a config error."""
    path = tmp_path / "keywords.txt"
    path.write_text("# only comments\n\n", encoding="utf-8")

    with pytest.raises(ConfigFileError):
        load_keywords(path)


def test_filter_config_helpers_normalize_values(tmp_path):
    """Config helpers should coerce common JSON shapes."""
    path = tmp_path / "filters.json"
    path.write_text(
        '{"section": {"name": " Germany ", "limit": "42", "items": "A, B"}}',
        encoding="utf-8",
    )

    config = load_filter_config(path)

    assert config_str(config, "section", "name") == "Germany"
    assert config_int(config, "section", "limit", 0) == 42
    assert config_list(config, "section", "items", []) == ["A", "B"]


def test_env_settings_respects_explicit_empty_local_values(monkeypatch):
    """Passing an explicit empty mapping should not fall back to the real .env file."""
    monkeypatch.setattr(
        "jobfinder.env.load_local_env",
        lambda: pytest.fail("EnvSettings({}) unexpectedly loaded .env"),
    )

    settings = EnvSettings({})

    assert settings.get("MISSING_SETTING", "fallback") == "fallback"
