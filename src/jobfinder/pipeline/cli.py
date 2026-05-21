"""Command-line entry point for the one-step scrape/evaluate pipeline."""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys

from jobfinder.core.logging import configure_cli_logging
from jobfinder.env import EnvSettings, load_local_env
from jobfinder.operations.reports import write_report_from_env
from jobfinder.paths import ENV_FILE, PROJECT_ROOT
from jobfinder.pipeline.preflight import run_preflight
from jobfinder.scraper.settings import parse_apify_api_tokens

LOGGER = logging.getLogger("jobfinder.pipeline")

PIPELINE_MODE_SCRAPE_ONLY = "scrape_only"
PIPELINE_MODE_SCRAPE_AND_EVALUATE = "scrape_and_evaluate"
DEFAULT_PIPELINE_MODE = PIPELINE_MODE_SCRAPE_AND_EVALUATE
DEFAULT_STEP_TIMEOUT_SECONDS = 6 * 60 * 60
PIPELINE_MODE_ALIASES = {
    "scrape": PIPELINE_MODE_SCRAPE_ONLY,
    "scrape_only": PIPELINE_MODE_SCRAPE_ONLY,
    "scrape-only": PIPELINE_MODE_SCRAPE_ONLY,
    "scraper": PIPELINE_MODE_SCRAPE_ONLY,
    "scraper_only": PIPELINE_MODE_SCRAPE_ONLY,
    "scraper-only": PIPELINE_MODE_SCRAPE_ONLY,
    "both": PIPELINE_MODE_SCRAPE_AND_EVALUATE,
    "full": PIPELINE_MODE_SCRAPE_AND_EVALUATE,
    "scrape_and_evaluate": PIPELINE_MODE_SCRAPE_AND_EVALUATE,
    "scrape-and-evaluate": PIPELINE_MODE_SCRAPE_AND_EVALUATE,
    "scrape_evaluate": PIPELINE_MODE_SCRAPE_AND_EVALUATE,
    "scrape-evaluate": PIPELINE_MODE_SCRAPE_AND_EVALUATE,
}


def setting(local_env: dict[str, str], name: str, default: str = "") -> str:
    """Read a setting from environment variables with local env fallback."""
    return EnvSettings(local_env).get(name, default)


def parse_pipeline_mode(value: str | None) -> str:
    """Resolve user-facing pipeline mode aliases into canonical mode names."""
    normalized = (value or DEFAULT_PIPELINE_MODE).strip().lower()
    mode = PIPELINE_MODE_ALIASES.get(normalized)
    if mode:
        return mode

    allowed = ", ".join(sorted(PIPELINE_MODE_ALIASES))
    raise SystemExit(f"Unknown pipeline mode {value!r}. Use one of: {allowed}.")


def resolve_pipeline_mode(args: argparse.Namespace, local_env: dict[str, str]) -> str:
    """Resolve the selected mode from CLI args, env, or the default."""
    mode_value = args.mode or setting(local_env, "JOBFINDER_PIPELINE_MODE")
    return parse_pipeline_mode(mode_value)


def validate_required_settings(local_env: dict[str, str], pipeline_mode: str) -> None:
    """Ensure the selected pipeline mode has the secrets it needs."""
    apify_token = setting(local_env, "APIFY_API_TOKEN")

    missing = []
    try:
        apify_tokens = parse_apify_api_tokens(apify_token)
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc
    if not apify_tokens:
        missing.append("APIFY_API_TOKEN")

    if pipeline_mode == PIPELINE_MODE_SCRAPE_AND_EVALUATE:
        openai_key = setting(local_env, "OPENAI_API_KEY")
        if not openai_key:
            missing.append("OPENAI_API_KEY")

    if missing:
        names = ", ".join(missing)
        raise SystemExit(
            f"Missing required setting(s): {names}. Add them to {ENV_FILE.name}."
        )


def validate_python_dependencies(pipeline_mode: str) -> None:
    """Fail early when dependencies for the selected mode are missing."""
    if pipeline_mode == PIPELINE_MODE_SCRAPE_ONLY:
        return

    missing_packages = []
    try:
        import openai  # noqa: F401
    except ImportError:
        missing_packages.append("openai")

    if missing_packages:
        packages = ", ".join(missing_packages)
        raise SystemExit(
            f"Missing Python package(s): {packages}. Run this inside your Conda "
            "environment: python -m pip install -r requirements.txt"
        )


def parse_step_timeout_seconds(local_env: dict[str, str]) -> int | None:
    """Return the per-child pipeline timeout, or ``None`` when disabled."""
    raw_value = setting(
        local_env,
        "JOBFINDER_PIPELINE_STEP_TIMEOUT_SECONDS",
        str(DEFAULT_STEP_TIMEOUT_SECONDS),
    )
    try:
        seconds = int(raw_value)
    except ValueError as exc:
        raise SystemExit(
            "JOBFINDER_PIPELINE_STEP_TIMEOUT_SECONDS must be an integer number "
            "of seconds."
        ) from exc
    return seconds if seconds > 0 else None


def run_step(
    command: list[str],
    env: dict[str, str],
    label: str,
    *,
    timeout_seconds: int | None,
) -> None:
    """Run one pipeline child command and stop on non-zero exit."""
    LOGGER.info(label)
    try:
        result = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            env=env,
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        LOGGER.error(
            "%s timed out after %ss. Stopping the pipeline.",
            label,
            timeout_seconds,
        )
        raise SystemExit(124) from exc
    if result.returncode:
        raise SystemExit(result.returncode)


def build_arg_parser() -> argparse.ArgumentParser:
    """Build the pipeline CLI argument parser."""
    parser = argparse.ArgumentParser(
        description=(
            "Run JobFinder: scrape jobs to Google Sheets, optionally followed by "
            "OpenAI evaluation."
        )
    )
    parser.add_argument(
        "--mode",
        help=(
            "Use 'scrape_only' to stop after scraping, or "
            "'scrape_and_evaluate' to run both steps. Defaults to "
            "JOBFINDER_PIPELINE_MODE or scrape_and_evaluate."
        ),
    )
    parser.add_argument(
        "--preflight",
        action="store_true",
        help="Validate configuration and provider access without running the pipeline.",
    )
    return parser


def child_pythonpath() -> str:
    """Return a PYTHONPATH value that includes the local src directory."""
    src_path = str(PROJECT_ROOT / "src")
    existing = os.environ.get("PYTHONPATH")
    if existing:
        return os.pathsep.join([src_path, existing])
    return src_path


def main() -> int:
    """Run the scraper pipeline in the selected mode."""
    configure_cli_logging()
    args = build_arg_parser().parse_args()
    local_env = load_local_env()
    pipeline_mode = resolve_pipeline_mode(args, local_env)
    step_timeout_seconds = parse_step_timeout_seconds(local_env)
    validate_required_settings(local_env, pipeline_mode)
    validate_python_dependencies(pipeline_mode)

    if args.preflight:
        try:
            result = run_preflight(
                env=EnvSettings(local_env),
                should_evaluate=pipeline_mode == PIPELINE_MODE_SCRAPE_AND_EVALUATE,
            )
        except Exception as exc:
            LOGGER.error("Preflight failed: %s", exc)
            write_report_from_env(
                "JOBFINDER_PIPELINE_REPORT_FILE",
                "failed",
                "preflight",
                {"error": str(exc)},
            )
            return 1
        else:
            write_report_from_env(
                "JOBFINDER_PIPELINE_REPORT_FILE",
                "succeeded",
                "preflight",
                result,
            )
            LOGGER.info(
                "Preflight complete. sources=%s, output=%s, keywords=%s",
                result.source_mode,
                result.output_mode,
                result.keyword_count,
            )
            return 0

    env = os.environ.copy()
    for key, value in local_env.items():
        env.setdefault(key, value)
    env["PYTHONPATH"] = child_pythonpath()
    env["JOBSCRAPER_OUTPUT_MODE"] = "google_sheets"
    env["JOBFINDER_PIPELINE_MODE"] = pipeline_mode

    scrape_command = [sys.executable, "-m", "jobfinder.scraper.cli"]
    evaluate_command = [
        sys.executable,
        "-m",
        "jobfinder.evaluator.cli",
        "--source",
        "google_sheets",
        "--sheet",
        "latest",
    ]

    if pipeline_mode == PIPELINE_MODE_SCRAPE_ONLY:
        run_step(
            scrape_command,
            env,
            "Step 1/1: Scraping jobs to Google Sheets",
            timeout_seconds=step_timeout_seconds,
        )
        LOGGER.info("Scrape-only pipeline complete. Evaluation was skipped.")
        return 0

    run_step(
        scrape_command,
        env,
        "Step 1/2: Scraping jobs to Google Sheets",
        timeout_seconds=step_timeout_seconds,
    )
    run_step(
        evaluate_command,
        env,
        "Step 2/2: Evaluating jobs with OpenAI",
        timeout_seconds=step_timeout_seconds,
    )

    LOGGER.info(
        "Pipeline complete. Your Google Sheet now includes the AI evaluation columns."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
