"""Data Quality API — /api/v1/data-quality"""

from __future__ import annotations

import sys, os

backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from datetime import date
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from aqrti.database.engine import get_db_dependency
from aqrti.database.models import DataSourceHealth

router = APIRouter()


@router.get("")
def quality_dashboard(
    days: int = Query(default=7, ge=1, le=30),
    db: Session = Depends(get_db_dependency),
):
    from data_supremacy.quality_engine import get_quality_dashboard
    return get_quality_dashboard(db, days=days)


@router.get("/source-health")
def source_health(db: Session = Depends(get_db_dependency)):
    today = date.today()
    rows = db.query(DataSourceHealth).filter(
        DataSourceHealth.check_date == today
    ).order_by(DataSourceHealth.source_name).all()
    if not rows:
        # Return last known
        rows = db.query(DataSourceHealth).order_by(
            DataSourceHealth.check_date.desc(), DataSourceHealth.source_name
        ).limit(20).all()
    return {
        "sources": [
            {
                "source_name":         r.source_name,
                "check_date":          str(r.check_date),
                "status":              r.status,
                "records_fetched":     r.records_fetched,
                "fetch_duration_ms":   r.fetch_duration_ms,
                "consecutive_failures":r.consecutive_failures,
                "last_success_at":     r.last_success_at.isoformat() if r.last_success_at else None,
                "error_message":       r.error_message,
            }
            for r in rows
        ]
    }


@router.post("/run-checks")
def run_checks(db: Session = Depends(get_db_dependency)):
    from data_supremacy.quality_engine import run_quality_checks
    return run_quality_checks(db)


@router.post("/run-pipeline")
def run_pipeline():
    from data_supremacy.pipeline import run_data_supremacy_pipeline
    return run_data_supremacy_pipeline()
