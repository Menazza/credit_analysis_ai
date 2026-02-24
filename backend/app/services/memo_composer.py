"""
Memo section builders — deterministic, data-driven, no LLM.
Produces section text from NormalizedFact, MetricFact, RatingResult.
"""
from __future__ import annotations

from datetime import date
from typing import Any


def _fmt(v: float | None, decimals: int = 2) -> str:
    if v is None:
        return "N/A"
    if abs(v) >= 1e9:
        return f"{v / 1e9:,.{decimals}f} Bn"
    if abs(v) >= 1e6:
        return f"{v / 1e6:,.{decimals}f} Mn"
    return f"{v:,.{decimals}f}"


def build_executive_summary(
    company_name: str,
    review_period_end: date | None,
    rating_grade: str | None,
    key_metrics: dict[str, float],
    recommendation: str = "Maintain",
) -> str:
    para = f"This credit review covers {company_name} for the period ending {review_period_end or 'N/A'}.\n\n"
    if rating_grade:
        para += f"Internal rating: {rating_grade}. Recommendation: {recommendation}.\n\n"
    ebitda = key_metrics.get("ebitda")
    nd_ebitda = key_metrics.get("net_debt_to_ebitda")
    margin = key_metrics.get("ebitda_margin")
    if ebitda is not None:
        para += f"EBITDA: {_fmt(ebitda)}. "
    if margin is not None and 0 <= margin <= 100:
        para += f"EBITDA margin: {margin:.1f}%. "
    if nd_ebitda is not None:
        para += f"Net debt/EBITDA: {nd_ebitda:.2f}x.\n\n"
    para += "Key risks and mitigants are set out in the sections below."
    return para


def build_financial_performance(
    facts_by_period: dict[date, dict[str, float]],
    metric_by_period: dict[date, dict[str, float]],
) -> str:
    lines = []
    for pe in sorted(facts_by_period.keys(), reverse=True):
        vals = facts_by_period[pe]
        rev = vals.get("revenue")
        gp = vals.get("gross_profit")
        op = vals.get("operating_profit")
        pat = vals.get("profit_after_tax")
        lines.append(f"Period {pe.isoformat()}:")
        if rev is not None:
            lines.append(f"  Revenue: {_fmt(rev)}")
        if gp is not None and (rev is None or gp <= rev):
            lines.append(f"  Gross profit: {_fmt(gp)}")
        if op is not None:
            lines.append(f"  Operating profit: {_fmt(op)}")
        if pat is not None:
            lines.append(f"  Profit after tax: {_fmt(pat)}")
        m = metric_by_period.get(pe, {})
        margin = m.get("ebitda_margin")
        if margin is not None and 0 <= margin <= 100:
            lines.append(f"  EBITDA margin: {margin:.1f}%")
        lines.append("")
    return "\n".join(lines) if lines else "No financial data available."


def build_cash_flow_liquidity(
    facts_by_period: dict[date, dict[str, float]],
    metric_by_period: dict[date, dict[str, float]],
) -> str:
    lines = []
    for pe in sorted(facts_by_period.keys(), reverse=True)[:3]:
        vals = facts_by_period[pe]
        cfo = vals.get("net_cfo")
        capex = vals.get("capex")
        cash = vals.get("cash_and_cash_equivalents")
        m = metric_by_period.get(pe, {})
        cr = m.get("current_ratio")
        fcf = m.get("fcf_conversion")
        lines.append(f"Period {pe.isoformat()}:")
        if cfo is not None:
            lines.append(f"  Net CFO: {_fmt(cfo)}")
        if capex is not None:
            lines.append(f"  Capex: {_fmt(capex)}")
        if cash is not None:
            lines.append(f"  Cash and equivalents: {_fmt(cash)}")
        if cr is not None and cr >= 0:
            lines.append(f"  Current ratio: {cr:.2f}x")
        if fcf is not None:
            lines.append(f"  FCF conversion: {fcf:.1%}")
        lines.append("")
    return "\n".join(lines) if lines else "No cash flow or liquidity data available."


def build_balance_sheet_leverage(
    facts_by_period: dict[date, dict[str, float]],
    metric_by_period: dict[date, dict[str, float]],
) -> str:
    lines = []
    for pe in sorted(facts_by_period.keys(), reverse=True)[:3]:
        vals = facts_by_period[pe]
        ta = vals.get("total_assets")
        te = vals.get("total_equity")
        tl = vals.get("total_liabilities")
        m = metric_by_period.get(pe, {})
        nd_ebitda = m.get("net_debt_to_ebitda")
        nd = m.get("net_debt_incl_leases") or m.get("net_debt_ex_leases")
        ic = m.get("interest_cover")
        lines.append(f"Period {pe.isoformat()}:")
        if ta is not None:
            lines.append(f"  Total assets: {_fmt(ta)}")
        if te is not None:
            lines.append(f"  Total equity: {_fmt(te)}")
        if tl is not None:
            lines.append(f"  Total liabilities: {_fmt(tl)}")
        if nd is not None:
            lines.append(f"  Net debt: {_fmt(nd)}")
        if nd_ebitda is not None:
            lines.append(f"  Net debt/EBITDA: {nd_ebitda:.2f}x")
        if ic is not None and ic >= 0:
            lines.append(f"  Interest cover: {ic:.2f}x")
        lines.append("")
    return "\n".join(lines) if lines else "No balance sheet or leverage data available."


def _build_rating_rationale(rating_grade: str | None, key_metrics: dict[str, float]) -> str:
    """Deterministic rating rationale from grade and key metrics."""
    if not rating_grade:
        return "No rating computed."
    lines = [f"Internal rating: {rating_grade}."]
    nd_ebitda = key_metrics.get("net_debt_to_ebitda")
    ic = key_metrics.get("interest_cover")
    margin = key_metrics.get("ebitda_margin")
    if nd_ebitda is not None:
        lines.append(f"Net debt/EBITDA: {nd_ebitda:.2f}x.")
    if ic is not None and ic >= 0:
        lines.append(f"Interest cover: {ic:.2f}x.")
    if margin is not None and 0 <= margin <= 100:
        lines.append(f"EBITDA margin: {margin:.1f}%.")
    return " ".join(lines)


def build_placeholder(section_key: str) -> str:
    defaults = {
        "transaction_overview": "Transaction details to be completed by deal team.",
        "industry_overview": "Industry context and outlook to be added.",
        "competitive_position": "Competitive positioning analysis to be completed.",
        "security_collateral": "Security and collateral details to be documented.",
        "recommendation_conditions": "Conditions to be specified based on facility terms.",
        "monitoring_plan": "See Monitoring Triggers section below.",
        "appendices": "Supporting schedules and exhibits.",
    }
    return defaults.get(section_key, "Content to be completed.")


def build_all_sections(
    company_name: str,
    review_period_end: date | None,
    rating_grade: str | None,
    recommendation: str,
    facts_by_period: dict[date, dict[str, float]],
    metric_by_period: dict[date, dict[str, float]],
    key_metrics: dict[str, float],
    notes_json: dict | None = None,
    analysis_output: dict[str, Any] | None = None,
    recommendation_conditions: list[str] | None = None,
) -> dict[str, str]:
    """Build all memo section texts. Uses section-based structure when analysis_output has section_blocks."""
    from app.services.notes_indexer import format_risks_for_memo

    section_blocks = (analysis_output or {}).get("section_blocks")
    aggregation = (analysis_output or {}).get("aggregation")
    if section_blocks and aggregation:
        return build_sections_from_blocks(
            company_name=company_name,
            review_period_end=review_period_end,
            rating_grade=rating_grade or aggregation.get("rating_grade"),
            recommendation=recommendation,
            section_blocks=section_blocks,
            aggregation=aggregation,
            facts_by_period=facts_by_period,
            metric_by_period=metric_by_period,
            recommendation_conditions=recommendation_conditions,
        )

    base = {
        "executive_summary": build_executive_summary(
            company_name, review_period_end, rating_grade, key_metrics, recommendation
        ),
        "financial_performance": build_financial_performance(facts_by_period, metric_by_period),
        "cash_flow_liquidity": build_cash_flow_liquidity(facts_by_period, metric_by_period),
        "balance_sheet_leverage": build_balance_sheet_leverage(facts_by_period, metric_by_period),
        "transaction_overview": build_placeholder("transaction_overview"),
        "business_description": build_placeholder("business_description"),
        "industry_overview": build_placeholder("industry_overview"),
        "competitive_position": build_placeholder("competitive_position"),
        "key_notes_accounting": build_placeholder("key_notes_accounting"),
        "key_risks": format_risks_for_memo(notes_json),
        "covenants_headroom": build_placeholder("covenants_headroom"),
        "security_collateral": build_placeholder("security_collateral"),
        "internal_rating_rationale": _build_rating_rationale(rating_grade, key_metrics),
        "recommendation_conditions": "\n".join(recommendation_conditions) if recommendation_conditions else build_placeholder("recommendation_conditions"),
        "monitoring_plan": build_placeholder("monitoring_plan"),
        "appendices": build_placeholder("appendices"),
    }

    comm = (analysis_output or {}).get("commentary", {})
    stress = (analysis_output or {}).get("stress", {})
    base["financial_risk"] = comm.get("financial_risk", build_placeholder("financial_risk"))
    base["liquidity_leverage"] = comm.get("liquidity_leverage", build_placeholder("liquidity_leverage"))
    base["stress_testing_results"] = _format_stress(stress) if stress else build_placeholder("stress_testing_results")
    base["accounting_disclosure_quality"] = comm.get("accounting_disclosure_quality", build_placeholder("accounting_disclosure_quality"))
    if comm.get("key_risks"):
        base["key_risks"] = comm["key_risks"] + "\n\n" + base["key_risks"]
    if comm.get("executive_summary"):
        base["executive_summary"] = comm["executive_summary"]

    return base


def _build_3yr_table(facts_by_period: dict, metric_by_period: dict) -> str:
    """Build 3-5 year financial summary table."""
    periods = sorted(facts_by_period.keys(), reverse=True)[:5]
    if len(periods) < 2:
        return ""
    lines = ["3-Year Financial Summary:", "Period | Revenue | EBITDA | EBITDA % | Net Debt | ND/EBITDA | Interest Cover"]
    for pe in periods:
        vals = facts_by_period.get(pe, {})
        m = metric_by_period.get(pe, {})
        rev = vals.get("revenue")
        ebitda = m.get("ebitda") or vals.get("operating_profit")
        margin = m.get("ebitda_margin")
        nd = m.get("net_debt_incl_leases") or m.get("net_debt_ex_leases")
        nd_eb = m.get("net_debt_to_ebitda")
        ic = m.get("interest_cover")
        rev_s = _fmt(rev) if rev is not None else "N/A"
        ebitda_s = _fmt(ebitda) if ebitda is not None else "N/A"
        margin_s = f"{margin:.1f}%" if margin is not None else "N/A"
        nd_s = _fmt(nd) if nd is not None else "N/A"
        nd_eb_s = f"{nd_eb:.2f}x" if nd_eb is not None else "N/A"
        ic_s = f"{ic:.2f}x" if ic is not None else "N/A"
        lines.append(f"{pe.isoformat()} | {rev_s} | {ebitda_s} | {margin_s} | {nd_s} | {nd_eb_s} | {ic_s}")
    return "\n".join(lines)


def _build_rating_rationale_with_drivers(grade: str, agg: dict, breakdown: dict) -> str:
    """Track 6A: Rationale tied to drivers - top positive/negative sections, governance thresholds."""
    lines = [f"Internal rating: {grade}. Aggregate score: {agg.get('aggregate_score', 'N/A')}/100."]
    sorted_secs = sorted(breakdown.items(), key=lambda x: x[1].get("score", 0), reverse=True)
    top_pos = [(s, d.get("rating", "")) for s, d in sorted_secs[:2] if (d.get("score") or 0) >= 60]
    top_neg = [(s, d.get("rating", "")) for s, d in reversed(sorted_secs[-2:]) if (d.get("score") or 100) < 60]
    if top_pos:
        lines.append(f"Top positive drivers: {', '.join(s.replace('_', ' ').title() + ' (' + r + ')' for s, r in top_pos)}.")
    if top_neg:
        lines.append(f"Key constraints: {', '.join(s.replace('_', ' ').title() + ' (' + r + ')' for s, r in top_neg)}.")
    gov_rules = agg.get("governance_rules") or []
    if gov_rules:
        lines.append(f"Governance thresholds applied: {'; '.join(gov_rules[:3])}.")
    return " ".join(lines)


def _build_monitoring_triggers(blocks: dict, agg: dict) -> str:
    """Build monitoring triggers from covenant/leverage/liquidity."""
    lines = []
    cov = blocks.get("covenants", {}).get("key_metrics") or {}
    if cov.get("leverage_breach") or cov.get("interest_cover_breach"):
        lines.append("Covenant breach: Monitor quarterly covenant compliance; early engagement with lenders.")
    lev = blocks.get("leverage", {}).get("key_metrics") or {}
    nd = lev.get("net_debt_to_ebitda_incl_leases")
    if nd is not None and nd > 4:
        lines.append(f"Leverage: ND/EBITDA at {nd:.2f}x; monitor debt reduction and EBITDA growth.")
    liq = blocks.get("liquidity", {}).get("key_metrics") or {}
    cr = liq.get("current_ratio")
    if cr is not None and cr < 1.0:
        lines.append(f"Liquidity: Current ratio {cr:.2f}x; monitor cash and undrawn facilities.")
    if lines:
        return "\n".join(lines)
    return "Standard quarterly financial monitoring."


def _format_stress(stress: dict[str, Any]) -> str:
    lines = []
    for name, sc in (stress.get("scenarios") or {}).items():
        parts = [f"{name}:"]
        if sc.get("interest_cover_stressed") is not None:
            parts.append(f"Interest cover {sc['interest_cover_stressed']:.2f}x")
        if sc.get("net_debt_to_ebitda_stressed") is not None:
            parts.append(f"ND/EBITDA {sc['net_debt_to_ebitda_stressed']:.2f}x")
        if sc.get("st_debt_to_cash_stressed") is not None:
            parts.append(f"ST debt/cash {sc['st_debt_to_cash_stressed']:.2f}x")
        if sc.get("cash_after_shock") is not None and "C_" in name:
            parts.append(f"Cash after shock: {_fmt(sc['cash_after_shock'])}")
        lines.append(" ".join(parts))
    return "\n".join(lines) if lines else "Stress scenarios computed."


def _section_block_to_text(block: dict[str, Any]) -> str:
    """Render a section block: commentary first (narrative), then compact metrics."""
    parts = []
    name = block.get("section_name", "")
    score = block.get("score", "N/A")
    rating = block.get("section_rating", "N/A")
    if name:
        parts.append(f"{name} — Score: {score}/100, Rating: {rating}\n")
    # Lead with commentary (analytical narrative)
    comm = block.get("llm_commentary")
    if comm:
        parts.append(comm.strip())
        parts.append("")
    # Key metrics — limit to 10, prioritize leverage/liquidity/covenant
    km = block.get("key_metrics") or {}
    skip_keys = {"scenarios", "geographic_regions"}
    priority_substrs = ("net_debt", "ebitda_to_interest", "current_ratio", "liquidity_coverage",
                        "revenue", "ebitda_margin", "liquidity_surplus", "headroom")
    def _score_key(k: str) -> int:
        for i, s in enumerate(priority_substrs):
            if s in (k or "").lower():
                return i
        return 99
    items = [(k, v) for k, v in km.items() if v is not None and k not in skip_keys and not isinstance(v, (dict, list))]
    items.sort(key=lambda x: (_score_key(x[0]), x[0]))
    metrics_lines = []
    for k, v in items[:10]:
        label = k.replace("_", " ").title()
        if isinstance(v, (int, float)):
            metrics_lines.append(f"- {label}: {_fmt(v)}")
        else:
            metrics_lines.append(f"- {label}: {v}")
    if metrics_lines:
        parts.append("Key metrics:\n" + "\n".join(metrics_lines))
        parts.append("")
    flags = block.get("risk_flags") or []
    if flags:
        parts.append("Risk flags:\n" + "\n".join(f"- {f}" for f in flags[:5]))
        parts.append("")
    evidence = block.get("evidence_notes") or []
    if evidence:
        parts.append("Source notes: " + ", ".join(evidence[:5]))
    return "\n".join(parts).strip() if parts else ""


def build_sections_from_blocks(
    company_name: str,
    review_period_end: date | None,
    rating_grade: str | None,
    recommendation: str,
    section_blocks: dict[str, dict[str, Any]],
    aggregation: dict[str, Any],
    facts_by_period: dict[date, dict[str, float]],
    metric_by_period: dict[date, dict[str, float]],
    recommendation_conditions: list[str] | None = None,
) -> dict[str, str]:
    """
    Build memo section texts from section blocks (institutional structure).
    Executive summary written LAST from all section outputs.
    """
    blocks = section_blocks or {}
    agg = aggregation or {}
    grade = rating_grade or agg.get("rating_grade", "N/A")

    exec_lines = [
        f"This credit review covers {company_name} for the period ending {review_period_end or 'N/A'}.",
        f"Internal rating: {grade}. Recommendation: {recommendation}.",
    ]
    breakdown = agg.get("section_breakdown") or {}
    for sec, data in list(breakdown.items())[:5]:
        rating = data.get("rating") or data.get("section_rating") or "N/A"
        score = data.get("score", 0)
        exec_lines.append(f"  • {sec.replace('_', ' ').title()}: {rating} ({score:.1f}/100)")
    if blocks.get("business_risk", {}).get("key_metrics", {}).get("revenue_growth_pct") is not None:
        exec_lines.append(f"Revenue growth: {blocks['business_risk']['key_metrics']['revenue_growth_pct']:.1f}% YoY.")
    if blocks.get("leverage", {}).get("key_metrics", {}).get("net_debt_to_ebitda_incl_leases") is not None:
        nd = blocks["leverage"]["key_metrics"]["net_debt_to_ebitda_incl_leases"]
        exec_lines.append(f"Net debt/EBITDA (incl. leases): {nd:.2f}x.")
    exec_lines.append("Key risks and mitigants are set out in the sections below.")
    executive_summary = "\n\n".join(exec_lines)

    perf_block = blocks.get("financial_performance", {})
    perf_text = _section_block_to_text(perf_block)
    if not perf_text:
        perf_text = build_financial_performance(facts_by_period, metric_by_period)
    three_yr = _build_3yr_table(facts_by_period, metric_by_period)
    if three_yr:
        perf_text = three_yr + "\n\n" + perf_text

    liq_block = blocks.get("liquidity", {})
    liq_text = _section_block_to_text(liq_block)
    if not liq_text:
        liq_text = build_cash_flow_liquidity(facts_by_period, metric_by_period)

    lev_block = blocks.get("leverage", {})
    lev_text = _section_block_to_text(lev_block)
    if not lev_text:
        lev_text = build_balance_sheet_leverage(facts_by_period, metric_by_period)

    stress_scenarios = (blocks.get("stress", {}).get("key_metrics") or {}).get("scenarios", {})
    stress_text = _format_stress({"scenarios": stress_scenarios}) if stress_scenarios else "Stress scenarios computed."

    key_risks_parts = []
    for b in [blocks.get("business_risk"), blocks.get("accounting_quality"), blocks.get("stress")]:
        if b and b.get("risk_flags"):
            key_risks_parts.extend(b["risk_flags"][:3])
    key_risks_text = "; ".join(key_risks_parts) if key_risks_parts else "Risk assessment from section blocks."

    # Track 6A: Rating rationale with drivers - top positive/negative, metric thresholds
    rating_rationale = _build_rating_rationale_with_drivers(grade, agg, breakdown)

    monitoring = _build_monitoring_triggers(blocks, agg)
    if monitoring:
        monitoring_plan = monitoring
    else:
        monitoring_plan = build_placeholder("monitoring_plan")

    def _industry_from_blocks() -> str:
        br = blocks.get("business_risk", {}).get("key_metrics") or {}
        regions = br.get("geographic_regions") or []
        segments = br.get("segment_count")
        rev = br.get("revenue")
        if regions or segments or rev:
            parts = []
            if segments:
                parts.append(f"Company operates across {segments} business segments.")
            if regions:
                parts.append(f"Geographic exposure: {', '.join(regions[:5])}.")
            return " ".join(parts) if parts else build_placeholder("industry_overview")
        return build_placeholder("industry_overview")

    def _competitive_from_blocks() -> str:
        br = blocks.get("business_risk", {}).get("key_metrics") or {}
        margin = br.get("ebitda_margin_pct")
        growth = br.get("revenue_growth_pct")
        if margin is not None or growth is not None:
            parts = []
            if margin is not None:
                parts.append(f"EBITDA margin of {margin:.1f}%.")
            if growth is not None:
                parts.append(f"Revenue growth {growth:.1f}% YoY indicates market positioning.")
            return " ".join(parts)
        return build_placeholder("competitive_position")

    return {
        "executive_summary": executive_summary,
        "transaction_overview": build_placeholder("transaction_overview"),
        "business_description": _section_block_to_text(blocks.get("business_risk", {})),
        "industry_overview": _industry_from_blocks(),
        "competitive_position": _competitive_from_blocks(),
        "financial_performance": perf_text,
        "financial_risk": _format_stress({"scenarios": (blocks.get("stress", {}).get("key_metrics") or {}).get("scenarios", {})}) or build_placeholder("financial_risk"),
        "cash_flow_liquidity": liq_text,
        "balance_sheet_leverage": lev_text,
        "liquidity_leverage": _section_block_to_text(liq_block) + "\n\n" + _section_block_to_text(lev_block),
        "stress_testing_results": stress_text,
        "accounting_disclosure_quality": _section_block_to_text(blocks.get("accounting_quality", {})),
        "key_notes_accounting": _section_block_to_text(blocks.get("accounting_quality", {})),
        "key_risks": key_risks_text,
        "covenants_headroom": _section_block_to_text(blocks.get("covenants", {})),
        "security_collateral": build_placeholder("security_collateral"),
        "internal_rating_rationale": rating_rationale,
        "recommendation_conditions": "\n".join(recommendation_conditions) if recommendation_conditions else build_placeholder("recommendation_conditions"),
        "monitoring_plan": monitoring_plan,
        "appendices": build_placeholder("appendices"),
    }
