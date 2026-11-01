"""Material CRUD helpers."""
from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import to_ist_iso
from app.errors import ApiError
from app.models import Material

# changing any of these invalidates the inventory snapshot (not the forecast)
INVENTORY_PARAMS = {"current_stock", "lead_time_days", "minimum_order_quantity", "order_multiple", "active"}


def name_key(name: str) -> str:
    """'Iron Ore' == 'iron-ore' == 'IRONORE'."""
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def make_material_id(db: Session, name: str) -> str:
    base = "MAT-" + (re.sub(r"[^A-Z0-9]+", "-", name.upper()).strip("-")[:40] or "ITEM")
    candidate, i = base, 2
    while db.get(Material, candidate) is not None:
        candidate, i = f"{base}-{i}", i + 1
    return candidate


def find_by_name(db: Session, name: str) -> Material | None:
    key = name_key(name)
    return next((m for m in db.scalars(select(Material)).all() if name_key(m.name) == key), None)


def get_or_404(db: Session, material_id: str) -> Material:
    m = db.get(Material, material_id)
    if m is None:
        raise ApiError(404, f"Material '{material_id}' not found")
    return m


def create_material(db: Session, data: dict) -> Material:
    name = data["name"].strip()
    if find_by_name(db, name):
        raise ApiError(409, f"A material named '{name}' already exists")
    mid = (data.get("material_id") or "").strip() or make_material_id(db, name)
    if db.get(Material, mid) is not None:
        raise ApiError(409, f"Material id '{mid}' already exists")
    fields = {k: v for k, v in data.items() if k not in {"name", "material_id"} and v is not None}
    m = Material(material_id=mid, name=name, **fields)
    db.add(m)
    db.commit()
    return m


def update_material(db: Session, material: Material, data: dict) -> bool:
    """Apply a partial update. Returns True if an inventory-relevant parameter changed."""
    if "name" in data and data["name"] is not None:
        other = find_by_name(db, data["name"])
        if other and other.material_id != material.material_id:
            raise ApiError(409, f"A material named '{data['name']}' already exists")
        data["name"] = data["name"].strip()
    changed = False
    for k, v in data.items():
        if k == "material_id" or v is None and k != "category" and k != "unit_cost":
            continue
        if getattr(material, k) != v:
            setattr(material, k, v)
            changed = changed or k in INVENTORY_PARAMS
    db.commit()
    return changed


def material_to_dict(m: Material) -> dict:
    return {
        "material_id": m.material_id, "name": m.name, "category": m.category, "unit": m.unit,
        "current_stock": m.current_stock, "unit_cost": m.unit_cost, "lead_time_days": m.lead_time_days,
        "safety_stock": round(m.safety_stock, 2), "reorder_point": round(m.reorder_point, 2),
        "minimum_order_quantity": m.minimum_order_quantity, "order_multiple": m.order_multiple,
        "active": m.active, "created_at": to_ist_iso(m.created_at), "updated_at": to_ist_iso(m.updated_at),
    }
