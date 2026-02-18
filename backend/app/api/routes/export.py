from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.session import get_db
from app.api.deps import get_current_user
from app.models.tenancy import User
from app.models.company import Company, CreditReview, CreditReviewVersion
from app.services.report_generator import build_memo_docx, MEMO_SECTIONS

router = APIRouter(prefix="/export", tags=["export"])


@router.get("/credit-review/{version_id}/memo")
async def export_credit_memo(
    version_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from app.models.company import Engagement
    result = await db.execute(
        select(CreditReviewVersion, CreditReview, Engagement)
        .join(CreditReview, CreditReview.id == CreditReviewVersion.credit_review_id)
        .join(Engagement, Engagement.id == CreditReview.engagement_id)
        .where(
            CreditReviewVersion.id == version_id,
            Engagement.tenant_id == user.tenant_id,
        )
    )
    row = result.one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Version not found")
    version, review, eng = row
    co_result = await db.execute(select(Company).where(Company.id == eng.company_id))
    company = co_result.scalar_one_or_none()
    company_name = company.name if company else "Unknown Company"
    section_texts = {s: f"(Section: {s})" for s in MEMO_SECTIONS}
    buf = build_memo_docx(
        company_name=company_name,
        review_period_end=review.review_period_end,
        version_id=str(version_id),
        section_texts=section_texts,
        recommendation="Maintain",
    )
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f"attachment; filename=credit-memo-{version_id}.docx"},
    )
