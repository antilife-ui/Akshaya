from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.constants import CONFIDENCE_Z
from app.database import get_db
from app.errors import ApiError
from app.schemas import RecalculateParams
from app.services import materials as materials_svc
from app.services.inventory import stock_projection
from app.services.pipeline import forecast_data, latest_forecast, refresh_material
from app.services.recommendations import all_items, get_material_recommendation

router = APIRouter(prefix="/inventory", tags=["inventory"])


@router.get("/overview")
def overview(db: Session = Depends(get_db)):
    return {"materials": all_items(db)}


@router.get("/{material_id}")
def detail(material_id: str, projection_days: int = Query(90, ge=1, le=180), db: Session = Depends(get_db)):
    m = materials_svc.get_or_404(db, material_id)
    item = get_material_recommendation(db, material_id)
    out = {**item, "minimum_order_quantity": m.minimum_order_quantity, "order_multiple": m.order_multiple}
    row = latest_forecast(db, material_id)
    if row is not None:
        fd = forecast_data(row)
        out["confidence_level"] = fd.confidence
        out["model_name"] = fd.model_name
        out["stock_projection"] = stock_projection(
            m.current_stock, fd.predicted, fd.dates, fd.sigma, CONFIDENCE_Z.get(fd.confidence, 1.645), projection_days
        )
    return out


@router.post("/{material_id}/recalculate")
def recalculate(material_id: str, params: RecalculateParams | None = None, db: Session = Depends(get_db)):
    """Recompute the snapshot from the current forecast (what-if: service level, review period, inbound)."""
    params = params or RecalculateParams()
    m = materials_svc.get_or_404(db, material_id)
    refresh_material(
        db, m, retrain=False, service_level=params.service_level,
        review_period_days=params.review_period_days, inbound=params.expected_inbound_quantity,
    )
    return get_material_recommendation(db, material_id)
