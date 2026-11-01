"""Pydantic v2 request/response schemas for the shapes the frontend relies on."""
from __future__ import annotations

import datetime as dt
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ------------------------------------------------------------------------ materials
class MaterialCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    material_id: Optional[str] = Field(default=None, max_length=80)
    category: Optional[str] = None
    unit: str = "tonne"
    current_stock: float = Field(default=0.0, ge=0)
    unit_cost: Optional[float] = Field(default=None, ge=0)
    lead_time_days: int = Field(default=7, ge=1, le=365)
    safety_stock: float = Field(default=0.0, ge=0)
    reorder_point: float = Field(default=0.0, ge=0)
    minimum_order_quantity: float = Field(default=0.0, ge=0)
    order_multiple: float = Field(default=0.0, ge=0)
    active: bool = True

    @field_validator("name")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name must not be blank")
        return v


class MaterialUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    category: Optional[str] = None
    unit: Optional[str] = None
    current_stock: Optional[float] = Field(default=None, ge=0)
    unit_cost: Optional[float] = Field(default=None, ge=0)
    lead_time_days: Optional[int] = Field(default=None, ge=1, le=365)
    minimum_order_quantity: Optional[float] = Field(default=None, ge=0)
    order_multiple: Optional[float] = Field(default=None, ge=0)
    active: Optional[bool] = None


# -------------------------------------------------------------------------- upload
class UploadError(BaseModel):
    row: Optional[int] = None
    error: str


class UploadSummary(BaseModel):
    upload_id: str
    file_name: str
    total_rows: int
    valid_rows: int
    invalid_rows: int
    inserted_rows: int
    duplicate_rows: int
    materials_processed: int
    forecasts_generated: int
    status: str
    errors: list[UploadError]
    warnings: list[UploadError] = []


# ----------------------------------------------------------------------------- chat
class ChatRequest(BaseModel):
    session_id: Optional[str] = Field(default=None, max_length=64)
    message: str = Field(min_length=1, max_length=1000)

    @field_validator("message")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("message must not be blank")
        return v.strip()


class ChatResponse(BaseModel):
    session_id: str
    answer: str
    material_id: Optional[str] = None
    material_ids: list[str] = []
    intent: str
    data_used: dict[str, Any] = {}
    suggestions: list[str] = []


# -------------------------------------------------------------------- recommendations
class RecommendationItem(BaseModel):
    model_config = ConfigDict(extra="allow")
    material_id: str
    material_name: str
    current_stock: float
    unit: str
    average_daily_demand: float
    days_of_cover: float
    predicted_depletion_date: Optional[dt.date] = None
    reorder_point: float
    recommended_order_quantity: float
    stock_status: str
    recommendation: str


class RecommendationSummary(BaseModel):
    total_materials: int
    critical_count: int
    reorder_count: int
    overstock_count: int
    healthy_count: int
    slow_moving_count: int = 0


class RecommendationsResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    generated_at: str
    critical_materials: list[RecommendationItem]
    reorder_now: list[RecommendationItem]
    overstocked_materials: list[RecommendationItem]
    healthy_materials: list[RecommendationItem]
    slow_moving_materials: list[RecommendationItem] = []
    summary: RecommendationSummary


# -------------------------------------------------------------------------- forecast
class GenerateForecastRequest(BaseModel):
    material_ids: Optional[list[str]] = None
    confidence_level: float = Field(default=0.90)

    @field_validator("confidence_level")
    @classmethod
    def _conf(cls, v: float) -> float:
        if v not in (0.90, 0.95):
            raise ValueError("confidence_level must be 0.90 or 0.95")
        return v


class RecalculateParams(BaseModel):
    service_level: Optional[float] = None
    review_period_days: Optional[int] = Field(default=None, ge=0, le=90)
    expected_inbound_quantity: float = Field(default=0.0, ge=0)


# ---------------------------------------------------------------------- simulation
class ConsumeRequest(BaseModel):
    material_id: str
    quantity: float = Field(gt=0)
    date: Optional[dt.date] = None


class DeliveryRequest(BaseModel):
    material_id: str
    quantity: float = Field(gt=0)


class RunDayRequest(BaseModel):
    date: Optional[dt.date] = None
    noise: float = Field(default=0.08, ge=0, le=0.5)


class SeedRequest(BaseModel):
    confirm: bool = False
    months: int = Field(default=18, ge=2, le=36)
