"""
Pattern Memory
Stores summaries of historically significant market situations and their outcomes.

A pattern memory entry captures:
  - The market context (regime, volatility, sector flows) at the time
  - The AQRTI prediction and actual outcome
  - Which features were dominant
  - The similarity score to future lookups

This module writes memory entries and retrieves nearest-neighbour
situations for comparison.
"""

from __future__ import annotations

import sys
import os
import json
from datetime import date, timedelta
from typing import Optional

import numpy as np
from sqlalchemy.orm import Session

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from aqrti.database.models import Prediction, PatternMatch, PatternOutcome, MarketRegime, KnowledgeEvent
from aqrti.utils.logger import get_logger

log = get_logger("pattern_memory")

SIMILARITY_THRESHOLD = 0.70


def _get_regime(db: Session, on_date: date) -> str:
    row = (
        db.query(MarketRegime.regime)
        .filter(MarketRegime.date <= on_date)
        .order_by(MarketRegime.date.desc())
        .first()
    )
    return row[0] if row else "UNKNOWN"


def record_pattern_memory(
    db:             Session,
    symbol:         str,
    prediction_date: date,
    pattern_confidence: float,
    predicted_return:   float,
    top_similar_symbol: Optional[str] = None,
    similarity_score:   float         = 0.0,
    regime_at:          Optional[str] = None,
) -> PatternOutcome:
    """
    Create a PatternOutcome row for a new prediction.
    actual_return fields are filled in later by pattern_outcome_tracker.
    """
    existing = (
        db.query(PatternOutcome.id)
        .filter(
            PatternOutcome.symbol          == symbol,
            PatternOutcome.prediction_date == prediction_date,
        )
        .first()
    )
    if existing:
        log.debug("Pattern memory already exists for %s %s", symbol, prediction_date)
        return None

    regime = regime_at or _get_regime(db, prediction_date)
    row    = PatternOutcome(
        symbol              = symbol,
        prediction_date     = prediction_date,
        pattern_confidence  = pattern_confidence,
        predicted_return    = predicted_return,
        top_similar_symbol  = top_similar_symbol,
        similarity_score    = similarity_score,
        regime_at           = regime,
    )
    db.add(row)
    log.debug("Pattern memory recorded for %s on %s", symbol, prediction_date)
    return row


def bulk_record_from_predictions(db: Session, days: int = 7) -> int:
    """
    Create PatternOutcome rows for all recent predictions that have
    a matching PatternMatch entry.
    """
    cutoff = date.today() - timedelta(days=days)
    preds  = (
        db.query(Prediction)
        .filter(Prediction.date >= cutoff)
        .all()
    )
    recorded = 0
    for p in preds:
        # Look for a PatternMatch for this symbol on this date
        pm = (
            db.query(PatternMatch)
            .filter(
                PatternMatch.symbol == p.symbol,
                PatternMatch.date   == p.date,
            )
            .order_by(PatternMatch.created_at.desc())
            .first()
        )
        conf      = float(pm.confidence)    if pm else float(p.confidence or 50)
        sim_score = float(pm.similarity)    if pm else 0.0
        top_sym   = pm.similar_symbol       if pm else None

        row = record_pattern_memory(
            db,
            symbol              = p.symbol,
            prediction_date     = p.date,
            pattern_confidence  = conf,
            predicted_return    = p.expected_return or 0.0,
            top_similar_symbol  = top_sym,
            similarity_score    = sim_score,
        )
        if row:
            recorded += 1

    db.commit()
    log.info("Bulk pattern memory: %d records created from %d predictions", recorded, len(preds))
    return recorded


def get_recent_patterns(db: Session, symbol: Optional[str] = None, days: int = 30) -> list[dict]:
    cutoff = date.today() - timedelta(days=days)
    q      = db.query(PatternOutcome).filter(PatternOutcome.prediction_date >= cutoff)
    if symbol:
        q = q.filter(PatternOutcome.symbol == symbol)
    rows = q.order_by(PatternOutcome.prediction_date.desc()).all()

    return [
        {
            "id":                  r.id,
            "symbol":              r.symbol,
            "prediction_date":     str(r.prediction_date),
            "pattern_confidence":  r.pattern_confidence,
            "predicted_return":    r.predicted_return,
            "actual_return_5d":    r.actual_return_5d,
            "actual_return_10d":   r.actual_return_10d,
            "was_correct":         r.was_correct,
            "outperformed_nifty":  r.outperformed_nifty,
            "similarity_score":    r.similarity_score,
            "top_similar_symbol":  r.top_similar_symbol,
            "regime_at":           r.regime_at,
        }
        for r in rows
    ]
