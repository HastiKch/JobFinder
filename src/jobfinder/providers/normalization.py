"""Shared provider-output normalization primitives."""

from __future__ import annotations

import re
from typing import Any

HTML_TAG_RE = re.compile(r"<[^>]+>")
WHITESPACE_RE = re.compile(r"\s+")


def clean_scalar_text(value: Any, *, strip_html: bool = False) -> str:
    """Normalize one scalar actor-output value."""
    text = str(value)
    if strip_html:
        text = HTML_TAG_RE.sub(" ", text)
    return WHITESPACE_RE.sub(" ", text).strip()


def first_text(
    item: dict[str, Any],
    *keys: str,
    fallback: Any = "",
    strip_html: bool = False,
) -> str:
    """Return the first non-empty scalar value for the given keys."""
    for key in keys:
        value = item.get(key)
        if value is None or isinstance(value, bool | dict | list):
            continue
        text = clean_scalar_text(value, strip_html=strip_html)
        if text:
            return text

    if fallback is None or isinstance(fallback, bool | dict | list):
        return ""
    return clean_scalar_text(fallback, strip_html=strip_html)


def nested_text(
    item: dict[str, Any],
    *keys: str,
    strip_html: bool = False,
) -> str:
    """Read a nested scalar value from actor output."""
    value: Any = item
    for key in keys:
        if not isinstance(value, dict):
            return ""
        value = value.get(key)
    if value is None or isinstance(value, bool | dict | list):
        return ""
    return clean_scalar_text(value, strip_html=strip_html)


def values_from_shape(
    value: Any,
    *,
    strip_html: bool = False,
    prefer_label_keys: tuple[str, ...] = (),
) -> list[str]:
    """Flatten actor dict/list/string metadata shapes into human labels."""
    if value in (None, "", "N/A") or isinstance(value, bool):
        return []
    if isinstance(value, dict):
        for key in prefer_label_keys:
            label = value.get(key)
            if label not in (None, ""):
                return values_from_shape(
                    label,
                    strip_html=strip_html,
                    prefer_label_keys=prefer_label_keys,
                )
        return [
            item
            for raw_value in value.values()
            for item in values_from_shape(
                raw_value,
                strip_html=strip_html,
                prefer_label_keys=prefer_label_keys,
            )
        ]
    if isinstance(value, list):
        return [
            item
            for raw_value in value
            for item in values_from_shape(
                raw_value,
                strip_html=strip_html,
                prefer_label_keys=prefer_label_keys,
            )
        ]

    text = clean_scalar_text(value, strip_html=strip_html)
    return [text] if text else []


def unique(values: list[str], *, limit: int | None = None) -> tuple[str, ...]:
    """Return unique non-empty values in input order."""
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        text = clean_scalar_text(value)
        key = text.casefold()
        if not text or key in seen:
            continue
        seen.add(key)
        output.append(text)
        if limit is not None and len(output) >= limit:
            break
    return tuple(output)


def populated_metadata_dict(metadata: object) -> dict[str, Any]:
    """Return populated metadata fields, converting tuples for JSON-like output."""
    values: dict[str, Any] = {}
    for key, value in vars(metadata).items():
        if value:
            values[key] = list(value) if isinstance(value, tuple) else value
    return values


def seconds_from_published_at(value: str) -> int | None:
    """Parse LinkedIn-style ``rSECONDS`` windows used by provider settings."""
    text = (value or "").strip().casefold()
    if not text.startswith("r"):
        return None
    try:
        seconds = int(text[1:])
    except ValueError:
        return None
    return seconds if seconds > 0 else None


def parse_salary_number(value: Any) -> float | None:
    """Parse non-negative numeric salary values from actor output."""
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        number = float(str(value).replace(",", "").strip())
    except ValueError:
        return None
    return number if number >= 0 else None


def format_money(value: float) -> str:
    """Format a salary number without unnecessary decimals."""
    if value.is_integer():
        return f"{int(value):,}"
    return f"{value:,.2f}".rstrip("0").rstrip(".")


def append_metadata_block(
    description: str,
    source_label: str,
    metadata_lines: list[str],
) -> str:
    """Append source metadata lines to a base description."""
    if not metadata_lines:
        return description

    metadata_block = "\n".join(f"- {line}" for line in metadata_lines)
    metadata_text = f"{source_label} structured metadata:\n{metadata_block}"
    if description:
        return f"{description}\n\n{metadata_text}"
    return metadata_text
