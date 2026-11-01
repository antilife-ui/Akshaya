"""Shared constants and enums (no third-party imports)."""
from __future__ import annotations

from enum import Enum


class StockStatus(str, Enum):
    CRITICAL = "CRITICAL_STOCKOUT_RISK"
    REORDER_NOW = "REORDER_NOW"
    STOCKOUT_RISK = "STOCKOUT_RISK"
    OVERSTOCK = "OVERSTOCK"
    SLOW_MOVING = "SLOW_MOVING"
    HEALTHY = "HEALTHY"


class DemandClass(str, Enum):
    COLD_START = "COLD_START"
    INTERMITTENT = "INTERMITTENT"
    STABLE = "STABLE"
    SEASONAL = "SEASONAL"
    TRENDING = "TRENDING"
    VOLATILE = "VOLATILE"


REQUIRED_COLUMNS = ["material_name", "date", "quantity_consumed"]
OPTIONAL_COLUMNS = ["material_id", "unit", "current_stock", "lead_time_days", "unit_cost"]

# Service level -> z (as specified)
SERVICE_LEVEL_Z = {0.90: 1.28, 0.95: 1.645, 0.98: 2.05, 0.99: 2.33}
# Forecast interval confidence -> z (as specified)
CONFIDENCE_Z = {0.90: 1.645, 0.95: 1.96}

HORIZONS = (7, 14, 30, 90, 180)
MAX_HORIZON = 180

DEFAULT_MATERIALS = [
    {"material_id": "MAT-IRON-ORE", "name": "Iron Ore", "category": "Ferrous raw material"},
    {"material_id": "MAT-COKING-COAL", "name": "Coking Coal", "category": "Fuel / reductant"},
    {"material_id": "MAT-LIMESTONE", "name": "Limestone", "category": "Flux"},
    {"material_id": "MAT-DOLOMITE", "name": "Dolomite", "category": "Flux"},
    {"material_id": "MAT-SCRAP", "name": "Scrap", "category": "Metallic charge"},
]
