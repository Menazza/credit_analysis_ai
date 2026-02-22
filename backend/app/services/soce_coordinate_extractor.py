"""
Coordinate-based SoCE extraction using x,y positions from PDF.

Columns: inferred ONLY from header spans in the PDF – no extra columns added.
Value assignment: a numeric span belongs to a column iff its X position falls
within that column's x-range. This ensures values are never assigned to the
wrong column.
"""
from __future__ import annotations

import re
from typing import Any

# Known header hints for label mapping (optional - used when span text matches)
HEADER_HINTS = [
    ("notes", "notes"),
    ("total equity", "total_equity"),
    ("non-controlling", "non_controlling_interest"),
    ("attributable", "attributable_total"),
    ("stated capital", "stated_capital"),
    ("treasury shares", "treasury_shares"),
    ("other reserves", "other_reserves"),
    ("retained earnings", "retained_earnings"),
]


def _parse_amount(text: str) -> float | None:
    """Parse numeric; (x) = negative. Handles space thousands."""
    s = text.strip().replace("\u00a0", " ")
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


def _is_numeric_span(text: str) -> bool:
    """True if span looks like a number (including dash for empty)."""
    t = text.strip()
    if t in ("-", "—", "–", ""):
        return True
    return _parse_amount(t) is not None


def _label_for_cluster(cluster_text: str) -> str:
    """Map cluster text to canonical key if possible, else col_N style."""
    lower = cluster_text.lower()
    for hint, key in HEADER_HINTS:
        if hint in lower:
            return key
    return re.sub(r"[^a-z0-9]+", "_", lower.strip(" _"))[:40] or "unknown"


def _cluster_spans_by_x(
    spans: list[tuple[str, float, float]], gap_threshold: float = 25.0
) -> list[tuple[float, float, str]]:
    """
    Merge spans that are close in x into one column. Returns (x_start, x_end, label) per column.
    Prevents truncated headers ("Total equity (202", "4)") from becoming separate columns.
    
    Only creates ONE column per canonical label - no duplicates for multi-year headers.
    """
    if not spans:
        return []
    sorted_spans = sorted(spans, key=lambda s: s[1])  # by x0
    clusters: list[list[tuple[str, float, float]]] = []
    for t, x0, x1 in sorted_spans:
        placed = False
        for cluster in clusters:
            # last span in cluster
            _, _, last_x1 = cluster[-1]
            if x0 - last_x1 <= gap_threshold:
                cluster.append((t, x0, x1))
                placed = True
                break
        if not placed:
            clusters.append([(t, x0, x1)])
    
    result: list[tuple[float, float, str]] = []
    seen_labels: set[str] = set()
    
    for cluster in clusters:
        texts = [t for t, _, _ in cluster]
        x_start = min(x0 for _, x0, _ in cluster)
        x_end = max(x1 for _, _, x1 in cluster)
        label = _label_for_cluster(" ".join(texts))
        
        # Only add if we haven't seen this label before (prevent duplicates)
        if label not in seen_labels:
            result.append((x_start, x_end, label))
            seen_labels.add(label)
    
    return result


def extract_soce_from_page_dict(page_dict: dict, page_no: int) -> tuple[list[str], list[str], list[dict[str, Any]]]:
    """
    Extract SoCE rows using x,y coordinates from PyMuPDF page dict.

    Infers column count from the PDF - no fixed count. Merges truncated header
    fragments by x-proximity. Values are assigned to columns by x-position.

    Returns (column_keys, period_labels, rows).
    """
    rows: list[dict[str, Any]] = []
    blocks = page_dict.get("blocks", [])

    # 1) Collect all spans with (text, x0, y0, x1, y1)
    spans: list[tuple[str, float, float, float, float]] = []
    for block in blocks:
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                t = span.get("text", "").strip()
                if not t:
                    continue
                bbox = span.get("bbox")
                if not bbox or len(bbox) < 4:
                    continue
                x0, y0, x1, y1 = float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])
                spans.append((t, x0, y0, x1, y1))

    if not spans:
        return [], [], rows

    # 2) Group spans by approximate y (same row)
    y_tolerance = 3.0
    y_groups: dict[float, list[tuple[str, float, float, float, float]]] = {}
    for t, x0, y0, x1, y1 in spans:
        y_key = round(y0 / y_tolerance) * y_tolerance
        if y_key not in y_groups:
            y_groups[y_key] = []
        y_groups[y_key].append((t, x0, y0, x1, y1))

    sorted_y = sorted(y_groups.keys())

    # 3) Use only the first row as the header row – the column headers in the first row
    _EQUITY_HEADER_MARKERS = ("total equity", "non-controlling", "attributable", "stated capital", "treasury", "other reserves", "retained earnings")
    header_y: float | None = None
    for y in sorted_y:
        row_text = " ".join(t.lower() for t, *_ in y_groups[y])
        if any(m in row_text for m in _EQUITY_HEADER_MARKERS) or ("notes" in row_text and ("total" in row_text or "equity" in row_text)):
            header_y = y
            break

    # 4) Collect header spans from the first row only – exclude pure period/currency markers
    header_spans: list[tuple[str, float, float]] = []
    if header_y is not None:
        for t, x0, _, x1, _ in y_groups[header_y]:
            tl = t.strip().lower()
            if tl in ("rm",) and len(y_groups[header_y]) > 3:
                continue
            if re.match(r"^20\d{2}$", tl):
                continue  # Skip bare years (2024, 2025) – they are period labels, not column names
            header_spans.append((t, x0, x1))

    # 5) Cluster by x to merge truncated fragments into logical columns
    column_ranges = _cluster_spans_by_x(header_spans)

    # Use only columns found in the PDF - no additions
    all_columns = list(column_ranges)
    notes_col_idx = 0 if all_columns and all_columns[0][2] == "notes" else -1
    value_columns = all_columns[1:] if notes_col_idx == 0 else all_columns
    n_value_cols = len(value_columns)
    column_keys = [label for _, _, label in value_columns]

    # 6) Infer period labels from header row (e.g. 2024, 2025)
    years: list[str] = []
    if header_y is not None:
        row_text = " ".join(t for t, *_ in y_groups[header_y])
        for m in re.finditer(r"\b(20\d{2})\b", row_text):
            if m.group(1) not in years:
                years.append(m.group(1))
    years.sort()
    period_labels = years[-2:] if len(years) >= 2 else years or ["current", "prior"]

    # 7) Detect cols per period from actual column count (for values_json structure)
    cols_per_period = n_value_cols
    if n_value_cols > 4:
        for cpp in [7, 6, 5, 4]:
            if n_value_cols % cpp == 0:
                cols_per_period = cpp
                break
    num_periods = max(1, n_value_cols // cols_per_period) if cols_per_period else 1

    # 8) Value assignment: a span belongs to column i iff its mid_x is in [x_start_i, x_end_i]
    # For notes: check if ANY part of the span overlaps with the notes column x-range
    notes_x0, notes_x1 = (all_columns[0][0], all_columns[0][1]) if notes_col_idx == 0 and all_columns else (0, 0)
    
    def _is_in_notes_column(span_x0: float, span_x1: float) -> bool:
        """Check if span overlaps with notes column x-range (not just center point)."""
        if notes_col_idx != 0 or not all_columns:
            return False
        # Overlap check: span.x0 <= notes.x1 AND span.x1 >= notes.x0
        return span_x0 <= notes_x1 and span_x1 >= notes_x0
    
    def _column_for_x(mid_x: float) -> int:
        """Return value column index (0..n_value_cols-1) for this x, or -1 if notes."""
        for i, (x0, x1, _) in enumerate(value_columns):
            if x0 <= mid_x <= x1:
                return i
        # Check notes column
        if notes_col_idx == 0 and all_columns:
            x0, x1, _ = all_columns[0]
            if x0 <= mid_x <= x1:
                return -1  # notes
        return -2  # outside any column

    # 9) Process data rows (exclude the header row)
    data_y = [y for y in sorted_y if y != header_y]
    skip_starts = ("consolidated statement", "for the year", "statement of changes", "notes", "rm")

    pending_label: str | None = None  # For multi-line account names
    current_section: str | None = None

    for y in data_y:
        row_spans = sorted(y_groups[y], key=lambda s: s[1])
        row_text = " ".join(t for t, *_ in row_spans)
        lower = row_text.lower()

        if any(lower.startswith(s) for s in skip_starts) and len(row_spans) < 3:
            continue

        if "balance at" in lower and re.search(r"\d{1,2}\s+\w+\s+20\d{2}", row_text):
            current_section = row_text
            pending_label = row_text
            continue

        if "total comprehensive" in lower or "recognised in other" in lower or "profit/(loss)" in lower:
            current_section = row_text
            pending_label = row_text
            continue

        col_values: list[float | None] = [None] * n_value_cols
        note_val: str | None = None
        label_parts: list[str] = []

        for t, x0, _, x1, _ in row_spans:
            mid_x = (x0 + x1) / 2
            parsed = _parse_amount(t)
            is_note_like = parsed is not None and 0 <= parsed < 500 and parsed == int(parsed)
            col_idx = _column_for_x(mid_x)

            # Check if this is a note using x-coordinate OVERLAP (not just center point)
            # A small integer that overlaps the notes column x-range is a note reference
            if is_note_like and _is_in_notes_column(x0, x1) and note_val is None:
                note_val = str(int(parsed))
                continue
            
            if col_idx == -1:
                # Notes column (by center point) - treat as note if note-like
                if is_note_like and note_val is None:
                    note_val = str(int(parsed))
            elif col_idx >= 0 and col_idx < n_value_cols:
                # Value column: assign to this column by X position
                if parsed is not None:
                    col_values[col_idx] = parsed
                elif t.strip() in ("-", "—", "–"):
                    col_values[col_idx] = 0.0
            elif col_idx == -2 and not _is_numeric_span(t) and t.strip():
                label_parts.append(t)

        row_label = " ".join(label_parts) if label_parts else ""
        has_values = any(v is not None for v in col_values)

        # Multi-line account name handling:
        # If this row has only labels and no values, it's likely a continuation or start
        # of a multi-line account name. Store it and merge with the next row.
        if row_label and not has_values:
            if pending_label:
                pending_label = f"{pending_label} {row_label}"
            else:
                pending_label = row_label
            continue

        # Combine pending label with current row's label
        if pending_label:
            if row_label:
                final_label = f"{pending_label} {row_label}"
            else:
                final_label = pending_label
            pending_label = None
        else:
            final_label = row_label

        if has_values:
            values_json: dict[str, dict[str, float]] = {}
            for p in range(num_periods):
                period = period_labels[p] if p < len(period_labels) else str(p)
                values_json[period] = {}
                for j in range(cols_per_period):
                    idx = p * cols_per_period + j
                    key = column_keys[j] if j < len(column_keys) else f"col_{j}"
                    val = col_values[idx] if idx < len(col_values) else None
                    values_json[period][key] = float(val) if val is not None else 0.0

            rows.append({
                "raw_label": final_label or "",
                "note": note_val,
                "values_json": values_json,
                "section": current_section,
            })

    # Return canonical keys (first cols_per_period) for values_json structure
    canonical_keys = column_keys[:cols_per_period]
    return canonical_keys, period_labels, rows


def extract_soce_with_coordinates(pdf_bytes: bytes, page_no: int) -> tuple[list[str], list[str], list[dict[str, Any]]]:
    """
    Extract SoCE from a PDF page using coordinate-based parsing.
    Returns (column_keys, period_labels, rows) - columns inferred from PDF, none added.
    Values are assigned strictly by X position: a value belongs to a column iff its
    x falls within that column's x-range.
    """
    import fitz
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        page = doc[page_no - 1]
        page_dict = page.get_text("dict")
        return extract_soce_from_page_dict(page_dict, page_no)
    finally:
        doc.close()


def extract_soce_structured_lines_from_pdf(
    pdf_bytes: bytes, page_no: int, start_line_no: int = 1
) -> list[dict[str, Any]]:
    """
    Extract SoCE using PDF coordinates, returning the same format as
    soce_parser.extract_soce_structured_lines for drop-in replacement.

    Returns list of {line_no, raw_label, note, values_json, section_path, evidence_json, column_keys, period_labels}.
    """
    column_keys, period_labels, rows = extract_soce_with_coordinates(pdf_bytes, page_no)
    result: list[dict[str, Any]] = []
    for i, row in enumerate(rows):
        result.append({
            "line_no": start_line_no + i,
            "raw_label": row["raw_label"],
            "note": row.get("note"),
            "values_json": row["values_json"],
            "section_path": row.get("section"),
            "evidence_json": {"page": page_no},
            "column_keys": column_keys,
            "period_labels": period_labels,
        })
    return result
