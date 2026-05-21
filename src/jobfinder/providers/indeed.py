"""Indeed provider integration for ``valig/indeed-jobs-scraper``."""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlparse

from jobfinder.providers.apify_client import run_actor
from jobfinder.providers.normalization import (
    clean_scalar_text,
    first_text,
    nested_text,
    unique,
    values_from_shape,
)
from jobfinder.scraper.settings import ScraperSettings

INDEED_DOMAIN_BY_COUNTRY = {
    "us": "www.indeed.com",
    "gb": "uk.indeed.com",
    "uk": "uk.indeed.com",
    "de": "de.indeed.com",
    "at": "at.indeed.com",
    "ch": "ch.indeed.com",
    "fr": "fr.indeed.com",
    "nl": "nl.indeed.com",
    "it": "it.indeed.com",
    "es": "es.indeed.com",
    "ca": "ca.indeed.com",
    "au": "au.indeed.com",
}
INDEED_MAX_LIMIT = 1000
INDEED_DATE_POSTED_DAYS = (1, 3, 7, 14)
INDEED_RESULT_RUNNER = Callable[
    [ScraperSettings, str, dict[str, Any], int],
    list[dict[str, Any]],
]

BENEFIT_WORDS = (
    "insurance",
    "leave",
    "paid time",
    "pto",
    "benefit",
    "retirement",
    "401",
    "pension",
    "stock",
    "wellness",
    "commuter",
    "dental",
    "vision",
    "health",
)
EDUCATION_WORDS = (
    "degree",
    "bachelor",
    "master",
    "phd",
    "doctorate",
    "diploma",
    "certification",
)
SENIORITY_WORDS = (
    "intern",
    "entry",
    "junior",
    "mid",
    "senior",
    "lead",
    "principal",
    "staff",
    "director",
    "manager",
)
PROGRAMMING_LANGUAGE_WORDS = {
    "python",
    "sql",
    "java",
    "javascript",
    "typescript",
    "r",
    "c++",
    "c#",
    "scala",
    "go",
    "rust",
    "matlab",
    "kotlin",
    "swift",
    "php",
}
SKILL_WORDS = PROGRAMMING_LANGUAGE_WORDS | {
    "analytics",
    "analysis",
    "aws",
    "azure",
    "bigquery",
    "communication",
    "data",
    "docker",
    "excel",
    "gis",
    "kubernetes",
    "machine learning",
    "power bi",
    "spark",
    "tableau",
}


@dataclass(frozen=True)
class IndeedActorInput:
    """Typed input for the new Indeed Apify actor."""

    country: str
    title: str
    location: str
    limit: int
    date_posted: str = ""

    def as_payload(self) -> dict[str, Any]:
        """Return the JSON payload accepted by the Apify actor."""
        payload: dict[str, Any] = {
            "country": self.country,
            "title": self.title,
            "location": self.location,
            "limit": self.limit,
        }
        if self.date_posted:
            payload["datePosted"] = self.date_posted
        return payload


@dataclass(frozen=True)
class IndeedMetadata:
    """Structured Indeed metadata kept inside the normalized job dict."""

    salary: str = ""
    benefits: tuple[str, ...] = ()
    skills: tuple[str, ...] = ()
    programming_languages: tuple[str, ...] = ()
    remote_work: str = ""
    seniority: str = ""
    experience_requirements: tuple[str, ...] = ()
    education_requirements: tuple[str, ...] = ()
    employer_rating: str = ""
    company_size: str = ""
    industry: str = ""

    def as_dict(self) -> dict[str, Any]:
        """Return only populated metadata values."""
        values: dict[str, Any] = {}
        for key, value in self.__dict__.items():
            if value:
                values[key] = list(value) if isinstance(value, tuple) else value
        return values

    def description_lines(self) -> list[str]:
        """Return concise metadata lines that improve evaluator context."""
        lines: list[str] = []
        scalar_fields = (
            ("Salary", self.salary),
            ("Work mode", self.remote_work),
            ("Seniority", self.seniority),
            ("Employer rating", self.employer_rating),
            ("Company size", self.company_size),
            ("Industry", self.industry),
        )
        for label, value in scalar_fields:
            if value:
                lines.append(f"{label}: {value}")

        collection_fields = (
            ("Skills", self.skills),
            ("Programming languages", self.programming_languages),
            ("Experience", self.experience_requirements),
            ("Education", self.education_requirements),
            ("Benefits", self.benefits),
        )
        for label, values in collection_fields:
            if values:
                lines.append(f"{label}: {', '.join(values)}")
        return lines


def base_url(settings: ScraperSettings) -> str:
    """Return the public Indeed base URL for the configured country."""
    country_key = settings.indeed_country.lower()
    domain = INDEED_DOMAIN_BY_COUNTRY.get(country_key, f"{country_key}.indeed.com")
    return f"https://{domain}"


def clamp_actor_limit(value: int) -> int:
    """Clamp requested result counts to the actor-supported range."""
    return min(INDEED_MAX_LIMIT, max(1, value))


def seconds_from_published_at(value: str) -> int | None:
    """Parse LinkedIn-style ``rSECONDS`` windows used by scraper settings."""
    text = (value or "").strip().casefold()
    if not text.startswith("r"):
        return None
    try:
        seconds = int(text[1:])
    except ValueError:
        return None
    return seconds if seconds > 0 else None


def date_posted_filter(settings: ScraperSettings) -> str:
    """Map scraper posted windows to Indeed's supported day buckets."""
    seconds = seconds_from_published_at(settings.published_at)
    if seconds is None:
        return ""

    days = max(1, math.ceil(seconds / 86_400))
    for supported_days in INDEED_DATE_POSTED_DAYS:
        if days <= supported_days:
            return str(supported_days)
    return ""


def build_actor_input(settings: ScraperSettings, keyword: str) -> dict[str, Any]:
    """Build the Apify actor payload for one Indeed keyword search."""
    actor_input = IndeedActorInput(
        country=settings.indeed_country.lower(),
        title=keyword,
        location=settings.indeed_location,
        limit=clamp_actor_limit(settings.indeed_max_results_per_search),
        date_posted=date_posted_filter(settings),
    )
    return actor_input.as_payload()


def run_actor_search(
    settings: ScraperSettings,
    actor_id: str,
    payload: dict[str, Any],
    max_items: int,
    *,
    actor_runner: INDEED_RESULT_RUNNER = run_actor,
) -> list[dict[str, Any]]:
    """Run the Indeed actor and normalize actor-specific output."""
    items = actor_runner(settings, actor_id, payload, max_items)
    return normalize_actor_output(items)


def normalize_actor_output(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize all actor items into the scraper's stable raw-job contract."""
    return [normalize_actor_item(item) for item in items if isinstance(item, dict)]


def normalize_actor_item(item: dict[str, Any]) -> dict[str, Any]:
    """Normalize one actor result into fields consumed by the shared pipeline."""
    job_key = indeed_job_key(item)
    metadata = build_metadata(item)
    indeed_url = first_text(item, "url", "link")
    external_apply_url = first_text(item, "jobUrl", "applyUrl")
    raw_employer = item.get("employer")
    employer: dict[str, Any] = raw_employer if isinstance(raw_employer, dict) else {}

    normalized = {
        "jobId": job_key,
        "job_id": job_key,
        "id": job_key,
        "indeedKey": job_key,
        "title": first_text(item, "title", "name"),
        "companyName": first_text(employer, "name", fallback=item.get("companyName")),
        "companyDetails": company_details(employer),
        "location": format_location(item.get("location")),
        "jobType": format_job_types(item),
        "employmentType": format_job_types(item),
        "description": description_with_metadata(item, metadata),
        "descriptionHtml": nested_text(item, "description", "html"),
        "postedAt": first_text(item, "datePublished", "dateOnIndeed", "postedAt"),
        "datePublished": first_text(item, "datePublished"),
        "dateOnIndeed": first_text(item, "dateOnIndeed"),
        "jobUrl": indeed_url,
        "url": indeed_url,
        "applyUrl": external_apply_url,
        "_jobfinder_indeed_metadata": metadata.as_dict(),
    }

    return {
        key: value
        for key, value in normalized.items()
        if value not in ("", None, {}, [])
    }


def indeed_job_key(item: dict[str, Any]) -> str:
    """Return the most stable Indeed-native job identifier."""
    job_key = first_text(item, "key", "jobKey", "jobId", "job_id", "id")
    if job_key:
        return job_key

    for url_key in ("url", "jobUrl", "link"):
        url = first_text(item, url_key)
        parsed_key = job_key_from_url(url)
        if parsed_key:
            return parsed_key
    return ""


def job_key_from_url(url: str) -> str:
    """Extract Indeed's ``jk`` value from a job URL."""
    if not url:
        return ""
    parsed = urlparse(url)
    values = parse_qs(parsed.query).get("jk", [])
    return values[0].strip() if values and values[0].strip() else ""


def company_details(employer: dict[str, Any]) -> dict[str, Any]:
    """Map employer details without exposing actor-specific key names downstream."""
    if not employer:
        return {}

    details: dict[str, Any] = {}
    for source_key, target_key in (
        ("name", "name"),
        ("industry", "industry"),
        ("employeesCount", "employeesCount"),
        ("ratingsValue", "ratingsValue"),
        ("ratingsCount", "ratingsCount"),
        ("relativeCompanyPageUrl", "relativeCompanyPageUrl"),
    ):
        value = employer.get(source_key)
        if value not in (None, "", [], {}):
            details[target_key] = value
    return details


def format_location(value: Any) -> str:
    """Normalize Indeed location objects into a concise display string."""
    if isinstance(value, dict):
        parts = [
            first_text(value, "city"),
            first_text(value, "admin1Code"),
            first_text(value, "countryName", "countryCode"),
        ]
        unique_parts = unique([part for part in parts if part])
        if unique_parts:
            return ", ".join(unique_parts)
        return first_text(value, "streetAddress", "formatted", "name")
    if value is None:
        return ""
    return clean_scalar_text(value)


def format_job_types(item: dict[str, Any]) -> str:
    """Return employment/job-type text from the actor's structured tags."""
    values = values_from_shape(item.get("jobTypes"))
    if not values:
        values = [
            value
            for value in values_from_shape(item.get("employerAttributes"))
            if is_job_type(value)
        ]
    return ", ".join(unique(values))


def format_salary(value: Any) -> str:
    """Normalize structured or text salary data into compact display text."""
    if isinstance(value, dict):
        min_value = parse_salary_number(value.get("minValue"))
        max_value = parse_salary_number(value.get("maxValue"))
        currency = first_text(value, "currencyCode")
        unit = salary_unit_label(first_text(value, "unitOfWork"))

        if min_value is not None and max_value is not None and min_value != max_value:
            amount = f"{format_money(min_value)}-{format_money(max_value)}"
        elif min_value is not None:
            amount = format_money(min_value)
        elif max_value is not None:
            amount = format_money(max_value)
        else:
            amount = ""

        if amount:
            prefix = f"{currency} " if currency else ""
            suffix = f" / {unit}" if unit else ""
            return f"{prefix}{amount}{suffix}"

    return ", ".join(unique(values_from_shape(value)))


def parse_salary_number(value: Any) -> float | None:
    """Parse numeric salary values from actor output."""
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        number = float(str(value).replace(",", "").strip())
    except ValueError:
        return None
    return number if number >= 0 else None


def format_money(value: float) -> str:
    """Format a salary number without unnecessary decimals."""
    if value.is_integer():
        return f"{int(value):,}"
    return f"{value:,.2f}".rstrip("0").rstrip(".")


def salary_unit_label(value: str) -> str:
    """Return a human-friendly salary period label."""
    unit = value.strip().casefold()
    return {
        "year": "year",
        "month": "month",
        "week": "week",
        "day": "day",
        "hour": "hour",
    }.get(unit, unit)


def build_metadata(item: dict[str, Any]) -> IndeedMetadata:
    """Extract richer actor metadata useful to evaluation and future filtering."""
    raw_employer = item.get("employer")
    employer: dict[str, Any] = raw_employer if isinstance(raw_employer, dict) else {}
    attributes = unique(values_from_shape(item.get("attributes")), limit=40)
    benefits = unique(values_from_shape(item.get("benefits")), limit=12)
    job_types = unique(values_from_shape(item.get("jobTypes")), limit=8)
    employer_attributes = unique(
        values_from_shape(item.get("employerAttributes")), limit=12
    )
    all_tags = unique([*attributes, *benefits, *job_types, *employer_attributes])

    education = unique([value for value in all_tags if is_education(value)], limit=5)
    experience = unique([value for value in all_tags if is_experience(value)], limit=5)
    seniority = first_matching(all_tags, is_seniority)
    remote_work = classify_remote_work(item, all_tags)
    skills = unique(
        [
            value
            for value in all_tags
            if is_skill(value)
            and not is_benefit(value)
            and not is_job_type(value)
            and not is_education(value)
            and not is_experience(value)
            and value != seniority
        ],
        limit=12,
    )
    programming_languages = unique(
        [value for value in skills if is_programming_language(value)],
        limit=6,
    )
    salary = (
        format_salary(item.get("baseSalary"))
        or format_salary(item.get("salary"))
        or format_salary(item.get("salaryText"))
    )

    return IndeedMetadata(
        salary=salary,
        benefits=benefits,
        skills=skills,
        programming_languages=programming_languages,
        remote_work=remote_work,
        seniority=seniority,
        experience_requirements=experience,
        education_requirements=education,
        employer_rating=format_employer_rating(employer),
        company_size=first_text(employer, "employeesCount"),
        industry=first_text(employer, "industry"),
    )


def description_with_metadata(
    item: dict[str, Any],
    metadata: IndeedMetadata,
) -> str:
    """Append concise structured Indeed metadata to the base description."""
    description = nested_text(item, "description", "text") or first_text(
        item,
        "description",
        "summary",
        "snippet",
    )
    metadata_lines = metadata.description_lines()
    if not metadata_lines:
        return description

    metadata_block = "\n".join(f"- {line}" for line in metadata_lines)
    if description:
        return f"{description}\n\nIndeed structured metadata:\n{metadata_block}"
    return f"Indeed structured metadata:\n{metadata_block}"


def format_employer_rating(employer: dict[str, Any]) -> str:
    """Return employer rating text when available."""
    rating = first_text(employer, "ratingsValue")
    if not rating:
        return ""
    count = first_text(employer, "ratingsCount")
    return f"{rating} ({count} reviews)" if count else rating


def first_matching(values: tuple[str, ...], predicate: Callable[[str], bool]) -> str:
    """Return the first value that matches a predicate."""
    for value in values:
        if predicate(value):
            return value
    return ""


def contains_word(value: str, words: tuple[str, ...] | set[str]) -> bool:
    """Return true when text contains one of the supplied words/phrases."""
    normalized = value.casefold()
    return any(word in normalized for word in words)


def is_benefit(value: str) -> bool:
    """Return true when a tag is likely a benefit."""
    return contains_word(value, BENEFIT_WORDS)


def is_education(value: str) -> bool:
    """Return true when a tag is likely an education requirement."""
    return contains_word(value, EDUCATION_WORDS)


def is_experience(value: str) -> bool:
    """Return true when a tag is likely an experience requirement."""
    text = value.casefold()
    return bool(re.search(r"\d+\+?\s+years?", text)) or "experience" in text


def is_job_type(value: str) -> bool:
    """Return true when a tag describes employment type."""
    text = value.casefold()
    return any(
        phrase in text
        for phrase in (
            "full-time",
            "part-time",
            "contract",
            "temporary",
            "internship",
            "permanent",
            "freelance",
        )
    )


def is_seniority(value: str) -> bool:
    """Return true when a tag describes seniority."""
    text = value.casefold()
    return "level" in text and contains_word(text, SENIORITY_WORDS)


def is_programming_language(value: str) -> bool:
    """Return true when a skill is a programming language."""
    normalized = value.casefold().strip()
    return normalized in PROGRAMMING_LANGUAGE_WORDS


def is_skill(value: str) -> bool:
    """Return true when a tag is useful skill metadata."""
    text = value.casefold()
    if text in PROGRAMMING_LANGUAGE_WORDS:
        return True
    return text.endswith(" skills") or contains_word(
        text,
        SKILL_WORDS - PROGRAMMING_LANGUAGE_WORDS,
    )


def classify_remote_work(item: dict[str, Any], tags: tuple[str, ...]) -> str:
    """Classify remote/hybrid/on-site hints from tags and location."""
    text = " ".join([format_location(item.get("location")), *tags]).casefold()
    if "hybrid" in text:
        return "Hybrid"
    if "remote" in text or "work from home" in text:
        return "Remote"
    if "on-site" in text or "on site" in text or "in-person" in text:
        return "On-site"
    return ""
