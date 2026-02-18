from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel

from app.db.session import get_db
from app.api.deps import get_current_user
from app.models.tenancy import User, Portfolio, PortfolioCompany
from app.models.company import Company

router = APIRouter(prefix="/portfolios", tags=["portfolios"])


class PortfolioCreate(BaseModel):
    name: str


class PortfolioResponse(BaseModel):
    id: str
    name: str

    class Config:
        from_attributes = True


@router.get("", response_model=list[PortfolioResponse])
async def list_portfolios(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(select(Portfolio).where(Portfolio.tenant_id == user.tenant_id))
    portfolios = result.scalars().all()
    return [PortfolioResponse.model_validate(p) for p in portfolios]


@router.post("", response_model=PortfolioResponse)
async def create_portfolio(
    data: PortfolioCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    portfolio = Portfolio(tenant_id=user.tenant_id, name=data.name)
    db.add(portfolio)
    await db.flush()
    return PortfolioResponse.model_validate(portfolio)


@router.post("/{portfolio_id}/companies/{company_id}")
async def add_company_to_portfolio(
    portfolio_id: UUID,
    company_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Portfolio).where(Portfolio.id == portfolio_id, Portfolio.tenant_id == user.tenant_id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Portfolio not found")
    result = await db.execute(
        select(Company).where(Company.id == company_id, Company.tenant_id == user.tenant_id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Company not found")
    existing = await db.execute(
        select(PortfolioCompany).where(
            PortfolioCompany.portfolio_id == portfolio_id,
            PortfolioCompany.company_id == company_id,
        )
    )
    if existing.scalar_one_or_none():
        return {"message": "Company already in portfolio"}
    pc = PortfolioCompany(portfolio_id=portfolio_id, company_id=company_id)
    db.add(pc)
    await db.flush()
    return {"message": "Company added to portfolio"}
