"""Compatibility wrapper for the JobScraper CLI.

The scraper implementation lives in ``src/jobfinder/scraper``. This wrapper
preserves the historical command:

    python linkedin_job_scraper.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from jobfinder.scraper.cli import main

if __name__ == "__main__":
    sys.exit(main())
