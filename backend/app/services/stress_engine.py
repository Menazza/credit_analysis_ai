"""
Stress Test Engine - what breaks this credit?
Scenario A: Revenue -10%, B: Interest +200bps, C: Working capital shock.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from app.services.financial_engine import (
    get_fact,
    compute_ebitda,
    compute_net_debt_ex_leases,
    compute_net_debt_incl_leases,
)


def run_stress_engine(
    facts: dict[tuple[str, date], float],
    periods: list[date],
) -> dict[str, Any]:
    """
    Run minimum stress scenarios. Recalculate EBITDA, interest cover, net debt/EBITDA.
    """
    results: dict[str, Any] = {"scenarios": {}}
    for pe in sorted(periods, reverse=True)[:1]:  # Latest period
        pe_iso = pe.isoformat()
        rev = get_fact(facts, "revenue", pe) or 0
        op = get_fact(facts, "operating_profit", pe) or 0
        da = get_fact(facts, "depreciation_amortisation", pe) or 0
        fc = get_fact(facts, "finance_costs", pe)
        finance_costs = abs(fc) if fc and fc < 0 else 0
        ebitda = compute_ebitda(facts, pe) or 0
        net_debt = compute_net_debt_incl_leases(facts, pe) or 0

        # Scenario A: Revenue -10%
        rev_shock = rev * 0.9
        margin_pct = (ebitda / rev * 100) if rev and rev > 0 else 0
        ebitda_a = rev_shock * (margin_pct / 100) if margin_pct else ebitda * 0.9  # Rough
        ic_a = (op * 0.9 / finance_costs) if finance_costs > 0 else None
        nd_ebitda_a = (net_debt / ebitda_a) if ebitda_a and ebitda_a > 0 else None

        results["scenarios"]["A_revenue_minus_10pct"] = {
            "period": pe_iso,
            "revenue_stressed": rev_shock,
            "ebitda_stressed": round(ebitda_a, 2),
            "interest_cover_stressed": round(ic_a, 2) if ic_a is not None else None,
            "net_debt_to_ebitda_stressed": round(nd_ebitda_a, 2) if nd_ebitda_a is not None else None,
        }

        # Scenario B: Interest +200bps on gross debt
        gross_debt = (
            (get_fact(facts, "short_term_borrowings", pe) or 0)
            + (get_fact(facts, "current_portion_long_term_debt", pe) or 0)
            + (get_fact(facts, "long_term_borrowings", pe) or 0)
        )
        extra_interest = gross_debt * 0.02  # 200 bps
        fc_b = finance_costs + extra_interest
        ic_b = (op / fc_b) if fc_b and fc_b > 0 else None

        results["scenarios"]["B_interest_plus_200bps"] = {
            "period": pe_iso,
            "extra_interest": round(extra_interest, 2),
            "interest_cover_stressed": round(ic_b, 2) if ic_b is not None and ic_b >= 0 else None,
        }

        # Scenario C: Working capital shock (e.g. receivables +10% of revenue, cash -10% of revenue)
        wc_shock = rev * 0.10
        cash_curr = get_fact(facts, "cash_and_cash_equivalents", pe) or 0
        cash_c = cash_curr - wc_shock
        st_debt = (
            (get_fact(facts, "short_term_borrowings", pe) or 0)
            + (get_fact(facts, "current_portion_long_term_debt", pe) or 0)
        )
        st_debt_to_cash_c = (st_debt / cash_c) if cash_c and cash_c > 0 else None

        results["scenarios"]["C_working_capital_shock"] = {
            "period": pe_iso,
            "wc_shock_amount": round(wc_shock, 2),
            "cash_after_shock": round(cash_c, 2),
            "st_debt_to_cash_stressed": round(st_debt_to_cash_c, 2) if st_debt_to_cash_c is not None else None,
        }

        # Scenario D: EBITDA margin compression (-200bps)
        margin_pct = (ebitda / rev * 100) if rev and rev > 0 else 0
        margin_d = max(0, margin_pct - 2.0)
        ebitda_d = rev * (margin_d / 100) if rev else 0
        nd_d = net_debt / ebitda_d if ebitda_d and ebitda_d > 0 else None
        ic_d = (op * (margin_d / margin_pct) / finance_costs) if finance_costs and margin_pct and margin_pct > 0 else None
        results["scenarios"]["D_margin_compression_200bps"] = {
            "period": pe_iso,
            "ebitda_stressed": round(ebitda_d, 2),
            "interest_cover_stressed": round(ic_d, 2) if ic_d is not None else None,
            "net_debt_to_ebitda_stressed": round(nd_d, 2) if nd_d is not None else None,
        }

        # Scenario E: Combined (rev -10% + interest +200bps)
        ebitda_e = ebitda_a
        fc_e = finance_costs + extra_interest
        ic_e = (op * 0.9 / fc_e) if fc_e and fc_e > 0 else None
        nd_e = net_debt / ebitda_e if ebitda_e and ebitda_e > 0 else None
        results["scenarios"]["E_combined"] = {
            "period": pe_iso,
            "interest_cover_stressed": round(ic_e, 2) if ic_e is not None else None,
            "net_debt_to_ebitda_stressed": round(nd_e, 2) if nd_e is not None else None,
        }

    return results
