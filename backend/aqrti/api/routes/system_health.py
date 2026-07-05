"""
GO-3: System health API — exposes the latest pipeline self-check result so
the UI can show a red banner when the pipeline silently failed.
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from aqrti.database.engine import get_db_dependency
from aqrti.database.models import DailyPrice, PaperTrade, SystemHealthCheck, StrategyV2

_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent.parent
_RESTART_LOG = _BACKEND_DIR / "watchdog_restart_log.json"

router = APIRouter()


@router.get("/system-health")
def get_system_health(db: Session = Depends(get_db_dependency)):
    """Latest pipeline self-check result. Called by UI to show/hide red banner."""
    row = (
        db.query(SystemHealthCheck)
        .order_by(SystemHealthCheck.checked_at.desc())
        .first()
    )
    if not row:
        return {
            "status": "unknown",
            "message": "No health check has run yet — will run at 16:30 IST on weekdays.",
            "checked_at": None,
            "failures": [],
            "overall_ok": True,
        }
    age_hours = (datetime.utcnow() - row.checked_at).total_seconds() / 3600
    return {
        "status":       "ok" if row.overall_ok else "failed",
        "checked_at":   row.checked_at.isoformat(),
        "age_hours":    round(age_hours, 1),
        "prices_ok":    row.prices_ok,
        "shadow_ok":    row.shadow_ok,
        "pipeline_ok":  row.pipeline_ok,
        "overall_ok":   row.overall_ok,
        "prices_count": row.prices_count,
        "shadow_count": row.shadow_count,
        "failures":     row.failures.split(",") if row.failures else [],
        "stale":        age_hours > 30,   # >30h means check didn't run today
    }


@router.get("/system/restart-log")
def get_restart_log():
    """GO-2: Last N backend restarts from the watchdog — shown in UI header."""
    try:
        entries = json.loads(_RESTART_LOG.read_text()) if _RESTART_LOG.exists() else []
    except Exception:
        entries = []
    latest = entries[0] if entries else None
    age_min = None
    if latest:
        try:
            ts = datetime.fromisoformat(latest["ts"])
            age_min = round((datetime.now() - ts).total_seconds() / 60)
        except Exception:
            pass
    return {
        "last_restart":    latest,
        "age_minutes":     age_min,
        "total_restarts":  len(entries),
        "recent":          entries[:5],
    }


@router.post("/system-health/run-check")
def run_health_check_now(db: Session = Depends(get_db_dependency)):
    """Manually trigger the pipeline health check (also called by scheduler)."""
    result = _do_health_check(db)
    return result


def _do_health_check(db: Session) -> dict:
    """Core check logic — also called from the scheduler job."""
    today = date.today()
    failures = []

    # 1. Prices: did we ingest any DailyPrice rows for today?
    prices_today = db.query(DailyPrice).filter(DailyPrice.date == today).count()
    prices_ok = prices_today > 0
    if not prices_ok:
        failures.append(f"no_prices_today (date={today})")

    # 2. Shadow paper trading updated today: check PaperTrade rows closed/opened today
    shadow_today = (
        db.query(PaperTrade)
        .filter(PaperTrade.trade_date >= today)
        .count()
    )
    shadow_ok = shadow_today > 0
    if not shadow_ok:
        failures.append("no_shadow_trades_today")

    # 3. Strategy research: did any strategy get backtested/scored today?
    today_start = datetime.combine(today, datetime.min.time())
    pipeline_today = (
        db.query(StrategyV2)
        .filter(StrategyV2.updated_at >= today_start)
        .count()
    )
    pipeline_ok = pipeline_today > 0
    if not pipeline_ok:
        failures.append("no_strategy_updates_today")

    overall_ok = prices_ok and shadow_ok and pipeline_ok

    row = SystemHealthCheck(
        checked_at   = datetime.utcnow(),
        prices_ok    = prices_ok,
        shadow_ok    = shadow_ok,
        pipeline_ok  = pipeline_ok,
        overall_ok   = overall_ok,
        prices_count = prices_today,
        shadow_count = shadow_today,
        failures     = ",".join(failures) if failures else None,
    )
    db.add(row)
    db.commit()

    return {
        "status":       "ok" if overall_ok else "failed",
        "prices_ok":    prices_ok,
        "shadow_ok":    shadow_ok,
        "pipeline_ok":  pipeline_ok,
        "overall_ok":   overall_ok,
        "prices_count": prices_today,
        "shadow_count": shadow_today,
        "failures":     failures,
    }
