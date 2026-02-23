"""
Full end-to-end test for annual credit analysis pipeline.

Runs: Upload PDF -> Ingest -> Extraction -> Excel + Notes output.
Uses the local shp-afs-2025.pdf and requires:
  - Database (alembic upgrade head, python -m scripts.seed)
  - Redis (for Celery)
  - S3/MinIO storage
  - Redis (for Celery app; tasks run via .apply() - no worker needed)

Usage:
    cd backend
    python -m scripts.run_full_pipeline_test
    python -m scripts.run_full_pipeline_test path/to/other.pdf
"""
import asyncio
import hashlib
import sys
from pathlib import Path
from uuid import UUID

# Add backend to path
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

# Set working directory for .env loading
import os
os.chdir(backend_dir.parent)


async def ensure_seed(db):
    """Ensure tenant, user, company exist."""
    from sqlalchemy import select
    from app.models.tenancy import Tenant, User
    from app.models.company import Company

    result = await db.execute(select(Tenant).limit(1))
    tenant = result.scalar_one_or_none()
    if not tenant:
        print("Running seed...")
        from scripts.seed import seed
        await seed()
        await db.commit()
        result = await db.execute(select(Tenant).limit(1))
        tenant = result.scalar_one_or_none()
        if not tenant:
            raise RuntimeError("Seed failed to create tenant.")

    result = await db.execute(select(Company).where(Company.tenant_id == tenant.id).limit(1))
    company = result.scalar_one_or_none()
    if not company:
        raise RuntimeError("No company found. Run: python -m scripts.seed")
    return tenant, company


async def main():
    pdf_path = backend_dir.parent / "shp-afs-2025.pdf"
    if len(sys.argv) > 1:
        pdf_path = Path(sys.argv[1])
    if not pdf_path.exists():
        print(f"ERROR: PDF not found: {pdf_path}")
        sys.exit(1)

    print("=" * 70)
    print("FULL ANNUAL CREDIT ANALYSIS PIPELINE TEST")
    print("=" * 70)
    print(f"\nPDF: {pdf_path.name}")
    print(f"Size: {pdf_path.stat().st_size / 1024 / 1024:.2f} MB")

    # 1. Ensure DB seeded and get tenant/company
    from app.db.session import async_session_maker

    async with async_session_maker() as db:
        tenant, company = await ensure_seed(db)
        print(f"\nTenant: {tenant.name}")
        print(f"Company: {company.name} ({company.id})")

        # 2. Get or create user for upload
        from sqlalchemy import select
        from app.models.tenancy import User

        result = await db.execute(select(User).where(User.tenant_id == tenant.id).limit(1))
        user = result.scalar_one_or_none()
        if not user:
            raise RuntimeError("No user found. Run: python -m scripts.seed")

        # 3. Create Engagement and CreditReview
        from app.models.company import Engagement, CreditReview, CreditReviewVersion
        from datetime import date

        engagement = Engagement(
            tenant_id=tenant.id,
            company_id=company.id,
            type="ANNUAL_REVIEW",
            name=f"Test Review {pdf_path.stem}",
        )
        db.add(engagement)
        await db.flush()

        review = CreditReview(
            engagement_id=engagement.id,
            review_period_end=date(2025, 6, 29),
            base_currency="ZAR",
        )
        db.add(review)
        await db.flush()

        cr_version = CreditReviewVersion(
            credit_review_id=review.id,
            version_no="1",
        )
        db.add(cr_version)
        await db.flush()
        print(f"\nEngagement: {engagement.id}")
        print(f"CreditReview: {review.id}")
        print(f"CreditReviewVersion: {cr_version.id}")

        # 4. Upload PDF to storage and create Document + DocumentVersion
        from app.models.document import Document, DocumentVersion
        from app.services.storage import upload_file, generate_doc_key

        pdf_bytes = pdf_path.read_bytes()
        sha256 = hashlib.sha256(pdf_bytes).hexdigest()
        filename = pdf_path.name

        doc = Document(
            tenant_id=tenant.id,
            company_id=company.id,
            engagement_id=engagement.id,
            doc_type="AFS",
            original_filename=filename,
            uploaded_by=user.id,
        )
        db.add(doc)
        await db.flush()

        key = generate_doc_key(str(tenant.id), str(company.id), str(doc.id), filename)
        import io
        url = upload_file(key, io.BytesIO(pdf_bytes), content_type="application/pdf")
        doc.storage_url = url
        await db.flush()

        version = DocumentVersion(
            document_id=doc.id,
            sha256=sha256,
            status="PENDING",
        )
        db.add(version)
        await db.flush()

        print(f"\nDocument: {doc.id}")
        print(f"DocumentVersion: {version.id}")
        print(f"Storage URL: {url[:80]}...")
        await db.commit()

        version_id_str = str(version.id)
        cr_version_id_str = str(cr_version.id)

    # 5. Run ingest + extraction (synchronously via Celery .apply() - no worker needed)
    print("\n" + "-" * 70)
    print("Running ingest pipeline...")
    print("-" * 70)

    from app.worker.tasks import run_ingest_pipeline, run_extraction

    result = run_ingest_pipeline.apply(args=[version_id_str])
    if not result.successful():
        print(f"Ingest FAILED: {result.result}")
        sys.exit(1)
    print(f"Ingest result: {result.result}")

    print("\nRunning extraction...")
    result = run_extraction.apply(args=[version_id_str])
    if not result.successful():
        print(f"Extraction FAILED: {result.result}")
        sys.exit(1)
    print(f"Extraction result: {result.result}")

    # 5b. Run full credit analysis (Phase 1-3: mapping, financial engine, rating, pack)
    from app.worker.tasks import run_full_credit_analysis
    print("\nRunning full credit analysis (mapping -> financial -> rating -> pack)...")
    result = run_full_credit_analysis.apply(args=[cr_version_id_str, ["DOCX", "XLSX", "PPTX"]])
    if not result.successful():
        print(f"Full analysis FAILED: {result.result}")
    else:
        print(f"Full analysis result: {result.result}")

    # 6. Download and save all results to test_results
    print("\n" + "=" * 70)
    print("RESULTS")
    print("=" * 70)

    from app.config import get_settings
    from app.services.storage import get_s3_client, download_file_from_url

    output_dir = backend_dir.parent / "test_results" / "pipeline_output"
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"\nSaving all results to: {output_dir}")

    # 6a. Extracted files from S3
    bucket = get_settings().object_storage_bucket
    prefix = f"extracted/{tenant.id}/{version_id_str}/"
    try:
        s3 = get_s3_client()
        resp = s3.list_objects_v2(Bucket=bucket, Prefix=prefix)
        objects = resp.get("Contents", [])
        for obj in objects:
            key = obj["Key"]
            name = key.split("/")[-1]
            s3_resp = s3.get_object(Bucket=bucket, Key=key)
            out_path = output_dir / name
            out_path.write_bytes(s3_resp["Body"].read())
            print(f"  - {name} -> {out_path}")
    except Exception as e:
        print(f"  Could not download extracted files: {e}")

    # 6b. Generated packs (DOCX, XLSX, PPTX) from ExportArtifacts
    from app.worker.tasks import get_sync_session
    from app.models.metrics import ExportArtifact
    from sqlalchemy import select

    db_sync = get_sync_session()
    try:
        arts = db_sync.execute(
            select(ExportArtifact).where(
                ExportArtifact.credit_review_version_id == UUID(cr_version_id_str)
            )
        ).scalars().all()
        for art in arts:
            if not art.storage_url:
                continue
            names = {"DOCX": "credit_memo.docx", "XLSX": "financial_model.xlsx", "PPTX": "committee_deck.pptx"}
            fname = names.get(art.type, f"export_{art.type.lower()}")
            try:
                buf = download_file_from_url(art.storage_url)
                out_path = output_dir / fname
                out_path.write_bytes(buf)
                print(f"  - {fname} -> {out_path}")
            except Exception as e:
                print(f"  - {fname}: download failed ({e})")

        # 6c. Save analysis output JSON (trend, liquidity, leverage, stress, risk)
        try:
            from app.models.company import CreditReview, CreditReviewVersion, Engagement
            from app.models.document import Document
            from app.models.mapping import NormalizedFact
            cv = db_sync.get(CreditReviewVersion, UUID(cr_version_id_str))
            if cv:
                review = db_sync.get(CreditReview, cv.credit_review_id)
                if review:
                    eng = db_sync.get(Engagement, review.engagement_id)
                    if eng:
                        facts_by_period = {}
                        for r in db_sync.query(NormalizedFact).filter(NormalizedFact.company_id == eng.company_id).all():
                            pe = r.period_end
                            if pe not in facts_by_period:
                                facts_by_period[pe] = {}
                            facts_by_period[pe][r.canonical_key] = float(r.value_base)
                        facts_dict = {(k, pe): v for pe, vals in facts_by_period.items() for k, v in vals.items()}
                        periods = sorted(facts_by_period.keys(), reverse=True)[:5]
                        notes_json = None
                        for doc in db_sync.query(Document).filter(Document.engagement_id == eng.id).all():
                            for dv in doc.versions:
                                if dv.status != "MAPPED":
                                    continue
                                pdf_name = (doc.original_filename or "document").replace(".pdf", "").replace(".PDF", "")
                                json_key = f"extracted/{eng.tenant_id}/{dv.id}/notes_{pdf_name}.json"
                                try:
                                    import json as _json
                                    notes_raw = download_json_from_storage(json_key)
                                    notes_json = _json.loads(notes_raw) if isinstance(notes_raw, str) else notes_raw
                                    break
                                except Exception:
                                    pass
                            if notes_json:
                                break
                        from app.services.analysis_orchestrator import run_full_analysis
                        analysis = run_full_analysis(facts_dict, periods, notes_json)
                        out_path = output_dir / "analysis_output.json"
                        import json as _json
                        out_path.write_text(_json.dumps(analysis, indent=2, default=str), encoding="utf-8")
                        print(f"  - analysis_output.json -> {out_path}")
        except Exception as e:
            print(f"  - analysis_output.json: skipped ({e})")
    finally:
        db_sync.close()

    print(f"\nAll test results saved to: {output_dir}")
    print("\n" + "=" * 70)
    print("PIPELINE TEST COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
