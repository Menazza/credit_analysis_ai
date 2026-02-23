"""Rating Governance - hard caps, override rules. Deterministic."""
from __future__ import annotations
from typing import Any

RATING_ORDER = ["AAA","AA+","AA","AA-","A+","A","A-","BBB+","BBB","BBB-","BB+","BB","BB-","B+","B","B-","CCC"]

def _idx(g: str) -> int:
    return RATING_ORDER.index(g) if g in RATING_ORDER else 0

def _notch_down(grade: str, n: int = 1) -> str:
    i = min(_idx(grade) + n, len(RATING_ORDER) - 1)
    return RATING_ORDER[i]

def apply_governance(base_grade: str, section_blocks: dict, covenant_block: dict | None, stress_output: dict | None, notes_json: dict | None) -> dict:
    grade = base_grade
    applied = []
    lev = section_blocks.get("leverage", {})
    lev_score = lev.get("score", 100)
    nd_ebitda = (lev.get("key_metrics") or {}).get("net_debt_to_ebitda_incl_leases")
    ic = (lev.get("key_metrics") or {}).get("ebitda_to_interest")
    if lev_score is not None and lev_score < 30:
        if _idx(grade) < _idx("BB"): grade = "BB"; applied.append("Leverage score <30 cap BB")
    if nd_ebitda is not None and nd_ebitda > 5.0:
        if _idx(grade) < _idx("BB"): grade = "BB"; applied.append("ND/EBITDA >5x cap BB")
    if ic is not None and ic < 1.5:
        if _idx(grade) < _idx("B+"): grade = "B+"; applied.append("Interest cover <1.5x cap B+")
    if covenant_block and covenant_block.get("risk_flags"):
        breach = any("breach" in str(f).lower() or "at or above" in str(f).lower() for f in covenant_block["risk_flags"])
        if breach and _idx(grade) < _idx("BB-"): grade = "BB-"; applied.append("Covenant breach cap BB-")
    notes = (notes_json or {}).get("notes") or notes_json
    if isinstance(notes, dict):
        for n, v in notes.items():
            if isinstance(v, dict) and "going concern" in (v.get("text") or "").lower() and "doubt" in (v.get("text") or "").lower():
                if _idx(grade) < _idx("B"): grade = "B"; applied.append("Going concern cap B")
                break
    if stress_output:
        for name, sc in (stress_output.get("scenarios") or {}).items():
            nd = sc.get("net_debt_to_ebitda_stressed")
            if nd is not None and nd > 6.0:
                grade = _notch_down(grade, 1)
                applied.append(f"Stress ND>6x downgrade 1 notch")
                break
    return {"final_grade": grade, "base_grade": base_grade, "applied_rules": applied}
