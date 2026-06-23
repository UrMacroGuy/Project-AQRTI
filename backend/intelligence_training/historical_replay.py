"""
AQRTI Historical Replay Engine — Phase 8.5A
Reconstructs the market exactly as it existed at any point in time.
No future data leakage guarantee: all queries are bounded by replay_date.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from aqrti.database.engine import get_session_factory
from aqrti.utils.logger import get_logger

logger = get_logger("historical_replay")


@dataclass
class ReplaySnapshot:
    """Complete market state at a specific moment — guaranteed no-future-leakage."""
    replay_date: date
    replay_scope: str  # day|week|month|regime|event
    scope_label: str
    market_data: List[Dict[str, Any]] = field(default_factory=list)
    index_data: Dict[str, Any] = field(default_factory=dict)
    regime: Optional[str] = None
    regime_confidence: Optional[float] = None
    features: Dict[str, Dict[str, float]] = field(default_factory=dict)
    news_events: List[Dict[str, Any]] = field(default_factory=list)
    sentiment: Dict[str, Any] = field(default_factory=dict)
    options_data: List[Dict[str, Any]] = field(default_factory=list)
    predictions_at_date: List[Dict[str, Any]] = field(default_factory=list)
    active_strategies: List[Dict[str, Any]] = field(default_factory=list)
    aqrti_confidence_at_date: float = 0.0
    knowledge_score_at_date: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


def replay_day(target_date: date, db: Optional[Session] = None) -> ReplaySnapshot:
    """Reconstruct complete market state for a single trading day."""
    own_session = db is None
    if own_session:
        db = get_session_factory()()

    try:
        snapshot = ReplaySnapshot(
            replay_date=target_date,
            replay_scope="day",
            scope_label=str(target_date),
        )

        # Market OHLCV — only rows up to and including target_date
        rows = db.execute(
            "SELECT symbol, date, open, high, low, close, volume, daily_return "
            "FROM daily_prices WHERE date = :d ORDER BY symbol",
            {"d": target_date},
        ).fetchall()
        snapshot.market_data = [dict(r._mapping) for r in rows]

        # Index data
        idx_rows = db.execute(
            "SELECT index_name, open, high, low, close, volume, returns "
            "FROM index_data WHERE date = :d",
            {"d": target_date},
        ).fetchall()
        for r in idx_rows:
            snapshot.index_data[r.index_name] = dict(r._mapping)

        # Regime — latest as-of target_date
        regime_row = db.execute(
            "SELECT regime, confidence FROM market_regimes "
            "WHERE date <= :d ORDER BY date DESC LIMIT 1",
            {"d": target_date},
        ).fetchone()
        if regime_row:
            snapshot.regime = regime_row.regime
            snapshot.regime_confidence = regime_row.confidence

        # Features — latest version per (symbol, feature_name) as-of target_date
        feat_rows = db.execute(
            "SELECT symbol, feature_name, value FROM feature_values "
            "WHERE date = :d",
            {"d": target_date},
        ).fetchall()
        for r in feat_rows:
            snapshot.features.setdefault(r.symbol, {})[r.feature_name] = r.value

        # News — within the 3-day window ending on target_date (no future)
        lookback = target_date - timedelta(days=3)
        news_rows = db.execute(
            "SELECT headline, company, event_type, sentiment_score, impact_score, timestamp "
            "FROM news_events WHERE date(timestamp) BETWEEN :lb AND :d ORDER BY timestamp DESC LIMIT 100",
            {"lb": lookback, "d": target_date},
        ).fetchall()
        snapshot.news_events = [dict(r._mapping) for r in news_rows]

        # Sentiment at that date
        sent_rows = db.execute(
            "SELECT entity, entity_type, score, velocity, confidence "
            "FROM sentiment_records WHERE date(timestamp) = :d",
            {"d": target_date},
        ).fetchall()
        for r in sent_rows:
            snapshot.sentiment[r.entity] = {
                "entity_type": r.entity_type,
                "score": r.score,
                "velocity": r.velocity,
                "confidence": r.confidence,
            }

        # Options data as-of target_date
        opt_rows = db.execute(
            "SELECT symbol, open_interest, oi_change, put_call_ratio, max_pain, atm_iv "
            "FROM options_data WHERE date = :d",
            {"d": target_date},
        ).fetchall()
        snapshot.options_data = [dict(r._mapping) for r in opt_rows]

        # AQRTI predictions issued ON target_date (what AQRTI knew that day)
        pred_rows = db.execute(
            "SELECT symbol, direction, confidence, expected_return, regime "
            "FROM predictions WHERE date = :d ORDER BY confidence DESC",
            {"d": target_date},
        ).fetchall()
        snapshot.predictions_at_date = [dict(r._mapping) for r in pred_rows]
        if pred_rows:
            snapshot.aqrti_confidence_at_date = sum(
                r.confidence for r in pred_rows if r.confidence
            ) / len(pred_rows)

        # Knowledge score at that date
        ks_row = db.execute(
            "SELECT overall_score FROM knowledge_scores WHERE date <= :d ORDER BY date DESC LIMIT 1",
            {"d": target_date},
        ).fetchone()
        if ks_row:
            snapshot.knowledge_score_at_date = ks_row.overall_score

        snapshot.metadata = {
            "symbols_count": len(snapshot.market_data),
            "news_count": len(snapshot.news_events),
            "predictions_count": len(snapshot.predictions_at_date),
            "features_symbols": len(snapshot.features),
            "generated_at": datetime.utcnow().isoformat(),
        }

        logger.info("Replay snapshot for %s: %s symbols, %s news, %s predictions",
                    target_date, len(snapshot.market_data),
                    len(snapshot.news_events), len(snapshot.predictions_at_date))
        return snapshot

    finally:
        if own_session:
            db.close()


def replay_week(week_start: date, db: Optional[Session] = None) -> List[ReplaySnapshot]:
    """Replay an entire trading week (Mon–Fri)."""
    own_session = db is None
    if own_session:
        db = get_session_factory()()
    try:
        snapshots = []
        for offset in range(5):
            d = week_start + timedelta(days=offset)
            try:
                snap = replay_day(d, db)
                snap.replay_scope = "week"
                snap.scope_label = f"W{week_start.isocalendar()[1]}/{week_start.year}"
                snapshots.append(snap)
            except Exception as exc:
                logger.warning("No data for %s in week replay: %s", d, exc)
        return snapshots
    finally:
        if own_session:
            db.close()


def replay_month(year: int, month: int, db: Optional[Session] = None) -> List[ReplaySnapshot]:
    """Replay all trading days in a calendar month."""
    own_session = db is None
    if own_session:
        db = get_session_factory()()
    try:
        # Find all dates with price data in the requested month
        rows = db.execute(
            "SELECT DISTINCT date FROM daily_prices "
            "WHERE strftime('%Y', date) = :y AND strftime('%m', date) = :m "
            "ORDER BY date",
            {"y": str(year), "m": f"{month:02d}"},
        ).fetchall()
        dates = [r[0] for r in rows]
        snapshots = []
        for d in dates:
            if isinstance(d, str):
                d = date.fromisoformat(d)
            snap = replay_day(d, db)
            snap.replay_scope = "month"
            snap.scope_label = f"{year}-{month:02d}"
            snapshots.append(snap)
        logger.info("Month replay %d-%02d: %d trading days", year, month, len(snapshots))
        return snapshots
    finally:
        if own_session:
            db.close()


def replay_regime(regime_name: str, db: Optional[Session] = None) -> List[ReplaySnapshot]:
    """Replay all days that occurred under a specific market regime."""
    own_session = db is None
    if own_session:
        db = get_session_factory()()
    try:
        rows = db.execute(
            "SELECT date FROM market_regimes WHERE regime = :r ORDER BY date",
            {"r": regime_name.upper()},
        ).fetchall()
        dates = [r[0] for r in rows]
        snapshots = []
        for d in dates:
            if isinstance(d, str):
                d = date.fromisoformat(d)
            snap = replay_day(d, db)
            snap.replay_scope = "regime"
            snap.scope_label = regime_name.upper()
            snapshots.append(snap)
        logger.info("Regime replay '%s': %d days", regime_name, len(snapshots))
        return snapshots
    finally:
        if own_session:
            db.close()


def replay_event_window(
    event_date: date,
    days_before: int = 5,
    days_after: int = 5,
    db: Optional[Session] = None,
) -> List[ReplaySnapshot]:
    """Replay the window around a specific market event (e.g., earnings, crash)."""
    own_session = db is None
    if own_session:
        db = get_session_factory()()
    try:
        start = event_date - timedelta(days=days_before)
        end = event_date + timedelta(days=days_after)
        rows = db.execute(
            "SELECT DISTINCT date FROM daily_prices WHERE date BETWEEN :s AND :e ORDER BY date",
            {"s": start, "e": end},
        ).fetchall()
        dates = [r[0] for r in rows]
        snapshots = []
        for d in dates:
            if isinstance(d, str):
                d = date.fromisoformat(d)
            snap = replay_day(d, db)
            snap.replay_scope = "event"
            snap.scope_label = f"Event@{event_date}"
            snapshots.append(snap)
        logger.info("Event replay around %s: %d days", event_date, len(snapshots))
        return snapshots
    finally:
        if own_session:
            db.close()


def snapshot_to_dict(snap: ReplaySnapshot) -> Dict[str, Any]:
    d = asdict(snap)
    # Convert date objects to ISO strings
    for k, v in d.items():
        if isinstance(v, date):
            d[k] = v.isoformat()
    return d
