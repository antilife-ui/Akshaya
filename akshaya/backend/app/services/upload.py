"""CSV upload: validate -> map materials -> store -> rebuild series/forecasts/snapshots."""
from __future__ import annotations

import io

import numpy as np
import pandas as pd
from sqlalchemy import func, insert, select
from sqlalchemy.orm import Session

from app.config import now_ist, settings, to_ist_iso, today
from app.constants import REQUIRED_COLUMNS
from app.database import new_id
from app.errors import ApiError
from app.models import ConsumptionRecord, Material, UploadBatch
from app.services.csv_parser import CsvFormatError, parse_and_validate
from app.services.materials import make_material_id, name_key
from app.services.pipeline import refresh_all

CHUNK = 1000
MAX_STORED_ERRORS = 500


def _db_now():
    return now_ist().replace(tzinfo=None)


def sample_template_csv() -> str:
    from datetime import timedelta

    d = (today() - timedelta(days=1)).isoformat()
    rows = [
        ("Iron Ore", 820, 5000, 7), ("Coking Coal", 310, 2200, 12), ("Limestone", 480, 3500, 5),
        ("Dolomite", 250, 1800, 6), ("Scrap", 390, 2600, 8),
    ]
    buf = io.StringIO()
    buf.write("material_name,date,quantity_consumed,current_stock,lead_time_days,unit\n")
    for name, q, stock, lead in rows:
        buf.write(f"{name},{d},{q},{stock},{lead},tonne\n")
    return buf.getvalue()


def _record_batch(db: Session, upload_id: str, file_name: str, total: int, valid: int, invalid: int,
                  status: str, errors: list) -> None:
    db.rollback()  # discard any half-applied work before recording the outcome
    db.add(UploadBatch(
        upload_id=upload_id, file_name=file_name, uploaded_at=_db_now(), total_rows=total,
        valid_rows=valid, invalid_rows=invalid, status=status, errors=errors[:MAX_STORED_ERRORS],
    ))
    db.commit()


def process_csv_upload(db: Session, file_name: str, content: bytes) -> dict:
    upload_id = new_id("UPL")

    def fail(code: int, message: str, *, errors=None, total=0, valid=0, invalid=0, status="FAILED"):
        errs = errors or [{"row": None, "error": message}]
        _record_batch(db, upload_id, file_name, total, valid, invalid, status, errs)
        raise ApiError(code, {"message": message, "upload_id": upload_id, "errors": errs[:20]})

    # 1) file-level validation
    if not file_name.lower().endswith(".csv"):
        fail(400, "Invalid file type: only .csv files are accepted.")
    if len(content) > settings.max_upload_mb * 1024 * 1024:
        fail(400, f"File is too large (limit {settings.max_upload_mb} MB).")
    try:
        parsed = parse_and_validate(content, today())
    except CsvFormatError as exc:
        fail(400, str(exc))
    if parsed.valid.empty:
        fail(400, "No valid rows found in the CSV. Check the dates and quantities.",
             errors=parsed.errors, total=parsed.total_rows, invalid=parsed.invalid_rows)

    valid = parsed.valid.copy()

    # 2) map material_name -> material_id (auto-create unknown materials)
    existing = db.scalars(select(Material)).all()
    by_id = {m.material_id: m for m in existing}
    by_key = {name_key(m.name): m for m in existing}
    mapping: dict[tuple[str, str], str] = {}
    for mid_raw, name in valid[["material_id", "material_name"]].drop_duplicates().itertuples(index=False):
        mat = by_id.get(mid_raw) if mid_raw else None
        if mat is None:
            mat = by_key.get(name_key(name))
        if mat is None:
            units = valid.loc[valid["material_name"] == name, "unit"]
            units = units[units != ""]
            mat = Material(
                material_id=make_material_id(db, name), name=name,
                unit=units.iloc[0] if len(units) else "tonne", current_stock=0.0, lead_time_days=7,
            )
            db.add(mat)
            db.flush()
            by_id[mat.material_id], by_key[name_key(name)] = mat, mat
        mapping[(mid_raw, name)] = mat.material_id
    valid["mat_id"] = [mapping[(a, b)] for a, b in zip(valid["material_id"], valid["material_name"])]

    # 3) store consumption rows (exact duplicates are skipped by the unique constraint)
    unique_rows = valid.drop_duplicates(subset=["mat_id", "date", "quantity_consumed"])
    before = db.scalar(select(func.count()).select_from(ConsumptionRecord)) or 0
    now = _db_now()
    payload = [
        {"record_id": new_id("REC"), "material_id": m, "date": d, "quantity_consumed": float(q),
         "source": "csv_upload", "created_at": now}
        for m, d, q in zip(unique_rows["mat_id"], unique_rows["date"], unique_rows["quantity_consumed"])
    ]
    table = ConsumptionRecord.__table__
    for i in range(0, len(payload), CHUNK):
        db.execute(insert(table).prefix_with("OR IGNORE"), payload[i : i + CHUNK])
    inserted = (db.scalar(select(func.count()).select_from(ConsumptionRecord)) or 0) - before
    valid_rows = len(valid)
    if inserted == 0:
        fail(409, f"Duplicate upload: all {valid_rows} valid rows already exist in the database.",
             errors=parsed.errors or None, total=parsed.total_rows, valid=valid_rows,
             invalid=parsed.invalid_rows, status="DUPLICATE")

    # 4) update stock / lead time / cost / unit from the most recent row that carries them
    ordered = valid.sort_values(["date", "row"])
    for mid, g in ordered.groupby("mat_id"):
        mat = by_id[mid]
        s = g["current_stock"].dropna()
        s = s[s >= 0]
        if len(s):
            mat.current_stock = float(s.iloc[-1])
        lt = g["lead_time_days"].dropna()
        lt = lt[lt >= 1]
        if len(lt):
            mat.lead_time_days = int(round(lt.iloc[-1]))
        uc = g["unit_cost"].dropna()
        uc = uc[uc >= 0]
        if len(uc):
            mat.unit_cost = float(uc.iloc[-1])
        un = g["unit"][g["unit"] != ""]
        if len(un):
            mat.unit = str(un.iloc[-1])
        mat.updated_at = now
    db.commit()

    # 5) rebuild daily series, retrain forecasts and recompute recommendations
    affected = sorted(set(valid["mat_id"]))
    result = refresh_all(db, affected, retrain=True)
    warnings = [
        {"row": None, "error": f"Forecast failed for {f['material_id']}: {f['error']}"} for f in result["failed"]
    ]
    status = "COMPLETED" if not warnings else "COMPLETED_WITH_WARNINGS"
    _record_batch(db, upload_id, file_name, parsed.total_rows, valid_rows, parsed.invalid_rows, status,
                  parsed.errors + warnings)
    return {
        "upload_id": upload_id, "file_name": file_name, "total_rows": parsed.total_rows,
        "valid_rows": valid_rows, "invalid_rows": parsed.invalid_rows, "inserted_rows": int(inserted),
        "duplicate_rows": int(valid_rows - inserted), "materials_processed": len(affected),
        "forecasts_generated": len(result["done"]), "status": status,
        "errors": parsed.errors[:MAX_STORED_ERRORS], "warnings": warnings,
    }


def batch_to_dict(b: UploadBatch, include_errors: bool = True) -> dict:
    d = {
        "upload_id": b.upload_id, "file_name": b.file_name, "uploaded_at": to_ist_iso(b.uploaded_at),
        "total_rows": b.total_rows, "valid_rows": b.valid_rows, "invalid_rows": b.invalid_rows, "status": b.status,
    }
    if include_errors:
        d["errors"] = b.errors or []
    return d
