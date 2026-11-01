"""Forecasting engine: model zoo, validation, selection, fallbacks, intervals.

Pure pandas/numpy/scikit-learn (+ statsmodels, imported lazily so a missing or
failing statsmodels triggers the documented fallback chain instead of a crash).

No data leakage: every model is fitted only on data before the point it
predicts; validation holds out the *last* days of history, trains on the rest,
and only then is the final model refitted on the full history.
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from datetime import date
from functools import partial
from typing import Callable

import numpy as np
import pandas as pd

from app.constants import CONFIDENCE_Z, MAX_HORIZON, DemandClass
from app.services.preprocessing import DemandProfile


class ForecastError(RuntimeError):
    """Raised when every model in the fallback chain fails."""


ModelFn = Callable[[np.ndarray, int, pd.Timestamp], np.ndarray]


# --------------------------------------------------------------------------- models
def moving_average(y: np.ndarray, horizon: int, start: pd.Timestamp, window: int = 7) -> np.ndarray:
    return np.full(horizon, float(np.mean(y[-min(window, len(y)):])))


def simple_average(y: np.ndarray, horizon: int, start: pd.Timestamp) -> np.ndarray:
    return np.full(horizon, float(np.mean(y)))


def seasonal_naive(y: np.ndarray, horizon: int, start: pd.Timestamp) -> np.ndarray:
    """forecast[t] = demand[t-7] (recursive, so it repeats the last observed week)."""
    if len(y) < 7:
        raise ValueError("seasonal_naive needs at least 7 days of history")
    last = y[-7:]
    return np.array([last[i % 7] for i in range(horizon)], dtype=float)


def croston(y: np.ndarray, horizon: int, start: pd.Timestamp, alpha: float = 0.1) -> np.ndarray:
    """Croston with the Syntetos-Boylan bias correction.

    Demand size and inter-demand interval are smoothed separately; their ratio
    is the average demand per day.
    """
    nz = np.flatnonzero(y > 0)
    if len(nz) == 0:
        return np.zeros(horizon)
    sizes = y[nz]
    intervals = np.diff(np.concatenate([[-1], nz])).astype(float)
    z, p = float(sizes[0]), float(intervals[0])
    for size, gap in zip(sizes[1:], intervals[1:]):
        z += alpha * (size - z)
        p += alpha * (gap - p)
    return np.full(horizon, (z / p) * (1.0 - alpha / 2.0))


def holt_winters(y: np.ndarray, horizon: int, start: pd.Timestamp, trend: str | None = None) -> np.ndarray:
    """Additive Holt-Winters, weekly seasonality (seasonal_periods = 7)."""
    if len(y) < 28:
        raise ValueError("holt_winters needs at least 28 days of history")
    from statsmodels.tsa.holtwinters import ExponentialSmoothing  # lazy import

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        model = ExponentialSmoothing(
            y,
            trend=trend,
            damped_trend=bool(trend),
            seasonal="add",
            seasonal_periods=7,
            initialization_method="estimated",
        )
        fit = model.fit(optimized=True)
        fc = np.asarray(fit.forecast(horizon), dtype=float)
    return np.clip(fc, 0.0, None)


GB_LAGS = (1, 2, 3, 7, 14, 28)
GB_MIN_HISTORY = 90


def _gb_features(tail: np.ndarray, day: pd.Timestamp) -> list[float]:
    """Lag, rolling mean/std, trend-ratio and calendar features from the last >=28 values."""
    f = [float(tail[-lag]) for lag in GB_LAGS]
    r7, r14, r28 = float(tail[-7:].mean()), float(tail[-14:].mean()), float(tail[-28:].mean())
    s7, s14 = float(tail[-7:].std()), float(tail[-14:].std())
    eps = 1e-9
    f += [r7, r14, r28, s7, s14, r7 / (r28 + eps), r14 / (r28 + eps), day.dayofweek, day.day, day.month]
    return f


def gradient_boosting(y: np.ndarray, horizon: int, start: pd.Timestamp) -> np.ndarray:
    """HistGradientBoostingRegressor with recursive multi-step forecasting."""
    n = len(y)
    if n < GB_MIN_HISTORY:
        raise ValueError(f"gradient_boosting needs at least {GB_MIN_HISTORY} days of history")
    from sklearn.ensemble import HistGradientBoostingRegressor

    first_day = start - pd.Timedelta(days=n)  # date of y[0]
    X, t = [], []
    for i in range(28, n):
        X.append(_gb_features(y[:i][-28:], first_day + pd.Timedelta(days=i)))
        t.append(y[i])
    model = HistGradientBoostingRegressor(
        max_iter=200, learning_rate=0.05, max_depth=4, min_samples_leaf=20,
        l2_regularization=1.0, random_state=0,
    )
    model.fit(np.asarray(X), np.asarray(t))

    tail = list(y[-28:])
    out = []
    for h in range(horizon):
        day = start + pd.Timedelta(days=h)
        x = np.asarray([_gb_features(np.asarray(tail[-28:]), day)])
        p = max(float(model.predict(x)[0]), 0.0)
        out.append(p)
        tail.append(p)  # recursive: feed prediction back as the next lag
    return np.asarray(out)


MODELS: dict[str, ModelFn] = {
    "moving_average_7": partial(moving_average, window=7),
    "moving_average_14": partial(moving_average, window=14),
    "moving_average_30": partial(moving_average, window=30),
    "seasonal_naive": seasonal_naive,
    "holt_winters": partial(holt_winters, trend=None),
    "holt_winters_trend": partial(holt_winters, trend="add"),
    "gradient_boosting": gradient_boosting,
    "croston": croston,
    "simple_average": simple_average,
}


# ----------------------------------------------------------------------- validation
@dataclass
class Validation:
    mae: float
    mape: float | None
    rmse: float
    holdout_days: int


def _check(pred: np.ndarray, horizon: int) -> np.ndarray:
    pred = np.asarray(pred, dtype=float)
    if pred.shape != (horizon,) or not np.all(np.isfinite(pred)):
        raise ValueError("model returned a non-finite or mis-shaped forecast")
    return np.clip(pred, 0.0, None)


def validate_model(name: str, y: np.ndarray, index: pd.DatetimeIndex) -> Validation | None:
    """Hold out the last min(30, n//4) days, train on the rest, score on the holdout.

    Returns None when history is too short to validate (< 7 holdout days).
    """
    n = len(y)
    hold = min(30, n // 4)
    if hold < 7:
        return None
    pred = _check(MODELS[name](y[:-hold], hold, index[n - hold]), hold)
    actual = y[-hold:]
    resid = actual - pred
    nz = actual > 0
    mape = float(np.mean(np.abs(resid[nz]) / actual[nz]) * 100.0) if nz.any() else None
    return Validation(
        mae=float(np.mean(np.abs(resid))),
        mape=mape,
        rmse=float(np.sqrt(np.mean(resid**2))),
        holdout_days=hold,
    )


def candidate_models(profile: DemandProfile, n: int) -> list[str]:
    """Model-selection rules from the spec."""
    label = profile.label
    if label == DemandClass.COLD_START.value:
        return ["moving_average_7"]
    if label == DemandClass.INTERMITTENT.value:
        return ["croston"]
    if label == DemandClass.SEASONAL.value:
        return ["holt_winters_trend" if profile.trend_clear else "holt_winters"]
    if label == DemandClass.TRENDING.value:
        return ["holt_winters_trend"]
    if label == DemandClass.VOLATILE.value:
        if n >= 120:
            return ["gradient_boosting", "holt_winters"]
        return ["holt_winters"] if n >= 28 else ["moving_average_14"]
    # STABLE
    return ["moving_average_30", "holt_winters"] if n >= 56 else ["moving_average_30"]


# --------------------------------------------------------------------------- result
@dataclass
class ForecastResult:
    model_name: str
    status: str  # OK | FALLBACK_USED
    dates: list[date]
    predicted: np.ndarray
    lower: np.ndarray
    upper: np.ndarray
    confidence_level: float
    residual_std: float
    validation_mae: float | None
    validation_mape: float | None
    validation_rmse: float | None
    training_start: date
    training_end: date
    horizon: int
    candidates: dict = field(default_factory=dict)
    notes: list = field(default_factory=list)

    def points(self, horizon: int | None = None) -> list[dict]:
        h = min(horizon or self.horizon, self.horizon)
        return [
            {
                "date": self.dates[i].isoformat(),
                "predicted_demand": round(float(self.predicted[i]), 2),
                "lower_bound": round(float(self.lower[i]), 2),
                "upper_bound": round(float(self.upper[i]), 2),
                "confidence_level": self.confidence_level,
            }
            for i in range(h)
        ]

    def to_payload(self, profile: DemandProfile | None = None) -> dict:
        return {
            "confidence_level": self.confidence_level,
            "residual_std": round(self.residual_std, 4),
            "validation_rmse": None if self.validation_rmse is None else round(self.validation_rmse, 4),
            "candidates": self.candidates,
            "notes": self.notes,
            "demand_profile": profile.to_dict() if profile else None,
            "data": self.points(),
        }


# ------------------------------------------------------------------------- engine
def generate_forecast(
    series: pd.Series,
    profile: DemandProfile,
    horizon: int = MAX_HORIZON,
    confidence: float = 0.90,
) -> ForecastResult:
    """Select, validate and fit a model; return forecast + residual-based intervals.

    series: outlier-adjusted daily demand, continuous DatetimeIndex ending at 'as of'.
    """
    if confidence not in CONFIDENCE_Z:
        raise ValueError(f"confidence must be one of {sorted(CONFIDENCE_Z)}")
    y = series.to_numpy(dtype=float)
    n = len(y)
    if n == 0:
        raise ForecastError("No consumption history available to forecast from.")
    index = series.index
    start = index[-1] + pd.Timedelta(days=1)
    notes: list[str] = []

    # 1) rank candidate models on a held-out validation window
    candidates = candidate_models(profile, n)
    vals: dict[str, Validation | None] = {}
    scores: dict[str, float | None] = {}
    for c in candidates:
        try:
            vals[c] = validate_model(c, y, index)
            scores[c] = None if vals[c] is None else round(vals[c].mae, 4)
        except Exception as exc:  # noqa: BLE001 - any model failure is non-fatal here
            notes.append(f"{c} failed validation: {exc}")
            scores[c] = None
            vals[c] = None
    scored = [(vals[c].mae, c) for c in candidates if vals.get(c) is not None]
    selected = min(scored, key=lambda t: t[0])[1] if scored else candidates[0]

    # 2) fallback chain: selected -> Holt-Winters -> 7d MA -> seasonal naive -> simple average
    chain: list[str] = []
    for m in [selected, "holt_winters", "moving_average_7", "seasonal_naive", "simple_average"]:
        if m not in chain:
            chain.append(m)

    chosen, pred, used_val = None, None, None
    for rank, name in enumerate(chain):
        try:
            if name not in vals:
                try:
                    vals[name] = validate_model(name, y, index)
                except Exception as exc:  # noqa: BLE001
                    notes.append(f"{name} failed validation: {exc}")
                    vals[name] = None
            pred = _check(MODELS[name](y, horizon, start), horizon)
            chosen, used_val = name, vals.get(name)
            break
        except Exception as exc:  # noqa: BLE001
            notes.append(f"{name} failed: {exc}")
    if chosen is None:
        raise ForecastError("All forecasting models failed. " + "; ".join(notes))
    status = "OK" if chosen == chain[0] else "FALLBACK_USED"

    # 3) uncertainty from validation residuals (RMSE); in-sample dispersion if no holdout
    if used_val is not None:
        sigma = used_val.rmse
    elif n > 1:
        sigma = float(np.std(y, ddof=1))
    else:
        sigma = 0.25 * float(y[0])
    z = CONFIDENCE_Z[confidence]
    lower = np.clip(pred - z * sigma, 0.0, None)
    upper = pred + z * sigma

    dates = [(start + pd.Timedelta(days=i)).date() for i in range(horizon)]
    return ForecastResult(
        model_name=chosen,
        status=status,
        dates=dates,
        predicted=pred,
        lower=lower,
        upper=upper,
        confidence_level=confidence,
        residual_std=float(sigma),
        validation_mae=None if used_val is None else used_val.mae,
        validation_mape=None if used_val is None else used_val.mape,
        validation_rmse=None if used_val is None else used_val.rmse,
        training_start=index[0].date(),
        training_end=index[-1].date(),
        horizon=horizon,
        candidates=scores,
        notes=notes,
    )
