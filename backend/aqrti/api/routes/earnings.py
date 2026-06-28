"""Earnings Intelligence API — /api/v1/earnings"""

from __future__ import annotations

import sys, os

backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from aqrti.database.engine import get_db_dependency

router = APIRouter()


def _auto_scrape_if_empty(db: Session, days_ahead: int = 30) -> None:
    """If earnings_events table is empty, scrape NSE board meetings automatically."""
    from aqrti.database.models import EarningsEvent
    from datetime import date, timedelta
    count = db.query(EarningsEvent).count()
    if count == 0:
        try:
            from data_supremacy.earnings_scraper import scrape_earnings, scrape_board_meetings
            from_date = date.today() - timedelta(days=30)
            to_date   = date.today() + timedelta(days=days_ahead)
            try:
                scrape_board_meetings(db, days_ahead=days_ahead)
            except Exception:
                pass
            scrape_earnings(db, from_date=from_date, to_date=to_date)
        except Exception:
            pass


@router.get("/calendar")
def earnings_calendar(
    days_ahead: int = Query(default=30, ge=1, le=90),
    db: Session = Depends(get_db_dependency),
):
    from data_supremacy.earnings_scraper import get_earnings_calendar
    _auto_scrape_if_empty(db, days_ahead=days_ahead)
    return {"calendar": get_earnings_calendar(db, days_ahead=days_ahead)}


@router.get("/results")
def recent_results(
    days:      int        = Query(default=30,  ge=1, le=365),
    beat_miss: str | None = Query(default=None),
    limit:     int        = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db_dependency),
):
    from data_supremacy.earnings_scraper import get_recent_results
    return {"results": get_recent_results(db, days=days, beat_miss=beat_miss, limit=limit)}


@router.get("/summary")
def earnings_summary(
    days: int = Query(default=90, ge=1, le=365),
    db: Session = Depends(get_db_dependency),
):
    from data_supremacy.earnings_scraper import get_earnings_summary
    return get_earnings_summary(db, days=days)


@router.post("/scrape")
def trigger_scrape(
    days: int = Query(default=30, ge=1, le=90),
    db: Session = Depends(get_db_dependency),
):
    from data_supremacy.earnings_scraper import scrape_earnings, scrape_board_meetings
    from datetime import date, timedelta
    to_date   = date.today() + timedelta(days=days)
    from_date = date.today() - timedelta(days=30)
    bm = {}
    try:
        bm = scrape_board_meetings(db, days_ahead=days)
    except Exception:
        pass
    result = scrape_earnings(db, from_date=from_date, to_date=to_date)
    result["board_meetings"] = bm
    return result
