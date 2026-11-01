"""Optional scheduled forecasting (enable with AKSHAYA_ENABLE_SCHEDULER=1)."""
from __future__ import annotations

import logging

from app.config import settings

log = logging.getLogger("akshaya.scheduler")


def _refresh_job() -> None:
    from app.database import SessionLocal
    from app.services.pipeline import refresh_all

    with SessionLocal() as db:
        res = refresh_all(db, retrain=True)
        log.info("Scheduled refresh: %d ok, %d failed", len(res["done"]), len(res["failed"]))


def start_scheduler():
    if not settings.enable_scheduler:
        return None
    from apscheduler.schedulers.background import BackgroundScheduler

    sched = BackgroundScheduler(timezone="Asia/Kolkata")
    sched.add_job(_refresh_job, "cron", hour=settings.scheduler_hour, minute=0, id="daily_refresh",
                  replace_existing=True)
    sched.start()
    log.info("Scheduler started: daily refresh at %02d:00 IST", settings.scheduler_hour)
    return sched
