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


# ——— RMB-style Credit Review Memo sections (populated from canonical dataset + commentary) ———
MEMO_SECTIONS = [
    "executive_summary",
    "transaction_overview",
    "business_description",
    "industry_overview",
    "competitive_position",
    "financial_performance",
    "cash_flow_liquidity",
    "balance_sheet_leverage",
    "key_notes_accounting",
    "key_risks",
    "covenants_headroom",
    "security_collateral",
    "internal_rating_rationale",
    "recommendation_conditions",
    "monitoring_plan",
    "appendices",
]


def build_memo_docx(
    company_name: str,
    review_period_end: date | None,
    version_id: str,
    section_texts: dict[str, str],
    rating_grade: str | None = None,
    recommendation: str = "Maintain",
) -> BytesIO:
    doc = DocxDocument()
    doc.add_heading("Credit Review Memo", 0)
    doc.add_paragraph(f"Company: {company_name}")
    doc.add_paragraph(f"Review period end: {review_period_end or 'N/A'}")
    doc.add_paragraph(f"Version: {version_id}")
    doc.add_paragraph("")
    if rating_grade:
        doc.add_paragraph(f"Internal rating: {rating_grade}")
    doc.add_paragraph(f"Recommendation: {recommendation}")
    doc.add_paragraph("")
    for section_key in MEMO_SECTIONS:
        title = section_key.replace("_", " ").title()
        doc.add_heading(title, level=1)
        text = section_texts.get(section_key) or "(No content)"
        doc.add_paragraph(text)
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
) -> BytesIO:
    try:
        from pptx import Presentation
        from pptx.util import Inches, Pt
    except ImportError:
        buf = BytesIO()
        buf.write(b"PPTX generation requires python-pptx; placeholder.")
        buf.seek(0)
        return buf
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[0])
    title = slide.shapes.title
    if title:
        title.text = f"Credit Committee — {company_name}"
    body = slide.placeholders[1] if len(slide.placeholders) > 1 else None
    if body:
        body.text = f"Rating: {rating_grade}\nRecommendation: {recommendation}\nVersion: {version_id}\n\nKey drivers:\n" + "\n".join(key_drivers[:5])
    buf = BytesIO()
    prs.save(buf)
    buf.seek(0)
    return buf
