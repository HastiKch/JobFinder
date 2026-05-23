# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install all dependencies (including dev)
pip install -r requirements-dev.txt
pip install -e .

# Run all tests
python -m pytest

# Run a single test file
python -m pytest tests/test_cv_pdf_output.py

# Run a single test by name
python -m pytest tests/test_cv_pdf_output.py::test_cv_pdf_filename_uses_requested_parts_in_order

# Lint
python -m ruff check .

# Format
python -m black .

# Type-check
python -m mypy src

# Run the full pipeline (scrape + evaluate)
python run_job_pipeline.py

# Run scraper only
jobfinder-scrape        # or: python scripts/scrape_jobs.py

# Run evaluator only
jobfinder-evaluate      # or: python scripts/evaluate_jobs.py

# Run pipeline with a specific mode
JOBFINDER_PIPELINE_MODE=scrape_only python run_job_pipeline.py
```

## Architecture

JobFinder is a three-stage Python pipeline: **scrape → evaluate → export**. All meaningful logic lives under `src/jobfinder/`. Root-level scripts (`run_job_pipeline.py`, `scripts/`, `linkedin_job_scraper.py`, etc.) are thin backward-compatible entry points only.

### Stage 1 — Scraping (`scraper/` + `providers/`)

The scraper calls Apify cloud actors for four job boards: LinkedIn, Indeed, Stepstone, Xing. Each provider has a stable module under `providers/` (payload builder, actor output normalizer) and a thin compatibility re-export under `scraper/providers/`.

Provider dispatch is registered in `providers/registry.py` via `ProviderAdapter`. Adding a new provider means: (1) create `providers/<name>.py`, (2) add a `ProviderAdapter` entry in `PROVIDER_ADAPTERS`.

`scraper/search.py` orchestrates concurrent keyword × provider searches using `ScraperSettings` (resolved in `scraper/settings.py`). After scraping, `scraper/filters.py` applies the global post-scrape filters (excluded titles, excluded companies, max applicants), and `scraper/normalize.py` normalizes raw actor output into the canonical spreadsheet row shape.

Search filters per provider come from `configs/filters.json`. Keywords come from `configs/keywords.txt` (one per line, injected from `JOB_KEYWORDS_TEXT` secret in CI). `scraper/run_history.py` tracks previously seen job IDs to skip already-exported jobs.

### Stage 2 — Evaluation (`evaluator/`)

The evaluator reads rows from Excel or Google Sheets, sends each job advertisement to OpenAI with the master prompt and master LaTeX CV, then parses the structured response.

- `evaluator/openai_client.py` — `OpenAIJobEvaluator.evaluate()` handles the OpenAI call, retry logic, and a repair pass if a Suitable verdict lacks a CV.
- `evaluator/parsing.py` — extracts verdict, fit score, reasons, and the tailored LaTeX CV from response text. Also enforces protected sections (e.g. `Ausbildung`) from the master CV via `enforce_protected_cv_sections()`.
- `evaluator/models.py` — `JobEvaluation` dataclass with `value_for_column()` for writing back to spreadsheets.
- `evaluator/pdf_output.py` — compiles generated LaTeX CVs with `latexmk -xelatex` and uploads PDFs to Google Drive.
- `evaluator/service.py` — `run_evaluation()` is the main entry point; wires together all evaluator sub-components.

The prompt is assembled in `evaluator/parsing.py::build_full_prompt()`. The AI must output three machine-readable header lines (Verdict / Fit Score / Unsuitable Reasons) followed by optional reason text and, for Suitable jobs, the tailored LaTeX CV.

### Stage 3 — Export (`scraper/export_*`, `evaluator/storage.py`)

Both Excel (`scraper/export_excel.py`) and Google Sheets (`scraper/export_google_sheets.py`) exporters use the canonical column contract defined in `spreadsheet/schema.py`. Column changes start there and flow outward.

### Supporting Modules

| Module | Responsibility |
|---|---|
| `env.py` / `EnvSettings` | All env var access; reads `.env` as fallback. Use this everywhere instead of `os.environ` directly. |
| `paths.py` | All repository-relative path constants (`FILTERS_FILE`, `KEYWORDS_FILE`, `DEFAULT_CV_FILE`, etc.). |
| `config_files.py` | Loads `filters.json` and `keywords.txt` with typed helpers (`config_str`, `config_list`, `config_int`). |
| `dedupe/` | Pure deterministic duplicate matching and canonical merging. No I/O. |
| `pipeline/cli.py` | Runs scraper and evaluator as child subprocesses with timeout management. |
| `integrations/google/` | Google Sheets and Drive adapters. The `google_*.py` files in the package root are compatibility facades. |
| `core/logging.py` | `configure_cli_logging()` — used by all three CLI entry points. |
| `operations/reports.py` | Writes JSON run-summary reports from env paths. |

## Key Conventions

- **New providers**: implement `providers/<name>.py`, register in `providers/registry.py`. The scraper orchestration requires no other changes.
- **Column changes**: start in `spreadsheet/schema.py`, then update exporters, evaluator storage/parsing, tests, and docs.
- **All env access** goes through `EnvSettings`, not `os.environ` directly.
- **Service modules** orchestrate; **CLI modules** only parse args, configure logging, translate exceptions to exit codes, and write reports.
- **Compatibility facades** (`scraper/providers/linkedin.py`, root `google_*.py`, root scripts) re-export from the stable paths. New code imports from the stable paths, not the facades.
- Provider actor output normalization puts provider-specific metadata under `_jobfinder_<provider>_metadata` keys.

## Configuration Files

| File | Purpose |
|---|---|
| `configs/filters.json` | Per-provider search filters (location, experience levels, etc.) and global post-scrape filters |
| `configs/keywords.txt` | Job search keywords, one per line (injected from `JOB_KEYWORDS_TEXT` secret in CI) |
| `prompts/master_prompt.txt` | OpenAI evaluation prompt (injected from `MASTER_PROMPT_TEXT` secret in CI) |
| `cv/master_cv.tex` | Master LaTeX CV used as the base for tailored CVs (injected from `MASTER_CV_TEX` secret in CI) |
| `.env` | Local-only secrets and overrides; see `.env.example` for all supported variables |
