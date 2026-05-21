"""Tests for scraper normalization and deduplication behavior."""

from __future__ import annotations

from datetime import UTC
from types import SimpleNamespace

from jobfinder.scraper.normalize import (
    clean_job_description,
    merge_and_deduplicate,
    parse_applicant_count_value,
    parse_datetime_value,
)


def test_parse_applicant_count_handles_text_units_and_plus():
    """Applicant parser should handle common labels from scraper actors."""
    assert parse_applicant_count_value("25 applicants") == 25
    assert parse_applicant_count_value("1.2k applicants") == 1200
    assert parse_applicant_count_value("Over 100 applicants") == 101
    assert parse_applicant_count_value({"label": "51+ applicants"}) == 52


def test_clean_job_description_removes_html_without_flattening_lists():
    """HTML descriptions should become readable plain text."""
    raw = "<p>Hello<br>World</p><ul><li>GIS</li><li>Python</li></ul>"

    assert clean_job_description(raw) == "Hello\nWorld\n* GIS\n* Python"


def test_parse_datetime_value_ignores_unrepresentable_timestamps():
    """Bad provider timestamps should not crash scraper filtering or sorting."""
    settings = SimpleNamespace(posted_tz=UTC)

    assert parse_datetime_value(settings, "1e999") is None


def test_merge_and_deduplicate_collects_all_matched_keywords():
    """Deduplication should keep one job and remember all matching keywords."""
    jobs = [
        (
            "GIS",
            [
                {
                    "_source": "linkedin",
                    "jobId": "1",
                    "title": "Analyst",
                    "companyName": "GeoCo",
                    "location": "Berlin",
                }
            ],
        ),
        (
            "Python",
            [
                {
                    "_source": "linkedin",
                    "jobId": "2",
                    "title": "Analyst",
                    "companyName": "GeoCo GmbH",
                    "location": "Berlin, Germany",
                }
            ],
        ),
    ]

    merged = merge_and_deduplicate(jobs)

    assert len(merged) == 1
    assert merged[0]["keywords_matched"] == ["GIS", "Python"]


def test_merge_and_deduplicate_uses_allowed_cells_for_indeed_duplicates():
    """Indeed duplicates should merge by allowed identity cells, not actor keys."""
    jobs = [
        (
            "GIS",
            [
                {
                    "_source": "indeed",
                    "key": "abc123",
                    "title": "Analyst",
                    "companyName": "GeoCo",
                    "location": "Berlin",
                }
            ],
        ),
        (
            "Python",
            [
                {
                    "_source": "indeed",
                    "key": "xyz999",
                    "title": "Analyst",
                    "companyName": "GeoCo GmbH",
                    "location": "Berlin, Germany",
                }
            ],
        ),
    ]

    merged = merge_and_deduplicate(jobs)

    assert len(merged) == 1
    assert merged[0]["keywords_matched"] == ["GIS", "Python"]


def test_merge_and_deduplicate_uses_allowed_cells_for_stepstone_duplicates():
    """Stepstone duplicates should merge by allowed identity cells, not actor IDs."""
    jobs = [
        (
            "GIS",
            [
                {
                    "_source": "stepstone",
                    "stepstoneId": "12424623",
                    "title": "Analyst",
                    "companyName": "GeoCo",
                    "location": "Berlin",
                }
            ],
        ),
        (
            "Python",
            [
                {
                    "_source": "stepstone",
                    "id": "999999",
                    "title": "Analyst",
                    "companyName": "GeoCo GmbH",
                    "location": "Berlin, Germany",
                }
            ],
        ),
    ]

    merged = merge_and_deduplicate(jobs)

    assert len(merged) == 1
    assert merged[0]["keywords_matched"] == ["GIS", "Python"]
