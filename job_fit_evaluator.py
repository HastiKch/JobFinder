"""Compatibility wrapper for the JobFinder evaluator CLI.

The evaluator implementation lives in ``src/jobfinder/evaluator``. This
wrapper preserves the historical command:

    python job_fit_evaluator.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from jobfinder.evaluator.cli import main

if __name__ == "__main__":
    sys.exit(main())
