"""Deterministic cross-provider duplicate matching pipeline."""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

from jobfinder.dedupe.merge import merge_cluster
from jobfinder.dedupe.models import DedupeResult, MatchDecision, NormalizedJob
from jobfinder.dedupe.normalize import normalize_job
from jobfinder.dedupe.scoring import (
    company_similarity,
    conflicting_role_family,
    conflicting_seniority,
    job_type_similarity,
    location_similarity,
    posted_time_similarity,
    title_similarity,
)

LOGGER = logging.getLogger("jobfinder.dedupe")
COMPANY_MATCH_THRESHOLD = 0.90
TITLE_MATCH_THRESHOLD = 0.82
LOCATION_MATCH_THRESHOLD = 0.82
JOB_TYPE_MATCH_THRESHOLD = 0.70
POSTED_TIME_MATCH_THRESHOLD = 0.55
MATCH_THRESHOLD = 0.88


def identity_blockers(left: NormalizedJob, right: NormalizedJob) -> list[str]:
    """Return deterministic contradictions in the allowed identity cells."""
    blockers: list[str] = []
    if conflicting_seniority(left, right):
        blockers.append("conflicting title seniority")
    if conflicting_role_family(left, right):
        blockers.append("conflicting role family")
    return blockers


def allowed_cell_scores(left: NormalizedJob, right: NormalizedJob) -> dict[str, float]:
    """Score only title, company, location, job type, and post time."""
    return {
        "company": company_similarity(left, right),
        "title": title_similarity(left, right),
        "location": location_similarity(left, right),
        "job_type": job_type_similarity(left, right),
        "posted_time": posted_time_similarity(left, right),
    }


def weighted_confidence(scores: dict[str, float]) -> float:
    """Return a compact confidence from the allowed identity cells only."""
    return (
        (0.30 * scores["company"])
        + (0.34 * scores["title"])
        + (0.18 * scores["location"])
        + (0.10 * scores["job_type"])
        + (0.08 * scores["posted_time"])
    )


def similarity_blockers(scores: dict[str, float]) -> list[str]:
    """Return threshold misses for the allowed identity cells."""
    blockers: list[str] = []
    if scores["company"] < COMPANY_MATCH_THRESHOLD:
        blockers.append("company similarity below threshold")
    if scores["title"] < TITLE_MATCH_THRESHOLD:
        blockers.append("title similarity below threshold")
    if scores["location"] < LOCATION_MATCH_THRESHOLD:
        blockers.append("location similarity below threshold")
    if scores["job_type"] < JOB_TYPE_MATCH_THRESHOLD:
        blockers.append("job type similarity below threshold")
    if scores["posted_time"] < POSTED_TIME_MATCH_THRESHOLD:
        blockers.append("post time similarity below threshold")
    return blockers


def same_apply_link_match(
    left: NormalizedJob, right: NormalizedJob
) -> MatchDecision | None:
    """Use the external company apply link as the only URL-based strong signal."""
    if not left.apply_url_key or left.apply_url_key != right.apply_url_key:
        return None

    scores = allowed_cell_scores(left, right)
    blockers = [*identity_blockers(left, right), *similarity_blockers(scores)]
    if blockers:
        return MatchDecision(
            left.index,
            right.index,
            False,
            weighted_confidence(scores),
            "blocked",
            tuple(f"{name}={score:.2f}" for name, score in scores.items()),
            tuple(blockers),
        )

    return MatchDecision(
        left.index,
        right.index,
        True,
        0.99,
        "company_apply_link",
        ("same canonical external company apply link",),
    )


def exact_allowed_cells_match(
    left: NormalizedJob, right: NormalizedJob
) -> MatchDecision | None:
    """Match exact normalized company, title, location, and compatible metadata."""
    if not left.profile_key or left.profile_key != right.profile_key:
        return None

    scores = allowed_cell_scores(left, right)
    blockers = [*identity_blockers(left, right), *similarity_blockers(scores)]
    if blockers:
        return MatchDecision(
            left.index,
            right.index,
            False,
            weighted_confidence(scores),
            "blocked",
            tuple(f"{name}={score:.2f}" for name, score in scores.items()),
            tuple(blockers),
        )

    return MatchDecision(
        left.index,
        right.index,
        True,
        0.96,
        "exact_allowed_cells",
        ("same normalized company, title, location, job type, and post time",),
    )


def scored_allowed_cells_match(
    left: NormalizedJob, right: NormalizedJob
) -> MatchDecision:
    """Score possible duplicates using only the allowed identity cells."""
    scores = allowed_cell_scores(left, right)
    confidence = weighted_confidence(scores)
    reasons = tuple(f"{name}={score:.2f}" for name, score in scores.items())
    blockers = [*identity_blockers(left, right), *similarity_blockers(scores)]
    if confidence < MATCH_THRESHOLD:
        blockers.append("overall allowed-cell confidence below threshold")

    return MatchDecision(
        left.index,
        right.index,
        not blockers,
        confidence,
        "allowed_cell_score",
        reasons,
        tuple(blockers),
    )


def evaluate_match(left: NormalizedJob, right: NormalizedJob) -> MatchDecision:
    """Run the compact deterministic matching stages for a pair."""
    apply_match = same_apply_link_match(left, right)
    if apply_match is not None:
        return apply_match
    exact_match = exact_allowed_cells_match(left, right)
    if exact_match is not None:
        return exact_match
    return scored_allowed_cells_match(left, right)


def best_cluster_match(
    job: NormalizedJob,
    cluster: list[NormalizedJob],
) -> MatchDecision:
    """Return the best pairwise decision between a job and a cluster."""
    decisions = [evaluate_match(job, existing) for existing in cluster]
    matched = [decision for decision in decisions if decision.matched]
    if matched:
        return max(matched, key=lambda decision: decision.confidence)
    return max(decisions, key=lambda decision: decision.confidence)


def flatten_search_results(
    all_results: list[tuple[str, list[dict[str, Any]]]],
) -> list[NormalizedJob]:
    """Flatten keyword search output and precompute matching features."""
    normalized: list[NormalizedJob] = []
    index = 0
    for keyword, jobs in all_results:
        for job in jobs:
            normalized.append(normalize_job(job, keyword=keyword, index=index))
            index += 1
    return normalized


def deduplicate_search_results(
    all_results: list[tuple[str, list[dict[str, Any]]]],
    *,
    include_debug: bool = False,
) -> DedupeResult:
    """Deduplicate scraped jobs using indexed deterministic matching."""
    clusters: list[list[NormalizedJob]] = []
    blocking_index: dict[str, set[int]] = defaultdict(set)
    decisions: list[MatchDecision] = []

    for job in flatten_search_results(all_results):
        candidate_cluster_ids: set[int] = set()
        for key in job.blocking_keys:
            candidate_cluster_ids.update(blocking_index.get(key, ()))

        best_decision: MatchDecision | None = None
        best_cluster_id: int | None = None
        for cluster_id in sorted(candidate_cluster_ids):
            decision = best_cluster_match(job, clusters[cluster_id])
            decisions.append(decision)
            if include_debug and not decision.matched:
                LOGGER.debug(
                    "Not merging job %s with cluster %s: confidence=%.2f "
                    "stage=%s blockers=%s reasons=%s",
                    job.index,
                    cluster_id,
                    decision.confidence,
                    decision.stage,
                    "; ".join(decision.blockers),
                    "; ".join(decision.reasons),
                )
            if not decision.matched:
                continue
            if best_decision is None or decision.confidence > best_decision.confidence:
                best_decision = decision
                best_cluster_id = cluster_id

        if best_cluster_id is None:
            cluster_id = len(clusters)
            clusters.append([job])
        else:
            cluster_id = best_cluster_id
            clusters[cluster_id].append(job)
            if best_decision is not None:
                LOGGER.debug(
                    "Merged job %s into cluster %s: confidence=%.2f "
                    "stage=%s reasons=%s",
                    job.index,
                    cluster_id,
                    best_decision.confidence,
                    best_decision.stage,
                    "; ".join(best_decision.reasons),
                )

        for key in job.blocking_keys:
            blocking_index[key].add(cluster_id)

    jobs = [merge_cluster(cluster) for cluster in clusters]
    return DedupeResult(
        jobs=jobs,
        decisions=decisions,
        input_count=sum(len(jobs) for _, jobs in all_results),
        output_count=len(jobs),
    )
