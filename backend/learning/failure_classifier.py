"""
Failure Classifier
Takes raw FailureCandidates from the detector and classifies them
into detailed failure types with severity ratings.

Failure taxonomy:
  false_positive    → predicted bullish, stock fell
  false_negative    → predicted bearish, stock rose
  overconfidence    → ≥80% confident, was wrong
  regime_failure    → wrong prediction + regime was adverse
  sentiment_failure → sentiment contradicted the move
  feature_failure   → key features were missing or extreme
  pattern_failure   → pattern suggested wrong direction
  portfolio_failure → loss exceeded risk limits
  trade_loss        → trade closed at a loss
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from sqlalchemy.orm import Session

from aqrti.database.models import SentimentRecord, FeatureValue, MarketRegime
from aqrti.utils.logger import get_logger
from learning.failure_detector import FailureCandidate

log = get_logger("failure_classifier")

SEVERITY_MAP = {
    "overconfidence":   "high",
    "regime_failure":   "high",
    "false_positive":   "medium",
    "false_negative":   "medium",
    "sentiment_failure": "medium",
    "feature_failure":  "low",
    "pattern_failure":  "low",
    "portfolio_failure": "high",
    "trade_loss":       "medium",
}

ADVERSE_REGIMES = {"BEAR", "VOLATILE"}


def _get_sentiment(db: Session, symbol: str, on_date: date) -> Optional[float]:
    row = (
        db.query(SentimentRecord.score)
        .filter(
            SentimentRecord.entity == symbol,
            SentimentRecord.entity_type == "stock",
        )
        .order_by(SentimentRecord.timestamp.desc())
        .first()
    )
    return row[0] if row else None


def _has_missing_features(db: Session, symbol: str, on_date: date) -> bool:
    """True if critical features were missing or zero on the prediction date."""
    critical_features = ["rsi_14", "ema_21", "macd_signal", "rolling_vol_21d"]
    for feat in critical_features:
        row = (
            db.query(FeatureValue.value)
            .filter(
                FeatureValue.symbol == symbol,
                FeatureValue.date   == on_date,
                FeatureValue.feature_name == feat,
            )
            .first()
        )
        if not row or row[0] is None:
            return True
    return False


def classify_failure(
    db:        Session,
    candidate: FailureCandidate,
) -> dict:
    """
    Enrich a FailureCandidate with detailed classification.
    Returns a dict ready to write into FailureRecord.
    """
    category = candidate.raw_category
    symbol   = candidate.symbol
    on_date  = candidate.failure_date
    regime   = candidate.regime_at

    # Regime escalation
    if regime in ADVERSE_REGIMES and category in ("false_positive", "false_negative"):
        category = "regime_failure"

    # Sentiment misalignment check
    sentiment = _get_sentiment(db, symbol, on_date)
    sentiment_conflict = False
    if sentiment is not None:
        is_bull_pred = candidate.predicted_value > 0
        sentiment_conflict = (
            (is_bull_pred and sentiment < 40) or
            (not is_bull_pred and sentiment > 60)
        )
    if sentiment_conflict and category not in ("overconfidence", "regime_failure"):
        category = "sentiment_failure"

    # Feature completeness check
    feature_issue = _has_missing_features(db, symbol, on_date)
    if feature_issue and category == "false_positive":
        category = "feature_failure"

    severity = SEVERITY_MAP.get(category, "medium")

    # Escalate severity for large magnitude failures
    magnitude = abs(candidate.actual_value - candidate.predicted_value)
    if magnitude > 10 and severity == "medium":
        severity = "high"
    elif magnitude > 20:
        severity = "critical"

    return {
        "failure_date":     on_date,
        "symbol":           symbol,
        "failure_category": category,
        "failure_type":     _derive_type(category, candidate),
        "severity":         severity,
        "predicted_value":  candidate.predicted_value,
        "actual_value":     candidate.actual_value,
        "confidence_at":    candidate.confidence_at,
        "regime_at":        regime,
        "prediction_id":    candidate.prediction_id,
        "trade_id":         candidate.trade_id,
        "contributing_factors": _contributing_factors(
            regime, sentiment, feature_issue, sentiment_conflict
        ),
    }


def _derive_type(category: str, c: FailureCandidate) -> str:
    if category == "overconfidence":
        level = "extreme" if c.confidence_at >= 90 else "high"
        return f"{level}_confidence_wrong"
    if category == "regime_failure":
        return f"bullish_in_{c.regime_at.lower()}_regime"
    if category == "false_positive":
        return "bullish_predicted_bearish_outcome"
    if category == "false_negative":
        return "bearish_predicted_bullish_outcome"
    if category == "sentiment_failure":
        return "prediction_contradicts_sentiment"
    if category == "feature_failure":
        return "missing_critical_features"
    if category == "trade_loss":
        return f"loss_{abs(c.actual_value):.1f}pct"
    return category


def _contributing_factors(regime, sentiment, feature_issue, sentiment_conflict) -> str:
    import json
    factors = []
    if regime in ADVERSE_REGIMES:
        factors.append(f"adverse_regime:{regime}")
    if sentiment_conflict:
        factors.append(f"sentiment_conflict:score={sentiment:.0f}" if sentiment else "sentiment_conflict")
    if feature_issue:
        factors.append("missing_critical_features")
    return json.dumps(factors)
