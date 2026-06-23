"""
Patterns API — /api/v1/patterns
Returns pattern similarity search results.
"""

from __future__ import annotations

import json
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from aqrti.database.engine import get_db_dependency
from aqrti.database.models import PatternMatch

router = APIRouter()


@router.get("")
def get_patterns(
    min_confidence: float   = Query(default=0.0, ge=0, le=1),
    limit:          int     = Query(default=20, ge=1, le=100),
    db:             Session = Depends(get_db_dependency),
):
    """All pattern matches from the latest run."""
    cutoff = date.today() - timedelta(days=7)
    rows = (
        db.query(PatternMatch)
        .filter(
            PatternMatch.search_date         >= cutoff,
            PatternMatch.pattern_confidence  >= min_confidence,
        )
        .order_by(PatternMatch.pattern_confidence.desc())
        .limit(limit)
        .all()
    )

    return [_serialize_pattern(r) for r in rows]


@router.get("/symbol/{symbol}")
def get_symbol_pattern(
    symbol: str,
    db:     Session = Depends(get_db_dependency),
):
    """Most recent pattern match for a specific symbol."""
    row = (
        db.query(PatternMatch)
        .filter_by(symbol=symbol)
        .order_by(PatternMatch.search_date.desc())
        .first()
    )
    if not row:
        return {"symbol": symbol, "available": False}
    return _serialize_pattern(row)


def _serialize_pattern(row: PatternMatch) -> dict:
    return {
        "symbol":            row.symbol,
        "searchDate":        str(row.search_date),
        "expectedReturn":    row.expected_return,
        "winRate":           row.win_rate,
        "outperformRate":    row.outperform_rate,
        "patternConfidence": row.pattern_confidence,
        "sampleSize":        row.sample_size,
        "similarSituations": json.loads(row.similar_situations or "[]"),
        "computedAt":        str(row.computed_at),
    }
