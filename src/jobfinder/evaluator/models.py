"""Domain models and constants for job-fit evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from jobfinder.spreadsheet.schema import (
    AI_OUTPUT_COLUMNS,
    DETAIL_COLUMNS,
    OUTPUT_COLUMNS,
    REMOVED_AI_OUTPUT_COLUMNS,
)

__all__ = [
    "AI_OUTPUT_COLUMNS",
    "DEFAULT_MODEL",
    "DETAIL_COLUMNS",
    "EvaluationError",
    "GoogleSheetsError",
    "JobEvaluation",
    "JobRecord",
    "OpenAIQuotaError",
    "OUTPUT_COLUMNS",
    "REMOVED_AI_OUTPUT_COLUMNS",
    "UNHELPFUL_COLUMNS",
]

DEFAULT_MODEL = "gpt-5-mini"
MAX_CELL_CHARS = 49_000

UNHELPFUL_COLUMNS = {
    "application status",
    "applicants",
    "applicant",
    "applicant count",
    "applicants count",
    "number of applicants",
    "num applicants",
    "formatted applicants count",
    "job url",
    "apply url",
}


class EvaluationError(RuntimeError):
    """Raised when a row cannot be evaluated or parsed."""


class OpenAIQuotaError(EvaluationError):
    """Raised when OpenAI reports missing/expired quota or billing."""


class GoogleSheetsError(RuntimeError):
    """Raised when Google Sheets access or update fails."""


@dataclass(frozen=True)
class JobRecord:
    """A worksheet row converted into a job advertisement prompt input."""

    row_number: int
    display_name: str
    advertisement: str


@dataclass
class JobEvaluation:
    """Parsed evaluation result for one worksheet row."""

    row_number: int
    verdict: str
    fit_score: int | None
    reason: str
    unsuitable_reasons: str = ""
    raw_verdict: str = ""
    tailored_cv: str = ""
    cv_pdf: str = ""
    evaluated_at: str = ""
    model: str = ""
    error: str = ""

    @property
    def category(self) -> str:
        """Return the spreadsheet category derived from the verdict."""
        if self.verdict == "Suitable":
            return "Relevant"
        if self.verdict == "Not Suitable":
            return "Irrelevant"
        return "Error"

    @property
    def unsuitable_reasons_value(self) -> str:
        """Return rejection reasons only for rows marked not suitable."""
        if self.verdict == "Not Suitable":
            return self.unsuitable_reasons or self.reason
        return ""

    def value_for_column(self, column_name: str) -> Any:
        """Return the output value for a named AI result column."""
        values = {
            "AI Verdict": self.verdict,
            "AI Fit Score": self.fit_score if self.fit_score is not None else "",
            "AI Unsuitable Reasons": self.unsuitable_reasons_value,
            "AI Category": self.category,
            "AI Reason": self.reason,
            "AI Raw Verdict": self.raw_verdict,
            "AI Tailored CV": self.tailored_cv,
            "AI CV PDF": self.cv_pdf,
            "AI Evaluated At": self.evaluated_at,
            "AI Model": self.model,
            "AI Error": self.error,
        }
        return sheet_safe(values[column_name])


def sheet_safe(value: Any) -> Any:
    """Convert evaluator output to a safe spreadsheet cell value."""
    if value is None:
        return ""
    if isinstance(value, int):
        return value

    text = str(value).strip()
    if not text:
        return ""
    if len(text) > MAX_CELL_CHARS:
        text = text[: MAX_CELL_CHARS - 25] + " ... [truncated]"
    if text[0] in "=+-@":
        return "'" + text
    return text
