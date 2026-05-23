# Configuration Files

`configs/` contains user-editable scraper configuration.

Private search keywords are local-only. Shared non-secret defaults and filters
are committed.

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
| `max_applicants` | Applicant cap used when `JOBSCRAPER_MAX_APPLICANTS` is unset. |

`JOBSCRAPER_MAX_APPLICANTS=0` disables the applicant-count filter.

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
