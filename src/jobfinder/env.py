"""Small helpers for reading local environment settings."""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from pathlib import Path

from jobfinder.paths import ENV_FILE


def load_local_env(path: Path = ENV_FILE) -> dict[str, str]:
    """Load simple ``KEY=value`` settings from a local dotenv-style file."""
    values: dict[str, str] = {}
    if not path.exists():
        return values

    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("\"'")

    return values


class EnvSettings:
    """Resolve settings from real environment variables and a local env file."""

    def __init__(
        self,
        local_values: Mapping[str, str] | None = None,
        *,
        logger: logging.Logger | None = None,
    ) -> None:
        """Create a settings reader using the provided local values."""
        self.local_values = dict(
            load_local_env() if local_values is None else local_values
        )
        self.logger = logger

    def get(self, name: str, default: str = "") -> str:
        """Return a string setting with whitespace stripped."""
        return os.environ.get(name, self.local_values.get(name, default)).strip()

    def get_alias(self, name: str, *legacy_names: str, default: str = "") -> str:
        """Return a setting, checking a canonical name before legacy aliases."""
        for candidate in (name, *legacy_names):
            value = self.get(candidate)
            if value:
                return value
        return default.strip()

    def get_int(self, name: str, default: int) -> int:
        """Return an integer setting, falling back to the default on bad input."""
        value = self.get(name, str(default))
        try:
            return int(value)
        except ValueError:
            message = f"Invalid integer for {name}={value!r}; using {default}."
            (self.logger or logging.getLogger(__name__)).warning(message)
            return default

    def get_int_alias(self, name: str, *legacy_names: str, default: int) -> int:
        """Return an integer setting from a canonical name or legacy aliases."""
        value = self.get_alias(name, *legacy_names, default=str(default))
        try:
            return int(value)
        except ValueError:
            message = f"Invalid integer for {name}={value!r}; using {default}."
            (self.logger or logging.getLogger(__name__)).warning(message)
            return default

    def get_float(self, name: str, default: float) -> float:
        """Return a float setting, falling back to the default on bad input."""
        value = self.get(name, str(default))
        try:
            return float(value)
        except ValueError:
            message = f"Invalid float for {name}={value!r}; using {default}."
            (self.logger or logging.getLogger(__name__)).warning(message)
            return default

    def get_float_alias(
        self,
        name: str,
        *legacy_names: str,
        default: float,
    ) -> float:
        """Return a float setting from a canonical name or legacy aliases."""
        value = self.get_alias(name, *legacy_names, default=str(default))
        try:
            return float(value)
        except ValueError:
            message = f"Invalid float for {name}={value!r}; using {default}."
            (self.logger or logging.getLogger(__name__)).warning(message)
            return default

    def get_bool(self, name: str, default: bool) -> bool:
        """Return a boolean setting, accepting common true/false strings."""
        value = self.get(name, str(default).lower()).lower()
        if value in {"1", "true", "yes", "y", "on"}:
            return True
        if value in {"0", "false", "no", "n", "off"}:
            return False

        message = f"Invalid boolean for {name}={value!r}; using {default}."
        (self.logger or logging.getLogger(__name__)).warning(message)
        return default

    def get_bool_alias(self, name: str, *legacy_names: str, default: bool) -> bool:
        """Return a boolean setting from a canonical name or legacy aliases."""
        value = self.get_alias(
            name,
            *legacy_names,
            default=str(default).lower(),
        ).lower()
        if value in {"1", "true", "yes", "y", "on"}:
            return True
        if value in {"0", "false", "no", "n", "off"}:
            return False

        message = f"Invalid boolean for {name}={value!r}; using {default}."
        (self.logger or logging.getLogger(__name__)).warning(message)
        return default
