# Scraper Provider Compatibility Package

This package contains provider modules historically imported by scraper code.
It now re-exports implementations from `jobfinder.providers` so older imports
keep working while new code uses the stable provider package.

## Prerequisites

- Python 3.14 or newer.
- Existing downstream imports that still point at `jobfinder.scraper.providers`.

## Quick Start

Use the stable import path for new code:

```python
from jobfinder.providers.registry import provider_adapter
```

Legacy imports still work:

```python
from jobfinder.scraper.providers.apify_client import run_actor
```

## Files

| File | Role |
|---|---|
| `apify_client.py` | Compatibility wrapper around `jobfinder.providers.apify_client`. |
| `linkedin.py` | Compatibility wrapper around `jobfinder.providers.linkedin`. |
| `indeed.py` | Compatibility wrapper around `jobfinder.providers.indeed`. |
| `stepstone.py` | Compatibility wrapper around `jobfinder.providers.stepstone`. |
| `xing.py` | Compatibility wrapper around `jobfinder.providers.xing`. |

## Apify Execution Contract

`apify_client.run_actor()`:

1. Selects the active Apify token.
2. Starts an actor run through the async Apify API.
3. Polls run status until a terminal status.
4. Fetches the default dataset items.
5. Retires unavailable tokens and retries with the next token when configured.

Temporary HTTP/API failures are represented as `ApifyTransientError` and retried
by `scraper/search.py` according to scraper settings.

## Use This For Your Own Project

Do not add new provider behavior here in a fork. Add payload builders,
normalizers, actor runners, and registrations under `jobfinder.providers`, then
keep this package as a compatibility layer only if older local code still imports
it.

## Maintainer Note

Prefer adding new provider adapter logic under `jobfinder.providers`. Keep this
package for compatibility until downstream imports no longer require it.

## Troubleshooting

| Problem | What to check |
|---|---|
| New provider is not available through legacy imports | Add a small compatibility wrapper only after the stable provider module exists. |
| Tests monkeypatch the old Apify path | Keep `apify_client.py` re-exporting the names tests patch, including `requests`. |
| Import cycles appear | Move real behavior back to `jobfinder.providers`; this package should not own implementation logic. |
