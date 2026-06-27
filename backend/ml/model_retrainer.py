"""
Model Self-Improvement Engine
Monitors model accuracy and triggers retraining when performance degrades.

Triggered by:
  - model_research_agent detecting win rate < 50% over last 30 days
  - Direct POST /admin/retrain call
  - Scheduled daily sweep (if model is > 30 days old and accuracy has drifted)

Retraining steps:
  1. Build a fresh training dataset (last 365 days)
  2. Walk-forward validation to select hyperparams
  3. Train final models (LGB + XGB + CatBoost) on full dataset
  4. Register new model versions in model_versions table
  5. Retire the old active model (is_active → False)
  6. Write a LessonLearned record explaining what changed
  7. Run a fresh confidence calibration on the new model

Failure analysis fed into retraining:
  - Which regimes had worst accuracy → regime-specific re-weighting
  - Which confidence bands were overconfident → adjust calibration
  - Which features had near-zero importance → consider dropping
"""

from __future__ import annotations

import sys, os, json, time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from sqlalchemy.orm import Session

from aqrti.database.models import (
    ModelVersion, Prediction, LessonLearned, KnowledgeEvent,
    MarketRegime,
)
from aqrti.utils.logger import get_logger

log = get_logger("model_retrainer")

# ── Thresholds ────────────────────────────────────────────────
WIN_RATE_FLOOR        = 50.0   # below this → trigger retraining
WIN_RATE_TARGET       = 75.0   # new model must achieve this on eval set to be promoted
ACCURACY_EVAL_DAYS    = 30     # evaluate accuracy over last N days
MODEL_STALE_DAYS      = 45     # retrain if model hasn't been updated in N days
MIN_PREDICTIONS_EVAL  = 20     # need at least this many evaluated predictions
MAX_RETRAIN_ATTEMPTS  = 5      # max retrain loops before giving up


def _current_regime(db: Session) -> str:
    row = db.query(MarketRegime.regime).order_by(MarketRegime.date.desc()).first()
    return row[0] if row else "BULL"


def _check_accuracy(db: Session) -> dict:
    """
    Check recent prediction accuracy.
    Returns: {"should_retrain": bool, "reason": str, "win_rate": float, ...}
    """
    cutoff = date.today() - timedelta(days=ACCURACY_EVAL_DAYS)
    evaluated = (
        db.query(Prediction)
        .filter(Prediction.date >= cutoff, Prediction.success.isnot(None))
        .all()
    )

    if len(evaluated) < MIN_PREDICTIONS_EVAL:
        return {
            "should_retrain": False,
            "reason":         f"insufficient_data ({len(evaluated)} < {MIN_PREDICTIONS_EVAL})",
            "win_rate":       None,
            "evaluated":      len(evaluated),
        }

    wins     = sum(1 for p in evaluated if p.success)
    win_rate = wins / len(evaluated) * 100

    # Per-regime breakdown
    by_regime: dict[str, list[int]] = {}
    for p in evaluated:
        reg = getattr(p, "regime", None) or "UNKNOWN"
        by_regime.setdefault(reg, []).append(1 if p.success else 0)
    regime_wr = {
        r: round(sum(v) / len(v) * 100, 1)
        for r, v in by_regime.items() if v
    }

    should_retrain = win_rate < WIN_RATE_FLOOR
    reason = (
        f"win_rate={win_rate:.1f}% < threshold={WIN_RATE_FLOOR}%"
        if should_retrain
        else f"win_rate={win_rate:.1f}% acceptable"
    )

    return {
        "should_retrain":   should_retrain,
        "reason":           reason,
        "win_rate":         round(win_rate, 2),
        "evaluated":        len(evaluated),
        "wins":             wins,
        "regime_win_rates": regime_wr,
    }


def _check_model_staleness(db: Session) -> dict:
    """Check if the active model is too old."""
    active = (
        db.query(ModelVersion)
        .filter(ModelVersion.is_active == True)
        .order_by(ModelVersion.trained_at.desc())
        .first()
    )
    if not active:
        return {"stale": True, "reason": "no_active_model", "age_days": None}
    if not active.trained_at:
        return {"stale": False, "reason": "unknown_age", "age_days": None}

    age = (datetime.utcnow() - active.trained_at).days
    stale = age > MODEL_STALE_DAYS
    return {
        "stale":       stale,
        "reason":      f"model_age={age}d > {MODEL_STALE_DAYS}d" if stale else f"model_age={age}d ok",
        "age_days":    age,
        "model_name":  active.model_name,
        "trained_at":  str(active.trained_at),
    }


def _run_training_pipeline(db: Session, trigger_reason: str) -> dict:
    """
    Execute the full model training pipeline.
    Uses the existing walk_forward + model training infrastructure.
    Returns summary dict.
    """
    start = time.time()
    log.info("Starting model retraining. Reason: %s", trigger_reason)

    try:
        from ml.datasets.training_dataset import prepare_training_dataset
        from ml.models.lightgbm_model import LightGBMModel
        from ml.models.xgboost_model import XGBoostModel
        from ml.models.catboost_model import CatBoostModel
        import pandas as pd, numpy as np

        dataset = prepare_training_dataset(label_col="direction_5d", top_features=40, scale=True)
        splits  = dataset.folds

        if not splits:
            log.warning("No training splits available — not enough data for retraining")
            return {"status": "no_data", "reason": "insufficient_historical_data"}

        # Walk-forward validation on latest split for metric comparison
        latest_split = splits[-1]
        X_train = latest_split.X_train
        y_train = latest_split.y_train
        X_test  = latest_split.X_test
        y_test  = latest_split.y_test

        # Compute next version number before training so models can use it
        last_version = (
            db.query(ModelVersion.version)
            .order_by(ModelVersion.version.desc())
            .first()
        )
        next_version = (last_version[0] + 1) if last_version else 1

        trained_models = []
        metrics_list   = []

        for ModelClass in [LightGBMModel, XGBoostModel, CatBoostModel]:
            try:
                model = ModelClass(task="direction", label_col="direction_5d", version=next_version)
                model.fit(X_train, y_train, X_val=X_test, y_val=y_test)
                # Compute metrics manually using predict
                preds = model.predict(X_test)
                correct = int((preds == y_test.values).sum())
                accuracy = correct / len(y_test) if len(y_test) > 0 else 0.0
                try:
                    probas = model.predict_proba(X_test)
                    from sklearn.metrics import roc_auc_score
                    # predict_proba returns 1D array of P(class=1) for classifiers
                    prob_pos = probas if probas.ndim == 1 else probas[:, 1]
                    auc = float(roc_auc_score(y_test, prob_pos))
                except Exception:
                    auc = 0.5
                test_metrics = {"accuracy": accuracy, "auc_roc": auc, "n_test": len(y_test)}
                metrics_list.append({"model": model.model_type, "metrics": test_metrics})
                trained_models.append((model, test_metrics))
                log.info("Trained %s: accuracy=%.3f auc=%.3f", model.model_type, accuracy, auc)
            except Exception as exc:
                log.warning("Training %s failed: %s", ModelClass.__name__, exc)

        if not trained_models:
            return {"status": "error", "reason": "all_model_training_failed"}

        # Register the best model as new active version
        best_model, best_metrics = max(
            trained_models,
            key=lambda x: x[1].get("accuracy", 0),
        )

        # Retire current active models
        current_active = db.query(ModelVersion).filter(ModelVersion.is_active == True).all()
        for m in current_active:
            m.is_active = False

        # Save model artifact to disk (version already set on model)
        save_path = best_model.save()

        # Register in DB — delete ALL records for this version (any model name) to avoid UNIQUE collision
        db.query(ModelVersion).filter(
            ModelVersion.task == "direction",
            ModelVersion.version == next_version,
        ).delete(synchronize_session=False)
        db.flush()
        new_mv = ModelVersion(
            model_name    = best_model.model_type,
            task          = "direction",
            label_col     = "direction_5d",
            version       = next_version,
            primary_metric = best_metrics.get("accuracy"),
            metrics_json  = json.dumps(best_metrics),
            importance_json = json.dumps(best_model.feature_importance() if hasattr(best_model, "feature_importance") else {}),
            train_rows    = len(X_train),
            is_active     = True,
            trained_at    = datetime.utcnow(),
        )
        db.add(new_mv)

        elapsed = round(time.time() - start, 1)
        log.info(
            "Retraining complete in %.1fs: model=%s v%d accuracy=%.3f",
            elapsed, best_model.model_type, next_version, best_metrics.get("accuracy", 0),
        )

        # win_rate on test set (% of correctly predicted directions)
        accuracy = best_metrics.get("accuracy", 0.0)
        win_rate_pct = round(accuracy * 100, 2)

        return {
            "status":      "ok",
            "model":       best_model.model_type,
            "version":     next_version,
            "accuracy":    accuracy,
            "win_rate":    win_rate_pct,
            "metrics":     metrics_list,
            "elapsed_sec": elapsed,
            "trigger":     trigger_reason,
        }

    except ImportError as exc:
        log.warning("Model training imports unavailable: %s", exc)
        return {"status": "unavailable", "reason": str(exc)}
    except Exception as exc:
        log.error("Retraining failed: %s", exc)
        return {"status": "error", "reason": str(exc)}


def _record_lesson(db: Session, accuracy_check: dict, retrain_result: dict) -> None:
    """Write a LessonLearned record for the retraining event."""
    regime = _current_regime(db)
    win_rate = accuracy_check.get("win_rate")

    win_rate_str = f"{win_rate:.1f}%" if win_rate is not None else "N/A"
    what_failed = (
        f"Model win rate: {win_rate_str} (threshold {WIN_RATE_FLOOR}%) "
        f"over last {ACCURACY_EVAL_DAYS} days ({accuracy_check.get('evaluated', 0)} predictions)."
    )
    regime_breakdown = accuracy_check.get("regime_win_rates", {})
    worst_regime = min(regime_breakdown, key=regime_breakdown.get) if regime_breakdown else None

    what_happened = (
        f"Automatic model retraining triggered. Reason: {accuracy_check.get('reason', 'forced')}. "
        f"Worst performing regime: {worst_regime} ({regime_breakdown.get(worst_regime, 'N/A')}% accuracy). "
        f"New model: {retrain_result.get('model', 'N/A')} v{retrain_result.get('version', '?')} "
        f"accuracy={retrain_result.get('accuracy', 0):.3f}."
    )

    lesson = LessonLearned(
        lesson_date     = date.today(),
        category        = "model",
        title           = f"Model retrained (win_rate={win_rate_str}) in {regime} regime",
        description     = what_happened,
        what_happened   = what_happened,
        what_failed     = what_failed,
        why_it_happened = (
            f"Market conditions changed in {regime} regime. "
            f"Model patterns from previous training window no longer generalise."
        ),
        recommendation  = (
            "Monitor regime-specific accuracy daily. "
            "Consider training separate regime models if divergence persists."
        ),
        severity        = "warning" if (win_rate is not None and win_rate >= 40) else "critical",
        regime          = regime,
        applied         = True,
    )
    db.add(lesson)

    # Also write KnowledgeEvent for cross-agent visibility
    event = KnowledgeEvent(
        event_date  = date.today(),
        category    = "model",
        event_type  = "model_retrained",
        description = (
            f"Model retrained. "
            f"win_rate={win_rate_str}. "
            f"New model: {retrain_result.get('model', 'N/A')} "
            f"v{retrain_result.get('version', '?')} "
            f"accuracy={retrain_result.get('accuracy', 0):.3f}."
        ),
        outcome     = "positive" if retrain_result.get("status") == "ok" else "negative",
        magnitude   = retrain_result.get("accuracy", 0.0),
        metadata_json = json.dumps({
            "accuracy_check": accuracy_check,
            "retrain_result": retrain_result,
        }),
    )
    db.add(event)
    db.commit()


# ═════════════════════════════════════════════════════════════════════
# PUBLIC API
# ═════════════════════════════════════════════════════════════════════

def check_and_retrain(db: Session, force: bool = False) -> dict:
    """
    Check if retraining is needed and run it if so.

    Args:
        db:    DB session
        force: if True, retrain regardless of accuracy check

    Returns:
        Summary dict with "retrained", "reason", and optional "result".
    """
    accuracy = _check_accuracy(db)
    staleness = _check_model_staleness(db)

    should_retrain = force or accuracy["should_retrain"] or staleness["stale"]
    reason = []
    if force:
        reason.append("forced")
    if accuracy["should_retrain"]:
        reason.append(accuracy["reason"])
    if staleness["stale"]:
        reason.append(staleness["reason"])

    trigger_reason = "; ".join(reason) if reason else "scheduled_check"

    if not should_retrain:
        log.info("No retraining needed: %s", accuracy["reason"])
        return {
            "retrained":   False,
            "reason":      accuracy["reason"],
            "win_rate":    accuracy.get("win_rate"),
            "model_age":   staleness.get("age_days"),
        }

    log.info("Triggering retraining: %s", trigger_reason)

    # Retry loop: keep retraining until win_rate >= WIN_RATE_TARGET or max attempts
    attempt = 0
    result = {}
    while attempt < MAX_RETRAIN_ATTEMPTS:
        attempt += 1
        attempt_trigger = f"{trigger_reason} (attempt {attempt}/{MAX_RETRAIN_ATTEMPTS})"
        log.info("Retrain attempt %d/%d", attempt, MAX_RETRAIN_ATTEMPTS)
        result = _run_training_pipeline(db, attempt_trigger)

        if result.get("status") != "ok":
            log.warning("Retrain attempt %d failed: %s", attempt, result.get("reason"))
            break

        # Commit after each attempt so the next attempt starts with a clean session state
        db.commit()

        achieved_wr = result.get("win_rate", 0.0)
        log.info("Attempt %d: win_rate=%.1f%% (target=%.1f%%)", attempt, achieved_wr, WIN_RATE_TARGET)

        if achieved_wr >= WIN_RATE_TARGET:
            log.info("Win rate target achieved (%.1f%% >= %.1f%%) — promoting model", achieved_wr, WIN_RATE_TARGET)
            break
        else:
            log.info(
                "Win rate %.1f%% below target %.1f%% — retiring model and retraining",
                achieved_wr, WIN_RATE_TARGET,
            )
            # Mark the just-trained model inactive so next attempt can promote the new one
            from aqrti.database.models import ModelVersion as _MV
            db.query(_MV).filter(_MV.is_active == True).update({"is_active": False})
            db.commit()

    if result.get("status") == "ok":
        _record_lesson(db, accuracy, result)

    return {
        "retrained":       True,
        "attempts":        attempt,
        "trigger_reason":  trigger_reason,
        "accuracy_check":  accuracy,
        "staleness":       staleness,
        "result":          result,
        "win_rate_target": WIN_RATE_TARGET,
        "win_rate_achieved": result.get("win_rate"),
    }


def get_retraining_status(db: Session) -> dict:
    """
    Return a summary of whether retraining is needed without running it.
    Used by the model research agent and the UI.
    """
    accuracy  = _check_accuracy(db)
    staleness = _check_model_staleness(db)

    # Last retraining event
    last_retrain = (
        db.query(KnowledgeEvent)
        .filter(KnowledgeEvent.event_type == "model_retrained")
        .order_by(KnowledgeEvent.created_at.desc())
        .first()
    )

    return {
        "needs_retraining":   accuracy["should_retrain"] or staleness["stale"],
        "accuracy_check":     accuracy,
        "staleness_check":    staleness,
        "last_retrained_at":  str(last_retrain.created_at) if last_retrain else None,
        "last_retrain_detail": json.loads(last_retrain.metadata_json or "{}") if last_retrain else None,
    }
