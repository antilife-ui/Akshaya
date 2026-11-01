"""Chart-screen analytics (consumption history, forecast view, summary)."""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import to_ist_iso
from app.constants import HORIZONS, MAX_HORIZON
from app.errors import ApiError
from app.models import ConsumptionRecord, Material
from app.services.materials import get_or_404
from app.services.pipeline import forecast_data, get_as_of, get_series, latest_forecast
from app.services.preprocessing import classify_demand

PERIOD_DAYS = {"6M": 180, "12M": 365}


def parse_period(period: str) -> tuple[str, int]:
    p = (period or "").upper()
    if p not in PERIOD_DAYS:
        raise ApiError(400, "Invalid period. Use 6M or 12M.")
    return p, PERIOD_DAYS[p]


def active_materials(db: Session) -> list[Material]:
    return list(db.scalars(select(Material).where(Material.active.is_(True)).order_by(Material.name)).all())


def materials_overview(db: Session) -> list[dict]:
    as_of = get_as_of(db)
    out = []
    for m in active_materials(db):
        first, last = db.execute(
            select(func.min(ConsumptionRecord.date), func.max(ConsumptionRecord.date))
            .where(ConsumptionRecord.material_id == m.material_id, ConsumptionRecord.date <= (as_of or date.min))
        ).one()
        out.append({
            "material_id": m.material_id, "material_name": m.name, "unit": m.unit,
            "current_stock": m.current_stock,
            "available_history_days": ((as_of - first).days + 1) if (first and as_of) else 0,
            "latest_consumption_date": last.isoformat() if last else None,
        })
    return out


def _window(series: pd.DataFrame, days: int, as_of: date | None) -> pd.Series:
    """Raw daily consumption for the last `days` days (never earlier than the first record)."""
    if series.empty or as_of is None:
        return pd.Series(dtype=float)
    start = pd.Timestamp(as_of) - pd.Timedelta(days=days - 1)
    return series["quantity"].loc[series.index >= start]


def consumption_for_material(
    db: Session, material: Material, period: str, granularity: str = "daily", as_of: date | None = None
) -> dict:
    label, days = parse_period(period)
    as_of = as_of or get_as_of(db)
    s = _window(get_series(db, material.material_id, as_of), days, as_of)
    total = float(s.sum()) if len(s) else 0.0
    avg = total / len(s) if len(s) else 0.0
    plot = s.resample("MS").sum() if (granularity == "monthly" and len(s)) else s
    return {
        "material_id": material.material_id, "material_name": material.name, "unit": material.unit,
        "period": label, "granularity": granularity,
        "start_date": s.index[0].date().isoformat() if len(s) else None,
        "end_date": s.index[-1].date().isoformat() if len(s) else None,
        "total_consumption": round(total, 2), "average_daily_consumption": round(avg, 2),
        "data": [{"date": d.date().isoformat(), "quantity_consumed": round(float(v), 2)} for d, v in plot.items()],
    }


def consumption_all(db: Session, period: str, granularity: str = "daily") -> dict:
    label, _ = parse_period(period)
    as_of = get_as_of(db)
    mats = [consumption_for_material(db, m, period, granularity, as_of) for m in active_materials(db)]
    mats = [m for m in mats if m["data"]]
    stacked: dict[str, dict] = {}
    for m in mats:
        for pt in m["data"]:
            stacked.setdefault(pt["date"], {"date": pt["date"]})[m["material_id"]] = pt["quantity_consumed"]
    return {
        "period": label, "granularity": granularity,
        "start_date": min((m["start_date"] for m in mats), default=None),
        "end_date": max((m["end_date"] for m in mats), default=None),
        "total_consumption": round(sum(m["total_consumption"] for m in mats), 2),
        "materials": mats,
        "stacked": [stacked[k] for k in sorted(stacked)],
    }


def forecast_view(db: Session, material_id: str, horizon: int = MAX_HORIZON) -> dict:
    material = get_or_404(db, material_id)
    if not 1 <= horizon <= MAX_HORIZON:
        raise ApiError(400, f"horizon must be between 1 and {MAX_HORIZON} days")
    row = latest_forecast(db, material_id)
    if row is None:
        raise ApiError(404, f"No forecast found for '{material_id}'. Upload data or POST /api/v1/forecast/generate.")
    fd = forecast_data(row)
    h = min(horizon, len(fd.predicted))
    return {
        "material_id": material_id, "material_name": material.name, "unit": material.unit,
        "model_name": fd.model_name, "status": fd.status, "horizon_days": h,
        "confidence_level": fd.confidence, "generated_at": to_ist_iso(fd.generated_at),
        "training_end_date": row.training_end_date.isoformat(),
        "totals": {str(k): round(float(fd.predicted[:k].sum()), 2) for k in HORIZONS if k <= len(fd.predicted)},
        "forecast": [
            {
                "date": fd.dates[i].isoformat(), "predicted_demand": round(float(fd.predicted[i]), 2),
                "lower_bound": round(float(fd.lower[i]), 2), "upper_bound": round(float(fd.upper[i]), 2),
                "confidence_level": fd.confidence,
            }
            for i in range(h)
        ],
    }


def summary(db: Session, period: str = "12M") -> dict:
    label, days = parse_period(period)
    as_of = get_as_of(db)
    rows = []
    for m in active_materials(db):
        series = get_series(db, m.material_id, as_of)
        if series.empty:
            continue
        w = _window(series, days, as_of)
        prof = classify_demand(series["adjusted"], series["quantity"])
        rows.append({
            "material_id": m.material_id, "material_name": m.name, "unit": m.unit,
            "total_consumption": round(float(w.sum()), 2),
            "average_daily_consumption": round(float(w.mean()), 2) if len(w) else 0.0,
            "volatility_cv": round(prof.cv, 3), "trend_pct_change": round(prof.trend_pct_change, 1),
            "trend_direction": prof.trend_direction, "demand_class": prof.label,
        })

    def pick(key, reverse=True, cond=lambda r: True, label_key=None):
        c = [r for r in rows if cond(r)]
        if not c:
            return None
        r = max(c, key=lambda x: x[key]) if reverse else min(c, key=lambda x: x[key])
        return {"material_id": r["material_id"], "material_name": r["material_name"], "value": r[key], "unit": r["unit"]}

    return {
        "period": label, "as_of": as_of.isoformat() if as_of else None, "materials": rows,
        "highest_consumption": pick("total_consumption"),
        "lowest_consumption": pick("total_consumption", reverse=False),
        "most_volatile": pick("volatility_cv"),
        "strongest_upward_trend": pick("trend_pct_change", cond=lambda r: r["trend_pct_change"] > 0),
        "strongest_downward_trend": pick("trend_pct_change", reverse=False, cond=lambda r: r["trend_pct_change"] < 0),
    }
