# Operations

This package contains small operational helpers used by local and GitHub Actions
runs. It keeps reporting behavior in one place so workflow artifacts are useful
without exposing private job data or credentials.

## Prerequisites

- Python 3.14 or newer.
- A caller that sets one of the report-path environment variables.

## Quick Start

Set a report destination, then run a command that writes reports:

```bash
JOBFINDER_PIPELINE_REPORT_FILE=reports/pipeline_preflight.json python run_job_pipeline.py --mode scrape_only --preflight
```

## Reports

`reports.py` writes sanitized JSON report files when report paths are configured
through environment variables:

- `JOBFINDER_PIPELINE_REPORT_FILE`
- `JOBFINDER_SCRAPER_REPORT_FILE`
- `JOBFINDER_EVALUATOR_REPORT_FILE`

Reports contain:

| Field | Description |
|---|---|
| `status` | `succeeded` or `failed`. |
| `category` | Report category such as `preflight`, `scrape`, or `evaluation`. |
| `generated_at` | UTC timestamp. |
| `details` | Dataclass or dictionary payload from the caller. |

The helper serializes dataclasses with `dataclasses.asdict()` and sorts JSON
keys for stable artifacts.

## Usage Example

```python
from jobfinder.operations.reports import write_report_from_env

write_report_from_env(
    "JOBFINDER_SCRAPER_REPORT_FILE",
    "succeeded",
    "scrape",
    {"unique_job_count": 12},
)
```

If the environment variable is not set, no report file is written.

## Use This For Your Own Project

Forks can add new summary fields, but report payloads should stay sanitized and
small. Put raw scraped jobs, prompts, CV content, API tokens, and Google token
JSON somewhere else, not in report artifacts.

## Constraints

- Do not write secrets into report details.
- Use reports for summaries and diagnostics, not raw scraped job data.
- Keep report payloads durable enough for CI artifact review.

## Troubleshooting

| Problem | What to check |
|---|---|
| No report file appears | Confirm the matching `JOBFINDER_*_REPORT_FILE` variable is set. |
| Report upload artifact is empty | Confirm the file path is under `reports/` in `.github/workflows/jobs.yml`. |
| Sensitive text appears in a report | Remove it at the caller. `reports.py` does not know which arbitrary fields are secrets. |
