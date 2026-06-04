# Configuration Files

`configs/` contains the user-editable, non-secret scraper configuration for
JobFinder. Forks use this directory to choose search geography, search terms,
post-scrape filters, and spreadsheet status values without changing code.

Private search keywords are local-only. Shared non-secret defaults and filters
are committed.

## Prerequisites

- A local clone of the repository.
- Python dependencies installed if you want to validate with tests.
- Private keywords created as `configs/keywords.txt` for local runs, or saved in
  the GitHub secret `JOB_KEYWORDS_TEXT` for Actions runs.

## Quick Start

```bash
cp configs/keywords.example.txt configs/keywords.txt
python -m json.tool configs/filters.json
python -m pytest tests/test_config_files.py
```

Then edit `configs/keywords.txt` for private search terms and
`configs/filters.json` for shared, non-secret defaults.

## Use This For Your Own Project

Most forks should review:

| Need | Change |
|---|---|
| Different search location | `linkedin_search.location`, `linkedin_search.geo_id`, `stepstone_search.location`, and `xing_search.location`. |
| Different providers or output mode | Environment variables such as `JOBFINDER_SCRAPER_SOURCES` and `JOBFINDER_SCRAPER_OUTPUT_MODE`, not this file. |
| Different blocked titles or companies | `final_filters.excluded_title_terms` and `final_filters.excluded_company_terms`. |
| Different applicant-count cutoff | `final_filters.max_applicants`, or override with `JOBFINDER_SCRAPER_MAX_APPLICANTS`. |
| Different application status values | `spreadsheet.application_status_options`. |

Do not commit `configs/keywords.txt`; it usually reveals private job-search
intent. Commit `configs/filters.json` only when the values are safe to share.

## Files

| File | Commit? | Purpose |
|---|---|---|
| `filters.json` | Yes | Provider defaults, final filters, and spreadsheet dropdown values. |
| `keywords.example.txt` | Yes | Example keyword file. |
| `keywords.txt` | No | Private keyword list used by local and non-CI scraper runs. |

## `keywords.txt`

Create it from the example:

```bash
cp configs/keywords.example.txt configs/keywords.txt
```

Rules:

- One keyword per line.
- Blank lines are ignored.
- Lines starting with `#` are ignored.
- The file must contain at least one usable keyword.

Example:

```text
GIS analyst
geospatial data
remote sensing
```

Each keyword is searched against each selected provider, except Stepstone and
Xing direct URL modes.

## `filters.json`

Current sections:

```json
{
  "linkedin_search": {},
  "stepstone_search": {},
  "xing_search": {},
  "final_filters": {},
  "spreadsheet": {}
}
```

### `linkedin_search`

| Key | Meaning |
|---|---|
| `location` | LinkedIn search location. Also used as default Indeed location when `INDEED_LOCATION` is unset. |
| `geo_id` | LinkedIn geo ID. |
| `published_at` | Default LinkedIn-style posted-time value, such as `r86400`. Runtime posted-window logic can override it. |
| `experience_levels` | LinkedIn experience filter values. |
| `contract_types` | LinkedIn job-type filter values. |
| `split_country` | LinkedIn actor split-country value when location splitting is enabled. |

### `stepstone_search`

| Key | Meaning |
|---|---|
| `location` | Stepstone location fallback when `STEPSTONE_LOCATION` is unset. |
| `category` | Optional Stepstone category fallback. |
| `start_urls` | Optional direct URL list. Overridden by `STEPSTONE_START_URLS`. |

### `xing_search`

| Key | Meaning |
|---|---|
| `location` | Xing location fallback when `XING_LOCATION` is unset. |
| `discipline` | Optional Xing discipline fallback. |
| `remote` | Optional Xing remote filter fallback. |
| `start_url` | Optional direct Xing search URL. Overridden by `XING_START_URL`. |
| `max_pages` | Maximum Xing result pages when `XING_MAX_PAGES` is unset. |

### `final_filters`

| Key | Meaning |
|---|---|
| `excluded_title_terms` | Case-insensitive title filters applied after dedupe. |
| `excluded_company_terms` | Case-insensitive and punctuation-tolerant company filters applied after dedupe. |
| `max_applicants` | Applicant cap used when `JOBFINDER_SCRAPER_MAX_APPLICANTS` is unset. |

`JOBFINDER_SCRAPER_MAX_APPLICANTS=0` disables the applicant-count filter. The
legacy alias `JOBSCRAPER_MAX_APPLICANTS` is still accepted.

### `spreadsheet`

| Key | Meaning |
|---|---|
| `application_status_options` | Google Sheets dropdown values for `Application Status`. |

## Validation

Run:

```bash
python -m json.tool configs/filters.json
python -m pytest tests/test_config_files.py
```

The loader is intentionally forgiving for scalar/list config values, but the
top-level file must be valid JSON and must contain a JSON object.

## Troubleshooting

| Problem | What to check |
|---|---|
| `keywords.txt does not contain any keywords` | Add at least one non-comment line to `configs/keywords.txt`. |
| JSON validation fails | Fix commas, quotes, or braces in `configs/filters.json`, then rerun `python -m json.tool configs/filters.json`. |
| Source still searches the old location | Check provider-specific environment variables in `.env` or `.github/workflows/jobs.yml`; real env values override file defaults. |
| Applicant filter does not match `filters.json` | Check `JOBFINDER_SCRAPER_MAX_APPLICANTS`; it overrides `final_filters.max_applicants`. |
