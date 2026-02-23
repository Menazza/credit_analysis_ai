"""Risk Scoring Engine - score risks from notes."""
from __future__ import annotations
import re
from typing import Any

def run_risk_engine(notes: dict[str, Any], facts: dict[str, float], ebitda: float | None) -> dict[str, Any]:
    notes_dict = notes.get("notes") or notes if isinstance(notes, dict) else {}
    ebitda = ebitda or 1.0
    results = {"risk_items": [], "triggers": [], "accounting_risk_flags": []}
    patterns = [
        ("impairment", r"impairment|value.in.use|cgu"),
        ("lease", r"lease|ifrs\s*16"),
        ("contingent", r"contingent|litigation|guarantee"),
        ("financial_instruments", r"fair\s*value|hedge|derivative"),
        ("going_concern", r"going\s*concern"),
        ("related_party", r"related\s*party"),
    ]
    for nid, note in (notes_dict.items() if isinstance(notes_dict, dict) else []):
        if not isinstance(note, dict):
            continue
        text = (note.get("text") or "")[:6000]
        for cat, pat in patterns:
            if re.search(pat, text, re.I):
                sev = "HIGH" if "material" in text.lower() or "significant" in text.lower() else "MEDIUM"
                results["risk_items"].append({
                    "risk_category": cat, "note_id": str(nid), "risk_severity": sev,
                    "materiality_score": 0.7 if sev == "HIGH" else 0.5, "quantitative_flag": bool(re.search(r"\d+[\.,]?\d*", text)),
                })
                break
    total_lease = (facts.get("lease_liabilities_current") or 0) + (facts.get("lease_liabilities_non_current") or 0)
    if total_lease > 0 and ebitda > 0 and (total_lease / ebitda) > 3.0:
        results["triggers"].append({"trigger": "lease_gt_3x_ebitda", "value": round(total_lease / ebitda, 2)})
    return results
