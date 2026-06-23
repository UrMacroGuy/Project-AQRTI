"""Failures API — /api/v1/failures"""

from __future__ import annotations

import sys, os
backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from aqrti.database.engine import get_db_dependency
from aqrti.database.models import FailureRecord

router = APIRouter()


@router.get("")
def get_failures(
    days:     int = Query(default=30, ge=1, le=365),
    category: str = Query(default=None),
    severity: str = Query(default=None),
    symbol:   str = Query(default=None),
    limit:    int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db_dependency),
):
    cutoff = date.today() - timedelta(days=days)
    q      = db.query(FailureRecord).filter(FailureRecord.failure_date >= cutoff)
    if category:
        q = q.filter(FailureRecord.failure_category == category)
    if severity:
        q = q.filter(FailureRecord.severity == severity)
    if symbol:
        q = q.filter(FailureRecord.symbol == symbol)

    rows = q.order_by(FailureRecord.failure_date.desc()).limit(limit).all()

    return {
        "failures": [
            {
                "id":                 f.id,
                "date":               str(f.failure_date),
                "symbol":             f.symbol,
                "category":           f.failure_category,
                "type":               f.failure_type,
                "severity":           f.severity,
                "predictedValue":     f.predicted_value,
                "actualValue":        f.actual_value,
                "confidenceAt":       f.confidence_at,
                "regimeAt":           f.regime_at,
                "rootCause":          f.root_cause,
                "contributingFactors": f.contributing_factors,
                "lesson":             f.lesson,
                "resolved":           f.resolved,
                "predictionId":       f.prediction_id,
                "tradeId":            f.trade_id,
            }
            for f in rows
        ],
        "total": len(rows),
        "days":  days,
    }


@router.get("/summary")
def get_failure_summary(
    days: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(get_db_dependency),
):
    cutoff   = date.today() - timedelta(days=days)
    failures = db.query(FailureRecord).filter(FailureRecord.failure_date >= cutoff).all()

    by_cat: dict = {}
    by_sev: dict = {}
    timeline: dict = {}

    for f in failures:
        by_cat[f.failure_category or "unknown"] = by_cat.get(f.failure_category or "unknown", 0) + 1
        by_sev[f.severity or "medium"] = by_sev.get(f.severity or "medium", 0) + 1
        day = str(f.failure_date)
        timeline[day] = timeline.get(day, 0) + 1

    return {
        "total":        len(failures),
        "resolved":     sum(1 for f in failures if f.resolved),
        "critical":     sum(1 for f in failures if f.severity == "critical"),
        "byCategory":   by_cat,
        "bySeverity":   by_sev,
        "timeline":     [{"date": d, "count": c} for d, c in sorted(timeline.items())],
        "days":         days,
    }


@router.patch("/{failure_id}/resolve")
def resolve_failure(
    failure_id: int,
    db: Session = Depends(get_db_dependency),
):
    row = db.query(FailureRecord).filter(FailureRecord.id == failure_id).first()
    if not row:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Failure not found")
    row.resolved = True
    db.commit()
    return {"id": failure_id, "resolved": True}
