"""Tests for the Stepstone provider integration."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from jobfinder.providers.stepstone import (
    build_actor_input,
    normalize_actor_item,
    run_actor_search,
)
from jobfinder.scraper.normalize import get_apply_url, get_job_url


def make_settings(**overrides: Any) -> SimpleNamespace:
    """Build the provider settings used by Stepstone tests."""
    values = {
        "published_at": "r86400",
        "stepstone_location": "Germany",
        "stepstone_category": "",
        "stepstone_start_urls": [],
        "stepstone_max_results_per_search": 500,
        "stepstone_max_concurrency": 10,
        "stepstone_min_concurrency": 1,
        "stepstone_max_request_retries": 3,
        "stepstone_use_apify_proxy": True,
        "stepstone_proxy_groups": ["RESIDENTIAL"],
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def sample_actor_item() -> dict[str, Any]:
    """Return a representative memo23/stepstone-search-cheerio-ppr result."""
    return {
        "id": 12424623,
        "title": "IT Administrators (m/f/d) full-time",
        "labels": [{"label": "Schnelle Bewerbung", "type": "QUICK_APPLY"}],
        "url": (
            "/stellenangebote--IT-Administrators-m-f-d-full-time-Cologne-Germany-"
            "Marketplace-Hub--12424623-inline.html?rltr=1_1_25"
        ),
        "companyId": 253207,
        "companyName": "LOW Teq GmbH",
        "companyUrl": "https://www.stepstone.de/cmp/de/low-teq-gmbh-253207/jobs",
        "companyLogoUrl": "https://www.stepstone.de/upload_de/logo/alt/104231.png",
        "datePosted": "2025-11-30T00:09:47+01:00",
        "location": "Cologne, Germany",
        "isAnonymous": False,
        "salary": "",
        "unifiedSalary": {
            "min": 60000,
            "max": 76000,
            "currency": "EUR",
            "period": "year",
            "salaryAvailable": True,
        },
        "workFromHome": "2",
        "section": "main",
        "topLabels": ["Top Job"],
        "skills": ["Python", "SQL"],
        "textSnippet": (
            "You will support <strong>IT</strong> systems and work in a "
            "Home Office friendly team."
        ),
        "isHighlighted": True,
        "isSponsored": False,
        "isTopJob": True,
        "partnership": {"isPartnershipJob": False},
    }


def test_build_actor_input_uses_keyword_location_and_date_bucket():
    """Keyword searches should match the actor's supported input names."""
    payload = build_actor_input(
        make_settings(published_at="r90000", stepstone_max_results_per_search=250),
        "Data Analyst",
    )

    assert payload == {
        "keyword": "data-analyst",
        "location": "germany",
        "postedWithin": "3",
        "maxItems": 250,
        "maxConcurrency": 10,
        "minConcurrency": 1,
        "maxRequestRetries": 3,
        "proxy": {
            "useApifyProxy": True,
            "apifyProxyGroups": ["RESIDENTIAL"],
        },
    }


def test_build_actor_input_uses_direct_urls_without_keyword_filters():
    """Configured Stepstone URLs should run once without duplicate keyword payloads."""
    payload = build_actor_input(
        make_settings(
            stepstone_start_urls=["https://www.stepstone.de/jobs/software"],
        ),
        "Data Analyst",
    )

    assert payload["startUrls"] == [{"url": "https://www.stepstone.de/jobs/software"}]
    assert "keyword" not in payload
    assert "location" not in payload
    assert "postedWithin" not in payload


def test_normalize_actor_item_preserves_contract_and_internal_metadata():
    """Actor output should feed existing exporters without adding sheet columns."""
    job = normalize_actor_item(sample_actor_item())

    assert job["jobId"] == "12424623"
    assert job["stepstoneId"] == "12424623"
    assert job["title"] == "IT Administrators (m/f/d) full-time"
    assert job["companyName"] == "LOW Teq GmbH"
    assert job["location"] == "Cologne, Germany"
    assert job["jobType"] == "full-time"
    assert job["postedAt"] == "2025-11-30T00:09:47+01:00"
    assert job["jobUrl"].startswith("https://www.stepstone.de/stellenangebote--")
    assert "IT systems" in job["description"]
    assert "Stepstone structured metadata:" in job["description"]

    metadata = job["_jobfinder_stepstone_metadata"]
    assert metadata["salary"] == "EUR 60,000-76,000 / year"
    assert metadata["work_mode"] == "Remote"
    assert metadata["labels"] == ["Schnelle Bewerbung", "Top Job"]
    assert metadata["skills"] == ["Python", "SQL"]
    assert metadata["is_highlighted"] is True
    assert metadata["is_top_job"] is True


def test_normalized_urls_keep_stepstone_job_url_absolute():
    """Relative Stepstone URLs should become absolute public job URLs."""
    job = normalize_actor_item(sample_actor_item())

    assert get_job_url(make_settings(), job).startswith(
        "https://www.stepstone.de/stellenangebote--"
    )
    assert get_apply_url(job) == "N/A"


def test_run_actor_search_normalizes_actor_results():
    """Stepstone execution should isolate actor-specific output conversion."""
    calls: list[tuple[str, dict[str, Any], int]] = []

    def fake_runner(settings, actor_id, payload, max_items):
        calls.append((actor_id, payload, max_items))
        return [sample_actor_item()]

    jobs = run_actor_search(
        make_settings(),
        "memo23~stepstone-search-cheerio-ppr",
        {"keyword": "gis"},
        500,
        actor_runner=fake_runner,
    )

    assert calls == [("memo23~stepstone-search-cheerio-ppr", {"keyword": "gis"}, 500)]
    assert jobs[0]["jobId"] == "12424623"
    assert jobs[0]["companyName"] == "LOW Teq GmbH"
