"""Tests for evaluator orchestration."""

from __future__ import annotations

from jobfinder.evaluator.models import JobEvaluation, JobRecord
from jobfinder.evaluator.openai_client import (
    OpenAIJobEvaluator,
    RequestPacer,
    evaluate_records,
)


class FakeEvaluator:
    """Small evaluator double for orchestration tests."""

    model = "test-model"

    def evaluate(
        self,
        record: JobRecord,
        master_prompt: str,
        latex_cv: str,
    ) -> JobEvaluation:
        return JobEvaluation(
            row_number=record.row_number,
            verdict="Suitable",
            fit_score=90,
            reason=f"Evaluated {record.display_name}",
            model=self.model,
        )


def make_records(count: int) -> list[JobRecord]:
    return [
        JobRecord(
            row_number=idx + 2,
            display_name=f"row {idx + 2}",
            advertisement="Job Title: GIS Analyst\nCompany: Acme",
        )
        for idx in range(count)
    ]


def test_evaluate_records_calls_save_callback_for_each_result():
    """Each evaluated row should be made available for immediate persistence."""
    saved_rows: list[int] = []

    results = evaluate_records(
        make_records(3),
        evaluator=FakeEvaluator(),
        master_prompt="Prompt",
        latex_cv="CV",
        concurrency=1,
        batch_size=2,
        large_queue_threshold=200,
        large_queue_sleep_ms=1000,
        on_evaluation=lambda evaluation: saved_rows.append(evaluation.row_number),
    )

    assert saved_rows == [2, 3, 4]
    assert list(results) == [2, 3, 4]


def test_evaluate_records_paces_only_large_queues(monkeypatch):
    """Request pacing should activate only above the configured record threshold."""
    waits: list[float] = []

    def record_wait(self: RequestPacer) -> None:
        waits.append(self.delay_seconds)

    monkeypatch.setattr(RequestPacer, "wait", record_wait)

    evaluate_records(
        make_records(2),
        evaluator=FakeEvaluator(),
        master_prompt="Prompt",
        latex_cv="CV",
        concurrency=1,
        batch_size=2,
        large_queue_threshold=2,
        large_queue_sleep_ms=250,
    )
    assert waits == []

    evaluate_records(
        make_records(3),
        evaluator=FakeEvaluator(),
        master_prompt="Prompt",
        latex_cv="CV",
        concurrency=1,
        batch_size=3,
        large_queue_threshold=2,
        large_queue_sleep_ms=250,
    )

    assert waits == [0.25, 0.25, 0.25]


def test_openai_evaluator_restores_master_education_section(monkeypatch):
    """The OpenAI evaluator should not trust a model-shortened education section."""
    evaluator = OpenAIJobEvaluator.__new__(OpenAIJobEvaluator)
    evaluator.model = "test-model"

    def fake_call_openai(prompt: str, record: JobRecord) -> str:
        return r"""Verdict: Suitable
Fit Score: 91%
Unsuitable Reasons:

Customized CV (LaTeX):
```latex
\documentclass{article}
\begin{document}
\section*{Profil}
Tailored profile

\section*{Ausbildung}
\textbf{Politecnico di Milano}

\section*{Berufserfahrung}
Tailored experience
\end{document}
```
"""

    monkeypatch.setattr(evaluator, "call_openai", fake_call_openai)
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

    result = evaluator.evaluate(
        JobRecord(
            row_number=2,
            display_name="GIS Analyst",
            advertisement="Job Title: GIS Analyst",
        ),
        "Prompt",
        master_cv,
    )

    assert result.verdict == "Suitable"
    assert r"\item \textbf{Universit\"at Bonn}" in result.tailored_cv
    assert (
        r"\item \textbf{Karlsruher Institut f\"ur Technologie (KIT)}"
        in result.tailored_cv
    )
    assert r"\textbf{Universit\"at Teheran}" in result.tailored_cv


def test_openai_evaluator_retries_suitable_response_missing_cv(monkeypatch):
    """Suitable responses that omit LaTeX should get a targeted repair call."""
    evaluator = OpenAIJobEvaluator.__new__(OpenAIJobEvaluator)
    evaluator.model = "test-model"
    responses = [
        """Verdict: Suitable
Fit Score: 86%
Unsuitable Reasons:

Why it fits:
- Solid GIS match.
""",
        r"""Verdict: Suitable
Fit Score: 86%
Unsuitable Reasons:

Customized CV (LaTeX):
```latex
\documentclass{article}
\begin{document}
\section*{Profil}
Tailored profile

\section*{Ausbildung}
\textbf{Politecnico di Milano}

\section*{Berufserfahrung}
Tailored experience
\end{document}
```
""",
    ]
    prompts: list[str] = []

    def fake_call_openai(prompt: str, record: JobRecord) -> str:
        prompts.append(prompt)
        return responses.pop(0)

    monkeypatch.setattr(evaluator, "call_openai", fake_call_openai)
    master_cv = r"""\documentclass{article}
\begin{document}
\section*{Ausbildung}
\textbf{Politecnico di Milano}
\begin{itemize}
    \item \textbf{Universit\"at Bonn}
\end{itemize}

\section*{Berufserfahrung}
Master experience
\end{document}
"""

    result = evaluator.evaluate(
        JobRecord(
            row_number=2,
            display_name="GIS Analyst",
            advertisement="Job Title: GIS Analyst",
        ),
        "Prompt",
        master_cv,
    )

    assert result.verdict == "Suitable"
    assert len(prompts) == 2
    assert "Missing Tailored CV Repair Task" in prompts[1]
    assert r"\section*{Profil}" in result.tailored_cv
    assert r"\item \textbf{Universit\"at Bonn}" in result.tailored_cv
