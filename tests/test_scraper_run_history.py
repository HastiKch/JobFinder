"""Tests for scraper run-history windows and cross-run deduplication."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from jobfinder.env import EnvSettings
from jobfinder.scraper.run_history import (
    SEEN_JOBS_SHEET_NAME,
    apply_configured_posted_time_window,
    apply_previous_run_search_window,
    filter_jobs_to_previous_run_window,
    find_previous_run_started_at,
    job_identity_keys_from_values,
    load_google_spreadsheet_context,
    read_latest_google_posted_at,
    remove_jobs_seen_in_history,
)
from jobfinder.scraper.settings import ApifyTokenPool, ScraperSettings


def make_settings(run_started_at: datetime) -> ScraperSettings:
    """Build minimal scraper settings for run-history tests."""
    berlin = ZoneInfo("Europe/Berlin")
    return ScraperSettings(
        env=EnvSettings({}),
        filter_config={},
        keywords=["GIS"],
        apify_api_token="token",
        apify_api_tokens=("token",),
        apify_token_pool=ApifyTokenPool(("token",)),
        google_spreadsheet_id="spreadsheet-id",
        scraper_timezone="Europe/Berlin",
        posted_timezone="Europe/Berlin",
        scraper_tz=berlin,
        posted_tz=berlin,
        run_started_at_utc=run_started_at.astimezone(UTC),
        run_started_at=run_started_at,
        run_sheet_name=run_started_at.strftime("%Y-%m-%d %H-%M-%S"),
        source_mode="linkedin",
        output_mode="google_sheets",
        excel_output_file=Path("jobs.xlsx"),
        max_results_per_search=500,
        indeed_max_results_per_search=500,
        search_concurrency=1,
        apify_batch_size=1,
        apify_memory_limit_mb=0,
        apify_run_memory_mb=512,
        apify_run_timeout_seconds=300,
        apify_client_timeout_seconds=360,
        apify_transient_error_retries=5,
        apify_retry_delay_seconds=30,
        delay_between_requests=0,
        search_window_buffer_seconds=3600,
        posted_time_window="since_previous_run",
        location="Germany",
        geo_id="101282230",
        published_at="r86400",
        experience_levels=["1", "2"],
        contract_types=["F"],
        scrape_company_details=False,
        use_incognito_mode=True,
        split_by_location=False,
        split_country="DE",
        excluded_title_terms=[],
        excluded_company_terms=[],
        max_applicants=100,
        application_status_options=["applied"],
        indeed_country="DE",
        indeed_location="Germany",
        indeed_max_concurrency=5,
        indeed_save_only_unique_items=True,
        stepstone_location="deutschland",
        stepstone_category="",
        stepstone_start_urls=[],
        stepstone_max_results_per_search=500,
        stepstone_max_concurrency=10,
        stepstone_min_concurrency=1,
        stepstone_max_request_retries=3,
        stepstone_use_apify_proxy=True,
        stepstone_proxy_groups=["RESIDENTIAL"],
        source_actor_ids={"linkedin": "actor"},
        source_max_items={"linkedin": 500},
    )


def test_find_previous_run_started_at_uses_latest_timestamped_sheet():
    """Only timestamped run tabs should determine the previous run."""
    berlin = ZoneInfo("Europe/Berlin")
    current = datetime(2026, 5, 6, 10, 0, tzinfo=berlin)

    previous = find_previous_run_started_at(
        [
            "Notes",
            "2026-05-05 09-00-00",
            "2026-05-06 08-30-00",
            "2026-05-07 08-30-00",
        ],
        current,
        berlin,
    )

    assert previous == datetime(2026, 5, 6, 8, 30, tzinfo=berlin)


def test_read_latest_google_posted_at_scans_all_posted_columns(monkeypatch):
    """The lower-bound anchor should come from actual Posted cells across tabs."""
    berlin = ZoneInfo("Europe/Berlin")
    settings = make_settings(datetime(2026, 5, 6, 10, 0, tzinfo=berlin))

    def fake_batch_get_values(
        service,
        spreadsheet_id,
        ranges,
        *,
        value_render_option="FORMATTED_VALUE",
    ):
        if all(range_name.endswith("!1:1") for range_name in ranges):
            return [
                {"values": [["Job Title", "Posted"]]},
                {"values": [["Application Status", "Posted Date"]]},
                {"values": [["Job Key"]]},
            ]
        return [
            {"values": [["2026-05-05 08:00:00"], ["N/A"]]},
            {"values": [["2026-05-06 07:15:00"], ["2026-05-07 12:00:00"]]},
        ]

    monkeypatch.setattr(
        "jobfinder.scraper.run_history.batch_get_values",
        fake_batch_get_values,
    )

    latest = read_latest_google_posted_at(
        settings,
        service=object(),
        spreadsheet_id="spreadsheet-id",
        sheet_names=["2026-05-05 09-00-00", "All", SEEN_JOBS_SHEET_NAME],
    )

    assert latest == datetime(2026, 5, 6, 7, 15, tzinfo=berlin)


def test_apply_previous_run_search_window_adds_safety_buffer():
    """The Apify search window should cover the exact prior run plus a buffer."""
    berlin = ZoneInfo("Europe/Berlin")
    settings = make_settings(datetime(2026, 5, 6, 10, 0, tzinfo=berlin))
    previous = datetime(2026, 5, 5, 9, 0, tzinfo=berlin)

    updated, seconds = apply_previous_run_search_window(settings, previous)

    assert seconds == 25 * 60 * 60 + 3600
    assert updated.published_at == f"r{seconds}"


def test_apply_configured_posted_time_window_uses_fixed_manual_window():
    """Manual fixed windows should not be narrowed to the previous-run interval."""
    berlin = ZoneInfo("Europe/Berlin")
    settings = replace(
        make_settings(datetime(2026, 5, 6, 10, 0, tzinfo=berlin)),
        posted_time_window="last_7d",
    )
    previous = datetime(2026, 5, 5, 9, 0, tzinfo=berlin)

    updated, seconds, should_filter_previous = apply_configured_posted_time_window(
        settings,
        previous,
    )

    assert seconds == 7 * 24 * 60 * 60
    assert updated.published_at == "r604800"
    assert should_filter_previous is False


def test_apply_configured_posted_time_window_can_backfill_without_provider_date():
    """Backfill mode should leave provider searches unrestricted by posted date."""
    berlin = ZoneInfo("Europe/Berlin")
    settings = replace(
        make_settings(datetime(2026, 5, 6, 10, 0, tzinfo=berlin)),
        posted_time_window="backfill",
    )

    updated, seconds, should_filter_previous = apply_configured_posted_time_window(
        settings,
        datetime(2026, 5, 5, 9, 0, tzinfo=berlin),
    )

    assert seconds is None
    assert updated.published_at == ""
    assert should_filter_previous is False


def test_filter_jobs_to_previous_run_window_keeps_exact_interval():
    """Posted dates are filtered after scraping to the exact inclusive window."""
    berlin = ZoneInfo("Europe/Berlin")
    settings = make_settings(datetime(2026, 5, 6, 10, 0, tzinfo=berlin))
    previous = datetime(2026, 5, 5, 9, 0, tzinfo=berlin)
    jobs = [
        {"title": "Old", "postedAt": "2026-05-05T08:59:59+02:00"},
        {"title": "At lower bound", "postedAt": "2026-05-05T09:00:00+02:00"},
        {"title": "First new", "postedAt": "2026-05-05T09:00:01+02:00"},
        {"title": "At run start", "postedAt": "2026-05-06T10:00:00+02:00"},
        {"title": "Future", "postedAt": "2026-05-06T10:00:01+02:00"},
        {"title": "Unknown"},
    ]

    kept, outside_count, unknown_count = filter_jobs_to_previous_run_window(
        settings,
        jobs,
        previous,
    )

    assert [job["title"] for job in kept] == [
        "At lower bound",
        "First new",
        "At run start",
        "Unknown",
    ]
    assert outside_count == 2
    assert unknown_count == 1


def test_remove_jobs_seen_in_history_matches_allowed_identity_cells():
    """New raw jobs should match previous rows by title, company, and location."""
    berlin = ZoneInfo("Europe/Berlin")
    settings = make_settings(datetime(2026, 5, 6, 10, 0, tzinfo=berlin))
    historical_keys = job_identity_keys_from_values(
        source="LinkedIn",
        title="GIS Analyst",
        company="GeoCo",
        location="Berlin",
    )
    jobs = [
        {
            "_source": "linkedin",
            "_source_label": "LinkedIn",
            "jobId": "123456",
            "title": "GIS Analyst",
            "companyName": "GeoCo",
            "location": "Berlin",
        },
        {
            "_source": "linkedin",
            "_source_label": "LinkedIn",
            "jobId": "999999",
            "title": "Remote Sensing Analyst",
            "companyName": "SpaceCo",
            "location": "Munich",
        },
    ]

    kept, duplicate_count = remove_jobs_seen_in_history(
        settings,
        jobs,
        historical_keys,
    )

    assert [job["jobId"] for job in kept] == ["999999"]
    assert duplicate_count == 1


def test_remove_jobs_seen_in_history_ignores_provider_id_only_keys():
    """Provider IDs are no longer part of historical duplicate identity."""
    berlin = ZoneInfo("Europe/Berlin")
    settings = make_settings(datetime(2026, 5, 6, 10, 0, tzinfo=berlin))
    historical_keys = {"id|indeed|abc123"}
    jobs = [
        {
            "_source": "indeed",
            "_source_label": "Indeed",
            "key": "abc123",
            "title": "Data Analyst",
            "companyName": "Acme Data",
            "location": "Berlin",
        },
        {
            "_source": "indeed",
            "_source_label": "Indeed",
            "key": "xyz999",
            "title": "GIS Analyst",
            "companyName": "GeoCo",
            "location": "Munich",
        },
    ]

    kept, duplicate_count = remove_jobs_seen_in_history(
        settings,
        jobs,
        historical_keys,
    )

    assert [job["key"] for job in kept] == ["abc123", "xyz999"]
    assert duplicate_count == 0


def test_remove_jobs_seen_in_history_ignores_provider_url_only_keys():
    """Provider job URLs are no longer part of historical duplicate identity."""
    berlin = ZoneInfo("Europe/Berlin")
    settings = make_settings(datetime(2026, 5, 6, 10, 0, tzinfo=berlin))
    historical_keys = {"url|stepstone|stepstone:12424623"}
    jobs = [
        {
            "_source": "stepstone",
            "_source_label": "Stepstone",
            "id": "12424623",
            "title": "IT Administrator",
            "companyName": "LOW Teq GmbH",
            "location": "Cologne",
            "url": (
                "https://www.stepstone.de/stellenangebote--IT-Administrator--"
                "12424623-inline.html?rltr=2"
            ),
        },
        {
            "_source": "stepstone",
            "_source_label": "Stepstone",
            "id": "999999",
            "title": "GIS Analyst",
            "companyName": "GeoCo",
            "location": "Munich",
        },
    ]

    kept, duplicate_count = remove_jobs_seen_in_history(
        settings,
        jobs,
        historical_keys,
    )

    assert [job["id"] for job in kept] == ["12424623", "999999"]
    assert duplicate_count == 0


def test_load_google_spreadsheet_context_prefers_seen_jobs_index(monkeypatch):
    """Maintained seen-jobs indexes avoid repeatedly scanning historical run tabs."""
    berlin = ZoneInfo("Europe/Berlin")
    settings = make_settings(datetime(2026, 5, 6, 10, 0, tzinfo=berlin))

    def fake_read_google_spreadsheet_id(settings):
        return "spreadsheet-id"

    def fake_get_google_spreadsheet(service, spreadsheet_id):
        return {
            "spreadsheetUrl": "https://docs.google.com/spreadsheets/d/spreadsheet-id",
            "sheets": [
                {"properties": {"title": "2026-05-05 09-00-00"}},
                {"properties": {"title": SEEN_JOBS_SHEET_NAME}},
            ],
        }

    def fake_read_seen_jobs_index(service, spreadsheet_id):
        return {"profile|linkedin|gis analyst|geoco|berlin"}

    def fake_latest_posted_at(settings, service, spreadsheet_id, sheet_names):
        return None

    def fail_historical_scan(service, spreadsheet_id, sheet_names):
        raise AssertionError("historical tab scan should not run when index exists")

    monkeypatch.setattr(
        "jobfinder.scraper.export_google_sheets.read_google_spreadsheet_id",
        fake_read_google_spreadsheet_id,
    )
    monkeypatch.setattr(
        "jobfinder.scraper.export_google_sheets.get_google_spreadsheet",
        fake_get_google_spreadsheet,
    )
    monkeypatch.setattr(
        "jobfinder.scraper.run_history.read_seen_jobs_index",
        fake_read_seen_jobs_index,
    )
    monkeypatch.setattr(
        "jobfinder.scraper.run_history.read_latest_google_posted_at",
        fake_latest_posted_at,
    )
    monkeypatch.setattr(
        "jobfinder.scraper.run_history.read_historical_google_job_keys",
        fail_historical_scan,
    )

    context = load_google_spreadsheet_context(settings, service=object())

    assert context.previous_run_started_at == datetime(2026, 5, 5, 9, 0, tzinfo=berlin)
    assert context.historical_job_keys == {"profile|linkedin|gis analyst|geoco|berlin"}


def test_load_google_spreadsheet_context_seeds_seen_jobs_index(monkeypatch):
    """The first indexed run should preserve keys discovered from old tabs."""
    berlin = ZoneInfo("Europe/Berlin")
    settings = make_settings(datetime(2026, 5, 6, 10, 0, tzinfo=berlin))
    seeded_keys: list[set[str]] = []

    def fake_read_google_spreadsheet_id(settings):
        return "spreadsheet-id"

    def fake_get_google_spreadsheet(service, spreadsheet_id):
        return {
            "spreadsheetUrl": "https://docs.google.com/spreadsheets/d/spreadsheet-id",
            "sheets": [{"properties": {"title": "2026-05-05 09-00-00"}}],
        }

    def fake_historical_scan(service, spreadsheet_id, sheet_names):
        return {"profile|linkedin|gis analyst|geoco|berlin"}

    def fake_latest_posted_at(settings, service, spreadsheet_id, sheet_names):
        return None

    def fake_append_seen_job_keys(service, spreadsheet_id, sheet_names, job_keys):
        seeded_keys.append(set(job_keys))

    monkeypatch.setattr(
        "jobfinder.scraper.export_google_sheets.read_google_spreadsheet_id",
        fake_read_google_spreadsheet_id,
    )
    monkeypatch.setattr(
        "jobfinder.scraper.export_google_sheets.get_google_spreadsheet",
        fake_get_google_spreadsheet,
    )
    monkeypatch.setattr(
        "jobfinder.scraper.run_history.read_historical_google_job_keys",
        fake_historical_scan,
    )
    monkeypatch.setattr(
        "jobfinder.scraper.run_history.read_latest_google_posted_at",
        fake_latest_posted_at,
    )
    monkeypatch.setattr(
        "jobfinder.scraper.run_history.append_seen_job_keys",
        fake_append_seen_job_keys,
    )

    context = load_google_spreadsheet_context(settings, service=object())

    assert context.historical_job_keys == {"profile|linkedin|gis analyst|geoco|berlin"}
    assert seeded_keys == [{"profile|linkedin|gis analyst|geoco|berlin"}]


def test_load_google_spreadsheet_context_can_skip_seen_jobs_seed(monkeypatch):
    """Preflight callers should be able to validate access without writes."""
    berlin = ZoneInfo("Europe/Berlin")
    settings = make_settings(datetime(2026, 5, 6, 10, 0, tzinfo=berlin))

    def fake_read_google_spreadsheet_id(settings):
        return "spreadsheet-id"

    def fake_get_google_spreadsheet(service, spreadsheet_id):
        return {
            "spreadsheetUrl": "https://docs.google.com/spreadsheets/d/spreadsheet-id",
            "sheets": [{"properties": {"title": "2026-05-05 09-00-00"}}],
        }

    def fake_historical_scan(service, spreadsheet_id, sheet_names):
        return {"profile|linkedin|gis analyst|geoco|berlin"}

    def fake_latest_posted_at(settings, service, spreadsheet_id, sheet_names):
        return None

    def fail_append_seen_job_keys(service, spreadsheet_id, sheet_names, job_keys):
        raise AssertionError("preflight should not seed the index")

    monkeypatch.setattr(
        "jobfinder.scraper.export_google_sheets.read_google_spreadsheet_id",
        fake_read_google_spreadsheet_id,
    )
    monkeypatch.setattr(
        "jobfinder.scraper.export_google_sheets.get_google_spreadsheet",
        fake_get_google_spreadsheet,
    )
    monkeypatch.setattr(
        "jobfinder.scraper.run_history.read_historical_google_job_keys",
        fake_historical_scan,
    )
    monkeypatch.setattr(
        "jobfinder.scraper.run_history.read_latest_google_posted_at",
        fake_latest_posted_at,
    )
    monkeypatch.setattr(
        "jobfinder.scraper.run_history.append_seen_job_keys",
        fail_append_seen_job_keys,
    )

    context = load_google_spreadsheet_context(
        settings,
        service=object(),
        seed_seen_jobs_index=False,
    )

    assert context.historical_job_keys == {"profile|linkedin|gis analyst|geoco|berlin"}
