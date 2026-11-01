"""Synthetic but realistic consumption generator (pure; used by scripts/seed_data.py)."""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

# weekly = Mon..Sun multipliers. Scenarios are chosen so the demo shows every status class.
SEED_MATERIALS = [
    {  # strong weekly seasonality, close to stockout (5 days cover vs 7 day lead time)
        "material_id": "MAT-IRON-ORE", "name": "Iron Ore", "category": "Ferrous raw material",
        "base": 820, "weekly": [1.08, 1.10, 1.07, 1.03, 1.00, 0.85, 0.70], "trend": 0.03,
        "monthly_amp": 0.05, "phase": 0.3, "noise": 0.05, "spike_prob": 0.01, "spike": (1.4, 1.8),
        "current_stock": 4300, "lead_time_days": 7, "unit_cost": 5800,
        "minimum_order_quantity": 500, "order_multiple": 100,
    },
    {  # clear upward trend, comfortably stocked
        "material_id": "MAT-COKING-COAL", "name": "Coking Coal", "category": "Fuel / reductant",
        "base": 310, "weekly": [1.02, 1.01, 1.00, 1.00, 0.99, 0.98, 0.96], "trend": 0.28,
        "monthly_amp": 0.06, "phase": 1.2, "noise": 0.06, "spike_prob": 0.01, "spike": (1.4, 1.8),
        "current_stock": 5600, "lead_time_days": 12, "unit_cost": 14500,
        "minimum_order_quantity": 300, "order_multiple": 50,
    },
    {  # stable and healthy
        "material_id": "MAT-LIMESTONE", "name": "Limestone", "category": "Flux",
        "base": 480, "weekly": [1.01, 1.01, 1.00, 1.00, 1.00, 0.99, 0.99], "trend": 0.00,
        "monthly_amp": 0.04, "phase": 2.0, "noise": 0.05, "spike_prob": 0.005, "spike": (1.3, 1.6),
        "current_stock": 5200, "lead_time_days": 5, "unit_cost": 1400,
        "minimum_order_quantity": 200, "order_multiple": 50,
    },
    {  # downward trend and overstocked
        "material_id": "MAT-DOLOMITE", "name": "Dolomite", "category": "Flux",
        "base": 250, "weekly": [1.02, 1.02, 1.01, 1.00, 0.99, 0.98, 0.98], "trend": -0.18,
        "monthly_amp": 0.05, "phase": 0.8, "noise": 0.06, "spike_prob": 0.005, "spike": (1.3, 1.6),
        "current_stock": 9500, "lead_time_days": 6, "unit_cost": 1900,
        "minimum_order_quantity": 100, "order_multiple": 50,
    },
    {  # volatile with demand spikes; stock sits just under its reorder point
        "material_id": "MAT-SCRAP", "name": "Scrap", "category": "Metallic charge",
        "base": 390, "weekly": [1.03, 1.03, 1.02, 1.00, 0.98, 0.95, 0.90], "trend": 0.00,
        "monthly_amp": 0.08, "phase": 4.0, "noise": 0.30, "spike_prob": 0.04, "spike": (1.6, 2.4),
        "current_stock": 3500, "lead_time_days": 8, "unit_cost": 29000,
        "minimum_order_quantity": 100, "order_multiple": 10,
    },
]


def generate_seed_frame(end_date: date, months: int = 18, rng_seed: int = 42) -> pd.DataFrame:
    """Daily consumption for every seed material: columns material_id, date, quantity_consumed."""
    end = pd.Timestamp(end_date)
    start = end - pd.DateOffset(months=months) + pd.Timedelta(days=1)
    days = pd.date_range(start, end, freq="D")
    n = len(days)
    t = np.arange(n)
    frames = []
    for i, m in enumerate(SEED_MATERIALS):
        rng = np.random.default_rng([rng_seed, i])
        weekly = np.asarray(m["weekly"], dtype=float)
        weekly = weekly / weekly.mean()
        trend = 1.0 + m["trend"] * (t / max(n - 1, 1))
        # month-to-month variation: one independent random factor per calendar month
        month_key = days.year.to_numpy() * 12 + days.month.to_numpy()
        uniq, inv = np.unique(month_key, return_inverse=True)
        monthly = 1.0 + np.clip(rng.normal(0.0, m["monthly_amp"], len(uniq)), -0.15, 0.15)[inv]
        noise = 1.0 + rng.normal(0.0, m["noise"], n)
        spikes = np.where(rng.random(n) < m["spike_prob"], rng.uniform(*m["spike"], n), 1.0)
        q = m["base"] * trend * weekly[days.dayofweek.to_numpy()] * monthly * noise * spikes
        q = np.round(np.clip(q, 0.0, None), 2)
        keep = q > 0
        frames.append(
            pd.DataFrame(
                {"material_id": m["material_id"], "date": days[keep].date, "quantity_consumed": q[keep]}
            )
        )
    return pd.concat(frames, ignore_index=True)
