"""
Pattern Outcome Tracker
Evaluates PatternOutcome rows after 5 and 10 trading days have elapsed.

For each row where actual_return_5d is still NULL and the prediction
date is at least 5 trading days old, it:
  1. Looks up the actual 5d return from the Prediction table
  2. Compares against NIFTY benchmark from MarketRegime / price data
  3. Marks was_correct, outperformed_nifty, and fills both return fields

This module is called by the daily learning loop.
"""

from __future__ import annotations

import sys
import os
from datetime import date, timedelta
from typing import Optional

from sqlalchemy.orm import Session

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from aqrti.database.models import PatternOutcome, Prediction, DailyPrice, IndexData
from aqrti.utils.logger import get_logger

log = get_logger("pattern_outcome_tracker")

# Approximate trading days (not calendar days)
EVAL_5D_CALENDAR  = 7
EVAL_10D_CALENDAR = 14


def _actual_return(db: Session, symbol: str, from_date: date, horizon_calendar: int) -> Optional[float]:
    to_date = from_date + timedelta(days=horizon_calendar)
    start_row = (
        db.query(DailyPrice.close)
        .filter(DailyPrice.symbol == symbol, DailyPrice.date >= from_date)
        .order_by(DailyPrice.date.asc())
        .first()
    )
    end_row = (
        db.query(DailyPrice.close)
        .filter(DailyPrice.symbol == symbol, DailyPrice.date <= to_date)
        .order_by(DailyPrice.date.desc())
        .first()
    )
    if not start_row or not end_row:
        return None
    if start_row[0] == 0:
        return None
    return round((end_row[0] - start_row[0]) / start_row[0] * 100, 4)


def _nifty_return(db: Session, from_date: date, horizon_calendar: int) -> Optional[float]:
    """Compute NIFTY50 index return for the same horizon using IndexData."""
    to_date = from_date + timedelta(days=horizon_calendar)
    start_row = (
        db.query(IndexData.close)
        .filter(IndexData.index_name == "NIFTY50", IndexData.date >= from_date)
        .order_by(IndexData.date.asc())
        .first()
    )
    end_row = (
        db.query(IndexData.close)
        .filter(IndexData.index_name == "NIFTY50", IndexData.date <= to_date)
        .order_by(IndexData.date.desc())
        .first()
    )
    if not start_row or not end_row:
        return None
    if start_row[0] == 0:
        return None
    return round((end_row[0] - start_row[0]) / start_row[0] * 100, 4)


def evaluate_pending_outcomes(db: Session) -> dict:
    """
    Evaluate all PatternOutcome rows where actual_return_5d is still NULL
    and the prediction date is old enough (>= 5 trading days).

    Returns summary of evaluations.
    """
    threshold_5d  = date.today() - timedelta(days=EVAL_5D_CALENDAR)
    threshold_10d = date.today() - timedelta(days=EVAL_10D_CALENDAR)

    pending = (
        db.query(PatternOutcome)
        .filter(
            PatternOutcome.actual_return_5d.is_(None),
            PatternOutcome.prediction_date <= threshold_5d,
        )
        .all()
    )

    evaluated = 0
    skipped   = 0

    for row in pending:
        ret_5d  = _actual_return(db, row.symbol, row.prediction_date, EVAL_5D_CALENDAR)
        if ret_5d is None:
            # Try getting it from Prediction table first
            pred = (
                db.query(Prediction)
                .filter(
                    Prediction.symbol == row.symbol,
                    Prediction.date   == row.prediction_date,
                )
                .first()
            )
            if pred and pred.actual_return is not None:
                ret_5d = pred.actual_return

        if ret_5d is None:
            skipped += 1
            continue

        # 10d return only if date is old enough
        ret_10d = None
        if row.prediction_date <= threshold_10d:
            ret_10d = _actual_return(db, row.symbol, row.prediction_date, EVAL_10D_CALENDAR)

        nifty_5d = _nifty_return(db, row.prediction_date, EVAL_5D_CALENDAR)

        was_correct = (
            (row.predicted_return > 0 and ret_5d > 0) or
            (row.predicted_return < 0 and ret_5d < 0)
        )
        outperformed = (ret_5d > nifty_5d) if nifty_5d is not None else None

        row.actual_return_5d  = ret_5d
        row.actual_return_10d = ret_10d
        row.was_correct        = was_correct
        row.outperformed_nifty = outperformed
        row.evaluated_at       = date.today()
        evaluated += 1

    db.commit()
    log.info("Pattern outcomes evaluated: %d evaluated, %d skipped", evaluated, skipped)
    return {
        "pending":   len(pending),
        "evaluated": evaluated,
        "skipped":   skipped,
    }


def get_outcome_summary(db: Session, days: int = 30) -> dict:
    cutoff = date.today() - timedelta(days=days)
    rows   = (
        db.query(PatternOutcome)
        .filter(
            PatternOutcome.prediction_date >= cutoff,
            PatternOutcome.actual_return_5d.isnot(None),
        )
        .all()
    )
    if not rows:
        return {"days": days, "total": 0, "hit_rate": None}

    correct      = sum(1 for r in rows if r.was_correct)
    outperformed = sum(1 for r in rows if r.outperformed_nifty)
    avg_5d       = sum(r.actual_return_5d for r in rows) / len(rows)

    return {
        "days":             days,
        "total":            len(rows),
        "hit_rate":         round(correct / len(rows) * 100, 2),
        "nifty_beat_rate":  round(outperformed / len(rows) * 100, 2),
        "avg_return_5d":    round(avg_5d, 4),
    }
