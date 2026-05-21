"""Tests for the combined scraper/evaluator pipeline CLI."""

from __future__ import annotations

import argparse

import pytest

from jobfinder.pipeline.cli import (
    PIPELINE_MODE_SCRAPE_AND_EVALUATE,
    PIPELINE_MODE_SCRAPE_ONLY,
    parse_pipeline_mode,
    parse_step_timeout_seconds,
    resolve_pipeline_mode,
    validate_required_settings,
)


def test_parse_pipeline_mode_accepts_user_facing_aliases():
    """Local and GitHub Actions mode names should resolve to canonical values."""
    assert parse_pipeline_mode("scrape") == PIPELINE_MODE_SCRAPE_ONLY
    assert parse_pipeline_mode("scrape_only") == PIPELINE_MODE_SCRAPE_ONLY
    assert parse_pipeline_mode("both") == PIPELINE_MODE_SCRAPE_AND_EVALUATE
    assert (
        parse_pipeline_mode("scrape_and_evaluate") == PIPELINE_MODE_SCRAPE_AND_EVALUATE
    )


def test_resolve_pipeline_mode_prefers_cli_over_env():
    """An explicit CLI mode should override the dotenv/environment fallback."""
    args = argparse.Namespace(mode="scrape_only")

    mode = resolve_pipeline_mode(
        args,
        {"JOBFINDER_PIPELINE_MODE": "scrape_and_evaluate"},
    )

    assert mode == PIPELINE_MODE_SCRAPE_ONLY


def test_parse_step_timeout_accepts_disabled_and_default_values():
    """Pipeline subprocesses should have a bounded default with explicit opt-out."""
    assert parse_step_timeout_seconds({}) == 21600
    assert (
        parse_step_timeout_seconds({"JOBFINDER_PIPELINE_STEP_TIMEOUT_SECONDS": "0"})
        is None
    )


def test_scrape_only_requires_apify_but_not_openai(monkeypatch):
    """Scrape-only mode should not block on evaluator-only secrets."""
    monkeypatch.delenv("APIFY_API_TOKEN", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    validate_required_settings(
        {"APIFY_API_TOKEN": "apify_api_real_token"},
        PIPELINE_MODE_SCRAPE_ONLY,
    )


def test_scrape_only_accepts_multiple_apify_tokens(monkeypatch):
    """The pipeline gate should accept semicolon-separated Apify token fallbacks."""
    monkeypatch.delenv("APIFY_API_TOKEN", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    validate_required_settings(
        {"APIFY_API_TOKEN": "apify_api_first;apify_api_second"},
        PIPELINE_MODE_SCRAPE_ONLY,
    )


def test_pipeline_rejects_too_many_apify_tokens(monkeypatch):
    """The GitHub secret should be capped to a bounded token list."""
    monkeypatch.delenv("APIFY_API_TOKEN", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    tokens = [f"apify_api_{idx}" for idx in range(13)]

    with pytest.raises(SystemExit, match="at most 12"):
        validate_required_settings(
            {"APIFY_API_TOKEN": ";".join(tokens)},
            PIPELINE_MODE_SCRAPE_ONLY,
        )


def test_scrape_and_evaluate_requires_openai_key(monkeypatch):
    """The full pipeline still needs the OpenAI key before it starts."""
    monkeypatch.delenv("APIFY_API_TOKEN", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(SystemExit) as excinfo:
        validate_required_settings(
            {"APIFY_API_TOKEN": "apify_api_real_token"},
            PIPELINE_MODE_SCRAPE_AND_EVALUATE,
        )

    assert "OPENAI_API_KEY" in str(excinfo.value)
