"""
Phase 6: Reconciliation checks + scale/units.

- Compare SOFP "Borrowings" vs Note 21 (DEBT) total.
- Compare SOFP "Lease liabilities" vs Note 20 (LEASES) total.
- Flag mismatches in validation results.
- Scale/unit validation: ensure we compare like-for-like.
"""
from __future__ import annotations

from typing import Any

BORROWINGS_KEYS = frozenset({
    "short_term_borrowings",
    "current_portion_long_term_debt",
    "long_term_borrowings",
})

LEASE_LIABILITY_KEYS = frozenset({
    "lease_liabilities_current",
    "lease_liabilities_non_current",
})

# Relative tolerance for numeric comparison (e.g. 0.01 = 1%)
RECONCILIATION_TOLERANCE = 0.02


def _get_canonical_key(raw_label: str, canonical_mappings: list[dict] | None) -> str | None:
    """Resolve raw_label to canonical_key via canonical_mappings."""
    if not canonical_mappings:
        return None
    mappings = canonical_mappings
    if isinstance(canonical_mappings, dict) and "mappings" in canonical_mappings:
        mappings = canonical_mappings["mappings"]
    if not isinstance(mappings, list):
        return None
    raw_lower = (raw_label or "").strip().lower()
    for m in mappings:
        if isinstance(m, dict):
            ml = (m.get("raw_label") or "").strip().lower()
            ck = m.get("canonical_key")
            if ml and ck and ml == raw_lower:
                return str(ck) if ck != "UNMAPPED" else None
    return None


def _sum_statement_values(
    lines: list[Any],
    period_labels: list[str],
    canonical_mappings: list[dict] | None,
    target_keys: frozenset[str],
) -> dict[str, float]:
    """
    Sum values_json across lines whose canonical_key (from raw_label mapping) is in target_keys.
    Returns {period_label: total} per period.
    """
    totals: dict[str, float] = {}
    for line in lines or []:
        raw_label = getattr(line, "raw_label", None) or ""
        ck = _get_canonical_key(raw_label, canonical_mappings)
        if ck not in target_keys:
            continue
        values_json = getattr(line, "values_json", None) or {}
        for lbl in period_labels:
            v = values_json.get(lbl)
            if v is None:
                continue
            try:
                num = float(v) if not isinstance(v, (int, float)) else float(v)
            except (ValueError, TypeError):
                continue
            totals[lbl] = totals.get(lbl, 0) + num
    return totals


def _get_note_values(
    note_extractions: list[Any],
    note_type: str,
    field_keys: list[str],
) -> dict[str, float]:
    """
    Extract field values from NoteExtraction for given note_type (DEBT, LEASES).
    field_keys: e.g. ["total_borrowings"] for DEBT, or ["lease_liabilities", ...] for LEASES.
    Returns {period_label: value} (uses first matching extraction).
    """
    out: dict[str, float] = {}
    for ne in note_extractions or []:
        ev = getattr(ne, "evidence_json", None) or {}
        ext = ev.get("extraction", ev)
        if ext.get("type") != note_type:
            continue
        fields = ext.get("fields", {})
        for fk in field_keys:
            val = fields.get(fk)
            if val is None:
                continue
            if isinstance(val, dict) and fk != "unit":
                for k, v in val.items():
                    if k in ("unit",):
                        continue
                    if isinstance(v, (int, float)):
                        try:
                            out[str(k)] = float(v)
                        except (ValueError, TypeError):
                            pass
            break
        if out:
            break
    return out


def _compare_values(
    sofp: dict[str, float],
    note: dict[str, float],
    scale_factor: float | None,
) -> list[dict]:
    """
    Compare SOFP totals vs note totals per period.
    Returns list of {period, sofp_value, note_value, match, diff_pct, message}.
    """
    results = []
    periods = sorted(set(sofp.keys()) | set(note.keys()))
    for p in periods:
        sv = sofp.get(p)
        nv = note.get(p)
        if sv is None and nv is None:
            continue
        if sv is None:
            results.append({
                "period": p,
                "sofp_value": None,
                "note_value": nv,
                "match": False,
                "diff_pct": None,
                "message": "SOFP value missing",
            })
            continue
        if nv is None:
            results.append({
                "period": p,
                "sofp_value": sv,
                "note_value": None,
                "match": False,
                "diff_pct": None,
                "message": "Note value missing",
            })
            continue
        denom = abs(nv) if nv else 1
        diff_pct = abs(sv - nv) / denom if denom else 0
        match = diff_pct <= RECONCILIATION_TOLERANCE
        results.append({
            "period": p,
            "sofp_value": sv,
            "note_value": nv,
            "match": match,
            "diff_pct": round(diff_pct * 100, 2),
            "message": "OK" if match else f"Mismatch: {diff_pct * 100:.1f}% difference",
        })
    return results


def run_reconciliation(
    statements: list[Any],
    canonical_mappings: dict | list | None,
    note_extractions: list[Any],
    scale_factor: float | None = None,
    currency: str | None = None,
    scale: str | None = None,
) -> dict[str, Any]:
    """
    Run reconciliation checks for a document version.

    Inputs:
    - statements: Statement objects with .lines (StatementLine), .periods_json, .statement_type
    - canonical_mappings: from PresentationContext scope_key=canonical_mappings (evidence_json)
    - note_extractions: NoteExtraction objects with evidence_json
    - scale_factor, currency, scale: from presentation_scale

    Returns:
    - {
        "checks": [
          {"item": "borrowings", "period_results": [...], "overall_match": bool},
          {"item": "lease_liabilities", "period_results": [...], "overall_match": bool},
        ],
        "scale_validation": {"currency": ..., "scale": ..., "scale_factor": ...},
        "warnings": ["..."]
      }
    """
    checks = []
    warnings = []

    # Resolve canonical_mappings structure
    cm = canonical_mappings
    if isinstance(cm, dict) and "mappings" in cm:
        cm = cm.get("mappings")

    # Get SFP statement and period labels
    sfp = None
    period_labels: list[str] = []
    for stmt in statements or []:
        if getattr(stmt, "statement_type", "") == "SFP":
            sfp = stmt
            periods_json = getattr(stmt, "periods_json", None) or []
            period_labels = [p.get("label", str(i)) for i, p in enumerate(periods_json)]
            break

    if not sfp:
        return {
            "checks": [],
            "scale_validation": {"currency": currency, "scale": scale, "scale_factor": scale_factor},
            "warnings": ["No SFP statement found"],
        }

    lines = list(getattr(sfp, "lines", []))

    # Borrowings: SOFP vs Note DEBT
    sofp_borrowings = _sum_statement_values(lines, period_labels, cm, BORROWINGS_KEYS)
    note_borrowings = _get_note_values(note_extractions, "DEBT", ["total_borrowings"])
    br_results = _compare_values(sofp_borrowings, note_borrowings, scale_factor)
    if not sofp_borrowings and not note_borrowings:
        warnings.append("Borrowings: no SOFP or note data to reconcile")
    checks.append({
        "item": "borrowings",
        "sofp_keys": list(BORROWINGS_KEYS),
        "period_results": br_results,
        "overall_match": all(r.get("match", False) for r in br_results) if br_results else None,
    })

    # Lease liabilities: SOFP vs Note LEASES
    sofp_leases = _sum_statement_values(lines, period_labels, cm, LEASE_LIABILITY_KEYS)
    note_leases = _get_note_values(
        note_extractions,
        "LEASES",
        ["lease_liabilities", "lease_liabilities_total", "carrying_amount", "balance_at_end"],
    )
    lr_results = _compare_values(sofp_leases, note_leases, scale_factor)
    if not sofp_leases and not note_leases:
        warnings.append("Lease liabilities: no SOFP or note data to reconcile")
    checks.append({
        "item": "lease_liabilities",
        "sofp_keys": list(LEASE_LIABILITY_KEYS),
        "period_results": lr_results,
        "overall_match": all(r.get("match", False) for r in lr_results) if lr_results else None,
    })

    return {
        "checks": checks,
        "scale_validation": {
            "currency": currency,
            "scale": scale,
            "scale_factor": scale_factor,
        },
        "warnings": warnings,
    }
