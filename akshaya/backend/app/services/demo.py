"""Demo data: seed the database with 18 months of realistic consumption (used by script + endpoint)."""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import delete, insert
from sqlalchemy.orm import Session

from app.config import now_ist, today
from app.database import new_id
from app.models import ConsumptionRecord, Forecast, InventorySnapshot, Material
from app.services.pipeline import refresh_all
from app.services.seed_generator import SEED_MATERIALS, generate_seed_frame


def seed_database(db: Session, months: int = 18, rng_seed: int = 42) -> dict:
    """DESTRUCTIVE: replaces all consumption data, forecasts and snapshots with demo data."""
    end = today() - timedelta(days=1)
    frame = generate_seed_frame(end, months, rng_seed)
    now = now_ist().replace(tzinfo=None)

    db.execute(delete(InventorySnapshot))
    db.execute(delete(Forecast))
    db.execute(delete(ConsumptionRecord))
    for cfg in SEED_MATERIALS:
        m = db.get(Material, cfg["material_id"]) or Material(material_id=cfg["material_id"], name=cfg["name"])
        m.name, m.category, m.unit, m.active = cfg["name"], cfg["category"], "tonne", True
        m.current_stock, m.unit_cost = cfg["current_stock"], cfg["unit_cost"]
        m.lead_time_days = cfg["lead_time_days"]
        m.minimum_order_quantity, m.order_multiple = cfg["minimum_order_quantity"], cfg["order_multiple"]
        m.safety_stock, m.reorder_point, m.updated_at = 0.0, 0.0, now
        db.add(m)
    db.flush()

    payload = [
        {"record_id": new_id("REC"), "material_id": mid, "date": d, "quantity_consumed": float(q),
         "source": "seed", "created_at": now}
        for mid, d, q in zip(frame["material_id"], frame["date"], frame["quantity_consumed"])
    ]
    for i in range(0, len(payload), 1000):
        db.execute(insert(ConsumptionRecord.__table__), payload[i : i + 1000])
    db.commit()

    result = refresh_all(db, [c["material_id"] for c in SEED_MATERIALS], retrain=True)
    return {
        "records_inserted": len(payload), "start_date": frame["date"].min().isoformat(),
        "end_date": end.isoformat(), "materials": [
            {"material_id": r["material_id"], "model": r["model_name"], "forecast_status": r["forecast_status"],
             "demand_class": r["demand_class"], "stock_status": r["metrics"].stock_status,
             "days_of_cover": r["metrics"].days_of_cover}
            for r in result["done"]
        ],
        "failed": result["failed"],
    }
