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

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import fitz

from app.services.soce_geometry_extractor import extract_soce_geometry
from app.services.statement_geometry_extractor import extract_statement_geometry
from app.services.notes_store import extract_notes_structured, NoteSection


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
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    pages: list[StatementPage] = []
    
    # Statement detection keywords
    patterns = {
        "SFP": [
            r"statement\s+of\s+financial\s+position",
            r"balance\s+sheet",
            r"total\s+assets",
            r"total\s+equity\s+and\s+liabilities",
        ],
        "SCI": [
            r"statement\s+of\s+comprehensive\s+income",
            r"income\s+statement",
            r"profit\s+for\s+the\s+year",
            r"revenue.*cost\s+of\s+sales",
        ],
        "SOCE": [
            r"statement\s+of\s+changes\s+in\s+equity",
            r"changes\s+in\s+equity",
            r"balance\s+at.*july",
            r"balance\s+at.*june",
        ],
        "CF": [
            r"statement\s+of\s+cash\s+flows",
            r"cash\s+flow\s+statement",
            r"cash\s+flows\s+from\s+operating",
            r"cash\s+generated\s+from\s+operations",
        ],
    }
    
    # Scope detection keywords
    group_keywords = ["group", "consolidated", "subsidiaries"]
    company_keywords = ["company", "parent", "holdings ltd"]
    
    found_statements: dict[str, set] = {k: set() for k in patterns}
    
    for page_idx in range(len(doc)):
        page = doc[page_idx]
        page_no = page_idx + 1
        text = page.get_text().lower()
        
        # Skip notes pages
        if "notes to the" in text and "continued" in text:
            continue
        
        # Skip table of contents / index pages
        if text.count("...") > 5:
            continue
        
        for stmt_type, keywords in patterns.items():
            for kw in keywords:
                if re.search(kw, text):
                    # Determine scope
                    scope = "GROUP"
                    if any(k in text for k in company_keywords) and not any(k in text for k in group_keywords):
                        scope = "COMPANY"
                    
                    # Check if not already found for this scope
                    key = f"{stmt_type}_{scope}"
                    if key not in found_statements[stmt_type]:
                        found_statements[stmt_type].add(key)
                        pages.append(StatementPage(
                            page_no=page_no,
                            statement_type=stmt_type,
                            entity_scope=scope,
                        ))
                    break
    
    # Handle two-column pages (common layout)
    # If SFP is found but SCI is on same page, add SCI
    # If SOCE is found but CF is on same page, add CF
    additional = []
    for sp in pages:
        page_text = doc[sp.page_no - 1].get_text().lower()
        
        if sp.statement_type == "SFP":
            if "comprehensive income" in page_text or "profit for the year" in page_text:
                key = f"SCI_{sp.entity_scope}"
                if not any(p.statement_type == "SCI" and p.entity_scope == sp.entity_scope for p in pages):
                    additional.append(StatementPage(sp.page_no, "SCI", sp.entity_scope))
        
        if sp.statement_type == "SOCE":
            if "cash flows" in page_text or "operating activities" in page_text:
                key = f"CF_{sp.entity_scope}"
                if not any(p.statement_type == "CF" and p.entity_scope == sp.entity_scope for p in pages):
                    additional.append(StatementPage(sp.page_no, "CF", sp.entity_scope))
        
        if sp.statement_type == "SCI":
            if "financial position" in page_text or "total assets" in page_text:
                key = f"SFP_{sp.entity_scope}"
                if not any(p.statement_type == "SFP" and p.entity_scope == sp.entity_scope for p in pages):
                    additional.append(StatementPage(sp.page_no, "SFP", sp.entity_scope))
        
        if sp.statement_type == "CF":
            if "changes in equity" in page_text or "balance at" in page_text:
                key = f"SOCE_{sp.entity_scope}"
                if not any(p.statement_type == "SOCE" and p.entity_scope == sp.entity_scope for p in pages):
                    additional.append(StatementPage(sp.page_no, "SOCE", sp.entity_scope))
    
    pages.extend(additional)
    doc.close()
    
    return pages


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
                for row in rows:
                    row["page"] = sp.page_no
                    row["period_labels"] = period_labels
                all_rows.extend(rows)
                if period_labels and not all_period_labels:
                    all_period_labels = period_labels
            except Exception as e:
                print(f"Error extracting {key} from page {sp.page_no}: {e}")
        
        if all_rows:
            result.statements[key] = all_rows
    
    # Extract notes
    if extract_notes:
        try:
            result.notes = extract_notes_structured(pdf_bytes, scope="GROUP")
        except Exception as e:
            print(f"Error extracting notes: {e}")
    
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
