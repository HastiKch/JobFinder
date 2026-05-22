"""Runtime settings for the Apify-powered job scraper."""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from jobfinder.config_files import (
    ConfigFileError,
    config_int,
    config_list,
    config_str,
    load_filter_config,
    load_keywords,
)
from jobfinder.env import EnvSettings
from jobfinder.paths import (
    DEFAULT_EXCEL_FILE,
    ENV_FILE,
    FILTERS_FILE,
    GOOGLE_SPREADSHEET_ID_FILE,
    KEYWORDS_FILE,
)

APIFY_API_TOKEN_ENV = "APIFY_API_TOKEN"
TOKEN_PLACEHOLDER = "apify_api_XXXXXXXXXXXX"
TOKEN_SEPARATOR = ";"
MAX_APIFY_API_TOKENS = 12
DEFAULT_SPREADSHEET_TITLE = "jobs"
DEFAULT_APIFY_RUN_TIMEOUT_SECONDS = 3600
DEFAULT_APIFY_CLIENT_TIMEOUT_SECONDS = 120
DEFAULT_APIFY_TRANSIENT_ERROR_RETRIES = 5
DEFAULT_APIFY_RETRY_DELAY_SECONDS = 30
MAX_SEARCH_CONCURRENCY = 50
MAX_PROVIDER_CONCURRENCY = 50
MAX_APIFY_BATCH_SIZE = 25

LINKEDIN_ACTOR_ID = "curious_coder~linkedin-jobs-scraper"
INDEED_ACTOR_ID = "valig~indeed-jobs-scraper"
INDEED_MAX_RESULTS_LIMIT = 1000
STEPSTONE_ACTOR_ID = "memo23~stepstone-search-cheerio-ppr"

TOKEN_ENV_VAR = APIFY_API_TOKEN_ENV
"""Backward-compatible alias for the Apify token environment variable name."""

SPREADSHEET_TITLE = DEFAULT_SPREADSHEET_TITLE
"""Backward-compatible alias for the default spreadsheet title."""

SOURCE_ORDER = ("linkedin", "indeed", "stepstone")
SOURCE_DISPLAY_NAMES = {
    "linkedin": "LinkedIn",
    "indeed": "Indeed",
    "stepstone": "Stepstone",
}
SOURCE_ALIASES = {
    "linkedin": {"linkedin"},
    "li": {"linkedin"},
    "indeed": {"indeed"},
    "stepstone": {"stepstone"},
    "stepstone_de": {"stepstone"},
    "stepstone-de": {"stepstone"},
    "ss": {"stepstone"},
    "all": {"linkedin", "indeed", "stepstone"},
}
OUTPUT_MODE_ALIASES = {
    "excel": {"excel"},
    "local": {"excel"},
    "xlsx": {"excel"},
    "google": {"google_sheets"},
    "drive": {"google_sheets"},
    "google_sheets": {"google_sheets"},
    "sheets": {"google_sheets"},
    "both": {"excel", "google_sheets"},
    "all": {"excel", "google_sheets"},
}
POSTED_TIME_WINDOW_SINCE_PREVIOUS_RUN = "since_previous_run"
POSTED_TIME_WINDOW_LAST_24H = "last_24h"
POSTED_TIME_WINDOW_LAST_7D = "last_7d"
POSTED_TIME_WINDOW_BACKFILL = "backfill"
POSTED_TIME_WINDOW_ALIASES = {
    "since_previous_run": POSTED_TIME_WINDOW_SINCE_PREVIOUS_RUN,
    "since-previous-run": POSTED_TIME_WINDOW_SINCE_PREVIOUS_RUN,
    "previous_run": POSTED_TIME_WINDOW_SINCE_PREVIOUS_RUN,
    "previous-run": POSTED_TIME_WINDOW_SINCE_PREVIOUS_RUN,
    "daily": POSTED_TIME_WINDOW_SINCE_PREVIOUS_RUN,
    "last_24h": POSTED_TIME_WINDOW_LAST_24H,
    "last-24h": POSTED_TIME_WINDOW_LAST_24H,
    "24h": POSTED_TIME_WINDOW_LAST_24H,
    "last_7d": POSTED_TIME_WINDOW_LAST_7D,
    "last-7d": POSTED_TIME_WINDOW_LAST_7D,
    "7d": POSTED_TIME_WINDOW_LAST_7D,
    "backfill": POSTED_TIME_WINDOW_BACKFILL,
    "all": POSTED_TIME_WINDOW_BACKFILL,
    "all_time": POSTED_TIME_WINDOW_BACKFILL,
    "all-time": POSTED_TIME_WINDOW_BACKFILL,
}

DEFAULT_EXCLUDED_COMPANY_TERMS = [
    "Zeiss",
    "Airbus",
    "Airbus Aircraft",
    "Boston Consulting Group",
    "BCG",
    "IBM",
    "Fraunhofer",
    "German Aerospace Center",
    "DLR",
    "Siemens",
    "Tesla",
]


@dataclass(frozen=True)
class ApifyTokenSelection:
    """One token chosen from the configured Apify token list."""

    index: int
    token: str
    total: int

    @property
    def label(self) -> str:
        """Return a log-safe token label without exposing the secret."""
        if self.total <= 1:
            return APIFY_API_TOKEN_ENV
        return f"{APIFY_API_TOKEN_ENV} #{self.index + 1}"


class ApifyTokenPool:
    """Thread-safe ordered pool of Apify tokens for billing failover."""

    def __init__(self, tokens: tuple[str, ...]) -> None:
        self._tokens = tokens
        self._current_index = 0
        self._unavailable_indices: set[int] = set()
        self._lock = threading.Lock()

    @property
    def tokens(self) -> tuple[str, ...]:
        """Return configured tokens in fallback order."""
        return self._tokens

    @property
    def total_count(self) -> int:
        """Return the number of configured tokens."""
        return len(self._tokens)

    @property
    def available_count(self) -> int:
        """Return the number of tokens not yet marked unavailable."""
        with self._lock:
            return max(0, len(self._tokens) - len(self._unavailable_indices))

    def active(self) -> ApifyTokenSelection | None:
        """Return the active token, skipping tokens already marked unavailable."""
        with self._lock:
            index = self._next_available_index_locked(self._current_index)
            if index is None:
                return None
            self._current_index = index
            return ApifyTokenSelection(index, self._tokens[index], len(self._tokens))

    def retire(self, selection: ApifyTokenSelection) -> ApifyTokenSelection | None:
        """Mark a token unavailable and return the next usable token if any."""
        with self._lock:
            if (
                0 <= selection.index < len(self._tokens)
                and self._tokens[selection.index] == selection.token
            ):
                self._unavailable_indices.add(selection.index)
                start_index = (selection.index + 1) % len(self._tokens)
            else:
                start_index = self._current_index

            next_index = self._next_available_index_locked(start_index)
            if next_index is None:
                return None
            self._current_index = next_index
            return ApifyTokenSelection(
                next_index,
                self._tokens[next_index],
                len(self._tokens),
            )

    def _next_available_index_locked(self, start_index: int) -> int | None:
        """Return the next non-retired token index while the lock is held."""
        if not self._tokens or len(self._unavailable_indices) >= len(self._tokens):
            return None

        for offset in range(len(self._tokens)):
            index = (start_index + offset) % len(self._tokens)
            if index not in self._unavailable_indices:
                return index
        return None


@dataclass(frozen=True)
class ScraperSettings:
    """Resolved scraper settings from env variables and config files."""

    env: EnvSettings
    filter_config: dict[str, Any]
    keywords: list[str]
    apify_api_token: str
    apify_api_tokens: tuple[str, ...]
    apify_token_pool: ApifyTokenPool
    google_spreadsheet_id: str
    scraper_timezone: str
    posted_timezone: str
    scraper_tz: ZoneInfo
    posted_tz: ZoneInfo
    run_started_at_utc: datetime
    run_started_at: datetime
    run_sheet_name: str
    source_mode: str
    output_mode: str
    excel_output_file: Path
    max_results_per_search: int
    indeed_max_results_per_search: int
    search_concurrency: int
    apify_batch_size: int
    apify_memory_limit_mb: int
    apify_run_memory_mb: int
    apify_run_timeout_seconds: int
    apify_client_timeout_seconds: int
    apify_transient_error_retries: int
    apify_retry_delay_seconds: int
    delay_between_requests: int
    search_window_buffer_seconds: int
    posted_time_window: str
    location: str
    geo_id: str
    published_at: str
    experience_levels: list[str]
    contract_types: list[str]
    scrape_company_details: bool
    use_incognito_mode: bool
    split_by_location: bool
    split_country: str
    excluded_title_terms: list[str]
    excluded_company_terms: list[str]
    max_applicants: int
    application_status_options: list[str]
    indeed_country: str
    indeed_location: str
    indeed_max_concurrency: int
    indeed_save_only_unique_items: bool
    stepstone_location: str
    stepstone_category: str
    stepstone_start_urls: list[str]
    stepstone_max_results_per_search: int
    stepstone_max_concurrency: int
    stepstone_min_concurrency: int
    stepstone_max_request_retries: int
    stepstone_use_apify_proxy: bool
    stepstone_proxy_groups: list[str]
    source_actor_ids: dict[str, str]
    source_max_items: dict[str, int]

    @property
    def token_file(self) -> Path:
        """Return the env-file path referenced in user-facing token messages."""
        return ENV_FILE

    @property
    def spreadsheet_id_file(self) -> Path:
        """Return the file used to cache the Google spreadsheet ID."""
        return GOOGLE_SPREADSHEET_ID_FILE

    @property
    def provider_selection(self) -> str:
        """Return the configured job-provider selection string."""
        return self.source_mode

    @property
    def provider_actor_ids(self) -> dict[str, str]:
        """Return Apify actor IDs keyed by provider."""
        return self.source_actor_ids

    @property
    def provider_max_items(self) -> dict[str, int]:
        """Return maximum actor items keyed by provider."""
        return self.source_max_items

    @property
    def provider_posted_window(self) -> str:
        """Return the provider-facing posted-time filter value."""
        return self.published_at


def load_scraper_settings(env: EnvSettings | None = None) -> ScraperSettings:
    """Resolve and validate scraper settings."""
    env = env or EnvSettings()
    try:
        filter_config = load_filter_config(FILTERS_FILE)
        keywords = load_keywords(KEYWORDS_FILE)
    except ConfigFileError as exc:
        raise RuntimeError(f"Configuration error: {exc}") from exc

    scraper_timezone = env.get_alias(
        "JOBFINDER_SCRAPER_TIMEZONE",
        "JOBSCRAPER_TIMEZONE",
        default="Europe/Berlin",
    )
    posted_timezone = env.get_alias(
        "JOBFINDER_SCRAPER_POSTED_TIMEZONE",
        "JOBSCRAPER_POSTED_TIMEZONE",
        default="Europe/Berlin",
    )
    scraper_tz = load_timezone(scraper_timezone, "JOBFINDER_SCRAPER_TIMEZONE")
    posted_tz = load_timezone(posted_timezone, "JOBFINDER_SCRAPER_POSTED_TIMEZONE")

    run_started_at_utc = datetime.now(UTC)
    run_started_at = run_started_at_utc.astimezone(scraper_tz)

    max_results_per_search = max(
        1,
        env.get_int_alias(
            "JOBFINDER_SCRAPER_MAX_RESULTS_PER_SEARCH",
            "JOBSCRAPER_MAX_RESULTS_PER_SEARCH",
            default=500,
        ),
    )
    indeed_max_results = min(
        INDEED_MAX_RESULTS_LIMIT,
        max(
            1,
            env.get_int("INDEED_MAX_RESULTS_PER_SEARCH", max_results_per_search),
        ),
    )
    stepstone_max_results = max(
        1,
        env.get_int("STEPSTONE_MAX_RESULTS_PER_SEARCH", max_results_per_search),
    )
    apify_run_timeout_seconds = max(
        60,
        env.get_int("APIFY_RUN_TIMEOUT_SECONDS", DEFAULT_APIFY_RUN_TIMEOUT_SECONDS),
    )
    apify_client_timeout_seconds = max(
        1,
        env.get_int(
            "APIFY_CLIENT_TIMEOUT_SECONDS",
            DEFAULT_APIFY_CLIENT_TIMEOUT_SECONDS,
        ),
    )
    location = config_str(filter_config, "linkedin_search", "location", "Germany")
    config_max_applicants = config_int(
        filter_config, "final_filters", "max_applicants", 100
    )

    apify_run_memory_mb = max(128, env.get_int("APIFY_RUN_MEMORY_MB", 512))
    apify_memory_limit_mb = max(
        0,
        env.get_int_alias(
            "JOBFINDER_SCRAPER_APIFY_MEMORY_LIMIT_MB",
            "JOBSCRAPER_APIFY_MEMORY_LIMIT_MB",
            default=0,
        ),
    )
    search_concurrency = min(
        MAX_SEARCH_CONCURRENCY,
        max(
            1,
            env.get_int_alias(
                "JOBFINDER_SCRAPER_SEARCH_CONCURRENCY",
                "JOBSCRAPER_SEARCH_CONCURRENCY",
                default=15,
            ),
        ),
    )
    if apify_memory_limit_mb:
        search_concurrency = min(
            search_concurrency,
            max(1, apify_memory_limit_mb // apify_run_memory_mb),
        )
    raw_apify_token = env.get(APIFY_API_TOKEN_ENV)
    apify_api_tokens = parse_apify_api_tokens(raw_apify_token)

    return ScraperSettings(
        env=env,
        filter_config=filter_config,
        keywords=keywords,
        apify_api_token=apify_api_tokens[0] if apify_api_tokens else raw_apify_token,
        apify_api_tokens=apify_api_tokens,
        apify_token_pool=ApifyTokenPool(apify_api_tokens),
        google_spreadsheet_id=env.get("GOOGLE_SPREADSHEET_ID"),
        scraper_timezone=scraper_timezone,
        posted_timezone=posted_timezone,
        scraper_tz=scraper_tz,
        posted_tz=posted_tz,
        run_started_at_utc=run_started_at_utc,
        run_started_at=run_started_at,
        run_sheet_name=run_started_at.strftime("%Y-%m-%d %H-%M-%S"),
        source_mode=env.get_alias(
            "JOBFINDER_SCRAPER_SOURCES",
            "JOBSCRAPER_SOURCES",
            default="linkedin",
        ).lower(),
        output_mode=env.get_alias(
            "JOBFINDER_SCRAPER_OUTPUT_MODE",
            "JOBSCRAPER_OUTPUT_MODE",
            default="excel",
        ).lower(),
        excel_output_file=DEFAULT_EXCEL_FILE,
        max_results_per_search=max_results_per_search,
        indeed_max_results_per_search=indeed_max_results,
        search_concurrency=search_concurrency,
        apify_batch_size=min(
            MAX_APIFY_BATCH_SIZE,
            max(
                1,
                env.get_int_alias(
                    "JOBFINDER_SCRAPER_APIFY_BATCH_SIZE",
                    "JOBSCRAPER_APIFY_BATCH_SIZE",
                    default=1,
                ),
            ),
        ),
        apify_memory_limit_mb=apify_memory_limit_mb,
        apify_run_memory_mb=apify_run_memory_mb,
        apify_run_timeout_seconds=apify_run_timeout_seconds,
        apify_client_timeout_seconds=apify_client_timeout_seconds,
        apify_transient_error_retries=max(
            0,
            env.get_int(
                "APIFY_TRANSIENT_ERROR_RETRIES",
                DEFAULT_APIFY_TRANSIENT_ERROR_RETRIES,
            ),
        ),
        apify_retry_delay_seconds=max(
            0,
            env.get_int("APIFY_RETRY_DELAY_SECONDS", DEFAULT_APIFY_RETRY_DELAY_SECONDS),
        ),
        delay_between_requests=max(
            0,
            env.get_int_alias(
                "JOBFINDER_SCRAPER_DELAY_BETWEEN_REQUESTS",
                "JOBSCRAPER_DELAY_BETWEEN_REQUESTS",
                default=0,
            ),
        ),
        search_window_buffer_seconds=max(
            0,
            env.get_int_alias(
                "JOBFINDER_SCRAPER_SEARCH_WINDOW_BUFFER_SECONDS",
                "JOBSCRAPER_SEARCH_WINDOW_BUFFER_SECONDS",
                default=3600,
            ),
        ),
        posted_time_window=parse_posted_time_window(
            env.get_alias(
                "JOBFINDER_SCRAPER_POSTED_TIME_WINDOW",
                "JOBSCRAPER_POSTED_TIME_WINDOW",
            )
        ),
        location=location,
        geo_id=config_str(filter_config, "linkedin_search", "geo_id", "101282230"),
        published_at=config_str(
            filter_config, "linkedin_search", "published_at", "r86400"
        ),
        experience_levels=config_list(
            filter_config, "linkedin_search", "experience_levels", ["1", "2"]
        ),
        contract_types=config_list(
            filter_config, "linkedin_search", "contract_types", ["F", "P", "I"]
        ),
        scrape_company_details=env.get_bool_alias(
            "JOBFINDER_SCRAPER_SCRAPE_COMPANY_DETAILS",
            "JOBSCRAPER_SCRAPE_COMPANY_DETAILS",
            default=False,
        ),
        use_incognito_mode=env.get_bool_alias(
            "JOBFINDER_SCRAPER_USE_INCOGNITO_MODE",
            "JOBSCRAPER_USE_INCOGNITO_MODE",
            default=True,
        ),
        split_by_location=env.get_bool_alias(
            "JOBFINDER_SCRAPER_SPLIT_BY_LOCATION",
            "JOBSCRAPER_SPLIT_BY_LOCATION",
            default=False,
        ),
        split_country=config_str(
            filter_config, "linkedin_search", "split_country", "DE"
        ),
        excluded_title_terms=config_list(
            filter_config,
            "final_filters",
            "excluded_title_terms",
            ["Werkstudent", "Working Student", "Senior"],
        ),
        excluded_company_terms=config_list(
            filter_config,
            "final_filters",
            "excluded_company_terms",
            DEFAULT_EXCLUDED_COMPANY_TERMS,
        ),
        max_applicants=max(
            0,
            env.get_int_alias(
                "JOBFINDER_SCRAPER_MAX_APPLICANTS",
                "JOBSCRAPER_MAX_APPLICANTS",
                default=config_max_applicants,
            ),
        ),
        application_status_options=config_list(
            filter_config,
            "spreadsheet",
            "application_status_options",
            ["applied", "rejected", "interview", "accepted"],
        ),
        indeed_country=env.get("INDEED_COUNTRY", "DE").upper(),
        indeed_location=env.get("INDEED_LOCATION", location),
        indeed_max_concurrency=min(
            MAX_PROVIDER_CONCURRENCY,
            max(1, env.get_int("INDEED_MAX_CONCURRENCY", 5)),
        ),
        indeed_save_only_unique_items=env.get_bool(
            "INDEED_SAVE_ONLY_UNIQUE_ITEMS", True
        ),
        stepstone_location=env.get(
            "STEPSTONE_LOCATION",
            config_str(filter_config, "stepstone_search", "location", "deutschland"),
        ),
        stepstone_category=env.get(
            "STEPSTONE_CATEGORY",
            config_str(filter_config, "stepstone_search", "category", ""),
        ),
        stepstone_start_urls=parse_env_list(env.get("STEPSTONE_START_URLS"))
        or config_list(filter_config, "stepstone_search", "start_urls", []),
        stepstone_max_results_per_search=stepstone_max_results,
        stepstone_max_concurrency=min(
            MAX_PROVIDER_CONCURRENCY,
            max(1, env.get_int("STEPSTONE_MAX_CONCURRENCY", 10)),
        ),
        stepstone_min_concurrency=max(1, env.get_int("STEPSTONE_MIN_CONCURRENCY", 1)),
        stepstone_max_request_retries=max(
            0,
            env.get_int("STEPSTONE_MAX_REQUEST_RETRIES", 3),
        ),
        stepstone_use_apify_proxy=env.get_bool("STEPSTONE_USE_APIFY_PROXY", True),
        stepstone_proxy_groups=parse_env_list(
            env.get("STEPSTONE_APIFY_PROXY_GROUPS", "RESIDENTIAL")
        ),
        source_actor_ids={
            "linkedin": LINKEDIN_ACTOR_ID,
            "indeed": INDEED_ACTOR_ID,
            "stepstone": STEPSTONE_ACTOR_ID,
        },
        source_max_items={
            "linkedin": max_results_per_search,
            "indeed": indeed_max_results,
            "stepstone": stepstone_max_results,
        },
    )


def parse_posted_time_window(value: str | None) -> str:
    """Resolve the selected posted-time window for scraper runs."""
    normalized = (value or POSTED_TIME_WINDOW_SINCE_PREVIOUS_RUN).strip().casefold()
    if not normalized:
        return POSTED_TIME_WINDOW_SINCE_PREVIOUS_RUN

    window = POSTED_TIME_WINDOW_ALIASES.get(normalized)
    if window:
        return window

    allowed = ", ".join(
        [
            POSTED_TIME_WINDOW_SINCE_PREVIOUS_RUN,
            POSTED_TIME_WINDOW_LAST_24H,
            POSTED_TIME_WINDOW_LAST_7D,
            POSTED_TIME_WINDOW_BACKFILL,
        ]
    )
    raise RuntimeError(
        "Unsupported JOBFINDER_SCRAPER_POSTED_TIME_WINDOW "
        f"{value!r}. Use one of: {allowed}."
    )


def parse_env_list(value: str | None) -> list[str]:
    """Parse comma/newline separated environment settings."""
    if not value:
        return []
    items = re.split(r"[\n,]+", value)
    return [item.strip() for item in items if item.strip()]


def parse_apify_api_tokens(value: str | None) -> tuple[str, ...]:
    """Parse semicolon-separated Apify API tokens from one env setting."""
    if not value:
        return ()

    tokens: list[str] = []
    seen: set[str] = set()
    for item in value.split(TOKEN_SEPARATOR):
        token = item.strip()
        if not token or token == TOKEN_PLACEHOLDER or token in seen:
            continue
        if len(tokens) >= MAX_APIFY_API_TOKENS:
            raise RuntimeError(
                f"{APIFY_API_TOKEN_ENV} supports at most {MAX_APIFY_API_TOKENS} "
                f"semicolon-separated token(s)."
            )
        tokens.append(token)
        seen.add(token)
    return tuple(tokens)


def load_timezone(value: str, setting_name: str) -> ZoneInfo:
    """Load an IANA timezone or raise a user-facing runtime error."""
    try:
        return ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        raise RuntimeError(
            f"Timezone '{value}' is not available. Install tzdata or set "
            f"{setting_name} to a valid IANA timezone."
        ) from exc


def source_label(source: str) -> str:
    """Return a display label for a job source."""
    return SOURCE_DISPLAY_NAMES.get(source, source.title())
