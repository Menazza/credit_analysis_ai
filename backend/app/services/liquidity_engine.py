"""
Liquidity Engine - short-term credit survival metrics.
Current ratio, quick ratio, ST debt/cash, runway, undrawn facilities.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from app.services.financial_engine import get_fact


def _current_assets(facts: dict, pe: date) -> float:
    return (
        (get_fact(facts, "cash_and_cash_equivalents", pe) or 0)
        + (get_fact(facts, "trade_receivables", pe) or 0)
        + (get_fact(facts, "other_receivables", pe) or 0)
        + (get_fact(facts, "inventories", pe) or 0)
    )


def _current_liabilities(facts: dict, pe: date) -> float:
    return (
        (get_fact(facts, "trade_payables", pe) or 0)
        + (get_fact(facts, "short_term_borrowings", pe) or 0)
        + (get_fact(facts, "current_portion_long_term_debt", pe) or 0)
        + (get_fact(facts, "lease_liabilities_current", pe) or 0)
    )


def _quick_assets(facts: dict, pe: date) -> float:
    return (
        (get_fact(facts, "cash_and_cash_equivalents", pe) or 0)
        + (get_fact(facts, "trade_receivables", pe) or 0)
        + (get_fact(facts, "other_receivables", pe) or 0)
    )


def run_liquidity_engine(
    facts: dict[tuple[str, date], float],
    periods: list[date],
    committed_facilities: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Compute liquidity metrics. committed_facilities: { period_iso: undrawn_amount }"""
    results: dict[str, Any] = {"by_period": {}}

    for pe in sorted(periods, reverse=True):
        pe_iso = pe.isoformat()
        curr_assets = _current_assets(facts, pe)
        curr_liab = _current_liabilities(facts, pe)
        quick_assets = _quick_assets(facts, pe)
        cash = get_fact(facts, "cash_and_cash_equivalents", pe) or 0
        st_borr = get_fact(facts, "short_term_borrowings", pe) or 0
        curr_port = get_fact(facts, "current_portion_long_term_debt", pe) or 0
        lease_curr = get_fact(facts, "lease_liabilities_current", pe) or 0
        st_debt = st_borr + curr_port + lease_curr
        net_cfo = get_fact(facts, "net_cfo", pe)
        capex = get_fact(facts, "capex", pe)
        undrawn = (committed_facilities or {}).get(pe_iso)

        curr_ratio = (curr_assets / curr_liab) if curr_liab > 0 else None
        quick_ratio = (quick_assets / curr_liab) if curr_liab > 0 else None
        st_debt_to_cash = (st_debt / cash) if cash > 0 else (None if st_debt == 0 else 999.0)
        monthly_burn = (-(net_cfo or 0) / 12) if net_cfo and net_cfo < 0 else 0
        runway_months = (cash / monthly_burn) if monthly_burn > 0 and cash > 0 else None
        lease_adj_liquidity = cash + (undrawn or 0) - lease_curr

        # 12-month forward Sources/Uses model
        forecast_cfo = net_cfo  # Use prior year CFO as proxy for next 12 months
        total_sources = cash + (undrawn or 0) + max(0, forecast_cfo or 0)
        capex_amt = abs(capex or 0)  # capex stored as negative
        total_uses = st_debt + lease_curr + (capex_amt * 0.8 if capex_amt else 0)  # Maintenance capex ~80%
        wc_assumption = 0.02 * (get_fact(facts, "revenue", pe) or 0)  # 2% of revenue as WC increase
        total_uses += wc_assumption
        liquidity_surplus = total_sources - total_uses
        coverage_ratio = (total_sources / total_uses) if total_uses and total_uses > 0 else None
        headroom_pct = (100 * (total_sources - total_uses) / total_uses) if total_uses and total_uses > 0 else None
        months_runway = (cash / (total_uses / 12)) if total_uses and total_uses > 0 and cash > 0 else None

        results["by_period"][pe_iso] = {
            "current_ratio": round(curr_ratio, 2) if curr_ratio is not None and curr_ratio >= 0 else None,
            "quick_ratio": round(quick_ratio, 2) if quick_ratio is not None and quick_ratio >= 0 else None,
            "st_debt_to_cash": round(st_debt_to_cash, 2) if st_debt_to_cash is not None and st_debt_to_cash != 999.0 else None,
            "liquidity_runway_months": round(runway_months, 1) if runway_months is not None else None,
            "undrawn_facilities": undrawn,
            "lease_adjusted_liquidity": round(lease_adj_liquidity, 2),
            "cash": cash,
            "st_debt": st_debt,
            # Sources/Uses 12-month forward
            "total_sources_12m": round(total_sources, 2),
            "total_uses_12m": round(total_uses, 2),
            "liquidity_surplus_12m": round(liquidity_surplus, 2),
            "liquidity_coverage_ratio": round(coverage_ratio, 2) if coverage_ratio is not None else None,
            "liquidity_headroom_pct": round(headroom_pct, 1) if headroom_pct is not None else None,
            "months_runway_sources_uses": round(months_runway, 1) if months_runway is not None else None,
        }

    return results
