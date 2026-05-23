"""Compatibility wrapper for the Xing provider."""

from __future__ import annotations

from jobfinder.providers.xing import (
    XING_BASE_URL,
    XingActorInput,
    XingMetadata,
    absolute_xing_url,
    build_actor_input,
    build_direct_actor_input,
    build_metadata,
    normalize_actor_item,
    normalize_actor_output,
    run_actor_search,
    xing_job_key,
)

__all__ = [
    "XING_BASE_URL",
    "XingActorInput",
    "XingMetadata",
    "absolute_xing_url",
    "build_actor_input",
    "build_direct_actor_input",
    "build_metadata",
    "normalize_actor_item",
    "normalize_actor_output",
    "run_actor_search",
    "xing_job_key",
]
