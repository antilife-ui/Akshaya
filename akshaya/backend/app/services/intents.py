"""Deterministic intent detection + template answers for the AI Space (no LLM, no DB)."""
from __future__ import annotations

import re
from enum import Enum

from app.constants import MAX_HORIZON, StockStatus


class Intent(str, Enum):
    MATERIAL_DEPLETION = "depletion_prediction"
    MATERIAL_FORECAST = "demand_forecast"
    INVENTORY_STATUS = "inventory_status"
    REORDER_RECOMMENDATION = "reorder_recommendation"
    CONSUMPTION_ANALYSIS = "consumption_analysis"
    CRITICAL_MATERIALS = "critical_materials"
    GENERAL_HELP = "general_help"


_HELP_EXPLICIT = re.compile(r"(what can you do|what do you do|how does (this|the|it)( system| app| tool)? work|who are you|capabilit)")
_CRITICAL = re.compile(r"(at risk|\bcritical|(exhaust|run out|runs out|deplete|depleted|finish)\w* first|\bscarce|scarcity|shortage|most urgent|in danger|risky)")
_REORDER = re.compile(r"\b(re-?order\w*|order|orders|purchase|procure\w*|buy|replenish\w*)\b")
_DEPLETION = re.compile(r"(how long|run(s|ning)? out|deplet|exhaust|stock ?out|days (of cover|left|remaining)|will .{0,40}\blast\b|\blast (for|long)\b|\bfinish)")
_FORECAST = re.compile(r"(forecast|predict|projection|\bproject(ed)?\b|\bnext (\d+ )?(day|days|week|weeks|month|months|quarter|year)\b|tomorrow|upcoming|expected demand)")
_CONSUMPTION = re.compile(r"(consum|usage|\bused\b|\buse\b|histor|\b(last|past) (\d+ )?(day|days|week|weeks|month|months|quarter|year|years)\b|trend)")
_STATUS = re.compile(r"(stock|inventory|status|on hand|in hand|available|how much .{0,30}(have|left))")
_HELP_LOOSE = re.compile(r"\bhelp\b")

_UNIT_DAYS = {"day": 1, "week": 7, "month": 30, "quarter": 90, "year": 365}


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def detect_intent(text: str, has_material: bool = False) -> Intent:
    t = _clean(text)
    if _HELP_EXPLICIT.search(t):
        return Intent.GENERAL_HELP
    if _CRITICAL.search(t):
        return Intent.CRITICAL_MATERIALS
    if _REORDER.search(t):
        return Intent.REORDER_RECOMMENDATION
    if _DEPLETION.search(t):
        return Intent.MATERIAL_DEPLETION
    if _FORECAST.search(t):
        return Intent.MATERIAL_FORECAST
    if _CONSUMPTION.search(t):
        return Intent.CONSUMPTION_ANALYSIS
    if _STATUS.search(t):
        return Intent.INVENTORY_STATUS
    if _HELP_LOOSE.search(t):
        return Intent.GENERAL_HELP
    return Intent.INVENTORY_STATUS if has_material else Intent.GENERAL_HELP


def parse_days(text: str, default: int, cap: int | None = None) -> int:
    """Turn '30 days', 'next week', 'last 6 months', 'tomorrow' ... into a day count."""
    t = _clean(text)
    days = default
    m = re.search(r"(\d+)\s*(day|week|month|quarter|year)s?\b", t)
    if m:
        days = int(m.group(1)) * _UNIT_DAYS[m.group(2)]
    else:
        m = re.search(r"\b(next|last|past|this|coming)\s+(day|week|month|quarter|year)\b", t)
        if m:
            days = _UNIT_DAYS[m.group(2)]
        elif "tomorrow" in t:
            days = 1
    days = max(days, 1)
    return min(days, cap) if cap else days


def parse_horizon(text: str, default: int = 30) -> int:
    return parse_days(text, default, cap=MAX_HORIZON)


def find_materials(text: str, materials: list[tuple[str, str]]) -> list[str]:
    """materials: [(material_id, name)]. Returns ids in order of first mention."""
    t = re.sub(r"[^a-z0-9 ]", " ", text.lower())
    t = re.sub(r"\s+", " ", t)
    token_count: dict[str, int] = {}
    for _, name in materials:
        for tok in set(re.sub(r"[^a-z0-9 ]", " ", name.lower()).split()):
            token_count[tok] = token_count.get(tok, 0) + 1

    hits: list[tuple[int, str]] = []
    for mid, name in materials:
        words = re.sub(r"[^a-z0-9 ]", " ", name.lower()).split()
        if not words:
            continue
        patterns = [r"\b" + r"\s*".join(map(re.escape, words)) + r"s?\b"]
        patterns += [  # distinctive single words, e.g. "iron" -> Iron Ore, "coal" -> Coking Coal
            r"\b" + re.escape(w) + r"s?\b" for w in words if len(w) >= 4 and token_count.get(w) == 1
        ]
        positions = [m.start() for p in patterns for m in [re.search(p, t)] if m]
        if positions:
            hits.append((min(positions), mid))
    return [mid for _, mid in sorted(hits)]


# ------------------------------------------------------------------ number formatting
def n(x: float | None, d: int = 1) -> str:
    if x is None:
        return "n/a"
    s = f"{x:,.{d}f}"
    return s[:-2] if d == 1 and s.endswith(".0") else s


SEVERITY = {
    StockStatus.CRITICAL.value: 0, StockStatus.REORDER_NOW.value: 1, StockStatus.STOCKOUT_RISK.value: 2,
    StockStatus.HEALTHY.value: 4, StockStatus.OVERSTOCK.value: 5, StockStatus.SLOW_MOVING.value: 5,
}
NEEDS_ACTION = {StockStatus.CRITICAL.value, StockStatus.REORDER_NOW.value, StockStatus.STOCKOUT_RISK.value}


def risk_sort_key(item: dict) -> tuple:
    return (SEVERITY.get(item["stock_status"], 9), item["days_of_cover"])


# ------------------------------------------------------------------------- templates
HELP_TEXT = (
    "I'm the Akshaya inventory assistant. I can tell you how long a material will last, forecast its demand, "
    "show current stock and status, recommend what to reorder, summarise past consumption and flag the materials "
    "most at risk. Try: \"How long will Iron Ore last?\", \"Which materials need reorder?\" or "
    "\"Forecast Limestone demand for next 30 days\". Everything is computed from your uploaded CSV data with "
    "statistical forecasting; I recommend actions but never place orders."
)
NO_DATA_TEXT = (
    "I don't have any consumption data to analyse yet. Upload a CSV on the data intake panel "
    "(or use the sample template) and I'll be able to answer."
)


def answer_depletion(it: dict) -> str:
    s = (
        f"{it['material_name']} is expected to last approximately {n(it['days_of_cover'])} days based on current "
        f"stock of {n(it['current_stock'])} {it['unit']} and forecasted average daily demand of "
        f"{n(it['average_daily_demand'])} {it['unit']}."
    )
    if it["predicted_depletion_date"]:
        s += f" It is expected to deplete on {it['predicted_depletion_date']}."
    else:
        s += f" No depletion is projected within the {MAX_HORIZON}-day forecast window."
    if it["recommended_order_quantity"] > 0:
        s += f" Recommended reorder quantity is {n(it['recommended_order_quantity'])} {it['unit']}."
    else:
        s += " No reorder is needed right now."
    return s


def answer_forecast(it: dict, horizon: int, total: float) -> str:
    return (
        f"{it['material_name']} is forecasted to consume approximately {n(total)} {it['unit']} over the next "
        f"{horizon} days. Average daily demand is expected to be {n(total / horizon)} {it['unit']}."
    )


def answer_status(it: dict) -> str:
    return (
        f"{it['material_name']}: current stock is {n(it['current_stock'])} {it['unit']}, about "
        f"{n(it['days_of_cover'])} days of cover at {n(it['average_daily_demand'])} {it['unit']}/day "
        f"(lead time {it['lead_time_days']} days). Status: {it['stock_status'].replace('_', ' ').lower()}. "
        f"{it['recommendation']}"
    )


def answer_reorder(it: dict) -> str:
    unit = it["unit"]
    if it["stock_status"] in (StockStatus.CRITICAL.value, StockStatus.REORDER_NOW.value):
        return (
            f"{it['material_name']} should be reordered now. Current stock is {n(it['current_stock'])} {unit}, "
            f"which is below the reorder point of {n(it['reorder_point'])} {unit}. Recommended order quantity is "
            f"{n(it['recommended_order_quantity'])} {unit}."
        )
    if it["stock_status"] == StockStatus.STOCKOUT_RISK.value:
        return (
            f"{it['material_name']} is projected to fall below safety stock during its {it['lead_time_days']}-day "
            f"lead time. Plan an order of about {n(it['recommended_order_quantity'])} {unit} soon."
        )
    return (
        f"{it['material_name']} does not need reordering right now. Current stock is {n(it['current_stock'])} {unit}, "
        f"above the reorder point of {n(it['reorder_point'])} {unit}."
    )


def answer_critical(it: dict) -> str:
    when = (
        f"It is expected to deplete on {it['predicted_depletion_date']}, with approximately "
        f"{n(it['days_of_cover'])} days of cover remaining."
        if it["predicted_depletion_date"]
        else f"No depletion is projected in the forecast window; it has about {n(it['days_of_cover'])} days of cover."
    )
    return f"The most critical material is {it['material_name']}. {when}"


def suggestions_for(material_name: str | None) -> list[str]:
    first = f"Show {material_name} consumption for the last 6 months" if material_name else "Which materials need reorder?"
    return [first, "Which material will exhaust first?", "What should I reorder this week?"]
