"""
Parser for Statement of Changes in Equity (SOCE / SoCE).

Finds column headers (Total equity, Non-controlling interest, Stated capital, etc.)
and parses rows into a multi-column table structure.
"""
from __future__ import annotations

import re
from typing import Any


# Standard SOCE column keys and header patterns (order in document)
SOCE_COLUMNS: list[tuple[str, list[str]]] = [
    ("total_equity", ["total equity"]),
    ("non_controlling_interest", ["non-controlling interest", "non controlling interest", "nci"]),
    ("attributable_total", ["attributable to owners of the parent", "attributable to owners"]),
    ("stated_capital", ["stated capital"]),
    ("treasury_shares", ["treasury shares"]),
    ("other_reserves", ["other reserves"]),
    ("retained_earnings", ["retained earnings"]),
]


def _parse_amount(raw: str) -> float | None:
    """Parse numeric amount; (x) = negative."""
    s = raw.strip().replace("\u00a0", " ")
    neg = False
    if s.startswith("(") and s.endswith(")"):
        neg = True
        s = s[1:-1]
    s = s.replace(" ", "").replace(",", "")
    if not s or any(c for c in s if not (c.isdigit() or c in ".-")):
        return None
    try:
        val = float(s)
    except ValueError:
        return None
    return -val if neg else val


def _extract_amounts_from_line(line: str) -> list[float]:
    """Extract all numeric amounts from a line in order."""
    amounts: list[float] = []
    # Split on whitespace; also handle inline (1 234) patterns
    tokens = re.split(r"\s+", line)
    for tok in tokens:
        amt = _parse_amount(tok)
        if amt is not None:
            amounts.append(amt)
    # Also try to find amounts with spaces inside: "26 278" as one number
    for m in re.finditer(r"\(?\d[\d\s,.]*\)?", line):
        s = m.group(0)
        amt = _parse_amount(s)
        if amt is not None and amt not in amounts:  # avoid double-counting
            pass  # prefer token-by-token to preserve order
    return amounts


def detect_soce_columns(text: str) -> list[str]:
    """
    Detect SOCE column order from header section.
    Returns list of column keys in document order.
    """
    text_lower = text.lower()
    found: list[tuple[int, str]] = []

    for key, patterns in SOCE_COLUMNS:
        for pat in patterns:
            m = re.search(re.escape(pat), text_lower)
            if m:
                found.append((m.start(), key))
                break

    # Sort by position in text, then deduplicate by key (keep first occurrence)
    found.sort(key=lambda x: x[0])
    seen: set[str] = set()
    result: list[str] = []
    for _, key in found:
        if key not in seen:
            seen.add(key)
            result.append(key)

    if result:
        return result

    # Fallback: use standard order
    return [k for k, _ in SOCE_COLUMNS]


def _extract_period_labels_from_soce(text: str) -> list[str]:
    """Extract period labels from Balance at DATE lines."""
    years: list[str] = []
    for m in re.finditer(r"balance at (\d{1,2} \w+ (20\d{2}))", text, re.IGNORECASE):
        y = m.group(2)
        if y not in years:
            years.append(y)
    for m in re.finditer(r"\b(20\d{2})\b", text):
        y = m.group(1)
        if y not in years:
            years.append(y)
    years.sort()
    return years[-2:] if len(years) >= 2 else years or ["current", "prior"]


def parse_soce_table(
    text: str,
    column_keys: list[str] | None = None,
    period_labels: list[str] | None = None,
) -> tuple[list[str], list[str], list[dict[str, Any]]]:
    """
    Parse SOCE text into column keys, period labels, and structured rows.

    Returns:
        (column_keys, period_labels, rows)
        Each row: {"raw_label": str, "note": str|None, "values_json": {period: {col: value}}, "section": str|None}
    """
    column_keys = column_keys or detect_soce_columns(text)
    period_labels = period_labels or _extract_period_labels_from_soce(text)

    # Assume two period blocks with same column count, or single block
    cols_per_period = len(column_keys)
    total_cols = cols_per_period * len(period_labels)

    rows: list[dict[str, Any]] = []
    current_label: str | None = None
    current_note: str | None = None
    current_amounts: list[float] = []
    current_section: str | None = None

    # Skip header lines
    skip_patterns = [
        r"consolidated statement of changes in equity",
        r"statement of changes in equity",
        r"for the year ended",
        r"notes\s+52 weeks",
        r"^\s*notes\s*$",
    ]

    def flush_row() -> None:
        nonlocal current_label, current_amounts, rows
        if not current_label:
            return
        if not current_amounts:
            current_label = None
            current_note = None
            return
        # Distribute amounts across periods (7 or 14 columns typical)
        num_periods = min(len(period_labels), max(1, len(current_amounts) // cols_per_period))
        values_json: dict[str, dict[str, float]] = {}
        for i in range(num_periods):
            period = period_labels[i] if i < len(period_labels) else str(i)
            start = i * cols_per_period
            end = start + cols_per_period
            if end <= len(current_amounts):
                values_json[period] = {
                    column_keys[j]: current_amounts[start + j]
                    for j in range(cols_per_period)
                }
            else:
                # Partial row - fill available columns
                values_json[period] = {}
                for j in range(min(cols_per_period, len(current_amounts) - start)):
                    if start + j < len(current_amounts):
                        values_json[period][column_keys[j]] = current_amounts[start + j]
                for col in column_keys:
                    if col not in values_json[period]:
                        values_json[period][col] = 0.0
        if any(v for pv in values_json.values() for v in pv.values()):
            rows.append({
                "raw_label": current_label,
                "note": current_note,
                "values_json": values_json,
                "section": current_section,
            })
        current_label = None
        current_note = None
        current_amounts = []

    for raw in text.splitlines():
        s = raw.strip()
        if not s or len(s) > 400:
            continue

        lower = s.lower()
        if any(re.search(rx, lower) for rx in skip_patterns):
            continue

        # Section headers (Balance at, Total comprehensive income, Other equity movements)
        if "balance at" in lower and re.search(r"\d{1,2}\s+\w+\s+20\d{2}", s):
            if current_label:
                flush_row()
            current_section = s
            current_label = s
            current_note = None
            current_amounts = []
            continue

        if "total comprehensive income" in lower:
            if current_label:
                flush_row()
            current_section = s
            current_label = s
            current_note = None
            current_amounts = []
            continue

        if "recognised in other comprehensive" in lower or "other comprehensive loss" in lower:
            if current_label:
                flush_row()
            current_section = s
            current_label = s
            current_note = None
            current_amounts = []
            continue

        if "other equity movements" in lower or "profit/(loss) for the year" in lower:
            if current_label:
                flush_row()
            current_section = s
            current_label = s
            current_note = None
            current_amounts = []
            continue

        # Numeric line: collect amounts
        amounts = _extract_amounts_from_line(s)
        if amounts:
            if current_label:
                current_amounts.extend(amounts)
                if len(current_amounts) >= total_cols:
                    flush_row()
            continue

        # Potential note number
        if s.isdigit() and int(s) < 500 and current_label and not current_amounts:
            current_note = s
            continue

        # New label line (contains letters, not a section header)
        if any(c.isalpha() for c in s):
            if current_label and current_amounts:
                flush_row()
            # Inline pattern: "Label 123 456 789" - label + amounts on same line
            tokens = s.split()
            first_num_idx = None
            for i, tok in enumerate(tokens):
                if _parse_amount(tok) is not None:
                    first_num_idx = i
                    break
            if first_num_idx is not None and first_num_idx > 0:
                label_part = " ".join(tokens[:first_num_idx])
                num_tokens = tokens[first_num_idx:]
                inline_amounts = []
                for tok in num_tokens:
                    amt = _parse_amount(tok)
                    if amt is not None:
                        inline_amounts.append(amt)
                if label_part and inline_amounts:
                    if current_label:
                        flush_row()
                    current_label = label_part
                    current_note = None
                    current_amounts = inline_amounts
                    if len(current_amounts) >= total_cols:
                        flush_row()
                    continue
            if current_label:
                flush_row()
            current_label = s
            current_note = None
            current_amounts = []
            continue

    if current_label:
        flush_row()

    return column_keys, period_labels, rows


def extract_soce_structured_lines(
    text: str,
    start_line_no: int = 1,
    page_no: int | None = None,
) -> list[dict[str, Any]]:
    """
    Extract SOCE rows as StatementLine-compatible dicts.

    Returns list of:
      {line_no, raw_label, note, values_json, evidence_json}
    where values_json = {"2024": {"total_equity": x, ...}, "2025": {...}}
    """
    column_keys, period_labels, rows = parse_soce_table(text)

    result: list[dict[str, Any]] = []
    for i, row in enumerate(rows):
        result.append({
            "line_no": start_line_no + i,
            "raw_label": row["raw_label"],
            "note": row.get("note"),
            "values_json": row["values_json"],
            "section_path": row.get("section"),
            "evidence_json": {"page": page_no} if page_no else {},
            "column_keys": column_keys,
            "period_labels": period_labels,
        })
    return result
