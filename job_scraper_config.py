"""Compatibility imports for the refactored config helpers.

New code should import from ``jobfinder.config_files``. This module exists so
older local snippets that import ``job_scraper_config`` keep working.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from jobfinder.config_files import (
    ConfigFileError,
    config_int,
    config_list,
    config_section,
    config_str,
    load_filter_config,
    load_keywords,
)

__all__ = [
    "ConfigFileError",
    "config_int",
    "config_list",
    "config_section",
    "config_str",
    "load_filter_config",
    "load_keywords",
]
