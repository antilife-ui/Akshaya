import numpy as np
import pandas as pd
import pytest

from app.services import forecasting as F
from app.services.preprocessing import classify_demand


def _series(n=240, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2025-01-01", periods=n)
    vals = 100 * np.array([1.2, 1.2, 1.1, 1.0, 0.9, 0.6, 0.5])[idx.dayofweek] + rng.normal(0, 4, n)
    return pd.Series(vals, idx)


def test_forecast_generation_shape_bounds_and_dates():
    s = _series()
    res = F.generate_forecast(s, classify_demand(s), horizon=180, confidence=0.90)
    assert len(res.predicted) == 180 and res.dates[0] == (s.index[-1] + pd.Timedelta(days=1)).date()
    assert np.all(res.lower >= 0) and np.all(res.lower <= res.predicted) and np.all(res.predicted <= res.upper)
    pt = res.points(7)[0]
    assert set(pt) == {"date", "predicted_demand", "lower_bound", "upper_bound", "confidence_level"}


def test_interval_uses_validation_residuals_and_z():
    s = _series()
    r90 = F.generate_forecast(s, classify_demand(s), 30, 0.90)
    r95 = F.generate_forecast(s, classify_demand(s), 30, 0.95)
    assert r90.residual_std > 0
    half90 = (r90.upper[0] - r90.predicted[0]) / r90.residual_std
    half95 = (r95.upper[0] - r95.predicted[0]) / r95.residual_std
    assert half90 == pytest.approx(1.645, rel=1e-6) and half95 == pytest.approx(1.96, rel=1e-6)


def test_fallback_chain_marks_status(monkeypatch):
    s = _series()
    def boom(*a, **k):
        raise RuntimeError("model exploded")
    monkeypatch.setitem(F.MODELS, "holt_winters", boom)
    monkeypatch.setitem(F.MODELS, "holt_winters_trend", boom)
    res = F.generate_forecast(s, classify_demand(s), 30)
    assert res.status == "FALLBACK_USED" and res.model_name in {"moving_average_7", "seasonal_naive", "simple_average"}


def test_all_models_fail_raises_clear_error(monkeypatch):
    s = _series()
    for name in list(F.MODELS):
        monkeypatch.setitem(F.MODELS, name, lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    with pytest.raises(F.ForecastError, match="All forecasting models failed"):
        F.generate_forecast(s, classify_demand(s), 30)


def test_validation_trains_only_on_past():
    y = _series().to_numpy()
    seen = {}
    def spy(train, h, start):
        seen["n"] = len(train)
        return np.full(h, 1.0)
    F.MODELS["_spy"] = spy
    try:
        F.validate_model("_spy", y, _series().index)
    finally:
        del F.MODELS["_spy"]
    assert seen["n"] == len(y) - 30  # holdout is excluded from training


def test_individual_models():
    y = np.array([10.0, 0, 0, 20, 0, 0, 0, 30, 0, 0, 0, 0, 10, 0] * 4)
    assert F.croston(y, 5, pd.Timestamp("2026-01-01")).shape == (5,) and F.croston(y, 5, None)[0] > 0
    assert list(F.seasonal_naive(np.arange(14.0), 9, None)) == [7, 8, 9, 10, 11, 12, 13, 7, 8]
    gb = F.gradient_boosting(_series(150).to_numpy(), 20, pd.Timestamp("2026-01-01"))
    assert gb.shape == (20,) and np.all(gb >= 0)


def test_cold_start_uses_moving_average():
    s = _series(12)
    res = F.generate_forecast(s, classify_demand(s), 14)
    assert res.model_name == "moving_average_7"
