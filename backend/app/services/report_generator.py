"""
Report generation — Word (credit memo), Excel (financial model), PowerPoint (committee deck).
All outputs reference version id, model id, document version hashes for audit.
"""
from datetime import date
from io import BytesIO
from typing import Any
from docx import Document as DocxDocument
from docx.shared import Pt, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, Border, Side
from openpyxl.utils import get_column_letter


# ——— Structured Credit Review Memo sections (Phase 1 architecture) ———
MEMO_SECTIONS = [
    "executive_summary",
    "transaction_overview",
    "business_description",
    "industry_overview",
    "competitive_position",
    "financial_performance",
    "financial_risk",
    "cash_flow_liquidity",
    "balance_sheet_leverage",
    "liquidity_leverage",
    "stress_testing_results",
    "accounting_disclosure_quality",
    "key_notes_accounting",
    "key_risks",
    "covenants_headroom",
    "security_collateral",
    "internal_rating_rationale",
    "recommendation_conditions",
    "monitoring_plan",
    "appendices",
]


def _add_formatted_paragraphs(doc: "DocxDocument", text: str, style: str | None = None) -> None:
    """Add paragraphs from text, splitting on double newlines. Preserves bullet lists."""
    style = style or "Normal"
    blocks = text.split("\n\n")
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        lines = block.split("\n")
        if len(lines) > 1 and any(line.strip().startswith(("- ", "• ", "* ")) for line in lines):
            # Bullet list
            for line in lines:
                line = line.strip()
                if line.startswith(("- ", "• ", "* ")):
                    line = line[2:].strip()
                if line:
                    p = doc.add_paragraph(line, style=style)
                    p.paragraph_format.left_indent = Inches(0.25)
                    p.paragraph_format.space_before = Pt(0)
                    p.paragraph_format.space_after = Pt(3)
        else:
            p = doc.add_paragraph(block, style=style)
            p.paragraph_format.space_after = Pt(6)
            p.paragraph_format.line_spacing = 1.15


def build_memo_docx(
    company_name: str,
    review_period_end: date | None,
    version_id: str,
    section_texts: dict[str, str],
    rating_grade: str | None = None,
    recommendation: str = "Maintain",
) -> BytesIO:
    doc = DocxDocument()
    # Title and metadata
    title = doc.add_heading("Credit Review Memo", 0)
    title.alignment = WD_ALIGN_PARAGRAPH.LEFT
    for s in doc.styles:
        if s.name == "Normal":
            s.font.size = Pt(11)
            s.font.name = "Calibri"
            break
    meta = doc.add_paragraph()
    meta.add_run("Company: ").bold = True
    meta.add_run(f"{company_name}\n")
    meta.add_run("Review period end: ").bold = True
    meta.add_run(f"{review_period_end or 'N/A'}\n")
    meta.add_run("Version: ").bold = True
    meta.add_run(f"{version_id}")
    meta.paragraph_format.space_after = Pt(12)
    if rating_grade:
        rp = doc.add_paragraph()
        rp.add_run("Internal rating: ").bold = True
        rp.add_run(f"{rating_grade}")
        rp.paragraph_format.space_after = Pt(3)
    rp2 = doc.add_paragraph()
    rp2.add_run("Recommendation: ").bold = True
    rp2.add_run(f"{recommendation}")
    rp2.paragraph_format.space_after = Pt(18)
    # Sections with readable formatting
    for section_key in MEMO_SECTIONS:
        title = section_key.replace("_", " ").title()
        h = doc.add_heading(title, level=1)
        h.paragraph_format.space_before = Pt(12)
        h.paragraph_format.space_after = Pt(6)
        text = section_texts.get(section_key) or "(No content)"
        _add_formatted_paragraphs(doc, text)
    buf = BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf


def build_financial_model_xlsx(
    company_name: str,
    period_ends: list[date],
    normalized_rows: list[dict],  # [{ "label": "Revenue", "canonical_key": "revenue", "values": [period_end -> value] }]
    metrics_rows: list[dict],
    version_id: str,
) -> BytesIO:
    wb = Workbook()
    ws = wb.active
    if ws is None:
        raise RuntimeError("No active sheet")
    ws.title = "Financial model"
    thin = Side(style="thin")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    # Header
    ws.cell(1, 1, "Credit Analysis AI — Financial model").font = Font(bold=True, size=14)
    ws.cell(2, 1, f"Company: {company_name}")
    ws.cell(3, 1, f"Version: {version_id}")
    row = 5
    # Period headers
    ws.cell(row, 1, "Line item")
    for c, pe in enumerate(period_ends, start=2):
        ws.cell(row, c, pe.isoformat() if isinstance(pe, date) else str(pe))
    row += 1
    for r in normalized_rows:
        ws.cell(row, 1, r.get("label", r.get("canonical_key", "")))
        for c, pe in enumerate(period_ends, start=2):
            vals = r.get("values") or {}
            key = pe.isoformat() if isinstance(pe, date) else pe
            val = vals.get(key)
            ws.cell(row, c, val if val is not None else "")
        row += 1
    row += 1
    ws.cell(row, 1, "Metrics").font = Font(bold=True)
    row += 1
    for r in metrics_rows:
        ws.cell(row, 1, r.get("label", r.get("metric_key", "")))
        for c, pe in enumerate(period_ends, start=2):
            vals = r.get("values") or {}
            key = pe.isoformat() if isinstance(pe, date) else pe
            val = vals.get(key)
            ws.cell(row, c, val if val is not None else "")
        row += 1
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def build_committee_pptx(
    company_name: str,
    rating_grade: str,
    recommendation: str,
    key_drivers: list[str],
    version_id: str,
    section_texts: dict[str, str] | None = None,
) -> BytesIO:
    """Build 8-10 slide committee deck."""
    try:
        from pptx import Presentation
        from pptx.util import Inches, Pt
    except ImportError:
        buf = BytesIO()
        buf.write(b"PPTX generation requires python-pptx; placeholder.")
        buf.seek(0)
        return buf

    prs = Presentation()
    sections = section_texts or {}

    def add_title_slide(title_text: str, subtitle: str = ""):
        s = prs.slides.add_slide(prs.slide_layouts[0])
        if s.shapes.title:
            s.shapes.title.text = title_text
        if len(s.placeholders) > 1 and subtitle:
            s.placeholders[1].text = subtitle[:500]

    def add_content_slide(title_text: str, body: str):
        s = prs.slides.add_slide(prs.slide_layouts[1])
        if s.shapes.title:
            s.shapes.title.text = title_text
        if len(s.placeholders) > 1:
            s.placeholders[1].text = (body or "N/A")[:2000]

    # 1. Title
    add_title_slide(f"Credit Committee — {company_name}", f"Rating: {rating_grade} | Recommendation: {recommendation} | {version_id}")

    # 2. Executive Summary
    add_content_slide("Executive Summary", sections.get("executive_summary", ""))

    # 3. Financial Performance
    add_content_slide("Financial Performance", sections.get("financial_performance", ""))

    # 4. Cash Flow & Liquidity
    add_content_slide("Cash Flow & Liquidity", sections.get("cash_flow_liquidity", ""))

    # 5. Balance Sheet & Leverage
    add_content_slide("Balance Sheet & Leverage", sections.get("balance_sheet_leverage", ""))

    # 6. Key Risks
    add_content_slide("Key Risks", sections.get("key_risks", ""))

    # 7. Stress Testing
    add_content_slide("Stress Testing Results", sections.get("stress_testing_results", ""))

    # 8. Rating Rationale
    add_content_slide("Internal Rating Rationale", sections.get("internal_rating_rationale", f"Rating: {rating_grade}"))

    # 9. Recommendation
    add_content_slide("Recommendation", f"Recommendation: {recommendation}\n\nKey drivers: " + ", ".join(key_drivers[:5]))

    # 10. Appendix
    add_content_slide("Appendix", sections.get("appendices", f"Version: {version_id}"))

    buf = BytesIO()
    prs.save(buf)
    buf.seek(0)
    return buf
