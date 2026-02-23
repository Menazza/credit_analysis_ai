"""
Mapping pipeline: ExtractedFacts -> (Pass A + B) -> NormalizedFact.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from app.services.mapping_rules import map_raw_label
from app.services.extraction_loader import load_extraction_from_s3, extraction_to_flat_rows


def year_to_period_end(year: str) -> date:
    """Assume June year-end for SA AFS. year='2025' -> 2025-06-30."""
    return date(int(year), 6, 30)


def run_mapping(
    excel_key: str,
    company_id: str,
    scale_factor: float = 1.0,
) -> list[dict[str, Any]]:
    """
    Load extraction from S3, map to canonical keys, return NormalizedFact rows.
    Returns list of dicts ready for NormalizedFact insertion.
    """
    extraction = load_extraction_from_s3(excel_key)
    sheet_to_type = {s: s.split("_")[0] for s in extraction.keys()}
    flat = extraction_to_flat_rows(extraction, sheet_to_type)

    # Prefer GROUP (consolidated) over COMPANY for credit analysis
    group_sheets = {s for s in extraction.keys() if "_GROUP" in s.upper()}
    flat = [r for r in flat if r.get("sheet") in group_sheets]

    # Keys where we prefer SFP (balance sheet) over CF - CF may have different structure
    SFP_PREFERRED_KEYS = frozenset({"cash_and_cash_equivalents", "total_equity", "total_assets", "total_liabilities"})

    facts_by_key: dict[tuple[str, date], list[tuple[dict, str]]] = {}
    seen: set[tuple[str, date, str]] = set()

    for row in flat:
        raw_label = row["raw_label"]
        year = row["year"]
        value = row["value"]
        canonical_key, method, is_expense = map_raw_label(raw_label)
        if not canonical_key:
            continue

        period_end = year_to_period_end(year)
        sheet = row.get("sheet", "")
        dedup_key = (canonical_key, period_end, sheet)
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        if is_expense and value > 0:
            value = -value
        value_base = value * scale_factor

        source_ref = {
            "page": row.get("page"),
            "line_no": row.get("line_no"),
            "raw_label": raw_label[:200],
            "mapping_method": method,
            "sheet": sheet,
        }

        fact = {
            "company_id": company_id,
            "period_end": period_end,
            "statement_type": row.get("statement_type", "SCI"),
            "canonical_key": canonical_key,
            "value_base": value_base,
            "value_original": value,
            "unit_meta_json": {"scale_factor": scale_factor},
            "source_refs_json": [source_ref],
        }
        k = (canonical_key, period_end)
        if k not in facts_by_key:
            facts_by_key[k] = []
        facts_by_key[k].append((fact, sheet))

    # Coalesce duplicates: prefer SFP for balance sheet keys (cash, equity, etc.)
    facts = []
    for (canonical_key, period_end), candidates in facts_by_key.items():
        if len(candidates) == 1:
            facts.append(candidates[0][0])
            continue
        if canonical_key in SFP_PREFERRED_KEYS:
            sfp = [c for c in candidates if "SFP" in (c[1] or "").upper()]
            chosen = sfp[0] if sfp else candidates[0]
        else:
            chosen = candidates[0]
        facts.append(chosen[0])
    return facts
