"""
Base note extractors: regex/rule-based extraction for key credit notes.
Returns strict JSON with provenance (page, quote) for audit trail.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

NUM_RE = re.compile(r"[-+]?\d{1,3}(?:[ \u00A0]\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?")


def _to_float(s: str, scale: float = 1e6) -> Optional[float]:
    s = (s or "").replace(" ", "").replace("\u00a0", "")
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    try:
        return float(s) * scale
    except ValueError:
        return None


def _find_year_columns(lines: List[str]) -> Optional[tuple]:
    """Find (year1, year2) from header line like '2025 Rm 2024 Rm'."""
    for line in lines[:15]:
        m = re.findall(r"\b(20\d{2})\b", line)
        if len(m) >= 2:
            return (m[0], m[1])
    return None


def _extract_two_year_table(
    text: str,
    label_patterns: List[str],
    page: int,
    unit: str = "ZAR_million",
    scale: float = 1e6,
) -> Dict[str, Any]:
    """
    Generic extractor: find lines matching label_patterns and extract last 2 numbers as year values.
    Returns {field_name: {"2025": v1, "2024": v2}, "unit": unit}
    """
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    years = _find_year_columns(lines)
    if not years:
        years = ("2025", "2024")
    out: Dict[str, Any] = {}
    for label_pat in label_patterns:
        rx = re.compile(label_pat, re.IGNORECASE)
        for line in lines:
            if not rx.search(line):
                continue
            nums = NUM_RE.findall(line)
            if len(nums) < 2:
                continue
            v1 = _to_float(nums[-2], scale)
            v2 = _to_float(nums[-1], scale)
            if v1 is not None or v2 is not None:
                key = label_pat.replace(r"\b", "").replace("(", "").replace(")", "").replace(" ", "_")[:40]
                out[key] = {years[0]: v1, years[1]: v2}
                break
    out["unit"] = unit
    return out


def extract_borrowings(text: str, page: int, unit: str = "ZAR_million", scale: float = 1e6) -> Dict[str, Any]:
    """Extract total borrowings, non-current, current from Borrowings note."""
    fields = _extract_two_year_table(
        text,
        [
            r"total\s*borrowings|analysis\s*of\s*total\s*borrowings",
            r"non[- ]current\s*[\d\s]*$",
            r"current\s*[\d\s]*$",
            r"^\s*6\s*993\s+5\s*993\b",
        ],
        page,
        unit,
        scale,
    )
    # Fallback: look for "6 993 5 993" near borrowings
    if not fields:
        m = re.search(r"borrowings?\s+([\d\s]+)\s+([\d\s]+)", text, re.IGNORECASE)
        if m:
            v1, v2 = _to_float(m.group(1), scale), _to_float(m.group(2), scale)
            if v1 is not None or v2 is not None:
                fields["total_borrowings"] = {"2025": v1, "2024": v2}
    return {
        "type": "DEBT",
        "fields": fields,
        "evidence": [{"page": page, "quote": text[:500]}],
    }


def extract_leases(text: str, page: int, unit: str = "ZAR_million", scale: float = 1e6) -> Dict[str, Any]:
    """Extract lease liabilities totals from Lease note."""
    fields = _extract_two_year_table(
        text,
        [
            r"lease\s*liabilities?\s*(?:total|carrying)",
            r"balance\s*at\s*the\s*beginning\s*of\s*the\s*year",
            r"balance\s*at\s*the\s*end\s*of\s*the\s*year",
        ],
        page,
        unit,
        scale,
    )
    return {
        "type": "LEASES",
        "fields": fields,
        "evidence": [{"page": page, "quote": text[:500]}],
    }


def extract_contingencies(text: str, page: int, unit: str = "ZAR_million", scale: float = 1e6) -> Dict[str, Any]:
    """Extract contingent liabilities totals."""
    fields = _extract_two_year_table(
        text,
        [
            r"contingent\s*liabilities?\s+[\d\s]+",
            r"amounts?\s*arising\s*in\s*the\s*ordinary\s*course",
        ],
        page,
        unit,
        scale,
    )
    return {
        "type": "CONTINGENCIES",
        "fields": fields,
        "evidence": [{"page": page, "quote": text[:500]}],
    }


def extract_risk(text: str, page: int) -> Dict[str, Any]:
    """Extract gearing ratio, liquidity info from Risk note."""
    fields: Dict[str, Any] = {}
    m = re.search(r"gearing\s*ratio\s*[^\d]*(\d+\.?\d*)\s*%?\s*\(?(\d{4})[^\d]*(\d+\.?\d*)\s*%", text, re.IGNORECASE | re.DOTALL)
    if m:
        fields["gearing_ratio_pct"] = {
            "2025": float(m.group(1)),
            "2024": float(m.group(3)),
        }
    return {
        "type": "RISK",
        "fields": fields,
        "evidence": [{"page": page, "quote": text[:500]}],
    }


NOTE_TYPE_TO_EXTRACTOR = {
    "DEBT": extract_borrowings,
    "LEASES": extract_leases,
    "CONTINGENCIES": extract_contingencies,
    "borrowings": extract_borrowings,
    "leases": extract_leases,
    "contingencies": extract_contingencies,
    "risk": extract_risk,
}


def extract_note_by_type(
    note_type: str,
    text: str,
    page: int,
    unit: str = "ZAR_million",
    scale: float = 1e6,
) -> Dict[str, Any]:
    """
    Dispatch to the right extractor based on note_type.
    note_type: DEBT, LEASES, CONTINGENCIES, RISK, or packet packet_type (borrowings, leases, etc.)
    """
    fn = NOTE_TYPE_TO_EXTRACTOR.get(note_type.upper()) or NOTE_TYPE_TO_EXTRACTOR.get(note_type.lower())
    if not fn:
        return {"type": note_type, "fields": {}, "evidence": [{"page": page, "quote": text[:200]}]}
    if note_type.upper() == "RISK" or note_type.lower() == "risk":
        return extract_risk(text, page)
    return fn(text, page, unit, scale)
