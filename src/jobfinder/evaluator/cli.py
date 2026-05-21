"""Command-line entry point for evaluating scraped jobs with OpenAI."""

from __future__ import annotations

import argparse
import logging
import sys

from jobfinder.core.logging import configure_cli_logging
from jobfinder.env import EnvSettings
from jobfinder.evaluator.models import (
    EvaluationError,
    GoogleSheetsError,
)
from jobfinder.evaluator.service import (
    SOURCE_ALIASES,
    load_input_rows,
    options_from_env,
    parse_source,
    run_evaluation,
    validate_runtime_settings,
    write_outputs,
)
from jobfinder.operations.reports import write_report_from_env

LOGGER = logging.getLogger("job_fit_evaluator")

__all__ = [
    "SOURCE_ALIASES",
    "build_arg_parser",
    "configure_logging",
    "load_input_rows",
    "main",
    "parse_source",
    "validate_runtime_settings",
    "write_outputs",
]


def build_arg_parser(env: EnvSettings | None = None) -> argparse.ArgumentParser:
    """Build the evaluator CLI argument parser."""
    env = env or EnvSettings(logger=LOGGER)
    parser = argparse.ArgumentParser(
        description="Evaluate job postings with OpenAI and update the same sheet."
    )
    parser.add_argument(
        "--source",
        choices=sorted(SOURCE_ALIASES),
        default=None,
        help=(
            "Where to read jobs from. Defaults to Google Sheets when a spreadsheet "
            "ID is configured, otherwise Excel."
        ),
    )
    parser.add_argument(
        "--sheet",
        default=env.get("JOB_EVAL_SHEET", "latest"),
        help="Worksheet or Google Sheet tab to evaluate. Defaults to the latest tab.",
    )
    parser.add_argument(
        "--google-sheet-id",
        default=env.get("JOB_EVAL_GOOGLE_SPREADSHEET_ID"),
        help=(
            "Google spreadsheet ID for this run. Defaults to "
            "JOB_EVAL_GOOGLE_SPREADSHEET_ID, GOOGLE_SPREADSHEET_ID, or "
            "google_spreadsheet_id.txt."
        ),
    )
    return parser


def configure_logging() -> None:
    """Configure evaluator logging for CLI output."""
    configure_cli_logging()


def main() -> int:
    """Run the evaluator CLI."""
    configure_logging()
    env = EnvSettings(logger=LOGGER)
    args = build_arg_parser(env).parse_args()

    try:
        options = options_from_env(
            env,
            source_arg=args.source,
            sheet=args.sheet,
            google_sheet_id_arg=args.google_sheet_id,
        )
        summary = run_evaluation(options)
        write_report_from_env(
            "JOBFINDER_EVALUATOR_REPORT_FILE",
            "succeeded",
            "evaluation",
            summary,
        )
        return 0

    except (EvaluationError, GoogleSheetsError) as exc:
        LOGGER.error("%s", exc)
        write_report_from_env(
            "JOBFINDER_EVALUATOR_REPORT_FILE",
            "failed",
            "runtime",
            {"error": str(exc)},
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
