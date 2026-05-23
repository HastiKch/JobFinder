"""PDF generation and Google Drive output for tailored CVs."""

from __future__ import annotations

import logging
import re
import tempfile
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from jobfinder.evaluator.latex import LatexCompilationResult, compile_latex_to_pdf
from jobfinder.evaluator.models import EvaluationError, JobEvaluation, JobRecord
from jobfinder.evaluator.parsing import looks_like_latex_cv
from jobfinder.integrations.google.drive import (
    DriveFolder,
    build_google_drive_service,
    create_drive_folder,
    get_drive_folder,
    upload_pdf_to_drive,
)

LOGGER = logging.getLogger("job_fit_evaluator")

DEFAULT_DRIVE_PARENT_FOLDER_ID = ""
DEFAULT_CV_PDF_APPLICANT_NAME = "Applicant"
DEFAULT_CV_MAX_PAGES = 2
DEFAULT_CV_MAX_SHORTEN_ATTEMPTS = 2
ERROR_CELL_LIMIT = 4000
INVALID_FILENAME_CHARS_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')
SAFE_FILENAME_TOKEN_RE = re.compile(r"[^A-Za-z0-9]+")
COMPANY_LEGAL_SUFFIXES = {
    "ag",
    "co",
    "company",
    "corp",
    "corporation",
    "gmbh",
    "group",
    "inc",
    "kg",
    "limited",
    "llc",
    "ltd",
    "mbh",
    "se",
    "ug",
}


@dataclass(frozen=True)
class CvPdfCandidate:
    """One generated LaTeX CV selected for PDF output."""

    cv_id: int
    row_number: int
    display_name: str
    latex: str
    filename: str


@dataclass(frozen=True)
class CvPdfRunResult:
    """Summary of PDF compilation and Drive upload work for one evaluator run."""

    outputs: dict[int, str]
    success_count: int
    error_count: int
    run_folder_name: str = ""
    run_folder_link: str = ""


CompileLatexFunc = Callable[..., LatexCompilationResult]
UploadPdfFunc = Callable[..., Any]
# (current_latex, current_page_count) -> shortened_latex — raises on failure
ShortenLatexFunc = Callable[[str, int], str]


def build_evaluator_google_drive_service() -> Any:
    """Build a Google Drive service for evaluator PDF uploads."""
    return build_google_drive_service(error_cls=EvaluationError)


def sanitize_filename(value: str, *, max_length: int = 120) -> str:
    """Return a filesystem and Drive-safe filename stem."""
    normalized = unicodedata.normalize("NFKC", str(value or "")).strip()
    sanitized = INVALID_FILENAME_CHARS_RE.sub(" ", normalized)
    sanitized = re.sub(r"\s+", " ", sanitized)
    sanitized = sanitized.strip(" ._-")
    if not sanitized:
        sanitized = "CV"
    if len(sanitized) > max_length:
        sanitized = sanitized[:max_length].rstrip(" ._-") or "CV"
    return sanitized


def safe_filename_token(
    value: str,
    *,
    max_words: int | None = None,
    drop_words: set[str] | None = None,
    fallback: str = "CV",
) -> str:
    """Return an upload-safe ASCII token using only letters, numbers, underscores."""
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    ascii_text = "".join(char for char in normalized if not unicodedata.combining(char))
    ascii_text = ascii_text.encode("ascii", "ignore").decode("ascii")
    words = [
        word
        for word in SAFE_FILENAME_TOKEN_RE.split(ascii_text)
        if word and word.casefold() not in (drop_words or set())
    ]
    if max_words is not None:
        words = words[:max_words]
    return "_".join(words) or fallback


def display_name_parts(display_name: str) -> tuple[str, str]:
    """Split a row display name into simple role and company labels."""
    parts = [part.strip() for part in str(display_name or "").split(" / ", 1)]
    role = parts[0] if parts and parts[0] else ""
    company = parts[1] if len(parts) > 1 else ""
    return role, company


def cv_pdf_filename(
    cv_id: int,
    display_name: str = "",
    applicant_name: str = DEFAULT_CV_PDF_APPLICANT_NAME,
) -> str:
    """Build a PDF filename from row ID, applicant, role, and company."""
    role, company = display_name_parts(display_name)
    parts = [
        str(cv_id),
        "CV",
        safe_filename_token(applicant_name, max_words=4),
    ]
    if role:
        role_token = safe_filename_token(role, max_words=5, fallback="")
        if role_token:
            parts.append(role_token)
    if company:
        company_token = safe_filename_token(
            company,
            max_words=4,
            drop_words=COMPANY_LEGAL_SUFFIXES,
            fallback="",
        )
        if company_token:
            parts.append(company_token)
    stem = "_".join(part for part in parts if part)
    if len(stem) > 156:
        stem = stem[:156].rstrip("_") or f"{cv_id}_CV"
    return f"{stem}.pdf"


def assign_cv_ids(
    records: Sequence[JobRecord],
    evaluations: Mapping[int, JobEvaluation],
    *,
    applicant_name: str = DEFAULT_CV_PDF_APPLICANT_NAME,
) -> list[CvPdfCandidate]:
    """Assign stable row-number IDs to evaluations with generated LaTeX CVs."""
    candidates: list[CvPdfCandidate] = []
    for record in records:
        evaluation = evaluations.get(record.row_number)
        if (
            evaluation is None
            or evaluation.verdict != "Suitable"
            or not looks_like_latex_cv(evaluation.tailored_cv)
        ):
            continue
        cv_id = record.row_number
        candidates.append(
            CvPdfCandidate(
                cv_id=cv_id,
                row_number=record.row_number,
                display_name=record.display_name,
                latex=evaluation.tailored_cv,
                filename=cv_pdf_filename(cv_id, record.display_name, applicant_name),
            )
        )
    return candidates


def drive_run_folder_name(now: datetime | None = None) -> str:
    """Return the timestamped Drive run folder name."""
    current = now or datetime.now().astimezone()
    return current.strftime("%Y-%m-%d_%H-%M-%S")


def error_cell(prefix: str, details: str) -> str:
    """Format a bounded error string for the PDF spreadsheet column."""
    message = f"{prefix}: {details.strip()}" if details.strip() else prefix
    if len(message) <= ERROR_CELL_LIMIT:
        return message
    return message[: ERROR_CELL_LIMIT - 25].rstrip() + " ... [truncated]"


def prepare_drive_run_folder(
    service: Any,
    *,
    parent_folder_id: str,
    now: datetime | None = None,
) -> tuple[DriveFolder, DriveFolder]:
    """Create the timestamped Drive folder for this evaluator run."""
    parent = get_drive_folder(service, parent_folder_id)
    run_folder = create_drive_folder(
        service,
        drive_run_folder_name(now),
        parent_id=parent.id,
    )
    return parent, run_folder


def generate_cv_pdf_outputs(
    records: Sequence[JobRecord],
    evaluations: Mapping[int, JobEvaluation],
    *,
    photo_path: Path | None = None,
    drive_service: Any | None = None,
    parent_folder_id: str = DEFAULT_DRIVE_PARENT_FOLDER_ID,
    applicant_name: str = DEFAULT_CV_PDF_APPLICANT_NAME,
    now: datetime | None = None,
    timeout_seconds: int = 120,
    compile_latex: CompileLatexFunc = compile_latex_to_pdf,
    upload_pdf: UploadPdfFunc = upload_pdf_to_drive,
    max_page_limit: int = DEFAULT_CV_MAX_PAGES,
    shorten_latex: ShortenLatexFunc | None = None,
    max_shorten_attempts: int = DEFAULT_CV_MAX_SHORTEN_ATTEMPTS,
) -> CvPdfRunResult:
    """Compile generated CVs, upload PDFs to Drive, and return sheet values.

    When ``shorten_latex`` is provided and a compiled CV exceeds
    ``max_page_limit`` pages, the LaTeX is sent to ``shorten_latex`` and
    recompiled.  This repeats up to ``max_shorten_attempts`` times.
    """
    candidates = assign_cv_ids(
        records,
        evaluations,
        applicant_name=applicant_name,
    )
    if not candidates:
        return CvPdfRunResult(outputs={}, success_count=0, error_count=0)

    try:
        service = drive_service or build_evaluator_google_drive_service()
        _, run_folder = prepare_drive_run_folder(
            service,
            parent_folder_id=parent_folder_id,
            now=now,
        )
    except Exception as exc:
        message = error_cell("Google Drive setup failed", str(exc))
        return CvPdfRunResult(
            outputs={candidate.row_number: message for candidate in candidates},
            success_count=0,
            error_count=len(candidates),
        )

    outputs: dict[int, str] = {}
    success_count = 0
    error_count = 0
    with tempfile.TemporaryDirectory(prefix="jobfinder_cv_pdfs_") as temp_name:
        output_dir = Path(temp_name)
        for candidate in candidates:
            pdf_path = output_dir / candidate.filename
            compile_result = _compile_with_page_limit(
                candidate,
                pdf_path=pdf_path,
                photo_path=photo_path,
                timeout_seconds=timeout_seconds,
                compile_latex=compile_latex,
                max_page_limit=max_page_limit,
                shorten_latex=shorten_latex,
                max_shorten_attempts=max_shorten_attempts,
            )

            if not compile_result.success or compile_result.pdf_path is None:
                outputs[candidate.row_number] = error_cell(
                    "LaTeX compilation failed",
                    compile_result.error,
                )
                error_count += 1
                continue

            try:
                uploaded = upload_pdf(
                    service,
                    compile_result.pdf_path,
                    folder_id=run_folder.id,
                    filename=candidate.filename,
                )
            except Exception as exc:
                outputs[candidate.row_number] = error_cell(
                    "Google Drive upload failed",
                    str(exc),
                )
                error_count += 1
                continue

            outputs[candidate.row_number] = str(uploaded.web_view_link)
            success_count += 1

    return CvPdfRunResult(
        outputs=outputs,
        success_count=success_count,
        error_count=error_count,
        run_folder_name=run_folder.name,
        run_folder_link=run_folder.web_view_link,
    )


def _compile_with_page_limit(
    candidate: CvPdfCandidate,
    *,
    pdf_path: Path,
    photo_path: Path | None,
    timeout_seconds: int,
    compile_latex: CompileLatexFunc,
    max_page_limit: int,
    shorten_latex: ShortenLatexFunc | None,
    max_shorten_attempts: int,
) -> LatexCompilationResult:
    """Compile a CV PDF, shortening the LaTeX if it exceeds max_page_limit pages.

    On each iteration:
    1. Compile the current LaTeX.
    2. If compilation failed, return the failure result immediately.
    3. If the page count is within the limit (or unknown), return success.
    4. Otherwise call ``shorten_latex`` and loop — up to ``max_shorten_attempts``
       times.  After exhausting attempts, return the last successful compilation
       even if it still exceeds the page limit.
    """
    current_latex = candidate.latex
    last_result: LatexCompilationResult | None = None

    for attempt in range(max_shorten_attempts + 1):
        result = compile_latex(
            current_latex,
            pdf_path,
            photo_path=photo_path,
            timeout_seconds=timeout_seconds,
        )
        last_result = result

        if not result.success or result.pdf_path is None:
            return result

        page_count = result.page_count

        # Accept when: page count unknown, within limit, or no shortener wired up.
        if page_count is None or page_count <= max_page_limit or shorten_latex is None:
            if page_count is not None and page_count > max_page_limit:
                LOGGER.warning(
                    "Row %s (%s): CV is %s page(s) but no shortener is configured "
                    "(max_page_limit=%s). Uploading as-is.",
                    candidate.row_number,
                    candidate.display_name,
                    page_count,
                    max_page_limit,
                )
            return result

        # Page count exceeds limit and shortener is available.
        if attempt >= max_shorten_attempts:
            LOGGER.warning(
                "Row %s (%s): CV is still %s page(s) after %s shortening "
                "attempt(s) (limit %s). Uploading current version.",
                candidate.row_number,
                candidate.display_name,
                page_count,
                max_shorten_attempts,
                max_page_limit,
            )
            return result

        LOGGER.info(
            "Row %s (%s): CV compiled to %s page(s) (limit %s). "
            "Requesting AI shortening (attempt %s/%s) ...",
            candidate.row_number,
            candidate.display_name,
            page_count,
            max_page_limit,
            attempt + 1,
            max_shorten_attempts,
        )
        try:
            current_latex = shorten_latex(current_latex, page_count)
        except Exception as exc:
            LOGGER.warning(
                "Row %s (%s): CV shortening failed: %s. Uploading current version.",
                candidate.row_number,
                candidate.display_name,
                exc,
            )
            return result

    # Unreachable but satisfies the type checker.
    return last_result  # type: ignore[return-value]
