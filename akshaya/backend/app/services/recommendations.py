"""Recommendation screen: latest inventory snapshots grouped by urgency."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.config import now_ist, to_ist_iso
from app.constants import MAX_HORIZON, StockStatus
from app.errors import ApiError, NoDataError
from app.models import InventorySnapshot, Material
from app.services.analytics import active_materials
from app.services.materials import get_or_404
from app.services.pipeline import get_as_of, latest_snapshot, refresh_all, refresh_material
from app.services.intents import risk_sort_key


def item_from(material: Material, snap: InventorySnapshot) -> dict:
    rop = snap.reorder_point
    return {
        "material_id": material.material_id, "material_name": material.name,
        "current_stock": snap.current_stock, "unit": material.unit,
        "average_daily_demand": snap.average_daily_demand,
        "forecasted_demand_next_30_days": snap.forecasted_demand_next_30_days,
        "days_of_cover": snap.days_of_cover,
        "predicted_depletion_date": snap.predicted_depletion_date.isoformat() if snap.predicted_depletion_date else None,
        "lead_time_days": material.lead_time_days, "safety_stock": snap.safety_stock, "reorder_point": rop,
        "recommended_order_quantity": snap.recommended_order_quantity,
        "stock_status": snap.stock_status, "recommendation": snap.recommendation,
        "risk_score": round((rop - snap.current_stock) / rop, 4) if rop > 0 else -1.0,
        "forecast_horizon_days": MAX_HORIZON, "generated_at": to_ist_iso(snap.generated_at),
    }


def all_items(db: Session, ensure: bool = True) -> list[dict]:
    """Latest snapshot per active material. Missing snapshots are generated lazily when data exists."""
    items = []
    as_of = get_as_of(db) if ensure else None
    for m in active_materials(db):
        snap = latest_snapshot(db, m.material_id)
        if snap is None and ensure and as_of is not None:
            try:
                refresh_material(db, m, as_of, retrain=False)
            except ApiError:
                db.rollback()
            snap = latest_snapshot(db, m.material_id)
        if snap is not None:
            items.append(item_from(m, snap))
    return sorted(items, key=risk_sort_key)


def build_response(items: list[dict]) -> dict:
    by = lambda *s: [i for i in items if i["stock_status"] in {x.value for x in s}]  # noqa: E731
    critical = by(StockStatus.CRITICAL)
    reorder = by(StockStatus.REORDER_NOW, StockStatus.STOCKOUT_RISK)
    over = by(StockStatus.OVERSTOCK)
    slow = by(StockStatus.SLOW_MOVING)
    healthy = by(StockStatus.HEALTHY)
    return {
        "generated_at": now_ist().isoformat(timespec="seconds"),
        "critical_materials": critical, "reorder_now": reorder, "overstocked_materials": over,
        "healthy_materials": healthy, "slow_moving_materials": slow,
        "summary": {
            "total_materials": len(items), "critical_count": len(critical), "reorder_count": len(reorder),
            "overstock_count": len(over), "healthy_count": len(healthy), "slow_moving_count": len(slow),
        },
    }


def get_recommendations(db: Session) -> dict:
    return build_response(all_items(db))


def get_material_recommendation(db: Session, material_id: str) -> dict:
    m = get_or_404(db, material_id)
    snap = latest_snapshot(db, material_id)
    if snap is None:
        try:
            refresh_material(db, m, retrain=False)
        except NoDataError:
            raise
        snap = latest_snapshot(db, material_id)
    return item_from(m, snap)


def refresh_recommendations(db: Session) -> dict:
    result = refresh_all(db, retrain=True)
    resp = build_response(all_items(db, ensure=False))
    resp["refreshed"] = [r["material_id"] for r in result["done"]]
    resp["failed"] = result["failed"]
    return resp
