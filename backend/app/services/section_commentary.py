"""
Institutional Section Commentary - 5-paragraph structured analysis per section.
Produces causal explanation, not metric repetition.
"""
from __future__ import annotations
from typing import Any

from app.services.memo_composer import _fmt as _fmt_num


def _para(parts: list[str]) -> str:
    """Join parts into a paragraph."""
    return " ".join(p for p in parts if p)


def _build_leverage_commentary(b: dict, covenant_block: dict | None, stress_scenarios: dict) -> str:
    """5-paragraph institutional leverage section."""
    km = b.get("key_metrics") or {}
    nd = km.get("net_debt_to_ebitda_incl_leases")
    ic = km.get("ebitda_to_interest")
    nd_ex = km.get("net_debt_ex_leases")
    by_period = b.get("by_period") or {}
    periods = sorted(by_period.keys(), reverse=True)[:2]
    prev_nd = by_period.get(periods[1], {}).get("net_debt_to_ebitda_incl_leases") if len(periods) >= 2 else None

    p1 = []  # Performance Summary
    p1.append(f"Net debt/EBITDA (incl. leases) is {nd:.2f}x" if nd is not None else "Leverage metrics available.")
    if prev_nd is not None and nd is not None:
        delta = nd - prev_nd
        p1.append(f", {'increasing' if delta > 0 else 'decreasing'} from {prev_nd:.2f}x in the prior period.")
    else:
        p1.append(".")
    if ic is not None:
        p1.append(f" Interest cover stands at {ic:.2f}x.")

    p2 = []  # Key Drivers of Change
    if prev_nd is not None and nd is not None and nd != prev_nd:
        p2.append(f"The {'increase' if nd > prev_nd else 'decrease'} in leverage reflects ")
        p2.append("higher debt and/or lower EBITDA." if nd > prev_nd else "debt reduction and/or EBITDA improvement.")
    if nd_ex is not None and nd_ex < 0:
        p2.append(" Net debt ex-leases is negative (cash exceeds debt); lease-adjusted leverage remains material due to IFRS 16 adoption.")

    p3 = []  # Structural vs Cyclical
    if nd is not None:
        p3.append(f"Leverage of {nd:.2f}x is ")
        p3.append("structurally elevated and inconsistent with investment-grade metrics." if nd > 4 else "moderate but warrants monitoring.")

    p4 = []  # Risk Implications
    cov_km = (covenant_block or {}).get("key_metrics") or {}
    lev_max = cov_km.get("covenant_leverage_max")
    if lev_max is not None and nd is not None and nd >= lev_max:
        p4.append(f"Current leverage exceeds covenant threshold of {lev_max:.1f}x, indicating breach risk.")
    elif lev_max is not None and nd is not None:
        headroom = cov_km.get("leverage_headroom_pct")
        if headroom is not None and headroom < 20:
            p4.append(f"Limited headroom ({headroom:.1f}%) to covenant limit.")
    for name, sc in (stress_scenarios or {}).items():
        nd_s = sc.get("net_debt_to_ebitda_stressed")
        if nd_s is not None and nd_s >= 6:
            p4.append(f" Under a 10% revenue stress scenario leverage increases to {nd_s:.2f}x.")
            break

    p5 = []  # Rating Impact Statement
    rating = b.get("section_rating", "Adequate")
    p5.append(f"The leverage profile is {rating.lower()} and ")
    p5.append("constrains the rating through governance caps." if nd and nd > 5 else "is factored into the section score.")

    paras = [_para(p1), _para(p2), _para(p3), _para(p4), _para(p5)]
    return "\n\n".join(p for p in paras if p.strip())


def _build_liquidity_commentary(b: dict) -> str:
    """5-paragraph institutional liquidity section."""
    km = b.get("key_metrics") or {}
    coverage = km.get("liquidity_coverage_ratio")
    cr = km.get("current_ratio")
    cash = km.get("cash")
    st_debt = km.get("st_debt")
    surplus = km.get("liquidity_surplus_12m")

    p1 = []
    if coverage is not None:
        p1.append(f"12-month forward liquidity coverage (sources/uses) is {coverage:.2f}x.")
    else:
        p1.append(f"Current ratio is {cr:.2f}x." if cr is not None else "Liquidity metrics available.")
    if surplus is not None:
        p1.append(f" Liquidity surplus over 12 months: {_fmt_num(surplus)}.")

    p2 = []
    if cash is not None and st_debt is not None:
        p2.append(f"Opening cash of {_fmt_num(cash)} against ST debt of {_fmt_num(st_debt)} ")
        p2.append("implies reliance on undrawn facilities or operating cash flow to meet maturities." if st_debt > cash else "provides a buffer for short-term obligations.")

    p3 = []
    if coverage is not None:
        if coverage >= 1.5:
            p3.append("Liquidity is structurally strong with adequate sources to cover uses.")
        elif coverage >= 1.0:
            p3.append("Liquidity is adequate but with limited headroom; refinancing execution risk is material.")
        else:
            p3.append("Liquidity is critical; sources are insufficient to cover 12-month uses.")

    p4 = []
    if cr is not None and cr < 1.0:
        p4.append("Current ratio below 1.0x indicates short-term obligations exceed liquid assets.")
    if km.get("st_debt_to_cash") and km["st_debt_to_cash"] > 5:
        p4.append(" ST debt to cash above 5x indicates elevated refinancing risk.")

    p5 = []
    rating = b.get("section_rating", "Adequate")
    p5.append(f"The liquidity profile is {rating.lower()} and influences the rating through governance caps where applicable.")

    paras = [_para(p1), _para(p2), _para(p3), _para(p4), _para(p5)]
    return "\n\n".join(p for p in paras if p.strip())


def _build_performance_commentary(b: dict) -> str:
    """5-paragraph institutional financial performance section."""
    km = b.get("key_metrics") or {}
    rev = km.get("revenue")
    rev_g = km.get("revenue_growth_pct")
    margin = km.get("ebitda_margin_pct")
    cfo_ebitda = km.get("cfo_to_ebitda")
    fcf = km.get("fcf_conversion")

    p1 = []
    if rev is not None:
        p1.append(f"Revenue of {_fmt_num(rev)}")
    if rev_g is not None:
        p1.append(f" grew {rev_g:.1f}% YoY" if p1 else f"Revenue grew {rev_g:.1f}% YoY")
    p1.append("." if p1 else "Financial performance metrics available.")
    if margin is not None:
        p1.append(f" EBITDA margin is {margin:.1f}%.")

    p2 = []
    if cfo_ebitda is not None and cfo_ebitda > 1:
        p2.append(f"CFO/EBITDA of {cfo_ebitda:.2f}x indicates strong cash conversion from earnings.")
    if fcf is not None and fcf > 0:
        p2.append(f" FCF conversion supports debt service capacity.")

    p3 = []
    if margin is not None:
        p3.append(f"EBITDA margin of {margin:.1f}% reflects operating efficiency and pricing power.")

    p4 = []
    p4.append("Revenue concentration and cyclicality are assessed in the business risk section.")

    p5 = []
    rating = b.get("section_rating", "Adequate")
    p5.append(f"Financial performance is {rating.lower()} and contributes to the overall section-weighted score.")

    paras = [_para(p1), _para(p2), _para(p3), _para(p4), _para(p5)]
    return "\n\n".join(p for p in paras if p.strip())


def _build_stress_commentary(b: dict) -> str:
    """5-paragraph institutional stress section."""
    scenarios = (b.get("key_metrics") or {}).get("scenarios") or {}
    flags = b.get("risk_flags") or []

    p1 = []
    p1.append("Stress scenarios demonstrate sensitivity to revenue, interest rates, and working capital.")

    p2 = []
    for name, sc in list(scenarios.items())[:3]:
        nd_s = sc.get("net_debt_to_ebitda_stressed")
        ic_s = sc.get("interest_cover_stressed")
        if nd_s is not None:
            p2.append(f"Under {name}, ND/EBITDA reaches {nd_s:.2f}x.")
        if ic_s is not None:
            p2.append(f" Interest cover falls to {ic_s:.2f}x.")

    p3 = []
    p3.append("Combined stress (revenue + interest) shows the extent of rating pressure under a downside scenario.")

    p4 = []
    if flags:
        p4.append("Risk implications: " + "; ".join(flags[:3]))
    else:
        p4.append("Stress outcomes influence the final rating through notch adjustments where thresholds are breached.")

    p5 = []
    rating = b.get("section_rating", "Adequate")
    p5.append(f"Stress resilience is {rating.lower()}. Breaches under stress trigger governance notch downgrades.")

    paras = [_para(p1), _para(p2), _para(p3), _para(p4), _para(p5)]
    return "\n\n".join(p for p in paras if p.strip())


def _build_covenant_commentary(b: dict) -> str:
    """5-paragraph institutional covenant section."""
    km = b.get("key_metrics") or {}
    lev_hr = km.get("leverage_headroom_pct")
    cov_hr = km.get("coverage_headroom_pct")
    lev_breach = km.get("leverage_breach")
    ic_breach = km.get("interest_cover_breach")
    lev_max = km.get("covenant_leverage_max")
    ic_min = km.get("covenant_interest_cover_min")

    p1 = []
    if lev_max is not None and ic_min is not None:
        p1.append(f"Covenant terms: max leverage {lev_max:.1f}x, min interest cover {ic_min:.1f}x.")
    if lev_breach or ic_breach:
        p1.append(" Current metrics indicate covenant breach.")

    p2 = []
    if lev_hr is not None:
        p2.append(f"Leverage headroom: {lev_hr:.1f}% to covenant limit.")
    if cov_hr is not None:
        p2.append(f" Interest cover headroom: {cov_hr:.1f}%.")

    p3 = []
    if lev_breach or ic_breach:
        p3.append("Breach triggers rating cap under governance (max BB-).")
    elif lev_hr is not None and lev_hr < 20:
        p3.append("Limited headroom increases refinancing and covenant compliance risk.")

    p4 = []
    p4.append("Refer to Note 48 (borrowings) and Note 43.4.3 for covenant terms and cure rights.")

    p5 = []
    rating = b.get("section_rating", "Adequate")
    p5.append(f"Covenant headroom is {rating.lower()} and directly influences the final rating where breach applies.")

    paras = [_para(p1), _para(p2), _para(p3), _para(p4), _para(p5)]
    return "\n\n".join(p for p in paras if p.strip())


def add_section_commentary(
    section_blocks: dict[str, dict[str, Any]],
    aggregation: dict[str, Any],
    company_name: str = "",
) -> None:
    """
    Add institutional 5-paragraph llm_commentary to each section block. In-place.
    Structure: Performance Summary | Key Drivers | Structural vs Cyclical | Risk Implications | Rating Impact.
    """
    stress_scenarios = (section_blocks.get("stress", {}).get("key_metrics") or {}).get("scenarios") or {}
    covenant_block = section_blocks.get("covenants")

    if "leverage" in section_blocks:
        section_blocks["leverage"]["llm_commentary"] = _build_leverage_commentary(
            section_blocks["leverage"], covenant_block, stress_scenarios
        )

    if "liquidity" in section_blocks:
        section_blocks["liquidity"]["llm_commentary"] = _build_liquidity_commentary(
            section_blocks["liquidity"]
        )

    if "financial_performance" in section_blocks:
        section_blocks["financial_performance"]["llm_commentary"] = _build_performance_commentary(
            section_blocks["financial_performance"]
        )

    if "stress" in section_blocks:
        section_blocks["stress"]["llm_commentary"] = _build_stress_commentary(
            section_blocks["stress"]
        )

    if "covenants" in section_blocks:
        section_blocks["covenants"]["llm_commentary"] = _build_covenant_commentary(
            section_blocks["covenants"]
        )

    # Shorter institutional format for business_risk and accounting_quality
    if "business_risk" in section_blocks:
        b = section_blocks["business_risk"]
        rev_g = (b.get("key_metrics") or {}).get("revenue_growth_pct")
        rev = (b.get("key_metrics") or {}).get("revenue")
        rating = b.get("section_rating", "Adequate")
        p1 = f"Business risk is {rating.lower()}."
        p2 = f"Revenue of {_fmt_num(rev)} grew {rev_g:.1f}% YoY." if rev is not None and rev_g is not None else ""
        p3 = "Key drivers: scale, diversification, and market position influence the section score."
        b["llm_commentary"] = "\n\n".join(p for p in [p1, p2, p3] if p)

    if "accounting_quality" in section_blocks:
        b = section_blocks["accounting_quality"]
        areas = (b.get("key_metrics") or {}).get("accounting_risk_areas_count", 0)
        rating = b.get("section_rating", "Adequate")
        b["llm_commentary"] = (
            f"Accounting and disclosure quality is {rating.lower()}. "
            + (f"{areas} accounting risk areas identified." if areas else "No material accounting risk areas.")
            + " Financial statements follow IFRS with appropriate disclosure. Rating impact is through the section-weighted score."
        )
