"""
Column normalization: derive columns_normalized when LLM returns period_labels only.
"""
from __future__ import annotations

import re


def derive_columns_from_period_labels(period_labels: list[str]) -> list[dict]:
    """
    Fallback: when LLM returns period_labels but no columns_normalized,
    derive a minimal column structure. entity_scope defaults to UNKNOWN.
    """
    columns: list[dict] = []
    for i, lbl in enumerate(period_labels):
        lbl_clean = (lbl or "").strip()
        if not lbl_clean:
            continue
        col_id = _safe_column_id(lbl_clean, i)
        is_note = _is_note_col(lbl_clean)
        columns.append({
            "id": col_id,
            "label": lbl_clean,
            "entity_scope": "UNKNOWN",
            "column_role": "NOTE_REF" if is_note else "VALUE",
            "period_end": None,
            "period_end_source": "none",
            "year": _extract_year(lbl_clean),
            "parent_column_id": None,
            "is_note_col": is_note,
            "order": i,
        })
    return columns


def _safe_column_id(label: str, index: int) -> str:
    """Generate a safe column id from label."""
    base = label.lower().replace(" ", "_").replace("/", "_").replace("(", "").replace(")", "")
    base = "".join(c for c in base if c.isalnum() or c == "_")[:40]
    if not base:
        base = f"col_{index}"
    return f"col_{index}_{base}" if base != f"col_{index}" else base


def _extract_year(s: str) -> int | None:
    """Extract 4-digit year from string."""
    import re
    m = re.search(r"\b(20\d{2})\b", s)
    return int(m.group(1)) if m else None


def _is_note_col(s: str) -> bool:
    """True if label suggests a Notes column."""
    lower = s.lower()
    return "note" in lower and ("ref" in lower or len(lower) < 15)


def get_column_ids(columns: list[dict], value_only: bool = False) -> list[str]:
    """Return ordered list of column ids. If value_only, exclude NOTE_REF/OTHER."""
    out = []
    for c in columns:
        if not c.get("id"):
            continue
        if value_only:
            if c.get("column_role") in ("NOTE_REF", "OTHER") or c.get("is_note_col"):
                continue
        out.append(c["id"])
    return out


def check_row_completeness(
    row: dict,
    value_column_ids: list[str],
) -> tuple[bool, list[str]]:
    """
    For row_role in (line_item, subtotal, total): row must have every value column id.
    Returns (complete, missing_ids).
    """
    role = (row.get("row_role") or "line_item").lower()
    if role not in ("line_item", "subtotal", "total"):
        return True, []
    raw = row.get("raw_value_strings") or {}
    missing = [cid for cid in value_column_ids if cid not in raw]
    return len(missing) == 0, missing


def _normalize_key_for_match(s: str) -> str:
    """Normalize for loose matching: lower, collapse spaces, strip."""
    s = (s or "").strip().lower()
    s = re.sub(r"\s+", " ", s).strip()
    return "".join(c for c in s if c.isalnum() or c in " _")


def raw_value_strings_to_column_keys(
    raw_value_strings: dict[str, str | None],
    columns: list[dict],
) -> dict[str, str | None]:
    """
    Map raw_value_strings keys to column ids.
    Handles: exact col id, exact label, bare year (2025), normalized label match.
    """
    col_ids = {c["id"]: c for c in columns}
    col_label_to_id: dict[str, str] = {}
    col_norm_to_id: dict[str, str] = {}
    year_to_col_id: dict[str, str] = {}
    for c in columns:
        if not c.get("id"):
            continue
        lid = c["id"]
        lbl = (c.get("label") or "").strip()
        if lbl:
            col_label_to_id[lbl] = lid
            col_norm_to_id[_normalize_key_for_match(lbl)] = lid
        yr = c.get("year")
        if yr is not None:
            year_to_col_id[str(yr)] = lid
        # Also extract year from label (e.g. "52 weeks 2025 Rm" -> 2025)
        m = re.search(r"\b(20\d{2})\b", lbl)
        if m and str(m.group(1)) not in year_to_col_id:
            year_to_col_id[str(m.group(1))] = lid

    out: dict[str, str | None] = {}
    used_col_ids: set[str] = set()
    for k, v in raw_value_strings.items():
        if not k:
            continue
        target_id: str | None = None
        if k in col_ids:
            target_id = k
        elif k in col_label_to_id:
            target_id = col_label_to_id[k]
        elif k in year_to_col_id:
            target_id = year_to_col_id[k]
        elif _normalize_key_for_match(k) in col_norm_to_id:
            target_id = col_norm_to_id[_normalize_key_for_match(k)]

        if not target_id:
            # Raw key may be "52 weeks 2025" (no "Rm") - extract year and match
            m = re.search(r"\b(20\d{2})\b", str(k))
            if m:
                target_id = year_to_col_id.get(m.group(1))
        if target_id:
            out[target_id] = v
            used_col_ids.add(target_id)
        else:
            out[k] = v
    return out
