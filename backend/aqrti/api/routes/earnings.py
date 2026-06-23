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


@router.get("/calendar")
def earnings_calendar(
    days_ahead: int = Query(default=14, ge=1, le=60),
    db: Session = Depends(get_db_dependency),
):
    from data_supremacy.earnings_scraper import get_earnings_calendar
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
    from data_supremacy.earnings_scraper import scrape_earnings
    from datetime import date, timedelta
    to_date   = date.today()
    from_date = to_date - timedelta(days=days)
    return scrape_earnings(db, from_date=from_date, to_date=to_date)
