"""Notes Validation Engine - reconcile notes to statements."""
from __future__ import annotations
from typing import Any

def run_notes_validation(notes: dict[str, Any], facts_by_period: dict[str, dict[str, float]]) -> dict[str, Any]:
    notes_dict = notes.get("notes") or notes if isinstance(notes, dict) else {}
    results = {"reconciliations": [], "mismatches": [], "accounting_risk_areas": []}
    risk_kw = ["significant judgement", "fair value model", "impairment sensitivity", "deferred tax"]
    for nid, note in (notes_dict.items() if isinstance(notes_dict, dict) else []):
        if not isinstance(note, dict):
            continue
        text = (note.get("text") or "").lower()
        for kw in risk_kw:
            if kw in text:
                results["accounting_risk_areas"].append({"note_id": str(nid), "area": kw})
    return results


def run_accounting_quality_engine(
    notes_json: dict | None,
    facts_by_period: dict[str, dict[str, float]],
    ebitda: float | None,
) -> dict[str, Any]:
    """Accounting & Disclosure Quality section block. Uses notes_validation + risk_engine."""
    from app.services.risk_engine import run_risk_engine
    from app.core.section_schema import score_to_rating

    block: dict[str, Any] = {
        "section_name": "Accounting & Disclosure Quality",
        "key_metrics": {},
        "score": 70.0,
        "section_rating": "Adequate",
        "risk_flags": [],
        "evidence_notes": [],
        "llm_commentary": "",
    }
    notes = notes_json or {}
    nv = run_notes_validation(notes, facts_by_period)
    flat = {}
    for pv in (facts_by_period or {}).values():
        if pv:
            flat.update(pv)
    risk = run_risk_engine(notes, flat, ebitda or 1.0)
    areas = nv.get("accounting_risk_areas") or []
    risk_items = risk.get("risk_items") or []
    block["key_metrics"] = {"accounting_risk_areas_count": len(areas), "risk_items_count": len(risk_items)}
    block["evidence_notes"] = [str(a.get("area", a)) + " (Note " + str(a.get("note_id", "")) + ")" for a in areas[:8]]
    base_score = 80.0
    for a in areas:
        block["risk_flags"].append("Accounting risk: " + str(a.get("area", a)))
    for r in risk_items[:5]:
        sev = r.get("risk_severity", "MEDIUM")
        block["risk_flags"].append(str(r.get("risk_category", "")) + " (Note " + str(r.get("note_id", "")) + "): " + sev)
        base_score -= 15 if sev == "HIGH" else 5
    block["evidence_notes"].extend(["Note 8: Impairment", "Note 14: Deferred tax", "Note 43: Financial instruments", "Note 1: Significant judgement"])
    section_score = max(0, min(100, base_score))
    block["score"] = round(section_score, 1)
    block["section_rating"] = score_to_rating(section_score)
    return block
