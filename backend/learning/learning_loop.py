"""
Daily Learning Loop
Orchestrates the full learning pipeline in one call.

Step order:
  1. Evaluate pending pattern outcomes
  2. Run failure analysis (detect → classify → root cause)
  3. Run model drift detection (30d + 90d windows)
  4. Compute confidence scaling recommendation
  5. Run feature decay detection
  6. Bulk-record pattern memories from recent predictions
  7. Compute and persist daily knowledge score
  8. Log a KnowledgeEvent summarising the run

Called by APScheduler Step 7 after predictions and paper trading.
"""

from __future__ import annotations

import sys
import os
import json
from datetime import date

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from aqrti.database.session import SessionLocal
from aqrti.utils.logger import get_logger

log = get_logger("learning_loop")


def _backfill_prediction_outcomes(db, days: int = 30) -> dict:
    """
    Fill Prediction.actual_return for any prediction whose 5-day forward
    return can now be computed from DailyPrice data.

    Predictions are made for a horizon of ~5 trading days (~7 calendar days).
    We only fill once the data is available; older predictions are also
    backfilled if they were missed. This makes all downstream learning
    steps (model drift, failure detection, confidence audit, feature decay)
    work correctly instead of returning zero results.
    """
    from datetime import timedelta
    from aqrti.database.models import Prediction, DailyPrice

    cutoff = date.today() - timedelta(days=days)
    # Only process predictions that don't have actual_return yet
    preds = (
        db.query(Prediction)
        .filter(
            Prediction.date >= cutoff,
            Prediction.actual_return.is_(None),
        )
        .all()
    )

    filled = 0
    skipped = 0
    HORIZON_CALENDAR = 7  # 5 trading days ≈ 7 calendar days

    for p in preds:
        target_date = p.date + timedelta(days=HORIZON_CALENDAR)
        start_row = (
            db.query(DailyPrice.close)
            .filter(DailyPrice.symbol == p.symbol, DailyPrice.date >= p.date)
            .order_by(DailyPrice.date.asc())
            .first()
        )
        end_row = (
            db.query(DailyPrice.close)
            .filter(DailyPrice.symbol == p.symbol, DailyPrice.date <= target_date)
            .order_by(DailyPrice.date.desc())
            .first()
        )
        if not start_row or not end_row or start_row[0] == end_row[0]:
            skipped += 1
            continue
        if start_row[0] == 0:
            skipped += 1
            continue

        actual = round((end_row[0] - start_row[0]) / start_row[0] * 100, 4)
        p.actual_return = actual
        filled += 1

    if filled:
        db.commit()

    log.info("Prediction backfill: filled=%d skipped=%d", filled, skipped)
    return {"filled": filled, "skipped": skipped, "total_checked": len(preds)}


def run_daily_learning(days: int = 7) -> dict:
    """
    Run the full learning loop for today.

    Args:
        days: lookback window for failure detection (default 7 — catches last week's predictions)

    Returns:
        Summary dict of each step's result.
    """
    db = SessionLocal()
    summary = {"date": str(date.today()), "steps": {}}

    try:
        def _run_step(name, fn):
            try:
                result = fn()
                summary["steps"][name] = result
                return result
            except Exception as step_exc:
                log.warning("[Learning Loop] Step '%s' failed: %s", name, step_exc)
                summary["steps"][name] = {"status": "error", "error": str(step_exc)}
                try:
                    db.rollback()
                except Exception:
                    pass
                return None

        # Step 0: Backfill Prediction.actual_return from price data
        # Must run before all downstream steps that filter on actual_return.isnot(None)
        log.info("[Learning Loop] Step 0: Backfill prediction outcomes")
        _run_step("prediction_backfill", lambda: _backfill_prediction_outcomes(db, days=days))

        # Step 1: Evaluate pending pattern outcomes
        log.info("[Learning Loop] Step 1: Pattern outcome evaluation")
        from learning.pattern_outcome_tracker import evaluate_pending_outcomes
        _run_step("pattern_outcomes", lambda: evaluate_pending_outcomes(db))

        # Step 2: Failure analysis
        log.info("[Learning Loop] Step 2: Failure analysis")
        from learning.root_cause_engine import run_failure_analysis
        _run_step("failure_analysis", lambda: run_failure_analysis(db, days=days))

        # Step 3: Model drift detection
        log.info("[Learning Loop] Step 3: Model drift detection")
        from learning.model_drift import run_drift_detection
        _run_step("drift_detection", lambda: run_drift_detection(db, windows=[30, 90]))

        # Step 4: Confidence scaling recommendation
        log.info("[Learning Loop] Step 4: Confidence scaling")
        from learning.confidence_retrainer import record_scaling_recommendation
        _run_step("confidence_scaling", lambda: record_scaling_recommendation(db, days=30))

        # Step 5: Feature decay detection
        log.info("[Learning Loop] Step 5: Feature decay detection")
        from learning.feature_decay_detector import run_decay_detection
        _run_step("feature_decay", lambda: run_decay_detection(db))

        # Step 6: Bulk pattern memory from recent predictions
        log.info("[Learning Loop] Step 6: Pattern memory sync")
        from learning.pattern_memory import bulk_record_from_predictions
        _run_step("pattern_memory", lambda: {"recorded": bulk_record_from_predictions(db, days=days)})

        # Step 7: Daily knowledge score
        log.info("[Learning Loop] Step 7: Knowledge score")
        from learning.knowledge_score import record_daily_score
        score_row = record_daily_score(db, days=30)
        summary["steps"]["knowledge_score"] = {
            "overall_score": score_row.overall_score,
            "score_delta":   score_row.score_delta,
        }

        # Step 8: Log summary KnowledgeEvent
        from aqrti.database.models import KnowledgeEvent
        event = KnowledgeEvent(
            event_date    = date.today(),
            category      = "model",
            event_type    = "daily_learning_loop",
            description   = (
                f"Daily learning loop complete. "
                f"Failures: {summary['steps']['failure_analysis'].get('failures_processed', 0)}. "
                f"Drift flagged: {len(summary['steps']['drift_detection'].get('flagged', []))}. "
                f"Intelligence score: {score_row.overall_score:.1f} "
                f"({score_row.score_delta:+.1f})."
            ),
            outcome       = "success",
            magnitude     = float(score_row.overall_score),
            metadata_json = json.dumps({k: v for k, v in summary["steps"].items()
                                        if isinstance(v, dict) and "error" not in v}),
        )
        db.add(event)
        db.commit()
        summary["status"] = "success"
        log.info(
            "[Learning Loop] Complete. Score=%.1f failures=%d",
            score_row.overall_score,
            summary["steps"]["failure_analysis"].get("failures_processed", 0),
        )

    except Exception as exc:
        log.error("[Learning Loop] Failed: %s", exc, exc_info=True)
        summary["status"]  = "error"
        summary["error"]   = str(exc)
        try:
            db.rollback()
        except Exception:
            pass
    finally:
        db.close()

    return summary
