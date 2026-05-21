"""Shared logging setup for command-line entry points."""

from __future__ import annotations

import logging

DEFAULT_LOG_FORMAT = "%(asctime)s %(levelname)s %(message)s"
DEFAULT_DATE_FORMAT = "%H:%M:%S"


def configure_cli_logging(level: int = logging.INFO) -> None:
    """Configure consistent human-readable logging for CLI commands."""
    logging.basicConfig(
        level=level,
        format=DEFAULT_LOG_FORMAT,
        datefmt=DEFAULT_DATE_FORMAT,
    )
