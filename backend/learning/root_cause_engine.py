"""
Root Cause Engine
Generates human-readable explanations for every classified failure.

For each failure it answers:
  - What happened
  - Why it happened (root cause)
  - What AQRTI should have done differently
  - What lesson to record

Writes to FailureRecord and generates a LessonLearned entry.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Optional

from sqlalchemy.orm import Session

from aqrti.database.models import FailureRecord
from aqrti.utils.logger import get_logger
from learning.lesson_registry import record_lesson

log = get_logger("root_cause_engine")

# ── Root cause templates ───────────────────────────────────────
_CAUSES = {
    "false_positive": (
        "Bullish prediction was incorrect. The model identified upward momentum signals "
        "but the stock declined. Likely caused by insufficient weight on downside risk indicators.",
        "Increase sensitivity to volume-based sell signals and sector weakness before confirming bullish signals.",
    ),
    "false_negative": (
        "Bearish prediction was incorrect. The model missed upside catalysts that drove the stock higher. "
        "Sentiment or event-driven signals were likely not captured.",
        "Review event classification pipeline. Ensure positive catalysts (earnings beats, regulatory approvals) "
        "are reflected in prediction inputs.",
    ),
    "overconfidence": (
        "Model expressed high confidence (≥80%) in a prediction that was incorrect. "
        "Calibration is off — stated probability does not match empirical accuracy.",
        "Recalibrate confidence scores. Apply confidence ceiling for stocks with high feature uncertainty. "
        "Review isotonic calibration on recent data.",
    ),
    "regime_failure": (
        "Bullish prediction was made during an adverse market regime (BEAR or VOLATILE). "
        "Regime-aware filters should have suppressed or reduced confidence in this signal.",
        "Strengthen regime gate: in BEAR regime, reduce bullish signal confidence by 20%. "
        "In VOLATILE regime, require 2x normal confirmation signals.",
    ),
    "sentiment_failure": (
        "The prediction directionally contradicted the prevailing sentiment signal. "
        "Either the sentiment model lagged, or the prediction model ignored sentiment context.",
        "Increase weight of recent sentiment velocity in model inputs. "
        "If sentiment score < 40 for Bullish predictions, require additional confirmation.",
    ),
    "feature_failure": (
        "One or more critical features were missing or invalid at prediction time. "
        "The model may have used zero-fill defaults which distorted the prediction.",
        "Implement feature health check before prediction: if critical features are missing, "
        "lower confidence by 30% or skip prediction entirely.",
    ),
    "pattern_failure": (
        "Historical pattern similarity suggested an outcome that did not materialise. "
        "The most similar historical situations had different underlying conditions.",
        "Increase minimum similarity threshold from 0.7 to 0.8. "
        "Weight patterns from matching regime periods 2x more than cross-regime patterns.",
    ),
    "trade_loss": (
        "Paper trade closed at a loss. The entry signal was valid but the exit was suboptimal "
        "or the position held through adverse price action.",
        "Review stop-loss placement (currently 8% hard stop). "
        "Consider tighter stops for high-volatility stocks or during adverse regimes.",
    ),
    "portfolio_failure": (
        "Portfolio-level loss exceeded expected parameters. "
        "Concentration risk or regime mismatch may have amplified individual losses.",
        "Enforce sector exposure limits more strictly. "
        "Reduce position sizes in VOLATILE regimes across the board.",
    ),
}


def generate_root_cause(
    db:             Session,
    classified:     dict,
) -> FailureRecord:
    """
    Write a FailureRecord with auto-generated root cause and lesson,
    then create a linked LessonLearned entry.
    """
    category  = classified["failure_category"]
    cause_tpl = _CAUSES.get(category, ("Unexpected failure pattern.", "Investigate manually."))
    root_cause = cause_tpl[0]
    recommendation = cause_tpl[1]

    symbol  = classified.get("symbol") or "—"
    regime  = classified.get("regime_at") or "UNKNOWN"
    conf    = classified.get("confidence_at") or 0
    pred    = classified.get("predicted_value") or 0
    actual  = classified.get("actual_value") or 0
    mag     = abs(actual - pred)

    description = (
        f"Symbol: {symbol}. "
        f"Predicted: {pred:+.2f}%  Actual: {actual:+.2f}%  Gap: {mag:.2f}pp. "
        f"Confidence at time: {conf:.0f}%. Regime: {regime}."
    )

    lesson_text = (
        f"[{category.upper()}] {symbol}: {root_cause[:120]}... "
        f"Recommendation: {recommendation[:120]}..."
    )

    fail_row = FailureRecord(
        failure_date        = classified["failure_date"],
        symbol              = symbol,
        failure_category    = category,
        failure_type        = classified.get("failure_type"),
        severity            = classified.get("severity", "medium"),
        predicted_value     = pred,
        actual_value        = actual,
        confidence_at       = conf,
        regime_at           = regime,
        root_cause          = root_cause,
        contributing_factors = classified.get("contributing_factors"),
        lesson              = recommendation,
        prediction_id       = classified.get("prediction_id"),
        trade_id            = classified.get("trade_id"),
    )
    db.add(fail_row)
    db.flush()

    # Generate linked lesson
    record_lesson(
        db               = db,
        category         = _lesson_category(category),
        title            = f"{category.replace('_', ' ').title()} — {symbol}",
        description      = description,
        what_happened    = f"{symbol} prediction was {category.replace('_', ' ')}. Actual return: {actual:+.2f}%.",
        why_it_happened  = root_cause,
        what_failed      = lesson_text,
        recommendation   = recommendation,
        severity         = classified.get("severity", "info"),
        symbol           = symbol if symbol != "—" else None,
        regime           = regime,
        source_failure_id = fail_row.id,
        lesson_date      = classified["failure_date"],
    )

    log.info("Root cause generated for %s [%s] severity=%s", symbol, category, fail_row.severity)
    return fail_row


def _lesson_category(failure_category: str) -> str:
    mapping = {
        "false_positive":   "prediction",
        "false_negative":   "prediction",
        "overconfidence":   "calibration",
        "regime_failure":   "regime",
        "sentiment_failure": "prediction",
        "feature_failure":  "feature",
        "pattern_failure":  "pattern",
        "trade_loss":       "portfolio",
        "portfolio_failure": "portfolio",
    }
    return mapping.get(failure_category, "prediction")


def run_failure_analysis(db: Session, days: int = 7) -> dict:
    """
    Full failure analysis pipeline:
      detect → classify → root cause → persist

    Returns summary dict.
    """
    from learning.failure_detector import detect_all_failures
    from learning.failure_classifier import classify_failure

    candidates = detect_all_failures(db, days=days)
    if not candidates:
        log.info("No failures detected in last %d days", days)
        return {"failures_processed": 0, "days": days}

    processed = 0
    errors    = []
    for c in candidates:
        try:
            classified = classify_failure(db, c)
            generate_root_cause(db, classified)
            processed += 1
        except Exception as exc:
            log.error("Root cause failed for %s: %s", c.symbol, exc)
            errors.append(str(exc))

    db.commit()
    log.info("Failure analysis complete: processed=%d errors=%d", processed, len(errors))
    return {
        "failures_processed": processed,
        "errors":             errors,
        "days":               days,
    }
