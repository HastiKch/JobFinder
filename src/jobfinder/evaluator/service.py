"""Application service for running evaluator workflows outside the CLI."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jobfinder.env import EnvSettings
from jobfinder.evaluator.models import (
    DEFAULT_MODEL,
    EvaluationError,
    JobEvaluation,
)
from jobfinder.evaluator.openai_client import OpenAIJobEvaluator, evaluate_records
from jobfinder.evaluator.parsing import (
    ensure_output_columns,
    extract_job_records,
    read_text_asset,
)
from jobfinder.evaluator.pdf_output import (
    DEFAULT_CV_MAX_PAGES,
    DEFAULT_CV_MAX_SHORTEN_ATTEMPTS,
    DEFAULT_CV_PDF_APPLICANT_NAME,
    DEFAULT_DRIVE_PARENT_FOLDER_ID,
    generate_cv_pdf_outputs,
)
from jobfinder.evaluator.storage import (
    build_evaluator_google_sheets_service,
    read_excel_input,
    read_google_input,
    read_google_spreadsheet_id,
    write_excel_output,
    write_google_output,
)
from jobfinder.paths import (
    DEFAULT_CV_FILE,
    DEFAULT_CV_PHOTO_FILE,
    DEFAULT_EXCEL_FILE,
    DEFAULT_MASTER_PROMPT_FILE,
)

LOGGER = logging.getLogger("job_fit_evaluator")

SOURCE_ALIASES = {
    "excel": "excel",
    "xlsx": "excel",
    "local": "excel",
    "google": "google_sheets",
    "google_sheets": "google_sheets",
    "sheets": "google_sheets",
    "drive": "google_sheets",
}

UNSUITABLE_ROW_POLICY_SINGLE_LABEL_ONLY = "single_label_only"
UNSUITABLE_ROW_POLICY_KEEP_ALL = "keep_all"
MAX_EVALUATOR_CONCURRENCY = 32
UNSUITABLE_ROW_POLICY_ALIASES = {
    "single_label_only": UNSUITABLE_ROW_POLICY_SINGLE_LABEL_ONLY,
    "single-label-only": UNSUITABLE_ROW_POLICY_SINGLE_LABEL_ONLY,
    "filter": UNSUITABLE_ROW_POLICY_SINGLE_LABEL_ONLY,
    "filtered": UNSUITABLE_ROW_POLICY_SINGLE_LABEL_ONLY,
    "hide_multi_label": UNSUITABLE_ROW_POLICY_SINGLE_LABEL_ONLY,
    "hide-multi-label": UNSUITABLE_ROW_POLICY_SINGLE_LABEL_ONLY,
    "remove_multi_label": UNSUITABLE_ROW_POLICY_SINGLE_LABEL_ONLY,
    "remove-multi-label": UNSUITABLE_ROW_POLICY_SINGLE_LABEL_ONLY,
    "keep_all": UNSUITABLE_ROW_POLICY_KEEP_ALL,
    "keep-all": UNSUITABLE_ROW_POLICY_KEEP_ALL,
    "all": UNSUITABLE_ROW_POLICY_KEEP_ALL,
    "save_all": UNSUITABLE_ROW_POLICY_KEEP_ALL,
    "save-all": UNSUITABLE_ROW_POLICY_KEEP_ALL,
}


@dataclass(frozen=True)
class EvaluationOptions:
    """Resolved evaluator settings for one workflow run."""

    env: EnvSettings
    source_arg: str | None
    sheet: str
    google_sheet_id_arg: str
    excel_file: Path
    master_prompt_file: Path
    cv_file: Path
    model: str
    batch_size: int
    concurrency: int
    retries: int
    retry_base_delay: float
    retry_max_delay: float
    timeout: float
    max_output_tokens: int
    cv_pdf_output: bool
    cv_photo_file: Path
    cv_pdf_compile_timeout: int
    cv_drive_folder_id: str
    cv_pdf_applicant_name: str
    large_queue_threshold: int
    large_queue_sleep_ms: int
    save_batch_size: int
    unsuitable_row_policy: str
    cv_max_pages: int
    cv_max_shorten_attempts: int


@dataclass(frozen=True)
class EvaluationSummary:
    """Summary of a completed evaluator run."""

    source: str
    sheet_name: str
    queued_count: int
    skipped_existing_count: int
    saved_count: int
    suitable_count: int
    not_suitable_count: int
    error_count: int
    cv_pdf_count: int = 0
    cv_pdf_error_count: int = 0
    cv_pdf_drive_folder: str = ""


def options_from_env(
    env: EnvSettings,
    *,
    source_arg: str | None,
    sheet: str,
    google_sheet_id_arg: str,
) -> EvaluationOptions:
    """Build evaluator options from CLI args plus environment settings."""
    cv_pdf_output = env.get_bool("JOB_EVAL_CV_PDF_OUTPUT", True)
    cv_drive_folder_id = env.get(
        "JOB_EVAL_CV_DRIVE_FOLDER_ID",
        DEFAULT_DRIVE_PARENT_FOLDER_ID,
    )
    if cv_pdf_output and not cv_drive_folder_id.strip():
        raise EvaluationError(
            "Missing JOB_EVAL_CV_DRIVE_FOLDER_ID. Set it to the ID of the Google "
            "Drive folder where generated CV PDFs should be uploaded, or set "
            "JOB_EVAL_CV_PDF_OUTPUT=false."
        )

    return EvaluationOptions(
        env=env,
        source_arg=source_arg,
        sheet=sheet,
        google_sheet_id_arg=google_sheet_id_arg,
        excel_file=Path(env.get("JOB_EVAL_EXCEL_FILE", str(DEFAULT_EXCEL_FILE))),
        master_prompt_file=Path(
            env.get("JOB_EVAL_MASTER_PROMPT_FILE", str(DEFAULT_MASTER_PROMPT_FILE))
        ),
        cv_file=Path(env.get("JOB_EVAL_CV_FILE", str(DEFAULT_CV_FILE))),
        model=env.get("JOB_EVAL_OPENAI_MODEL", DEFAULT_MODEL),
        batch_size=env.get_int("JOB_EVAL_BATCH_SIZE", 40),
        concurrency=env.get_int("JOB_EVAL_CONCURRENCY", 8),
        retries=env.get_int("JOB_EVAL_OPENAI_RETRIES", 3),
        retry_base_delay=env.get_float("JOB_EVAL_RETRY_BASE_DELAY", 2.0),
        retry_max_delay=env.get_float("JOB_EVAL_RETRY_MAX_DELAY", 60.0),
        timeout=env.get_float("JOB_EVAL_OPENAI_TIMEOUT", 120.0),
        max_output_tokens=env.get_int("JOB_EVAL_MAX_OUTPUT_TOKENS", 9000),
        cv_pdf_output=cv_pdf_output,
        cv_photo_file=Path(
            env.get("JOB_EVAL_CV_PHOTO_FILE", str(DEFAULT_CV_PHOTO_FILE))
        ),
        cv_pdf_compile_timeout=env.get_int("JOB_EVAL_CV_PDF_TIMEOUT", 120),
        cv_drive_folder_id=cv_drive_folder_id,
        cv_pdf_applicant_name=env.get(
            "JOB_EVAL_CV_PDF_APPLICANT_NAME",
            DEFAULT_CV_PDF_APPLICANT_NAME,
        ),
        large_queue_threshold=env.get_int("JOB_EVAL_LARGE_QUEUE_THRESHOLD", 200),
        large_queue_sleep_ms=env.get_int("JOB_EVAL_LARGE_QUEUE_SLEEP_MS", 2000),
        save_batch_size=max(1, env.get_int("JOB_EVAL_SAVE_BATCH_SIZE", 1)),
        unsuitable_row_policy=parse_unsuitable_row_policy(
            env.get("JOB_EVAL_UNSUITABLE_ROW_POLICY")
        ),
        cv_max_pages=max(1, env.get_int("JOB_EVAL_CV_MAX_PAGES", DEFAULT_CV_MAX_PAGES)),
        cv_max_shorten_attempts=max(
            0,
            env.get_int(
                "JOB_EVAL_CV_MAX_SHORTEN_ATTEMPTS", DEFAULT_CV_MAX_SHORTEN_ATTEMPTS
            ),
        ),
    )


def parse_unsuitable_row_policy(value: str | None) -> str:
    """Resolve how final output should handle not-suitable rows."""
    normalized = (value or UNSUITABLE_ROW_POLICY_SINGLE_LABEL_ONLY).strip().casefold()
    policy = UNSUITABLE_ROW_POLICY_ALIASES.get(normalized)
    if policy:
        return policy

    allowed = ", ".join(
        [UNSUITABLE_ROW_POLICY_SINGLE_LABEL_ONLY, UNSUITABLE_ROW_POLICY_KEEP_ALL]
    )
    raise EvaluationError(
        f"Unsupported JOB_EVAL_UNSUITABLE_ROW_POLICY {value!r}. Use one of: {allowed}."
    )


def should_remove_rejected_rows(policy: str) -> bool:
    """Return true when final output should keep only one-label rejections."""
    return policy == UNSUITABLE_ROW_POLICY_SINGLE_LABEL_ONLY


def parse_source(value: str | None, google_sheet_id: str, env: EnvSettings) -> str:
    """Resolve the evaluator source from CLI, env, or available spreadsheet ID."""
    selected = (value or env.get("JOB_EVAL_SOURCE")).strip().casefold()
    if selected:
        if selected not in SOURCE_ALIASES:
            raise EvaluationError("Unsupported source. Use 'excel' or 'google_sheets'.")
        return SOURCE_ALIASES[selected]
    if google_sheet_id:
        return "google_sheets"
    return "excel"


def validate_runtime_settings(options: EvaluationOptions) -> None:
    """Validate evaluator runtime settings before doing any I/O."""
    if options.batch_size < 1:
        raise EvaluationError("JOB_EVAL_BATCH_SIZE must be 1 or greater.")
    if options.concurrency < 1:
        raise EvaluationError("JOB_EVAL_CONCURRENCY must be 1 or greater.")
    if options.concurrency > MAX_EVALUATOR_CONCURRENCY:
        raise EvaluationError(
            f"JOB_EVAL_CONCURRENCY must be {MAX_EVALUATOR_CONCURRENCY} or less "
            "to avoid exhausting API and local worker resources."
        )
    if options.retries < 0:
        raise EvaluationError("JOB_EVAL_OPENAI_RETRIES must be 0 or greater.")
    if options.retry_base_delay < 0:
        raise EvaluationError("JOB_EVAL_RETRY_BASE_DELAY must be 0 or greater.")
    if options.retry_max_delay < 0:
        raise EvaluationError("JOB_EVAL_RETRY_MAX_DELAY must be 0 or greater.")
    if options.timeout <= 0:
        raise EvaluationError("JOB_EVAL_OPENAI_TIMEOUT must be greater than 0.")
    if options.max_output_tokens < 500:
        raise EvaluationError(
            "JOB_EVAL_MAX_OUTPUT_TOKENS is too small for reliable parsing."
        )
    if options.cv_pdf_compile_timeout < 1:
        raise EvaluationError("JOB_EVAL_CV_PDF_TIMEOUT must be 1 or greater.")
    if options.cv_max_pages < 1:
        raise EvaluationError("JOB_EVAL_CV_MAX_PAGES must be 1 or greater.")
    if options.cv_max_shorten_attempts < 0:
        raise EvaluationError("JOB_EVAL_CV_MAX_SHORTEN_ATTEMPTS must be 0 or greater.")
    if options.large_queue_threshold < 0:
        raise EvaluationError("JOB_EVAL_LARGE_QUEUE_THRESHOLD must be 0 or greater.")
    if options.large_queue_sleep_ms < 0:
        raise EvaluationError("JOB_EVAL_LARGE_QUEUE_SLEEP_MS must be 0 or greater.")


def resolve_cv_photo_file(configured_path: Path) -> Path | None:
    """Return an existing CV photo path, accepting common image extensions."""
    if configured_path.exists():
        return configured_path

    candidates = [
        configured_path.with_suffix(suffix)
        for suffix in (".jpg", ".jpeg", ".png", ".webp")
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def load_input_rows(
    sheet: str,
    source: str,
    spreadsheet_id: str,
    excel_file: Path,
) -> tuple[Any, Any, Any, str, list[str], list[list[Any]]]:
    """Read evaluator input rows from Excel or Google Sheets."""
    google_service = None
    if source == "excel":
        workbook, worksheet, sheet_name, headers, rows = read_excel_input(
            excel_file,
            sheet,
        )
    else:
        if not spreadsheet_id:
            raise EvaluationError(
                "Google Sheets source selected but no spreadsheet ID was provided. "
                "Set --google-sheet-id, GOOGLE_SPREADSHEET_ID, or "
                "google_spreadsheet_id.txt."
            )
        google_service = build_evaluator_google_sheets_service()
        sheet_name, headers, rows = read_google_input(
            google_service,
            spreadsheet_id,
            sheet,
        )
        workbook = worksheet = None

    return google_service, workbook, worksheet, sheet_name, headers, rows


def write_outputs(
    excel_file: Path,
    source: str,
    spreadsheet_id: str,
    google_service: Any,
    workbook: Any,
    worksheet: Any,
    sheet_name: str,
    headers: list[str],
    header_map: dict[str, int],
    evaluations: dict[int, JobEvaluation],
    *,
    cleanup_columns: bool = True,
    remove_rejected_rows: bool = True,
    remove_tailored_cv: bool = False,
) -> None:
    """Write evaluator headers and result values back to the selected source."""
    if source == "excel":
        write_excel_output(
            workbook,
            worksheet,
            excel_file,
            headers,
            header_map,
            evaluations,
            cleanup_columns=cleanup_columns,
            remove_rejected_rows=remove_rejected_rows,
            remove_tailored_cv=remove_tailored_cv,
        )
    else:
        write_google_output(
            google_service,
            spreadsheet_id,
            sheet_name,
            headers,
            header_map,
            evaluations,
            cleanup_columns=cleanup_columns,
            remove_rejected_rows=remove_rejected_rows,
            remove_tailored_cv=remove_tailored_cv,
        )


def run_evaluation(options: EvaluationOptions) -> EvaluationSummary:
    """Run the evaluator workflow using resolved options."""
    validate_runtime_settings(options)

    master_prompt = read_text_asset(options.master_prompt_file, "master prompt")
    latex_cv = read_text_asset(options.cv_file, "LaTeX CV")
    spreadsheet_id = read_google_spreadsheet_id(options.google_sheet_id_arg)
    source = parse_source(options.source_arg, spreadsheet_id, options.env)

    LOGGER.info("Loading %s input ...", source)
    google_service, workbook, worksheet, sheet_name, headers, rows = load_input_rows(
        options.sheet,
        source,
        spreadsheet_id,
        options.excel_file,
    )

    headers, header_map = ensure_output_columns(headers)
    records, skipped_existing = extract_job_records(headers, rows)
    remove_rejected_rows = should_remove_rejected_rows(options.unsuitable_row_policy)

    LOGGER.info("Sheet: %s", sheet_name)
    LOGGER.info("Rows queued: %s", len(records))
    LOGGER.info("Unsuitable row policy: %s", options.unsuitable_row_policy)
    if skipped_existing:
        LOGGER.info(
            "Rows skipped because AI Verdict already exists: %s",
            skipped_existing,
        )

    if not records:
        LOGGER.info("No rows need evaluation. Writing any missing AI headers only.")
        write_outputs(
            options.excel_file,
            source,
            spreadsheet_id,
            google_service,
            workbook,
            worksheet,
            sheet_name,
            headers,
            header_map,
            {},
            remove_rejected_rows=remove_rejected_rows,
            remove_tailored_cv=options.cv_pdf_output,
        )
        return EvaluationSummary(
            source=source,
            sheet_name=sheet_name,
            queued_count=0,
            skipped_existing_count=skipped_existing,
            saved_count=0,
            suitable_count=0,
            not_suitable_count=0,
            error_count=0,
        )

    api_key = options.env.get("OPENAI_API_KEY")
    if not api_key:
        raise EvaluationError(
            "Missing OPENAI_API_KEY. Add it to your environment or local .env file."
        )

    evaluator = OpenAIJobEvaluator(
        model=options.model,
        api_key=api_key,
        timeout=options.timeout,
        retries=options.retries,
        base_delay=options.retry_base_delay,
        max_delay=options.retry_max_delay,
        max_output_tokens=options.max_output_tokens,
    )

    pending_evaluations: dict[int, JobEvaluation] = {}

    def flush_pending(*, cleanup_columns: bool = False) -> None:
        if not pending_evaluations:
            return
        LOGGER.info("Saving %s pending evaluation(s) ...", len(pending_evaluations))
        write_outputs(
            options.excel_file,
            source,
            spreadsheet_id,
            google_service,
            workbook,
            worksheet,
            sheet_name,
            headers,
            header_map,
            dict(pending_evaluations),
            cleanup_columns=cleanup_columns,
            remove_rejected_rows=remove_rejected_rows,
        )
        pending_evaluations.clear()

    def save_evaluation(evaluation: JobEvaluation) -> None:
        pending_evaluations[evaluation.row_number] = evaluation
        if len(pending_evaluations) >= options.save_batch_size:
            flush_pending()

    try:
        evaluations = evaluate_records(
            records,
            evaluator=evaluator,
            master_prompt=master_prompt,
            latex_cv=latex_cv,
            concurrency=options.concurrency,
            batch_size=options.batch_size,
            large_queue_threshold=options.large_queue_threshold,
            large_queue_sleep_ms=options.large_queue_sleep_ms,
            on_evaluation=save_evaluation,
        )
    finally:
        flush_pending()

    LOGGER.info(
        "Finalizing output columns after %s saved evaluation(s) ...",
        len(evaluations),
    )
    cv_pdf_count = 0
    cv_pdf_error_count = 0
    cv_pdf_drive_folder = ""
    if options.cv_pdf_output:
        LOGGER.info("Compiling generated CVs to PDF and uploading to Google Drive ...")
        if options.cv_max_pages > 0:
            LOGGER.info(
                "CV page limit: %s page(s) max (up to %s AI shortening attempt(s)).",
                options.cv_max_pages,
                options.cv_max_shorten_attempts,
            )
        photo_path = resolve_cv_photo_file(options.cv_photo_file)

        def _shorten_cv(latex_code: str, page_count: int) -> str:
            return evaluator.shorten_latex(
                latex_code, page_count, options.cv_max_pages
            )

        pdf_result = generate_cv_pdf_outputs(
            records,
            evaluations,
            photo_path=photo_path,
            parent_folder_id=options.cv_drive_folder_id,
            applicant_name=options.cv_pdf_applicant_name,
            timeout_seconds=options.cv_pdf_compile_timeout,
            max_page_limit=options.cv_max_pages,
            shorten_latex=_shorten_cv if options.cv_max_shorten_attempts > 0 else None,
            max_shorten_attempts=options.cv_max_shorten_attempts,
        )
        cv_pdf_count = pdf_result.success_count
        cv_pdf_error_count = pdf_result.error_count
        cv_pdf_drive_folder = pdf_result.run_folder_link
        for row_number, value in pdf_result.outputs.items():
            evaluations[row_number].cv_pdf = value
        pdf_updates = {
            row_number: evaluation
            for row_number, evaluation in evaluations.items()
            if evaluation.cv_pdf
        }
        if pdf_updates:
            LOGGER.info(
                "Saving %s CV PDF link/error update(s) ...",
                len(pdf_updates),
            )
            write_outputs(
                options.excel_file,
                source,
                spreadsheet_id,
                google_service,
                workbook,
                worksheet,
                sheet_name,
                headers,
                header_map,
                pdf_updates,
                cleanup_columns=False,
                remove_rejected_rows=remove_rejected_rows,
            )
        if pdf_result.run_folder_name:
            LOGGER.info(
                "CV PDFs saved: %s uploaded, %s error(s), Drive folder: %s",
                cv_pdf_count,
                cv_pdf_error_count,
                pdf_result.run_folder_name,
            )
    else:
        LOGGER.info("CV PDF output is disabled by JOB_EVAL_CV_PDF_OUTPUT.")

    write_outputs(
        options.excel_file,
        source,
        spreadsheet_id,
        google_service,
        workbook,
        worksheet,
        sheet_name,
        headers,
        header_map,
        {},
        cleanup_columns=True,
        remove_rejected_rows=remove_rejected_rows,
        remove_tailored_cv=options.cv_pdf_output,
    )
    if source == "excel":
        LOGGER.info(
            "Saved Excel workbook: %s (sheet: %s)", options.excel_file, sheet_name
        )
    else:
        LOGGER.info(
            "Updated Google Sheet ID %s (tab: %s)",
            spreadsheet_id,
            sheet_name,
        )

    suitable_count = sum(
        1 for evaluation in evaluations.values() if evaluation.verdict == "Suitable"
    )
    not_suitable_count = sum(
        1 for evaluation in evaluations.values() if evaluation.verdict == "Not Suitable"
    )
    error_count = sum(
        1 for evaluation in evaluations.values() if evaluation.verdict == "Error"
    )
    LOGGER.info(
        "Done. Suitable=%s, Not Suitable=%s, Error=%s, CV PDFs=%s, CV PDF errors=%s",
        suitable_count,
        not_suitable_count,
        error_count,
        cv_pdf_count,
        cv_pdf_error_count,
    )

    return EvaluationSummary(
        source=source,
        sheet_name=sheet_name,
        queued_count=len(records),
        skipped_existing_count=skipped_existing,
        saved_count=len(evaluations),
        suitable_count=suitable_count,
        not_suitable_count=not_suitable_count,
        error_count=error_count,
        cv_pdf_count=cv_pdf_count,
        cv_pdf_error_count=cv_pdf_error_count,
        cv_pdf_drive_folder=cv_pdf_drive_folder,
    )
