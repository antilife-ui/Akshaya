"""Daily-demand preprocessing and demand classification.

Pure pandas/numpy: no database or web imports, so it is trivially testable.
Every statistic at time t uses only data strictly before t (no look-ahead).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date

import numpy as np
import pandas as pd

from app.constants import DemandClass

STATS_WINDOW_DAYS = 180   # level / variability / seasonality statistics
TREND_WINDOW_DAYS = 365   # trend needs a longer view than the other statistics


def empty_series_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "quantity": pd.Series(dtype=float),
            "is_outlier": pd.Series(dtype=bool),
            "adjusted": pd.Series(dtype=float),
        },
        index=pd.DatetimeIndex([], name="date"),
    )


def aggregate_daily(records: pd.DataFrame | None, end_date: date) -> pd.Series:
    """Group by date, sum quantity, drop future dates (> end_date)."""
    if records is None or len(records) == 0:
        return pd.Series(dtype=float, index=pd.DatetimeIndex([], name="date"))
    df = pd.DataFrame(
        {
            "date": pd.to_datetime(records["date"]).dt.normalize(),
            "q": pd.to_numeric(records["quantity_consumed"], errors="coerce"),
        }
    ).dropna()
    df = df[df["date"] <= pd.Timestamp(end_date)]
    if df.empty:
        return pd.Series(dtype=float, index=pd.DatetimeIndex([], name="date"))
    out = df.groupby("date")["q"].sum().sort_index().astype(float)
    out.index.name = "date"
    return out


def fill_missing_dates(daily: pd.Series, end_date: date) -> pd.Series:
    """Continuous daily index from first record to end_date; gaps become 0 demand."""
    if daily.empty:
        return daily
    idx = pd.date_range(daily.index.min(), pd.Timestamp(end_date), freq="D", name="date")
    return daily.reindex(idx, fill_value=0.0).astype(float)


def flag_outliers(s: pd.Series, window: int = 28, threshold: float = 4.0) -> pd.Series:
    """Rolling median / MAD outlier flag using only *past* observations.

    Intermittent stretches (rolling median == 0) are never flagged: a non-zero
    day there is normal demand, not an outlier.
    """
    past = s.shift(1)
    med = past.rolling(window, min_periods=7).median()
    mad = past.rolling(window, min_periods=7).apply(
        lambda w: np.median(np.abs(w - np.median(w))), raw=True
    )
    scale = np.maximum(1.4826 * mad, 0.05 * med)
    flagged = (med > 0) & (scale > 0) & ((s - med).abs() > threshold * scale)
    return flagged.fillna(False).astype(bool)


def cap_outliers(s: pd.Series, flagged: pd.Series, window: int = 90, q: float = 0.99) -> pd.Series:
    """Cap flagged spikes at the 99th percentile of the previous 90 days (never deletes)."""
    cap = s.shift(1).rolling(window, min_periods=14).quantile(q)
    mask = flagged & cap.notna() & (s > cap)
    adjusted = s.copy()
    adjusted[mask] = cap[mask]
    return adjusted


def build_daily_series(records: pd.DataFrame | None, end_date: date) -> pd.DataFrame:
    """records: columns [date, quantity_consumed] (may contain several rows per day).

    Returns a DataFrame indexed by day with:
      quantity   raw daily total (what the Chart screen shows)
      is_outlier flag from rolling median/MAD
      adjusted   outlier-capped series (what models train on)
    """
    daily = fill_missing_dates(aggregate_daily(records, end_date), end_date)
    if daily.empty:
        return empty_series_frame()
    flagged = flag_outliers(daily)
    adjusted = cap_outliers(daily, flagged)
    return pd.DataFrame({"quantity": daily, "is_outlier": flagged, "adjusted": adjusted})


@dataclass
class DemandProfile:
    label: str
    total_history_days: int
    nonzero_ratio: float
    avg_daily_demand: float
    demand_std: float
    cv: float
    weekly_seasonality_strength: float
    trend_direction: str  # UP | DOWN | FLAT
    trend_pct_change: float  # signed % change across the trend window (always reported)
    trend_clear: bool
    days_since_last_consumption: int | None

    def to_dict(self) -> dict:
        return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in asdict(self).items()}


def _weekly_strength(x: pd.Series) -> float:
    """Adjusted R^2 of a day-of-week mean model (0 = none, 1 = perfectly weekly)."""
    n = len(x)
    if n < 28:
        return 0.0
    ss_tot = float(((x - x.mean()) ** 2).sum())
    if ss_tot <= 1e-12:
        return 0.0
    dow_mean = x.groupby(x.index.dayofweek).transform("mean")
    r2 = 1.0 - float(((x - dow_mean) ** 2).sum()) / ss_tot
    adj = 1.0 - (1.0 - r2) * (n - 1) / (n - 7)
    return float(min(max(adj, 0.0), 1.0))


def _trend(x: pd.Series) -> tuple[float, float]:
    """Relative change across the window from a linear fit to weekly means, and its R^2."""
    k = len(x) // 7
    if k < 8:
        return 0.0, 0.0
    w = x.to_numpy()[-k * 7 :].reshape(k, 7).mean(axis=1)
    m = float(w.mean())
    if m <= 1e-9:
        return 0.0, 0.0
    t = np.arange(k)
    slope, intercept = np.polyfit(t, w, 1)
    fit = slope * t + intercept
    ss_tot = float(((w - m) ** 2).sum())
    r2 = 1.0 - float(((w - fit) ** 2).sum()) / ss_tot if ss_tot > 0 else 0.0
    return float(slope * (k - 1) / m), float(max(r2, 0.0))


def classify_demand(adjusted: pd.Series, raw: pd.Series | None = None) -> DemandProfile:
    n_total = len(adjusted)
    x = adjusted.iloc[-STATS_WINDOW_DAYS:]
    raw_s = raw if raw is not None else adjusted

    if n_total == 0:
        return DemandProfile(DemandClass.COLD_START.value, 0, 0.0, 0.0, 0.0, 0.0, 0.0, "FLAT", 0.0, False, None)

    nonzero_ratio = float((x > 0).mean())
    avg = float(x.mean())
    std = float(x.std(ddof=1)) if len(x) > 1 else 0.0
    cv = std / avg if avg > 1e-9 else 0.0
    weekly = _weekly_strength(x)
    rel, r2 = _trend(adjusted.iloc[-TREND_WINDOW_DAYS:])
    clear = abs(rel) >= 0.10 and r2 >= 0.25
    direction = ("UP" if rel > 0 else "DOWN") if clear else "FLAT"

    nz = np.flatnonzero(raw_s.to_numpy() > 0)
    since = int(len(raw_s) - 1 - nz[-1]) if len(nz) else None

    if n_total < 30:
        label = DemandClass.COLD_START
    elif nonzero_ratio < 0.20:
        label = DemandClass.INTERMITTENT
    elif weekly >= 0.30:
        label = DemandClass.SEASONAL
    elif clear:
        label = DemandClass.TRENDING
    elif cv >= 0.30:
        label = DemandClass.VOLATILE
    else:
        label = DemandClass.STABLE

    return DemandProfile(
        label=label.value,
        total_history_days=n_total,
        nonzero_ratio=nonzero_ratio,
        avg_daily_demand=avg,
        demand_std=std,
        cv=cv,
        weekly_seasonality_strength=weekly,
        trend_direction=direction,
        trend_pct_change=rel * 100.0,
        trend_clear=clear,
        days_since_last_consumption=since,
    )
