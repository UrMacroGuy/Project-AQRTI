"""
Knowledge Store
Persistent institutional memory layer.

Records every notable event AQRTI observes:
  prediction outcomes, trade results, regime transitions,
  pattern outcomes, model changes, failure resolutions.

Every write goes through record_event() which normalises and stores
to knowledge_events. Retrieval helpers power the dashboard and scoring.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from aqrti.database.models import KnowledgeEvent
from aqrti.utils.logger import get_logger

log = get_logger("knowledge_store")

# ── Event categories ───────────────────────────────────────────
CAT_PREDICTION  = "prediction"
CAT_TRADE       = "trade"
CAT_FAILURE     = "failure"
CAT_SUCCESS     = "success"
CAT_REGIME      = "regime"
CAT_PATTERN     = "pattern"
CAT_MODEL       = "model"
CAT_FEATURE     = "feature"


def record_event(
    db:            Session,
    category:      str,
    event_type:    str,
    description:   str,
    outcome:       str  = "neutral",       # positive|negative|neutral
    magnitude:     float = 0.0,
    symbol:        Optional[str] = None,
    confidence_at: Optional[float] = None,
    actual_result: Optional[float] = None,
    regime:        Optional[str]  = None,
    metadata:      Optional[dict] = None,
    event_date:    Optional[date] = None,
) -> KnowledgeEvent:
    """Write one knowledge event row."""
    row = KnowledgeEvent(
        event_date    = event_date or date.today(),
        category      = category,
        symbol        = symbol,
        event_type    = event_type,
        description   = description,
        outcome       = outcome,
        magnitude     = magnitude,
        confidence_at = confidence_at,
        actual_result = actual_result,
        regime        = regime,
        metadata_json = json.dumps(metadata) if metadata else None,
    )
    db.add(row)
    db.flush()
    return row


def get_recent_events(
    db:       Session,
    days:     int = 30,
    category: Optional[str] = None,
    symbol:   Optional[str] = None,
    limit:    int = 200,
) -> list[dict]:
    cutoff = date.today() - timedelta(days=days)
    q = db.query(KnowledgeEvent).filter(KnowledgeEvent.event_date >= cutoff)
    if category:
        q = q.filter(KnowledgeEvent.category == category)
    if symbol:
        q = q.filter(KnowledgeEvent.symbol == symbol)
    rows = q.order_by(KnowledgeEvent.event_date.desc()).limit(limit).all()
    return [_event_to_dict(r) for r in rows]


def get_event_counts(db: Session, days: int = 30) -> dict:
    """Summary counts by category and outcome."""
    cutoff = date.today() - timedelta(days=days)
    rows   = (
        db.query(KnowledgeEvent)
        .filter(KnowledgeEvent.event_date >= cutoff)
        .all()
    )
    cats    = {}
    outcomes = {"positive": 0, "negative": 0, "neutral": 0}
    for r in rows:
        cats[r.category] = cats.get(r.category, 0) + 1
        key = r.outcome or "neutral"
        outcomes[key] = outcomes.get(key, 0) + 1
    return {
        "total":       len(rows),
        "by_category": cats,
        "by_outcome":  outcomes,
        "days":        days,
    }


def _event_to_dict(r: KnowledgeEvent) -> dict:
    return {
        "id":           r.id,
        "date":         str(r.event_date),
        "category":     r.category,
        "symbol":       r.symbol,
        "eventType":    r.event_type,
        "description":  r.description,
        "outcome":      r.outcome,
        "magnitude":    r.magnitude,
        "confidenceAt": r.confidence_at,
        "actualResult": r.actual_result,
        "regime":       r.regime,
    }
