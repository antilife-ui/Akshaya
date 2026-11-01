from datetime import date, timedelta

import numpy as np
import pytest

from app.services import inventory as inv


def _dates(n=60):
    return [date(2026, 11, 1) + timedelta(days=i) for i in range(n)]


def test_depletion_date():
    pred = np.full(60, 100.0)
    d, day = inv.predict_depletion(450, pred, _dates())
    assert day == 5 and d == date(2026, 11, 5)  # 450 - 5*100 <= 0 on day 5
    assert inv.predict_depletion(1_000_000, pred, _dates()) == (None, None)


def test_safety_stock_and_service_levels():
    assert inv.service_level_z(0.95) == 1.645 and inv.service_level_z(0.99) == 2.33
    assert inv.calc_safety_stock(1.645, 50, 9) == pytest.approx(1.645 * 50 * 3)
    with pytest.raises(ValueError):
        inv.service_level_z(0.5)


def test_reorder_point():
    assert inv.calc_reorder_point(100, 7, 150) == 850


def test_recommended_order_quantity_with_moq_and_multiple():
    assert inv.calc_order_quantity(1000, 400, 0, 0, 0) == 600
    assert inv.calc_order_quantity(1000, 400, 100, 0, 0) == 500           # inbound reduces need
    assert inv.calc_order_quantity(1000, 400, 0, 800, 0) == 800           # MOQ
    assert inv.calc_order_quantity(1000, 400, 0, 0, 250) == 750           # round up to multiple
    assert inv.calc_order_quantity(1000, 1200, 0, 500, 100) == 0          # never negative / no MOQ when nothing needed


def _metrics(stock, lead=7, daily=100.0, **kw):
    pred = np.full(180, daily)
    return inv.compute_inventory_metrics(
        stock=stock, lead_time_days=lead, moq=0, order_multiple=0, pred=pred, dates=_dates(180),
        residual_std=20.0, history=np.full(90, daily), days_since_last_consumption=0, **kw,
    )


def test_status_priority_and_recommendations():
    crit = _metrics(500)  # 5 days cover < 7 day lead time
    assert crit.stock_status == "CRITICAL_STOCKOUT_RISK" and crit.recommended_order_quantity > 0
    assert _metrics(750).stock_status == "REORDER_NOW"  # cover > lead time but <= reorder point (787)
    assert _metrics(1200).stock_status == "HEALTHY"
    assert _metrics(2000).stock_status == "HEALTHY" and _metrics(2000).recommended_order_quantity == 0
    assert _metrics(20000).stock_status == "OVERSTOCK"


def test_slow_moving():
    m = inv.compute_inventory_metrics(
        stock=20, lead_time_days=7, moq=0, order_multiple=0, pred=np.full(180, 1.0), dates=_dates(180),
        residual_std=0.1, history=np.concatenate([np.full(60, 50.0), np.zeros(40)]),
        days_since_last_consumption=40,
    )
    assert m.stock_status == "SLOW_MOVING"  # (with a large stock this would be OVERSTOCK first, per priority)


def test_forecast_based_average_preferred_and_cover():
    m = _metrics(1000)
    assert m.average_daily_demand == 100 and m.days_of_cover == 10 and m.forecasted_demand_next_30_days == 3000
