"""Vault API — /api/v1/vault  (market snapshots, summary, trigger)"""

from __future__ import annotations

import sys, os

backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from aqrti.database.engine import get_db_dependency
from aqrti.database.models import MarketSnapshot

router = APIRouter()


@router.get("/summary")
def vault_summary(db: Session = Depends(get_db_dependency)):
    from vault.vault_manager import get_vault_summary
    return get_vault_summary(db)


@router.get("/snapshots")
def list_snapshots(
    days:  int = Query(default=30, ge=1, le=365),
    db: Session = Depends(get_db_dependency),
):
    from vault.snapshot_manager import get_snapshot_range
    end   = date.today()
    start = end - timedelta(days=days)
    return {"snapshots": get_snapshot_range(db, start, end)}


@router.get("/snapshots/{snapshot_date}")
def get_snapshot(snapshot_date: str, db: Session = Depends(get_db_dependency)):
    from vault.snapshot_manager import get_snapshot
    from fastapi import HTTPException
    try:
        d = date.fromisoformat(snapshot_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")
    snap = get_snapshot(db, d)
    if not snap:
        raise HTTPException(status_code=404, detail=f"No snapshot for {snapshot_date}")
    return snap


@router.post("/archive-today")
def trigger_archive(db: Session = Depends(get_db_dependency)):
    from vault.vault_manager import run_daily_vault
    return run_daily_vault(date.today())
