"""Sandbox security utilities — credential redaction and tool scoping."""

from __future__ import annotations

import re
from typing import Any


def redact_secrets(text: str, secret_values: list[str]) -> str:
    """Replace known secret values with ***REDACTED***.

    Sorts by length descending to prevent partial-match issues.
    """
    if not secret_values or not text:
        return text
    for secret in sorted(secret_values, key=len, reverse=True):
        if secret and secret in text:
            text = text.replace(secret, "***REDACTED***")
    return text


def validate_tool_scoping(
    *,
    allowed: list[str] | None = None,
    denied: list[str] | None = None,
    requested: list[str] | None = None,
) -> list[str]:
    """Resolve effective tool list after allow/deny filtering.

    Returns the list of tools the sandbox agent is permitted to use.
    If both allowed and denied are None, returns requested as-is.
    """
    if requested is None:
        return []

    effective = list(requested)

    if allowed is not None:
        allowed_set = set(allowed)
        effective = [t for t in effective if t in allowed_set]

    if denied is not None:
        denied_set = set(denied)
        effective = [t for t in effective if t not in denied_set]

    return effective
