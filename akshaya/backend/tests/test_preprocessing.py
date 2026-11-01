from datetime import date, timedelta

import pandas as pd

from app.services.preprocessing import aggregate_daily, build_daily_series, classify_demand, fill_missing_dates


def _rec(rows):
    return pd.DataFrame(rows, columns=["date", "quantity_consumed"])


def test_daily_demand_aggregation_sums_same_day():
    end = date(2026, 1, 10)
    s = aggregate_daily(_rec([(date(2026, 1, 1), 10), (date(2026, 1, 1), 5), (date(2026, 1, 2), 7)]), end)
    assert s.loc["2026-01-01"] == 15 and s.loc["2026-01-02"] == 7


def test_missing_dates_filled_with_zero_and_future_removed():
    end = date(2026, 1, 10)
    recs = _rec([(date(2026, 1, 1), 10), (date(2026, 1, 5), 20), (date(2026, 2, 1), 999)])
    df = build_daily_series(recs, end)
    assert len(df) == 10 and df.index[-1] == pd.Timestamp(end)  # continuous, future row dropped
    assert df.loc["2026-01-03", "quantity"] == 0 and df["quantity"].sum() == 30


def test_outliers_flagged_not_deleted_and_capped():
    end = date(2026, 6, 1)
    days = pd.date_range(end=end, periods=120)
    recs = _rec([(d.date(), 100 + (i % 5)) for i, d in enumerate(days)])
    recs.loc[100, "quantity_consumed"] = 5000
    df = build_daily_series(recs, end)
    spike = df.index[100]
    assert df.loc[spike, "quantity"] == 5000 and bool(df.loc[spike, "is_outlier"])  # raw kept
    assert df.loc[spike, "adjusted"] < 200  # capped for modelling


def test_outlier_flags_do_not_look_ahead():
    end = date(2026, 6, 1)
    days = pd.date_range(end=end, periods=100)
    base = [(d.date(), 100 + (i % 7)) for i, d in enumerate(days)]
    a = build_daily_series(_rec(base), end)
    changed = list(base)
    changed[-1] = (changed[-1][0], 9999)
    b = build_daily_series(_rec(changed), end)
    assert a["adjusted"].iloc[:-1].equals(b["adjusted"].iloc[:-1])
    assert a["is_outlier"].iloc[:-1].equals(b["is_outlier"].iloc[:-1])


def test_demand_classification():
    import numpy as np

    rng = np.random.default_rng(0)
    idx = pd.date_range("2025-01-01", periods=300)
    weekly = pd.Series(100 * np.array([1.2, 1.2, 1.1, 1.0, 0.9, 0.6, 0.5])[idx.dayofweek] + rng.normal(0, 3, 300), idx)
    assert classify_demand(weekly).label == "SEASONAL"
    assert classify_demand(weekly.iloc[:20]).label == "COLD_START"
    sparse = pd.Series((rng.random(300) < 0.1) * 50.0, idx)
    assert classify_demand(sparse).label == "INTERMITTENT"
    trend = pd.Series(np.linspace(100, 200, 300) + rng.normal(0, 3, 300), idx)
    assert classify_demand(trend).label == "TRENDING" and classify_demand(trend).trend_direction == "UP"
