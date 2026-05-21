"""Sanitized run-report helpers."""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jobfinder.env import EnvSettings


def report_payload(status: str, category: str, details: Any) -> dict[str, Any]:
    """Build a sanitized JSON report payload."""
    if is_dataclass(details) and not isinstance(details, type):
        details = asdict(details)
    return {
        "status": status,
        "category": category,
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "details": details,
    }


def write_report(path: str, status: str, category: str, details: Any) -> None:
    """Write a sanitized JSON report when a path is configured."""
    if not path:
        return
    report_path = Path(path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report_payload(status, category, details), indent=2, sort_keys=True),
        encoding="utf-8",
    )


def write_report_from_env(
    env_name: str,
    status: str,
    category: str,
    details: Any,
) -> None:
    """Write a report to the path named by an environment variable."""
    write_report(EnvSettings().get(env_name), status, category, details)
