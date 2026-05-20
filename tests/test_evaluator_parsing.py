"""Tests for evaluator row and model-response parsing."""

from __future__ import annotations

from jobfinder.evaluator.models import OUTPUT_COLUMNS
from jobfinder.evaluator.parsing import (
    enforce_protected_cv_sections,
    ensure_output_columns,
    extract_job_records,
    parse_model_response,
    row_to_job_advertisement,
)
from jobfinder.evaluator.storage import columns_to_remove_after_evaluation


def test_ensure_output_columns_appends_missing_ai_columns():
    """AI output columns should be appended without disturbing existing headers."""
    headers, header_map = ensure_output_columns(["Job Title", "Company"])

    assert headers[:2] == ["Job Title", "Company"]
    assert headers[-len(OUTPUT_COLUMNS) :] == OUTPUT_COLUMNS
    assert header_map["ai verdict"] == 2


def test_row_to_job_advertisement_omits_operational_columns():
    """Prompts should exclude URLs, applicant counts, status, and AI output."""
    headers = [
        "Job Title",
        "Applicants",
        "Job URL",
        "AI Verdict",
        "AI Unsuitable Reasons",
        "AI Reason",
        "Company",
    ]
    row = [
        "GIS Analyst",
        "90",
        "https://example.com",
        "Suitable",
        "Too senior",
        "Old reason",
        "Acme",
    ]

    advertisement = row_to_job_advertisement(headers, row)

    assert advertisement == "Job Title: GIS Analyst\nCompany: Acme"


def test_extract_job_records_skips_existing_non_error_verdicts():
    """Rows already evaluated successfully should not be queued by default."""
    headers, _ = ensure_output_columns(["Job Title", "Company"])
    verdict_idx = headers.index("AI Verdict")
    tailored_cv_idx = headers.index("AI Tailored CV")
    row = ["GIS Analyst", "Acme"] + [""] * (len(headers) - 2)
    row[verdict_idx] = "Suitable"
    row[tailored_cv_idx] = r"\documentclass{article}\begin{document}\end{document}"

    records, skipped = extract_job_records(
        headers,
        [row],
    )

    assert records == []
    assert skipped == 1


def test_extract_job_records_requeues_suitable_rows_missing_cv():
    """Suitable rows without usable LaTeX should be retried instead of skipped."""
    headers, _ = ensure_output_columns(["Job Title", "Company"])
    verdict_idx = headers.index("AI Verdict")
    tailored_cv_idx = headers.index("AI Tailored CV")
    row = ["GIS Analyst", "Acme"] + [""] * (len(headers) - 2)
    row[verdict_idx] = "Suitable"
    row[tailored_cv_idx] = ""

    records, skipped = extract_job_records(
        headers,
        [row],
    )

    assert len(records) == 1
    assert records[0].row_number == 2
    assert skipped == 0


def test_parse_model_response_extracts_verdict_score_reason_and_cv():
    """Machine-readable model responses should parse into evaluator fields."""
    response = """Verdict: Suitable
Fit Score: 88%

Strong GIS/Python match.

Customized CV (LaTeX):
```latex
\\section{Experience}
```
"""

    result = parse_model_response(response, row_number=7, model="test-model")

    assert result.verdict == "Suitable"
    assert result.fit_score == 88
    assert result.reason == "Strong GIS/Python match."
    assert result.tailored_cv == r"\section{Experience}"
    assert result.value_for_column("AI Unsuitable Reasons") == ""


def test_parse_model_response_extracts_unsuitable_reasons_for_rejected_jobs():
    """Not-suitable rows should expose rejection reasons in the dedicated column."""
    response = """Verdict: Not Suitable
Fit Score: 28%
Unsuitable Reasons: Requires fluent German and senior cloud architecture experience.
"""

    result = parse_model_response(response, row_number=8, model="test-model")

    assert result.verdict == "Not Suitable"
    assert result.reason == (
        "Requires fluent German and senior cloud architecture experience."
    )
    assert result.unsuitable_reasons == (
        "Requires fluent German and senior cloud architecture experience."
    )
    assert result.value_for_column("AI Unsuitable Reasons") == (
        "Requires fluent German and senior cloud architecture experience."
    )


def test_enforce_protected_cv_sections_restores_master_education():
    """Generated CVs should keep the master education section intact."""
    master_cv = r"""\documentclass{article}
\begin{document}
\section*{Profil}
Master profile

\section*{Ausbildung}
\textbf{Politecnico di Milano}
\begin{itemize}
    \item \textbf{Universit\"at Bonn}
    \item \textbf{Karlsruher Institut f\"ur Technologie (KIT)}
\end{itemize}
\textbf{Universit\"at Teheran}

\section*{Berufserfahrung}
Master experience
\end{document}
"""
    generated_cv = r"""\documentclass{article}
\begin{document}
\section*{Profil}
Tailored profile

\section*{Ausbildung}
\textbf{Politecnico di Milano}

\section*{Berufserfahrung}
Tailored experience
\end{document}
"""

    protected_cv = enforce_protected_cv_sections(generated_cv, master_cv)

    assert r"\item \textbf{Universit\"at Bonn}" in protected_cv
    assert r"\item \textbf{Karlsruher Institut f\"ur Technologie (KIT)}" in protected_cv
    assert r"\textbf{Universit\"at Teheran}" in protected_cv
    assert protected_cv.index(r"\section*{Ausbildung}") < protected_cv.index(
        r"\section*{Berufserfahrung}"
    )


def test_columns_to_remove_after_evaluation_targets_details_and_old_ai_columns():
    """Cleanup should remove details and legacy AI metadata columns."""
    headers = [
        "Job Title",
        "Job Description",
        "AI Verdict",
        "AI Fit Score",
        "AI Unsuitable Reasons",
        "AI Category",
        "AI Reason",
        "AI Tailored CV",
        "AI Error",
    ]

    assert columns_to_remove_after_evaluation(headers) == [1, 5, 6, 8]
