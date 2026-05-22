"""Canonical job merging for deterministic duplicate clusters."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from jobfinder.dedupe.models import NormalizedJob, Provenance
from jobfinder.dedupe.normalize import (
    KNOWN_SOURCE_LABELS,
    first_text,
    is_meaningful,
    source_key,
    unique_ordered,
)

SOURCE_ORDER = ("linkedin", "indeed", "stepstone")
SOURCE_ORDER_INDEX = {source: idx for idx, source in enumerate(SOURCE_ORDER)}
DESCRIPTION_FIELDS = (
    "descriptionText",
    "description_text",
    "jobDescriptionText",
    "job_description_text",
    "descriptionPlainText",
    "description_plain_text",
    "jobDescriptionPlainText",
    "job_description_plain_text",
    "jobDescription",
    "job_description",
    "description",
)


def source_sort_key(label: str) -> tuple[int, str]:
    """Sort source labels in stable product order."""
    key = source_key(label)
    if key in SOURCE_ORDER_INDEX:
        return SOURCE_ORDER_INDEX[key], label
    return len(SOURCE_ORDER), label.casefold()


def source_label_for_key(key: str) -> str:
    """Return a display label for a source key."""
    return KNOWN_SOURCE_LABELS.get(key) or key


def posted_sort_key(job: NormalizedJob) -> datetime:
    """Return a non-optional posted timestamp for already-filtered jobs."""
    if job.posted_at is None:
        raise ValueError("posted_sort_key requires a parseable posted_at value")
    return job.posted_at


def merge_keywords(jobs: list[NormalizedJob]) -> list[str]:
    """Merge matched keywords in first-seen order."""
    values: list[str] = []
    for job in jobs:
        values.extend(job.keywords)
    return list(unique_ordered(values))


def merge_source_labels(jobs: list[NormalizedJob]) -> tuple[str, list[str]]:
    """Return display App value and sorted platform labels."""
    labels = sorted(
        {job.source_label for job in jobs if job.source_label},
        key=source_sort_key,
    )
    return " | ".join(labels), labels


def richness_score(job: NormalizedJob) -> tuple[int, int, int]:
    """Score a raw job by useful completeness for base-record selection."""
    meaningful_fields = sum(1 for value in job.raw.values() if is_meaningful(value))
    return (len(job.description), meaningful_fields, -job.index)


def best_text(values: list[str], *, prefer_longer: bool = False) -> str:
    """Choose a deterministic best text field."""
    candidates = [
        (idx, value)
        for idx, value in enumerate(values)
        if is_meaningful(value)
    ]
    if not candidates:
        return ""
    if prefer_longer:
        return max(candidates, key=lambda item: (len(item[1]), -item[0]))[1]
    return max(
        candidates,
        key=lambda item: (len(item[1].split()), len(item[1]), -item[0]),
    )[1]


def best_description(jobs: list[NormalizedJob]) -> str:
    """Prefer the richest description across duplicate providers."""
    descriptions: list[str] = []
    for job in jobs:
        for field in DESCRIPTION_FIELDS:
            value = job.raw.get(field)
            if isinstance(value, str) and is_meaningful(value):
                descriptions.append(value.strip())
        if job.description:
            descriptions.append(job.description)
    return best_text(descriptions, prefer_longer=True)


def best_url(provenance: list[Provenance], attr: str) -> str:
    """Pick a stable primary URL while preserving all URLs in provenance."""
    candidates = [
        (source_sort_key(item.label), getattr(item, attr))
        for item in provenance
        if is_meaningful(getattr(item, attr))
    ]
    if not candidates:
        return ""
    return min(candidates, key=lambda item: item[0])[1]


def best_apply_url(provenance: list[Provenance]) -> str:
    """Prefer external ATS apply URLs over provider-owned apply URLs."""
    external = [
        item.apply_url
        for item in provenance
        if item.apply_url and item.apply_url_key and is_meaningful(item.apply_url)
    ]
    if external:
        return external[0]
    return best_url(provenance, "apply_url")


def merge_dicts_by_richness(values: list[Any]) -> dict[str, Any]:
    """Merge nested metadata dictionaries without random overwrites."""
    result: dict[str, Any] = {}
    for value in sorted(
        [item for item in values if isinstance(item, dict)],
        key=len,
    ):
        for key, nested_value in value.items():
            if not is_meaningful(nested_value):
                continue
            if key not in result or not is_meaningful(result[key]):
                result[key] = nested_value
            elif isinstance(result[key], list) and isinstance(nested_value, list):
                result[key] = list(unique_ordered([*result[key], *nested_value]))
            elif isinstance(result[key], dict) and isinstance(nested_value, dict):
                result[key] = merge_dicts_by_richness([result[key], nested_value])
    return result


def unique_provenance(jobs: list[NormalizedJob]) -> list[Provenance]:
    """Collapse repeated keyword hits for the same provider job into one record."""
    by_key: dict[tuple[str, str, str], Provenance] = {}
    for job in jobs:
        provenance = job.provenance
        key = (
            provenance.source,
            provenance.job_id.casefold(),
            provenance.job_url_key or provenance.apply_url_key,
        )
        if key not in by_key:
            by_key[key] = provenance
            continue
        existing = by_key[key]
        by_key[key] = Provenance(
            source=existing.source,
            label=existing.label,
            job_id=existing.job_id or provenance.job_id,
            job_url=existing.job_url or provenance.job_url,
            job_url_key=existing.job_url_key or provenance.job_url_key,
            apply_url=existing.apply_url or provenance.apply_url,
            apply_url_key=existing.apply_url_key or provenance.apply_url_key,
            company_url=existing.company_url or provenance.company_url,
            company_url_key=existing.company_url_key or provenance.company_url_key,
            title=existing.title or provenance.title,
            company=existing.company or provenance.company,
            location=existing.location or provenance.location,
            keywords=unique_ordered([*existing.keywords, *provenance.keywords]),
        )
    return sorted(by_key.values(), key=lambda item: source_sort_key(item.label))


def best_posted(jobs: list[NormalizedJob]) -> str:
    """Choose the newest parseable posted date, falling back to provider text."""
    parseable = [job for job in jobs if job.posted_at is not None]
    if parseable:
        newest = max(parseable, key=posted_sort_key)
        for key in (
            "postedAt",
            "publishedAt",
            "datePublished",
            "dateOnIndeed",
            "datePosted",
            "pubDate",
        ):
            value = newest.raw.get(key)
            if is_meaningful(value):
                return str(value)
    return first_text(
        max(jobs, key=richness_score).raw,
        "postedAt",
        "publishedAt",
        "datePublished",
        "dateOnIndeed",
        "datePosted",
        "pubDate",
    )


def merge_cluster(jobs: list[NormalizedJob]) -> dict[str, Any]:
    """Merge duplicate provider rows into one canonical job dictionary."""
    if not jobs:
        return {}

    base = max(jobs, key=richness_score)
    merged = dict(base.raw)
    provenance = unique_provenance(jobs)
    app_value, platform_labels = merge_source_labels(jobs)
    description = best_description(jobs)
    title = best_text([job.title for job in jobs]) or base.title
    company = best_text([job.company for job in jobs]) or base.company
    location = best_text([job.location for job in jobs]) or base.location
    job_type = best_text([job.job_type for job in jobs]) or base.job_type
    job_url = best_url(provenance, "job_url")
    apply_url = best_apply_url(provenance)
    posted = best_posted(jobs)

    merged.update(
        {
            "_source": "|".join(
                sorted(
                    {job.source for job in jobs},
                    key=lambda key: source_sort_key(source_label_for_key(key)),
                )
            ),
            "_source_label": app_value,
            "title": title,
            "companyName": company,
            "location": location,
            "keywords_matched": merge_keywords(jobs),
            "_jobfinder_provenance": [item.as_dict() for item in provenance],
            "_jobfinder_dedupe": {
                "platforms": platform_labels,
                "source_count": len(platform_labels),
                "input_rows": len(jobs),
                "profile_key": base.profile_key,
            },
        }
    )
    if job_type:
        merged["jobType"] = job_type
        merged["employmentType"] = job_type
    if description:
        merged["description"] = description
        merged["descriptionText"] = description
    if job_url:
        merged["jobUrl"] = job_url
        merged["url"] = job_url
    if apply_url:
        merged["applyUrl"] = apply_url
    if posted:
        merged["postedAt"] = posted

    company_details = merge_dicts_by_richness(
        [job.raw.get("companyDetails") for job in jobs]
    )
    if company_details:
        merged["companyDetails"] = company_details

    for metadata_key in ("_jobfinder_indeed_metadata", "_jobfinder_stepstone_metadata"):
        metadata = merge_dicts_by_richness([job.raw.get(metadata_key) for job in jobs])
        if metadata:
            merged[metadata_key] = metadata

    salaries = [job.salary for job in jobs if job.salary.raw]
    if salaries:
        best_salary = max(
            salaries,
            key=lambda salary: (
                salary.minimum is not None,
                salary.maximum is not None,
                len(salary.raw),
            ),
        )
        merged["_jobfinder_salary"] = {
            key: value
            for key, value in {
                "raw": best_salary.raw,
                "minimum": best_salary.minimum,
                "maximum": best_salary.maximum,
                "currency": best_salary.currency,
                "period": best_salary.period,
            }.items()
            if value not in ("", None)
        }

    return merged
