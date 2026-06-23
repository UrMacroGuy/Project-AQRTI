"""Vault Export API — /api/v1/vault-export  (JSON/CSV file downloads)"""

from __future__ import annotations

import sys, os

backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse, Response
from fastapi import HTTPException
from sqlalchemy.orm import Session

from aqrti.database.engine import get_db_dependency

router = APIRouter()


@router.get("/snapshots.json")
def export_snapshots_json(
    days: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(get_db_dependency),
):
    from vault.exporters import export_snapshots_json
    end   = date.today()
    start = end - timedelta(days=days)
    content = export_snapshots_json(db, start, end)
    return Response(content=content, media_type="application/json",
                    headers={"Content-Disposition": f"attachment; filename=aqrti_snapshots_{start}_{end}.json"})


@router.get("/snapshots.csv")
def export_snapshots_csv(
    days: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(get_db_dependency),
):
    from vault.exporters import export_snapshots_csv
    end   = date.today()
    start = end - timedelta(days=days)
    content = export_snapshots_csv(db, start, end)
    return Response(content=content, media_type="text/csv",
                    headers={"Content-Disposition": f"attachment; filename=aqrti_snapshots_{start}_{end}.csv"})


@router.get("/predictions.json")
def export_predictions_json(
    days: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(get_db_dependency),
):
    from vault.exporters import export_predictions_json
    end   = date.today()
    start = end - timedelta(days=days)
    content = export_predictions_json(db, start, end)
    return Response(content=content, media_type="application/json",
                    headers={"Content-Disposition": f"attachment; filename=aqrti_predictions_{start}_{end}.json"})


@router.get("/predictions.csv")
def export_predictions_csv(
    days: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(get_db_dependency),
):
    from vault.exporters import export_predictions_csv
    end   = date.today()
    start = end - timedelta(days=days)
    content = export_predictions_csv(db, start, end)
    return Response(content=content, media_type="text/csv",
                    headers={"Content-Disposition": f"attachment; filename=aqrti_predictions_{start}_{end}.csv"})


@router.get("/portfolio.csv")
def export_portfolio_csv(
    days: int = Query(default=90, ge=1, le=365),
    db: Session = Depends(get_db_dependency),
):
    from vault.exporters import export_portfolio_csv
    end   = date.today()
    start = end - timedelta(days=days)
    content = export_portfolio_csv(db, start, end)
    return Response(content=content, media_type="text/csv",
                    headers={"Content-Disposition": f"attachment; filename=aqrti_portfolio_{start}_{end}.csv"})
