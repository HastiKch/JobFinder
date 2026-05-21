# Tests

The test suite verifies JobFinder behavior without making real Apify, Google, or
OpenAI network calls.

Run all tests:

```bash
python -m pytest
```

Run CI-equivalent checks from the repository root:

```bash
python -m ruff check .
python -m ruff format --check .
python -m mypy src
python -m compileall src tests scripts run_job_pipeline.py linkedin_job_scraper.py job_fit_evaluator.py job_scraper_config.py
python -m json.tool configs/filters.json
python -m pytest
```

## Test Map

| Test file | Coverage |
|---|---|
| `test_config_files.py` | Keyword and filter config loading. |
| `test_scraper_settings.py` | Scraper settings resolution, token parsing, provider defaults, and value clamping. |
| `test_scraper_search.py` | Apify async execution, retries, token fallback, source parsing, batching, concurrency, and Stepstone failure isolation. |
| `test_scraper_filters.py` | Company and applicant-count filters. |
| `test_scraper_normalize.py` | Applicant parsing, HTML description cleanup, and scraper dedupe facade. |
| `test_scraper_export_rows.py` | Spreadsheet header and row generation. |
| `test_scraper_run_history.py` | Previous-run windows, exact posted filtering, historical duplicate keys, and seen-jobs index behavior. |
| `test_dedupe_matching.py` | Cross-provider matching, blockers, provenance, and historical dedupe identity. |
| `test_google_sheets.py` | Google auth config, service-account preference, missing credential messages, and OAuth token rewrite permissions. |
| `test_cv_pdf_output.py` | PDF filename sanitization, CV ID assignment, LaTeX compile failures, Drive folder naming, and mocked Drive uploads. |
| `test_indeed_provider.py` | Indeed actor payloads and normalization. |
| `test_stepstone_provider.py` | Stepstone actor payloads and normalization. |
| `test_evaluator_parsing.py` | Header updates, prompt row extraction, model-response parsing, and cleanup column selection. |
| `test_evaluator_storage.py` | Excel/Google writes, incremental-save cleanup behavior, and unsuitable-row policy. |
| `test_evaluator_openai_client.py` | Evaluator batching, callbacks, and large-queue pacing. |
| `test_evaluator_cli.py` | Evaluator source aliases and row-policy parsing. |
| `test_pipeline_cli.py` | Pipeline mode aliases and required secret validation. |

## External Service Strategy

Tests use:

- Simple fake response/service classes.
- `monkeypatch` for HTTP clients and provider runners.
- Temporary files for Excel and config tests.
- No real credentials.
- No network calls.

If a new test needs network access, prefer adding a fake adapter seam instead.

## Focused Test Guidance

| Change area | Suggested tests |
|---|---|
| Provider payload/normalization | Provider-specific test plus `test_scraper_search.py`. |
| Dedupe identity | `test_dedupe_matching.py`, `test_scraper_run_history.py`. |
| Spreadsheet schema | `test_scraper_export_rows.py`, `test_evaluator_parsing.py`, `test_evaluator_storage.py`. |
| Evaluator prompt or parsing | `test_evaluator_parsing.py`, `test_evaluator_openai_client.py`. |
| CV PDF output | `test_cv_pdf_output.py`, `test_evaluator_storage.py`. |
| Pipeline/GitHub settings | `test_pipeline_cli.py`, `test_scraper_settings.py`. |

## Maintaining Tests

- Keep tests deterministic and free of real secrets.
- Prefer small representative provider payloads over large captured fixtures.
- When changing column names, update scraper, evaluator, and schema tests
  together.
- When changing defaults, update `.env.example`, docs, and tests together.
