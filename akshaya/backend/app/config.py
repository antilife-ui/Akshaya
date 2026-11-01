"""Runtime configuration (environment driven, no third-party imports)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
IST = timezone(timedelta(hours=5, minutes=30), "IST")  # India has no DST


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(int(default))).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    db_url: str
    cors_origins: tuple[str, ...]
    max_upload_mb: int
    default_service_level: float
    default_confidence: float
    review_period_days: int
    overstock_factor: float
    enable_scheduler: bool
    scheduler_hour: int
    today_override: date | None


def load_settings() -> Settings:
    default_db = f"sqlite:///{(BASE_DIR / 'data' / 'akshaya.db').as_posix()}"
    origins = os.getenv(
        "AKSHAYA_CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173,http://127.0.0.1:4173",
    )
    override = os.getenv("AKSHAYA_TODAY", "").strip()
    return Settings(
        db_url=os.getenv("AKSHAYA_DB_URL", default_db),
        cors_origins=tuple(o.strip() for o in origins.split(",") if o.strip()),
        max_upload_mb=int(os.getenv("AKSHAYA_MAX_UPLOAD_MB", "10")),
        default_service_level=float(os.getenv("AKSHAYA_SERVICE_LEVEL", "0.95")),
        default_confidence=float(os.getenv("AKSHAYA_CONFIDENCE", "0.90")),
        review_period_days=int(os.getenv("AKSHAYA_REVIEW_PERIOD_DAYS", "7")),
        overstock_factor=float(os.getenv("AKSHAYA_OVERSTOCK_FACTOR", "2.0")),
        enable_scheduler=_bool("AKSHAYA_ENABLE_SCHEDULER", False),
        scheduler_hour=int(os.getenv("AKSHAYA_SCHEDULER_HOUR", "2")),
        today_override=date.fromisoformat(override) if override else None,
    )


settings = load_settings()


def now_ist() -> datetime:
    return datetime.now(IST)


def today() -> date:
    """'Today' in IST. Future-dated data is always discarded relative to this."""
    return settings.today_override or now_ist().date()


def to_ist_iso(dt: datetime | None) -> str | None:
    """DB datetimes are stored as naive IST wall-clock; re-attach the offset."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=IST)
    return dt.astimezone(IST).isoformat(timespec="seconds")
