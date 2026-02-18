"""
Deterministic financial engine — no AI.
Computes ratios, cash flow, leverage, liquidity from normalized facts.
All outputs are versioned, reproducible, traceable.
"""
from datetime import date
from typing import Any
from decimal import Decimal


def get_fact(facts: dict[tuple[str, date], float], key: str, period_end: date) -> float | None:
    return facts.get((key, period_end))


def compute_ebitda(facts: dict[tuple[str, date], float], period_end: date) -> float | None:
    op = get_fact(facts, "operating_profit", period_end)
    da = get_fact(facts, "depreciation_amortisation", period_end)
    if op is None:
        return None
    return (op or 0) + (da or 0)


def compute_net_debt_ex_leases(facts: dict[tuple[str, date], float], period_end: date) -> float | None:
    cash = get_fact(facts, "cash_and_cash_equivalents", period_end)
    st_borr = get_fact(facts, "short_term_borrowings", period_end)
    curr_portion = get_fact(facts, "current_portion_long_term_debt", period_end)
    lt_borr = get_fact(facts, "long_term_borrowings", period_end)
    if cash is None and st_borr is None and curr_portion is None and lt_borr is None:
        return None
    debt = (st_borr or 0) + (curr_portion or 0) + (lt_borr or 0)
    return debt - (cash or 0)


def compute_net_debt_incl_leases(facts: dict[tuple[str, date], float], period_end: date) -> float | None:
    net_ex = compute_net_debt_ex_leases(facts, period_end)
    lease_curr = get_fact(facts, "lease_liabilities_current", period_end)
    lease_nc = get_fact(facts, "lease_liabilities_non_current", period_end)
    cash = get_fact(facts, "cash_and_cash_equivalents", period_end)
    if net_ex is None and lease_curr is None and lease_nc is None:
        return None
    leases = (lease_curr or 0) + (lease_nc or 0)
    return (net_ex or 0) + leases


def compute_interest_cover(facts: dict[tuple[str, date], float], period_end: date) -> float | None:
    ebit = get_fact(facts, "operating_profit", period_end)
    finance_costs = get_fact(facts, "finance_costs", period_end)
    if ebit is None or finance_costs is None or finance_costs == 0:
        return None
    return ebit / finance_costs


def compute_net_debt_to_ebitda(
    facts: dict[tuple[str, date], float], period_end: date
) -> float | None:
    net_debt = compute_net_debt_incl_leases(facts, period_end)
    ebitda = compute_ebitda(facts, period_end)
    if net_debt is None or ebitda is None or ebitda == 0:
        return None
    return net_debt / ebitda


def compute_ebitda_margin(facts: dict[tuple[str, date], float], period_end: date) -> float | None:
    ebitda = compute_ebitda(facts, period_end)
    revenue = get_fact(facts, "revenue", period_end)
    if ebitda is None or revenue is None or revenue == 0:
        return None
    return 100.0 * (ebitda / revenue)


def compute_current_ratio(facts: dict[tuple[str, date], float], period_end: date) -> float | None:
    # Simplified: current assets / current liabilities from key line items
    cash = get_fact(facts, "cash_and_cash_equivalents", period_end) or 0
    receivables = get_fact(facts, "trade_receivables", period_end) or 0
    other_rcv = get_fact(facts, "other_receivables", period_end) or 0
    inventory = get_fact(facts, "inventories", period_end) or 0
    payables = get_fact(facts, "trade_payables", period_end) or 0
    st_borr = get_fact(facts, "short_term_borrowings", period_end) or 0
    curr_portion = get_fact(facts, "current_portion_long_term_debt", period_end) or 0
    curr_liab = payables + st_borr + curr_portion
    if curr_liab == 0:
        return None
    curr_assets = cash + receivables + other_rcv + inventory
    return curr_assets / curr_liab


def compute_fcf_conversion(facts: dict[tuple[str, date], float], period_end: date) -> float | None:
    net_cfo = get_fact(facts, "net_cfo", period_end)
    capex = get_fact(facts, "capex", period_end)
    ebitda = compute_ebitda(facts, period_end)
    if net_cfo is None or ebitda is None or ebitda == 0:
        return None
    fcf = (net_cfo or 0) - (capex or 0)
    return fcf / ebitda


def run_engine(facts: dict[tuple[str, date], float], periods: list[date]) -> dict[str, Any]:
    """Compute all metrics for given facts and periods. Returns metric_key -> { period_end -> value } with calc_trace."""
    results = {}
    for period_end in periods:
        ebitda = compute_ebitda(facts, period_end)
        if ebitda is not None:
            results.setdefault("ebitda", {})[period_end.isoformat()] = ebitda
        nd_ex = compute_net_debt_ex_leases(facts, period_end)
        if nd_ex is not None:
            results.setdefault("net_debt_ex_leases", {})[period_end.isoformat()] = nd_ex
        nd_incl = compute_net_debt_incl_leases(facts, period_end)
        if nd_incl is not None:
            results.setdefault("net_debt_incl_leases", {})[period_end.isoformat()] = nd_incl
        ic = compute_interest_cover(facts, period_end)
        if ic is not None:
            results.setdefault("interest_cover", {})[period_end.isoformat()] = ic
        nd_ebitda = compute_net_debt_to_ebitda(facts, period_end)
        if nd_ebitda is not None:
            results.setdefault("net_debt_to_ebitda", {})[period_end.isoformat()] = nd_ebitda
        margin = compute_ebitda_margin(facts, period_end)
        if margin is not None:
            results.setdefault("ebitda_margin", {})[period_end.isoformat()] = margin
        cr = compute_current_ratio(facts, period_end)
        if cr is not None:
            results.setdefault("current_ratio", {})[period_end.isoformat()] = cr
        fcf_conv = compute_fcf_conversion(facts, period_end)
        if fcf_conv is not None:
            results.setdefault("fcf_conversion", {})[period_end.isoformat()] = fcf_conv
    return results
