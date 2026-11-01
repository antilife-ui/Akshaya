from fastapi import APIRouter, Depends
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.config import now_ist
from app.database import get_db
from app.models import ConsumptionRecord, Material

router = APIRouter(tags=["health"])


@router.get("/health")
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {
        "status": "ok", "time": now_ist().isoformat(timespec="seconds"), "database": "ok",
        "materials": db.scalar(select(func.count()).select_from(Material)),
        "consumption_records": db.scalar(select(func.count()).select_from(ConsumptionRecord)),
    }
