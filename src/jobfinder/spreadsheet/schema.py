"""Canonical spreadsheet column contracts shared across JobFinder features."""

from __future__ import annotations

EVALUATION_OUTPUT_COLUMNS = [
    "AI Verdict",
    "AI Fit Score",
    "AI Unsuitable Reasons",
    "AI Tailored CV",
    "AI CV PDF",
]
"""AI columns kept in the final spreadsheet."""

OUTPUT_COLUMNS = EVALUATION_OUTPUT_COLUMNS
"""Backward-compatible alias for the final AI output columns."""

REMOVED_AI_OUTPUT_COLUMNS = [
    "AI Category",
    "AI Reason",
    "AI Raw Verdict",
    "AI Evaluated At",
    "AI Model",
    "AI Error",
]
"""Legacy AI columns removed from the final spreadsheet after evaluation."""

AI_OUTPUT_COLUMNS = EVALUATION_OUTPUT_COLUMNS + REMOVED_AI_OUTPUT_COLUMNS
"""All AI output columns, including legacy columns, for prompt filtering."""

DETAIL_COLUMNS = [
    "Job Description",
    "Description",
    "Details",
    "Job Details",
]
"""Job detail/description columns removed from the spreadsheet after evaluation."""

SCRAPER_OUTPUT_COLUMNS = [
    "Application Status",
    "App",
    "Job Title",
    "Company",
    "Location",
    "Job Type",
    "Job Description",
    "Posted",
    "Applicants",
    "Keywords Matched",
    "Job URL",
    "Apply URL",
    *EVALUATION_OUTPUT_COLUMNS,
]
"""Stable output columns written by scraper exports."""

HEADER = SCRAPER_OUTPUT_COLUMNS
"""Backward-compatible alias for scraper export headers."""
