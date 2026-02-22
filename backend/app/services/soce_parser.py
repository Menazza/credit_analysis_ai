"""
Parser for Statement of Changes in Equity (SOCE / SoCE).

Uses hierarchical header detection and canonical roles.
Validates with Rule A/B/C and resolves column shifts when needed.
"""
from __future__ import annotations

import re
from typing import Any

from app.services.soce_header import (
    parse_soce_columns_hierarchical,
    column_defs_to_keys,
    validate_soce_row,
    resolve_column_shift,
)

# Legacy flat column order (fallback)
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
    """Extract all numeric amounts from a line in order.

    Handles space-separated thousands (e.g. "26 278" -> 26278) and parenthesized negatives.
    Uses column separation (2+ spaces/tabs) when present; otherwise regex for number patterns.
    Standalone dashes (— - –) = 0.
    """
    # Treat standalone dash/emdash as 0 to preserve column alignment
    line = re.sub(r"(?<=\s)[-–—](?=\s)|(?<=\s)[-–—]$|^[-–—](?=\s)", " 0 ", line)
    amounts: list[float] = []

    # Strategy 1: Columns often separated by 2+ spaces or tabs - split and parse each segment
    segments = re.split(r"\s{2,}|\t", line)
    if len(segments) > 1:
        for seg in segments:
            seg = seg.strip()
            if not seg:
                continue
            amt = _parse_amount(seg)
            if amt is not None:
                amounts.append(amt)
            else:
                # Segment has multiple numbers (e.g. "26 278" or "7 516 (2 624)")
                sub = _extract_amounts_from_segment(seg)
                amounts.extend(sub)
        if amounts:
            return amounts

    # Strategy 2: Single segment or no clear separation - extract numbers by regex
    amounts = _extract_amounts_from_segment(line)
    return amounts


def _extract_amounts_from_segment(segment: str) -> list[float]:
    """Extract numbers from a segment; handles '26 278' as one number, not '26 278 148'."""
    amounts: list[float] = []
    neg_pat = r"\(\s*[\d\s,.]+?\s*\)"
    # Limit to 0-1 thousands groups to avoid "26 278 148" → 26278148; allows "26 278" and "148"
    pos_pat = r"\d{1,3}(?:\s\d{3}){0,1}(?:[.,]\d+)?"
    combined = rf"{neg_pat}|{pos_pat}"
    for m in re.finditer(combined, segment):
        s = m.group(0)
        amt = _parse_amount(s)
        if amt is not None:
            amounts.append(amt)
    return amounts


def detect_soce_columns(text: str) -> list[str]:
    """
    Detect SOCE column order — hierarchical first, fallback to flat.
    Returns list of column keys in document order.
    """
    column_defs = parse_soce_columns_hierarchical(text)
    keys = column_defs_to_keys(column_defs)
    if keys:
        return keys
    # Fallback: flat detection
    text_lower = text.lower()
    found: list[tuple[int, str]] = []
    for key, patterns in SOCE_COLUMNS:
        for pat in patterns:
            m = re.search(re.escape(pat), text_lower)
            if m:
                found.append((m.start(), key))
                break
    found.sort(key=lambda x: x[0])
    seen: set[str] = set()
    result: list[str] = []
    for _, key in found:
        if key not in seen:
            seen.add(key)
            result.append(key)
    return result if result else [k for k, _ in SOCE_COLUMNS]


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


def _normalize_column_order(column_order: list[str], period_labels: list[str]) -> list[str]:
    """
    Normalize column_order from LLM (may have period suffixes like total_equity_2024).
    Returns unique canonical keys in document order - only columns that exist, no extras.
    """
    if not column_order:
        return []
    seen: set[str] = set()
    result: list[str] = []
    for cid in column_order:
        base = cid
        for pl in period_labels:
            if cid.endswith("_" + pl):
                base = cid[: -len(pl) - 1]
                break
        if base and base not in seen:
            seen.add(base)
            result.append(base)
    return result


def parse_soce_table(
    text: str,
    column_keys: list[str] | None = None,
    period_labels: list[str] | None = None,
    layout_hint: dict | None = None,
) -> tuple[list[str], list[str], list[dict[str, Any]]]:
    """
    Parse SOCE text into column keys, period labels, and structured rows.

    Returns:
        (column_keys, period_labels, rows)
        Each row: {"raw_label": str, "note": str|None, "values_json": {period: {col: value}}, "section": str|None}
    """
    layout = layout_hint or {}
    period_labels = period_labels or layout.get("period_labels") or _extract_period_labels_from_soce(text)
    raw_keys = column_keys or layout.get("column_order") or detect_soce_columns(text)
    norm = _normalize_column_order(raw_keys or [], period_labels)
    column_keys = norm if norm else detect_soce_columns(text)
    has_notes_col = layout.get("has_notes_column", False)
    notes_col_idx = layout.get("notes_column_index", -1)

    # Use columns actually detected - don't add extra columns, don't lock to fixed count.
    value_cols_per_period = len(column_keys)
    total_value_cols = value_cols_per_period * len(period_labels)

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
        nonlocal current_label, current_note, current_section, current_amounts, rows
        if not current_label:
            return
        if not current_amounts:
            current_label = None
            current_note = None
            return
        # Notes is ONE optional leading amount (small int like 19, 22). Never skip value columns.
        value_amounts = list(current_amounts)
        note_ref_val: str | None = None
        if has_notes_col and notes_col_idx == 0 and value_amounts and value_amounts[0] < 500 and value_amounts[0] == int(value_amounts[0]):
            note_ref_val = str(int(value_amounts[0]))
            value_amounts = value_amounts[1:]

        num_periods = min(len(period_labels), max(1, len(value_amounts) // value_cols_per_period))
        values_json: dict[str, dict[str, float]] = {}
        for i in range(num_periods):
            period = period_labels[i] if i < len(period_labels) else str(i)
            start = i * value_cols_per_period
            end = start + value_cols_per_period
            if end <= len(value_amounts):
                values_json[period] = {
                    column_keys[j]: value_amounts[start + j]
                    for j in range(value_cols_per_period)
                }
            else:
                values_json[period] = {}
                for j in range(value_cols_per_period):
                    if start + j < len(value_amounts):
                        values_json[period][column_keys[j]] = value_amounts[start + j]
                for col in column_keys:
                    if col not in values_json[period]:
                        values_json[period][col] = 0.0
        if any(v for pv in values_json.values() for v in pv.values()):
            rows.append({
                "raw_label": current_label,
                "note": note_ref_val if note_ref_val is not None else current_note,
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
                if len(current_amounts) >= total_value_cols:
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
                num_part = " ".join(tokens[first_num_idx:])
                inline_amounts = _extract_amounts_from_line(num_part)
                if label_part and inline_amounts:
                    if current_label:
                        flush_row()
                    current_label = label_part
                    current_note = None
                    current_amounts = inline_amounts
                    if len(current_amounts) >= total_value_cols:
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

    # Column shift resolution: if validation fails on a balance row, try permutations
    tolerance = 1.0
    balance_rows = [r for r in rows if (r.get("raw_label") or "").lower().startswith("balance at")]
    if balance_rows and value_cols_per_period >= 3:
        row0 = balance_rows[0]
        vj = row0.get("values_json") or {}
        amounts_flat: list[float] = []
        p0 = period_labels[0]
        for k in column_keys:
            v = (vj.get(p0) or {}).get(k)
            amounts_flat.append(v if v is not None else 0.0)
        val0 = validate_soce_row((vj.get(period_labels[0]) or {}), tolerance)
        if not val0.passed:
            keys_old = list(column_keys)
            _, keys_new, val_new = resolve_column_shift(
                amounts_flat, column_keys, period_labels, tolerance
            )
            if val_new and val_new.passed and keys_new != keys_old:
                for r in rows:
                    old_vj = r.get("values_json") or {}
                    new_vj: dict[str, dict[str, float]] = {}
                    for period in period_labels:
                        old_p = old_vj.get(period) or {}
                        new_p = {
                            keys_new[j]: old_p.get(keys_old[j], 0.0)
                            for j in range(len(keys_old))
                            if j < len(keys_new)
                        }
                        new_vj[period] = new_p
                    r["values_json"] = new_vj
                column_keys = keys_new

    return column_keys, period_labels, rows


def extract_soce_structured_lines(
    text: str,
    start_line_no: int = 1,
    page_no: int | None = None,
    layout_hint: dict | None = None,
) -> list[dict[str, Any]]:
    """
    Extract SOCE rows as StatementLine-compatible dicts.

    Returns list of:
      {line_no, raw_label, note, values_json, evidence_json}
    where values_json = {"2024": {"total_equity": x, ...}, "2025": {...}}

    layout_hint: optional from LLM vision analysis {has_notes_column, notes_column_index, column_order, period_labels}
    """
    column_keys, period_labels, rows = parse_soce_table(text, layout_hint=layout_hint)

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
