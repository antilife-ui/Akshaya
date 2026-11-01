from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import ApiError
from app.schemas import ConsumeRequest, DeliveryRequest, RunDayRequest, SeedRequest
from app.services import demo, simulation as svc

router = APIRouter(prefix="/simulation", tags=["simulation"])


@router.post("/consume")
def consume(body: ConsumeRequest, db: Session = Depends(get_db)):
    return svc.consume(db, body.material_id, body.quantity, body.date)


@router.post("/receive-delivery")
def receive_delivery(body: DeliveryRequest, db: Session = Depends(get_db)):
    return svc.receive_delivery(db, body.material_id, body.quantity)


@router.post("/run-day")
def run_day(body: RunDayRequest | None = None, db: Session = Depends(get_db)):
    body = body or RunDayRequest()
    return svc.run_day(db, body.date, body.noise)


@router.post("/seed")
def seed(body: SeedRequest, db: Session = Depends(get_db)):
    """DESTRUCTIVE: replaces all consumption data, forecasts and snapshots with demo data."""
    if not body.confirm:
        raise ApiError(400, "This replaces ALL consumption data with demo data. Send {\"confirm\": true} to proceed.")
    return demo.seed_database(db, months=body.months)
