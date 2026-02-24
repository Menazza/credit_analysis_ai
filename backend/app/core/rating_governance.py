"""
Rating Governance Algorithm - Base → Hard Caps → Stress Notch → Final Rating.
Turns weighted scoring into bank-grade, governed ratings.
"""
from __future__ import annotations
from typing import Any

# Full rating scale (best to worst)
RATING_ORDER = [
    "AAA", "AA+", "AA", "AA-",
    "A+", "A", "A-",
    "BBB+", "BBB", "BBB-",
    "BB+", "BB", "BB-",
    "B+", "B", "B-",
    "CCC",
]


def _idx(grade: str) -> int:
    """Index in RATING_ORDER (0 = best). Higher index = worse."""
    for i, g in enumerate(RATING_ORDER):
        if g == grade:
            return i
    return len(RATING_ORDER) - 1  # Unknown = worst


def _notch_down(grade: str, n: int = 1) -> str:
    """Downgrade by n notches (worse rating)."""
    i = min(_idx(grade) + n, len(RATING_ORDER) - 1)
    return RATING_ORDER[i]


def _score_to_base_grade(score: float) -> str:
    """Map 0–100 score to base letter grade per spec."""
    if score >= 85:
        return "AA"
    if score >= 75:
        return "A"
    if score >= 65:
        return "BBB"
    if score >= 55:
        return "BB"
    if score >= 45:
        return "B"
    return "CCC"


def _apply_hard_caps(
    base_grade: str,
    section_blocks: dict,
    covenant_block: dict | None,
    notes_json: dict | None,
) -> tuple[str, list[str]]:
    """
    Step 2: Hard rating caps. Returns (capped_grade, list of applied rules).
    """
    grade = base_grade
    applied: list[str] = []

    lev = section_blocks.get("leverage", {}) or {}
    lev_km = lev.get("key_metrics") or {}
    nd_ebitda = lev_km.get("net_debt_to_ebitda_incl_leases")
    ic = lev_km.get("ebitda_to_interest")

    liq = section_blocks.get("liquidity", {}) or {}
    liq_km = liq.get("key_metrics") or {}
    cr = liq_km.get("current_ratio")
    st_debt_to_cash = liq_km.get("st_debt_to_cash")

    # Leverage caps
    if nd_ebitda is not None:
        if nd_ebitda >= 6.0 and _idx(grade) < _idx("B"):
            grade = "B"
            applied.append("ND/EBITDA ≥ 6.0x cap B")
        elif nd_ebitda >= 5.0 and _idx(grade) < _idx("BB"):
            grade = "BB"
            applied.append("ND/EBITDA ≥ 5.0x cap BB")
        elif nd_ebitda >= 4.0 and _idx(grade) < _idx("BBB-"):
            grade = "BBB-"
            applied.append("ND/EBITDA ≥ 4.0x cap BBB-")

    # Coverage caps
    if ic is not None:
        if ic < 1.5 and _idx(grade) < _idx("B+"):
            grade = "B+"
            applied.append("Interest cover < 1.5x cap B+")
        elif ic < 2.0 and _idx(grade) < _idx("BB+"):
            grade = "BB+"
            applied.append("Interest cover < 2.0x cap BB+")

    # Liquidity caps
    if cr is not None and cr < 0.8 and _idx(grade) < _idx("BB"):
        grade = "BB"
        applied.append("Current ratio < 0.8x cap BB")
    if st_debt_to_cash is not None and st_debt_to_cash > 5.0 and _idx(grade) < _idx("BB-"):
        grade = "BB-"
        applied.append("ST debt/cash > 5x cap BB-")

    # Covenant breach caps
    if covenant_block:
        cov_km = covenant_block.get("key_metrics") or {}
        lev_breach = cov_km.get("leverage_breach")
        ic_breach = cov_km.get("interest_cover_breach")
        if lev_breach or ic_breach:
            if _idx(grade) < _idx("BB-"):
                grade = "BB-"
                applied.append("Covenant breach cap BB-")

    # Going concern override
    notes_dict = (notes_json or {}).get("notes") or notes_json
    if isinstance(notes_dict, dict):
        for nid, note in notes_dict.items():
            if not isinstance(note, dict):
                continue
            text = (note.get("text") or "").lower()[:8000]
            if "going concern" in text and ("doubt" in text or "material uncertainty" in text):
                if _idx(grade) < _idx("B"):
                    grade = "B"
                    applied.append("Note 48 going concern cap B")
                break

    return grade, applied


def _stress_notch_adjustment(
    grade: str,
    stress_scenarios: dict,
) -> tuple[str, list[str]]:
    """
    Step 3: Stress notch adjustment. Returns (adjusted_grade, list of applied notches).
    Single breach → -1 notch. Combined breach (2+ conditions) → -2 notches.
    """
    breach_flags: list[str] = []
    for name, sc in (stress_scenarios or {}).items():
        nd_s = sc.get("net_debt_to_ebitda_stressed")
        ic_s = sc.get("interest_cover_stressed")
        cash_s = sc.get("cash_after_shock")

        if nd_s is not None and nd_s >= 6.0:
            breach_flags.append("ND/EBITDA ≥ 6x")
        if ic_s is not None and ic_s < 2.0:
            breach_flags.append("Interest cover < 2x")
        if cash_s is not None and cash_s < 0:
            breach_flags.append("Cash negative")

    notches = 0
    applied: list[str] = []
    if breach_flags:
        notches = 2 if len(breach_flags) >= 2 else 1
        applied.append(f"Stress breach ({', '.join(breach_flags[:3])}): -{notches} notch(es)")
    notches = min(notches, 3)
    for _ in range(notches):
        grade = _notch_down(grade, 1)
    return grade, applied


def apply_governance(
    base_score: float,
    section_blocks: dict,
    covenant_block: dict | None,
    stress_output: dict | None,
    notes_json: dict | None,
) -> dict[str, Any]:
    """
    Full rating governance: Base → Hard Caps → Stress Notch → Final.

    Returns:
        final_grade, base_grade, hard_cap_grade, applied_rules
    """
    base_grade = _score_to_base_grade(base_score)
    hard_cap_grade, cap_rules = _apply_hard_caps(
        base_grade, section_blocks, covenant_block, notes_json
    )
    stress_scenarios = (stress_output or {}).get("scenarios") or {}
    final_grade, stress_rules = _stress_notch_adjustment(hard_cap_grade, stress_scenarios)

    applied = cap_rules + stress_rules
    return {
        "final_grade": final_grade,
        "base_grade": base_grade,
        "hard_cap_grade": hard_cap_grade,
        "applied_rules": applied,
    }
