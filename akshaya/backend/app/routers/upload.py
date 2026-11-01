from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import ApiError
from app.models import UploadBatch
from app.schemas import UploadSummary
from app.services import upload as svc

router = APIRouter(prefix="/upload", tags=["upload"])


# NOTE: sync endpoints run in FastAPI's threadpool, so heavy forecasting never blocks the event loop.
@router.post("/csv", response_model=UploadSummary)
def upload_csv(file: UploadFile = File(...), db: Session = Depends(get_db)):
    return svc.process_csv_upload(db, file.filename or "upload.csv", file.file.read())


@router.get("/history")
def upload_history(db: Session = Depends(get_db)):
    rows = db.scalars(select(UploadBatch).order_by(UploadBatch.uploaded_at.desc()).limit(100)).all()
    return [svc.batch_to_dict(b, include_errors=False) for b in rows]


@router.get("/sample-template")
def sample_template():
    return Response(
        content=svc.sample_template_csv(), media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="akshaya-sample-template.csv"'},
    )


@router.get("/{upload_id}")
def upload_detail(upload_id: str, db: Session = Depends(get_db)):
    b = db.get(UploadBatch, upload_id)
    if b is None:
        raise ApiError(404, f"Upload '{upload_id}' not found")
    return svc.batch_to_dict(b)
