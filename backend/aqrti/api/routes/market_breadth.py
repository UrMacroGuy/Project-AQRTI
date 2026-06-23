"""Market Breadth API — /api/v1/market-breadth"""

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
def get_latest(db: Session = Depends(get_db_dependency)):
    from data_supremacy.breadth_engine import get_breadth_latest
    result = get_breadth_latest(db)
    if not result:
        return {"status": "no_data"}
    return result


@router.get("/history")
def get_history(
    days: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(get_db_dependency),
):
    from data_supremacy.breadth_engine import get_breadth_history
    return {"history": get_breadth_history(db, days=days)}


@router.post("/compute")
def trigger_compute(db: Session = Depends(get_db_dependency)):
    from data_supremacy.breadth_engine import compute_breadth
    return compute_breadth(db)
