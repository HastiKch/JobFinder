"""Command-line entry point for scraping and exporting jobs."""

from __future__ import annotations

import argparse
import logging
import sys

from jobfinder.core.logging import configure_cli_logging
from jobfinder.operations.reports import write_report_from_env
from jobfinder.scraper.export_google_sheets import GoogleSheetsExportError
from jobfinder.scraper.service import (
    ScraperServiceError,
    format_duration,
    parse_output_mode,
    run_scrape,
    sort_key,
)
from jobfinder.scraper.settings import (
    TOKEN_ENV_VAR,
    TOKEN_PLACEHOLDER,
    load_scraper_settings,
)

LOGGER = logging.getLogger("jobfinder.scraper")

__all__ = [
    "build_arg_parser",
    "configure_logging",
    "format_duration",
    "main",
    "parse_output_mode",
    "sort_key",
]


def build_arg_parser() -> argparse.ArgumentParser:
    """Build the scraper CLI argument parser."""
    return argparse.ArgumentParser(
        description=(
            "Scrape jobs through Apify and export them to Excel or Google Sheets."
        )
    )


def configure_logging() -> None:
    """Configure scraper logging for CLI output."""
    configure_cli_logging()


def main() -> int:
    """Run the scraper CLI using resolved local settings."""
    configure_logging()
    build_arg_parser().parse_args()
    try:
        settings = load_scraper_settings()
    except RuntimeError as exc:
        LOGGER.error("%s", exc)
        write_report_from_env(
            "JOBFINDER_SCRAPER_REPORT_FILE",
            "failed",
            "configuration",
            {"error": str(exc)},
        )
        return 1

    if not settings.apify_api_tokens:
        LOGGER.error(
            "Please set %s in %s or as an environment variable.",
            TOKEN_ENV_VAR,
            settings.token_file.name,
        )
        LOGGER.info("Example: %s=%s", TOKEN_ENV_VAR, TOKEN_PLACEHOLDER)
        write_report_from_env(
            "JOBFINDER_SCRAPER_REPORT_FILE",
            "failed",
            "configuration",
            {"error": f"Missing required setting: {TOKEN_ENV_VAR}"},
        )
        return 1

    try:
        result = run_scrape(settings)
    except (GoogleSheetsExportError, ScraperServiceError) as exc:
        LOGGER.error("%s", exc)
        write_report_from_env(
            "JOBFINDER_SCRAPER_REPORT_FILE",
            "failed",
            "runtime",
            {"error": str(exc)},
        )
        return 1
    write_report_from_env(
        "JOBFINDER_SCRAPER_REPORT_FILE", "succeeded", "scrape", result
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
