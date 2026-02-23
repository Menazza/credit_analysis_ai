"""Notes Extractor - structured extraction from notes JSON for credit analysis."""
from __future__ import annotations
import re
from typing import Any

def extract_debt_maturity(notes: dict) -> list[dict[str, Any]]:
    """Extract debt maturity ladder from Note 21/43."""
    out = []
    notes_dict = notes.get("notes") or notes if isinstance(notes, dict) else {}
    for nid, note in (notes_dict.items() if isinstance(notes_dict, dict) else []):
        if not isinstance(note, dict):
            continue
        text = (note.get("text") or "")[:15000]
        if "21" not in str(nid) and "43" not in str(nid):
            continue
        if "maturit" not in text.lower() and "due" not in text.lower():
            continue
        for m in re.finditer(r"(?:within\s+)?(\d+)\s*(?:months?|year)", text, re.I):
            out.append({"period": m.group(0), "note": str(nid)})
    return out[:10]


def extract_fx_sensitivity(notes: dict) -> dict[str, Any] | None:
    """Extract FX sensitivity from Note 43."""
    notes_dict = notes.get("notes") or notes if isinstance(notes, dict) else {}
    for nid, note in (notes_dict.items() if isinstance(notes_dict, dict) else []):
        if not isinstance(note, dict):
            continue
        text = (note.get("text") or "")[:12000]
        if "43" not in str(nid):
            continue
        if "foreign exchange" not in text.lower() and "currency" not in text.lower():
            continue
        m = re.search(r"(\d+)\s*%\s*(?:increase|decrease).*?(?:profit|equity|ebitda)", text, re.I | re.S)
        if m:
            return {"sensitivity_pct": int(m.group(1)), "note": str(nid)}
    return None


def extract_interest_sensitivity(notes: dict) -> dict[str, Any] | None:
    """Extract interest rate sensitivity from Note 43."""
    notes_dict = notes.get("notes") or notes if isinstance(notes, dict) else {}
    for nid, note in (notes_dict.items() if isinstance(notes_dict, dict) else []):
        if not isinstance(note, dict):
            continue
        text = (note.get("text") or "")[:12000]
        if "43" not in str(nid):
            continue
        if "interest" not in text.lower() or "sensitivity" not in text.lower():
            continue
        m = re.search(r"(\d+)\s*(?:basis\s+points?|bps?|%)", text, re.I)
        if m:
            return {"bps": int(m.group(1)), "note": str(nid)}
    return None


def extract_impairment_assumptions(notes: dict) -> list[str]:
    """Extract impairment key assumptions from Note 8."""
    out = []
    notes_dict = notes.get("notes") or notes if isinstance(notes, dict) else {}
    for nid, note in (notes_dict.items() if isinstance(notes_dict, dict) else []):
        if not isinstance(note, dict):
            continue
        text = (note.get("text") or "")[:8000]
        if "8" not in str(nid) and "impairment" not in text.lower():
            continue
        if "discount rate" in text.lower():
            out.append("Discount rate")
        if "growth rate" in text.lower():
            out.append("Growth rate")
        if "value in use" in text.lower():
            out.append("Value in use")
    return out


def extract_tax_reconciliation(notes: dict) -> dict[str, Any] | None:
    """Extract effective tax rate reconciliation from Note 34."""
    notes_dict = notes.get("notes") or notes if isinstance(notes, dict) else {}
    for nid, note in (notes_dict.items() if isinstance(notes_dict, dict) else []):
        if not isinstance(note, dict):
            continue
        text = (note.get("text") or "")[:6000]
        if "34" not in str(nid) and "tax" not in text.lower():
            continue
        m = re.search(r"effective\s+(?:tax\s+)?rate\s*[:\s]+(\d+\.?\d*)\s*%", text, re.I)
        if m:
            return {"effective_rate_pct": float(m.group(1)), "note": str(nid)}
    return None


def run_notes_extraction(notes_json: dict | None) -> dict[str, Any]:
    """Run all note extractions. Returns structured data for memo/engines."""
    notes = notes_json or {}
    return {
        "debt_maturity": extract_debt_maturity(notes),
        "fx_sensitivity": extract_fx_sensitivity(notes),
        "interest_sensitivity": extract_interest_sensitivity(notes),
        "impairment_assumptions": extract_impairment_assumptions(notes),
        "tax_reconciliation": extract_tax_reconciliation(notes),
    }
