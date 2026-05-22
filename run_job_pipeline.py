"""Compatibility wrapper for the one-step JobFinder pipeline.

The pipeline implementation lives in ``src/jobfinder/pipeline``. This wrapper
preserves the historical command:

    python run_job_pipeline.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from jobfinder.pipeline.cli import main

if __name__ == "__main__":
    sys.exit(main())
