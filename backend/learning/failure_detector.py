"""
Failure Detector
Scans evaluated predictions and closed trades to detect failures.

A prediction is a failure when:
  - actual_return is available AND
  - direction was wrong (false positive / false negative) OR
  - confidence was ≥ 80% but outcome was wrong (overconfidence)

A trade is a failure when gross_pnl < 0.

Returns structured FailureCandidate dicts for the classifier.
"""

from __future__ import annotations

from datetime import date, timedelta
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy.orm import Session

from aqrti.database.models import Prediction, PaperTrade, MarketRegime
from aqrti.utils.logger import get_logger

log = get_logger("failure_detector")

OVERCONFIDENCE_THRESHOLD = 78.0   # confidence above this + wrong = overconfidence failure
MIN_RETURN_MAGNITUDE     = 0.5    # ignore tiny moves, only flag meaningful failures


@dataclass
class FailureCandidate:
    failure_date:   date
    symbol:         str
    raw_category:   str          # false_positive|false_negative|overconfidence|trade_loss
    predicted_value: float
    actual_value:   float
    confidence_at:  float
    regime_at:      str
    prediction_id:  Optional[int] = None
    trade_id:       Optional[int] = None
    metadata:       dict = field(default_factory=dict)


def _get_regime_at(db: Session, on_date: date) -> str:
    row = (
        db.query(MarketRegime.regime)
        .filter(MarketRegime.date <= on_date)
        .order_by(MarketRegime.date.desc())
        .first()
    )
    return row[0] if row else "UNKNOWN"


def detect_prediction_failures(
    db:   Session,
    days: int = 7,
) -> list[FailureCandidate]:
    """
    Scan predictions with actual_return filled in, detect failures.
    Looks at the last N days of evaluated predictions.
    """
    cutoff = date.today() - timedelta(days=days)
    preds  = (
        db.query(Prediction)
        .filter(
            Prediction.date >= cutoff,
            Prediction.actual_return.isnot(None),
        )
        .all()
    )

    candidates = []
    for p in preds:
        actual  = p.actual_return or 0.0
        conf    = p.confidence or 50.0
        is_bull = p.direction == "Bullish"
        is_bear = p.direction == "Bearish"

        # Skip tiny moves — not meaningful
        if abs(actual) < MIN_RETURN_MAGNITUDE and abs(p.expected_return or 0) < MIN_RETURN_MAGNITUDE:
            continue

        # False positive: predicted Bullish, actual negative
        if is_bull and actual < -MIN_RETURN_MAGNITUDE:
            raw_cat = "overconfidence" if conf >= OVERCONFIDENCE_THRESHOLD else "false_positive"
            candidates.append(FailureCandidate(
                failure_date    = p.date,
                symbol          = p.symbol,
                raw_category    = raw_cat,
                predicted_value = p.expected_return or 0,
                actual_value    = actual,
                confidence_at   = conf,
                regime_at       = _get_regime_at(db, p.date),
                prediction_id   = p.id,
                metadata        = {"direction": p.direction, "risk_level": p.risk_level},
            ))

        # False negative: predicted Bearish, actual strongly positive
        elif is_bear and actual > MIN_RETURN_MAGNITUDE:
            raw_cat = "overconfidence" if conf >= OVERCONFIDENCE_THRESHOLD else "false_negative"
            candidates.append(FailureCandidate(
                failure_date    = p.date,
                symbol          = p.symbol,
                raw_category    = raw_cat,
                predicted_value = p.expected_return or 0,
                actual_value    = actual,
                confidence_at   = conf,
                regime_at       = _get_regime_at(db, p.date),
                prediction_id   = p.id,
                metadata        = {"direction": p.direction, "risk_level": p.risk_level},
            ))

    log.info("Detected %d prediction failures in last %d days", len(candidates), days)
    return candidates


def detect_trade_failures(
    db:   Session,
    days: int = 7,
) -> list[FailureCandidate]:
    """Scan recently closed paper trades for losses."""
    cutoff = date.today() - timedelta(days=days)
    trades = (
        db.query(PaperTrade)
        .filter(
            PaperTrade.exit_date >= cutoff,
            PaperTrade.is_open == False,
            PaperTrade.gross_pnl < 0,
        )
        .all()
    )

    candidates = []
    for t in trades:
        if abs(t.gross_pnl_pct or 0) < 0.5:
            continue
        candidates.append(FailureCandidate(
            failure_date    = t.exit_date or date.today(),
            symbol          = t.symbol,
            raw_category    = "trade_loss",
            predicted_value = t.predicted_return or 0,
            actual_value    = t.actual_return or 0,
            confidence_at   = t.confidence or 50,
            regime_at       = _get_regime_at(db, t.exit_date or date.today()),
            trade_id        = t.id,
            metadata        = {
                "holding_days": t.holding_days,
                "exit_reason":  t.exit_reason,
                "pnl_pct":      t.gross_pnl_pct,
            },
        ))

    log.info("Detected %d trade failures in last %d days", len(candidates), days)
    return candidates


def detect_all_failures(db: Session, days: int = 7) -> list[FailureCandidate]:
    return detect_prediction_failures(db, days) + detect_trade_failures(db, days)
