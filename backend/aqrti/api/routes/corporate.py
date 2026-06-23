"""Corporate Filings API — /api/v1/corporate"""

from __future__ import annotations

import sys, os

backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from aqrti.database.engine import get_db_dependency

router = APIRouter()


@router.get("")
def list_filings(
    days:        int        = Query(default=7,   ge=1, le=365),
    symbol:      str | None = Query(default=None),
    filing_type: str | None = Query(default=None),
    limit:       int        = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db_dependency),
):
    from data_supremacy.corporate_scraper import get_recent_filings
    return {"filings": get_recent_filings(db, days=days, symbol=symbol,
                                          filing_type=filing_type, limit=limit)}


@router.get("/summary")
def filing_summary(
    days: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(get_db_dependency),
):
    from data_supremacy.corporate_scraper import get_filing_summary
    return get_filing_summary(db, days=days)


@router.post("/scrape")
def trigger_scrape(
    days: int = Query(default=7, ge=1, le=30),
    db: Session = Depends(get_db_dependency),
):
    from data_supremacy.corporate_scraper import scrape_corporate_actions
    from datetime import date, timedelta
    to_date   = date.today()
    from_date = to_date - timedelta(days=days)
    return scrape_corporate_actions(db, from_date=from_date, to_date=to_date)


@router.post("/backfill")
def trigger_backfill(
    days: int = Query(default=365, ge=30, le=730),
    db: Session = Depends(get_db_dependency),
):
    from data_supremacy.corporate_scraper import backfill_corporate
    return backfill_corporate(db, days=days)
