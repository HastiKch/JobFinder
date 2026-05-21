# Provider Adapters

This package defines the stable provider adapter surface for source-specific job
boards. Provider adapters translate JobFinder settings into Apify actor payloads
and translate actor output back into the raw job contract consumed by the
scraper, dedupe, and exporters.

## Current Providers

| Provider | Actor | Main module | Responsibilities |
|---|---|---|---|
| LinkedIn | `curious_coder~linkedin-jobs-scraper` | `jobfinder.providers.linkedin` | Build LinkedIn search URLs and actor payloads. |
| Indeed | `valig~indeed-jobs-scraper` | `jobfinder.providers.indeed` | Build country/title/location payloads, map date windows to actor day buckets, normalize actor output and metadata. |
| Stepstone | `memo23~stepstone-search-cheerio-ppr` | `jobfinder.providers.stepstone` | Build keyword/location/category or direct-URL payloads, map date windows to actor day buckets, normalize Stepstone URLs and metadata. |

`jobfinder.providers.apify_client` owns the low-level Apify client. The old
`jobfinder.scraper.providers.*` paths are compatibility facades.

## Import Boundary

New provider-specific code should prefer imports from:

```python
from jobfinder.providers import indeed, linkedin, stepstone
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

Scraper settings use LinkedIn-style `published_at` values such as `r86400`.
Adapters map this to each actor's supported filter surface:

- Indeed supports fixed day buckets `1`, `3`, `7`, and `14`.
- Stepstone supports fixed day buckets `1`, `3`, and `7`.
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
