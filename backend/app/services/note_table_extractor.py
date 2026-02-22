"""
Extract structured tables from note text. Rule-based for common AFS patterns.
Returns list of {headers, rows, unit} for storage in tables_json.
"""
from __future__ import annotations

import re
from typing import Any


NUM_RE = re.compile(r"[-+]?\d{1,3}(?:[ \u00A0]\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?")
YEAR_RE = re.compile(r"\b(20\d{2})\b")


def _find_year_columns(lines: list[str]) -> tuple[str, str] | None:
    """Find (year1, year2) from header line."""
    for line in lines[:20]:
        m = YEAR_RE.findall(line)
        if len(m) >= 2:
            return (m[0], m[1])
    return None


def _parse_numeric(value: str) -> float | None:
    s = (value or "").replace(" ", "").replace("\u00a0", "")
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    try:
        return float(s)
    except ValueError:
        return None


def extract_two_year_tables(text: str, page: int | None = None) -> list[dict[str, Any]]:
    """
    Extract tables with structure: label | 2025 | 2024 (or similar year columns).
    Returns list of {headers, rows, unit, page}.
    """
    tables: list[dict[str, Any]] = []
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if len(lines) < 3:
        return tables

    years = _find_year_columns(lines)
    if not years:
        years = ("2025", "2024")

    # Find rows that have label + 2 numbers
    unit = "unknown"
    if "Rm" in text or "R millions" in text:
        unit = "Rm"
    elif "R'000" in text or "R thousands" in text:
        unit = "R'000"

    current_table: list[dict[str, Any]] = []
    for line in lines:
        nums = NUM_RE.findall(line)
        # Skip header-like lines
        if re.search(r"^\s*\d{4}\s+(?:Rm|R'000)?", line, re.I) and len(nums) < 2:
            continue
        if len(nums) >= 2:
            # Assume last two numbers are the year values
            label = NUM_RE.sub("", line).strip().strip("–—-:")
            if len(label) > 2 and len(label) < 200:
                v1 = _parse_numeric(nums[-2])
                v2 = _parse_numeric(nums[-1])
                current_table.append({
                    "label": label[:150],
                    years[0]: v1,
                    years[1]: v2,
                })
        elif current_table:
            # Blank line or new section - flush table
            if len(current_table) >= 2:
                tables.append({
                    "headers": [years[0], years[1]],
                    "rows": current_table,
                    "unit": unit,
                    "page": page,
                })
            current_table = []

    if len(current_table) >= 2:
        tables.append({
            "headers": [years[0], years[1]],
            "rows": current_table,
            "unit": unit,
            "page": page,
        })

    return tables


def extract_tables_from_note_text(text: str, page: int | None = None) -> list[dict[str, Any]]:
    """
    Main entry: extract all detectable tables from note text.
    """
    return extract_two_year_tables(text, page)
