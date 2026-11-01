from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import RecommendationItem, RecommendationsResponse
from app.services import recommendations as svc

router = APIRouter(prefix="/recommendations", tags=["recommendations"])


@router.get("", response_model=RecommendationsResponse)
def recommendations(db: Session = Depends(get_db)):
    return svc.get_recommendations(db)


@router.post("/refresh", response_model=RecommendationsResponse)
def refresh(db: Session = Depends(get_db)):
    """Retrain all forecasts and recompute recommendations. Never places orders."""
    return svc.refresh_recommendations(db)


@router.get("/{material_id}", response_model=RecommendationItem)
def one(material_id: str, db: Session = Depends(get_db)):
    return svc.get_material_recommendation(db, material_id)
