"""News Intelligence API — /api/v1/news"""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from aqrti.database.engine import get_db_dependency
from aqrti.database.models import NewsEvent

router = APIRouter()


@router.get("")
def get_news(
    hours: int   = Query(default=24, ge=1, le=168),
    company: str = Query(default=""),
    min_impact: float = Query(default=0.0, ge=0, le=100),
    limit: int   = Query(default=50, ge=1, le=200),
    db: Session  = Depends(get_db_dependency),
):
    """Return news events sorted by importance score descending."""
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    q = (
        db.query(NewsEvent)
        .filter(NewsEvent.timestamp >= cutoff)
    )
    if company:
        q = q.filter(NewsEvent.company == company.upper())
    if min_impact > 0:
        q = q.filter(NewsEvent.impact_score >= min_impact)

    events = q.order_by(NewsEvent.importance_score.desc()).limit(limit).all()

    return [
        {
            "id":              e.id,
            "headline":        e.headline,
            "summary":         e.summary,
            "company":         e.company,
            "sector":          e.sector,
            "source":          e.source,
            "timestamp":       e.timestamp.isoformat() if e.timestamp else None,
            "sentiment":       e.sentiment,
            "sentimentScore":  e.sentiment_score,
            "impactScore":     e.impact_score,
            "importanceScore": e.importance_score,
            "eventType":       e.event_type,
        }
        for e in events
    ]


@router.get("/stats")
def get_news_stats(
    hours: int = Query(default=24, ge=1, le=168),
    db: Session = Depends(get_db_dependency),
):
    """Return aggregate news stats for a time window."""
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    events = db.query(NewsEvent).filter(NewsEvent.timestamp >= cutoff).all()

    total = len(events)
    high_impact = sum(1 for e in events if (e.impact_score or 0) >= 70)
    positive    = sum(1 for e in events if e.sentiment == "positive")
    negative    = sum(1 for e in events if e.sentiment == "negative")
    entities    = len(set(e.company for e in events if e.company))

    avg_sentiment = None
    scores = [e.sentiment_score for e in events if e.sentiment_score is not None]
    if scores:
        avg_sentiment = round(sum(scores) / len(scores), 3)

    return {
        "totalArticles":   total,
        "highImpact":      high_impact,
        "positiveCount":   positive,
        "negativeCount":   negative,
        "entitiesTracked": entities,
        "avgSentiment":    avg_sentiment,
        "window_hours":    hours,
    }
