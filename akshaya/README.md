# Akshaya

Powering Atmanirbhar Supply Chains for India's Industrial Giants.
React/Vite dashboard (`/`) + FastAPI forecasting backend (`/backend`).

## Run everything

```bash
./start-dev.sh        # macOS / Linux      (Windows: start-dev.bat)
```
First run creates the Python venv, installs packages, seeds 18 months of demo data and opens the UI at
<http://localhost:5173>. The API docs are at <http://localhost:8000/docs>.

Manual alternative, two terminals:

```bash
cd backend && python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
python scripts/seed_data.py && uvicorn app.main:app --port 8000      # terminal 1
npm install && npm run dev                                           # terminal 2
```

## How the UI talks to the backend

| Panel | Reads / writes |
|---|---|
| Material Consumption | `GET /api/v1/analytics/consumption?period=12M&granularity=monthly` (6M/12M toggle slices it) |
| Upload Datasheet | `POST /api/v1/upload/csv`, **Sample CSV** button -> `GET /api/v1/upload/sample-template` |
| Demand Forecast | `GET /api/v1/inventory/{id}` (stock projection + bounds, model, confidence) and `GET /api/v1/analytics/consumption?material_id=` (recent stock history) |
| Replenishment Priorities | `GET /api/v1/recommendations` |

* In dev, Vite proxies `/api` to `http://localhost:8000`, so there is no CORS setup. For a separately hosted
  frontend set `VITE_API_URL` (see `.env.example`) and `AKSHAYA_CORS_ORIGINS` on the backend.
* **Graceful fallback:** if the API is down, or has no data yet, every panel shows the original built-in demo data
  exactly as before (cards read "demo data"). Uploading with the API down shows a clear message in the upload card.
* After an upload the whole dashboard refreshes: the backend validates the CSV, rebuilds the daily series, retrains the
  forecasts and recomputes recommendations, then all four panels re-read it.
* Look and feel is untouched: no CSS, Tailwind, layout, asset or className was changed.

## CSV format (what the Upload card now sends to the backend)

```
material_name,date,quantity_consumed,current_stock,lead_time_days,unit
Iron Ore,2026-10-30,820,5000,7,tonne
```
Required: `material_name`, `date`, `quantity_consumed`. Optional: `current_stock`, `lead_time_days`, `unit`, `unit_cost`,
`material_id`. One row per material per day (history is what the forecaster learns from). Click **Sample CSV** for a template.
Bad rows are skipped and reported, never blocking the whole file. Only `.csv`, max 10 MB.

See `backend/README.md` for the full API, forecasting models and inventory policy.
