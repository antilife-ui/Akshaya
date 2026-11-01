"""Akshaya backend: AI-driven dynamic inventory & demand forecasting engine."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app.config import settings
from app.database import init_db
from app.errors import ApiError
from app.routers import ai, analytics, forecast, inventory, materials, recommendations, simulation, system, upload
from app.scheduler import start_scheduler
from app.services.forecasting import ForecastError

log = logging.getLogger("akshaya")


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    sched = start_scheduler()
    yield
    if sched:
        sched.shutdown(wait=False)


app = FastAPI(
    title="Akshaya - AI Inventory & Demand Forecasting API",
    version="1.0.0",
    description="Backend for the Akshaya dashboard: consumption charts, CSV intake, AI assistant, recommendations.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware, allow_origins=list(settings.cors_origins), allow_credentials=False,
    allow_methods=["*"], allow_headers=["*"],
)


@app.exception_handler(ApiError)
async def _api_error(_: Request, exc: ApiError):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(ForecastError)
async def _forecast_error(_: Request, exc: ForecastError):
    return JSONResponse(status_code=500, content={"detail": f"Model failure: {exc}"})


@app.exception_handler(SQLAlchemyError)
async def _db_error(_: Request, exc: SQLAlchemyError):
    log.exception("Database failure")
    return JSONResponse(status_code=500, content={"detail": "Database failure. See server logs."})


for r in (system, materials, upload, analytics, forecast, inventory, ai, recommendations, simulation):
    app.include_router(r.router, prefix="/api/v1")
