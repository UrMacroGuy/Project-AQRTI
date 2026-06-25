"""Replay API — /api/v1/replay  (historical state reconstruction)"""

from __future__ import annotations

import sys, os

backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from datetime import date

from fastapi import APIRouter, Depends, Query
from fastapi import HTTPException
from sqlalchemy.orm import Session

from aqrti.database.engine import get_db_dependency

router = APIRouter()


@router.get("/history")
def get_replay_history(db: Session = Depends(get_db_dependency)):
    """List recent historical replays."""
    from sqlalchemy import text
    try:
        rows = db.execute(
            text("SELECT * FROM historical_replays ORDER BY created_at DESC LIMIT 50")
        ).fetchall()
        return [dict(r._mapping) for r in rows]
    except Exception as exc:
        return []


@router.get("/date-range")
def get_date_range(db: Session = Depends(get_db_dependency)):
    """Return the available date range for replay (oldest and newest trade dates)."""
    from sqlalchemy import text
    from aqrti.database.models import PaperTrade, DailyPrice
    # Use paper trade dates as primary source
    oldest_trade = db.query(PaperTrade.entry_date).order_by(PaperTrade.entry_date.asc()).first()
    newest_trade = db.query(PaperTrade.entry_date).order_by(PaperTrade.entry_date.desc()).first()
    # Supplement with daily price date range
    oldest_price = db.query(DailyPrice.date).order_by(DailyPrice.date.asc()).first()
    newest_price = db.query(DailyPrice.date).order_by(DailyPrice.date.desc()).first()

    start = None
    end   = None
    if oldest_trade and oldest_trade[0]:
        start = str(oldest_trade[0])
    elif oldest_price and oldest_price[0]:
        start = str(oldest_price[0])
    if newest_price and newest_price[0]:
        end = str(newest_price[0])
    elif newest_trade and newest_trade[0]:
        end = str(newest_trade[0])

    return {
        "start":     start or str(date.today()),
        "end":       end   or str(date.today()),
        "available": start is not None,
    }


@router.get("/{replay_date}")
def replay_date(replay_date: str, db: Session = Depends(get_db_dependency)):
    from vault.replay_engine import replay_date as _replay
    try:
        d = date.fromisoformat(replay_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")
    return _replay(db, d)


@router.get("/compare/{date_a}/{date_b}")
def compare(date_a: str, date_b: str, db: Session = Depends(get_db_dependency)):
    from vault.replay_engine import compare_dates
    try:
        da = date.fromisoformat(date_a)
        db_date = date.fromisoformat(date_b)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")
    return compare_dates(db, da, db_date)


@router.get("/timeline/{start}/{end}")
def timeline(start: str, end: str, db: Session = Depends(get_db_dependency)):
    from vault.replay_engine import replay_range
    from datetime import timedelta
    try:
        s = date.fromisoformat(start)
        e = date.fromisoformat(end)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")
    if (e - s).days > 365:
        raise HTTPException(status_code=400, detail="Timeline range cannot exceed 365 days.")
    return {"timeline": replay_range(db, s, e)}
