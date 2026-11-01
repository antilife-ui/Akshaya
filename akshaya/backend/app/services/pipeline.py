"""Orchestration: records -> daily series -> forecast -> inventory snapshot.

All persisted/derived numbers use only data on or before the 'as of' date.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.config import now_ist, settings, today
from app.constants import MAX_HORIZON
from app.database import new_id
from app.errors import ApiError, NoDataError
from app.models import ConsumptionRecord, Forecast, InventorySnapshot, Material
from app.services.forecasting import ForecastError, ForecastResult, generate_forecast
from app.services.inventory import InventoryMetrics, compute_inventory_metrics, service_level_z
from app.services.preprocessing import DemandProfile, build_daily_series, classify_demand

KEEP_FORECASTS = 5
KEEP_SNAPSHOTS = 30


def _db_now():
    return now_ist().replace(tzinfo=None)


# ---------------------------------------------------------------------- data access
def get_as_of(db: Session) -> date | None:
    """Latest date with data, never later than today (future dates are discarded)."""
    last = db.scalar(select(func.max(ConsumptionRecord.date)).where(ConsumptionRecord.date <= today()))
    return last


def load_daily_records(db: Session, material_id: str) -> pd.DataFrame:
    rows = db.execute(
        select(ConsumptionRecord.date, func.sum(ConsumptionRecord.quantity_consumed))
        .where(ConsumptionRecord.material_id == material_id)
        .group_by(ConsumptionRecord.date)
    ).all()
    return pd.DataFrame([(r[0], r[1]) for r in rows], columns=["date", "quantity_consumed"])


def get_series(db: Session, material_id: str, as_of: date | None = None) -> pd.DataFrame:
    as_of = as_of or get_as_of(db)
    if as_of is None:
        return build_daily_series(None, today())
    return build_daily_series(load_daily_records(db, material_id), as_of)


def latest_forecast(db: Session, material_id: str) -> Forecast | None:
    return db.scalars(
        select(Forecast).where(Forecast.material_id == material_id).order_by(Forecast.generated_at.desc()).limit(1)
    ).first()


def latest_snapshot(db: Session, material_id: str) -> InventorySnapshot | None:
    return db.scalars(
        select(InventorySnapshot).where(InventorySnapshot.material_id == material_id)
        .order_by(InventorySnapshot.generated_at.desc()).limit(1)
    ).first()


@dataclass
class ForecastData:
    dates: list[date]
    predicted: np.ndarray
    lower: np.ndarray
    upper: np.ndarray
    sigma: float
    confidence: float
    model_name: str
    status: str
    generated_at: object
    profile: dict | None


def forecast_data(row: Forecast) -> ForecastData:
    p = row.forecast_payload
    data = p["data"]
    return ForecastData(
        dates=[date.fromisoformat(d["date"]) for d in data],
        predicted=np.array([d["predicted_demand"] for d in data], dtype=float),
        lower=np.array([d["lower_bound"] for d in data], dtype=float),
        upper=np.array([d["upper_bound"] for d in data], dtype=float),
        sigma=float(p.get("residual_std", 0.0)),
        confidence=float(p.get("confidence_level", 0.9)),
        model_name=row.model_name, status=row.status, generated_at=row.generated_at,
        profile=p.get("demand_profile"),
    )


# ------------------------------------------------------------------------ persistence
def _save_forecast(db: Session, material_id: str, res: ForecastResult, profile: DemandProfile) -> Forecast:
    row = Forecast(
        forecast_id=new_id("FC"), material_id=material_id, model_name=res.model_name,
        generated_at=_db_now(), training_start_date=res.training_start, training_end_date=res.training_end,
        horizon_days=res.horizon, forecast_payload=res.to_payload(profile),
        validation_mae=res.validation_mae, validation_mape=res.validation_mape, status=res.status,
    )
    db.add(row)
    db.flush()
    old = db.scalars(
        select(Forecast.forecast_id).where(Forecast.material_id == material_id)
        .order_by(Forecast.generated_at.desc()).offset(KEEP_FORECASTS)
    ).all()
    if old:
        db.execute(delete(Forecast).where(Forecast.forecast_id.in_(old)))
    return row


def _save_snapshot(db: Session, material_id: str, m: InventoryMetrics) -> InventorySnapshot:
    snap = InventorySnapshot(
        snapshot_id=new_id("SNP"), material_id=material_id, generated_at=_db_now(),
        current_stock=m.current_stock, average_daily_demand=m.average_daily_demand,
        forecasted_demand_next_30_days=m.forecasted_demand_next_30_days, days_of_cover=m.days_of_cover,
        predicted_depletion_date=m.predicted_depletion_date, safety_stock=m.safety_stock,
        reorder_point=m.reorder_point, recommended_order_quantity=m.recommended_order_quantity,
        stock_status=m.stock_status, recommendation=m.recommendation,
    )
    db.add(snap)
    db.flush()
    old = db.scalars(
        select(InventorySnapshot.snapshot_id).where(InventorySnapshot.material_id == material_id)
        .order_by(InventorySnapshot.generated_at.desc()).offset(KEEP_SNAPSHOTS)
    ).all()
    if old:
        db.execute(delete(InventorySnapshot).where(InventorySnapshot.snapshot_id.in_(old)))
    return snap


# ----------------------------------------------------------------------- orchestration
def refresh_material(
    db: Session,
    material: Material,
    as_of: date | None = None,
    *,
    retrain: bool = True,
    service_level: float | None = None,
    review_period_days: int | None = None,
    inbound: float = 0.0,
    confidence: float | None = None,
) -> dict:
    """Rebuild the series, (re)train the forecast if needed, and store a fresh snapshot."""
    as_of = as_of or get_as_of(db)
    if as_of is None:
        raise NoDataError(material.material_id)
    series = build_daily_series(load_daily_records(db, material.material_id), as_of)
    if series.empty:
        raise NoDataError(material.material_id)
    profile = classify_demand(series["adjusted"], series["quantity"])

    level = service_level if service_level is not None else settings.default_service_level
    try:
        service_level_z(level)
    except ValueError as exc:
        raise ApiError(400, str(exc)) from exc

    fc_row = None if retrain else latest_forecast(db, material.material_id)
    if fc_row is None or fc_row.training_end_date != as_of:
        try:
            result = generate_forecast(
                series["adjusted"], profile, MAX_HORIZON, confidence or settings.default_confidence
            )
        except ForecastError as exc:
            raise ApiError(500, f"Model failure for '{material.material_id}': {exc}") from exc
        fc_row = _save_forecast(db, material.material_id, result, profile)
    fd = forecast_data(fc_row)

    metrics = compute_inventory_metrics(
        stock=material.current_stock,
        lead_time_days=material.lead_time_days,
        moq=material.minimum_order_quantity,
        order_multiple=material.order_multiple,
        pred=fd.predicted,
        dates=fd.dates,
        residual_std=fd.sigma,
        history=series["adjusted"].to_numpy(),
        days_since_last_consumption=profile.days_since_last_consumption,
        service_level=level,
        review_period_days=review_period_days if review_period_days is not None else settings.review_period_days,
        inbound=inbound,
        overstock_factor=settings.overstock_factor,
    )
    snap = _save_snapshot(db, material.material_id, metrics)
    material.safety_stock = metrics.safety_stock
    material.reorder_point = metrics.reorder_point
    db.commit()
    return {
        "material_id": material.material_id, "model_name": fc_row.model_name, "forecast_status": fc_row.status,
        "demand_class": profile.label, "snapshot": snap, "metrics": metrics,
    }


def refresh_all(
    db: Session, material_ids: list[str] | None = None, retrain: bool = True, confidence: float | None = None
) -> dict:
    """Refresh every active material that has data. One failure never stops the others."""
    as_of = get_as_of(db)
    q = select(Material).where(Material.active.is_(True))
    if material_ids:
        q = q.where(Material.material_id.in_(material_ids))
    done, failed, skipped = [], [], []
    for mat in db.scalars(q).all():
        try:
            done.append(refresh_material(db, mat, as_of, retrain=retrain, confidence=confidence))
        except NoDataError:
            skipped.append(mat.material_id)
        except ApiError as exc:
            db.rollback()
            failed.append({"material_id": mat.material_id, "error": str(exc.detail)})
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            failed.append({"material_id": mat.material_id, "error": f"{type(exc).__name__}: {exc}"})
    return {"as_of": as_of, "done": done, "failed": failed, "skipped": skipped}
