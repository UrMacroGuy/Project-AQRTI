"""Options Intelligence API — /api/v1/options-intelligence"""

from __future__ import annotations

import sys, os

backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from aqrti.database.engine import get_db_dependency

router = APIRouter()


@router.get("")
def get_snapshot(
    symbol: str = Query(default="NIFTY"),
    db: Session = Depends(get_db_dependency),
):
    from data_supremacy.options_scraper import get_options_snapshot
    snap = get_options_snapshot(db, symbol=symbol)
    if not snap:
        return {"status": "no_data", "symbol": symbol}
    return snap


@router.get("/history")
def get_history(
    symbol: str = Query(default="NIFTY"),
    days:   int = Query(default=30, ge=1, le=365),
    db: Session = Depends(get_db_dependency),
):
    from data_supremacy.options_scraper import get_options_history
    return {"symbol": symbol, "history": get_options_history(db, symbol=symbol, days=days)}


@router.post("/scrape")
def trigger_scrape(
    symbol:   str  = Query(default="NIFTY"),
    is_index: bool = Query(default=True),
    db: Session = Depends(get_db_dependency),
):
    from data_supremacy.options_scraper import scrape_option_chain
    return scrape_option_chain(db, symbol=symbol, is_index=is_index)


@router.post("/scrape-all")
def trigger_scrape_all(db: Session = Depends(get_db_dependency)):
    from data_supremacy.options_scraper import scrape_all_options
    return scrape_all_options(db)
