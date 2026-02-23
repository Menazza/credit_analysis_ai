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
        undrawn = (committed_facilities or {}).get(pe_iso)

        curr_ratio = (curr_assets / curr_liab) if curr_liab > 0 else None
        quick_ratio = (quick_assets / curr_liab) if curr_liab > 0 else None
        st_debt_to_cash = (st_debt / cash) if cash > 0 else (None if st_debt == 0 else 999.0)
        monthly_burn = (-(net_cfo or 0) / 12) if net_cfo and net_cfo < 0 else 0
        runway_months = (cash / monthly_burn) if monthly_burn > 0 and cash > 0 else None
        lease_adj_liquidity = cash + (undrawn or 0) - lease_curr

        results["by_period"][pe_iso] = {
            "current_ratio": round(curr_ratio, 2) if curr_ratio is not None and curr_ratio >= 0 else None,
            "quick_ratio": round(quick_ratio, 2) if quick_ratio is not None and quick_ratio >= 0 else None,
            "st_debt_to_cash": round(st_debt_to_cash, 2) if st_debt_to_cash is not None and st_debt_to_cash != 999.0 else None,
            "liquidity_runway_months": round(runway_months, 1) if runway_months is not None else None,
            "undrawn_facilities": undrawn,
            "lease_adjusted_liquidity": round(lease_adj_liquidity, 2),
            "cash": cash,
            "st_debt": st_debt,
        }

    return results
