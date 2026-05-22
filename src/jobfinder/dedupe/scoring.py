"""Deterministic scoring for the small job-identity surface."""

from __future__ import annotations

from difflib import SequenceMatcher

from jobfinder.dedupe.models import NormalizedJob

SENIORITY_TOKENS = {
    "intern",
    "junior",
    "jr",
    "senior",
    "sr",
    "lead",
    "principal",
    "staff",
    "head",
    "director",
    "manager",
}
ROLE_FAMILY_TOKENS = {
    "administrator",
    "analyst",
    "analytics",
    "architect",
    "consultant",
    "developer",
    "engineer",
    "manager",
    "scientist",
    "specialist",
}


def sequence_similarity(left: str, right: str) -> float:
    """Return a deterministic normalized string similarity."""
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    return SequenceMatcher(None, left, right).ratio()


def token_overlap(left: frozenset[str], right: frozenset[str]) -> float:
    """Return Jaccard token overlap."""
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def blended_text_similarity(
    left_text: str,
    right_text: str,
    left_tokens: frozenset[str],
    right_tokens: frozenset[str],
) -> float:
    """Blend sequence and token overlap for compact explainable matching."""
    if left_text == right_text and left_text:
        return 1.0
    return max(
        sequence_similarity(left_text, right_text),
        (0.65 * token_overlap(left_tokens, right_tokens))
        + (0.35 * sequence_similarity(left_text, right_text)),
    )


def company_similarity(left: NormalizedJob, right: NormalizedJob) -> float:
    """Score normalized company similarity."""
    return blended_text_similarity(
        left.normalized_company,
        right.normalized_company,
        left.company_tokens,
        right.company_tokens,
    )


def title_similarity(left: NormalizedJob, right: NormalizedJob) -> float:
    """Score normalized title similarity."""
    return blended_text_similarity(
        left.normalized_title,
        right.normalized_title,
        left.title_tokens,
        right.title_tokens,
    )


def location_similarity(left: NormalizedJob, right: NormalizedJob) -> float:
    """Score normalized location compatibility."""
    if not left.normalized_location or not right.normalized_location:
        return 0.75
    if left.normalized_location == right.normalized_location:
        return 1.0
    if (
        left.location_tokens
        and right.location_tokens
        and (
            left.location_tokens <= right.location_tokens
            or right.location_tokens <= left.location_tokens
        )
    ):
        return 0.92
    if left.remote_mode and right.remote_mode and left.remote_mode == right.remote_mode:
        return 0.82
    return blended_text_similarity(
        left.normalized_location,
        right.normalized_location,
        left.location_tokens,
        right.location_tokens,
    )


def job_type_similarity(left: NormalizedJob, right: NormalizedJob) -> float:
    """Score job-type compatibility, tolerating missing provider data."""
    if not left.normalized_job_type or not right.normalized_job_type:
        return 0.75
    return blended_text_similarity(
        left.normalized_job_type,
        right.normalized_job_type,
        left.job_type_tokens,
        right.job_type_tokens,
    )


def posted_time_similarity(left: NormalizedJob, right: NormalizedJob) -> float:
    """Score posting time proximity, tolerating missing provider data."""
    if left.posted_at is None or right.posted_at is None:
        return 0.75
    days = abs((left.posted_at - right.posted_at).total_seconds()) / 86_400
    if days <= 3:
        return 1.0
    if days <= 14:
        return 0.85
    if days <= 45:
        return 0.55
    return 0.0


def conflicting_seniority(left: NormalizedJob, right: NormalizedJob) -> bool:
    """Return true when role seniority clearly differs."""
    left_tokens = left.title_tokens & SENIORITY_TOKENS
    right_tokens = right.title_tokens & SENIORITY_TOKENS
    if not left_tokens or not right_tokens:
        return False
    junior = {"intern", "junior", "jr"}
    senior = {"senior", "sr", "lead", "principal", "staff", "head", "director"}
    return bool(
        (left_tokens & junior and right_tokens & senior)
        or (right_tokens & junior and left_tokens & senior)
    )


def conflicting_role_family(left: NormalizedJob, right: NormalizedJob) -> bool:
    """Return true for titles that share weak words but name different roles."""
    left_family = left.title_tokens & ROLE_FAMILY_TOKENS
    right_family = right.title_tokens & ROLE_FAMILY_TOKENS
    if not left_family or not right_family:
        return False
    return left_family.isdisjoint(right_family)
