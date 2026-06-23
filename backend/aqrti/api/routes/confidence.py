"""
Confidence API — /api/v1/confidence
Returns confidence scores and their component breakdowns.
"""

from __future__ import annotations

import json
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from aqrti.database.engine import get_db_dependency
from aqrti.database.models import ConfidenceHistory

router = APIRouter()


@router.get("")
def get_confidence_scores(
    min_score: float   = Query(default=0.0, ge=0, le=100),
    category:  str     = Query(default="all"),
    limit:     int     = Query(default=20, ge=1, le=100),
    db:        Session = Depends(get_db_dependency),
):
    """All confidence scores from the latest prediction run."""
    cutoff = date.today() - timedelta(days=7)
    q = (
        db.query(ConfidenceHistory)
        .filter(
            ConfidenceHistory.prediction_date >= cutoff,
            ConfidenceHistory.confidence_score >= min_score,
        )
        .order_by(ConfidenceHistory.confidence_score.desc())
    )
    if category != "all":
        q = q.filter(ConfidenceHistory.confidence_category == category)

    rows = q.limit(limit).all()

    return [
        {
            "symbol":    r.symbol,
            "date":      str(r.prediction_date),
            "score":     r.confidence_score,
            "category":  r.confidence_category,
            "components": json.loads(r.component_scores_json or "{}"),
        }
        for r in rows
    ]


@router.get("/symbol/{symbol}")
def get_symbol_confidence(
    symbol: str,
    days:   int     = Query(default=30, ge=1, le=365),
    db:     Session = Depends(get_db_dependency),
):
    """Confidence history for a single symbol."""
    cutoff = date.today() - timedelta(days=days)
    rows = (
        db.query(ConfidenceHistory)
        .filter(
            ConfidenceHistory.symbol          == symbol,
            ConfidenceHistory.prediction_date >= cutoff,
        )
        .order_by(ConfidenceHistory.prediction_date.asc())
        .all()
    )
    return [
        {
            "date":       str(r.prediction_date),
            "score":      r.confidence_score,
            "category":   r.confidence_category,
            "components": json.loads(r.component_scores_json or "{}"),
        }
        for r in rows
    ]


@router.get("/distribution")
def get_confidence_distribution(db: Session = Depends(get_db_dependency)):
    """Count of predictions per confidence category today."""
    cutoff = date.today() - timedelta(days=7)
    rows = (
        db.query(ConfidenceHistory.confidence_category)
        .filter(ConfidenceHistory.prediction_date >= cutoff)
        .all()
    )
    distribution = {}
    for (cat,) in rows:
        distribution[cat or "Unknown"] = distribution.get(cat or "Unknown", 0) + 1
    return distribution
