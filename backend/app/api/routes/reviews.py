from uuid import UUID
from datetime import date
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel

from app.db.session import get_db
from app.api.deps import get_current_user
from app.models.tenancy import User
from app.models.company import Company, Engagement, CreditReview, CreditReviewVersion

router = APIRouter(prefix="/reviews", tags=["reviews"])


class CreateEngagementRequest(BaseModel):
    company_id: UUID
    type: str  # ANNUAL_REVIEW, NEW_FACILITY, INCREASE, MONITORING
    name: str | None = None


class CreateCreditReviewRequest(BaseModel):
    engagement_id: UUID
    review_period_end: date | None = None
    base_currency: str = "ZAR"


class CreditReviewVersionResponse(BaseModel):
    id: str
    credit_review_id: str
    version_no: str
    locked_at: str | None
    created_at: str | None

    class Config:
        from_attributes = True


class CreditReviewDetailResponse(BaseModel):
    id: str
    engagement_id: str
    company_id: str
    review_period_end: str | None
    base_currency: str
    status: str
    # Optional high-level pipeline status for UI polling (e.g. ANALYSIS_PENDING/RUNNING/DONE)
    analysis_status: str | None = None
    # Optional summary from engines
    rating_grade: str | None = None
    pd_band: float | None = None
    key_metrics: dict[str, float] | None = None

    class Config:
        from_attributes = True


class CreditReviewRunResponse(BaseModel):
    review_id: str
    version_id: str
    status: str
    message: str | None = None


class EngagementDetailResponse(BaseModel):
    id: str
    company_id: str
    name: str | None
    type: str
    status: str
    created_at: str | None

    class Config:
        from_attributes = True


@router.post("/engagements")
async def create_engagement(
    data: CreateEngagementRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Company).where(Company.id == data.company_id, Company.tenant_id == user.tenant_id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Company not found")
    engagement = Engagement(
        tenant_id=user.tenant_id,
        company_id=data.company_id,
        type=data.type,
        name=data.name,
    )
    db.add(engagement)
    await db.flush()
    return {
        "id": str(engagement.id),
        "type": engagement.type,
        "name": engagement.name,
        "company_id": str(engagement.company_id),
    }


@router.get("/engagements")
async def list_engagements(
    company_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List engagements for the current tenant (optionally filtered by company)."""
    q = select(Engagement).where(Engagement.tenant_id == user.tenant_id)
    if company_id:
        q = q.where(Engagement.company_id == company_id)
    result = await db.execute(q)
    engagements = result.scalars().all()
    return [
        {
            "id": str(e.id),
            "company_id": str(e.company_id),
            "name": e.name,
            "type": e.type,
            "status": e.status,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in engagements
    ]


@router.post("/credit-reviews")
async def create_credit_review(
    data: CreateCreditReviewRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Engagement).where(
            Engagement.id == data.engagement_id,
            Engagement.tenant_id == user.tenant_id,
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Engagement not found")
    review = CreditReview(
        engagement_id=data.engagement_id,
        review_period_end=data.review_period_end,
        base_currency=data.base_currency,
    )
    db.add(review)
    await db.flush()
    version = CreditReviewVersion(credit_review_id=review.id, version_no="1")
    db.add(version)
    await db.flush()
    return {
        "id": str(review.id),
        "engagement_id": str(review.engagement_id),
        "review_period_end": review.review_period_end.isoformat() if review.review_period_end else None,
        "base_currency": review.base_currency,
        "status": review.status,
        "version_id": str(version.id),
        "version_no": version.version_no,
    }


@router.post("/credit-reviews/{review_id}/run", response_model=CreditReviewRunResponse)
async def run_credit_review_pipeline(
    review_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Kick off the main credit review pipeline for the latest version of a review.

    This wires the button the user presses to Celery by:
    - validating tenant access
    - locating the latest CreditReviewVersion
    - enqueueing deterministic engines (financials, rating, pack generation)
    """
    from sqlalchemy import desc
    from app.worker.tasks import run_full_credit_analysis

    result = await db.execute(
        select(CreditReview, Engagement)
        .join(Engagement, Engagement.id == CreditReview.engagement_id)
        .where(
            CreditReview.id == review_id,
            Engagement.tenant_id == user.tenant_id,
        )
    )
    row = result.one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Credit review not found")
    review, engagement = row

    # Latest version for this review (simple order by created_at/ID)
    v_result = await db.execute(
        select(CreditReviewVersion)
        .where(CreditReviewVersion.credit_review_id == review.id)
        .order_by(desc(CreditReviewVersion.created_at))
    )
    version = v_result.scalars().first()
    if not version:
        raise HTTPException(status_code=400, detail="No versions found for review")

    # Update high-level status so UI can reflect work in progress
    review.status = "IN_REVIEW"
    await db.flush()

    version_id_str = str(version.id)
    run_full_credit_analysis.delay(version_id_str, ["DOCX", "XLSX", "PPTX"])

    return CreditReviewRunResponse(
        review_id=str(review.id),
        version_id=version_id_str,
        status=review.status,
        message="Credit review analysis started",
    )


@router.get("/credit-reviews/{review_id}", response_model=CreditReviewDetailResponse)
async def get_credit_review(
    review_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(CreditReview, Engagement)
        .join(Engagement, Engagement.id == CreditReview.engagement_id)
        .where(
            CreditReview.id == review_id,
            Engagement.tenant_id == user.tenant_id,
        )
    )
    row = result.one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Credit review not found")
    review, engagement = row

    # Pull latest version, rating result and key metrics (if engines have run)
    from sqlalchemy import desc, func
    from app.models.metrics import MetricFact, RatingResult

    v_result = await db.execute(
        select(CreditReviewVersion)
        .where(CreditReviewVersion.credit_review_id == review.id)
        .order_by(desc(CreditReviewVersion.created_at))
    )
    version = v_result.scalars().first()

    rating_grade: str | None = None
    pd_band: float | None = None
    key_metrics: dict[str, float] | None = None

    if version:
        rr_result = await db.execute(
            select(RatingResult)
            .where(RatingResult.credit_review_version_id == version.id)
            .order_by(desc(RatingResult.created_at))
        )
        rr = rr_result.scalars().first()
        if rr:
            rating_grade = rr.rating_grade
            pd_band = rr.pd_band

        # Latest period's core metrics
        latest_period_result = await db.execute(
            select(func.max(MetricFact.period_end)).where(
                MetricFact.credit_review_version_id == version.id
            )
        )
        latest_period = latest_period_result.scalar_one_or_none()
        if latest_period:
            metrics_result = await db.execute(
                select(MetricFact).where(
                    MetricFact.credit_review_version_id == version.id,
                    MetricFact.period_end == latest_period,
                )
            )
            rows = metrics_result.scalars().all()
            if rows:
                key_metrics = {m.metric_key: m.value for m in rows}

    return CreditReviewDetailResponse(
        id=str(review.id),
        engagement_id=str(review.engagement_id),
        company_id=str(engagement.company_id),
        review_period_end=review.review_period_end.isoformat() if review.review_period_end else None,
        base_currency=review.base_currency,
        status=review.status,
        analysis_status=review.status,
        rating_grade=rating_grade,
        pd_band=pd_band,
        key_metrics=key_metrics,
    )


@router.get("/engagements/{engagement_id}", response_model=EngagementDetailResponse)
async def get_engagement(
    engagement_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Engagement).where(
            Engagement.id == engagement_id,
            Engagement.tenant_id == user.tenant_id,
        )
    )
    eng = result.scalar_one_or_none()
    if not eng:
        raise HTTPException(status_code=404, detail="Engagement not found")
    return EngagementDetailResponse(
        id=str(eng.id),
        company_id=str(eng.company_id),
        name=eng.name,
        type=eng.type,
        status=eng.status,
        created_at=eng.created_at.isoformat() if eng.created_at else None,
    )


@router.get("/credit-reviews/{review_id}/versions", response_model=list[CreditReviewVersionResponse])
async def list_credit_review_versions(
    review_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(CreditReviewVersion)
        .join(CreditReview, CreditReview.id == CreditReviewVersion.credit_review_id)
        .join(Engagement, Engagement.id == CreditReview.engagement_id)
        .where(
            CreditReview.id == review_id,
            Engagement.tenant_id == user.tenant_id,
        )
    )
    versions = result.scalars().all()
    return [
        CreditReviewVersionResponse(
            id=str(v.id),
            credit_review_id=str(v.credit_review_id),
            version_no=v.version_no,
            locked_at=v.locked_at.isoformat() if v.locked_at else None,
            created_at=v.created_at.isoformat() if v.created_at else None,
        )
        for v in versions
    ]


@router.post("/credit-reviews/{review_id}/lock")
async def lock_credit_review(
    review_id: UUID,
    reason: str = "",
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(CreditReview)
        .join(Engagement, Engagement.id == CreditReview.engagement_id)
        .where(
            CreditReview.id == review_id,
            Engagement.tenant_id == user.tenant_id,
        )
    )
    review = result.scalar_one_or_none()
    if not review:
        raise HTTPException(status_code=404, detail="Credit review not found")
    review.status = "LOCKED"
    # In full impl: set locked_at on latest version
    await db.flush()
    return {"message": "Review locked", "review_id": str(review_id)}
