from __future__ import annotations

import uuid
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings

if settings.db_url.startswith("sqlite:///") and ":memory:" not in settings.db_url:
    Path(settings.db_url.replace("sqlite:///", "", 1)).parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(settings.db_url, connect_args={"check_same_thread": False})


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_conn, _record):  # enforce foreign keys, better concurrency
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA journal_mode=WAL")
    cur.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12].upper()}"


def init_db() -> None:
    """Create tables and make sure the five default materials exist (idempotent)."""
    from app import models  # noqa: F401  (register tables)
    from app.constants import DEFAULT_MATERIALS

    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        for m in DEFAULT_MATERIALS:
            if db.get(models.Material, m["material_id"]) is None:
                db.add(models.Material(unit="tonne", **m))
        db.commit()
