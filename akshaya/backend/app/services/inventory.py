"""Inventory-policy engine (pure functions, no DB).

safety_stock  = z * forecast_error_std * sqrt(lead_time_days)
reorder_point = avg_daily_demand * lead_time_days + safety_stock
order qty     = max(required - stock - inbound, 0), then MOQ and order-multiple.
The engine only *recommends*; it never places orders.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

import numpy as np

from app.constants import SERVICE_LEVEL_Z, StockStatus

MAX_COVER_DAYS = 9999.0
EPS = 1e-6


def service_level_z(level: float) -> float:
    for k, z in SERVICE_LEVEL_Z.items():
        if abs(k - level) < 1e-9:
            return z
    raise ValueError(f"service_level must be one of {sorted(SERVICE_LEVEL_Z)}")


def calc_safety_stock(z: float, error_std: float, lead_time_days: float) -> float:
    return max(0.0, z * error_std * math.sqrt(max(lead_time_days, 1)))


def calc_reorder_point(avg_daily_demand: float, lead_time_days: float, safety_stock: float) -> float:
    return avg_daily_demand * lead_time_days + safety_stock


def demand_over(pred: np.ndarray, days: int, fallback_daily: float) -> float:
    """Sum of forecast demand over the first `days` days (extended with fallback_daily)."""
    days = max(int(days), 0)
    total = float(np.sum(pred[:days])) if len(pred) else 0.0
    if days > len(pred):
        total += (days - len(pred)) * fallback_daily
    return total


def predict_depletion(stock: float, pred: np.ndarray, dates: list[date]) -> tuple[date | None, int | None]:
    """First forecast date where running stock <= 0, plus its 1-based day number."""
    if len(pred) == 0:
        return None, None
    running = stock - np.cumsum(pred)
    hit = np.flatnonzero(running <= 0)
    if len(hit) == 0:
        return None, None
    i = int(hit[0])
    return dates[i], i + 1


def days_until_level(stock: float, level: float, pred: np.ndarray) -> int | None:
    """Days until running stock first drops to `level` (0 if already at/below)."""
    if stock <= level:
        return 0
    hit = np.flatnonzero(stock - np.cumsum(pred) <= level)
    return int(hit[0]) + 1 if len(hit) else None


def calc_order_quantity(
    required_stock: float, current_stock: float, inbound: float, moq: float, multiple: float
) -> float:
    net = required_stock - current_stock - inbound
    if net <= 0:
        return 0.0
    qty = max(net, moq or 0.0)
    if multiple and multiple > 0:
        qty = math.ceil(qty / multiple - 1e-9) * multiple
    return round(qty, 2)


def classify_stock(
    *,
    stock: float,
    safety_stock: float,
    reorder_point: float,
    lead_time_days: int,
    depletion_day: int | None,
    lead_time_demand: float,
    required_stock: float,
    days_since_last_consumption: int | None,
    recent_30d_total: float,
    overstock_factor: float,
) -> StockStatus:
    """Priority: CRITICAL > REORDER_NOW > STOCKOUT_RISK > OVERSTOCK > SLOW_MOVING > HEALTHY."""
    if (depletion_day is not None and depletion_day <= lead_time_days) or stock < safety_stock:
        return StockStatus.CRITICAL
    if stock <= reorder_point:
        return StockStatus.REORDER_NOW
    if stock - lead_time_demand < safety_stock:
        return StockStatus.STOCKOUT_RISK
    if required_stock > 0 and stock > overstock_factor * required_stock:
        return StockStatus.OVERSTOCK
    if (days_since_last_consumption is not None and days_since_last_consumption >= 30) or recent_30d_total <= 0:
        return StockStatus.SLOW_MOVING
    return StockStatus.HEALTHY


RECOMMENDATION_TEXT = {
    StockStatus.CRITICAL: "Reorder immediately to avoid production disruption.",
    StockStatus.REORDER_NOW: "Stock has reached the reorder point. Place a replenishment order now.",
    StockStatus.STOCKOUT_RISK: "Projected stock during the lead time falls below safety stock. Plan an order soon.",
    StockStatus.OVERSTOCK: "Stock is well above target. Hold off new purchases and review excess inventory.",
    StockStatus.SLOW_MOVING: "Little or no consumption for 30+ days. Review demand before ordering more.",
    StockStatus.HEALTHY: "Stock level is healthy. No action required.",
}
ACTION_STATUSES = (StockStatus.CRITICAL, StockStatus.REORDER_NOW, StockStatus.STOCKOUT_RISK)


@dataclass
class InventoryMetrics:
    current_stock: float
    average_daily_demand: float
    forecasted_demand_next_30_days: float
    days_of_cover: float
    predicted_depletion_date: date | None
    safety_stock: float
    reorder_point: float
    recommended_order_quantity: float
    stock_status: str
    recommendation: str
    required_stock: float
    reorder_in_days: int | None
    risk_score: float


def compute_inventory_metrics(
    *,
    stock: float,
    lead_time_days: int,
    moq: float,
    order_multiple: float,
    pred: np.ndarray,
    dates: list[date],
    residual_std: float | None,
    history: np.ndarray,
    days_since_last_consumption: int | None,
    service_level: float = 0.95,
    review_period_days: int = 7,
    inbound: float = 0.0,
    overstock_factor: float = 2.0,
) -> InventoryMetrics:
    L = max(int(lead_time_days), 1)
    recent = history[-30:] if len(history) else np.array([0.0])
    avg_recent = float(np.mean(recent))

    # forecast-based average daily demand over the lead time (preferred), else last-30-day mean
    avg = demand_over(pred, L, avg_recent) / L if len(pred) else avg_recent
    cover = min(stock / max(avg, EPS), MAX_COVER_DAYS)
    depletion_date, depletion_day = predict_depletion(stock, pred, dates)

    err_std = residual_std if residual_std is not None else float(np.std(history[-90:])) if len(history) else 0.0
    ss = calc_safety_stock(service_level_z(service_level), err_std, L)
    rop = calc_reorder_point(avg, L, ss)

    lead_demand = demand_over(pred, L, avg)
    required = demand_over(pred, L + review_period_days, avg) + ss
    raw_qty = calc_order_quantity(required, stock, inbound, moq, order_multiple)

    status = classify_stock(
        stock=stock, safety_stock=ss, reorder_point=rop, lead_time_days=L,
        depletion_day=depletion_day, lead_time_demand=lead_demand, required_stock=required,
        days_since_last_consumption=days_since_last_consumption,
        recent_30d_total=float(np.sum(recent)), overstock_factor=overstock_factor,
    )
    # Only report an order quantity when action is actually warranted.
    qty = raw_qty if status in ACTION_STATUSES else 0.0

    return InventoryMetrics(
        current_stock=float(stock),
        average_daily_demand=round(avg, 2),
        forecasted_demand_next_30_days=round(demand_over(pred, 30, avg), 2),
        days_of_cover=round(cover, 1),
        predicted_depletion_date=depletion_date,
        safety_stock=round(ss, 2),
        reorder_point=round(rop, 2),
        recommended_order_quantity=qty,
        stock_status=status.value,
        recommendation=RECOMMENDATION_TEXT[status],
        required_stock=round(required, 2),
        reorder_in_days=days_until_level(stock, rop, pred),
        risk_score=round((rop - stock) / rop, 4) if rop > 0 else -1.0,
    )


def stock_projection(
    stock: float, pred: np.ndarray, dates: list[date], sigma: float, z: float, days: int = 90
) -> list[dict]:
    """Projected stock trajectory with an uncertainty band that widens like sqrt(h)."""
    days = min(days, len(pred))
    cum = np.cumsum(pred[:days])
    out = []
    for i in range(days):
        mean = stock - float(cum[i])
        band = z * sigma * math.sqrt(i + 1)
        out.append(
            {
                "date": dates[i].isoformat(),
                "projected_stock": round(max(mean, 0.0), 2),
                "lower_bound": round(max(mean - band, 0.0), 2),
                "upper_bound": round(max(mean + band, 0.0), 2),
            }
        )
    return out
