"""
Hierarchical SoCE header parsing and validation.

Uses canonical roles (total_equity, non_controlling_interest, owners_total, owners_component)
instead of fixed labels. Implements validation rules and column-shift resolution.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from itertools import permutations
from typing import Any


# Canonical SoCE roles — "what does this column mean?"
ROLE_TOTAL_EQUITY = "total_equity"
ROLE_NON_CONTROLLING_INTEREST = "non_controlling_interest"
ROLE_OWNERS_TOTAL = "attributable_total"  # alias
ROLE_OWNERS_COMPONENT = "owners_component"

# Fixed owners_component roles (for validation and mapping)
OWNERS_COMPONENT_KEYS = ("stated_capital", "treasury_shares", "other_reserves", "retained_earnings")

# Role groups: top-level vs under "Attributable to owners"
TOP_LEVEL_ROLES = (ROLE_TOTAL_EQUITY, ROLE_NON_CONTROLLING_INTEREST)
ATTRIBUTABLE_GROUP = "attributable"
ATTRIBUTABLE_SUB_ROLES = (ROLE_OWNERS_TOTAL,) + OWNERS_COMPONENT_KEYS

# Header patterns: (canonical_key, patterns, role_type)
# role_type: "top" | "attributable_parent" | "attributable_sub"
HEADER_PATTERNS: list[tuple[str, list[str], str]] = [
    (ROLE_TOTAL_EQUITY, ["total equity"], "top"),
    (ROLE_NON_CONTROLLING_INTEREST, ["non-controlling interest", "non controlling interest", "nci"], "top"),
    ("attributable_parent", ["attributable to owners of the parent", "attributable to owners"], "attributable_parent"),
    (ROLE_OWNERS_TOTAL, ["total"], "attributable_sub"),  # sub-header under Attributable
    ("stated_capital", ["stated capital"], "attributable_sub"),
    ("treasury_shares", ["treasury shares"], "attributable_sub"),
    ("other_reserves", ["other reserves"], "attributable_sub"),
    ("retained_earnings", ["retained earnings"], "attributable_sub"),
]


@dataclass
class SoCEColumnDef:
    """A column definition with canonical role and optional label."""
    id: str
    role: str
    label: str | None = None
    group: str | None = None  # e.g. "attributable"
    order: int = 0


@dataclass
class SoCEValidationResult:
    """Result of validation rules."""
    rule_a_ok: bool
    rule_a_residual: float
    rule_b_ok: bool
    rule_b_residual: float
    rule_c_ok: bool
    rule_c_violations: list[str] = field(default_factory=list)
    passed: bool = False
    mapping_explanation: str = ""


def parse_soce_columns_hierarchical(text: str) -> list[SoCEColumnDef]:
    """
    Parse SoCE headers hierarchically. Returns column definitions in document order.

    Top level: Total equity, NCI, then "Attributable to owners" group.
    Under group: Total, Stated capital, Treasury shares, Other reserves, Retained earnings.
    """
    text_lower = text.lower()
    found: list[tuple[int, str, str, str]] = []  # (position, key, raw_match, role_type)

    # Find attributable parent — sub-headers only valid in or after that region
    attrib_match = re.search(r"attributable to owners (?:of the parent)?", text_lower)
    attrib_start = attrib_match.start() if attrib_match else 0
    text_after_attrib = text_lower[attrib_start:] if attrib_match else text_lower

    for key, patterns, role_type in HEADER_PATTERNS:
        if key == "attributable_parent":
            continue
        search_text = text_after_attrib if role_type == "attributable_sub" else text_lower
        base_pos = attrib_start if role_type == "attributable_sub" else 0
        for pat in patterns:
            if pat == "total":
                # Avoid matching "Total" in "Total equity"; require not followed by " equity"
                m = re.search(r"\btotal\b(?!\s*equity)", search_text)
            else:
                m = re.search(re.escape(pat), search_text)
            if m:
                pos = base_pos + m.start()
                cid = ROLE_OWNERS_TOTAL if key == "total" else key
                found.append((pos, cid, m.group(0), role_type))
                break

    found.sort(key=lambda x: x[0])

    # Build column list: deduplicate by id, preserve order
    result: list[SoCEColumnDef] = []
    seen: set[str] = set()
    order = 0
    for _, cid, raw, role_type in found:
        if cid in seen:
            continue
        seen.add(cid)
        role = ROLE_OWNERS_TOTAL if cid == ROLE_OWNERS_TOTAL else (ROLE_OWNERS_COMPONENT if cid in OWNERS_COMPONENT_KEYS else cid)
        result.append(SoCEColumnDef(id=cid, role=role, label=raw.title(), group=ATTRIBUTABLE_GROUP if role_type == "attributable_sub" else None, order=order))
        order += 1

    if result:
        return result

    # Fallback: standard 7-column order
    fallback_keys = [
        ROLE_TOTAL_EQUITY, ROLE_NON_CONTROLLING_INTEREST, ROLE_OWNERS_TOTAL,
        "stated_capital", "treasury_shares", "other_reserves", "retained_earnings",
    ]
    return [SoCEColumnDef(id=k, role=k, label=k.replace("_", " ").title(), order=i) for i, k in enumerate(fallback_keys)]


def column_defs_to_keys(column_defs: list[SoCEColumnDef]) -> list[str]:
    """Convert column defs to flat key list for values_json."""
    return [c.id for c in column_defs]


def validate_soce_row(period_values: dict[str, float], tolerance: float = 1.0) -> SoCEValidationResult:
    """
    Apply validation rules on a single period's values.

    Rule A: total_equity ≈ attributable_total + non_controlling_interest
    Rule B: attributable_total ≈ sum(owners_components)
    Rule C: treasury_shares usually negative; if positive → likely column shift
    """
    te = period_values.get(ROLE_TOTAL_EQUITY)
    nci = period_values.get(ROLE_NON_CONTROLLING_INTEREST)
    at = period_values.get(ROLE_OWNERS_TOTAL)
    sc = period_values.get("stated_capital")
    ts = period_values.get("treasury_shares")
    or_ = period_values.get("other_reserves")
    re_ = period_values.get("retained_earnings")

    rule_a_ok = True
    rule_a_residual = 0.0
    if te is not None and at is not None and nci is not None:
        rule_a_residual = abs(te - (at + nci))
        rule_a_ok = rule_a_residual <= tolerance

    rule_b_ok = True
    rule_b_residual = 0.0
    comps = [v for k, v in period_values.items() if k in OWNERS_COMPONENT_KEYS and v is not None]
    if at is not None and comps:
        comp_sum = sum(comps)
        rule_b_residual = abs(at - comp_sum)
        rule_b_ok = rule_b_residual <= tolerance

    rule_c_violations: list[str] = []
    if ts is not None and ts > 0:
        rule_c_violations.append("treasury_shares positive (expected negative)")

    rule_c_ok = len(rule_c_violations) == 0
    passed = rule_a_ok and rule_b_ok and rule_c_ok

    return SoCEValidationResult(
        rule_a_ok=rule_a_ok,
        rule_a_residual=rule_a_residual,
        rule_b_ok=rule_b_ok,
        rule_b_residual=rule_b_residual,
        rule_c_ok=rule_c_ok,
        rule_c_violations=rule_c_violations,
        passed=passed,
    )


def resolve_column_shift(
    amounts: list[float],
    column_keys: list[str],
    period_labels: list[str],
    tolerance: float = 1.0,
) -> tuple[dict[str, dict[str, float]], list[str], SoCEValidationResult | None]:
    """
    When Rule A fails, try permutations of (total_equity, nci, owners_total) assignment.
    Returns (values_json, column_keys_used, validation_result) for the best match.
    """
    cols_per_period = len(column_keys)
    num_periods = min(len(period_labels), max(1, len(amounts) // cols_per_period))

    # Identify the three main columns (must be present for Rule A)
    main_roles = [ROLE_TOTAL_EQUITY, ROLE_NON_CONTROLLING_INTEREST, ROLE_OWNERS_TOTAL]
    main_indices = []
    for r in main_roles:
        try:
            i = column_keys.index(r)
            main_indices.append(i)
        except ValueError:
            pass

    if len(main_indices) != 3:
        # Cannot resolve: return original
        values_json: dict[str, dict[str, float]] = {}
        for i in range(num_periods):
            period = period_labels[i] if i < len(period_labels) else str(i)
            start = i * cols_per_period
            values_json[period] = {}
            for j in range(cols_per_period):
                if start + j < len(amounts):
                    values_json[period][column_keys[j]] = amounts[start + j]
        val = validate_soce_row(values_json.get(period_labels[0], {}), tolerance)
        return values_json, column_keys, val

    # Get balance row values for first period (use first period for testing)
    start = 0
    row_vals = [amounts[start + j] if start + j < len(amounts) else 0.0 for j in range(cols_per_period)]

    # Try all permutations of (total_equity, nci, owners_total) for the three slots
    i_a, i_b, i_c = main_indices
    roles = [ROLE_TOTAL_EQUITY, ROLE_NON_CONTROLLING_INTEREST, ROLE_OWNERS_TOTAL]
    best_residual = float("inf")
    best_perm: tuple[str, str, str] | None = None
    best_val: SoCEValidationResult | None = None

    for perm in permutations(roles):
        te, nci, at = row_vals[i_a], row_vals[i_b], row_vals[i_c]
        assign = {perm[0]: te, perm[1]: nci, perm[2]: at}
        te_v = assign.get(ROLE_TOTAL_EQUITY)
        nci_v = assign.get(ROLE_NON_CONTROLLING_INTEREST)
        at_v = assign.get(ROLE_OWNERS_TOTAL)
        if te_v is None or nci_v is None or at_v is None:
            continue
        residual = abs(te_v - (at_v + nci_v))
        if residual > best_residual:
            continue
        # Build full period_vals to validate Rule B and C
        test_vals = {column_keys[j]: row_vals[j] for j in range(len(column_keys))}
        test_vals[ROLE_TOTAL_EQUITY] = te_v
        test_vals[ROLE_NON_CONTROLLING_INTEREST] = nci_v
        test_vals[ROLE_OWNERS_TOTAL] = at_v
        val = validate_soce_row(test_vals, tolerance)
        if residual < best_residual or (residual == best_residual and val.passed and (best_val is None or not best_val.passed)):
            best_residual = residual
            best_perm = perm
            best_val = val

    if best_perm is None or best_residual > tolerance:
        # No good permutation: return original
        values_json = {}
        for i in range(num_periods):
            period = period_labels[i] if i < len(period_labels) else str(i)
            start = i * cols_per_period
            values_json[period] = {
                column_keys[j]: amounts[start + j]
                for j in range(cols_per_period)
                if start + j < len(amounts)
            }
        return values_json, column_keys, validate_soce_row(values_json.get(period_labels[0], {}), tolerance)

    # Build permuted column_keys: swap roles at main_indices
    permuted_keys = list(column_keys)
    for idx, role in zip([i_a, i_b, i_c], best_perm):
        permuted_keys[idx] = role

    values_json = {}
    for i in range(num_periods):
        period = period_labels[i] if i < len(period_labels) else str(i)
        start = i * cols_per_period
        values_json[period] = {
            permuted_keys[j]: amounts[start + j]
            for j in range(cols_per_period)
            if start + j < len(amounts)
        }

    val = validate_soce_row(values_json.get(period_labels[0], {}), tolerance)
    return values_json, permuted_keys, val


def columns_normalized_for_storage(column_defs: list[SoCEColumnDef], period_labels: list[str]) -> list[dict[str, Any]]:
    """Produce columns_normalized format: id, label, role, group for export/UI."""
    out: list[dict[str, Any]] = []
    for c in column_defs:
        out.append({
            "id": c.id,
            "label": c.label or c.id.replace("_", " ").title(),
            "role": c.role,
            "group": c.group,
            "order": c.order,
        })
    return out
