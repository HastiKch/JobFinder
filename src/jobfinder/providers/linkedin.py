"""LinkedIn provider integration for ``curious_coder/linkedin-jobs-scraper``."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from jobfinder.scraper.settings import ScraperSettings


def build_search_url(settings: ScraperSettings, keyword: str) -> str:
    """Build a LinkedIn job-search URL for one keyword."""
    params = {
        "keywords": keyword,
        "location": settings.location,
        "geoId": settings.geo_id,
        "f_E": ",".join(settings.experience_levels),
        "f_JT": ",".join(settings.contract_types),
        "position": "1",
        "pageNum": "0",
    }
    if settings.published_at:
        params["f_TPR"] = settings.published_at

    return f"https://www.linkedin.com/jobs/search/?{urlencode(params)}"


def build_actor_input(settings: ScraperSettings, search_url: str) -> dict[str, Any]:
    """Build the Apify actor payload for LinkedIn searches."""
    payload = {
        "urls": [search_url],
        "count": settings.max_results_per_search,
        "scrapeCompany": settings.scrape_company_details,
        "useIncognitoMode": settings.use_incognito_mode,
        "splitByLocation": settings.split_by_location,
    }
    if settings.split_by_location:
        payload["splitCountry"] = settings.split_country
    return payload


def build_batch_actor_input(
    settings: ScraperSettings, search_urls: list[str]
) -> dict[str, Any]:
    """Build a LinkedIn actor payload containing multiple search URLs."""
    payload = build_actor_input(settings, search_urls[0])
    payload["urls"] = search_urls
    payload["count"] = settings.max_results_per_search * len(search_urls)
    return payload


__all__ = [
    "build_actor_input",
    "build_batch_actor_input",
    "build_search_url",
]
