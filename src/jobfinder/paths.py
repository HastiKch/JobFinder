"""Project path constants used by the JobFinder package."""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
"""Absolute path to the repository root."""

CONFIG_DIR = PROJECT_ROOT / "configs"
"""Directory containing user-editable scraper configuration files."""

ENV_FILE = PROJECT_ROOT / ".env"
"""Local environment file loaded after real environment variables."""

DEFAULT_EXCEL_FILE = PROJECT_ROOT / "jobs.xlsx"
"""Default local Excel workbook output path."""

DEFAULT_MASTER_PROMPT_FILE = PROJECT_ROOT / "prompts" / "master_prompt.txt"
"""Default master prompt used by the job-fit evaluator."""

DEFAULT_CV_FILE = PROJECT_ROOT / "cv" / "master_cv.tex"
"""Default LaTeX CV injected into evaluator prompts."""

DEFAULT_CV_PHOTO_FILE = PROJECT_ROOT / "cv" / "photo.jpg"
"""Default optional CV photo copied into LaTeX compilation directories."""

GOOGLE_SHARED_SERVICE_ACCOUNT_FILE = PROJECT_ROOT / "google_service_account.json"
"""Shared Google service-account credentials file used for Sheets and Drive."""

GOOGLE_SERVICE_ACCOUNT_FILE = GOOGLE_SHARED_SERVICE_ACCOUNT_FILE
"""Backward-compatible alias for the shared Google service-account file."""

GOOGLE_SPREADSHEET_ID_FILE = PROJECT_ROOT / "google_spreadsheet_id.txt"
"""Google spreadsheet ID cache file."""

KEYWORDS_FILE = CONFIG_DIR / "keywords.txt"
"""Default keyword configuration file."""

FILTERS_FILE = CONFIG_DIR / "filters.json"
"""Default filter configuration file."""
