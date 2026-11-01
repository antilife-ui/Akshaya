from app.services import intents as I
from app.services.intents import Intent

MATS = [("MAT-IRON-ORE", "Iron Ore"), ("MAT-COKING-COAL", "Coking Coal"), ("MAT-LIMESTONE", "Limestone"),
        ("MAT-DOLOMITE", "Dolomite"), ("MAT-SCRAP", "Scrap")]

CASES = {
    "How long will Iron Ore last?": Intent.MATERIAL_DEPLETION,
    "When will Coking Coal run out?": Intent.MATERIAL_DEPLETION,
    "Predict depletion for Scrap.": Intent.MATERIAL_DEPLETION,
    "Forecast Limestone demand for next 30 days.": Intent.MATERIAL_FORECAST,
    "What will Dolomite consumption be next week?": Intent.MATERIAL_FORECAST,
    "What is the current stock of Iron Ore?": Intent.INVENTORY_STATUS,
    "Show inventory status for Scrap.": Intent.INVENTORY_STATUS,
    "What should I reorder?": Intent.REORDER_RECOMMENDATION,
    "Which materials need reorder?": Intent.REORDER_RECOMMENDATION,
    "How much Iron Ore should I order?": Intent.REORDER_RECOMMENDATION,
    "Show Iron Ore consumption for last 6 months.": Intent.CONSUMPTION_ANALYSIS,
    "Which material was consumed the most last month?": Intent.CONSUMPTION_ANALYSIS,
    "Which materials are at risk?": Intent.CRITICAL_MATERIALS,
    "Which material will exhaust first?": Intent.CRITICAL_MATERIALS,
    "Show scarce materials.": Intent.CRITICAL_MATERIALS,
    "What can you do?": Intent.GENERAL_HELP,
    "How does this system work?": Intent.GENERAL_HELP,
}


def test_intent_detection_for_every_spec_example():
    for text, expected in CASES.items():
        assert I.detect_intent(text) == expected, text


def test_material_matching_including_multiple_and_aliases():
    assert I.find_materials("How long will iron ore and scrap last?", MATS) == ["MAT-IRON-ORE", "MAT-SCRAP"]
    assert I.find_materials("is coal ok", MATS) == ["MAT-COKING-COAL"]
    assert I.find_materials("what about the weather", MATS) == []


def test_horizon_and_period_parsing():
    assert I.parse_horizon("for next 30 days") == 30 and I.parse_horizon("next week") == 7
    assert I.parse_horizon("next 2 years") == 180  # capped at the model horizon
    assert I.parse_days("last 6 months", 30) == 180 and I.parse_days("how much", 30) == 30


ITEM = {
    "material_id": "MAT-IRON-ORE", "material_name": "Iron Ore", "unit": "tonne", "current_stock": 5000,
    "average_daily_demand": 822.2, "days_of_cover": 6.1, "predicted_depletion_date": "2026-11-04",
    "recommended_order_quantity": 5000, "reorder_point": 6500, "lead_time_days": 7,
    "stock_status": "CRITICAL_STOCKOUT_RISK", "recommendation": "Reorder immediately to avoid production disruption.",
}


def test_depletion_answer_matches_template():
    a = I.answer_depletion(ITEM)
    assert a == (
        "Iron Ore is expected to last approximately 6.1 days based on current stock of 5,000 tonne and forecasted "
        "average daily demand of 822.2 tonne. It is expected to deplete on 2026-11-04. "
        "Recommended reorder quantity is 5,000 tonne."
    )


def test_other_templates():
    assert "should be reordered now" in I.answer_reorder(ITEM) and "reorder point of 6,500" in I.answer_reorder(ITEM)
    assert I.answer_critical(ITEM).startswith("The most critical material is Iron Ore.")
    assert "forecasted to consume approximately 24,660 tonne over the next 30 days" in I.answer_forecast(ITEM, 30, 24660)
