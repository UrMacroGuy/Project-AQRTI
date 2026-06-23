"""
AQRTI Company Sentiment
Computes per-symbol sentiment score from news events stored in the DB.

Algorithm:
  1. Fetch news events for the symbol from the last `window_days` days
  2. Weight each event by: recency_weight × impact_score
  3. Compute weighted avg of sentiment_score (mapped to 0-100)
  4. Compute velocity: (3-day avg score - 7-day avg score) / 7-day avg score
  5. Compute acceleration: velocity_today vs velocity_yesterday
  6. Confidence: function of event count + impact avg
  7. Returns SentimentResult dataclass
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from aqrti.database.models import NewsEvent
from aqrti.utils.logger import get_logger

log = get_logger("company_sentiment")

WINDOW_DAYS = 7
SHORT_WINDOW = 3


@dataclass
class SentimentResult:
    entity:         str
    entity_type:    str      # 'stock' | 'sector' | 'market'
    score:          float    # 0-100
    velocity:       float    # rate of change, signed
    acceleration:   float    # change in velocity
    confidence:     float    # 0-100
    news_count:     int
    positive_pct:   float
    negative_pct:   float
    neutral_pct:    float
    computed_at:    datetime


def compute_company_sentiment(db: Session, symbol: str) -> Optional[SentimentResult]:
    """
    Compute sentiment for a single stock symbol.
    Returns None if there is insufficient news data.
    """
    cutoff = datetime.utcnow() - timedelta(days=WINDOW_DAYS)

    rows = (
        db.query(NewsEvent)
        .filter(
            NewsEvent.company == symbol,
            NewsEvent.timestamp >= cutoff,
            NewsEvent.sentiment_score.isnot(None),
            NewsEvent.impact_score.isnot(None),
        )
        .order_by(NewsEvent.timestamp.desc())
        .all()
    )

    if not rows:
        return None

    now = datetime.utcnow()

    # Compute recency-weighted and impact-weighted sentiment
    weighted_scores: list[tuple[float, float]] = []  # (score_0_100, weight)
    positive = negative = neutral = 0

    for row in rows:
        age_hours = (now - row.timestamp).total_seconds() / 3600
        recency_w = math.exp(-age_hours / (WINDOW_DAYS * 24 / 2))  # half-life = window/2
        impact_w  = (row.impact_score or 0) / 100.0
        weight    = recency_w * (0.5 + 0.5 * impact_w)  # floor at 50% even without impact

        # Map sentiment_score (-1 to +1) → (0 to 100)
        score_0_100 = (row.sentiment_score + 1.0) / 2.0 * 100.0
        weighted_scores.append((score_0_100, weight))

        label = (row.sentiment or "neutral").lower()
        if label == "positive":
            positive += 1
        elif label == "negative":
            negative += 1
        else:
            neutral += 1

    total_weight = sum(w for _, w in weighted_scores)
    if total_weight == 0:
        return None

    current_score = sum(s * w for s, w in weighted_scores) / total_weight

    # Short-window score (3d) for velocity
    short_cutoff = now - timedelta(days=SHORT_WINDOW)
    short_rows   = [r for r in rows if r.timestamp >= short_cutoff]
    if short_rows:
        short_sum = sum((r.sentiment_score + 1.0) / 2.0 * 100.0 for r in short_rows)
        short_score = short_sum / len(short_rows)
    else:
        short_score = current_score

    velocity = _safe_velocity(short_score, current_score)

    # Acceleration: compare velocity to prior window velocity
    # Proxy: use 5d score as "yesterday's" velocity anchor
    prior_cutoff = now - timedelta(days=5)
    prior_rows   = [r for r in rows if r.timestamp >= prior_cutoff]
    prior_score  = (sum((r.sentiment_score + 1.0) / 2.0 * 100.0 for r in prior_rows) /
                    len(prior_rows)) if prior_rows else current_score
    prior_velocity = _safe_velocity(short_score, prior_score)
    acceleration   = velocity - prior_velocity

    # Confidence: based on event count + average impact
    avg_impact = sum(r.impact_score or 0 for r in rows) / len(rows)
    count_factor = min(1.0, len(rows) / 10.0)  # saturates at 10 events
    confidence   = (count_factor * 0.6 + (avg_impact / 100.0) * 0.4) * 100.0

    n = len(rows)
    return SentimentResult(
        entity       = symbol,
        entity_type  = "stock",
        score        = round(current_score, 2),
        velocity     = round(velocity, 4),
        acceleration = round(acceleration, 4),
        confidence   = round(confidence, 2),
        news_count   = n,
        positive_pct = round(positive / n * 100, 1),
        negative_pct = round(negative / n * 100, 1),
        neutral_pct  = round(neutral  / n * 100, 1),
        computed_at  = now,
    )


def compute_all_company_sentiments(
    db: Session,
    symbols: list[str],
) -> dict[str, SentimentResult]:
    """Compute and return sentiment for all given symbols."""
    results: dict[str, SentimentResult] = {}
    for sym in symbols:
        result = compute_company_sentiment(db, sym)
        if result is not None:
            results[sym] = result
    return results


# ── Helpers ───────────────────────────────────────────────────
def _safe_velocity(short: float, full: float) -> float:
    if full == 0:
        return 0.0
    return (short - full) / max(abs(full), 1.0)
