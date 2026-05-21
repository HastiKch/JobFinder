"""Provider adapter registry used by scraper orchestration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from jobfinder.providers import indeed, linkedin, stepstone
from jobfinder.scraper.settings import ScraperSettings

ActorRunner = Callable[
    [ScraperSettings, str, dict[str, Any], int],
    list[dict[str, Any]],
]
ActorInputBuilder = Callable[[ScraperSettings, str], dict[str, Any]]
DirectActorInputBuilder = Callable[[ScraperSettings], dict[str, Any]]


@dataclass(frozen=True)
class ProviderAdapter:
    """Provider-specific behavior needed by generic scraper orchestration."""

    source: str
    build_actor_input: ActorInputBuilder
    run_actor_search: Callable[
        [ScraperSettings, str, dict[str, Any], int, ActorRunner],
        list[dict[str, Any]],
    ]
    build_direct_actor_input: DirectActorInputBuilder | None = None

    def build_direct_input(self, settings: ScraperSettings) -> dict[str, Any]:
        """Build a direct-URL payload for providers that support it."""
        if self.build_direct_actor_input is None:
            raise ValueError(f"{self.source} does not support direct actor inputs.")
        return self.build_direct_actor_input(settings)


def build_linkedin_actor_input(
    settings: ScraperSettings,
    keyword: str,
) -> dict[str, Any]:
    """Build a LinkedIn actor payload from a keyword."""
    search_url = linkedin.build_search_url(settings, keyword)
    return linkedin.build_actor_input(settings, search_url)


def run_default_actor_search(
    settings: ScraperSettings,
    actor_id: str,
    payload: dict[str, Any],
    max_items: int,
    actor_runner: ActorRunner,
) -> list[dict[str, Any]]:
    """Run a provider that needs no source-specific output conversion."""
    return actor_runner(settings, actor_id, payload, max_items)


def run_indeed_actor_search(
    settings: ScraperSettings,
    actor_id: str,
    payload: dict[str, Any],
    max_items: int,
    actor_runner: ActorRunner,
) -> list[dict[str, Any]]:
    """Run Indeed and normalize actor-specific output."""
    return indeed.run_actor_search(
        settings,
        actor_id,
        payload,
        max_items,
        actor_runner=actor_runner,
    )


def run_stepstone_actor_search(
    settings: ScraperSettings,
    actor_id: str,
    payload: dict[str, Any],
    max_items: int,
    actor_runner: ActorRunner,
) -> list[dict[str, Any]]:
    """Run Stepstone and normalize actor-specific output."""
    return stepstone.run_actor_search(
        settings,
        actor_id,
        payload,
        max_items,
        actor_runner=actor_runner,
    )


PROVIDER_ADAPTERS: dict[str, ProviderAdapter] = {
    "linkedin": ProviderAdapter(
        source="linkedin",
        build_actor_input=build_linkedin_actor_input,
        run_actor_search=run_default_actor_search,
    ),
    "indeed": ProviderAdapter(
        source="indeed",
        build_actor_input=indeed.build_actor_input,
        run_actor_search=run_indeed_actor_search,
    ),
    "stepstone": ProviderAdapter(
        source="stepstone",
        build_actor_input=stepstone.build_actor_input,
        build_direct_actor_input=stepstone.build_direct_actor_input,
        run_actor_search=run_stepstone_actor_search,
    ),
}


def provider_adapter(source: str) -> ProviderAdapter:
    """Return the registered provider adapter for a source key."""
    try:
        return PROVIDER_ADAPTERS[source]
    except KeyError as exc:
        raise ValueError(f"Unknown job source: {source}") from exc
