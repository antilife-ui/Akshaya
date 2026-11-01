#!/usr/bin/env bash
# Starts the Akshaya API (port 8000) and the UI (port 5173) together. Ctrl+C stops both.
set -e
cd "$(dirname "$0")"

if [ ! -d backend/.venv ]; then
  echo ">> Creating Python environment (first run only)..."
  python3 -m venv backend/.venv
  backend/.venv/bin/pip install -q -r backend/requirements.txt
fi
[ -d node_modules ] || { echo ">> Installing UI packages (first run only)..."; npm install; }
[ -f backend/data/akshaya.db ] || { echo ">> Seeding demo data..."; (cd backend && .venv/bin/python scripts/seed_data.py); }

(cd backend && .venv/bin/uvicorn app.main:app --port 8000) & API=$!
trap 'kill $API 2>/dev/null' EXIT
npm run dev
