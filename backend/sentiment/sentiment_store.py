"""
AQRTI Sentiment Store
Reads and writes SentimentRecord rows to the database.
Provides query helpers for API routes.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from aqrti.database.models import SentimentRecord
from aqrti.utils.logger import get_logger
from sentiment.company_sentiment import SentimentResult

log = get_logger("sentiment_store")


# ══════════════════════════════════════════════════════════════
# WRITE
# ══════════════════════════════════════════════════════════════
def save_sentiment_result(db: Session, result: SentimentResult, source: str = "news") -> int:
    """
    Upsert a SentimentResult into sentiment_records.
    Matches on entity + entity_type + timestamp (hour-truncated) to avoid duplicates.
    Returns the record ID.
    """
    # Truncate to hour for dedup granularity
    ts = result.computed_at.replace(minute=0, second=0, microsecond=0)

    existing = (
        db.query(SentimentRecord)
        .filter(
            SentimentRecord.entity      == result.entity,
            SentimentRecord.entity_type == result.entity_type,
            SentimentRecord.timestamp   == ts,
        )
        .first()
    )

    if existing:
        existing.score        = result.score
        existing.velocity     = result.velocity
        existing.confidence   = result.confidence
        existing.positive     = result.positive_pct / 100.0
        existing.negative     = result.negative_pct / 100.0
        existing.neutral      = result.neutral_pct  / 100.0
        existing.source       = source
        db.commit()
        return existing.id
    else:
        row = SentimentRecord(
            timestamp   = ts,
            entity      = result.entity,
            entity_type = result.entity_type,
            source      = source,
            positive    = result.positive_pct / 100.0,
            negative    = result.negative_pct / 100.0,
            neutral     = result.neutral_pct  / 100.0,
            score       = result.score,
            velocity    = result.velocity,
            confidence  = result.confidence,
        )
        db.add(row)
        db.commit()
        return row.id


def save_all_sentiments(
    db: Session,
    results: dict[str, SentimentResult],
    source: str = "news",
) -> int:
    """Bulk save all SentimentResult values. Returns count saved."""
    count = 0
    for result in results.values():
        save_sentiment_result(db, result, source)
        count += 1
    return count


# ══════════════════════════════════════════════════════════════
# READ — latest record for an entity
# ══════════════════════════════════════════════════════════════
def get_latest_sentiment(
    db: Session,
    entity: str,
    entity_type: str = "stock",
) -> Optional[dict]:
    row = (
        db.query(SentimentRecord)
        .filter_by(entity=entity, entity_type=entity_type)
        .order_by(SentimentRecord.timestamp.desc())
        .first()
    )
    return _row_to_dict(row) if row else None


# ══════════════════════════════════════════════════════════════
# READ — sentiment history for an entity
# ══════════════════════════════════════════════════════════════
def get_sentiment_history(
    db: Session,
    entity: str,
    days: int = 30,
    entity_type: Optional[str] = None,
) -> list[dict]:
    cutoff = datetime.utcnow() - timedelta(days=days)
    q = (
        db.query(SentimentRecord)
        .filter(
            SentimentRecord.entity    == entity,
            SentimentRecord.timestamp >= cutoff,
        )
    )
    if entity_type:
        q = q.filter(SentimentRecord.entity_type == entity_type)
    rows = q.order_by(SentimentRecord.timestamp.asc()).all()
    return [_row_to_dict(r) for r in rows]


# ══════════════════════════════════════════════════════════════
# READ — latest sentiment for all stocks / sectors
# ══════════════════════════════════════════════════════════════
def get_all_latest_sentiments(
    db: Session,
    entity_type: str = "stock",
) -> list[dict]:
    # Subquery: latest timestamp per entity
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
        .join(
            subq,
            (SentimentRecord.entity    == subq.c.entity) &
            (SentimentRecord.timestamp == subq.c.max_ts),
        )
        .all()
    )
    return [_row_to_dict(r) for r in rows]


# ── Helpers ───────────────────────────────────────────────────
def _row_to_dict(row: SentimentRecord) -> dict:
    return {
        "id":           row.id,
        "entity":       row.entity,
        "entity_type":  row.entity_type,
        "timestamp":    row.timestamp.isoformat() if row.timestamp else None,
        "score":        row.score,
        "velocity":     row.velocity,
        "confidence":   row.confidence,
        "positive":     row.positive,
        "negative":     row.negative,
        "neutral":      row.neutral,
        "source":       row.source,
    }
