"""Helpers for loading user-editable scraper configuration files."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from jobfinder.paths import FILTERS_FILE, KEYWORDS_FILE

LOGGER = logging.getLogger(__name__)


class ConfigFileError(RuntimeError):
    """Raised when a required user-editable config file is missing or invalid."""


def load_keywords(path: Path = KEYWORDS_FILE) -> list[str]:
    """Load search keywords from a text file, ignoring blanks and comments."""
    if not path.exists():
        raise ConfigFileError(
            f"Missing {path.name}. Add one keyword per line in that file."
        )

    keywords = []
    for line in path.read_text(encoding="utf-8").splitlines():
        keyword = line.strip()
        if keyword and not keyword.startswith("#"):
            keywords.append(keyword)

    if not keywords:
        raise ConfigFileError(f"{path.name} does not contain any keywords.")

    return keywords


def load_filter_config(path: Path = FILTERS_FILE) -> dict[str, Any]:
    """Load JSON filter configuration from disk."""
    if not path.exists():
        raise ConfigFileError(
            f"Missing {path.name}. Add search and final filter settings there."
        )

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigFileError(f"{path.name} is not valid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise ConfigFileError(f"{path.name} must contain a JSON object.")

    return data


def config_section(config: dict[str, Any], section: str) -> dict[str, Any]:
    """Return a named object section from a config dictionary."""
    value = config.get(section, {})
    return value if isinstance(value, dict) else {}


def config_str(
    config: dict[str, Any], section: str, name: str, default: str = ""
) -> str:
    """Read a string value from a nested config section."""
    value = config_section(config, section).get(name, default)
    if value is None:
        return default
    return str(value).strip()


def config_int(config: dict[str, Any], section: str, name: str, default: int) -> int:
    """Read an integer value from a nested config section."""
    value = config_section(config, section).get(name, default)
    try:
        return int(value)
    except (TypeError, ValueError):
        LOGGER.warning(
            "Invalid integer for %s.%s=%r; using %s.",
            section,
            name,
            value,
            default,
        )
        return default


def config_list(
    config: dict[str, Any], section: str, name: str, default: list[str]
) -> list[str]:
    """Read a string list from a nested config section."""
    value = config_section(config, section).get(name, default)

    if isinstance(value, str):
        items = value.split(",")
    elif isinstance(value, list):
        items = value
    else:
        LOGGER.warning("Invalid list for %s.%s; using defaults.", section, name)
        items = default

    return [
        str(item).strip() for item in items if item is not None and str(item).strip()
    ]
