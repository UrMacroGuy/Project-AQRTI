"""
AQRTI Impact Scoring
Computes two scores for each news event (0-100):

  importance_score — how significant is this news in general?
                     (source credibility × event type weight × recency)

  impact_score     — how much market impact is expected?
                     (event type × sentiment direction × entity significance)

  sentiment_score  — directional signal (-1.0 to +1.0)
  sentiment_label  — 'positive' | 'negative' | 'neutral'

All scores are deterministic (no ML) and fully explainable.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

from news.event_classifier import EventType
from news.news_collector   import SOURCE_WEIGHTS


# ══════════════════════════════════════════════════════════════
# EVENT TYPE WEIGHTS
# Base importance of each event type for market impact (0-1)
# ══════════════════════════════════════════════════════════════
EVENT_IMPORTANCE: dict[str, float] = {
    EventType.EARNINGS.value:          0.90,
    EventType.ACQUISITION.value:       0.85,
    EventType.MERGER.value:            0.85,
    EventType.BUYBACK.value:           0.75,
    EventType.REGULATORY_ACTION.value: 0.80,
    EventType.LARGE_ORDER.value:       0.80,
    EventType.DIVIDEND.value:          0.60,
    EventType.MANAGEMENT_CHANGE.value: 0.65,
    EventType.LEGAL_EVENT.value:       0.70,
    EventType.GENERAL.value:           0.30,
}

# Expected market IMPACT of each event type (can differ from importance)
EVENT_IMPACT: dict[str, float] = {
    EventType.EARNINGS.value:          0.95,
    EventType.ACQUISITION.value:       0.90,
    EventType.MERGER.value:            0.90,
    EventType.BUYBACK.value:           0.70,
    EventType.REGULATORY_ACTION.value: 0.85,
    EventType.LARGE_ORDER.value:       0.75,
    EventType.DIVIDEND.value:          0.50,
    EventType.MANAGEMENT_CHANGE.value: 0.60,
    EventType.LEGAL_EVENT.value:       0.65,
    EventType.GENERAL.value:           0.20,
}


# ══════════════════════════════════════════════════════════════
# SENTIMENT LEXICON
# Positive / negative signal words with weights
# ══════════════════════════════════════════════════════════════
_POSITIVE_SIGNALS: list[tuple[str, float]] = [
    (r"\b(surges?|soars?|jumps?|rallies?|spikes?|skyrockets?)\b",          0.9),
    (r"\b(rises?|gains?|advances?|climbs?|up|higher|upside)\b",            0.6),
    (r"\b(beat|beats|outperform|exceed|record\s+high|all.?time\s+high)\b", 0.8),
    (r"\b(strong\s+result|robust\s+growth|profit\s+jumps?|order\s+win)\b", 0.85),
    (r"\b(dividend|buyback|bonus|expansion|acquisition)\b",                 0.5),
    (r"\b(positive|bullish|optimistic|upgrade|buy\s+rating)\b",            0.7),
    (r"\b(approves?|clears?|approved?)\b",                                  0.55),
]

_NEGATIVE_SIGNALS: list[tuple[str, float]] = [
    (r"\b(plunges?|crashes?|tanks?|collapses?|slumps?|tumbles?)\b",        0.9),
    (r"\b(falls?|drops?|declines?|slips?|down|lower|downside)\b",          0.6),
    (r"\b(miss|misses|disappoints?|below\s+estimate|profit\s+falls?)\b",   0.85),
    (r"\b(loss|write.?down|impairment|default|warning|caution)\b",         0.8),
    (r"\b(penalty|fine|penali[sz]|sebi\s+action|rbi\s+ban)\b",             0.9),
    (r"\b(negative|bearish|pessimistic|downgrade|sell\s+rating)\b",        0.7),
    (r"\b(rejects?|rejected|denied?|litigation|lawsuit|probe)\b",           0.75),
    (r"\b(resign|quits?|steps?\s+down|sudden\s+departure)\b",              0.6),
]

# Quantitative magnitude boosters (%, ₹, crore etc.)
_MAGNITUDE_RE = re.compile(
    r"\b(\d+\.?\d*)\s*(%|percent|crore|cr|billion|mn|million)\b",
    re.IGNORECASE,
)


# ══════════════════════════════════════════════════════════════
# RECENCY DECAY
# news < 2h: 1.0, < 6h: 0.85, < 24h: 0.70, < 48h: 0.50, older: 0.30
# ══════════════════════════════════════════════════════════════
def _recency_factor(published_at: datetime) -> float:
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)
    age_hours = (datetime.now(tz=timezone.utc) - published_at).total_seconds() / 3600
    if age_hours < 2:
        return 1.00
    elif age_hours < 6:
        return 0.85
    elif age_hours < 24:
        return 0.70
    elif age_hours < 48:
        return 0.50
    else:
        return 0.30


# ══════════════════════════════════════════════════════════════
# SENTIMENT SCORING
# ══════════════════════════════════════════════════════════════
def _compute_raw_sentiment(text: str) -> tuple[float, str]:
    """
    Returns (score, label) where score ∈ [-1.0, 1.0].
    label ∈ 'positive' | 'negative' | 'neutral'
    """
    pos_score = 0.0
    neg_score = 0.0
    text_lower = text.lower()

    for pattern, weight in _POSITIVE_SIGNALS:
        matches = re.findall(pattern, text_lower, re.IGNORECASE)
        pos_score += len(matches) * weight

    for pattern, weight in _NEGATIVE_SIGNALS:
        matches = re.findall(pattern, text_lower, re.IGNORECASE)
        neg_score += len(matches) * weight

    # Magnitude boost
    magnitudes = _MAGNITUDE_RE.findall(text)
    if magnitudes:
        boost = min(0.2, len(magnitudes) * 0.05)
        if pos_score > neg_score:
            pos_score += boost
        elif neg_score > pos_score:
            neg_score += boost

    total = pos_score + neg_score
    if total == 0:
        return 0.0, "neutral"

    # Normalise to [-1, 1]
    raw = (pos_score - neg_score) / max(total, 1.0)
    raw = max(-1.0, min(1.0, raw))

    if raw > 0.1:
        return raw, "positive"
    elif raw < -0.1:
        return raw, "negative"
    else:
        return raw, "neutral"


# ══════════════════════════════════════════════════════════════
# MAIN SCORING FUNCTION
# ══════════════════════════════════════════════════════════════
def compute_impact_scores(
    headline: str,
    summary: Optional[str],
    event_type: str,
    source: str,
    published_at: datetime,
    primary_symbol: Optional[str] = None,
) -> dict:
    """
    Returns:
      {
        importance_score: float (0-100),
        impact_score:     float (0-100),
        sentiment_score:  float (-1 to 1),
        sentiment_label:  str,
        score_components: dict   (for explainability)
      }
    """
    text = headline + " " + (summary or "")

    # ── Source credibility ────────────────────────────────────
    source_weight = SOURCE_WEIGHTS.get(source.lower(), 0.5)

    # ── Recency ───────────────────────────────────────────────
    recency = _recency_factor(published_at)

    # ── Event type weights ────────────────────────────────────
    evt_imp    = EVENT_IMPORTANCE.get(event_type, 0.30)
    evt_impact = EVENT_IMPACT.get(event_type, 0.20)

    # ── Sentiment ─────────────────────────────────────────────
    sent_score, sent_label = _compute_raw_sentiment(text)
    sentiment_magnitude    = abs(sent_score)

    # ── Importance Score ─────────────────────────────────────
    # Weighted combination: event type × source × recency, boosted by sentiment magnitude
    raw_importance = (
        evt_imp * 0.45 +
        source_weight * 0.30 +
        recency * 0.15 +
        sentiment_magnitude * 0.10
    )
    importance_score = round(min(100.0, raw_importance * 100), 1)

    # ── Impact Score ─────────────────────────────────────────
    # Event impact × recency × sentiment direction weight
    sent_weight = 0.5 + 0.5 * sentiment_magnitude
    raw_impact = (
        evt_impact * 0.50 +
        recency * 0.20 +
        source_weight * 0.15 +
        sent_weight * 0.15
    )
    impact_score = round(min(100.0, raw_impact * 100), 1)

    return {
        "importance_score": importance_score,
        "impact_score":     impact_score,
        "sentiment_score":  round(sent_score, 4),
        "sentiment_label":  sent_label,
        "score_components": {
            "source_weight":        round(source_weight, 3),
            "recency_factor":       round(recency, 3),
            "event_importance_wt":  round(evt_imp, 3),
            "event_impact_wt":      round(evt_impact, 3),
            "sentiment_magnitude":  round(sentiment_magnitude, 3),
        },
    }
