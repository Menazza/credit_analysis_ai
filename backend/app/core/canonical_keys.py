"""
Locked canonical key list for mapping pipeline.
30-60 keys max. Engines consume these.
"""
from __future__ import annotations

IS_KEYS = [
    "revenue", "cost_of_sales", "gross_profit", "operating_expenses",
    "operating_profit", "depreciation_amortisation", "ebitda",
    "finance_income", "finance_costs", "net_finance_cost",
    "share_of_profit_associates", "profit_before_tax", "income_tax_expense",
    "profit_after_tax", "profit_for_year",
]
BS_KEYS = [
    "cash_and_cash_equivalents", "trade_receivables", "other_receivables",
    "inventories", "total_current_assets", "property_plant_equipment",
    "right_of_use_assets", "intangible_assets", "investment_property",
    "investments_and_associates", "total_assets", "trade_payables",
    "other_payables", "short_term_borrowings", "current_portion_long_term_debt",
    "lease_liabilities_current", "total_current_liabilities",
    "long_term_borrowings", "lease_liabilities_non_current",
    "total_liabilities", "total_equity",
]
CF_KEYS = [
    "net_cfo", "capex", "net_cfi", "net_cff", "net_change_in_cash",
    "cash_generated_operations", "interest_paid", "dividends_paid",
]
OTHER_KEYS = ["committed_facilities"]

CANONICAL_KEYS = IS_KEYS + BS_KEYS + CF_KEYS + OTHER_KEYS

KEY_TO_STATEMENT_TYPE: dict[str, str] = {}
for k in IS_KEYS:
    KEY_TO_STATEMENT_TYPE[k] = "SCI"
for k in BS_KEYS:
    KEY_TO_STATEMENT_TYPE[k] = "SFP"
for k in CF_KEYS:
    KEY_TO_STATEMENT_TYPE[k] = "CF"
for k in OTHER_KEYS:
    KEY_TO_STATEMENT_TYPE[k] = "NOTE"
