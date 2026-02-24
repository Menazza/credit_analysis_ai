"""
Report generation — Word (credit memo), Excel (financial model), PowerPoint (committee deck).
Production-ready styling, institutional format.
"""
from datetime import date
from io import BytesIO
from typing import Any
from docx import Document as DocxDocument
from docx.shared import Pt, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, Border, Side, PatternFill
from openpyxl.utils import get_column_letter


# ——— Memo sections (no duplicates; liquidity_leverage removed) ———
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

# Human-readable section titles
MEMO_SECTION_TITLES = {
    "executive_summary": "Executive Summary",
    "transaction_overview": "Transaction Overview",
    "business_description": "Business Risk Assessment",
    "industry_overview": "Industry Overview",
    "competitive_position": "Competitive Position",
    "financial_performance": "Financial Performance",
    "financial_risk": "Financial Risk",
    "cash_flow_liquidity": "Cash Flow & Liquidity",
    "balance_sheet_leverage": "Balance Sheet & Leverage",
    "stress_testing_results": "Stress Testing Results",
    "accounting_disclosure_quality": "Accounting & Disclosure Quality",
    "key_notes_accounting": "Key Notes (Accounting)",
    "key_risks": "Key Risks",
    "covenants_headroom": "Covenants & Headroom",
    "security_collateral": "Security & Collateral",
    "internal_rating_rationale": "Internal Rating Rationale",
    "recommendation_conditions": "Recommendation & Conditions",
    "monitoring_plan": "Monitoring Plan",
    "appendices": "Appendices",
}


def _add_formatted_paragraphs(doc: "DocxDocument", text: str, style: str | None = None) -> None:
    """Add paragraphs with institutional formatting: bold subheadings, bullets, proper spacing."""
    para_style = style or "Normal"
    bullet_style = "List Bullet" if "List Bullet" in [s.name for s in doc.styles] else para_style
    subheading_patterns = ("key metrics:", "risk flags:", "source notes:", "governance rules:")
    blocks = text.split("\n\n")
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        lines = [ln.strip() for ln in block.split("\n") if ln.strip()]
        bullet_lines = [ln for ln in lines if ln.startswith(("- ", "• ", "* "))]
        first_lower = lines[0].lower() if lines else ""
        is_subheading_first = first_lower.endswith(":") and any(p in first_lower for p in subheading_patterns)
        if is_subheading_first and len(lines) > 1 and bullet_lines:
            # Bold subheading then bullets
            p = doc.add_paragraph()
            r = p.add_run(lines[0])
            r.bold = True
            r.font.size = Pt(10)
            p.paragraph_format.space_before = Pt(8)
            p.paragraph_format.space_after = Pt(4)
            for line in bullet_lines:
                s = line[2:].lstrip() if len(line) > 2 else line
                if s:
                    bp = doc.add_paragraph(s, style=bullet_style)
                    bp.paragraph_format.space_after = Pt(2)
                    bp.paragraph_format.left_indent = Pt(18)
            if doc.paragraphs:
                doc.paragraphs[-1].paragraph_format.space_after = Pt(6)
        elif len(lines) > 1 and bullet_lines:
            for line in lines:
                if line.startswith(("- ", "• ", "* ")):
                    s = line[2:].lstrip()
                else:
                    s = line
                if s:
                    p = doc.add_paragraph(s, style=bullet_style)
                    p.paragraph_format.space_after = Pt(2)
            if doc.paragraphs:
                doc.paragraphs[-1].paragraph_format.space_after = Pt(8)
        else:
            p = doc.add_paragraph(block, style=para_style)
            p.paragraph_format.space_after = Pt(8)
            p.paragraph_format.line_spacing = 1.15


def build_memo_docx(
    company_name: str,
    review_period_end: date | None,
    version_id: str,
    section_texts: dict[str, str],
    rating_grade: str | None = None,
    recommendation: str = "Maintain",
    key_metrics: dict | None = None,
    metric_by_period: dict | None = None,
    facts_by_period: dict | None = None,
) -> BytesIO:
    doc = DocxDocument()
    try:
        for s in [doc.styles["Normal"], doc.styles["Heading 1"], doc.styles["Heading 2"]]:
            s.font.name = "Calibri"
            s.font.size = Pt(11) if s.name == "Normal" else Pt(14 if s.name == "Heading 1" else 12)
    except KeyError:
        pass
    # Title
    title = doc.add_heading("Credit Review Memo", 0)
    title.alignment = WD_ALIGN_PARAGRAPH.LEFT
    title.paragraph_format.space_after = Pt(6)
    # Metadata block
    meta = doc.add_paragraph()
    meta.add_run("Company: ").bold = True
    meta.add_run(f"{company_name}  ")
    meta.add_run("Review period end: ").bold = True
    meta.add_run(f"{review_period_end or 'N/A'}  ")
    meta.add_run("Version: ").bold = True
    meta.add_run(version_id[:8] + "..." if len(version_id) > 12 else version_id)
    meta.paragraph_format.space_after = Pt(4)
    rating_rec = doc.add_paragraph()
    rating_rec.add_run("Internal rating: ").bold = True
    rating_rec.add_run(f"{rating_grade or 'N/A'}  ")
    rating_rec.add_run("Recommendation: ").bold = True
    rating_rec.add_run(recommendation)
    rating_rec.paragraph_format.space_after = Pt(18)
    # Track 5A: Key metrics table + trend table
    if key_metrics or metric_by_period:
        _add_key_metrics_and_trend_tables(doc, key_metrics or {}, metric_by_period or {}, facts_by_period or {})

    # Sections
    for section_key in MEMO_SECTIONS:
        title_text = MEMO_SECTION_TITLES.get(section_key, section_key.replace("_", " ").title())
        h = doc.add_heading(title_text, level=1)
        h.paragraph_format.space_before = Pt(16)
        h.paragraph_format.space_after = Pt(8)
        text = section_texts.get(section_key) or ""
        if not text.strip():
            text = "Content to be completed."
        _add_formatted_paragraphs(doc, text)
    buf = BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf


def _add_key_metrics_and_trend_tables(doc, key_metrics: dict, metric_by_period: dict, facts_by_period: dict) -> None:
    """Track 5A: Insert key metrics table and trend table into memo."""
    periods = sorted(metric_by_period.keys(), reverse=True)[:5] if metric_by_period else []
    if not periods and not key_metrics:
        return
    h = doc.add_heading("Key Metrics", level=2)
    h.paragraph_format.space_before = Pt(12)
    km_keys = ["revenue", "ebitda", "ebitda_margin", "net_debt_to_ebitda", "net_debt_to_ebitda_incl_leases", "interest_cover", "ebitda_to_interest", "current_ratio"]
    km_labels = {"revenue": "Revenue", "ebitda": "EBITDA", "ebitda_margin": "EBITDA %", "net_debt_to_ebitda": "ND/EBITDA", "net_debt_to_ebitda_incl_leases": "ND/EBITDA (incl)", "interest_cover": "Interest Cover", "ebitda_to_interest": "Interest Cover", "current_ratio": "Current Ratio"}
    tbl = doc.add_table(rows=len(km_keys) + 1, cols=len(periods) + 2)
    tbl.style = "Table Grid"
    row0 = tbl.rows[0].cells
    row0[0].text = "Metric"
    for c, pe in enumerate(periods, 1):
        row0[c].text = str(pe)[:7] if hasattr(pe, "isoformat") else str(pe)[:7]
    for r, k in enumerate(km_keys, 1):
        cells = tbl.rows[r].cells
        cells[0].text = km_labels.get(k, k.replace("_", " ").title())
        for c, pe in enumerate(periods, 1):
            v = metric_by_period.get(pe, {}).get(k) or key_metrics.get(k)
            if v is not None:
                cells[c].text = f"{v:,.2f}" if isinstance(v, (int, float)) and abs(v) < 100 else f"{v:,.1f}"
    doc.add_paragraph()
    # Trend: Revenue, EBITDA, ND/EBITDA
    h2 = doc.add_heading("3-Year Trend", level=2)
    h2.paragraph_format.space_before = Pt(8)
    nd_key = "net_debt_to_ebitda_incl_leases" if any(metric_by_period.get(p, {}).get("net_debt_to_ebitda_incl_leases") for p in periods) else "net_debt_to_ebitda"
    trend_keys = [("revenue", "Revenue"), ("ebitda", "EBITDA"), (nd_key, "ND/EBITDA")]
    tbl2 = doc.add_table(rows=4, cols=len(periods) + 2)
    tbl2.style = "Table Grid"
    tbl2.rows[0].cells[0].text = "Line"
    for c, pe in enumerate(periods[:5], 1):
        tbl2.rows[0].cells[c].text = str(pe)[:7] if hasattr(pe, "isoformat") else str(pe)[:7]
    for r, (k, label) in enumerate(trend_keys, 1):
        tbl2.rows[r].cells[0].text = label
        for c, pe in enumerate(periods[:5], 1):
            v = metric_by_period.get(pe, {}).get(k) or facts_by_period.get(pe, {}).get(k) or (facts_by_period.get(pe, {}).get("operating_profit") if k == "ebitda" else None)
            if v is not None and isinstance(v, (int, float)):
                tbl2.rows[r].cells[c].text = f"{v:,.2f}" if abs(v) < 100 else f"{v:,.0f}"
    doc.add_paragraph()


def _period_key(pe) -> str:
    """Normalize period to lookup key (isoformat or str)."""
    return pe.isoformat() if hasattr(pe, "isoformat") else str(pe)


def _categorize_fact_key(key: str) -> str:
    k = (key or "").lower()
    if any(x in k for x in ("revenue", "cost_of", "gross_profit", "operating", "profit", "tax", "comprehensive")):
        return "pnl"
    if any(x in k for x in ("assets", "equity", "liabilities", "cash", "debt", "inventor", "receivable", "payable")):
        return "bs"
    if any(x in k for x in ("cfo", "capex", "investing", "financing", "cash_flow")):
        return "cf"
    return "other"

def _write_formatted_sheet(ws, title: str, rows: list[dict], period_ends: list, period_key_fn) -> None:
    """Write a sheet with header styling and number formats."""
    header_fill = PatternFill(start_color="2F5496", end_color="2F5496", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF")
    total_fill = PatternFill(start_color="D6DCE4", end_color="D6DCE4", fill_type="solid")
    bold_font = Font(bold=True)
    ws.cell(1, 1, title).font = Font(bold=True, size=14)
    ws.cell(2, 1, "Line Item").font = header_font
    for c, pe in enumerate(period_ends, start=2):
        cell = ws.cell(2, c, period_key_fn(pe))
        cell.font = header_font
        cell.fill = header_fill
    row = 3
    for r in rows:
        label = r.get("label", r.get("canonical_key", r.get("metric_key", "")))
        vals = r.get("values") or {}
        ws.cell(row, 1, label).font = bold_font if "total" in label.lower() else Font()
        for c, pe in enumerate(period_ends, start=2):
            key = period_key_fn(pe)
            val = vals.get(key)
            cell = ws.cell(row, c, val if val is not None else "")
            if val is not None and isinstance(val, (int, float)):
                cell.number_format = "#,##0" if abs(val) >= 1 else "#,##0.00"
        row += 1
    for col in range(1, len(period_ends) + 2):
        ws.column_dimensions[get_column_letter(col)].width = max(18, min(28, len(title) + 4))

def build_financial_model_xlsx(
    company_name: str,
    period_ends: list[date],
    normalized_rows: list[dict],
    metrics_rows: list[dict],
    version_id: str,
    analysis_output: dict[str, Any] | None = None,
) -> BytesIO:
    wb = Workbook()
    period_key_fn = lambda pe: _period_key(pe)
    pnl_rows = [r for r in normalized_rows if _categorize_fact_key(r.get("canonical_key", "")) == "pnl"]
    bs_rows = [r for r in normalized_rows if _categorize_fact_key(r.get("canonical_key", "")) == "bs"]
    cf_rows = [r for r in normalized_rows if _categorize_fact_key(r.get("canonical_key", "")) == "cf"]
    other_rows = [r for r in normalized_rows if _categorize_fact_key(r.get("canonical_key", "")) == "other"]

    header_fill = PatternFill(start_color="2F5496", end_color="2F5496", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF")

    # Sheet 1: Summary
    ws0 = wb.active
    ws0.title = "Summary"
    ws0.cell(1, 1, "Credit Analysis — Financial Model").font = Font(bold=True, size=16)
    ws0.cell(2, 1, f"Company: {company_name}").font = Font(bold=True)
    ws0.cell(3, 1, f"Version: {version_id}")
    agg = (analysis_output or {}).get("aggregation") or {}
    ws0.cell(5, 1, "Internal Rating:").font = Font(bold=True)
    ws0.cell(5, 2, agg.get("rating_grade", "N/A"))
    ws0.cell(6, 1, "Aggregate Score:").font = Font(bold=True)
    ws0.cell(6, 2, str(agg.get("aggregate_score", "N/A")) + "/100")
    ws0.cell(8, 1, "Key Ratios").font = header_font
    for c, pe in enumerate(period_ends, start=2):
        ws0.cell(8, c, period_key_fn(pe)).font = header_font
        ws0.cell(8, c).fill = header_fill
    row = 9
    for r in metrics_rows[:20]:
        ws0.cell(row, 1, r.get("label", r.get("metric_key", ""))).font = Font(bold=True)
        vals = r.get("values") or {}
        for c, pe in enumerate(period_ends, start=2):
            v = vals.get(period_key_fn(pe))
            cell = ws0.cell(row, c, v if v is not None else "")
            if v is not None and isinstance(v, (int, float)):
                cell.number_format = "#,##0.00" if abs(v) < 1000 else "#,##0"
        row += 1
    ws0.column_dimensions["A"].width = 32
    for c in range(2, len(period_ends) + 2):
        ws0.column_dimensions[get_column_letter(c)].width = 14

    # Sheet 2: P&L
    ws1 = wb.create_sheet("Income Statement")
    all_pnl = pnl_rows if pnl_rows else []
    _write_formatted_sheet(ws1, "Income Statement", all_pnl or [{"label": "No P&L data", "values": {}}], period_ends, period_key_fn)

    # Sheet 3: Balance Sheet
    ws2 = wb.create_sheet("Balance Sheet")
    all_bs = bs_rows if bs_rows else []
    _write_formatted_sheet(ws2, "Balance Sheet", all_bs or [{"label": "No BS data", "values": {}}], period_ends, period_key_fn)

    # Sheet 4: Cash Flow
    ws3 = wb.create_sheet("Cash Flow")
    all_cf = cf_rows if cf_rows else []
    _write_formatted_sheet(ws3, "Cash Flow", all_cf or [{"label": "No CF data", "values": {}}], period_ends, period_key_fn)

    # Sheet 5: Full model (legacy)
    ws4 = wb.create_sheet("Full Model")
    ws4.cell(1, 1, "All Line Items").font = Font(bold=True, size=12)
    row = 3
    ws4.cell(row, 1, "Line Item").font = header_font
    for c, pe in enumerate(period_ends, start=2):
        ws4.cell(row, c, period_key_fn(pe)).font = header_font
        ws4.cell(row, c).fill = header_fill
    row += 1
    for r in normalized_rows:
        ws4.cell(row, 1, r.get("label", r.get("canonical_key", "")))
        for c, pe in enumerate(period_ends, start=2):
            v = (r.get("values") or {}).get(period_key_fn(pe))
            cell = ws4.cell(row, c, v if v is not None else "")
            if v is not None and isinstance(v, (int, float)):
                cell.number_format = "#,##0"
        row += 1
    row += 1
    ws4.cell(row, 1, "Ratios & Metrics").font = Font(bold=True, size=11)
    row += 1
    for r in metrics_rows:
        ws4.cell(row, 1, r.get("label", r.get("metric_key", "")))
        for c, pe in enumerate(period_ends, start=2):
            v = (r.get("values") or {}).get(period_key_fn(pe))
            cell = ws4.cell(row, c, v if v is not None else "")
            if v is not None and isinstance(v, (int, float)):
                cell.number_format = "#,##0.00"
        row += 1

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def _add_chart_slides(prs, blank_layout, metric_by_period: dict, facts_by_period: dict) -> None:
    """Track 5C: Add deterministic chart slides - Revenue/EBITDA, ND/EBITDA, CFO vs Capex."""
    try:
        from pptx.chart.data import CategoryChartData
        from pptx.enum.chart import XL_CHART_TYPE
        from pptx.util import Inches
    except ImportError:
        return
    periods = sorted(metric_by_period.keys(), reverse=True)[:5]
    if not periods:
        periods = sorted(facts_by_period.keys(), reverse=True)[:5]
    if not periods:
        return
    period_labels = [str(p)[:7] if hasattr(p, "isoformat") else str(p)[:7] for p in reversed(periods)]

    def _rev(pe): return facts_by_period.get(pe, {}).get("revenue")
    def _ebitda(pe): return metric_by_period.get(pe, {}).get("ebitda") or facts_by_period.get(pe, {}).get("operating_profit")
    def _nd_eb(pe): return metric_by_period.get(pe, {}).get("net_debt_to_ebitda") or metric_by_period.get(pe, {}).get("net_debt_to_ebitda_incl_leases")
    def _cfo(pe): return facts_by_period.get(pe, {}).get("net_cfo")
    def _capex(pe): return abs(facts_by_period.get(pe, {}).get("capex") or 0)

    # Chart 1: Revenue & EBITDA trend
    rev_vals = [_rev(p) for p in reversed(periods)]
    ebitda_vals = [_ebitda(p) for p in reversed(periods)]
    if any(v is not None for v in rev_vals + ebitda_vals):
        chart_data = CategoryChartData()
        chart_data.categories = period_labels
        chart_data.add_series("Revenue (Rm)", [v if v is not None else 0 for v in rev_vals])
        chart_data.add_series("EBITDA (Rm)", [v if v is not None else 0 for v in ebitda_vals])
        s = prs.slides.add_slide(blank_layout)
        tx = s.shapes.add_textbox(Inches(0.5), Inches(0.2), Inches(12), Inches(0.5))
        tx.text_frame.paragraphs[0].text = "Revenue & EBITDA Trend"
        tx.text_frame.paragraphs[0].font.bold = True
        s.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(0.5), Inches(0.7), Inches(12), Inches(5.8), chart_data)

    # Chart 2: ND/EBITDA trend
    nd_vals = [_nd_eb(p) for p in reversed(periods)]
    if any(v is not None for v in nd_vals):
        chart_data = CategoryChartData()
        chart_data.categories = period_labels
        chart_data.add_series("ND/EBITDA (x)", [v if v is not None else 0 for v in nd_vals])
        s = prs.slides.add_slide(blank_layout)
        tx = s.shapes.add_textbox(Inches(0.5), Inches(0.2), Inches(12), Inches(0.5))
        tx.text_frame.paragraphs[0].text = "ND/EBITDA Trend"
        tx.text_frame.paragraphs[0].font.bold = True
        s.shapes.add_chart(XL_CHART_TYPE.LINE, Inches(0.5), Inches(0.7), Inches(12), Inches(5.8), chart_data)

    # Chart 3: CFO vs Capex
    cfo_vals = [_cfo(p) for p in reversed(periods)]
    capex_vals = [_capex(p) for p in reversed(periods)]
    if any(v is not None and v != 0 for v in cfo_vals + capex_vals):
        chart_data = CategoryChartData()
        chart_data.categories = period_labels
        chart_data.add_series("Net CFO (Rm)", [v if v is not None else 0 for v in cfo_vals])
        chart_data.add_series("Capex (Rm)", [v if v is not None else 0 for v in capex_vals])
        s = prs.slides.add_slide(blank_layout)
        tx = s.shapes.add_textbox(Inches(0.5), Inches(0.2), Inches(12), Inches(0.5))
        tx.text_frame.paragraphs[0].text = "CFO vs Capex"
        tx.text_frame.paragraphs[0].font.bold = True
        s.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(0.5), Inches(0.7), Inches(12), Inches(5.8), chart_data)


def build_committee_pptx(
    company_name: str,
    rating_grade: str,
    recommendation: str,
    key_drivers: list[str],
    version_id: str,
    section_texts: dict[str, str] | None = None,
    metric_by_period: dict | None = None,
    facts_by_period: dict | None = None,
) -> BytesIO:
    """Build professional committee deck with styled slides, colors, and explanatory content."""
    try:
        from pptx import Presentation
        from pptx.util import Inches, Pt
        from pptx.dml.color import RGBColor
        from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
    except ImportError:
        buf = BytesIO()
        buf.write(b"PPTX generation requires python-pptx; placeholder.")
        buf.seek(0)
        return buf

    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    sections = section_texts or {}

    DARK_BLUE = RGBColor(0x1F, 0x4E, 0x79)
    ACCENT = RGBColor(0x2E, 0x75, 0xB6)
    LIGHT_BG = RGBColor(0xF2, 0xF2, 0xF2)
    RED = RGBColor(0xC0, 0x00, 0x00)
    GREEN = RGBColor(0x00, 0x70, 0x40)

    blank_layout = prs.slide_layouts[6] if len(prs.slide_layouts) > 6 else prs.slide_layouts[0]

    def add_title_slide(title_text: str, subtitle: str = ""):
        s = prs.slides.add_slide(blank_layout)
        left = Inches(0.5)
        top = Inches(2.2)
        width = Inches(12.3)
        tx = s.shapes.add_textbox(left, top, width, Inches(1.2))
        tf = tx.text_frame
        p = tf.paragraphs[0]
        p.text = title_text
        p.font.size = Pt(40)
        p.font.bold = True
        p.font.color.rgb = DARK_BLUE
        if subtitle:
            tx2 = s.shapes.add_textbox(left, Inches(3.6), width, Inches(1))
            tf2 = tx2.text_frame
            p2 = tf2.paragraphs[0]
            p2.text = subtitle[:400]
            p2.font.size = Pt(18)
            p2.font.color.rgb = ACCENT

    def add_content_slide(title_text: str, body: str, highlight: str | None = None):
        s = prs.slides.add_slide(blank_layout)
        # Title bar
        box = s.shapes.add_shape(1, Inches(0), Inches(0), Inches(13.333), Inches(1.2))  # Rectangle
        box.fill.solid()
        box.fill.fore_color.rgb = DARK_BLUE
        box.line.fill.background()
        tx = s.shapes.add_textbox(Inches(0.5), Inches(0.25), Inches(12), Inches(0.8))
        tf = tx.text_frame
        p = tf.paragraphs[0]
        p.text = title_text
        p.font.size = Pt(28)
        p.font.bold = True
        p.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
        # Body
        body_box = s.shapes.add_textbox(Inches(0.6), Inches(1.5), Inches(12), Inches(5.5))
        tf = body_box.text_frame
        tf.word_wrap = True
        lines = (body or "N/A").split("\n")[:25]
        for i, line in enumerate(lines[:15]):
            if i == 0:
                p = tf.paragraphs[0]
            else:
                p = tf.add_paragraph()
            line = line.strip()
            if len(line) > 120:
                line = line[:117] + "..."
            p.text = line
            p.font.size = Pt(14)
            p.space_after = Pt(8)
        if highlight:
            hl = s.shapes.add_textbox(Inches(0.6), Inches(5.8), Inches(12), Inches(0.8))
            tf2 = hl.text_frame
            p2 = tf2.paragraphs[0]
            p2.text = "► " + highlight[:200]
            p2.font.size = Pt(12)
            p2.font.italic = True
            p2.font.color.rgb = ACCENT

    def _truncate_for_slide(t: str, max_len: int = 1200) -> str:
        t = (t or "")[:max_len]
        if len(t) >= max_len:
            t = t[:max_len - 3] + "..."
        return t

    # 1. Title
    add_title_slide(
        f"Credit Committee",
        f"{company_name}  •  Rating: {rating_grade}  •  Recommendation: {recommendation}  •  v{version_id[:8]}"
    )

    # 2. Executive Summary
    exec_sum = _truncate_for_slide(sections.get("executive_summary", ""), 900)
    add_content_slide("Executive Summary", exec_sum, "Key risks and mitigants are detailed in the sections below.")

    # Track 5C: Deck charts - revenue/EBITDA, ND/EBITDA, CFO vs capex
    _add_chart_slides(prs, blank_layout, metric_by_period or {}, facts_by_period or {})

    # 3. Financial Performance
    add_content_slide("Financial Performance", _truncate_for_slide(sections.get("financial_performance", "")))

    # 4. Cash Flow & Liquidity
    add_content_slide("Cash Flow & Liquidity", _truncate_for_slide(sections.get("cash_flow_liquidity", "")), "12-month forward liquidity model.")

    # 5. Balance Sheet & Leverage
    add_content_slide("Balance Sheet & Leverage", _truncate_for_slide(sections.get("balance_sheet_leverage", "")))

    # 6. Key Risks
    add_content_slide("Key Risks", _truncate_for_slide(sections.get("key_risks", "")))

    # 7. Stress Testing
    add_content_slide("Stress Testing Results", _truncate_for_slide(sections.get("stress_testing_results", "")), "Breaches under stress trigger governance notch downgrades.")

    # 8. Covenants
    add_content_slide("Covenants & Headroom", _truncate_for_slide(sections.get("covenants_headroom", "")))

    # 9. Rating Rationale
    add_content_slide("Internal Rating Rationale", _truncate_for_slide(sections.get("internal_rating_rationale", f"Rating: {rating_grade}")))

    # 10. Recommendation
    rec_text = f"Recommendation: {recommendation}\n\nKey drivers monitored: " + ", ".join(str(d) for d in key_drivers[:6])
    add_content_slide("Recommendation", rec_text)

    buf = BytesIO()
    prs.save(buf)
    buf.seek(0)
    return buf
