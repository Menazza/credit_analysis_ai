"""
Commentary Engine - controlled LLM layer.
Interprets metrics, explains movements, references note findings.
MUST NOT: calculate, decide rating, modify numbers.
Inputs: metrics, trend, liquidity, leverage, stress, risk, notes validation, rating.
Output: structured section text only.
"""
from __future__ import annotations
from typing import Any

def build_commentary_sections(
    company_name: str,
    rating_grade: str | None,
    metrics: dict[str, Any],
    trend: dict[str, Any],
    liquidity: dict[str, Any],
    leverage: dict[str, Any],
    stress: dict[str, Any],
    risk: dict[str, Any],
    notes_validation: dict[str, Any],
    use_llm: bool = False,
) -> dict[str, str]:
    """
    Build section commentary. use_llm=True would call LLM; default deterministic templates.
    LLM must receive structured JSON only and return structured text - no calculations.
    """
    sections = {}

    # Executive summary (deterministic template)
    name = company_name.strip() if company_name else "the company"
    lines = [f"Credit review for {name}. Internal rating: {rating_grade or 'N/A'}."]
    if trend.get("growth_diagnostics"):
        g = trend["growth_diagnostics"]
        if g.get("revenue_growth_pct") is not None:
            lines.append(f"Revenue growth: {g['revenue_growth_pct']:.1f}% YoY.")
        if g.get("ebitda_growth_pct") is not None:
            lines.append(f"EBITDA growth: {g['ebitda_growth_pct']:.1f}% YoY.")
    if leverage.get("by_period"):
        lp = list(leverage["by_period"].values())[0]
        if lp.get("net_debt_to_ebitda_incl_leases") is not None:
            lines.append(f"Net debt/EBITDA (incl. leases): {lp['net_debt_to_ebitda_incl_leases']:.2f}x.")
    sections["executive_summary"] = " ".join(lines)

    # Financial risk
    lines = []
    if stress.get("scenarios"):
        for name, sc in stress["scenarios"].items():
            if sc.get("interest_cover_stressed"):
                lines.append(f"Under {name}: Interest cover stressed to {sc['interest_cover_stressed']:.2f}x.")
    sections["financial_risk"] = " ".join(lines) if lines else "Stress scenarios computed. See stress output for details."

    # Liquidity & Leverage
    parts = []
    if liquidity.get("by_period"):
        lp = list(liquidity["by_period"].values())[0]
        cr = lp.get("current_ratio")
        qr = lp.get("quick_ratio")
        cash = lp.get("cash")
        st_debt = lp.get("st_debt")
        runway = lp.get("liquidity_runway_months")
        if cr is not None:
            parts.append(f"Current ratio: {cr:.2f}x")
        if qr is not None:
            parts.append(f"Quick ratio: {qr:.2f}x")
        if cash is not None:
            parts.append(f"Cash: {cash:,.0f}")
        if runway is not None:
            parts.append(f"Runway: {runway:.1f} months")
    if leverage.get("by_period"):
        lp = list(leverage["by_period"].values())[0]
        nd = lp.get("net_debt_incl_leases")
        nd_eb = lp.get("net_debt_to_ebitda_incl_leases")
        if nd is not None:
            parts.append(f"Net debt (incl. leases): {nd:,.0f}")
        if nd_eb is not None:
            parts.append(f"ND/EBITDA: {nd_eb:.2f}x")
    sections["liquidity_leverage"] = ". ".join(parts) if parts else "Liquidity metrics available in output."

    # Key risks (from risk engine)
    if risk.get("risk_items"):
        items = [f"{r['risk_category']} (Note {r['note_id']}): {r['risk_severity']}" for r in risk["risk_items"][:5]]
        sections["key_risks"] = "Risks identified: " + "; ".join(items)
    else:
        sections["key_risks"] = "Risk scoring applied. See risk output for details."

    # Accounting quality
    if notes_validation.get("accounting_risk_areas"):
        areas = [a["area"] for a in notes_validation["accounting_risk_areas"][:5]]
        sections["accounting_disclosure_quality"] = "Accounting risk areas: " + ", ".join(areas)
    else:
        sections["accounting_disclosure_quality"] = "Notes validation complete. No material accounting flags."

    return sections
