"""FII/DII Flow API — /api/v1/fii-dii"""

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
def get_fii_dii(
    days: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(get_db_dependency),
):
    from data_supremacy.fii_dii_scraper import get_fii_dii_latest
    return get_fii_dii_latest(db, days=days)


@router.post("/scrape")
def trigger_scrape(db: Session = Depends(get_db_dependency)):
    from data_supremacy.fii_dii_scraper import scrape_fii_dii
    return scrape_fii_dii(db)
