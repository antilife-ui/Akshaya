from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.config import to_ist_iso
from app.constants import HORIZONS, MAX_HORIZON
from app.database import get_db
from app.errors import ApiError
from app.schemas import GenerateForecastRequest
from app.services import analytics as analytics_svc
from app.services.materials import get_or_404
from app.services.pipeline import forecast_data, latest_forecast, refresh_all, refresh_material

router = APIRouter(prefix="/forecast", tags=["forecasting"])


def _summ(r: dict) -> dict:
    return {"material_id": r["material_id"], "model_name": r["model_name"], "status": r["forecast_status"],
            "demand_class": r["demand_class"]}


@router.post("/generate")
def generate(body: GenerateForecastRequest | None = None, db: Session = Depends(get_db)):
    """Retrain forecasts (180-day horizon is always generated; 7/14/30/90/180 are slices of it)."""
    body = body or GenerateForecastRequest()
    if body.material_ids:
        for mid in body.material_ids:
            get_or_404(db, mid)
    res = refresh_all(db, body.material_ids, retrain=True, confidence=body.confidence_level)
    return {"generated": [_summ(r) for r in res["done"]], "failed": res["failed"], "skipped_no_data": res["skipped"],
            "horizons_available": list(HORIZONS)}


@router.post("/retrain/{material_id}")
def retrain(material_id: str, db: Session = Depends(get_db)):
    m = get_or_404(db, material_id)
    return _summ(refresh_material(db, m, retrain=True))


@router.get("/{material_id}/accuracy")
def accuracy(material_id: str, db: Session = Depends(get_db)):
    get_or_404(db, material_id)
    row = latest_forecast(db, material_id)
    if row is None:
        raise ApiError(404, f"No forecast found for '{material_id}'")
    fd = forecast_data(row)
    p = row.forecast_payload
    return {
        "material_id": material_id, "model_name": row.model_name, "status": row.status,
        "validation_mae": row.validation_mae, "validation_mape": row.validation_mape,
        "validation_rmse": p.get("validation_rmse"), "residual_std": fd.sigma,
        "confidence_level": fd.confidence, "candidate_mae": p.get("candidates"),
        "demand_class": (fd.profile or {}).get("label"), "demand_profile": fd.profile, "notes": p.get("notes", []),
        "training_start_date": row.training_start_date.isoformat(), "training_end_date": row.training_end_date.isoformat(),
        "generated_at": to_ist_iso(row.generated_at),
    }


@router.get("/{material_id}")
def get_forecast(material_id: str, horizon: int = Query(MAX_HORIZON, ge=1, le=MAX_HORIZON),
                 db: Session = Depends(get_db)):
    return analytics_svc.forecast_view(db, material_id, horizon)
