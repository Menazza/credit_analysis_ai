"""
Canonical chart of accounts — standard keys for SFP, SCI, CF, SoCE.
All extraction and mapping targets these keys for a consistent platform model.
"""

SFP_KEYS = [
    "cash_and_cash_equivalents",
    "restricted_cash",
    "trade_receivables",
    "other_receivables",
    "inventories",
    "current_tax_asset",
    "other_current_assets",
    "assets_held_for_sale",
    "property_plant_equipment",
    "right_of_use_assets",
    "investment_property",
    "goodwill",
    "intangible_assets",
    "deferred_tax_asset",
    "investments_and_associates",
    "other_non_current_assets",
    "share_capital",
    "share_premium",
    "treasury_shares",
    "reserves",
    "retained_earnings",
    "non_controlling_interests",
    "total_equity",
    "trade_payables",
    "other_payables",
    "contract_liabilities",
    "short_term_borrowings",
    "current_portion_long_term_debt",
    "lease_liabilities_current",
    "provisions_current",
    "current_tax_liability",
    "other_current_liabilities",
    "long_term_borrowings",
    "lease_liabilities_non_current",
    "provisions_non_current",
    "deferred_tax_liability",
    "other_non_current_liabilities",
]

SCI_KEYS = [
    "revenue",
    "cost_of_sales",
    "gross_profit",
    "other_income",
    "distribution_costs",
    "admin_expenses",
    "operating_expenses_other",
    "operating_profit",
    "depreciation_amortisation",
    "impairment_charges",
    "finance_income",
    "finance_costs",
    "share_of_profit_associates",
    "profit_before_tax",
    "income_tax_expense",
    "profit_after_tax",
    "discontinued_operations_profit",
    "profit_for_year",
    "nci_profit_attrib",
    "owners_profit_attrib",
    "eps_basic",
    "eps_diluted",
]

CF_KEYS = [
    "cfo_before_wc",
    "change_in_working_capital",
    "cash_generated_operations",
    "interest_paid",
    "tax_paid",
    "net_cfo",
    "capex",
    "proceeds_disposals",
    "acquisitions",
    "net_cfi",
    "debt_raised",
    "debt_repaid",
    "lease_payments_principal",
    "dividends_paid",
    "net_cff",
    "net_change_cash",
    "opening_cash",
    "closing_cash",
]

DERIVED_KEYS = [
    "ebitda",
    "net_debt_ex_leases",
    "net_debt_incl_leases",
    "funds_from_operations",
    "free_cash_flow",
    "fixed_charge_cover",
    "debt_maturity_wall_12m",
    "liquidity_headroom",
]

CANONICAL_ACCOUNTS = []
for k in SFP_KEYS:
    CANONICAL_ACCOUNTS.append({"canonical_key": k, "statement_type": "SFP", "display_name": k.replace("_", " ").title()})
for k in SCI_KEYS:
    CANONICAL_ACCOUNTS.append({"canonical_key": k, "statement_type": "SCI", "display_name": k.replace("_", " ").title()})
for k in CF_KEYS:
    CANONICAL_ACCOUNTS.append({"canonical_key": k, "statement_type": "CF", "display_name": k.replace("_", " ").title()})
for k in DERIVED_KEYS:
    CANONICAL_ACCOUNTS.append({"canonical_key": k, "statement_type": "DERIVED", "display_name": k.replace("_", " ").title()})
