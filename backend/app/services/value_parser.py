"""
Deterministic value parser for financial statement raw strings.
LLM outputs verbatim strings; this module parses them into numeric values.
Rule: Nothing enters ratios/validation unless it passes deterministic parsing.
"""
from __future__ import annotations

import re
import unicodedata

SCALE_FACTORS = {
    "units": 1.0,
    "thousand": 1e3,
    "million": 1e6,
    "billion": 1e9,
}


def scale_factor_from_literal(scale: str | None) -> float:
    """Map scale literal to multiplier (e.g. 'million' -> 1e6)."""
    if not scale:
        return 1.0
    return SCALE_FACTORS.get((scale or "").lower().strip(), 1.0)


def parse_raw_value_string(raw: str | None) -> float | None:
    """
    Parse a numeric amount from a raw string exactly as it appears on the page.
    Handles: brackets for negatives, thin spaces, commas, dashes as null.
    Returns None for unparseable, blank, dash, or "—".
    """
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    # Dash variants as null/missing
    dash_chars = {"-", "—", "–", "–"}
    if s in dash_chars or s == "—" or s.replace(" ", "") in dash_chars:
        return None
    # Normalize unicode (e.g. thin space U+2009 → space)
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("\u00a0", " ")  # nbsp
    s = s.replace("\u2009", " ")  # thin space
    s = s.replace("\u202f", " ")  # narrow nbsp
    neg = False
    if s.startswith("(") and s.endswith(")"):
        neg = True
        s = s[1:-1].strip()
    # Remove thousands separators (space, comma)
    s = s.replace(" ", "").replace(",", "")
    # Allow optional leading minus
    if s.startswith("-"):
        neg = True
        s = s[1:]
    # Reject if contains non-numeric (except one decimal point)
    if not s or not re.match(r"^[\d.]+$", s):
        return None
    try:
        val = float(s)
    except ValueError:
        return None
    return -val if neg else val


def parse_and_scale(
    raw_value_strings: dict[str, str | None],
    column_keys: list[str],
    scale_factor: float = 1.0,
) -> dict[str, float | None]:
    """
    Parse raw strings to numbers and apply scale multiplier.
    column_keys: list of keys (column ids or period labels) to look up in raw_value_strings.
    Returns {key: scaled_float | None} for each key.
    """
    out: dict[str, float | None] = {}
    for k in column_keys:
        raw = raw_value_strings.get(k) if raw_value_strings else None
        parsed = parse_raw_value_string(raw)
        if parsed is None:
            out[k] = None
        else:
            out[k] = parsed * scale_factor
    return out
