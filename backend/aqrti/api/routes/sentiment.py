"""Sentiment API — /api/v1/sentiment"""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from aqrti.database.engine import get_db_dependency
from aqrti.database.models import SentimentRecord

router = APIRouter()


def _latest_scores(db: Session, entity_type: str) -> list[dict]:
    """Return latest sentiment score per entity of given type."""
    # Subquery: max timestamp per entity
    from sqlalchemy import func
    subq = (
        db.query(
            SentimentRecord.entity,
            func.max(SentimentRecord.timestamp).label("max_ts"),
        )
        .filter(SentimentRecord.entity_type == entity_type)
        .group_by(SentimentRecord.entity)
        .subquery()
    )
    rows = (
        db.query(SentimentRecord)
        .join(subq, (SentimentRecord.entity == subq.c.entity) &
                    (SentimentRecord.timestamp == subq.c.max_ts))
        .order_by(SentimentRecord.score.desc())
        .all()
    )
    return [
        {
            "entity":    r.entity,
            "score":     r.score,
            "positive":  r.positive,
            "negative":  r.negative,
            "neutral":   r.neutral,
            "velocity":  r.velocity,
            "confidence": r.confidence,
            "timestamp": r.timestamp.isoformat() if r.timestamp else None,
        }
        for r in rows
    ]


@router.get("")
def get_sentiment(db: Session = Depends(get_db_dependency)):
    """Return complete sentiment snapshot: market, companies, sectors."""
    companies = _latest_scores(db, "stock")
    sectors   = _latest_scores(db, "sector")
    market    = _latest_scores(db, "market")

    # Market-level summary
    mkt_score = None
    if companies:
        mkt_score = round(sum(c["score"] for c in companies if c["score"]) / len(companies), 1)

    mkt_label = "Neutral"
    if mkt_score:
        if mkt_score >= 75:
            mkt_label = "Euphoric"
        elif mkt_score >= 60:
            mkt_label = "Optimistic"
        elif mkt_score >= 45:
            mkt_label = "Neutral"
        else:
            mkt_label = "Fear"

    return {
        "market": {
            "label":      mkt_label,
            "score":      mkt_score,
            "fearGreed":  mkt_score,
        },
        "companies": companies,
        "sectors":   sectors,
    }


@router.get("/history/{entity}")
def get_sentiment_history(
    entity: str,
    days: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(get_db_dependency),
):
    cutoff = datetime.utcnow() - timedelta(days=days)
    rows = (
        db.query(SentimentRecord)
        .filter(
            SentimentRecord.entity == entity.upper(),
            SentimentRecord.timestamp >= cutoff,
        )
        .order_by(SentimentRecord.timestamp.asc())
        .all()
    )
    return [
        {
            "timestamp": r.timestamp.isoformat(),
            "score":     r.score,
            "velocity":  r.velocity,
        }
        for r in rows
    ]
