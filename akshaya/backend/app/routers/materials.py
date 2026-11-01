from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import NoDataError
from app.models import Material
from app.schemas import MaterialCreate, MaterialUpdate
from app.services import materials as svc
from app.services.pipeline import refresh_material

router = APIRouter(prefix="/materials", tags=["materials"])


@router.get("")
def list_materials(active_only: bool = Query(False), db: Session = Depends(get_db)):
    q = select(Material).order_by(Material.name)
    if active_only:
        q = q.where(Material.active.is_(True))
    return [svc.material_to_dict(m) for m in db.scalars(q).all()]


@router.post("", status_code=201)
def create_material(body: MaterialCreate, db: Session = Depends(get_db)):
    return svc.material_to_dict(svc.create_material(db, body.model_dump()))


@router.get("/{material_id}")
def get_material(material_id: str, db: Session = Depends(get_db)):
    return svc.material_to_dict(svc.get_or_404(db, material_id))


@router.put("/{material_id}")
def update_material(material_id: str, body: MaterialUpdate, db: Session = Depends(get_db)):
    m = svc.get_or_404(db, material_id)
    changed = svc.update_material(db, m, body.model_dump(exclude_unset=True))
    if changed:  # keep recommendations consistent with the new stock / lead time
        try:
            refresh_material(db, m, retrain=False)
        except NoDataError:
            pass
    return svc.material_to_dict(m)
