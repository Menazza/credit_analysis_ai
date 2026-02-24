"""
Track 5B: Rules-based recommendation conditions.
Recommendation driven by leverage, liquidity, concentration, covenant headroom.
"""
from __future__ import annotations

from typing import Any


def compute_recommendation(
    key_metrics: dict[str, float],
    covenant_metrics: dict[str, Any] | None = None,
    stress_breaches: int = 0,
) -> tuple[str, list[str]]:
    """
    Rules-based recommendation. Returns (recommendation, list of condition strings).
    Options: Approve, Maintain, Caution, Decline (or similar).
    """
    conditions: list[str] = []
    nd_ebitda = key_metrics.get("net_debt_to_ebitda") or key_metrics.get("net_debt_to_ebitda_incl_leases")
    ic = key_metrics.get("interest_cover") or key_metrics.get("ebitda_to_interest")
    cr = key_metrics.get("current_ratio")
    st_debt_to_cash = key_metrics.get("st_debt_to_cash")

    cov = covenant_metrics or {}
    lev_breach = cov.get("leverage_breach") or cov.get("leverage_breach_flag")
    ic_breach = cov.get("interest_cover_breach") or cov.get("interest_cover_breach_flag")

    if lev_breach or ic_breach:
        conditions.append("Covenant breach: Monitor closely; early engagement with lenders.")
    if stress_breaches >= 2:
        conditions.append("Multiple stress scenario breaches: Enhanced monitoring required.")

    if nd_ebitda is not None:
        if nd_ebitda >= 6.0:
            conditions.append("Leverage ND/EBITDA ≥ 6x: Debt reduction plan required.")
        elif nd_ebitda >= 5.0:
            conditions.append("Leverage ND/EBITDA 5–6x: Monitor quarterly.")
    if ic is not None and ic < 2.0:
        conditions.append("Interest cover < 2x: Cash flow and interest rate sensitivity review.")
    if cr is not None and cr < 0.8:
        conditions.append("Current ratio < 0.8x: Liquidity monitoring.")
    if st_debt_to_cash is not None and st_debt_to_cash > 5.0:
        conditions.append("ST debt/cash > 5x: Undrawn facilities and refinancing plan.")

    if conditions:
        if lev_breach or ic_breach or (stress_breaches >= 2):
            return "Caution", conditions
        return "Maintain", conditions
    return "Maintain", ["Standard quarterly monitoring."]
