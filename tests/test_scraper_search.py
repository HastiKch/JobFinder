"""Tests for Apify search execution."""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace
from typing import Any

import pytest
import requests

from jobfinder.scraper.providers.apify_client import retry_delay_seconds
from jobfinder.scraper.search import (
    ApifyConfigurationError,
    ApifyRunTimeoutError,
    SearchExecutionError,
    SearchRequest,
    apify_http_timeout,
    fetch_jobs_for_search,
    get_searches,
    parse_job_sources,
    run_actor,
    run_all_searches,
)
from jobfinder.scraper.settings import SOURCE_ALIASES, ApifyTokenPool


class FakeResponse:
    """Small response double for Apify API tests."""

    def __init__(self, payload: Any, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code
        self.text = ""
        self.reason = "OK"

    def json(self) -> Any:
        return self.payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            error = requests.HTTPError(f"HTTP {self.status_code}")
            error.response = self
            raise error


def make_settings() -> SimpleNamespace:
    """Build the settings attributes used by Apify search execution."""
    return SimpleNamespace(
        apify_api_token="apify_api_real_token",
        apify_run_timeout_seconds=3600,
        apify_run_memory_mb=512,
        apify_client_timeout_seconds=120,
        apify_transient_error_retries=5,
        apify_retry_delay_seconds=0,
        apify_batch_size=1,
        search_concurrency=2,
        delay_between_requests=0,
        max_results_per_search=500,
        scrape_company_details=False,
        use_incognito_mode=True,
        split_by_location=False,
        split_country="DE",
        indeed_max_concurrency=5,
        published_at="r86400",
        stepstone_location="Germany",
        stepstone_category="",
        stepstone_max_concurrency=10,
        stepstone_min_concurrency=1,
        stepstone_max_request_retries=3,
        stepstone_max_results_per_search=500,
        stepstone_use_apify_proxy=True,
        stepstone_proxy_groups=["RESIDENTIAL"],
        stepstone_start_urls=[],
        xing_location="Germany",
        xing_discipline="",
        xing_remote="",
        xing_start_url="",
        xing_max_results_per_search=500,
        xing_max_pages=20,
        xing_max_concurrency=5,
        xing_use_apify_proxy=True,
        xing_proxy_groups=["RESIDENTIAL"],
        source_actor_ids={
            "linkedin": "linkedin~actor",
            "indeed": "indeed~actor",
            "stepstone": "stepstone~actor",
            "xing": "xing~actor",
        },
        source_max_items={
            "linkedin": 500,
            "indeed": 500,
            "stepstone": 500,
            "xing": 500,
        },
        keywords=["GIS", "Python"],
        source_mode="linkedin",
    )


def configure_apify_tokens(
    settings: SimpleNamespace,
    *tokens: str,
) -> SimpleNamespace:
    """Attach a real token pool to the lightweight search settings double."""
    settings.apify_api_token = tokens[0] if tokens else ""
    settings.apify_api_tokens = tuple(tokens)
    settings.apify_token_pool = ApifyTokenPool(tuple(tokens))
    return settings


def test_run_actor_uses_async_api_and_fetches_dataset(monkeypatch):
    """Long keyword searches should not use Apify's 300-second sync endpoint."""
    settings = make_settings()
    calls: list[tuple[str, str, dict[str, Any] | None]] = []

    def fake_post(url: str, **kwargs: Any) -> FakeResponse:
        calls.append(("POST", url, kwargs.get("params")))
        return FakeResponse({"data": {"id": "run-1", "defaultDatasetId": "dataset-1"}})

    def fake_get(url: str, **kwargs: Any) -> FakeResponse:
        calls.append(("GET", url, kwargs.get("params")))
        if "/actor-runs/" in url:
            return FakeResponse(
                {
                    "data": {
                        "id": "run-1",
                        "status": "SUCCEEDED",
                        "defaultDatasetId": "dataset-1",
                    }
                }
            )
        return FakeResponse([{"title": "GIS Analyst"}])

    monkeypatch.setattr(
        "jobfinder.scraper.providers.apify_client.requests.post", fake_post
    )
    monkeypatch.setattr(
        "jobfinder.scraper.providers.apify_client.requests.get", fake_get
    )

    jobs = run_actor(settings, "owner~actor", {"input": True}, 500)

    assert jobs == [{"title": "GIS Analyst"}]
    assert calls[0] == (
        "POST",
        "https://api.apify.com/v2/acts/owner~actor/runs",
        {"timeout": 3600, "memory": 512, "maxItems": 500},
    )
    assert calls[2] == (
        "GET",
        "https://api.apify.com/v2/datasets/dataset-1/items",
        (("format", "json"), ("limit", 500)),
    )
    assert apify_http_timeout(settings) == 120


def test_run_actor_reports_apify_timed_out_status(monkeypatch):
    """A terminal TIMED-OUT actor status should be handled as a search timeout."""
    settings = make_settings()

    def fake_post(url: str, **kwargs: Any) -> FakeResponse:
        return FakeResponse({"data": {"id": "run-1", "defaultDatasetId": "dataset-1"}})

    def fake_get(url: str, **kwargs: Any) -> FakeResponse:
        return FakeResponse({"data": {"id": "run-1", "status": "TIMED-OUT"}})

    monkeypatch.setattr(
        "jobfinder.scraper.providers.apify_client.requests.post", fake_post
    )
    monkeypatch.setattr(
        "jobfinder.scraper.providers.apify_client.requests.get", fake_get
    )

    with pytest.raises(ApifyRunTimeoutError):
        run_actor(settings, "owner~actor", {"input": True}, 500)


def test_fetch_jobs_for_search_retries_temporary_apify_http_errors(monkeypatch):
    """A temporary Apify 502 should be retried instead of becoming 0 results."""
    settings = make_settings()
    post_statuses = [502, 201]
    post_calls = 0

    def fake_post(url: str, **kwargs: Any) -> FakeResponse:
        nonlocal post_calls
        post_calls += 1
        status_code = post_statuses.pop(0)
        if status_code >= 400:
            return FakeResponse("<h1>Bad Gateway</h1>", status_code=status_code)
        return FakeResponse({"data": {"id": "run-1", "defaultDatasetId": "dataset-1"}})

    def fake_get(url: str, **kwargs: Any) -> FakeResponse:
        if "/actor-runs/" in url:
            return FakeResponse(
                {
                    "data": {
                        "id": "run-1",
                        "status": "SUCCEEDED",
                        "defaultDatasetId": "dataset-1",
                    }
                }
            )
        return FakeResponse([{"title": "GIS Analyst"}])

    monkeypatch.setattr(
        "jobfinder.scraper.providers.apify_client.requests.post", fake_post
    )
    monkeypatch.setattr(
        "jobfinder.scraper.providers.apify_client.requests.get", fake_get
    )

    jobs = fetch_jobs_for_search(
        settings,
        SearchRequest(
            source="linkedin",
            source_label="LinkedIn",
            keyword="GIS",
            display_label="LinkedIn / GIS",
            actor_id="owner~actor",
            payload={"input": True},
            max_items=500,
        ),
    )

    assert post_calls == 2
    assert jobs == [
        {"title": "GIS Analyst", "_source": "linkedin", "_source_label": "LinkedIn"}
    ]


def test_fetch_jobs_for_search_fails_after_retry_budget(monkeypatch):
    """A keyword should fail the pipeline instead of being silently skipped."""
    settings = make_settings()
    settings.apify_transient_error_retries = 1

    def fake_post(url: str, **kwargs: Any) -> FakeResponse:
        return FakeResponse("<h1>Bad Gateway</h1>", status_code=502)

    monkeypatch.setattr(
        "jobfinder.scraper.providers.apify_client.requests.post", fake_post
    )

    with pytest.raises(SearchExecutionError):
        fetch_jobs_for_search(
            settings,
            SearchRequest(
                source="linkedin",
                source_label="LinkedIn",
                keyword="GIS",
                display_label="LinkedIn / GIS",
                actor_id="owner~actor",
                payload={"input": True},
                max_items=500,
            ),
        )


def test_retry_delay_uses_exponential_backoff_with_cap():
    """Transient Apify retries should spread out instead of retrying linearly."""
    settings = make_settings()
    settings.apify_retry_delay_seconds = 30

    assert retry_delay_seconds(settings, 1) == 30
    assert retry_delay_seconds(settings, 2) == 60
    assert retry_delay_seconds(settings, 5) == 300


def test_run_all_searches_accepts_empty_search_list():
    """Direct service calls should not crash when no searches are supplied."""
    settings = make_settings()

    assert run_all_searches(settings, []) == ([], [], {}, [])


def test_run_actor_rotates_to_next_apify_token_when_credit_is_empty(monkeypatch):
    """A 402 billing response should retire that token and retry with the next one."""
    settings = configure_apify_tokens(
        make_settings(),
        "apify_api_empty",
        "apify_api_funded",
    )
    post_authorizations: list[str] = []

    def fake_post(url: str, **kwargs: Any) -> FakeResponse:
        post_authorizations.append(kwargs["headers"]["Authorization"])
        if len(post_authorizations) == 1:
            return FakeResponse(
                {"error": {"message": "Insufficient credits."}},
                status_code=402,
            )
        return FakeResponse({"data": {"id": "run-2", "defaultDatasetId": "dataset-2"}})

    def fake_get(url: str, **kwargs: Any) -> FakeResponse:
        if "/actor-runs/" in url:
            return FakeResponse(
                {
                    "data": {
                        "id": "run-2",
                        "status": "SUCCEEDED",
                        "defaultDatasetId": "dataset-2",
                    }
                }
            )
        return FakeResponse([{"title": "GIS Analyst"}])

    monkeypatch.setattr(
        "jobfinder.scraper.providers.apify_client.requests.post", fake_post
    )
    monkeypatch.setattr(
        "jobfinder.scraper.providers.apify_client.requests.get", fake_get
    )

    jobs = run_actor(settings, "owner~actor", {"input": True}, 500)

    assert jobs == [{"title": "GIS Analyst"}]
    assert post_authorizations == [
        "Bearer apify_api_empty",
        "Bearer apify_api_funded",
    ]


def test_run_actor_restarts_with_next_token_when_credit_runs_out(monkeypatch):
    """A mid-run billing failure should restart the search on the next token."""
    settings = configure_apify_tokens(
        make_settings(),
        "apify_api_empty_mid_run",
        "apify_api_funded",
    )
    post_authorizations: list[str] = []
    dataset_authorizations: list[str] = []

    def fake_post(url: str, **kwargs: Any) -> FakeResponse:
        post_authorizations.append(kwargs["headers"]["Authorization"])
        run_number = len(post_authorizations)
        return FakeResponse(
            {
                "data": {
                    "id": f"run-{run_number}",
                    "defaultDatasetId": f"dataset-{run_number}",
                }
            }
        )

    def fake_get(url: str, **kwargs: Any) -> FakeResponse:
        authorization = kwargs["headers"]["Authorization"]
        if "/actor-runs/" in url and authorization == "Bearer apify_api_empty_mid_run":
            return FakeResponse(
                {
                    "data": {
                        "id": "run-1",
                        "status": "FAILED",
                        "statusMessage": "Run stopped because of insufficient credits.",
                    }
                }
            )
        if "/actor-runs/" in url:
            return FakeResponse(
                {
                    "data": {
                        "id": "run-2",
                        "status": "SUCCEEDED",
                        "defaultDatasetId": "dataset-2",
                    }
                }
            )
        dataset_authorizations.append(authorization)
        return FakeResponse([{"title": "Python Analyst"}])

    monkeypatch.setattr(
        "jobfinder.scraper.providers.apify_client.requests.post", fake_post
    )
    monkeypatch.setattr(
        "jobfinder.scraper.providers.apify_client.requests.get", fake_get
    )

    jobs = run_actor(settings, "owner~actor", {"input": True}, 500)

    assert jobs == [{"title": "Python Analyst"}]
    assert post_authorizations == [
        "Bearer apify_api_empty_mid_run",
        "Bearer apify_api_funded",
    ]
    assert dataset_authorizations == ["Bearer apify_api_funded"]


def test_run_actor_fails_when_all_apify_tokens_are_unavailable(monkeypatch):
    """A clear configuration error should be raised after every token fails."""
    settings = configure_apify_tokens(
        make_settings(),
        "apify_api_empty_1",
        "apify_api_empty_2",
    )

    def fake_post(url: str, **kwargs: Any) -> FakeResponse:
        return FakeResponse(
            {"error": {"message": "Payment required."}},
            status_code=402,
        )

    monkeypatch.setattr(
        "jobfinder.scraper.providers.apify_client.requests.post", fake_post
    )

    with pytest.raises(ApifyConfigurationError) as excinfo:
        run_actor(settings, "owner~actor", {"input": True}, 500)

    assert "Tried 2 token(s)" in str(excinfo.value)


def test_run_all_searches_batches_linkedin_when_results_are_attributable(monkeypatch):
    """Opt-in LinkedIn batching should preserve keyword attribution when possible."""
    settings = make_settings()
    settings.apify_batch_size = 2
    payloads: list[dict[str, Any]] = []

    def fake_run_actor(settings, actor_id, payload, max_items):
        payloads.append(payload)
        first_url, second_url = payload["urls"]
        return [
            {"title": "GIS Analyst", "inputUrl": first_url},
            {"title": "Python Analyst", "inputUrl": second_url},
        ]

    monkeypatch.setattr("jobfinder.scraper.search.run_actor", fake_run_actor)

    results, zero_searches, failed_sources, skipped_searches = run_all_searches(
        settings,
        [
            SearchRequest(
                source="linkedin",
                source_label="LinkedIn",
                keyword="GIS",
                display_label="LinkedIn / GIS",
                actor_id="owner~actor",
                payload={
                    "urls": ["https://www.linkedin.com/jobs/search/?keywords=GIS"]
                },
                max_items=500,
            ),
            SearchRequest(
                source="linkedin",
                source_label="LinkedIn",
                keyword="Python",
                display_label="LinkedIn / Python",
                actor_id="owner~actor",
                payload={
                    "urls": ["https://www.linkedin.com/jobs/search/?keywords=Python"]
                },
                max_items=500,
            ),
        ],
    )

    assert len(payloads) == 1
    assert [keyword for keyword, _ in results] == ["GIS", "Python"]
    assert [jobs[0]["title"] for _, jobs in results] == [
        "GIS Analyst",
        "Python Analyst",
    ]
    assert zero_searches == []
    assert failed_sources == {}
    assert skipped_searches == []


def test_run_all_searches_respects_indeed_source_concurrency(monkeypatch):
    """Indeed actor runs should be bounded separately from global concurrency."""
    settings = make_settings()
    settings.search_concurrency = 6
    settings.indeed_max_concurrency = 2
    active_count = 0
    max_active_count = 0
    lock = threading.Lock()

    def fake_run_actor(settings, actor_id, payload, max_items):
        nonlocal active_count, max_active_count
        with lock:
            active_count += 1
            max_active_count = max(max_active_count, active_count)
        time.sleep(0.02)
        with lock:
            active_count -= 1
        return [{"title": payload["title"], "key": payload["title"]}]

    monkeypatch.setattr("jobfinder.scraper.search.run_actor", fake_run_actor)

    results, zero_searches, failed_sources, skipped_searches = run_all_searches(
        settings,
        [
            SearchRequest(
                source="indeed",
                source_label="Indeed",
                keyword=f"Keyword {idx}",
                display_label=f"Indeed / Keyword {idx}",
                actor_id="valig~indeed-jobs-scraper",
                payload={"title": f"Keyword {idx}"},
                max_items=500,
            )
            for idx in range(6)
        ],
    )

    assert max_active_count <= 2
    assert [keyword for keyword, _ in results] == [f"Keyword {idx}" for idx in range(6)]
    assert zero_searches == []
    assert failed_sources == {}
    assert skipped_searches == []


def test_parse_job_sources_supports_stepstone_xing_and_comma_lists():
    """Users should be able to mix DACH sources with existing providers."""
    settings = make_settings()
    settings.source_mode = "linkedin,stepstone,xing"

    assert parse_job_sources(settings) == ["linkedin", "stepstone", "xing"]

    settings.source_mode = "all"
    assert parse_job_sources(settings) == ["linkedin", "indeed", "stepstone", "xing"]


def test_parse_job_sources_does_not_support_both_shortcut():
    """Source selection should not expose the old LinkedIn-plus-Indeed shortcut."""
    assert "both" not in SOURCE_ALIASES


def test_get_searches_uses_one_stepstone_run_for_direct_urls():
    """Direct URL mode should not duplicate the same Stepstone URL per keyword."""
    settings = make_settings()
    settings.stepstone_start_urls = ["https://www.stepstone.de/jobs/software"]

    _, searches = get_searches(settings, ["stepstone"])

    assert len(searches) == 1
    assert searches[0].source == "stepstone"
    assert searches[0].keyword == "Configured URLs"
    assert searches[0].payload["startUrls"] == [
        {"url": "https://www.stepstone.de/jobs/software"}
    ]


def test_get_searches_uses_one_xing_run_for_direct_url():
    """Direct URL mode should not duplicate the same Xing URL per keyword."""
    settings = make_settings()
    settings.xing_start_url = "https://www.xing.com/jobs/t-remote?keywords=Remote"

    _, searches = get_searches(settings, ["xing"])

    assert len(searches) == 1
    assert searches[0].source == "xing"
    assert searches[0].keyword == "Configured URL"
    assert searches[0].payload["startUrl"] == (
        "https://www.xing.com/jobs/t-remote?keywords=Remote"
    )
    assert "keyword" not in searches[0].payload


def test_run_all_searches_respects_stepstone_source_concurrency(monkeypatch):
    """Stepstone actor runs should be bounded separately from global concurrency."""
    settings = make_settings()
    settings.search_concurrency = 6
    settings.stepstone_max_concurrency = 2
    active_count = 0
    max_active_count = 0
    lock = threading.Lock()

    def fake_run_actor(settings, actor_id, payload, max_items):
        nonlocal active_count, max_active_count
        with lock:
            active_count += 1
            max_active_count = max(max_active_count, active_count)
        time.sleep(0.02)
        with lock:
            active_count -= 1
        return [{"title": payload["keyword"], "id": payload["keyword"]}]

    monkeypatch.setattr("jobfinder.scraper.search.run_actor", fake_run_actor)

    results, zero_searches, failed_sources, skipped_searches = run_all_searches(
        settings,
        [
            SearchRequest(
                source="stepstone",
                source_label="Stepstone",
                keyword=f"Keyword {idx}",
                display_label=f"Stepstone / Keyword {idx}",
                actor_id="memo23~stepstone-search-cheerio-ppr",
                payload={"keyword": f"Keyword {idx}"},
                max_items=500,
            )
            for idx in range(6)
        ],
    )

    assert max_active_count <= 2
    assert [keyword for keyword, _ in results] == [f"Keyword {idx}" for idx in range(6)]
    assert zero_searches == []
    assert failed_sources == {}
    assert skipped_searches == []


def test_run_all_searches_respects_xing_source_concurrency(monkeypatch):
    """Xing actor runs should be bounded separately from global concurrency."""
    settings = make_settings()
    settings.search_concurrency = 6
    settings.xing_max_concurrency = 2
    active_count = 0
    max_active_count = 0
    lock = threading.Lock()

    def fake_run_actor(settings, actor_id, payload, max_items):
        nonlocal active_count, max_active_count
        with lock:
            active_count += 1
            max_active_count = max(max_active_count, active_count)
        time.sleep(0.02)
        with lock:
            active_count -= 1
        return [{"title": payload["keyword"], "job_id": payload["keyword"]}]

    monkeypatch.setattr("jobfinder.scraper.search.run_actor", fake_run_actor)

    results, zero_searches, failed_sources, skipped_searches = run_all_searches(
        settings,
        [
            SearchRequest(
                source="xing",
                source_label="Xing",
                keyword=f"Keyword {idx}",
                display_label=f"Xing / Keyword {idx}",
                actor_id="shahidirfan~Xing-Jobs-Scraper",
                payload={"keyword": f"Keyword {idx}"},
                max_items=500,
            )
            for idx in range(6)
        ],
    )

    assert max_active_count <= 2
    assert [keyword for keyword, _ in results] == [f"Keyword {idx}" for idx in range(6)]
    assert zero_searches == []
    assert failed_sources == {}
    assert skipped_searches == []


def test_run_all_searches_continues_when_stepstone_source_fails(monkeypatch):
    """A Stepstone failure should not take down already working providers."""
    settings = make_settings()
    settings.search_concurrency = 2

    def fake_run_actor(settings, actor_id, payload, max_items):
        if actor_id == "memo23~stepstone-search-cheerio-ppr":
            raise RuntimeError("temporary Stepstone issue")
        return [{"title": payload["keyword"], "jobId": payload["keyword"]}]

    monkeypatch.setattr("jobfinder.scraper.search.run_actor", fake_run_actor)

    results, zero_searches, failed_sources, skipped_searches = run_all_searches(
        settings,
        [
            SearchRequest(
                source="stepstone",
                source_label="Stepstone",
                keyword="GIS",
                display_label="Stepstone / GIS",
                actor_id="memo23~stepstone-search-cheerio-ppr",
                payload={"keyword": "GIS"},
                max_items=500,
            ),
            SearchRequest(
                source="linkedin",
                source_label="LinkedIn",
                keyword="GIS",
                display_label="LinkedIn / GIS",
                actor_id="curious_coder~linkedin-jobs-scraper",
                payload={"keyword": "GIS"},
                max_items=500,
            ),
            SearchRequest(
                source="stepstone",
                source_label="Stepstone",
                keyword="Python",
                display_label="Stepstone / Python",
                actor_id="memo23~stepstone-search-cheerio-ppr",
                payload={"keyword": "Python"},
                max_items=500,
            ),
        ],
    )

    assert results == [
        (
            "GIS",
            [
                {
                    "title": "GIS",
                    "jobId": "GIS",
                    "_source": "linkedin",
                    "_source_label": "LinkedIn",
                }
            ],
        )
    ]
    assert zero_searches == []
    assert "stepstone" in failed_sources
    assert skipped_searches == ["Stepstone / GIS", "Stepstone / Python"]


def test_run_all_searches_continues_when_xing_source_fails(monkeypatch):
    """A Xing failure should not take down already working providers."""
    settings = make_settings()
    settings.search_concurrency = 2

    def fake_run_actor(settings, actor_id, payload, max_items):
        if actor_id == "shahidirfan~Xing-Jobs-Scraper":
            raise RuntimeError("temporary Xing issue")
        return [{"title": payload["keyword"], "jobId": payload["keyword"]}]

    monkeypatch.setattr("jobfinder.scraper.search.run_actor", fake_run_actor)

    results, zero_searches, failed_sources, skipped_searches = run_all_searches(
        settings,
        [
            SearchRequest(
                source="xing",
                source_label="Xing",
                keyword="GIS",
                display_label="Xing / GIS",
                actor_id="shahidirfan~Xing-Jobs-Scraper",
                payload={"keyword": "GIS"},
                max_items=500,
            ),
            SearchRequest(
                source="linkedin",
                source_label="LinkedIn",
                keyword="GIS",
                display_label="LinkedIn / GIS",
                actor_id="curious_coder~linkedin-jobs-scraper",
                payload={"keyword": "GIS"},
                max_items=500,
            ),
            SearchRequest(
                source="xing",
                source_label="Xing",
                keyword="Python",
                display_label="Xing / Python",
                actor_id="shahidirfan~Xing-Jobs-Scraper",
                payload={"keyword": "Python"},
                max_items=500,
            ),
        ],
    )

    assert results == [
        (
            "GIS",
            [
                {
                    "title": "GIS",
                    "jobId": "GIS",
                    "_source": "linkedin",
                    "_source_label": "LinkedIn",
                }
            ],
        )
    ]
    assert zero_searches == []
    assert "xing" in failed_sources
    assert skipped_searches == ["Xing / GIS", "Xing / Python"]
