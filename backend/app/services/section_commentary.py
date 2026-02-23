"""
Section Commentary - deterministic interpretation of section blocks.
LLM never calculates, never overrides scores. Only explains.
"""
from __future__ import annotations
from typing import Any

def add_section_commentary(
    section_blocks: dict[str, dict[str, Any]],
    aggregation: dict[str, Any],
    company_name: str = "",
) -> None:
    """
    Add llm_commentary to each section block. In-place. Deterministic templates.
    """
    name = (company_name or "the company").strip()

    if "business_risk" in section_blocks:
        b = section_blocks["business_risk"]
        rating = b.get("section_rating", "Adequate")
        score = b.get("score", 50)
        flags = b.get("risk_flags", [])
        rev_g = b.get("key_metrics", {}).get("revenue_growth_pct")
        parts = [f"Business risk assessment: {rating} (score {score}/100)."]
        if rev_g is not None:
            parts.append(f"Revenue growth {rev_g:.1f}% YoY.")
        if flags:
            parts.append("Risks: " + "; ".join(flags[:3]))
        b["llm_commentary"] = " ".join(parts)

    if "financial_performance" in section_blocks:
        b = section_blocks["financial_performance"]
        rating = b.get("section_rating", "Adequate")
        margin = b.get("key_metrics", {}).get("ebitda_margin_pct")
        parts = [f"Financial performance: {rating}."]
        if margin is not None:
            parts.append(f"EBITDA margin {margin:.1f}%.")
        b["llm_commentary"] = " ".join(parts)

    if "liquidity" in section_blocks:
        b = section_blocks["liquidity"]
        rating = b.get("section_rating", "Adequate")
        cr = b.get("key_metrics", {}).get("current_ratio")
        cash = b.get("key_metrics", {}).get("cash")
        parts = [f"Liquidity: {rating}."]
        if cr is not None:
            parts.append(f"Current ratio {cr:.2f}x.")
        if cash is not None:
            parts.append(f"Cash {cash:,.0f}.")
        b["llm_commentary"] = " ".join(parts)

    if "leverage" in section_blocks:
        b = section_blocks["leverage"]
        rating = b.get("section_rating", "Adequate")
        nd = b.get("key_metrics", {}).get("net_debt_to_ebitda_incl_leases")
        ic = b.get("key_metrics", {}).get("ebitda_to_interest")
        parts = [f"Leverage: {rating}."]
        if nd is not None:
            parts.append(f"ND/EBITDA {nd:.2f}x.")
        if ic is not None:
            parts.append(f"Interest cover {ic:.2f}x.")
        b["llm_commentary"] = " ".join(parts)

    if "accounting_quality" in section_blocks:
        b = section_blocks["accounting_quality"]
        rating = b.get("section_rating", "Adequate")
        areas = b.get("key_metrics", {}).get("accounting_risk_areas_count", 0)
        b["llm_commentary"] = f"Accounting quality: {rating}. {areas} accounting risk areas identified."

    if "stress" in section_blocks:
        b = section_blocks["stress"]
        rating = b.get("section_rating", "Adequate")
        flags = b.get("risk_flags", [])
        b["llm_commentary"] = f"Stress resilience: {rating}." + (" Risks: " + "; ".join(flags[:2]) if flags else "")

    if "covenants" in section_blocks:
        b = section_blocks["covenants"]
        rating = b.get("section_rating", "Adequate")
        b["llm_commentary"] = f"Covenant headroom: {rating}. See Note 48 and 43.4.3."
