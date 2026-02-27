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
def run_ingest_pipeline(self, document_version_id: str, skip_extraction_task: bool = False):
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

        if not skip_extraction_task:
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


@celery_app.task(name="app.worker.tasks.run_extraction")
def run_extraction(document_version_id: str):
    """
    Simple extraction pipeline - runs geometry-based extraction and uploads to S3.
    No LLM calls, no complex database persistence.
    
    Uploads to S3:
    - statements_{filename}.xlsx - Excel with all financial statements
    - notes_{filename}.json - Full notes JSON
    - notes_summary_{filename}.txt - Notes summary
    """
    import logging
    from datetime import datetime
    
    log = logging.getLogger(__name__)
    log.info("run_extraction (TEST PIPELINE) starting for document_version_id=%s", document_version_id)

    db = get_sync_session()
    try:
        version = db.get(DocumentVersion, UUID(document_version_id))
        if not version:
            return {"error": "DocumentVersion not found"}
        
        doc = db.get(Document, version.document_id)
        if not doc or not doc.storage_url:
            version.status = "FAILED"
            db.commit()
            return {"error": "Document or storage URL not found"}

        # Download PDF
        pdf_bytes = download_file_from_url(doc.storage_url)
        pdf_name = doc.original_filename or "document"
        if pdf_name.lower().endswith(".pdf"):
            pdf_name = pdf_name[:-4]
        
        log.info("Extracting statements and notes from %s", doc.original_filename)
        
        from app.services.document_extractor import (
            detect_scale_from_pdf,
            extract_all_from_pdf,
        )
        from app.services.notes_store import extract_notes_structured, notes_to_json
        
        # Detect scale
        scale_info = detect_scale_from_pdf(pdf_bytes)
        log.info("Scale detected: %s (%s)", scale_info["scale"], scale_info["scale_label"])
        
        # Extract all statements (canonical extraction path)
        extraction_result = extract_all_from_pdf(pdf_bytes, extract_notes=False)
        log.info("Detected %d statement pages", len(extraction_result.pages_detected))
        
        import pandas as pd
        all_dfs = {}
        
        for key, rows in extraction_result.statements.items():
            statement_type = key.split("_")[0]
            excel_rows = []
            
            # Determine column keys from all rows (for consistent ordering)
            all_value_keys = []
            for row in rows:
                vals = (row.get("values_json") or {}).get("") or {}
                period_labels = row.get("period_labels") or []
                if statement_type == "SOCE":
                    for k in vals.keys():
                        if k not in all_value_keys:
                            all_value_keys.append(k)
                else:
                    for k in (period_labels or list(vals.keys())):
                        if k and k not in all_value_keys:
                            all_value_keys.append(k)
            
            for i, row in enumerate(rows):
                vj = row.get("values_json", {}) or {}
                vals = vj.get("") or {}
                period_labels = row.get("period_labels") or []
                
                row_data = {
                    "page": row.get("page"),
                    "line_no": i + 1,
                    "raw_label": row.get("raw_label", ""),
                    "note": row.get("note"),
                    "section": row.get("section"),
                }
                
                if statement_type == "SOCE":
                    for col_key in all_value_keys:
                        header = col_key.replace("_", " ").title()
                        row_data[header] = vals.get(col_key)
                else:
                    years = all_value_keys or (period_labels if period_labels else list(vals.keys()))
                    for year in years:
                        col_name = f"{year} ({scale_info['scale_label']})" if year else scale_info["scale_label"]
                        row_data[col_name] = vals.get(year)
                
                excel_rows.append(row_data)
            
            if excel_rows:
                base_cols = ["page", "line_no", "raw_label", "note", "section"]
                value_cols = [c for c in excel_rows[0].keys() if c not in base_cols]
                all_dfs[key] = pd.DataFrame(excel_rows)[base_cols + value_cols]
                log.info("Extracted %s: %d rows", key, len(excel_rows))
        
        if not all_dfs and extraction_result.pages_detected:
            log.warning(
                "Statement pages detected (%d) but no rows extracted; geometry extractors may have failed for this layout",
                len(extraction_result.pages_detected),
            )
        
        # Extract notes
        log.info("Extracting notes...")
        notes = extract_notes_structured(pdf_bytes, scope="GROUP")
        log.info("Extracted %d notes", len(notes))
        
        # Build Excel file in memory
        import io as io_module
        from app.services.storage import upload_bytes
        from app.services.excel_formatting import format_statement_sheet, format_summary_sheet
        
        excel_buffer = io_module.BytesIO()
        with pd.ExcelWriter(excel_buffer, engine="openpyxl") as writer:
            # Summary sheet
            summary_data = {
                "Property": ["PDF File", "Scale", "Currency", "Extraction Date", "Document ID"],
                "Value": [
                    doc.original_filename,
                    f"{scale_info['scale']} ({scale_info['scale_label']})",
                    scale_info.get('currency') or 'Not detected',
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    str(version.id),
                ]
            }
            pd.DataFrame(summary_data).to_excel(writer, sheet_name="Summary", index=False)
            format_summary_sheet(writer.sheets["Summary"])
            
            for sheet_name, df in all_dfs.items():
                safe_name = sheet_name[:31]
                df.to_excel(writer, sheet_name=safe_name, index=False)
                statement_type = sheet_name.split("_")[0]
                format_statement_sheet(writer.sheets[safe_name], df, statement_type)
        
        # Upload Excel to S3
        excel_key = f"extracted/{doc.tenant_id}/{version.id}/statements_{pdf_name}.xlsx"
        upload_bytes(excel_key, excel_buffer.getvalue(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        log.info("Uploaded Excel to S3: %s", excel_key)
        
        # Upload notes JSON to S3
        json_content = notes_to_json(notes)
        json_key = f"extracted/{doc.tenant_id}/{version.id}/notes_{pdf_name}.json"
        upload_bytes(json_key, json_content.encode("utf-8"), content_type="application/json")
        log.info("Uploaded notes JSON to S3: %s", json_key)
        
        # Build and upload notes summary
        summary_lines = ["NOTES SUMMARY", "=" * 60, ""]
        for note_id in sorted(notes.keys(), key=lambda x: int(x)):
            note = notes[note_id]
            summary_lines.append(f"Note {note_id}: {note.title}")
            summary_lines.append(f"  Pages: {note.pages}")
            summary_lines.append(f"  Content: {len(note.text)} chars")
            summary_lines.append("")
        summary_text = "\n".join(summary_lines)
        summary_key = f"extracted/{doc.tenant_id}/{version.id}/notes_summary_{pdf_name}.txt"
        upload_bytes(summary_key, summary_text.encode("utf-8"), content_type="text/plain")
        log.info("Uploaded notes summary to S3: %s", summary_key)
        
        # Update status
        version.status = "MAPPED"
        db.commit()
        
        log.info("Extraction complete for %s", document_version_id)
        return {
            "document_version_id": document_version_id,
            "status": "MAPPED",
            "statements": list(all_dfs.keys()),
            "notes_count": len(notes),
            "excel_file": excel_key,
            "json_file": json_key,
        }
        
    except Exception as e:
        log.exception("Extraction failed: %s", e)
        try:
            version = db.get(DocumentVersion, UUID(document_version_id))
            if version:
                version.status = "FAILED"
                db.commit()
        except Exception:
            pass
        raise
    finally:
        db.close()


@celery_app.task(name="app.worker.tasks.run_mapping")
def run_mapping(document_version_id: str):
    """Legacy mapping task for document_version_id. Prefer run_mapping_for_review."""
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


@celery_app.task(name="app.worker.tasks.run_mapping_for_review")
def run_mapping_for_review(credit_review_version_id: str):
    """
    Load extraction from S3 for MAPPED document versions in engagement,
    run mapping pipeline, persist NormalizedFact. Required before financial engine.
    """
    import logging
    from app.services.mapping_pipeline import run_mapping as run_mapping_pipeline
    from app.services.mapping_validator import validate_facts

    log = logging.getLogger(__name__)
    db = get_sync_session()
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

        company_id = str(engagement.company_id)
        tenant_id = str(engagement.tenant_id)

        from app.models.document import Document

        docs = db.query(Document).filter(Document.engagement_id == engagement.id).all()
        if not docs:
            log.warning("No documents in engagement %s", engagement.id)
            return {"credit_review_version_id": credit_review_version_id, "facts_count": 0, "message": "No documents"}

        all_facts = []
        for doc in docs:
            for dv in doc.versions:
                if dv.status != "MAPPED":
                    continue
                pdf_name = (doc.original_filename or "document").replace(".pdf", "").replace(".PDF", "")
                excel_key = f"extracted/{tenant_id}/{dv.id}/statements_{pdf_name}.xlsx"
                try:
                    facts = run_mapping_pipeline(excel_key, company_id)
                    all_facts.extend(facts)
                except Exception as e:
                    log.warning("Mapping failed for %s: %s", excel_key, e)

        if not all_facts:
            return {"credit_review_version_id": credit_review_version_id, "facts_count": 0}

        val = validate_facts(all_facts)
        if not val["passed"]:
            log.warning("Validation failures: %s", val["failures"])

        db.query(NormalizedFact).filter(NormalizedFact.company_id == engagement.company_id).delete()
        for f in all_facts:
            f["company_id"] = engagement.company_id
            nf = NormalizedFact(
                company_id=engagement.company_id,
                period_end=f["period_end"],
                statement_type=f["statement_type"],
                canonical_key=f["canonical_key"],
                value_base=f["value_base"],
                value_original=f.get("value_original"),
                unit_meta_json=f.get("unit_meta_json") or {},
                source_refs_json=f.get("source_refs_json") or [],
            )
            db.add(nf)

        db.commit()
        return {"credit_review_version_id": credit_review_version_id, "facts_count": len(all_facts)}
    except Exception as e:
        log.exception("Mapping failed: %s", e)
        raise
    finally:
        db.close()


@celery_app.task(name="app.worker.tasks.run_validation")
def run_validation(document_version_id: str):
    """Validation job. Stub."""
    return {"document_version_id": document_version_id, "status": "PASS"}


def _facts_rows_to_dict(facts_rows: list) -> tuple[dict, list]:
    """Convert NormalizedFact rows to (facts dict, periods list) for financial engine."""
    facts: dict[tuple[str, "date"], float] = {}
    periods_set: set["date"] = set()
    for row in facts_rows:
        pe = row.period_end
        key = (row.canonical_key, pe)
        facts[key] = float(row.value_base)
        periods_set.add(pe)
    return facts, sorted(periods_set, reverse=True)


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

        facts_q = db.query(NormalizedFact).filter(NormalizedFact.company_id == engagement.company_id)
        facts_rows = facts_q.all()
        if not facts_rows:
            return {"error": "No normalized facts found"}

        facts_dict, periods = _facts_rows_to_dict(facts_rows)
        engine_out = run_engine(facts_dict, periods, return_traces=True)
        engine_results = engine_out[0] if isinstance(engine_out, tuple) else engine_out
        engine_traces = engine_out[1] if isinstance(engine_out, tuple) else {}

        # Delete existing MetricFact for this version
        db.query(MetricFact).filter(MetricFact.credit_review_version_id == version.id).delete()

        count = 0
        for metric_key, period_values in engine_results.items():
            for pe_str, value in (period_values or {}).items():
                pe = date.fromisoformat(pe_str) if isinstance(pe_str, str) else pe_str
                trace = (engine_traces.get(metric_key) or {}).get(pe_str)
                calc_trace = [trace] if trace else []
                db.add(MetricFact(
                    credit_review_version_id=version.id,
                    metric_key=metric_key,
                    period_end=pe,
                    value=float(value),
                    calc_trace_json=calc_trace,
                ))
                count += 1

        db.commit()
        return {"credit_review_version_id": credit_review_version_id, "metrics_computed": count}
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

        latest_period = (
            db.query(func.max(MetricFact.period_end))
            .filter(MetricFact.credit_review_version_id == version.id)
            .scalar()
        )
        if not latest_period:
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

        from app.models.tenancy import Tenant

        tenant_id = engagement.tenant_id  # Use Engagement.tenant_id (company can be None)
        model = (
            db.query(RatingModel)
            .filter(RatingModel.tenant_id == tenant_id)
            .first()
        )
        if not model:
            model = RatingModel(
                tenant_id=tenant_id,
                name="Default rating model",
                version="1.0",
                config_json={},
            )
            db.add(model)
            db.flush()

        result = run_rating_engine(metrics)

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

        review.status = ReviewStatus.APPROVED.value

        db.commit()

        return {
            "credit_review_version_id": credit_review_version_id,
            "rating_grade": rr.rating_grade,
            "pd_band": rr.pd_band,
        }
    finally:
        db.close()


@celery_app.task(name="app.worker.tasks.run_full_credit_analysis")
def run_full_credit_analysis(credit_review_version_id: str, formats: list | None = None):
    """
    Run the full pipeline in sequence: mapping -> financial engine -> rating -> generate_pack.
    Call this from the Run button instead of individual tasks.
    """
    import logging
    log = logging.getLogger(__name__)
    formats = formats or ["DOCX"]
    run_mapping_for_review(credit_review_version_id)
    run_financial_engine(credit_review_version_id)
    run_rating(credit_review_version_id)
    return generate_pack(credit_review_version_id, formats)


@celery_app.task(name="app.worker.tasks.generate_pack")
def generate_pack(credit_review_version_id: str, formats: list | None = None):
    """Generate Word/Excel/PPT pack from NormalizedFact, MetricFact, RatingResult. Upload to S3, create ExportArtifact."""
    import logging
    from datetime import date
    from app.services.report_generator import (
        build_memo_docx,
        build_financial_model_xlsx,
        build_committee_pptx,
        build_memo_pdf,
        build_rating_output_json,
        build_data_room_zip,
        build_covenant_certificate_txt,
        build_cash_flow_stress_xlsx,
        build_risk_dashboard_pdf,
        build_sector_comparison_appendix_txt,
    )
    from app.services.memo_composer import build_all_sections
    from app.services.credit_risk_quant_engine import compute_credit_risk_quantification
    from app.services.storage import upload_bytes
    from app.models.metrics import ExportArtifact

    log = logging.getLogger(__name__)
    formats = formats or ["DOCX"]

    db = get_sync_session()
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

        company = engagement.company
        company_name = (company.name if company else None) or "Company"

        # Build facts_by_period and metric_by_period from NormalizedFact + MetricFact
        facts_rows = db.query(NormalizedFact).filter(NormalizedFact.company_id == engagement.company_id).all()
        facts_by_period: dict[date, dict[str, float]] = {}
        for r in facts_rows:
            pe = r.period_end
            if pe not in facts_by_period:
                facts_by_period[pe] = {}
            facts_by_period[pe][r.canonical_key] = float(r.value_base)

        m_rows = db.query(MetricFact).filter(MetricFact.credit_review_version_id == version.id).all()
        metric_by_period: dict[date, dict[str, float]] = {}
        key_metrics: dict[str, float] = {}
        latest_period = max((m.period_end for m in m_rows if m.period_end), default=None)
        for m in m_rows:
            pe = m.period_end
            if pe:
                if pe not in metric_by_period:
                    metric_by_period[pe] = {}
                metric_by_period[pe][m.metric_key] = float(m.value)
            if pe == latest_period:
                key_metrics[m.metric_key] = float(m.value)

        rr = db.query(RatingResult).filter(RatingResult.credit_review_version_id == version.id).order_by(RatingResult.created_at.desc()).first()
        rating_grade = rr.rating_grade if rr else None
        pd_band = rr.pd_band if rr else None

        # Load notes JSON from S3 for key_risks section (Phase 2)
        notes_json = None
        from app.models.document import Document
        from app.services.storage import download_json_from_storage
        docs = db.query(Document).filter(Document.engagement_id == engagement.id).all()
        for doc in docs:
            for dv in doc.versions:
                if dv.status != "MAPPED":
                    continue
                pdf_name = (doc.original_filename or "document").replace(".pdf", "").replace(".PDF", "")
                json_key = f"extracted/{engagement.tenant_id}/{dv.id}/notes_{pdf_name}.json"
                try:
                    import json as _json
                    notes_raw = download_json_from_storage(json_key)
                    notes_json = _json.loads(notes_raw) if isinstance(notes_raw, str) else notes_raw
                    break
                except Exception:
                    pass
            if notes_json:
                break

        periods = sorted(facts_by_period.keys(), reverse=True)[:5]
        facts_dict = {(k, pe): v for pe, vals in facts_by_period.items() for k, v in vals.items()}
        from app.services.analysis_orchestrator import run_full_analysis
        from app.services.provenance import add_provenance_to_analysis
        from app.services.recommendation_conditions import compute_recommendation

        analysis_output = run_full_analysis(
            facts=facts_dict,
            periods=periods,
            notes_json=notes_json,
            fs_version="",
            mapping_version="",
            company_name=company_name,
            rating_grade_override=rating_grade,
        )
        add_provenance_to_analysis(analysis_output, facts_rows, m_rows)
        cov_block = (analysis_output.get("section_blocks") or {}).get("covenants", {}).get("key_metrics") or {}
        stress_scenarios = (analysis_output.get("section_blocks") or {}).get("stress", {}).get("key_metrics", {}).get("scenarios") or {}
        stress_breaches = sum(1 for s in stress_scenarios.values() if isinstance(s, dict) and (s.get("net_debt_to_ebitda_stressed") or 0) >= 6 or (s.get("interest_cover_stressed") or 10) < 2)
        recommendation, rec_conditions = compute_recommendation(key_metrics, cov_block, stress_breaches)
        credit_risk_quant = compute_credit_risk_quantification(
            facts_by_period=facts_by_period,
            metric_by_period=metric_by_period,
            rating_grade=rating_grade,
            pd_band=pd_band,
            analysis_output=analysis_output,
        )
        analysis_output["credit_risk_quantification"] = credit_risk_quant
        section_texts = build_all_sections(
            company_name=company_name,
            review_period_end=review.review_period_end or (periods[0] if periods else None),
            rating_grade=rating_grade,
            recommendation=recommendation,
            recommendation_conditions=rec_conditions,
            facts_by_period=facts_by_period,
            metric_by_period=metric_by_period,
            key_metrics=key_metrics,
            notes_json=notes_json,
            analysis_output=analysis_output,
        )

        version_id_str = str(version.id)
        tenant_id = str(engagement.tenant_id)
        bucket_prefix = f"exports/{tenant_id}/{version_id_str}"
        # Shared row payloads for workbook + data-room package
        def _pe_key(pe):
            return pe.isoformat() if hasattr(pe, "isoformat") else str(pe)
        normalized_rows = [
            {
                "label": k.replace("_", " ").title(),
                "canonical_key": k,
                "values": {_pe_key(pe): facts_by_period.get(pe, {}).get(k) for pe in periods},
            }
            for k in sorted(set().union(*(f.keys() for f in facts_by_period.values())))
        ]
        metrics_rows = [
            {
                "label": mk.replace("_", " ").title(),
                "metric_key": mk,
                "values": {_pe_key(pe): metric_by_period.get(pe, {}).get(mk) for pe in periods},
            }
            for mk in sorted(set().union(*(m.keys() for m in metric_by_period.values())))
            if mk
        ]

        if "DOCX" in formats:
            buf = build_memo_docx(
                company_name=company_name,
                review_period_end=review.review_period_end,
                version_id=version_id_str,
                section_texts=section_texts,
                rating_grade=rating_grade,
                key_metrics=key_metrics,
                metric_by_period=metric_by_period,
                facts_by_period=facts_by_period,
            )
            docx_key = f"{bucket_prefix}/credit_memo.docx"
            url = upload_bytes(docx_key, buf.read(), content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
            db.add(ExportArtifact(credit_review_version_id=version.id, type="DOCX", storage_url=url))
            log.info("Uploaded DOCX to %s", docx_key)
            # Also generate memo PDF companion for committee sharing
            memo_pdf = build_memo_pdf(
                company_name=company_name,
                review_period_end=review.review_period_end,
                section_texts=section_texts,
                rating_grade=rating_grade,
                recommendation=recommendation,
            )
            memo_pdf_key = f"{bucket_prefix}/credit_memo.pdf"
            memo_pdf_url = upload_bytes(memo_pdf_key, memo_pdf.read(), content_type="application/pdf")
            db.add(ExportArtifact(credit_review_version_id=version.id, type="PDF", storage_url=memo_pdf_url))
            log.info("Uploaded memo PDF to %s", memo_pdf_key)

        if "XLSX" in formats:
            buf = build_financial_model_xlsx(company_name=company_name, period_ends=periods, normalized_rows=normalized_rows, metrics_rows=metrics_rows, version_id=version_id_str, analysis_output=analysis_output)
            xlsx_key = f"{bucket_prefix}/financial_model.xlsx"
            url = upload_bytes(xlsx_key, buf.read(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            db.add(ExportArtifact(credit_review_version_id=version.id, type="XLSX", storage_url=url))
            log.info("Uploaded XLSX to %s", xlsx_key)

        if "PPTX" in formats:
            buf = build_committee_pptx(
                company_name=company_name,
                rating_grade=rating_grade or "N/A",
                recommendation=recommendation,
                key_drivers=list(key_metrics.keys())[:5],
                version_id=version_id_str,
                section_texts=section_texts,
                metric_by_period=metric_by_period,
                facts_by_period=facts_by_period,
                credit_risk_quant=credit_risk_quant,
            )
            pptx_key = f"{bucket_prefix}/committee_deck.pptx"
            url = upload_bytes(pptx_key, buf.read(), content_type="application/vnd.openxmlformats-officedocument.presentationml.presentation")
            db.add(ExportArtifact(credit_review_version_id=version.id, type="PPTX", storage_url=url))
            log.info("Uploaded PPTX to %s", pptx_key)

        # Always emit structured rating output and data-room package (non-negotiable deliverables)
        rating_json_buf = build_rating_output_json(
            rating_grade=rating_grade,
            pd_band=pd_band,
            score_breakdown=rr.score_breakdown_json if rr else {},
            overrides=rr.overrides_json if rr else {},
            rationale=rr.rationale_json if rr else {},
            analysis_output=analysis_output,
            credit_risk_quant=credit_risk_quant,
        )
        rating_json_key = f"{bucket_prefix}/rating_output.json"
        rating_json_bytes = rating_json_buf.read()
        rating_json_url = upload_bytes(rating_json_key, rating_json_bytes, content_type="application/json")
        db.add(ExportArtifact(credit_review_version_id=version.id, type="JSON", storage_url=rating_json_url))
        log.info("Uploaded rating output to %s", rating_json_key)

        import json as _json
        rating_output_payload = _json.loads(rating_json_bytes.decode("utf-8"))

        # Optional but high-value institutional outputs
        cov_buf = build_covenant_certificate_txt(company_name, analysis_output)
        cov_key = f"{bucket_prefix}/covenant_compliance_certificate.txt"
        cov_url = upload_bytes(cov_key, cov_buf.read(), content_type="text/plain")
        db.add(ExportArtifact(credit_review_version_id=version.id, type="TXT", storage_url=cov_url))

        stress_xlsx_buf = build_cash_flow_stress_xlsx(company_name, analysis_output)
        stress_key = f"{bucket_prefix}/cash_flow_stress_test_model.xlsx"
        stress_url = upload_bytes(stress_key, stress_xlsx_buf.read(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        db.add(ExportArtifact(credit_review_version_id=version.id, type="XLSX", storage_url=stress_url))

        risk_pdf_buf = build_risk_dashboard_pdf(company_name, section_texts, rating_grade)
        risk_pdf_key = f"{bucket_prefix}/risk_dashboard.pdf"
        risk_pdf_url = upload_bytes(risk_pdf_key, risk_pdf_buf.read(), content_type="application/pdf")
        db.add(ExportArtifact(credit_review_version_id=version.id, type="PDF", storage_url=risk_pdf_url))

        sector_buf = build_sector_comparison_appendix_txt(company_name, section_texts)
        sector_key = f"{bucket_prefix}/sector_comparison_appendix.txt"
        sector_url = upload_bytes(sector_key, sector_buf.read(), content_type="text/plain")
        db.add(ExportArtifact(credit_review_version_id=version.id, type="TXT", storage_url=sector_url))

        zip_buf = build_data_room_zip(
            company_name=company_name,
            version_id=version_id_str,
            normalized_rows=normalized_rows,
            metrics_rows=metrics_rows,
            section_texts=section_texts,
            analysis_output=analysis_output,
            rating_output=rating_output_payload,
        )
        zip_key = f"{bucket_prefix}/data_room_export.zip"
        zip_url = upload_bytes(zip_key, zip_buf.read(), content_type="application/zip")
        db.add(ExportArtifact(credit_review_version_id=version.id, type="ZIP", storage_url=zip_url))
        log.info("Uploaded data room ZIP to %s", zip_key)

        db.commit()
        return {"credit_review_version_id": credit_review_version_id, "formats": formats}
    except Exception as e:
        log.exception("generate_pack failed: %s", e)
        raise
    finally:
        db.close()
