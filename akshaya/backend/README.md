# Akshaya backend - AI-driven dynamic inventory & demand forecasting

FastAPI + SQLite service behind the four Akshaya dashboard panels
(Material Consumption, Upload Datasheet, Demand Forecast, Replenishment Priorities) and the AI Space chat.
It is a **separate project**: nothing in the frontend needs to change for it to run.
It recommends actions only - it **never places purchase orders**.

## Run

```bash
cd backend
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python scripts/seed_data.py                             # 18 months of demo data + forecasts (optional)
uvicorn app.main:app --reload --port 8000
```

Interactive docs: <http://localhost:8000/docs>. Python 3.11+.
Tests: `pytest` (API tests auto-skip if FastAPI/SQLAlchemy/statsmodels are missing).

Config via environment variables (all optional):

| Variable | Default | Meaning |
|---|---|---|
| `AKSHAYA_DB_URL` | `sqlite:///data/akshaya.db` | database |
| `AKSHAYA_CORS_ORIGINS` | Vite dev/preview on 5173/4173 | comma-separated allowed origins |
| `AKSHAYA_SERVICE_LEVEL` | `0.95` | 0.90 / 0.95 / 0.98 / 0.99 |
| `AKSHAYA_CONFIDENCE` | `0.90` | forecast interval, 0.90 or 0.95 |
| `AKSHAYA_REVIEW_PERIOD_DAYS` | `7` | used in order-quantity calculation |
| `AKSHAYA_OVERSTOCK_FACTOR` | `2.0` | overstock if stock > factor x target stock |
| `AKSHAYA_MAX_UPLOAD_MB` | `10` | CSV size limit |
| `AKSHAYA_ENABLE_SCHEDULER` | `0` | `1` = refresh all forecasts daily (IST hour = `AKSHAYA_SCHEDULER_HOUR`, default 2) |

## Workflow (exactly as specified)

CSV upload -> validate + store -> daily series (sum per day, gaps = 0, future dates removed, outliers flagged/capped,
never deleted) -> demand classification -> model selection + validation -> 180-day forecast with intervals ->
depletion date, safety stock, reorder point, order quantity, stock status -> charts / AI answers / recommendations.

* **Models:** moving averages (7/14/30), seasonal naive, Holt-Winters (weekly, optional damped trend), gradient
  boosting (`HistGradientBoostingRegressor`, lag/rolling/calendar features, recursive), Croston-SBA for intermittent demand.
  Fallback chain: selected -> Holt-Winters -> 7-day MA -> seasonal naive -> simple average (`status: FALLBACK_USED`);
  if all fail the API returns 500 with a clear message.
* **No leakage:** validation holds out the last `min(30, n/4)` days, trains only on earlier data, then refits on everything.
  Interval half-width = z x validation RMSE (z = 1.645 for 90 %, 1.96 for 95 %); lower bound is clipped at 0.
  Outlier flags/caps use only past data.
* **Inventory policy:** `safety = z * forecast_error_std * sqrt(lead_time)`, `reorder_point = avg_daily * lead + safety`,
  `order = max(avg-forecast demand over lead+review + safety - stock - inbound, 0)` then MOQ and order multiple.
  Status priority: CRITICAL_STOCKOUT_RISK > REORDER_NOW > STOCKOUT_RISK > OVERSTOCK > SLOW_MOVING > HEALTHY.

## Endpoints (`/api/v1`)

| Panel | Endpoint |
|---|---|
| Consumption chart | `GET /analytics/consumption?period=6M\|12M[&material_id=][&granularity=daily\|monthly]`, `GET /analytics/materials`, `GET /analytics/summary` |
| Upload | `POST /upload/csv` (multipart field `file`), `GET /upload/history`, `GET /upload/{id}`, `GET /upload/sample-template` |
| Forecast chart | `GET /analytics/forecast?material_id=&horizon=`, `GET /inventory/{material_id}` (adds `stock_projection`) |
| Recommendations | `GET /recommendations`, `GET /recommendations/{material_id}`, `POST /recommendations/refresh` |
| AI Space | `POST /ai/chat`, `GET /ai/chat/{session_id}` |
| Other | `/health`, `/materials` (CRUD), `/forecast/*`, `/inventory/*`, `/simulation/*` |

## Wiring the existing frontend (no frontend files were modified)

The shipped React app currently runs on mock data (`data.js`, `inventory.js`) and parses CSVs in the browser.
When you are ready to switch it over, these are the only differences to be aware of:

1. **Consumption panel** - call `GET /analytics/consumption?period=12M&granularity=monthly`. The `stacked` array is
   `[{date, "MAT-IRON-ORE": x, ...}]`, one row per month, ready for the stacked `AreaChart` (map material ids to the
   panel's colours). The panel's `6M/12M` toggle maps to `period`.
2. **Upload panel** - POST the `File` to `/upload/csv` and read `valid_rows`, `invalid_rows`, `errors[]`. Show
   `detail.message` on HTTP 400/409. The "Sample CSV" button can link to `/upload/sample-template`.
3. **CSV format** - the backend takes a *time series* (`material_name,date,quantity_consumed` + optional
   `current_stock,lead_time_days,unit,unit_cost,material_id`), not the snapshot format the browser parser expects
   (`material,stock_kt,daily_use_kt,...`). Only `.csv` is accepted server-side (the UI also lists .tsv/.txt).
4. **Units** - the mock UI is in kilo-tonnes; the backend uses the `unit` of each material (default `tonne`).
5. **Forecast panel** - `GET /inventory/{id}` returns `stock_projection` (`projected_stock`, `lower_bound`,
   `upper_bound` per day), `safety_stock`, and `GET /analytics/forecast` returns demand with 90 % bounds.
6. **Replenishment panel** - `GET /recommendations` items carry `days_of_cover`, `lead_time_days`,
   `recommended_order_quantity`, `stock_status`, `risk_score` (same `(reorder_point - stock)/reorder_point` the UI sorts by).
7. **CORS** - Vite's default origins (`localhost:5173`, `:4173`) are already allowed.

## Behaviour notes

* `recommended_order_quantity` is reported only when action is needed (CRITICAL / REORDER_NOW / STOCKOUT_RISK);
  otherwise it is `0` so a healthy material never shows an order.
* Rows dated in the future are rejected at upload ("Date is in the future").
* Exact duplicate rows (same material, date, quantity) are stored once; a file whose rows all already exist returns `409`.
  `valid_rows` includes duplicates; `inserted_rows` / `duplicate_rows` break them out.
* `POST /simulation/seed` and `scripts/seed_data.py` **replace all consumption data** (the endpoint requires `{"confirm": true}`).
* `POST /simulation/run-day` simulates the day after the latest data (never beyond today); once caught up, further calls add
  consumption to today.
* AI Space is deterministic keyword/material matching with templated answers - no external LLM. Intents are returned as
  `depletion_prediction`, `demand_forecast`, `inventory_status`, `reorder_recommendation`, `consumption_analysis`,
  `critical_materials`, `general_help`. When several materials are named, `data_used` is keyed by `material_id`.
