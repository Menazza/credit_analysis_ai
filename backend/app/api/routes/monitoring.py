"""
Monitoring: scheduled reminders, covenant certificates, management accounts,
rating triggers, watchlist workflow. Stub endpoints for full implementation.
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from app.api.deps import get_current_user
from app.models.tenancy import User

router = APIRouter(prefix="/monitoring", tags=["monitoring"])


class WatchlistItem(BaseModel):
    company_id: str
    reason: str
    assigned_to: str | None
    status: str


@router.get("/reminders")
async def list_reminders(user: User = Depends(get_current_user)):
    """Scheduled reminders: covenant certs, MA, annual AFS."""
    return {"items": [], "message": "Configure scheduled jobs (Celery beat) for reminders."}


@router.get("/triggers")
async def list_triggers(user: User = Depends(get_current_user)):
    """Threshold-based triggers: leverage, liquidity, etc."""
    return {"triggers": [], "message": "Configure thresholds in tenant settings."}


@router.get("/watchlist", response_model=list[WatchlistItem])
async def list_watchlist(user: User = Depends(get_current_user)):
    """Watchlist with assignee and action log."""
    return []


@router.post("/watchlist")
async def add_to_watchlist(
    company_id: str,
    reason: str,
    user: User = Depends(get_current_user),
):
    """Add company to watchlist. Full impl would persist to DB."""
    return {"message": "Watchlist add would persist to DB.", "company_id": company_id, "reason": reason}
