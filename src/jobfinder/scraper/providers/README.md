# Scraper Provider Compatibility Package

This package contains provider modules historically imported by scraper code.
It now serves two roles:

- Own the low-level Apify client.
- Re-export provider implementations from `jobfinder.providers` for
  compatibility.

## Files

| File | Role |
|---|---|
| `apify_client.py` | Low-level asynchronous Apify actor execution, polling, dataset fetches, retry classification, and token fallback handling. |
| `linkedin.py` | LinkedIn search URL and actor payload construction. |
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

## Maintainer Note

Prefer adding new provider adapter logic under `jobfinder.providers`. Keep this
package for compatibility until downstream imports no longer require it.
