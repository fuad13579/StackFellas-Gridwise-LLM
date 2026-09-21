"""Deterministic parsing of explicit whole-hour clock ranges in operator notes."""

import re


_CLOCK_TOKEN = r"""
    noon
    | midnight
    | (?:1[0-2]|0?[1-9])(?::[0-5]\d)?\s*(?:a\.?m\.?|p\.?m\.?)
    | (?:[01]?\d|2[0-3]):[0-5]\d
"""

_TIME_RANGE = re.compile(
    rf"""
    (?:\b(?:from|between)\s+)?
    (?P<start>{_CLOCK_TOKEN})
    \s*(?:until|to|and|-)\s*
    (?P<end>{_CLOCK_TOKEN})
    """,
    re.IGNORECASE | re.VERBOSE,
)


def clock_token_to_hour(token: str) -> int | None:
    """Map a supported clock expression to its containing hourly bucket."""
    normalized = re.sub(r"\s+", "", token.lower().replace(".", ""))
    if normalized == "noon":
        return 12
    if normalized == "midnight":
        return 0

    match = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?([ap]m)?", normalized)
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    suffix = match.group(3)
    if minute > 59:
        return None
    if suffix == "am":
        if not 1 <= hour <= 12:
            return None
        return 0 if hour == 12 else hour
    if suffix == "pm":
        if not 1 <= hour <= 12:
            return None
        return 12 if hour == 12 else hour + 12
    if not 0 <= hour <= 23:
        return None
    return hour


def explicit_time_window_hours(note: str) -> list[int] | None:
    """Return canonical [start, end) hours for one explicit clock range.

    The official challenge uses whole-hour buckets. Minute-bearing timestamps map
    to their containing hour. Ambiguous prose without two clock endpoints is not
    interpreted here and remains the LLM's responsibility.
    """
    match = _TIME_RANGE.search(note)
    if not match:
        return None
    start = clock_token_to_hour(match.group("start"))
    end = clock_token_to_hour(match.group("end"))
    if start is None or end is None or start == end:
        return None
    if start < end:
        return list(range(start, end))
    return sorted(list(range(start, 24)) + list(range(0, end)))
