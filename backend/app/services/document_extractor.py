"""
Unified Document Extraction Service.

Extracts all financial statements and notes from PDF documents using
geometry-based extraction (fast, accurate) with LLM fallback.

Usage:
    from app.services.document_extractor import extract_all_from_pdf
    
    result = extract_all_from_pdf(pdf_bytes)
    # result.statements = {
    #     "SFP_GROUP": [...],
    #     "SCI_GROUP": [...],
    #     "SOCE_GROUP": [...],
    #     "CF_GROUP": [...],
    # }
    # result.notes = {
    #     "1": NoteSection(...),
    #     "2": NoteSection(...),
    # }
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

log = logging.getLogger(__name__)
from pathlib import Path
from typing import Any

import fitz

from app.services.soce_geometry_extractor import extract_soce_geometry
from app.services.statement_geometry_extractor import extract_statement_geometry
from app.services.notes_store import extract_notes_structured, NoteSection


def detect_scale_from_pdf(pdf_bytes: bytes) -> dict:
    """
    Detect the unit of measurement (scale) and currency from PDF text.
    
    Returns dict with:
        - scale: "million", "thousand", "billion", or "units"
        - scale_factor: numeric multiplier (e.g., 1_000_000 for Rm)
        - scale_label: display label (e.g., "Rm", "R'000")
        - currency: detected currency code (e.g., "ZAR", "USD", "EUR")
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    search_pages = min(15, len(doc))
    combined_text = ""
    for i in range(search_pages):
        combined_text += doc[i].get_text() + "\n"
    doc.close()
    
    text_lower = combined_text.lower()
    
    # Currency detection
    currency = None
    if "south africa" in text_lower or "zar" in text_lower or " r " in text_lower:
        currency = "ZAR"
    elif "us dollar" in text_lower or "usd" in text_lower:
        currency = "USD"
    elif "euro" in text_lower or "eur" in text_lower:
        currency = "EUR"
    
    # Scale detection
    scale = "units"
    scale_factor = 1.0
    scale_label = "R"
    
    # Check for "Rm" (millions)
    if re.search(r"\bRm\b", combined_text):
        scale, scale_factor, scale_label = "million", 1_000_000, "Rm"
    elif re.search(r"\br\s*million", text_lower) or re.search(r"amounts?\s+in\s+(r\s+)?millions?", text_lower):
        scale, scale_factor, scale_label = "million", 1_000_000, "R million"
    # Check for thousands
    elif re.search(r"r'?000\b", text_lower) or re.search(r"amounts?\s+in\s+thousands?", text_lower):
        scale, scale_factor, scale_label = "thousand", 1_000, "R'000"
    # Check for billions
    elif re.search(r"\br\s*billion", text_lower) or re.search(r"amounts?\s+in\s+(r\s+)?billions?", text_lower):
        scale, scale_factor, scale_label = "billion", 1_000_000_000, "R billion"
    
    # Fallback: check for Rm pattern with year
    if scale == "units" and ("Rm" in combined_text or re.search(r"\bRm\b.*\d{4}", combined_text)):
        scale, scale_factor, scale_label = "million", 1_000_000, "Rm"
    
    return {
        "scale": scale,
        "scale_factor": scale_factor,
        "scale_label": scale_label,
        "currency": currency,
    }


@dataclass
class StatementPage:
    """A detected statement page."""
    page_no: int
    statement_type: str  # SFP, SCI, CF, SOCE
    entity_scope: str  # GROUP, COMPANY


@dataclass
class ExtractionResult:
    """Result of document extraction."""
    statements: dict[str, list[dict]] = field(default_factory=dict)
    notes: dict[str, NoteSection] = field(default_factory=dict)
    pages_detected: list[StatementPage] = field(default_factory=list)


def detect_statement_pages(pdf_bytes: bytes) -> list[StatementPage]:
    """
    Detect which pages contain which financial statements.
    Uses heuristic detection (fast, no LLM required).
    Skips index/contents pages (typically pages 1-9) and uses content validation
    to find primary statement tables. Handles two-column layouts.
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    pages: list[StatementPage] = []

    for page_idx in range(len(doc)):
        text = doc[page_idx].get_text()
        text_lower = text.lower()
        page_no = page_idx + 1

        # Skip notes pages
        if "notes to the" in text_lower[:300]:
            continue

        # Skip index / contents pages (actual statements typically start page 10+)
        if page_no < 10:
            continue

        # Determine entity scope
        entity_scope = "GROUP"
        if "separate statement" in text_lower[:1000]:
            entity_scope = "COMPANY"
        elif "consolidated" in text_lower[:1000]:
            entity_scope = "GROUP"

        # SFP: must have statement title and total assets
        if "statement of financial position" in text_lower[:1000] and "total assets" in text_lower:
            pages.append(StatementPage(page_no=page_no, statement_type="SFP", entity_scope=entity_scope))

        # SCI: must have statement title and revenue/profit
        if "statement of comprehensive income" in text_lower[:1000]:
            if "revenue" in text_lower or "profit" in text_lower:
                pages.append(StatementPage(page_no=page_no, statement_type="SCI", entity_scope=entity_scope))

        # SOCE: must have statement title and balance at
        if "statement of changes in equity" in text_lower[:1000] and "balance at" in text_lower:
            pages.append(StatementPage(page_no=page_no, statement_type="SOCE", entity_scope=entity_scope))

        # CF: must have statement title and operating/cash content
        if "statement of cash flows" in text_lower[:1500]:
            if "operating" in text_lower or "cash generated" in text_lower or "cash flows" in text_lower:
                pages.append(StatementPage(page_no=page_no, statement_type="CF", entity_scope=entity_scope))

    # Deduplicate - keep first occurrence per statement_type + scope
    seen: set[str] = set()
    unique_pages: list[StatementPage] = []
    pages.sort(key=lambda p: (0 if 11 <= p.page_no <= 13 else 1, p.page_no))
    for p in pages:
        key = f"{p.statement_type}_{p.entity_scope}"
        if key not in seen:
            seen.add(key)
            unique_pages.append(p)

    # Handle two-column pages: add companion statements on same page
    additional: list[StatementPage] = []
    for sp in unique_pages:
        page_text = doc[sp.page_no - 1].get_text().lower()

        if sp.statement_type == "SFP":
            if "comprehensive income" in page_text or "profit for the year" in page_text:
                if not any(p.statement_type == "SCI" and p.entity_scope == sp.entity_scope for p in unique_pages):
                    additional.append(StatementPage(sp.page_no, "SCI", sp.entity_scope))

        if sp.statement_type == "SOCE":
            if "cash flows" in page_text or "operating activities" in page_text:
                if not any(p.statement_type == "CF" and p.entity_scope == sp.entity_scope for p in unique_pages):
                    additional.append(StatementPage(sp.page_no, "CF", sp.entity_scope))

        if sp.statement_type == "SCI":
            if "financial position" in page_text or "total assets" in page_text:
                if not any(p.statement_type == "SFP" and p.entity_scope == sp.entity_scope for p in unique_pages):
                    additional.append(StatementPage(sp.page_no, "SFP", sp.entity_scope))

        if sp.statement_type == "CF":
            if "changes in equity" in page_text or "balance at" in page_text:
                if not any(p.statement_type == "SOCE" and p.entity_scope == sp.entity_scope for p in unique_pages):
                    additional.append(StatementPage(sp.page_no, "SOCE", sp.entity_scope))

    unique_pages.extend(additional)
    doc.close()
    return unique_pages


def extract_statement(
    pdf_bytes: bytes,
    page_no: int,
    statement_type: str,
    entity_scope: str,
) -> tuple[list[str], list[dict]]:
    """
    Extract a single statement from a page using geometry-based extraction.
    
    Returns (period_labels, rows) where rows have: raw_label, note, section, values_json
    """
    if statement_type == "SOCE":
        column_keys, period_labels, rows = extract_soce_geometry(pdf_bytes, page_no)
        # Convert SOCE format to common format
        return period_labels if period_labels else column_keys, rows
    else:
        stmt_type, scope, period_labels, rows = extract_statement_geometry(
            pdf_bytes, page_no, statement_type
        )
        return period_labels, rows


def extract_all_from_pdf(
    pdf_bytes: bytes,
    extract_notes: bool = True,
) -> ExtractionResult:
    """
    Extract all financial statements and notes from a PDF.
    
    Args:
        pdf_bytes: Raw PDF file bytes
        extract_notes: Whether to extract notes (adds ~2-3 seconds)
    
    Returns:
        ExtractionResult with statements and notes
    """
    result = ExtractionResult()
    
    # Detect statement pages
    detected_pages = detect_statement_pages(pdf_bytes)
    result.pages_detected = detected_pages
    
    # Group by statement type + scope
    pages_by_type: dict[str, list[StatementPage]] = {}
    for sp in detected_pages:
        key = f"{sp.statement_type}_{sp.entity_scope}"
        if key not in pages_by_type:
            pages_by_type[key] = []
        pages_by_type[key].append(sp)
    
    # Extract each statement
    for key, statement_pages in pages_by_type.items():
        all_rows = []
        all_period_labels = []
        for sp in statement_pages:
            try:
                period_labels, rows = extract_statement(
                    pdf_bytes,
                    sp.page_no,
                    sp.statement_type,
                    sp.entity_scope,
                )
                if not rows:
                    log.warning("extract_statement returned 0 rows for %s page %d", key, sp.page_no)
                for row in rows:
                    row["page"] = sp.page_no
                    row["period_labels"] = period_labels
                all_rows.extend(rows)
                if period_labels and not all_period_labels:
                    all_period_labels = period_labels
            except Exception as e:
                log.warning("Error extracting %s from page %d: %s", key, sp.page_no, e, exc_info=True)
        
        if all_rows:
            result.statements[key] = all_rows
    
    # Extract notes
    if extract_notes:
        try:
            result.notes = extract_notes_structured(pdf_bytes, scope="GROUP")
        except Exception as e:
            log.warning("Error extracting notes: %s", e, exc_info=True)
    
    return result


def extract_statements_for_document_version(
    pdf_bytes: bytes,
    document_version_id: str,
    scale_factor: float = 1.0,
) -> dict[str, list[dict]]:
    """
    Extract all statements formatted for database storage.
    
    Returns dict of statement_type -> list of rows ready for StatementLine model.
    """
    result = extract_all_from_pdf(pdf_bytes, extract_notes=False)
    
    statements = {}
    for key, rows in result.statements.items():
        statement_type = key.split("_")[0]  # e.g., "SFP" from "SFP_GROUP"
        
        formatted_rows = []
        for i, row in enumerate(rows):
            # Apply scale factor to values
            values_json = row.get("values_json", {})
            if scale_factor != 1.0:
                scaled = {}
                for period, cols in values_json.items():
                    if isinstance(cols, dict):
                        scaled[period] = {
                            k: (float(v) * scale_factor if v is not None else None)
                            for k, v in cols.items()
                        }
                    else:
                        scaled[period] = float(cols) * scale_factor if cols is not None else None
                values_json = scaled
            
            formatted_rows.append({
                "line_no": i + 1,
                "raw_label": row.get("raw_label", ""),
                "note_ref": row.get("note"),
                "section_path": row.get("section"),
                "values_json": values_json,
                "period_labels": row.get("period_labels", []),
                "page": row.get("page"),
                "evidence_json": {"page": row.get("page")},
            })
        
        if statement_type not in statements:
            statements[statement_type] = []
        statements[statement_type].extend(formatted_rows)
    
    return statements
