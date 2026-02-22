import hashlib
import re
from uuid import UUID
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

import fitz  # PyMuPDF

from app.config import get_settings
from app.models.document import DocumentVersion, Document, PageAsset, PageLayout
from app.models.extraction import PresentationContext, NotesIndex, NoteExtraction, NoteChunk, Statement, StatementLine
from app.models.mapping import NormalizedFact
from app.models.metrics import MetricFact, RatingModel, RatingResult
from app.models.company import CreditReview, CreditReviewVersion, Engagement, ReviewStatus
from app.services.storage import download_file_from_url
from app.worker.celery_app import celery_app

# Max chars to send to LLM (leave room for prompt + response; ~100k chars ~= 25k tokens)
_EXTRACTION_TEXT_LIMIT = 100_000

# Sync engine for Celery (workers typically use sync DB)
# Recycle connections every 5 min to avoid "SSL connection closed" with cloud DBs (Neon etc.)
_sync_engine = None

def get_sync_session() -> Session:
    global _sync_engine
    if _sync_engine is None:
        url = get_settings().database_url.replace("+asyncpg", "").replace("postgresql+asyncpg", "postgresql")
        _sync_engine = create_engine(url, pool_pre_ping=True, pool_recycle=300)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_sync_engine)
    return SessionLocal()


def _split_statement_page_into_regions(
    page: dict,
    per_region_limit: int = 3000,
) -> list[dict]:
    """
    Split a single statement page into multiple LLM regions, each capped at per_region_limit characters.

    Special handling:
    - If the page contains the SFP sentinel "total equity and liabilities", we try to end the first
      region at the end of that line so the full SFP face is grouped together.
    - Remaining text on the page (e.g. another statement) is chunked sequentially into new regions.
    """
    text = page.get("text", "") or ""
    if not text.strip():
        return []

    regions: list[dict] = []
    page_no = page.get("page")
    base_region_id = page.get("region_id", f"page{page_no}")

    lower = text.lower()
    marker = "total equity and liabilities"
    split_points: list[int] = []

    if marker in lower:
        idx = lower.find(marker)
        # Include the full line containing the marker
        end_of_line = text.find("\n", idx)
        if end_of_line == -1:
            end_of_line = len(text)
        # Never exceed the per-region character limit
        split_points.append(min(end_of_line, idx + len(marker), per_region_limit))

    start = 0
    part = 1

    # First, emit any special split segments (e.g. SFP up to "total equity and liabilities")
    for sp in split_points:
        if sp <= start:
            continue
        chunk = text[start:sp]
        if chunk.strip():
            regions.append(
                {
                    "region_id": f"{base_region_id}_p{part}",
                    "page": page_no,
                    "text": chunk[:per_region_limit],
                }
            )
            part += 1
        start = sp

    # Then, chunk the remaining text sequentially into per_region_limit-sized regions
    n = len(text)
    while start < n:
        end = min(start + per_region_limit, n)
        chunk = text[start:end]
        if chunk.strip():
            regions.append(
                {
                    "region_id": f"{base_region_id}_p{part}",
                    "page": page_no,
                    "text": chunk,
                }
            )
            part += 1
        start = end

    return regions


def _extract_regions_from_page(page: "fitz.Page") -> list[dict]:
    """Build regions_json (bbox, label, confidence) from PyMuPDF page dict."""
    regions = []
    try:
        d = page.get_text("dict")
        for block in d.get("blocks", []):
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    bbox = span.get("bbox")
                    if bbox and len(bbox) >= 4:
                        regions.append({
                            "bbox": [round(bbox[0], 1), round(bbox[1], 1), round(bbox[2], 1), round(bbox[3], 1)],
                            "label": "text",
                            "confidence": 1.0,
                        })
    except Exception:
        pass
    return regions if regions else [{"bbox": [0, 0, 100, 20], "label": "text", "confidence": 0.9}]


@celery_app.task(bind=True, name="app.worker.tasks.run_ingest_pipeline")
def run_ingest_pipeline(self, document_version_id: str):
    """Ingest document: download PDF, extract pages and text blocks, store page assets."""
    db = get_sync_session()
    try:
        version = db.get(DocumentVersion, UUID(document_version_id))
        if not version:
            return {"error": "DocumentVersion not found"}
        doc = db.get(Document, version.document_id)
        if not doc or not doc.storage_url:
            return {"error": "Document or storage URL not found"}
        version.status = "INGESTING"
        db.commit()

        pdf_bytes = download_file_from_url(doc.storage_url)
        pdf_doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        page_count = len(pdf_doc)

        for page_no in range(1, page_count + 1):
            page = pdf_doc[page_no - 1]
            page_text = page.get_text()
            text_hash = hashlib.sha256(page_text.encode("utf-8", errors="replace")).hexdigest() if page_text else None

            pa = PageAsset(
                document_version_id=version.id,
                page_no=page_no,
                text_hash=text_hash,
            )
            db.add(pa)
            db.flush()
            regions = _extract_regions_from_page(page)
            layout = PageLayout(page_asset_id=pa.id, regions_json=regions)
            db.add(layout)

        pdf_doc.close()
        version.status = "EXTRACTING"
        db.commit()

        celery_app.send_task("app.worker.tasks.run_extraction", args=[str(version.id)])
        return {"document_version_id": document_version_id, "pages": page_count, "status": version.status}
    except Exception as e:
        if db:
            version = db.get(DocumentVersion, UUID(document_version_id))
            if version:
                version.status = "FAILED"
                db.commit()
        raise
    finally:
        db.close()


def _get_pages_text(doc: Document) -> list[dict]:
    """Download PDF and return list of {region_id, page, text} per page (deterministic input for LLM).

    Returns full page text; chunking to 3k chars per region is done by _split_statement_page_into_regions
    so long statements (e.g. full SCI) are not truncated.
    """
    pdf_bytes = download_file_from_url(doc.storage_url)
    pdf_doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    out = []
    for i in range(len(pdf_doc)):
        page_no = i + 1
        text = pdf_doc[i].get_text() or ""
        out.append({"region_id": f"page{page_no}", "page": page_no, "text": text})
    pdf_doc.close()
    return out


def _lines_from_region_text(text: str, statement_type: str, section_path: list[str], max_lines: int = 80) -> list[dict]:
    """Heuristic: split page text into lines; treat as raw_label for canonical mapping. No numbers invented."""
    lines = []
    for raw in text.splitlines():
        raw = raw.strip()
        if not raw or len(raw) < 3 or len(raw) > 250:
            continue
        lines.append({"statement_type": statement_type, "section_path": section_path, "raw_label": raw})
        if len(lines) >= max_lines:
            break
    return lines


# Canonical SoCE column keys (must match soce_parser and export)
_SOCE_CANONICAL_KEYS = (
    "total_equity", "non_controlling_interest", "attributable_total",
    "stated_capital", "treasury_shares", "other_reserves", "retained_earnings",
)


def _parse_soce_column_id(col_id: str, period_labels: list[str]) -> tuple[str | None, str | None]:
    """Parse column id like total_equity_2024 -> (soce_key, period). Returns (None, None) if not SoCE format."""
    for p in period_labels:
        if col_id.endswith(f"_{p}"):
            prefix = col_id[: -len(p) - 1]
            if prefix in _SOCE_CANONICAL_KEYS:
                return (prefix, p)
    return (None, None)


def _build_soce_values_json_from_llm(
    raw_value_strings: dict,
    columns: list[dict],
    period_labels: list[str],
    scale_factor: float,
) -> tuple[dict, list[str]]:
    """Build values_json {period: {soce_key: value}} from LLM SoCE output. Returns (values_json, soce_columns_in_order)."""
    from app.services.value_parser import parse_raw_value_string
    values_json: dict[str, dict[str, float | None]] = {p: {} for p in period_labels}
    soce_columns_ordered: list[str] = []
    seen: set[str] = set()
    for c in columns:
        cid = c.get("id", "")
        soce_key, period = _parse_soce_column_id(cid, period_labels)
        if soce_key and period:
            if soce_key not in seen:
                seen.add(soce_key)
                soce_columns_ordered.append(soce_key)
            raw = raw_value_strings.get(cid)
            parsed = parse_raw_value_string(raw) if raw else None
            val = float(parsed * scale_factor) if parsed is not None else None
            values_json.setdefault(period, {})[soce_key] = val
    if not soce_columns_ordered:
        soce_columns_ordered = list(_SOCE_CANONICAL_KEYS)
    return values_json, soce_columns_ordered


def _values_json_for_storage(
    parsed: dict[str, float | None],
    column_keys: list[str],
    columns: list[dict],
    period_labels: list[str],
) -> dict[str, float | None]:
    """Convert parsed to values_json; use label and year keys so export lookup works regardless of label format."""
    cols_by_id = {c["id"]: c for c in columns}
    out: dict[str, float | None] = {}
    for i, k in enumerate(column_keys):
        v = parsed.get(k)
        col = cols_by_id.get(k) if cols_by_id else None
        label = col.get("label") if col else (period_labels[i] if i < len(period_labels) else k)
        out[label] = v
        # Also store under year key (2025, 2024) so export finds values when period_labels differ
        if v is not None and label:
            m = re.search(r"\b(20\d{2})\b", str(label))
            if m and m.group(1) not in out:
                out[m.group(1)] = v
    return out if out else dict(parsed)


def _raw_value_string_from_parsed(val: float | None) -> str | None:
    """Convert a parsed numeric to a string for raw_value_strings (legacy compat)."""
    if val is None:
        return None
    s = str(int(val)) if isinstance(val, float) and val.is_integer() else str(val)
    return f" ({s}) " if val < 0 else f" {s} "


def _parse_amount(raw: str) -> float | None:
    """Parse a numeric amount from a string, preserving sign and brackets; return None if not a plain amount."""
    s = raw.strip().replace("\u00a0", " ")
    # Remove thousands separators and spaces
    neg = False
    if s.startswith("(") and s.endswith(")"):
        neg = True
        s = s[1:-1]
    s = s.replace(" ", "").replace(",", "")
    # Reject if it now contains anything but digits and decimal point
    if not s or any(c for c in s if not (c.isdigit() or c == "." or c == "-")):
        return None
    try:
        val = float(s)
    except ValueError:
        return None
    if neg:
        val = -val
    return val


def _detect_period_labels_from_text(text: str, max_periods: int = 4) -> list[str]:
    """Heuristic: pull distinct year-like tokens (20xx) from a statement page, newest first."""
    years = []
    for m in re.finditer(r"\b(20\d{2})\b", text):
        y = m.group(1)
        if y not in years:
            years.append(y)
    years.sort(reverse=True)
    return years[:max_periods] if years else []


def _extract_structured_lines_from_statement_page(
    text: str,
    period_labels: list[str],
    start_line_no: int = 1,
    statement_type: str = "SFP",
) -> list[dict]:
    """Very simple heuristic parser for tabular statement pages.

    Assumptions (matched to typical SFP / SoCE / SCI layouts):
    - Each line item label (e.g. 'Property, plant and equipment') appears on its own line.
    - Optional note number appears on a separate short numeric line immediately after the label.
    - One numeric line per period follows (e.g. '22 536', '19 672').
    - statement_type: SFP, SCI, SOCE, IS - controls header guards and stop conditions.
    """
    lines: list[dict] = []
    current_label: str | None = None
    current_note: str | None = None
    current_values: list[float | None] = []
    line_no = start_line_no
    is_sfp = statement_type.upper() == "SFP"

    def flush_current() -> None:
        nonlocal current_label, current_note, current_values, line_no, lines
        if current_label and any(v is not None for v in current_values):
            raw_value_strings = {
                lbl: _raw_value_string_from_parsed(v) if i < len(current_values) else None
                for i, lbl in enumerate(period_labels)
            }
            values_json = {}
            for i, lbl in enumerate(period_labels):
                if i < len(current_values):
                    v = current_values[i]
                    values_json[lbl] = v
            lines.append(
                {
                    "line_no": line_no,
                    "raw_label": current_label,
                    "note": current_note,
                    "raw_value_strings": raw_value_strings,
                    "values_json": values_json,
                }
            )
            line_no += 1
        current_label = None
        current_note = None
        current_values = []

    for raw in text.splitlines():
        s = raw.strip()
        if not s:
            continue

        lower = s.lower()

        # Hard stop for SFP only: non-SFP narrative that can appear on the same page
        # (e.g. basis-of-preparation, profit/52-weeks). For SCI/SOCE, "52 weeks" and
        # "profit for the year" are valid line items.
        if is_sfp and ("52 weeks" in lower or "profit for the year" in lower):
            if current_label:
                flush_current()
            break

        # Header guard: skip obvious headings that are not line items
        if "consolidated statement" in lower or "statement of financial position" in lower:
            continue
        if "statement of comprehensive income" in lower or "statement of profit" in lower:
            continue
        if "statement of cash flows" in lower or "cash flow statement" in lower:
            continue
        if is_sfp and lower in {"assets", "equity", "liabilities"}:
            # treat as section header, flush any pending row
            if current_label:
                flush_current()
            continue

        # Try numeric amount
        amt = _parse_amount(s)
        if amt is not None:
            # Note number heuristic: small integer line immediately after label and before first amount
            if (
                current_label
                and current_note is None
                and not current_values
                and s.isdigit()
                and int(s) < 500
            ):
                current_note = s
                continue
            if current_label:
                if len(current_values) < len(period_labels):
                    current_values.append(amt)
            continue

        # Note number line without amount pattern
        if (
            current_label
            and current_note is None
            and not current_values
            and s.isdigit()
            and int(s) < 500
        ):
            current_note = s
            continue

        # New label line (contains letters)
        if any(c.isalpha() for c in s):
            # Try to parse inline pattern: "Label ... <note?> <amount_1> <amount_2>"
            tokens = s.split()
            first_num_idx = None
            for i, tok in enumerate(tokens):
                if any(ch.isdigit() for ch in tok):
                    first_num_idx = i
                    break
            if first_num_idx is not None:
                label_part = " ".join(tokens[:first_num_idx]).strip()
                numeric_tokens = tokens[first_num_idx:]
                inline_note: str | None = None
                inline_amounts: list[float] = []
                for tok in numeric_tokens:
                    amt_tok = _parse_amount(tok)
                    if amt_tok is None:
                        continue
                    # First small integer can be treated as note number if more numbers follow
                    if (
                        inline_note is None
                        and not inline_amounts
                        and amt_tok.is_integer()
                        and 0 < int(amt_tok) < 500
                    ):
                        inline_note = str(int(amt_tok))
                        continue
                    inline_amounts.append(amt_tok)
                if label_part and inline_amounts:
                    if current_label:
                        flush_current()
                    current_label = label_part
                    current_note = inline_note
                    current_values = inline_amounts[: len(period_labels)]
                    continue

            if current_label:
                flush_current()
            current_label = s
            continue

    if current_label:
        flush_current()

    return lines


def _extract_note_blocks(full_text: str) -> list[tuple[str | int, str, str]]:
    """Simple split: find 'Note N' or 'N. Title' patterns and yield (note_number, title, body)."""
    blocks = []
    # Match "Note 16" or "16. Borrowings" or "16 Borrowings"
    pattern = re.compile(r"(?i)(?:Note\s+)?(\d+)[\.\s\-–—]+\s*([^\n]+)")
    pos = 0
    for m in pattern.finditer(full_text):
        num, title = m.group(1), m.group(2).strip()
        start = m.end()
        next_m = pattern.search(full_text, start)
        end = next_m.start() if next_m else len(full_text)
        body = full_text[start:end].strip()[:12000]
        blocks.append((num, title, body))
        if len(blocks) >= 30:
            break
    return blocks


@celery_app.task(name="app.worker.tasks.run_extraction")
def run_extraction(document_version_id: str):
    """
    Extraction pipeline:
    - Load page text from PDF
    - Use section locator to identify key statement/note pages
    - Call LLM semantic tasks (A–E) on those focused snippets

    Runs once per document version. Multiple runs in logs = multiple versions queued
    (e.g. several uploads). Within one run, LLM is called in batches (e.g. 8 pages,
    80 lines per request), so many HTTP/prompt logs per version is expected.
    """
    import logging
    log = logging.getLogger(__name__)
    log.info("run_extraction starting for document_version_id=%s", document_version_id)

    db = get_sync_session()
    try:
        version = db.get(DocumentVersion, UUID(document_version_id))
        if not version:
            return {"error": "DocumentVersion not found"}
        # Idempotency: if already MAPPED, skip expensive LLM work and just chain mapping
        if version.status == "MAPPED":
            log.info("run_extraction skipping (already MAPPED) document_version_id=%s", document_version_id)
            celery_app.send_task("app.worker.tasks.run_mapping", args=[document_version_id])
            return {"document_version_id": document_version_id, "status": "MAPPED", "skipped": True}
        doc = db.get(Document, version.document_id)
        if not doc or not doc.storage_url:
            version.status = "FAILED"
            db.commit()
            return {"error": "Document or storage URL not found"}

        dv_id = str(version.id)
        pages = _get_pages_text(doc)
        if not pages:
            version.status = "EXTRACTING"
            db.commit()
            celery_app.send_task("app.worker.tasks.run_mapping", args=[dv_id])
            return {"document_version_id": document_version_id, "status": version.status, "llm_tasks": 0}

        # Import LLM tasks
        from app.services.llm.tasks import (
            llm_region_classifier,
            llm_scale_extractor,
            llm_canonical_mapper,
            llm_note_classifier,
            llm_risk_snippets,
            llm_statement_table_parser,
        )

        # Import section locator and note pipeline
        from app.services.section_locator import Page as LocatorPage
        from app.services.section_locator import (
            detect_scale_and_currency,
            detect_sections_and_note_packets,
        )
        from app.services.notes_index_extractor import (
            extract_notes_index_from_pages,
            infer_index_from_packets,
        )
        from app.services.notes_extractors import extract_note_by_type
        from app.services.reconciliation import run_reconciliation

        tasks_done = 0

        def _inject_evidence_dv_id(obj: dict, dv: str) -> None:
            """Inject document_version_id into all evidence_spans in nested obj."""
            if isinstance(obj, dict):
                if "evidence_spans" in obj:
                    for span in obj["evidence_spans"]:
                        if isinstance(span, dict):
                            span["document_version_id"] = dv
                for v in obj.values():
                    _inject_evidence_dv_id(v, dv)
            elif isinstance(obj, list):
                for item in obj:
                    _inject_evidence_dv_id(item, dv)

        # Build locator pages (one per physical page) and detect sections + note packets
        locator_pages_map: dict[int, str] = {}
        for p in pages:
            pg = p["page"]
            txt = p.get("text", "") or ""
            # If multiple entries exist for the same page, concatenate their text for locator purposes
            if pg in locator_pages_map:
                locator_pages_map[pg] += "\n" + txt
            else:
                locator_pages_map[pg] = txt
        locator_pages = [LocatorPage(page=pg, text=txt) for pg, txt in sorted(locator_pages_map.items())]
        scale_info = detect_scale_and_currency(locator_pages)
        sections, note_packets = detect_sections_and_note_packets(locator_pages)

        # Find where statements end – truncate document so we never look at notes (re-enable notes later)
        statement_pages_indices = {
            p.page for sec in ("sofp", "soci", "soce", "cashflow") for p in sections.get(sec, [])
        }
        last_statement_page = max(statement_pages_indices) if statement_pages_indices else None
        if last_statement_page is not None:
            pages = [p for p in pages if p["page"] <= last_statement_page]

        # Build statement regions (potentially multiple regions per page, each <= 3k chars)
        statement_regions: list[dict] = []
        for p in pages:
            if p["page"] in statement_pages_indices:
                statement_regions.extend(_split_statement_page_into_regions(p))

        # A) Region classification (only on statement regions – not notes)
        region_result = llm_region_classifier(statement_regions, dv_id)
        if region_result:
            payload = region_result.model_dump()
            _inject_evidence_dv_id(payload, dv_id)
            db.add(PresentationContext(
                document_version_id=version.id,
                scope="DOC",
                scope_key="region_classification",
                evidence_json=payload,
            ))
            tasks_done += 1

        # B) Presentation scale: if locator found something, store deterministically;
        # otherwise fall back to LLM on first page with text.
        if scale_info.get("currency") or scale_info.get("scale"):
            db.add(PresentationContext(
                document_version_id=version.id,
                scope="DOC",
                scope_key="presentation_scale",
                currency=scale_info.get("currency"),
                scale=scale_info.get("scale"),
                scale_factor=scale_info.get("scale_factor"),
                period_weeks=None,
                evidence_json={},
            ))
            tasks_done += 1
        else:
            for p in pages:
                if p.get("text", "").strip():
                    scale_result = llm_scale_extractor(p["region_id"], p["text"], dv_id)
                    if scale_result:
                        payload = scale_result.model_dump()
                        _inject_evidence_dv_id(payload, dv_id)
                        db.add(PresentationContext(
                            document_version_id=version.id,
                            scope="DOC",
                            scope_key="presentation_scale",
                            evidence_json=payload,
                        ))
                        tasks_done += 1
                    break

        # C) Canonical mapping: build statement_lines from only statement pages
        region_type_by_id: dict[str, str] = {}
        first_notes_page: int | None = None  # stop scanning once LLM returns NOTES
        if region_result:
            region_id_to_page = {p["region_id"]: p["page"] for p in statement_regions}
            for r in region_result.regions:
                region_type_by_id[r.region_id] = r.statement_type
            # Only treat NOTES as "notes section" when it appears AFTER the primary statements.
            # Accounting policies often mention "statement of comprehensive income" and get
            # mis-scored as soci; LLM correctly classifies them as NOTES. We must not exclude
            # the real SFP/SCI (e.g. pages 18-19) when NOTES appears earlier (e.g. page 15).
            _st = frozenset(("SFP", "SCI", "IS", "CF", "SOCE"))
            stmt_pages = [
                region_id_to_page[r.region_id]
                for r in region_result.regions
                if r.statement_type in _st and r.region_id in region_id_to_page
            ]
            max_statement_page = max(stmt_pages, default=0)
            for r in region_result.regions:
                if r.statement_type == "NOTES" and r.region_id in region_id_to_page:
                    pg = region_id_to_page[r.region_id]
                    if pg > max_statement_page and (first_notes_page is None or pg < first_notes_page):
                        first_notes_page = pg

        # Universal statement flow: same path for all types (SFP, SCI, IS, CF, SOCE).
        # 1) Take raw region text from PDF (already located by region classifier).
        # 2) LLM parses table: headers (period_labels) + rows (raw_label, values per column). Fallback: heuristic parser.
        # 3) Use parsed lines for canonical mapping and for Statement + StatementLine persistence.
        _STATEMENT_TYPES = frozenset(("SFP", "SCI", "IS", "CF", "SOCE"))
        parsed_by_type: dict[str, list[dict]] = {}  # statement_type -> list of {period_labels, lines with raw_label/values_json/note_ref/section_path, page}
        for region in statement_regions:
            if region["page"] not in statement_pages_indices:
                continue
            if first_notes_page is not None and region["page"] >= first_notes_page:
                continue
            stype = region_type_by_id.get(region["region_id"], "OTHER")
            if stype not in _STATEMENT_TYPES:
                continue
            text = (region.get("text") or "").strip()
            if not text:
                continue
            region_id = region.get("region_id", "")
            page = region.get("page")
            from app.services.column_normalizer import derive_columns_from_period_labels
            columns: list[dict] = []
            doc_hash = getattr(version, "sha256", None) if version else None

            # SoCE: deterministic geometry pipeline first; fallback to LLM
            if stype == "SOCE":
                from app.services.soce_parser import extract_soce_structured_lines
                from app.services.soce_geometry_extractor import extract_soce_structured_lines_geometry
                from app.services.soce_page_image import upload_soce_page_image
                from app.services.llm.tasks import llm_soce_table_from_image

                soce_lines: list[dict] = []
                if page and doc and version and doc.storage_url:
                    try:
                        pdf_bytes = download_file_from_url(doc.storage_url)
                        soce_lines = extract_soce_structured_lines_geometry(pdf_bytes, page, start_line_no=1)
                        if not soce_lines:
                            _, png_bytes = upload_soce_page_image(
                                pdf_bytes, page, str(doc.tenant_id), str(version.id)
                            )
                            import base64
                            b64 = base64.b64encode(png_bytes).decode("ascii")
                            out = llm_soce_table_from_image(
                                b64, str(version.id), page, doc_hash=doc_hash, pdf_text=text
                            )
                            if out and out.lines and out.column_headers:
                                headers = list(out.column_headers)
                                columns = [str(i) for i in range(len(headers))]
                                for i, line in enumerate(out.lines):
                                    vals = line.values if hasattr(line, "values") else []
                                    values_by_col: dict[str, float | None] = {}
                                    for j in range(len(columns)):
                                        v = vals[j] if j < len(vals) else None
                                        values_by_col[str(j)] = float(v) if v is not None else None
                                    soce_lines.append({
                                        "line_no": 1 + i,
                                        "raw_label": line.raw_label,
                                        "note": line.note_ref,
                                        "values_json": {"": values_by_col},
                                        "section_path": line.section_path,
                                        "evidence_json": {"page": page},
                                        "column_keys": columns,
                                        "column_headers": headers,
                                        "period_labels": [""],
                                    })
                    except Exception as e:
                        log.warning("SoCE LLM table extraction failed: %s", e)
                if not soce_lines:
                    soce_lines = extract_soce_structured_lines(
                        text, start_line_no=1, page_no=page
                    )
                if soce_lines:
                    column_keys = soce_lines[0].get("column_keys") or []
                    column_headers = soce_lines[0].get("column_headers") or []
                    period_labels = soce_lines[0].get("period_labels") or [""]
                    doc_sf = scale_info.get("scale_factor") or 1.0
                    rows = []
                    for x in soce_lines:
                        vj = x.get("values_json") or {}
                        if doc_sf != 1.0 and vj:
                            scaled_vj = {}
                            for period, cols in vj.items():
                                scaled_vj[period] = {
                                    c: (float(v) * doc_sf if v is not None else None)
                                    for c, v in cols.items()
                                }
                            vj = scaled_vj
                        rows.append({
                            "raw_label": x["raw_label"],
                            "raw_value_strings": {},
                            "values_json": vj,
                            "note_ref": x.get("note"),
                            "section_path": x.get("section_path"),
                            "row_role": "line_item",
                        })
                    key = "SoCE"
                    if key not in parsed_by_type:
                        parsed_by_type[key] = []
                    parsed_by_type[key].append({
                        "period_labels": period_labels,
                        "soce_columns": column_keys,
                        "soce_header_labels": column_headers,
                        "columns_normalized": [],
                        "rows": rows,
                        "page": page,
                        "scale_info": {},
                    })
                    continue  # skip LLM/heuristic for this region

            # SFP, SCI, CF: try geometry extraction first, then LLM fallback
            if stype in ("SFP", "SCI", "IS", "CF"):
                from app.services.statement_geometry_extractor import extract_statement_structured_lines
                
                fs_lines: list[dict] = []
                if page and doc and version and doc.storage_url:
                    try:
                        if 'pdf_bytes' not in dir() or pdf_bytes is None:
                            pdf_bytes = download_file_from_url(doc.storage_url)
                        fs_lines = extract_statement_structured_lines(pdf_bytes, page, stype, start_line_no=1)
                    except Exception as e:
                        log.warning("Geometry extraction failed for %s page %s: %s", stype, page, e)
                
                if fs_lines:
                    # Get period labels from first line
                    period_labels = fs_lines[0].get("period_labels") or ["current", "prior"]
                    column_keys = period_labels
                    doc_sf = scale_info.get("scale_factor") or 1.0
                    rows = []
                    for x in fs_lines:
                        vj = x.get("values_json") or {}
                        if doc_sf != 1.0 and vj:
                            scaled_vj = {}
                            for period, cols in vj.items():
                                if isinstance(cols, dict):
                                    scaled_vj[period] = {
                                        c: (float(v) * doc_sf if v is not None else None)
                                        for c, v in cols.items()
                                    }
                                else:
                                    scaled_vj[period] = float(cols) * doc_sf if cols is not None else None
                            vj = scaled_vj
                        rows.append({
                            "raw_label": x.get("raw_label") or "",
                            "raw_value_strings": {},
                            "values_json": vj,
                            "note_ref": x.get("note"),
                            "section_path": x.get("section_path"),
                            "row_role": "line_item",
                        })
                    key = stype
                    if key not in parsed_by_type:
                        parsed_by_type[key] = []
                    parsed_by_type[key].append({
                        "period_labels": period_labels,
                        "columns_normalized": [],
                        "rows": rows,
                        "page": page,
                        "scale_info": {},
                    })
                    continue  # skip LLM/heuristic for this region

            parse_out = llm_statement_table_parser(region_id, text, stype, dv_id, doc_hash=doc_hash)
            if parse_out is not None and (parse_out.period_labels or parse_out.lines):
                period_labels = parse_out.period_labels or ["current", "prior"]
                from app.services.value_parser import parse_and_scale, scale_factor_from_literal
                from app.services.column_normalizer import (
                    derive_columns_from_period_labels,
                    get_column_ids,
                    raw_value_strings_to_column_keys,
                )
                cols_raw = [c.model_dump() if hasattr(c, "model_dump") else c for c in (getattr(parse_out, "columns_normalized", None) or [])]
                columns = cols_raw if cols_raw else derive_columns_from_period_labels(period_labels)
                value_column_ids = get_column_ids(columns, value_only=True)
                column_keys = value_column_ids if value_column_ids else period_labels
                if not scale_info.get("scale_factor") and parse_out.scale:
                    scale_info["scale_factor"] = scale_factor_from_literal(parse_out.scale)
                    scale_info["scale"] = parse_out.scale
                table_scale_factor = scale_factor_from_literal(parse_out.scale) if parse_out.scale else scale_info.get("scale_factor") or 1.0
                doc_scale = scale_info.get("scale_factor") or 1.0
                sf = table_scale_factor if table_scale_factor and table_scale_factor != 1.0 else doc_scale
                cols_by_id = {c["id"]: c for c in columns}
                soce_columns_from_llm = []
                # SOCE + LLM: detect SoCE-style column ids (soce_key_period)
                is_llm_soce = (
                    stype == "SOCE"
                    and columns
                    and any(_parse_soce_column_id(c.get("id", ""), period_labels)[0] for c in columns)
                )

                rows = []
                soce_columns_from_llm: list[str] = []
                for line in parse_out.lines:
                    raw_strs = getattr(line, "raw_value_strings", None) or {}
                    legacy_vals = getattr(line, "values_json", None)
                    if is_llm_soce and raw_strs:
                        values_json, soce_cols = _build_soce_values_json_from_llm(
                            raw_strs, columns, period_labels, sf
                        )
                        if soce_cols and not soce_columns_from_llm:
                            soce_columns_from_llm = soce_cols
                    elif raw_strs and any(v is not None and str(v).strip() for v in raw_strs.values()):
                        raw_mapped = raw_value_strings_to_column_keys(raw_strs, columns) if columns else raw_strs
                        parsed = parse_and_scale(raw_mapped, column_keys, scale_factor=sf)
                        values_json = _values_json_for_storage(parsed, column_keys, columns, period_labels)
                    elif legacy_vals:
                        values_json = {}
                        for lbl, v in legacy_vals.items():
                            if lbl in period_labels:
                                values_json[lbl] = float(v) * sf if v is not None else None
                        # Include keys matching period_labels by year (e.g. "2025" when period_labels has "52 weeks 2025 Rm")
                        for lbl, v in legacy_vals.items():
                            if v is not None and lbl not in values_json:
                                m = re.search(r"\b(20\d{2})\b", str(lbl))
                                if m:
                                    yr = m.group(1)
                                    for pl in period_labels:
                                        if yr in str(pl):
                                            values_json[pl] = float(v) * sf
                                            values_json[yr] = float(v) * sf
                                            break
                        if not values_json:
                            values_json = {lbl: (float(v) * sf if v is not None else None) for lbl, v in legacy_vals.items()}
                        raw_strs = {lbl: _raw_value_string_from_parsed(v) for lbl, v in (legacy_vals or {}).items()}
                    else:
                        values_json = {}
                    rows.append({
                        "raw_label": line.raw_label,
                        "raw_value_strings": raw_strs,
                        "values_json": values_json,
                        "note_ref": line.note_ref,
                        "section_path": line.section_path,
                        "row_role": getattr(line, "row_role", "line_item"),
                    })
            else:
                # Fallback: heuristic parser (apply doc scale)
                period_labels = _detect_period_labels_from_text(text) or ["current", "prior"]
                columns = derive_columns_from_period_labels(period_labels)
                structured = _extract_structured_lines_from_statement_page(
                    text, period_labels, start_line_no=1, statement_type=stype
                )
                doc_sf = scale_info.get("scale_factor") or 1.0
                rows = []
                for row in structured:
                    vj = row.get("values_json") or {}
                    scaled = {lbl: (float(v) * doc_sf if v is not None else None) for lbl, v in vj.items()}
                    rows.append({
                        "raw_label": row["raw_label"],
                        "raw_value_strings": row.get("raw_value_strings", {}),
                        "values_json": scaled,
                        "note_ref": row.get("note"),
                        "section_path": None,
                        "row_role": "line_item",
                    })
            if not rows:
                continue
            key = "SoCE" if stype == "SOCE" else stype
            if key not in parsed_by_type:
                parsed_by_type[key] = []
            chunk_cols = columns
            chunk_scale = {}
            if parse_out is not None:
                chunk_scale = {"scale": getattr(parse_out, "scale", None), "scale_evidence": getattr(parse_out, "scale_evidence", None), "scale_source": getattr(parse_out, "scale_source", None)}
            chunk_extra: dict = {}
            if stype == "SOCE" and soce_columns_from_llm:
                chunk_extra["soce_columns"] = soce_columns_from_llm
            parsed_by_type[key].append({
                "period_labels": period_labels,
                "columns_normalized": chunk_cols,
                "rows": rows,
                "page": page,
                "scale_info": chunk_scale,
                **chunk_extra,
            })

        # Refresh DB session before bulk persist: connection may have gone stale during long LLM work
        # (cloud Postgres like Neon often close idle SSL connections after 1–2 min)
        try:
            db.commit()
        except Exception:
            db.rollback()
        db.close()
        db = get_sync_session()
        version = db.get(DocumentVersion, UUID(document_version_id))
        if not version:
            return {"error": "DocumentVersion not found after session refresh"}

        # Build statement_lines for canonical mapper from parsed lines only (no raw split)
        statement_lines = []
        for _stype, chunks in parsed_by_type.items():
            for chunk in chunks:
                for row in chunk["rows"]:
                    statement_lines.append({
                        "statement_type": _stype,
                        "section_path": row.get("section_path") or [],
                        "raw_label": row["raw_label"],
                    })
        if statement_lines:
            map_result = llm_canonical_mapper(statement_lines, dv_id)
            if map_result:
                from app.services.canonical_keys import apply_mapping_gate
                mappings_list = [m.model_dump() for m in map_result.mappings]
                gated = apply_mapping_gate(mappings_list)
                payload = {"mappings": gated}
                _inject_evidence_dv_id(payload, dv_id)
                db.add(PresentationContext(
                    document_version_id=version.id,
                    scope="DOC",
                    scope_key="canonical_mappings",
                    evidence_json=payload,
                ))
                tasks_done += 1

                # Persist Statement + StatementLine from same parsed data (one path for all types)
                for stype_key, chunks in parsed_by_type.items():
                    if not chunks:
                        continue
                    period_labels = chunks[0]["period_labels"]
                    if not period_labels:
                        period_labels = ["current", "prior"]
                    soce_columns = chunks[0].get("soce_columns")
                    soce_header_labels = chunks[0].get("soce_header_labels")
                    if stype_key == "SoCE" and soce_columns:
                        periods_json = [
                            {"label": lbl, "columns": list(soce_columns), "header_labels": soce_header_labels or []}
                            for lbl in period_labels
                        ]
                    else:
                        periods_json = [{"label": lbl} for lbl in period_labels]
                    stmt = Statement(
                        document_version_id=version.id,
                        statement_type=stype_key,
                        entity_scope="GROUP",
                        periods_json=periods_json,
                    )
                    db.add(stmt)
                    db.flush()
                    line_no = 1
                    for chunk in chunks:
                        page = chunk.get("page")
                        ev = {}
                        if page is not None:
                            ev["page"] = page
                            ev["pages"] = [page]
                        for row in chunk["rows"]:
                            ev_row = dict(ev)
                            if row.get("raw_value_strings"):
                                ev_row["raw_value_strings"] = row["raw_value_strings"]
                            if row.get("row_role"):
                                ev_row["row_role"] = row["row_role"]
                            sl = StatementLine(
                                statement_id=stmt.id,
                                line_no=line_no,
                                raw_label=row["raw_label"],
                                section_path=row.get("section_path"),
                                note_refs_json=[row["note_ref"]] if row.get("note_ref") else [],
                                values_json=row["values_json"],
                                evidence_json=ev_row,
                            )
                            db.add(sl)
                            line_no += 1

        # D) Notes: index + chunk + manifest (on-demand retrieval pattern)
        index_entries = extract_notes_index_from_pages(locator_pages)
        if not index_entries:
            index_entries = infer_index_from_packets(note_packets)
        for idx_entry in index_entries:
            ni = NotesIndex(
                document_version_id=version.id,
                note_number=idx_entry.note_number,
                title=idx_entry.title,
                start_page=idx_entry.start_page,
                end_page=idx_entry.end_page,
                confidence=idx_entry.confidence,
            )
            db.add(ni)

        from app.services.notes_chunker import chunk_note_text
        from app.services.notes_manifest_builder import build_notes_manifest
        from app.services.note_table_extractor import extract_tables_from_note_text
        from app.services.notes_embedding import get_embeddings

        chunk_rows: list[tuple[NoteChunk, str]] = []  # (nc, text_for_embedding)

        for pkt in note_packets:
            packet_pages = pkt.get("pages", [])
            packet_text = "\n\n".join(pg.get("text", "") for pg in packet_pages)[:_EXTRACTION_TEXT_LIMIT]
            if not packet_text.strip():
                continue
            first_page = packet_pages[0].get("page", 0) if packet_pages else 0
            last_page = packet_pages[-1].get("page", first_page) if packet_pages else first_page
            packet_type = pkt.get("packet_type", "OTHER")
            note_nums = pkt.get("note_numbers", [])
            note_no = str(note_nums[0]) if note_nums else "0"
            title = packet_type.replace("_", " ").title()

            chunks = chunk_note_text(
                full_text=packet_text,
                scope="GROUP",
                note_number=note_no,
                title=title,
                page_start=first_page,
                page_end=last_page,
            )
            for c in chunks:
                tables = extract_tables_from_note_text(c.text, first_page)
                tables_json = tables if tables else []
                nc = NoteChunk(
                    document_version_id=version.id,
                    scope="GROUP",
                    note_id=c.note_id,
                    chunk_id=c.chunk_id,
                    title=c.title,
                    page_start=c.page_start,
                    page_end=c.page_end,
                    text=c.text,
                    tables_json=tables_json,
                    tokens_approx=len(c.text) // 4,
                    keywords_json=c.keywords,
                )
                db.add(nc)
                db.flush()
                chunk_rows.append((nc, (c.title or "") + "\n" + c.text))

        # Generate embeddings in batch (requires OPENAI_API_KEY, pgvector)
        if chunk_rows:
            texts = [t for _, t in chunk_rows]
            try:
                embeddings = get_embeddings(texts)
                for (nc, _), emb in zip(chunk_rows, embeddings):
                    if emb and len(emb) == 1536:
                        setattr(nc, "embedding", emb)
            except Exception as e:
                log.warning("Note chunk embeddings skipped: %s", e)

        if note_packets:
            period_end = scale_info.get("period_end") or None
            build_notes_manifest(db, version.id, scope="GROUP", period_end=period_end)

        # E) Structured notes extraction using notes_store (new geometry-based approach)
        # This extracts full note content with subsections for LLM retrieval
        try:
            from app.services.notes_store import extract_notes_structured, notes_to_json
            from app.services.storage import upload_json_to_storage
            
            # Download PDF if not already available
            if 'pdf_bytes' not in dir() or pdf_bytes is None:
                pdf_bytes = download_file_from_url(doc.storage_url)
            
            # Extract structured notes
            structured_notes = extract_notes_structured(pdf_bytes, scope="GROUP")
            if structured_notes:
                log.info("Extracted %d structured notes for document %s", len(structured_notes), document_version_id)
                
                # Save notes JSON to storage
                notes_json = notes_to_json(structured_notes)
                storage_key = f"notes/{doc.tenant_id}/{version.id}/notes_structured.json"
                try:
                    upload_json_to_storage(storage_key, notes_json)
                    log.info("Uploaded structured notes JSON to: %s", storage_key)
                except Exception as e:
                    log.warning("Failed to upload notes JSON to S3: %s", e)
                
                # Also update NotesIndex with better data from structured extraction
                for note_id, note_section in structured_notes.items():
                    # Check if we already have this note in the index
                    existing = db.query(NotesIndex).filter(
                        NotesIndex.document_version_id == version.id,
                        NotesIndex.note_number == note_id,
                    ).first()
                    
                    if existing:
                        # Update with better data
                        existing.title = note_section.title
                        existing.start_page = min(note_section.pages) if note_section.pages else existing.start_page
                        existing.end_page = max(note_section.pages) if note_section.pages else existing.end_page
                    else:
                        # Create new index entry
                        ni = NotesIndex(
                            document_version_id=version.id,
                            note_number=note_id,
                            title=note_section.title,
                            start_page=min(note_section.pages) if note_section.pages else 0,
                            end_page=max(note_section.pages) if note_section.pages else 0,
                            confidence=0.95,
                        )
                        db.add(ni)
        except Exception as e:
            log.warning("Structured notes extraction failed: %s", e)

        # Commit now to persist and release connection (avoids SSL timeout during long LLM runs)
        db.commit()

        # F) Statement validation gates (SFP equation, CF reconciliation, sign sanity)
        from app.services.statement_validation import run_statement_validation
        stmt_for_validation = []
        for stype_key, chunks in parsed_by_type.items():
            if not chunks:
                continue
            pl = chunks[0].get("period_labels") or ["current", "prior"]
            cols = chunks[0].get("columns_normalized") or []
            all_lines = []
            for c in chunks:
                for row in c.get("rows", []):
                    all_lines.append({
                        "raw_label": row.get("raw_label", ""),
                        "values_json": row.get("values_json", {}),
                        "raw_value_strings": row.get("raw_value_strings", {}),
                        "row_role": row.get("row_role", "line_item"),
                    })
            stmt_for_validation.append({
                "statement_type": stype_key,
                "period_labels": pl,
                "periods": [{"label": lbl} for lbl in pl],
                "columns_normalized": cols,
                "lines": all_lines,
            })
        ctx_canon = db.query(PresentationContext).filter(
            PresentationContext.document_version_id == version.id,
            PresentationContext.scope == "DOC",
            PresentationContext.scope_key == "canonical_mappings",
        ).first()
        validation_result = run_statement_validation(
            stmt_for_validation,
            canonical_mappings=ctx_canon.evidence_json if ctx_canon else None,
        )
        db.add(PresentationContext(
            document_version_id=version.id,
            scope="DOC",
            scope_key="statement_validation",
            evidence_json=validation_result,
        ))

        # G) Reconciliation checks: SOFP vs Note (borrowings, lease liabilities)
        from sqlalchemy.orm import selectinload

        stmt_rows = db.query(Statement).filter(
            Statement.document_version_id == version.id
        ).options(selectinload(Statement.lines)).all()
        ctx_canon = db.query(PresentationContext).filter(
            PresentationContext.document_version_id == version.id,
            PresentationContext.scope == "DOC",
            PresentationContext.scope_key == "canonical_mappings",
        ).first()
        canonical_mappings = ctx_canon.evidence_json if ctx_canon else None
        ne_rows = db.query(NoteExtraction).filter(
            NoteExtraction.document_version_id == version.id
        ).all()
        scale_factor = scale_info.get("scale_factor")
        reconciliation_result = run_reconciliation(
            statements=list(stmt_rows),
            canonical_mappings=canonical_mappings,
            note_extractions=list(ne_rows),
            scale_factor=scale_factor,
            currency=scale_info.get("currency"),
            scale=scale_info.get("scale"),
        )
        db.add(PresentationContext(
            document_version_id=version.id,
            scope="DOC",
            scope_key="reconciliation_checks",
            evidence_json=reconciliation_result,
        ))

        # E) Risk snippets on focused note text (from packets)
        # DISABLED: Re-enable with notes when statements are stable.
        # focused_full_text = "\n\n".join(
        #     pg.get("text", "") for pkt in note_packets for pg in pkt.get("pages", [])
        # )[:25000]
        # if not focused_full_text.strip():
        #     focused_full_text = "\n\n".join(p.get("text", "") for p in pages)[:_EXTRACTION_TEXT_LIMIT]
        # risk_result = llm_risk_snippets(focused_full_text, dv_id)
        # if risk_result and risk_result.risk_snippets:
        #     payload = risk_result.model_dump()
        #     _inject_evidence_dv_id(payload, dv_id)
        #     db.add(PresentationContext(
        #         document_version_id=version.id,
        #         scope="DOC",
        #         scope_key="risk_snippets",
        #         evidence_json=payload,
        #     ))
        #     tasks_done += 1

        version.status = "MAPPED"
        db.commit()
        celery_app.send_task("app.worker.tasks.run_mapping", args=[dv_id])

        return {
            "document_version_id": document_version_id,
            "status": version.status,
            "llm_tasks": tasks_done,
        }
    except Exception:
        if db:
            try:
                db.rollback()
                v = db.get(DocumentVersion, UUID(document_version_id))
                if v:
                    v.status = "FAILED"
                    db.commit()
            except Exception:
                pass
        raise
    finally:
        db.close()


@celery_app.task(name="app.worker.tasks.run_mapping")
def run_mapping(document_version_id: str):
    """Canonical mapping (LLM + cache). Stub."""
    db = get_sync_session()
    try:
        version = db.get(DocumentVersion, UUID(document_version_id))
        if not version:
            return {"error": "DocumentVersion not found"}
        version.status = "MAPPED"
        db.commit()
        return {"document_version_id": document_version_id, "status": "MAPPED"}
    finally:
        db.close()


@celery_app.task(name="app.worker.tasks.run_validation")
def run_validation(document_version_id: str):
    """Validation job. Stub."""
    return {"document_version_id": document_version_id, "status": "PASS"}


@celery_app.task(name="app.worker.tasks.run_financial_engine")
def run_financial_engine(credit_review_version_id: str):
    """Compute metrics from normalized facts and persist MetricFact rows."""
    db = get_sync_session()
    from datetime import date
    from app.services.financial_engine import run_engine

    try:
        version = db.get(CreditReviewVersion, UUID(credit_review_version_id))
        if not version:
            return {"error": "CreditReviewVersion not found"}

        review = db.get(CreditReview, version.credit_review_id)
        if not review:
            return {"error": "CreditReview not found"}

        engagement = db.get(Engagement, review.engagement_id)
        if not engagement:
            return {"error": "Engagement not found"}

        # Load normalized facts for this company (all periods)
        facts_q = db.query(NormalizedFact).filter(NormalizedFact.company_id == engagement.company_id)
        facts_rows = facts_q.all()
        if not facts_rows:
            return {
                "credit_review_version_id": credit_review_version_id,
                "metrics": {},
                "message": "No normalized_facts found; financial metrics not computed",
            }

        fact_map: dict[tuple[str, date], float] = {}
        periods_set: set[date] = set()
        for nf in facts_rows:
            fact_map[(nf.canonical_key, nf.period_end)] = nf.value_base
            periods_set.add(nf.period_end)

        periods = sorted(periods_set)
        if not periods:
            return {
                "credit_review_version_id": credit_review_version_id,
                "metrics": {},
                "message": "No periods found in normalized_facts",
            }

        metrics = run_engine(fact_map, periods)

        # Clear existing MetricFact for this version to keep it idempotent
        db.query(MetricFact).filter(MetricFact.credit_review_version_id == version.id).delete()

        for metric_key, values_by_period in metrics.items():
            for period_iso, value in values_by_period.items():
                try:
                    pe = date.fromisoformat(period_iso)
                except Exception:
                    continue
                mf = MetricFact(
                    credit_review_version_id=version.id,
                    metric_key=metric_key,
                    value=value,
                    period_end=pe,
                    calc_trace_json={},
                )
                db.add(mf)

        db.commit()
        return {
            "credit_review_version_id": credit_review_version_id,
            "metrics_keys": list(metrics.keys()),
        }
    finally:
        db.close()


@celery_app.task(name="app.worker.tasks.run_rating")
def run_rating(credit_review_version_id: str):
    """Run rating engine based on MetricFact and store RatingResult; update review status."""
    db = get_sync_session()
    from datetime import date
    from sqlalchemy import func
    from app.services.rating_engine import run_rating as run_rating_engine

    try:
        version = db.get(CreditReviewVersion, UUID(credit_review_version_id))
        if not version:
            return {"error": "CreditReviewVersion not found"}

        review = db.get(CreditReview, version.credit_review_id)
        if not review:
            return {"error": "CreditReview not found"}

        engagement = db.get(Engagement, review.engagement_id)
        if not engagement:
            return {"error": "Engagement not found"}

        # Determine latest period_end for this version's MetricFacts
        latest_period = (
            db.query(func.max(MetricFact.period_end))
            .filter(MetricFact.credit_review_version_id == version.id)
            .scalar()
        )
        if not latest_period:
            # No metrics yet; keep review as IN_REVIEW but don't error
            return {
                "credit_review_version_id": credit_review_version_id,
                "message": "No MetricFact rows found; rating not computed",
            }

        m_rows = (
            db.query(MetricFact)
            .filter(
                MetricFact.credit_review_version_id == version.id,
                MetricFact.period_end == latest_period,
            )
            .all()
        )
        metrics: dict[str, float] = {m.metric_key: m.value for m in m_rows}

        # Ensure there is a RatingModel for this tenant
        from app.models.tenancy import Tenant  # only for type context; not used directly

        model = (
            db.query(RatingModel)
            .filter(RatingModel.tenant_id == engagement.company.tenant_id)  # type: ignore[attr-defined]
            .first()
        )
        if not model:
            # Create a default model entry tied to the tenant
            model = RatingModel(
                tenant_id=engagement.company.tenant_id,  # type: ignore[attr-defined]
                name="Default rating model",
                version="1.0",
                config_json={},
            )
            db.add(model)
            db.flush()

        result = run_rating_engine(metrics)

        # Clear existing RatingResult for this version to keep idempotent
        db.query(RatingResult).filter(RatingResult.credit_review_version_id == version.id).delete()

        rr = RatingResult(
            credit_review_version_id=version.id,
            model_id=model.id,
            rating_grade=result.get("rating_grade"),
            pd_band=result.get("pd_band"),
            score_breakdown_json=result.get("score_breakdown"),
            overrides_json={},
            rationale_json=result.get("rationale"),
        )
        db.add(rr)

        # Mark review as completed/approved for now
        review.status = ReviewStatus.APPROVED.value

        db.commit()

        return {
            "credit_review_version_id": credit_review_version_id,
            "rating_grade": rr.rating_grade,
            "pd_band": rr.pd_band,
        }
    finally:
        db.close()


@celery_app.task(name="app.worker.tasks.generate_pack")
def generate_pack(credit_review_version_id: str, formats: list):
    """Generate Word/PDF/Excel/PPT pack. Stub."""
    return {"credit_review_version_id": credit_review_version_id, "formats": formats}
