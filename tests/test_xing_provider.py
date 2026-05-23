"""Tests for the Xing provider integration."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from jobfinder.providers.xing import (
    build_actor_input,
    normalize_actor_item,
    run_actor_search,
)
from jobfinder.scraper.normalize import get_apply_url, get_job_url


def make_settings(**overrides: Any) -> SimpleNamespace:
    """Build the provider settings used by Xing tests."""
    values = {
        "xing_location": "Germany",
        "xing_discipline": "",
        "xing_remote": "",
        "xing_start_url": "",
        "xing_max_results_per_search": 100,
        "xing_max_pages": 10,
        "xing_use_apify_proxy": True,
        "xing_proxy_groups": ["RESIDENTIAL"],
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def sample_actor_item() -> dict[str, Any]:
    """Return a representative shahidirfan/Xing-Jobs-Scraper result."""
    return {
        "job_id": "148355491.3c4997",
        "slug": "berlin-data-analyst-148355491",
        "global_id": "urn:xing:jobs:148355491",
        "title": "Data Analyst",
        "company": "Acme Data GmbH",
        "discipline": "Technology",
        "location": "Berlin",
        "location_country": "Germany",
        "salary": "EUR 65,000 - EUR 80,000",
        "job_type": "Full-time",
        "remote": "Hybrid",
        "job_category": "Analytics",
        "keywords": ["Python", "SQL"],
        "matching_facts": [{"label": "Hybrid work"}],
        "date_posted": "2026-05-12T10:00:00Z",
        "active_until": "2026-06-12T10:00:00Z",
        "top_job": True,
        "company_id": "company-123",
        "company_logo": "https://www.xing.com/logo.png",
        "company_size": "1,001-5,000",
        "company_industry": "Technology",
        "company_city": "Berlin",
        "company_country": "Germany",
        "company_public_profile": "https://www.xing.com/pages/acme-data",
        "application_type": "external",
        "apply_url": "https://careers.example.com/jobs/148355491",
        "description_html": "<p>Build dashboards with Python and SQL.</p>",
        "description_text": "Build dashboards with Python and SQL.",
        "url": "https://www.xing.com/jobs/berlin-data-analyst-148355491",
    }


def test_build_actor_input_uses_xing_actor_schema():
    """Keyword searches should match the actor's supported input names."""
    payload = build_actor_input(
        make_settings(xing_max_results_per_search=25, xing_max_pages=5),
        "GIS analyst",
    )

    assert payload == {
        "keyword": "GIS analyst",
        "location": "Germany",
        "results_wanted": 25,
        "max_pages": 5,
        "proxyConfiguration": {
            "useApifyProxy": True,
            "apifyProxyGroups": ["RESIDENTIAL"],
        },
    }


def test_build_actor_input_uses_direct_url_without_keyword_filters():
    """Configured Xing URLs should run once without duplicate keyword payloads."""
    payload = build_actor_input(
        make_settings(
            xing_start_url="https://www.xing.com/jobs/t-remote?keywords=Remote",
        ),
        "GIS analyst",
    )

    assert payload["startUrl"] == "https://www.xing.com/jobs/t-remote?keywords=Remote"
    assert "keyword" not in payload
    assert "location" not in payload
    assert "discipline" not in payload


def test_normalize_actor_item_preserves_contract_and_internal_metadata():
    """Actor output should feed existing exporters without adding sheet columns."""
    job = normalize_actor_item(sample_actor_item())

    assert job["jobId"] == "148355491.3c4997"
    assert job["xingId"] == "148355491.3c4997"
    assert job["title"] == "Data Analyst"
    assert job["companyName"] == "Acme Data GmbH"
    assert job["companyDetails"]["id"] == "company-123"
    assert job["location"] == "Berlin, Germany"
    assert job["jobType"] == "Full-time"
    assert job["postedAt"] == "2026-05-12T10:00:00Z"
    assert job["jobUrl"] == "https://www.xing.com/jobs/berlin-data-analyst-148355491"
    assert job["applyUrl"] == "https://careers.example.com/jobs/148355491"
    assert "Build dashboards" in job["description"]
    assert "Xing structured metadata:" in job["description"]

    metadata = job["_jobfinder_xing_metadata"]
    assert metadata["salary"] == "EUR 65,000 - EUR 80,000"
    assert metadata["work_mode"] == "Hybrid"
    assert metadata["discipline"] == "Technology"
    assert metadata["keywords"] == ["Python", "SQL"]
    assert metadata["matching_facts"] == ["Hybrid work"]
    assert metadata["top_job"] is True


def test_normalized_urls_keep_xing_job_url_separate_from_apply_url():
    """Historical dedupe should see Xing URLs, while apply links stay separate."""
    job = normalize_actor_item(sample_actor_item())

    assert get_job_url(make_settings(), job) == (
        "https://www.xing.com/jobs/berlin-data-analyst-148355491"
    )
    assert get_apply_url(job) == "https://careers.example.com/jobs/148355491"


def test_run_actor_search_normalizes_actor_results():
    """Xing execution should isolate actor-specific output conversion."""
    calls: list[tuple[str, dict[str, Any], int]] = []

    def fake_runner(settings, actor_id, payload, max_items):
        calls.append((actor_id, payload, max_items))
        return [sample_actor_item()]

    jobs = run_actor_search(
        make_settings(),
        "shahidirfan~Xing-Jobs-Scraper",
        {"keyword": "GIS"},
        100,
        actor_runner=fake_runner,
    )

    assert calls == [("shahidirfan~Xing-Jobs-Scraper", {"keyword": "GIS"}, 100)]
    assert jobs[0]["jobId"] == "148355491.3c4997"
    assert jobs[0]["companyName"] == "Acme Data GmbH"
