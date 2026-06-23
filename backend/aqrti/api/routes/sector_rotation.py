"""Sector Rotation API — /api/v1/sector-rotation"""

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
    from data_supremacy.sector_rotation import get_sector_rotation_latest
    return {"sectors": get_sector_rotation_latest(db)}


@router.get("/history/{sector}")
def get_sector_history(
    sector: str,
    days:   int = Query(default=60, ge=1, le=365),
    db: Session = Depends(get_db_dependency),
):
    from data_supremacy.sector_rotation import get_sector_history
    return {"sector": sector, "history": get_sector_history(db, sector=sector, days=days)}


@router.post("/compute")
def trigger_compute(db: Session = Depends(get_db_dependency)):
    from data_supremacy.sector_rotation import compute_sector_rotation
    return compute_sector_rotation(db)
