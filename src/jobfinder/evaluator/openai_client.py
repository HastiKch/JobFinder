"""OpenAI client integration for job-fit evaluation."""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from threading import Lock

from jobfinder.evaluator.models import (
    EvaluationError,
    JobEvaluation,
    JobRecord,
    OpenAIQuotaError,
)
from jobfinder.evaluator.parsing import (
    build_full_prompt,
    build_missing_cv_retry_prompt,
    enforce_protected_cv_sections,
    extract_latex_cv_from_response,
    get_response_text,
    looks_like_latex_cv,
    parse_model_response,
)

LOGGER = logging.getLogger("job_fit_evaluator")

STRICT_OUTPUT_INSTRUCTIONS = """
Preserve the provided MASTER PROMPT logic and evidence rules exactly.
For this automation pipeline, the first three output lines must be machine-readable:

Verdict: <Suitable | Not Suitable>
Fit Score: <integer>%
Unsuitable Reasons: <category labels only when Not Suitable, otherwise blank>

Use "Suitable" only for realistically suitable roles. Use "Not Suitable" for
roles that should be skipped, are unrealistic, or are only borderline. For Not
Suitable roles, Unsuitable Reasons must contain only short category labels
separated by semicolons. Do not write explanatory sentences, job-category
detections, confidence scores, or detailed evidence in Unsuitable Reasons.
Allowed labels include: Language proficiency mismatch; Degree mismatch;
Seniority mismatch; Missing mandatory certification/license; Missing required
professional experience; Missing required tool/software experience; Missing
required domain/industry experience; Must-have skill mismatch;
Leadership/management mismatch; Role type mismatch; Location/relocation
mismatch; Work authorization/clearance mismatch; Physical/medical/safety
requirement mismatch; Other mandatory requirement mismatch. After those three
lines, include any additional reason text and, if required by the MASTER PROMPT,
the tailored LaTeX CV. If Verdict is Suitable, the tailored LaTeX CV is required
and must not be blank, N/A, omitted, or replaced with a placeholder.
""".strip()


class RequestPacer:
    """Thread-safe delay between OpenAI request starts."""

    def __init__(self, delay_seconds: float) -> None:
        self.delay_seconds = delay_seconds
        self._lock = Lock()
        self._next_request_at = 0.0

    def wait(self) -> None:
        """Sleep until the next OpenAI request slot is available."""
        if self.delay_seconds <= 0:
            return

        with self._lock:
            now = time.monotonic()
            if now < self._next_request_at:
                time.sleep(self._next_request_at - now)
                now = time.monotonic()
            self._next_request_at = max(now, self._next_request_at) + self.delay_seconds


def retry_after_seconds(exc: Exception) -> float | None:
    """Return the retry-after delay from an SDK exception when present."""
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None) or {}
    value = headers.get("retry-after") or headers.get("Retry-After")
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None


def openai_error_code(exc: Exception) -> str:
    """Extract an OpenAI error code from SDK exception shapes."""
    code = getattr(exc, "code", None)
    if code:
        return str(code)

    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        body_code = body.get("code")
        if body_code:
            return str(body_code)
        error = body.get("error")
        if isinstance(error, dict) and error.get("code"):
            return str(error["code"])

    return ""


def is_openai_quota_error(exc: Exception) -> bool:
    """Return true when an OpenAI exception indicates missing quota."""
    return openai_error_code(exc) == "insufficient_quota"


def is_retryable_openai_error(exc: Exception) -> bool:
    """Return true when an OpenAI exception is worth retrying."""
    if is_openai_quota_error(exc):
        return False
    class_name = exc.__class__.__name__
    if class_name in {"RateLimitError", "APITimeoutError", "APIConnectionError"}:
        return True
    status_code = getattr(exc, "status_code", None)
    return status_code in {408, 409, 429, 500, 502, 503, 504}


class OpenAIJobEvaluator:
    """Evaluate job records using the OpenAI Responses API."""

    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        timeout: float,
        retries: int,
        base_delay: float,
        max_delay: float,
        max_output_tokens: int,
    ) -> None:
        """Create an evaluator with explicit retry and timeout settings."""
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise EvaluationError(
                "Missing OpenAI Python SDK. Install dependencies with: "
                "python -m pip install -r requirements.txt"
            ) from exc

        self.model = model
        self.retries = retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.max_output_tokens = max_output_tokens
        self.client = OpenAI(api_key=api_key, timeout=timeout, max_retries=0)

    def evaluate(
        self,
        record: JobRecord,
        master_prompt: str,
        latex_cv: str,
    ) -> JobEvaluation:
        """Evaluate a single job record and parse the model response."""
        prompt = build_full_prompt(master_prompt, record.advertisement, latex_cv)
        response_text = self.call_openai(prompt, record)
        evaluation = parse_model_response(
            response_text,
            row_number=record.row_number,
            model=self.model,
        )
        if evaluation.verdict == "Suitable" and not looks_like_latex_cv(
            evaluation.tailored_cv
        ):
            LOGGER.warning(
                "Row %s (%s) was suitable but omitted a usable LaTeX CV. "
                "Requesting a repair response.",
                record.row_number,
                record.display_name,
            )
            retry_prompt = build_missing_cv_retry_prompt(
                master_prompt,
                record.advertisement,
                latex_cv,
                response_text,
            )
            retry_response_text = self.call_openai(retry_prompt, record)
            evaluation.tailored_cv = extract_latex_cv_from_response(retry_response_text)

        if evaluation.verdict == "Suitable" and not looks_like_latex_cv(
            evaluation.tailored_cv
        ):
            return JobEvaluation(
                row_number=record.row_number,
                verdict="Error",
                fit_score=None,
                reason=evaluation.reason,
                raw_verdict=evaluation.raw_verdict,
                evaluated_at=evaluation.evaluated_at,
                model=self.model,
                error=(
                    "Suitable response omitted a usable tailored LaTeX CV after retry."
                ),
            )

        if looks_like_latex_cv(evaluation.tailored_cv):
            evaluation.tailored_cv = enforce_protected_cv_sections(
                evaluation.tailored_cv,
                latex_cv,
            )
        return evaluation

    def call_openai(self, prompt: str, record: JobRecord) -> str:
        """Call OpenAI with retries and return non-empty response text."""
        attempts = self.retries + 1
        last_error: Exception | None = None

        for attempt in range(1, attempts + 1):
            try:
                response = self.client.responses.create(
                    model=self.model,
                    instructions=STRICT_OUTPUT_INSTRUCTIONS,
                    input=prompt,
                    max_output_tokens=self.max_output_tokens,
                )
                response_text = get_response_text(response)
                if not response_text:
                    raise EvaluationError("OpenAI returned an empty response.")
                return response_text
            except Exception as exc:
                last_error = exc
                if is_openai_quota_error(exc):
                    raise OpenAIQuotaError(
                        "OpenAI reported insufficient_quota. Add billing/credits "
                        "to the OpenAI API project, then run the evaluator again."
                    ) from exc

                retryable = is_retryable_openai_error(exc)
                if attempt >= attempts or not retryable:
                    break

                delay = retry_after_seconds(exc)
                if delay is None:
                    delay = min(self.max_delay, self.base_delay * (2 ** (attempt - 1)))
                    delay += random.uniform(0, 0.75)

                LOGGER.warning(
                    "OpenAI API issue for row %s (%s), attempt %s/%s: %s. "
                    "Retrying in %.1fs.",
                    record.row_number,
                    record.display_name,
                    attempt,
                    attempts,
                    exc,
                    delay,
                )
                time.sleep(delay)

        raise EvaluationError(
            f"OpenAI API failed after {attempts} attempt(s): {last_error}"
        )


def batch_items(items: list[JobRecord], batch_size: int) -> list[list[JobRecord]]:
    """Split job records into fixed-size batches."""
    return [items[idx : idx + batch_size] for idx in range(0, len(items), batch_size)]


def evaluate_records(
    records: list[JobRecord],
    *,
    evaluator: OpenAIJobEvaluator,
    master_prompt: str,
    latex_cv: str,
    concurrency: int,
    batch_size: int,
    large_queue_threshold: int = 200,
    large_queue_sleep_ms: int = 2000,
    on_evaluation: Callable[[JobEvaluation], None] | None = None,
) -> dict[int, JobEvaluation]:
    """Evaluate queued records in batches with bounded concurrency."""
    results: dict[int, JobEvaluation] = {}
    if not records:
        return results

    batches = batch_items(records, batch_size)
    completed = 0
    request_pacer: RequestPacer | None = None
    if large_queue_sleep_ms > 0 and len(records) > large_queue_threshold:
        delay_seconds = large_queue_sleep_ms / 1000
        request_pacer = RequestPacer(delay_seconds)
        LOGGER.info(
            "Large queue pacing enabled: %sms between OpenAI request starts "
            "because %s queued row(s) exceed the %s-row threshold.",
            large_queue_sleep_ms,
            len(records),
            large_queue_threshold,
        )

    def evaluate_record(record: JobRecord) -> JobEvaluation:
        if request_pacer is not None:
            request_pacer.wait()
        return evaluator.evaluate(record, master_prompt, latex_cv)

    for batch_idx, batch in enumerate(batches, start=1):
        LOGGER.info(
            "Evaluating batch %s/%s (%s job(s)) ...",
            batch_idx,
            len(batches),
            len(batch),
        )
        max_workers = min(max(1, concurrency), len(batch))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(evaluate_record, record): record for record in batch
            }
            for future in as_completed(futures):
                record = futures[future]
                try:
                    evaluation = future.result()
                except OpenAIQuotaError:
                    for pending_future in futures:
                        pending_future.cancel()
                    raise
                except EvaluationError as exc:
                    evaluation = JobEvaluation(
                        row_number=record.row_number,
                        verdict="Error",
                        fit_score=None,
                        reason="",
                        evaluated_at=datetime.now(UTC).strftime(
                            "%Y-%m-%d %H:%M:%S UTC"
                        ),
                        model=evaluator.model,
                        error=str(exc),
                    )

                results[record.row_number] = evaluation
                if on_evaluation is not None:
                    try:
                        on_evaluation(evaluation)
                    except Exception:
                        for pending_future in futures:
                            pending_future.cancel()
                        raise
                completed += 1
                score = (
                    f"{evaluation.fit_score}%"
                    if evaluation.fit_score is not None
                    else "n/a"
                )
                LOGGER.info(
                    "[%s/%s] Row %s (%s): %s, score %s",
                    completed,
                    len(records),
                    record.row_number,
                    record.display_name,
                    evaluation.verdict,
                    score,
                )

    return results
