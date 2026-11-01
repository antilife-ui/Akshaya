"""Simulation helpers for demos: consume stock, receive deliveries, advance a day."""
from __future__ import annotations

import zlib
from datetime import date, timedelta

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import now_ist, today
from app.database import new_id
from app.errors import ApiError, NoDataError
from app.models import ConsumptionRecord, Material
from app.services.materials import get_or_404
from app.services.pipeline import (
    forecast_data, get_as_of, get_series, latest_forecast, latest_snapshot, refresh_all, refresh_material,
)


def _add_record(db: Session, material: Material, qty: float, day: date, source: str = "simulation") -> None:
    """Add simulated consumption (merged into the day's simulation row to respect the unique key)."""
    existing = db.scalars(
        select(ConsumptionRecord).where(
            ConsumptionRecord.material_id == material.material_id,
            ConsumptionRecord.date == day,
            ConsumptionRecord.source == source,
        )
    ).first()
    if existing is not None:
        existing.quantity_consumed = round(existing.quantity_consumed + float(qty), 4)
    else:
        db.add(ConsumptionRecord(
            record_id=new_id("REC"), material_id=material.material_id, date=day,
            quantity_consumed=round(float(qty), 4), source=source, created_at=now_ist().replace(tzinfo=None),
        ))
    material.current_stock = max(0.0, material.current_stock - qty)
    db.flush()


def _snap_view(db: Session, material: Material) -> dict:
    s = latest_snapshot(db, material.material_id)
    return {
        "material_id": material.material_id, "current_stock": round(material.current_stock, 2),
        "stock_status": s.stock_status if s else None, "days_of_cover": s.days_of_cover if s else None,
        "recommended_order_quantity": s.recommended_order_quantity if s else None,
    }


def consume(db: Session, material_id: str, quantity: float, day: date | None = None) -> dict:
    m = get_or_404(db, material_id)
    day = day or today()
    if day > today():
        raise ApiError(400, "Cannot simulate consumption on a future date.")
    _add_record(db, m, quantity, day)
    db.commit()
    refresh_material(db, m, retrain=True)
    return {"message": f"Consumed {quantity} {m.unit} of {m.name} on {day}.", **_snap_view(db, m)}


def receive_delivery(db: Session, material_id: str, quantity: float) -> dict:
    m = get_or_404(db, material_id)
    m.current_stock += quantity
    db.commit()
    try:
        refresh_material(db, m, retrain=False)  # forecast unchanged; only the policy numbers move
    except NoDataError:
        pass
    return {"message": f"Received {quantity} {m.unit} of {m.name}.", **_snap_view(db, m)}


def run_day(db: Session, day: date | None = None, noise: float = 0.08) -> dict:
    """Simulate one day of consumption for every material that has data.

    Default day = the day after the latest data; once caught up with today, extra calls add
    further consumption to today (future dates are never stored).
    """
    as_of = get_as_of(db)
    d = day or (min(as_of + timedelta(days=1), today()) if as_of else today())
    if d > today():
        raise ApiError(400, "Cannot simulate a future date.")
    out = []
    for m in db.scalars(select(Material).where(Material.active.is_(True))).all():
        if as_of is None:
            break
        series = get_series(db, m.material_id, as_of)
        if series.empty:
            continue
        row = latest_forecast(db, m.material_id)
        base = None
        if row is not None:
            fd = forecast_data(row)
            if fd.dates and fd.dates[0] == d:
                base = float(fd.predicted[0])
        if base is None:
            base = float(series["adjusted"].tail(30).mean())
        rng = np.random.default_rng(zlib.crc32(m.material_id.encode()) ^ d.toordinal())
        qty = round(max(base * (1.0 + rng.normal(0.0, noise)), 0.0), 2)
        if qty <= 0:
            continue
        _add_record(db, m, qty, d)
        out.append({"material_id": m.material_id, "quantity_consumed": qty})
    db.commit()
    result = refresh_all(db, [o["material_id"] for o in out], retrain=True) if out else {"failed": []}
    for o in out:
        o.update(_snap_view(db, db.get(Material, o["material_id"])))
    return {"date": d.isoformat(), "materials": out, "failed": result["failed"]}
