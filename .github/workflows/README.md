# GitHub Workflows

This directory contains the repository's CI workflow and production JobFinder
pipeline workflow.

## `ci.yml`

Runs on:

- Pull requests.
- Pushes to `main`.

Checks:

1. Checkout.
2. Set up Python 3.14 with pip cache.
3. Install LaTeX tools for PDF-generation coverage.
4. Install `requirements-dev.txt`.
5. Run Ruff lint.
6. Run Ruff formatting check.
7. Run mypy on `src`.
8. Compile Python files.
9. Smoke-test CLI help with `PYTHONPATH=src`.
10. Validate `configs/filters.json`.
11. Run `pytest`.

This workflow does not require Apify, Google, or OpenAI secrets. Tests use fakes
and monkeypatching for external services.

## `jobs.yml`

Runs JobFinder in GitHub Actions.

Triggers:

- Manual `workflow_dispatch`.
- Daily schedule at `17 7 * * *`.

Manual inputs:

| Input | Options |
|---|---|
| `sources` | `linkedin`, `indeed`, `stepstone`, `xing`, `all` |
| `posted_time_window` | `since_previous_run`, `last_24h`, `last_7d`, `backfill` |
| `max_applicants` | `50`, `100`, `200`, `no_limit` |
| `run_mode` | `scrape_and_evaluate`, `scrape_only` |
| `unsuitable_rows` | `single_label_only`, `keep_all` |

## Production Job Flow

```mermaid
flowchart TD
    A["checkout"] --> B["setup Python 3.14"]
    B --> C["install LaTeX tools"]
    C --> D["install requirements.txt"]
    D --> E["validate required secrets"]
    E --> F["write private keyword/prompt/CV/photo files"]
    F --> G["write Google OAuth token and spreadsheet ID"]
    G --> H["preflight provider and sheet access"]
    H --> I["run selected pipeline"]
    I --> J["write workflow summary"]
    J --> K["upload report artifacts"]
    K --> L["remove private runtime files"]
```

The workflow sets `JOBFINDER_SCRAPER_OUTPUT_MODE=google_sheets` and writes private
runtime files from secrets. Cleanup removes those files in an `always()` step.

## Required Secrets

| Secret | Required when | Description |
|---|---|---|
| `APIFY_API_TOKEN` | Always | One Apify token or up to 12 semicolon-separated tokens. |
| `GOOGLE_SPREADSHEET_ID` | Always | Target spreadsheet ID. |
| `GOOGLE_TOKEN_JSON` | Always | Full authorized-user token JSON from `google_token.json` for Sheets and Drive. |
| `JOB_EVAL_CV_DRIVE_FOLDER_ID` | `scrape_and_evaluate` | Drive folder ID for generated CV PDF run folders. |
| `JOB_KEYWORDS_TEXT` | Always | Contents of private `configs/keywords.txt`. |
| `OPENAI_API_KEY` | `scrape_and_evaluate` | OpenAI API key. |
| `MASTER_PROMPT_TEXT` | `scrape_and_evaluate` | Contents of private evaluator prompt. |
| `MASTER_CV_TEX` | `scrape_and_evaluate` | Contents of private LaTeX CV. |
| `CV_PHOTO_BASE64` | Optional | Base64-encoded private CV photo for LaTeX PDF generation. |

## Report Artifacts

`jobs.yml` uploads `jobfinder-run-reports` with:

- `reports/pipeline_preflight.json`
- `reports/scraper.json`
- `reports/evaluator.json`
- `reports/workflow_summary.md`

Reports are generated only when the corresponding env var path is configured.

## Operational Constraints

- `concurrency.cancel-in-progress` is `false`, so scheduled/manual runs do not
  cancel an already running pipeline.
- The job timeout is 360 minutes.
- Scheduled runs use default workflow inputs, not the last manual selections.
- The workflow writes Google OAuth token JSON to a temporary runner file and
  applies restrictive file permissions before use.
- Do not echo secret values while debugging.
