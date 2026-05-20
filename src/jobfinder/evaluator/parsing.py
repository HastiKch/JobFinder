"""Parsing helpers for evaluator worksheet rows and model responses."""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jobfinder.evaluator.models import (
    AI_OUTPUT_COLUMNS,
    OUTPUT_COLUMNS,
    UNHELPFUL_COLUMNS,
    EvaluationError,
    JobEvaluation,
    JobRecord,
)

LOGGER = logging.getLogger("job_fit_evaluator")

VERDICT_RE = re.compile(r"(?im)^\s*Verdict\s*:\s*(?P<value>.+?)\s*$")
FIT_SCORE_RE = re.compile(r"(?im)^\s*Fit\s+Score\s*:\s*(?P<score>\d{1,3})\s*%")
UNSUITABLE_REASONS_LABEL_RE = re.compile(
    r"(?i)^(?:\d+\.\s*)?unsuitable\s+reasons?\s*:\s*(?P<value>.*)$"
)
CV_SECTION_RE = re.compile(
    r"(?is)\n?\s*(?:\d+\.\s*)?Customized\s+CV\s*\(LaTeX\)\s*:\s*"
)
LATEX_CODE_BLOCK_RE = re.compile(r"(?is)```(?:latex)?\s*(?P<cv>.*?)```")
LATEX_SECTION_START_RE = re.compile(r"(?m)^[ \t]*\\section\*?\{(?P<title>[^}]+)\}")

PROTECTED_CV_SECTION_TITLES = ("Ausbildung",)
EDUCATION_SECTION_ALIASES = (
    "Ausbildung",
    "Education",
    "Bildung",
    "Qualifikation",
    "Qualifikationen",
)
EDUCATION_INSERTION_ANCHORS = (
    "Berufserfahrung",
    "Experience",
    "Projekte",
    "Projects",
    "Technische Fähigkeiten",
    "Technical Skills",
    "Sprachen",
    "Languages",
)


def normalize_header(value: Any) -> str:
    """Normalize a spreadsheet header for robust lookup."""
    text = "" if value is None else str(value)
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


def trim_trailing_blank_headers(headers: list[Any]) -> list[str]:
    """Drop blank header cells after the last meaningful header."""
    last_idx = 0
    for idx, header in enumerate(headers, start=1):
        if str(header or "").strip():
            last_idx = idx
    return [str(header or "").strip() for header in headers[:last_idx]]


def build_header_map(headers: list[str]) -> dict[str, int]:
    """Build a normalized-header to zero-based-index map."""
    header_map: dict[str, int] = {}
    for idx, header in enumerate(headers):
        normalized = normalize_header(header)
        if normalized and normalized not in header_map:
            header_map[normalized] = idx
    return header_map


def ensure_output_columns(headers: list[str]) -> tuple[list[str], dict[str, int]]:
    """Append missing evaluator output columns to an existing header row."""
    updated_headers = list(headers)
    header_map = build_header_map(updated_headers)
    for column in OUTPUT_COLUMNS:
        normalized = normalize_header(column)
        if normalized not in header_map:
            header_map[normalized] = len(updated_headers)
            updated_headers.append(column)
    return updated_headers, header_map


def get_row_value(row: list[Any], idx: int) -> Any:
    """Return a row value by index or an empty string when absent."""
    if idx >= len(row):
        return ""
    value = row[idx]
    return "" if value is None else value


def row_is_empty(row: list[Any]) -> bool:
    """Return true when a worksheet row has no visible values."""
    return not any(str(value or "").strip() for value in row)


def clean_cell_text(value: Any) -> str:
    """Normalize worksheet cell text for prompt construction."""
    if value is None:
        return ""
    text = str(value).strip()
    if text == "N/A":
        return ""
    return re.sub(r"\s+", " ", text)


def include_job_column(header: str) -> bool:
    """Return true when a column is useful for the job advertisement prompt."""
    normalized = normalize_header(header)
    if not normalized:
        return False
    if normalized in UNHELPFUL_COLUMNS:
        return False
    if normalized in {normalize_header(column) for column in AI_OUTPUT_COLUMNS}:
        return False
    return True


def row_to_job_advertisement(headers: list[str], row: list[Any]) -> str:
    """Build the prompt advertisement text from a worksheet row."""
    lines = []
    for idx, header in enumerate(headers):
        if not include_job_column(header):
            continue
        value = clean_cell_text(get_row_value(row, idx))
        if value:
            lines.append(f"{header}: {value}")
    return "\n".join(lines)


def display_name_for_row(headers: list[str], row: list[Any], row_number: int) -> str:
    """Return a concise human-readable label for logging a worksheet row."""
    header_map = build_header_map(headers)
    title_idx = header_map.get("job title")
    if title_idx is None:
        title_idx = header_map.get("title")
    company_idx = header_map.get("company")
    title = (
        clean_cell_text(get_row_value(row, title_idx)) if title_idx is not None else ""
    )
    company = (
        clean_cell_text(get_row_value(row, company_idx))
        if company_idx is not None
        else ""
    )
    label = " / ".join(part for part in (title, company) if part)
    return label or f"row {row_number}"


def extract_job_records(
    headers: list[str],
    rows: list[list[Any]],
    *,
    reevaluate_existing: bool = False,
) -> tuple[list[JobRecord], int]:
    """Extract queued evaluator records from worksheet rows."""
    header_map = build_header_map(headers)
    verdict_idx = header_map.get(normalize_header("AI Verdict"))
    tailored_cv_idx = header_map.get(normalize_header("AI Tailored CV"))
    records: list[JobRecord] = []
    skipped_existing = 0

    for offset, row in enumerate(rows, start=2):
        if row_is_empty(row):
            continue

        existing_verdict = (
            clean_cell_text(get_row_value(row, verdict_idx))
            if verdict_idx is not None
            else ""
        )
        existing_tailored_cv = (
            clean_cell_text(get_row_value(row, tailored_cv_idx))
            if tailored_cv_idx is not None
            else ""
        )
        normalized_verdict = existing_verdict.casefold()
        suitable_missing_cv = (
            normalized_verdict == "suitable"
            and not looks_like_latex_cv(existing_tailored_cv)
        )
        if (
            not reevaluate_existing
            and existing_verdict
            and normalized_verdict != "error"
        ):
            if not suitable_missing_cv:
                skipped_existing += 1
                continue

        advertisement = row_to_job_advertisement(headers, row)
        if len(advertisement) < 20:
            LOGGER.warning("Skipping row %s because it has no usable job data.", offset)
            continue

        records.append(
            JobRecord(
                row_number=offset,
                display_name=display_name_for_row(headers, row, offset),
                advertisement=advertisement,
            )
        )

    return records, skipped_existing


def read_text_asset(path: Path, label: str) -> str:
    """Read a required prompt or CV text asset from disk."""
    if not path.exists():
        raise EvaluationError(f"Missing {label}: {path}")
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise EvaluationError(f"{label} is empty: {path}")
    return text


def build_full_prompt(master_prompt: str, job_advertisement: str, latex_cv: str) -> str:
    """Compose the final model prompt for one job record."""
    return "\n\n".join(
        [
            master_prompt.rstrip(),
            "%==================================================\n"
            "% 1. Job Advertisement\n"
            "%==================================================\n\n"
            f"{job_advertisement.strip()}",
            "%==================================================\n"
            "% 2. Master LaTeX CV\n"
            "%==================================================\n\n"
            "```latex\n"
            f"{latex_cv.strip()}\n"
            "```",
        ]
    )


def build_missing_cv_retry_prompt(
    master_prompt: str,
    job_advertisement: str,
    latex_cv: str,
    previous_response_text: str,
) -> str:
    """Compose a focused repair prompt when a suitable job omitted the CV."""
    return "\n\n".join(
        [
            master_prompt.rstrip(),
            "%==================================================\n"
            "% Missing Tailored CV Repair Task\n"
            "%==================================================\n\n"
            "The previous response marked this job as Suitable but did not include "
            "a usable customized LaTeX CV. Do not skip CV generation. Do not "
            "change the Suitable verdict. Generate the missing full tailored "
            "German LaTeX CV now, using only the Master LaTeX CV as evidence.\n\n"
            "Return the first three machine-readable lines, then include:\n\n"
            "Customized CV (LaTeX):\n"
            "```latex\n"
            "fully tailored LaTeX CV here\n"
            "```",
            "%==================================================\n"
            "% Previous Incomplete Response\n"
            "%==================================================\n\n"
            "```text\n"
            f"{previous_response_text.strip()}\n"
            "```",
            "%==================================================\n"
            "% Job Advertisement\n"
            "%==================================================\n\n"
            f"{job_advertisement.strip()}",
            "%==================================================\n"
            "% Master LaTeX CV\n"
            "%==================================================\n\n"
            "```latex\n"
            f"{latex_cv.strip()}\n"
            "```",
        ]
    )


def looks_like_latex_cv(text: str) -> bool:
    """Return true when text appears to be usable LaTeX CV content."""
    candidate = text.strip()
    if not candidate:
        return False
    if candidate.casefold() in {"n/a", "na", "none", "null", "not applicable"}:
        return False
    return bool(
        re.search(
            r"\\(?:documentclass|begin\{document\}|section\*?\{|textbf\{)",
            candidate,
        )
    )


def extract_latex_cv_from_response(response_text: str) -> str:
    """Extract usable LaTeX CV content from a model response."""
    tailored_cv = extract_tailored_cv(response_text)
    if looks_like_latex_cv(tailored_cv):
        return tailored_cv

    block = LATEX_CODE_BLOCK_RE.search(response_text)
    if block:
        candidate = block.group("cv").strip()
        if looks_like_latex_cv(candidate):
            return candidate

    stripped = response_text.strip()
    if looks_like_latex_cv(stripped):
        return stripped

    return ""


def normalize_latex_section_title(title: str) -> str:
    """Normalize a LaTeX section title for tolerant matching."""
    return re.sub(r"\s+", " ", title).strip().casefold()


def latex_section_span(
    latex: str,
    titles: str | tuple[str, ...],
) -> tuple[int, int] | None:
    """Return the start/end indexes for the first matching LaTeX section."""
    expected_titles = (titles,) if isinstance(titles, str) else titles
    normalized_titles = {
        normalize_latex_section_title(title) for title in expected_titles
    }
    section_starts = list(LATEX_SECTION_START_RE.finditer(latex))

    for idx, match in enumerate(section_starts):
        if normalize_latex_section_title(match.group("title")) not in normalized_titles:
            continue

        end = (
            section_starts[idx + 1].start()
            if idx + 1 < len(section_starts)
            else len(latex)
        )
        return match.start(), end

    return None


def extract_latex_section(latex: str, title: str) -> str:
    """Extract one complete LaTeX section by title."""
    span = latex_section_span(latex, title)
    if span is None:
        return ""
    start, end = span
    return latex[start:end].strip()


def insertion_index_for_latex_section(
    latex: str,
    before_titles: tuple[str, ...],
) -> int:
    """Find where a missing protected section should be inserted."""
    normalized_titles = {
        normalize_latex_section_title(title) for title in before_titles
    }
    for match in LATEX_SECTION_START_RE.finditer(latex):
        if normalize_latex_section_title(match.group("title")) in normalized_titles:
            return match.start()

    end_document_match = re.search(r"(?m)^[ \t]*\\end\{document\}", latex)
    if end_document_match:
        return end_document_match.start()

    return len(latex)


def replace_or_insert_latex_section(
    generated_latex: str,
    *,
    source_section: str,
    generated_titles: tuple[str, ...],
    insertion_anchors: tuple[str, ...],
) -> str:
    """Replace a generated section, or insert it if the model removed it."""
    generated_span = latex_section_span(generated_latex, generated_titles)
    if generated_span is None:
        insertion_index = insertion_index_for_latex_section(
            generated_latex,
            insertion_anchors,
        )
        prefix = generated_latex[:insertion_index].rstrip()
        suffix = generated_latex[insertion_index:].lstrip("\n")
    else:
        start, end = generated_span
        prefix = generated_latex[:start].rstrip()
        suffix = generated_latex[end:].lstrip("\n")

    return "\n\n".join(
        part for part in (prefix, source_section, suffix) if part
    ).strip()


def enforce_protected_cv_sections(
    generated_latex: str,
    master_latex: str,
    *,
    section_titles: tuple[str, ...] = PROTECTED_CV_SECTION_TITLES,
) -> str:
    """Restore protected CV sections from the master CV after model generation."""
    updated_latex = generated_latex.strip()
    for section_title in section_titles:
        source_section = extract_latex_section(master_latex, section_title)
        if not source_section:
            continue

        if section_title == "Ausbildung":
            updated_latex = replace_or_insert_latex_section(
                updated_latex,
                source_section=source_section,
                generated_titles=EDUCATION_SECTION_ALIASES,
                insertion_anchors=EDUCATION_INSERTION_ANCHORS,
            )
            continue

        updated_latex = replace_or_insert_latex_section(
            updated_latex,
            source_section=source_section,
            generated_titles=(section_title,),
            insertion_anchors=(),
        )

    return updated_latex


def normalize_verdict(raw_value: str) -> str | None:
    """Normalize a model verdict into the supported output labels."""
    text = raw_value.casefold()
    text_without_negative = re.sub(r"\bnot\s+suitable\b", "", text)
    has_not_suitable = "not suitable" in text or "❌" in raw_value
    has_maybe = "maybe" in text or "⚠" in raw_value
    has_suitable = bool(re.search(r"\bsuitable\b", text_without_negative)) or (
        "✅" in raw_value
    )

    labels = set()
    if has_not_suitable:
        labels.add("Not Suitable")
    if has_maybe:
        labels.add("Maybe")
    if has_suitable:
        labels.add("Suitable")

    if labels == {"Suitable"}:
        return "Suitable"
    if labels in ({"Not Suitable"}, {"Maybe"}):
        return "Not Suitable"
    return None


def extract_tailored_cv(response_text: str) -> str:
    """Extract the optional tailored LaTeX CV section from a model response."""
    parts = CV_SECTION_RE.split(response_text, maxsplit=1)
    if len(parts) == 1:
        return ""

    cv_text = parts[1].strip()
    block = LATEX_CODE_BLOCK_RE.search(cv_text)
    if block:
        return block.group("cv").strip()
    return cv_text


def remove_tailored_cv(response_text: str) -> str:
    """Remove the optional tailored CV section from a model response."""
    return CV_SECTION_RE.split(response_text, maxsplit=1)[0].strip()


def extract_reason(response_text: str) -> str:
    """Extract the human-readable reason from a model response."""
    evaluation_text = remove_tailored_cv(response_text)
    lines: list[str] = []
    for line in evaluation_text.splitlines():
        stripped = line.strip()
        if not stripped:
            if lines and lines[-1]:
                lines.append("")
            continue
        if re.match(r"(?i)^(?:\d+\.\s*)?fit evaluation$", stripped):
            continue
        if re.match(r"(?i)^verdict\s*:", stripped):
            continue
        if re.match(r"(?i)^fit\s+score\s*:", stripped):
            continue
        unsuitable_reasons_match = UNSUITABLE_REASONS_LABEL_RE.match(stripped)
        if unsuitable_reasons_match:
            label_value = unsuitable_reasons_match.group("value").strip()
            if label_value:
                lines.append(label_value)
            continue
        lines.append(line.rstrip())

    return "\n".join(lines).strip()


def extract_unsuitable_reasons(response_text: str) -> str:
    """Extract the labeled reasons for rejecting a not-suitable job."""
    evaluation_text = remove_tailored_cv(response_text)
    lines: list[str] = []
    collecting = False

    for line in evaluation_text.splitlines():
        stripped = line.strip()
        label_match = UNSUITABLE_REASONS_LABEL_RE.match(stripped)
        if label_match:
            collecting = True
            label_value = label_match.group("value").strip()
            if label_value:
                lines.append(label_value)
            continue

        if not collecting:
            continue
        if re.match(r"(?i)^verdict\s*:", stripped):
            break
        if re.match(r"(?i)^fit\s+score\s*:", stripped):
            break
        if not stripped:
            if lines and lines[-1]:
                lines.append("")
            continue
        lines.append(line.rstrip())

    return "\n".join(lines).strip()


def parse_model_response(
    response_text: str,
    *,
    row_number: int,
    model: str,
) -> JobEvaluation:
    """Parse the model response into a structured evaluation."""
    evaluated_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    verdict_match = VERDICT_RE.search(response_text)
    score_match = FIT_SCORE_RE.search(response_text)

    if not verdict_match or not score_match:
        return JobEvaluation(
            row_number=row_number,
            verdict="Error",
            fit_score=None,
            reason="",
            evaluated_at=evaluated_at,
            model=model,
            error="Parsing failed: missing required Verdict or Fit Score line.",
        )

    raw_verdict = verdict_match.group("value").strip()
    verdict = normalize_verdict(raw_verdict)
    try:
        score = int(score_match.group("score"))
    except ValueError:
        score = -1

    if verdict is None or not 0 <= score <= 100:
        return JobEvaluation(
            row_number=row_number,
            verdict="Error",
            fit_score=None,
            reason=extract_reason(response_text),
            unsuitable_reasons=extract_unsuitable_reasons(response_text),
            raw_verdict=raw_verdict,
            tailored_cv=extract_tailored_cv(response_text),
            evaluated_at=evaluated_at,
            model=model,
            error="Parsing failed: invalid verdict or score.",
        )

    return JobEvaluation(
        row_number=row_number,
        verdict=verdict,
        fit_score=score,
        reason=extract_reason(response_text),
        unsuitable_reasons=(
            extract_unsuitable_reasons(response_text)
            if verdict == "Not Suitable"
            else ""
        ),
        raw_verdict=raw_verdict,
        tailored_cv=extract_tailored_cv(response_text),
        evaluated_at=evaluated_at,
        model=model,
    )


def get_response_text(response: Any) -> str:
    """Extract text from OpenAI Responses API result shapes."""
    output_text = getattr(response, "output_text", None)
    if output_text:
        return str(output_text).strip()

    parts = []
    for item in getattr(response, "output", []) or []:
        for content in getattr(item, "content", []) or []:
            text = getattr(content, "text", None)
            if text:
                parts.append(str(text))
    return "\n".join(parts).strip()
