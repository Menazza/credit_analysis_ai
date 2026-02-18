from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel

from app.db.session import get_db
from app.api.deps import get_current_user
from app.models.tenancy import User
from app.models.company import Company, Engagement, CreditReview
from app.models.tenancy import Portfolio, PortfolioCompany

router = APIRouter(prefix="/companies", tags=["companies"])


class CompanyCreate(BaseModel):
    name: str
    reg_no: str | None = None
    country: str | None = None
    sector: str | None = None
    is_listed: str = "false"
    ticker: str | None = None
    group_structure_json: dict = {}


class CompanyResponse(BaseModel):
    id: UUID
    name: str
    reg_no: str | None
    country: str | None
    sector: str | None
    is_listed: str
    ticker: str | None
    group_structure_json: dict

    class Config:
        from_attributes = True


@router.get("", response_model=list[CompanyResponse])
async def list_companies(
    portfolio_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = select(Company).where(Company.tenant_id == user.tenant_id)
    if portfolio_id:
        sub = (
            select(PortfolioCompany.company_id)
            .join(Portfolio, Portfolio.id == PortfolioCompany.portfolio_id)
            .where(
                PortfolioCompany.portfolio_id == portfolio_id,
                Portfolio.tenant_id == user.tenant_id,
            )
        )
        q = q.where(Company.id.in_(sub))
    result = await db.execute(q)
    companies = result.scalars().all()
    return [CompanyResponse.model_validate(c) for c in companies]


@router.post("", response_model=CompanyResponse)
async def create_company(
    data: CompanyCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    company = Company(
        tenant_id=user.tenant_id,
        name=data.name,
        reg_no=data.reg_no,
        country=data.country,
        sector=data.sector,
        is_listed=data.is_listed,
        ticker=data.ticker,
        group_structure_json=data.group_structure_json or {},
    )
    db.add(company)
    await db.flush()
    return CompanyResponse.model_validate(company)


@router.get("/{company_id}", response_model=CompanyResponse)
async def get_company(
    company_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Company).where(Company.id == company_id, Company.tenant_id == user.tenant_id)
    )
    company = result.scalar_one_or_none()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    return CompanyResponse.model_validate(company)


@router.get("/{company_id}/engagements")
async def list_engagements(
    company_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Engagement).where(
            Engagement.company_id == company_id,
            Engagement.tenant_id == user.tenant_id,
        )
    )
    engagements = result.scalars().all()
    return [
        {
            "id": str(e.id),
            "name": e.name,
            "type": e.type,
            "status": e.status,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in engagements
    ]


@router.get("/{company_id}/credit-reviews")
async def list_credit_reviews(
    company_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(CreditReview)
        .join(Engagement, Engagement.id == CreditReview.engagement_id)
        .where(
            Engagement.company_id == company_id,
            Engagement.tenant_id == user.tenant_id,
        )
    )
    reviews = result.scalars().all()
    return [
        {
            "id": str(r.id),
            "engagement_id": str(r.engagement_id),
            "review_period_end": r.review_period_end.isoformat() if r.review_period_end else None,
            "status": r.status,
            "base_currency": r.base_currency,
        }
        for r in reviews
    ]
