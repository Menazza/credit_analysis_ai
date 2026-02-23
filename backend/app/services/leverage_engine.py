"""
Leverage Engine — IFRS 16 essential.
Net debt ex/incl leases, gross debt, debt/capital, EBITDA/interest, fixed charge cover.
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


def run_leverage_engine(
    facts: dict[tuple[str, date], float],
    periods: list[date],
) -> dict[str, Any]:
    """Compute leverage metrics including lease-adjusted ratios."""
    results: dict[str, Any] = {"by_period": {}}

    for pe in sorted(periods, reverse=True):
        pe_iso = pe.isoformat()
        ebitda = compute_ebitda(facts, pe)
        finance_costs = get_fact(facts, "finance_costs", pe)
        interest_paid = get_fact(facts, "interest_paid", pe) or finance_costs
        lease_curr = get_fact(facts, "lease_liabilities_current", pe) or 0
        lease_nc = get_fact(facts, "lease_liabilities_non_current", pe) or 0
        st_borr = get_fact(facts, "short_term_borrowings", pe) or 0
        curr_port = get_fact(facts, "current_portion_long_term_debt", pe) or 0
        lt_borr = get_fact(facts, "long_term_borrowings", pe) or 0
        cash = get_fact(facts, "cash_and_cash_equivalents", pe) or 0
        total_equity = get_fact(facts, "total_equity", pe) or 0
        total_liab = get_fact(facts, "total_liabilities", pe) or 0

        gross_debt = st_borr + curr_port + lt_borr + lease_curr + lease_nc
        net_debt_ex = compute_net_debt_ex_leases(facts, pe)
        net_debt_incl = compute_net_debt_incl_leases(facts, pe)

        # Debt / Capital (gross debt / (equity + gross debt))
        capital = total_equity + gross_debt
        debt_to_capital = (gross_debt / capital) if capital and capital > 0 else None

        # EBITDA / Interest (cash interest)
        interest_exp = abs(interest_paid) if interest_paid and interest_paid < 0 else (abs(finance_costs) if finance_costs and finance_costs < 0 else 0)
        ebitda_interest = (ebitda / interest_exp) if interest_exp and interest_exp > 0 else None

        # Fixed charge cover: (EBITDA + lease interest) / (interest + lease payments)
        # Approx: lease payment ~ lease_curr (simplified); use EBITDA / (interest + lease_curr/2) as proxy
        lease_payment_proxy = (lease_curr + lease_nc) * 0.1  # rough 10% implicit rate proxy
        fixed_charge = interest_exp + lease_payment_proxy if lease_payment_proxy > 0 else interest_exp
        fixed_charge_cover = (ebitda / fixed_charge) if fixed_charge and fixed_charge > 0 else ebitda_interest

        # Lease-adjusted interest cover
        lease_adjusted_ic = fixed_charge_cover

        # Net debt / EBITDA
        nd_ebitda_ex = (net_debt_ex / ebitda) if ebitda and ebitda != 0 and net_debt_ex is not None else None
        nd_ebitda_incl = (net_debt_incl / ebitda) if ebitda and ebitda != 0 and net_debt_incl is not None else None

        results["by_period"][pe_iso] = {
            "net_debt_ex_leases": net_debt_ex,
            "net_debt_incl_leases": net_debt_incl,
            "gross_debt": gross_debt,
            "debt_to_capital": round(debt_to_capital, 4) if debt_to_capital is not None else None,
            "net_debt_to_ebitda_ex_leases": round(nd_ebitda_ex, 2) if nd_ebitda_ex is not None else None,
            "net_debt_to_ebitda_incl_leases": round(nd_ebitda_incl, 2) if nd_ebitda_incl is not None else None,
            "ebitda_to_interest": round(ebitda_interest, 2) if ebitda_interest is not None and ebitda_interest >= 0 else None,
            "fixed_charge_cover": round(fixed_charge_cover, 2) if fixed_charge_cover is not None and fixed_charge_cover >= 0 else None,
            "lease_adjusted_interest_cover": round(lease_adjusted_ic, 2) if lease_adjusted_ic is not None and lease_adjusted_ic >= 0 else None,
        }

    return results
