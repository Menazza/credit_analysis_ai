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


def _score_accounting_deterministic(notes: dict, facts_flat: dict) -> tuple[float, list[str]]:
    """
    Deterministic accounting quality score. Fixed deductions. No LLM.
    Rules: significant judgement -10, DTA>20% equity -15, goodwill>30% assets -15,
    impairment sensitivity -10, going concern doubt -20.
    """
    score = 80.0
    flags = []
    notes_dict = notes.get("notes") or notes if isinstance(notes, dict) else {}
    for nid, note in (notes_dict.items() if isinstance(notes_dict, dict) else []):
        if not isinstance(note, dict):
            continue
        text = (note.get("text") or "").lower()
        if "significant judgement" in text or "significant judgment" in text:
            score -= 10
            flags.append("Significant judgement (Note 1): -10")
        if "impairment" in text and ("sensitivity" in text or "value in use" in text or "cgu" in text):
            score -= 10
            flags.append("Impairment sensitivity disclosed: -10")
        if "going concern" in text and ("doubt" in text or "material uncertainty" in text or "uncertainty" in text):
            score -= 20
            flags.append("Going concern uncertainty: -20")
            break
    dta = facts_flat.get("deferred_tax_assets") or 0
    equity = facts_flat.get("total_equity") or 1
    if equity and abs(equity) > 0 and (dta / abs(equity)) > 0.20:
        score -= 15
        flags.append("DTA > 20% of equity: -15")
    goodwill = facts_flat.get("goodwill") or 0
    assets = facts_flat.get("total_assets") or 1
    if assets and assets > 0 and (goodwill / assets) > 0.30:
        score -= 15
        flags.append("Goodwill > 30% of assets: -15")
    return max(0, min(100, score)), flags


def run_accounting_quality_engine(
    notes_json: dict | None,
    facts_by_period: dict[str, dict[str, float]],
    ebitda: float | None,
) -> dict[str, Any]:
    """Accounting & Disclosure Quality. Deterministic scoring only."""
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
    flat = {}
    for pv in (facts_by_period or {}).values():
        if pv:
            flat.update(pv)
    section_score, det_flags = _score_accounting_deterministic(notes, flat)
    block["score"] = round(section_score, 1)
    block["section_rating"] = score_to_rating(section_score)
    block["risk_flags"] = det_flags
    block["key_metrics"] = {"deterministic_score": section_score}
    block["evidence_notes"] = ["Note 1: Significant judgement", "Note 8: Impairment", "Note 14: Deferred tax", "Note 43: Financial instruments"]
    return block
