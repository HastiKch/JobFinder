"""Preflight validation for scheduled pipeline runs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from jobfinder.env import EnvSettings
from jobfinder.evaluator.parsing import read_text_asset
from jobfinder.evaluator.storage import read_google_spreadsheet_id
from jobfinder.paths import DEFAULT_CV_FILE, DEFAULT_MASTER_PROMPT_FILE
from jobfinder.scraper.export_google_sheets import build_scraper_google_sheets_service
from jobfinder.scraper.run_history import load_google_spreadsheet_context
from jobfinder.scraper.settings import ScraperSettings, load_scraper_settings


@dataclass(frozen=True)
class PreflightResult:
    """Summary of pipeline readiness checks."""

    source_mode: str
    output_mode: str
    keyword_count: int
    google_sheets_ready: bool
    evaluation_inputs_ready: bool


def run_preflight(env: EnvSettings, *, should_evaluate: bool) -> PreflightResult:
    """Validate local config, dependencies, and Google Sheets access."""
    settings = load_scraper_settings(env)
    google_sheets_ready = validate_google_sheets(settings)

    evaluation_inputs_ready = False
    if should_evaluate:
        master_prompt_file = Path(
            env.get("JOB_EVAL_MASTER_PROMPT_FILE", str(DEFAULT_MASTER_PROMPT_FILE))
        )
        cv_file = Path(env.get("JOB_EVAL_CV_FILE", str(DEFAULT_CV_FILE)))
        read_text_asset(master_prompt_file, "master prompt")
        read_text_asset(cv_file, "LaTeX CV")
        if not env.get("OPENAI_API_KEY"):
            raise RuntimeError("Missing OPENAI_API_KEY.")
        if env.get_bool("JOB_EVAL_CV_PDF_OUTPUT", True) and not env.get(
            "JOB_EVAL_CV_DRIVE_FOLDER_ID"
        ):
            raise RuntimeError(
                "Missing JOB_EVAL_CV_DRIVE_FOLDER_ID. Set it to the ID of the "
                "Google Drive folder where generated CV PDFs should be uploaded, "
                "or set JOB_EVAL_CV_PDF_OUTPUT=false."
            )
        read_google_spreadsheet_id(env.get("JOB_EVAL_GOOGLE_SPREADSHEET_ID"))
        evaluation_inputs_ready = True

    return PreflightResult(
        source_mode=settings.source_mode,
        output_mode=settings.output_mode,
        keyword_count=len(settings.keywords),
        google_sheets_ready=google_sheets_ready,
        evaluation_inputs_ready=evaluation_inputs_ready,
    )


def validate_google_sheets(settings: ScraperSettings) -> bool:
    """Validate Google Sheets credentials and spreadsheet access."""
    service = build_scraper_google_sheets_service()
    load_google_spreadsheet_context(settings, service, seed_seen_jobs_index=False)
    return True
