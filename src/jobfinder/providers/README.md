# Provider Adapters

This package defines the stable provider adapter surface for source-specific job
boards. Provider adapters translate JobFinder settings into Apify actor payloads
and translate actor output back into the raw job contract consumed by the
scraper, dedupe, and exporters.

## Prerequisites

- Python 3.14 or newer.
- An Apify API token for real actor runs.
- Provider actor access in the Apify account used by `APIFY_API_TOKEN`.
- Focused tests for payload and normalization changes.

## Quick Start

Run provider tests without external services:

```bash
python -m pytest tests/test_indeed_provider.py tests/test_stepstone_provider.py tests/test_xing_provider.py tests/test_scraper_search.py
```

Run one provider locally after configuring `.env` and `configs/keywords.txt`:

```bash
JOBFINDER_SCRAPER_OUTPUT_MODE=excel JOBFINDER_SCRAPER_SOURCES=indeed python linkedin_job_scraper.py
```

## Current Providers

| Provider | Actor | Main module | Responsibilities |
|---|---|---|---|
| LinkedIn | `curious_coder~linkedin-jobs-scraper` | `jobfinder.providers.linkedin` | Build LinkedIn search URLs and actor payloads. |
| Indeed | `valig~indeed-jobs-scraper` | `jobfinder.providers.indeed` | Build country/title/location payloads, map date windows to actor day buckets, normalize actor output and metadata. |
| Stepstone | `memo23~stepstone-search-cheerio-ppr` | `jobfinder.providers.stepstone` | Build keyword/location/category or direct-URL payloads, map date windows to actor day buckets, normalize Stepstone URLs and metadata. |
| Xing | `shahidirfan~Xing-Jobs-Scraper` | `jobfinder.providers.xing` | Build keyword/location/discipline or direct-URL payloads, normalize Xing output and metadata. |

`jobfinder.providers.apify_client` owns the low-level Apify client. The old
`jobfinder.scraper.providers.*` paths are compatibility facades.

## Import Boundary

New provider-specific code should prefer imports from:

```python
from jobfinder.providers import indeed, linkedin, stepstone, xing
from jobfinder.providers.registry import provider_adapter
```

The scraper uses `ProviderAdapter` registrations from `providers/registry.py`
instead of hard-coding provider execution details in search orchestration.

## Adapter Contract

A provider adapter should provide:

- A function that builds the actor payload from `ScraperSettings`.
- A function that runs the actor through the shared Apify runner.
- A normalizer that converts source-specific actor rows into a stable raw job
  dictionary.
- A `ProviderAdapter` registration when the source should be runnable by the
  generic scraper workflow.

The normalized raw job should prefer these shared field names where possible:

| Field | Meaning |
|---|---|
| `jobId`, `job_id`, `id` | Provider-native job identifier. |
| `title` | Job title. |
| `companyName` | Employer display name. |
| `companyDetails` | Optional nested company metadata. |
| `location` | Human-readable location. |
| `jobType` / `employmentType` | Employment type text. |
| `description` / `descriptionText` | Description used for spreadsheet and evaluator context. |
| `postedAt` | Posting timestamp or date text. |
| `jobUrl` / `url` | Public provider job URL. |
| `applyUrl` | External apply URL when available. |

Internal provider metadata should use `_jobfinder_*` keys so it can enrich
descriptions and dedupe without becoming spreadsheet columns accidentally.

## Date Window Behavior

Scraper settings expose provider posted-time windows as LinkedIn-style values
such as `r86400`.
Adapters map this to each actor's supported filter surface:

- Indeed supports fixed day buckets `1`, `3`, `7`, and `14`.
- Stepstone supports fixed day buckets `1`, `3`, and `7`.
- Xing has no provider posted-time input in JobFinder, so filtering happens
  after scraping when `date_posted` is present.
- Larger windows omit or relax provider date filters and rely on post-scrape
  filtering where possible.

## Extension Checklist

When adding a provider:

1. Add provider settings and actor ID in `scraper/settings.py`.
2. Add source aliases and display name.
3. Add payload builder and normalizer in this package.
4. Register the provider in `providers/registry.py`.
5. Decide whether failures should be fatal or source-isolated.
6. Add provider tests for payload construction, output normalization, and URL
   handling.
7. Update root docs, this README, and configuration examples.

## Use This For Your Own Project

Forks can usually reuse the existing providers by changing configuration rather
than code:

| Need | Change |
|---|---|
| Source mix | `JOBFINDER_SCRAPER_SOURCES`. |
| LinkedIn geography | `configs/filters.json` `linkedin_search.location` and `geo_id`. |
| Indeed geography | `INDEED_COUNTRY` and `INDEED_LOCATION`. |
| Stepstone geography or direct URL mode | `STEPSTONE_LOCATION` or `STEPSTONE_START_URLS`. |
| Xing geography or direct URL mode | `XING_LOCATION`, `XING_DISCIPLINE`, `XING_REMOTE`, or `XING_START_URL`. |
| Apify cost and speed | Per-source max-results and concurrency settings. |

Only add or edit adapter code when a provider actor schema changes, a new
provider is needed, or normalization loses fields that downstream code uses.

## Troubleshooting

| Problem | What to check |
|---|---|
| Actor returns no jobs | Verify keyword, location, posted-time window, direct URL settings, and actor status in Apify. |
| Actor fails with 401, 402, or 403 | Check token validity, actor access, billing, and fallback tokens. |
| Normalized rows miss company/title/location | Update the provider normalizer and add a focused fixture to the provider test. |
| New provider works alone but not through scraper | Confirm it is registered in `providers/registry.py` and included in `SOURCE_ALIASES` / `SOURCE_ORDER`. |
