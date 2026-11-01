"""SQLite schema (SQLAlchemy 2.0). Datetimes are stored as naive IST wall-clock."""
import datetime as dt
from typing import Optional

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.config import now_ist
from app.database import Base


def _now() -> dt.datetime:
    return now_ist().replace(tzinfo=None)


class Material(Base):
    __tablename__ = "materials"

    material_id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    category: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    unit: Mapped[str] = mapped_column(String, default="tonne")
    current_stock: Mapped[float] = mapped_column(Float, default=0.0)
    unit_cost: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    lead_time_days: Mapped[int] = mapped_column(Integer, default=7)
    safety_stock: Mapped[float] = mapped_column(Float, default=0.0)
    reorder_point: Mapped[float] = mapped_column(Float, default=0.0)
    minimum_order_quantity: Mapped[float] = mapped_column(Float, default=0.0)
    order_multiple: Mapped[float] = mapped_column(Float, default=0.0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class ConsumptionRecord(Base):
    __tablename__ = "consumption_records"
    __table_args__ = (
        UniqueConstraint("material_id", "date", "quantity_consumed", "source", name="uq_consumption_dedupe"),
        Index("ix_consumption_material_date", "material_id", "date"),
    )

    record_id: Mapped[str] = mapped_column(String, primary_key=True)
    material_id: Mapped[str] = mapped_column(ForeignKey("materials.material_id"), nullable=False)
    date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    quantity_consumed: Mapped[float] = mapped_column(Float, nullable=False)
    source: Mapped[str] = mapped_column(String, default="csv_upload")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)


class Forecast(Base):
    __tablename__ = "forecasts"

    forecast_id: Mapped[str] = mapped_column(String, primary_key=True)
    material_id: Mapped[str] = mapped_column(ForeignKey("materials.material_id"), nullable=False, index=True)
    model_name: Mapped[str] = mapped_column(String, nullable=False)
    generated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)
    training_start_date: Mapped[dt.date] = mapped_column(Date)
    training_end_date: Mapped[dt.date] = mapped_column(Date)
    horizon_days: Mapped[int] = mapped_column(Integer)
    forecast_payload: Mapped[dict] = mapped_column(JSON)
    validation_mae: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    validation_mape: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String, default="OK")  # OK | FALLBACK_USED


class InventorySnapshot(Base):
    __tablename__ = "inventory_snapshots"

    snapshot_id: Mapped[str] = mapped_column(String, primary_key=True)
    material_id: Mapped[str] = mapped_column(ForeignKey("materials.material_id"), nullable=False, index=True)
    generated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)
    current_stock: Mapped[float] = mapped_column(Float)
    average_daily_demand: Mapped[float] = mapped_column(Float)
    forecasted_demand_next_30_days: Mapped[float] = mapped_column(Float)
    days_of_cover: Mapped[float] = mapped_column(Float)
    predicted_depletion_date: Mapped[Optional[dt.date]] = mapped_column(Date, nullable=True)
    safety_stock: Mapped[float] = mapped_column(Float)
    reorder_point: Mapped[float] = mapped_column(Float)
    recommended_order_quantity: Mapped[float] = mapped_column(Float)
    stock_status: Mapped[str] = mapped_column(String)
    recommendation: Mapped[str] = mapped_column(String)


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    message_id: Mapped[str] = mapped_column(String, primary_key=True)
    session_id: Mapped[str] = mapped_column(String, index=True)
    role: Mapped[str] = mapped_column(String)  # user | assistant
    message: Mapped[str] = mapped_column(String)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)


class UploadBatch(Base):
    __tablename__ = "upload_batches"

    upload_id: Mapped[str] = mapped_column(String, primary_key=True)
    file_name: Mapped[str] = mapped_column(String)
    uploaded_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)
    total_rows: Mapped[int] = mapped_column(Integer, default=0)
    valid_rows: Mapped[int] = mapped_column(Integer, default=0)
    invalid_rows: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String)
    errors: Mapped[list] = mapped_column(JSON, default=list)
