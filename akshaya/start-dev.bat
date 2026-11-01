@echo off
REM Starts the Akshaya API (port 8000) and the UI (port 5173).
cd /d "%~dp0"
if not exist backend\.venv (
  echo ^>^> Creating Python environment (first run only)...
  python -m venv backend\.venv
  backend\.venv\Scripts\pip install -q -r backend\requirements.txt
)
if not exist node_modules ( echo ^>^> Installing UI packages... & call npm install )
if not exist backend\data\akshaya.db ( echo ^>^> Seeding demo data... & pushd backend & .venv\Scripts\python scripts\seed_data.py & popd )
start "Akshaya API" cmd /k "cd backend && .venv\Scripts\uvicorn app.main:app --port 8000"
npm run dev
