from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.constants import MAX_HORIZON
from app.database import get_db
from app.errors import ApiError
from app.services import analytics as svc
from app.services.materials import get_or_404

router = APIRouter(prefix="/analytics", tags=["analytics (chart screen)"])


@router.get("/materials")
def materials(db: Session = Depends(get_db)):
    return svc.materials_overview(db)


@router.get("/consumption")
def consumption(
    period: str = Query("6M", description="6M (last 180 days) or 12M (last 365 days)"),
    material_id: Optional[str] = Query(None),
    granularity: str = Query("daily", description="daily | monthly (monthly = stacked-chart friendly)"),
    db: Session = Depends(get_db),
):
    if granularity not in ("daily", "monthly"):
        raise ApiError(400, "granularity must be 'daily' or 'monthly'")
    if material_id:
        return svc.consumption_for_material(db, get_or_404(db, material_id), period, granularity)
    return svc.consumption_all(db, period, granularity)


@router.get("/forecast")
def forecast(
    material_id: str = Query(...), horizon: int = Query(MAX_HORIZON, ge=1, le=MAX_HORIZON),
    db: Session = Depends(get_db),
):
    return svc.forecast_view(db, material_id, horizon)


@router.get("/summary")
def summary(period: str = Query("12M"), db: Session = Depends(get_db)):
    return svc.summary(db, period)
