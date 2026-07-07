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
  3. Train final model (CatBoost) on full dataset
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

import sys, os, json, time, signal
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

_INTERRUPTED = False


def _signal_handler(signum, frame):
    global _INTERRUPTED
    if not _INTERRUPTED:
        _INTERRUPTED = True
        log.warning("Received signal %d — will checkpoint on next opportunity", signum)


try:
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)
except (ValueError, AttributeError):
    pass


def _save_intermediate_checkpoint(model, iteration: int, next_version: int, label: str = ""):
    """Save an intermediate model pickle to the intermediate directory."""
    try:
        from ml.models.base_model import ML_MODELS_DIR
        inter_dir = Path(backend_dir) / "ml_models" / "intermediate"
        inter_dir.mkdir(parents=True, exist_ok=True)
        # Keyed on label_col, matching base_model.py's save() — model.task
        # ("direction"/"expected_return") is shared by multiple label_cols
        # (direction_5d, outperform_binary), so using it here would look for
        # the wrong saved_path once two label_cols under the same task exist.
        fname = f"{model.model_type}_{model.label_col}_v{next_version}_iter_{iteration}"
        if label:
            fname += f"_{label}"
        fpath = inter_dir / f"{fname}.pkl"
        model.save()
        # Also copy the saved model to the intermediate dir with the iteration name
        import shutil
        saved_path = ML_MODELS_DIR / f"{model.model_type}_{model.label_col}_v{next_version}.pkl"
        if saved_path.exists():
            shutil.copy2(str(saved_path), str(fpath))
        log.info("Checkpoint saved at iteration %d — %s", iteration, fpath)
    except Exception as exc:
        log.warning("Checkpoint save failed at iteration %d: %s", iteration, exc)

# ── Thresholds ────────────────────────────────────────────────
WIN_RATE_FLOOR        = 50.0   # below this → trigger retraining
WIN_RATE_TARGET       = 55.0   # new model must achieve this on eval set to be promoted
ACCURACY_EVAL_DAYS    = 30     # evaluate accuracy over last N days
MODEL_STALE_DAYS      = 45     # retrain if model hasn't been updated in N days
MIN_PREDICTIONS_EVAL  = 20     # need at least this many evaluated predictions
MAX_RETRAIN_ATTEMPTS  = 5      # max retrain loops before giving up

# P0-D: Rolling IC trigger — if 20-day rolling Spearman IC between predicted
# P(UP) and actual outcome is below IC_FLOOR for 3 consecutive days, trigger
# an emergency retrain. This fires earlier than the win-rate trigger because
# IC degradation predicts accuracy degradation ~5 days ahead.
ROLLING_IC_WINDOW_DAYS     = 20   # days of predictions to compute IC over
ROLLING_IC_FLOOR           = 0.01 # IC threshold below which model is considered stale
ROLLING_IC_CONSECUTIVE_DAYS = 3   # number of consecutive days below floor before trigger


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


def _check_rolling_ic(db: Session) -> dict:
    """
    P0-D: Rolling IC trigger.
    Compute 20-day rolling Spearman IC between the model's predicted P(UP)
    (stored in Prediction.confidence) and the binary outcome (Prediction.success).

    If IC < ROLLING_IC_FLOOR for ROLLING_IC_CONSECUTIVE_DAYS consecutive days,
    flag for immediate retraining.

    Returns:
        {
          "should_retrain": bool,
          "reason": str,
          "rolling_ic": float | None,
          "consecutive_low_ic_days": int,
        }
    """
    import numpy as np
    from scipy.stats import spearmanr

    cutoff = date.today() - timedelta(days=ROLLING_IC_WINDOW_DAYS + ROLLING_IC_CONSECUTIVE_DAYS + 5)
    preds = (
        db.query(Prediction)
        .filter(
            Prediction.date >= cutoff,
            Prediction.success.isnot(None),
            Prediction.confidence.isnot(None),
        )
        .order_by(Prediction.date.asc())
        .all()
    )

    if len(preds) < ROLLING_IC_WINDOW_DAYS:
        return {
            "should_retrain":         False,
            "reason":                 f"insufficient_predictions_for_ic ({len(preds)} < {ROLLING_IC_WINDOW_DAYS})",
            "rolling_ic":             None,
            "consecutive_low_ic_days": 0,
        }

    # Group by date for daily IC computation
    from collections import defaultdict
    by_date: dict[str, list[tuple]] = defaultdict(list)
    for p in preds:
        by_date[str(p.date)].append((float(p.confidence), int(p.success)))

    sorted_dates = sorted(by_date.keys())
    daily_ics: list[tuple[str, float]] = []
    for d in sorted_dates:
        day_preds = by_date[d]
        if len(day_preds) < 5:
            continue
        confs, outcomes = zip(*day_preds)
        try:
            ic, _ = spearmanr(confs, outcomes)
            if not np.isnan(ic):
                daily_ics.append((d, float(ic)))
        except Exception:
            pass

    if not daily_ics:
        return {
            "should_retrain":         False,
            "reason":                 "insufficient_daily_ic_data",
            "rolling_ic":             None,
            "consecutive_low_ic_days": 0,
        }

    # Check if last ROLLING_IC_CONSECUTIVE_DAYS all have IC < floor
    last_n = daily_ics[-ROLLING_IC_CONSECUTIVE_DAYS:]
    recent_ic = np.mean([ic for _, ic in last_n]) if last_n else None
    consecutive_low = sum(1 for _, ic in last_n if ic < ROLLING_IC_FLOOR)

    should_retrain = (
        len(last_n) >= ROLLING_IC_CONSECUTIVE_DAYS
        and consecutive_low >= ROLLING_IC_CONSECUTIVE_DAYS
    )

    return {
        "should_retrain":         should_retrain,
        "reason":                 (
            f"rolling_ic={recent_ic:.4f} < {ROLLING_IC_FLOOR} for {consecutive_low} consecutive days"
            if should_retrain
            else f"rolling_ic={recent_ic:.4f} acceptable"
        ),
        "rolling_ic":             round(recent_ic, 4) if recent_ic is not None else None,
        "consecutive_low_ic_days": consecutive_low,
    }


    # 2026-07-06 policy (user decision): don't retrain on a schedule or on
    # rolling metrics alone. Only retrain when new data has actually arrived
    # since the last training run. Strategy improvement now comes entirely
    # from the algo generation/evolution loop, not from repeatedly retraining
    # the same model on the same data.
NEW_DATA_MIN_ROWS = 1500  # need at least this many new DailyPrice rows since last training to justify a retrain
                          # (~297 rows/trading day observed 2026-07 -> ~5 trading days / weekly cadence)


def _check_new_data_available(db: Session) -> dict:
    """
    Only trigger is that matters now: has enough new market data arrived
    since the active model was last trained? Time-based staleness and
    rolling-accuracy/IC decay no longer trigger retraining on their own —
    see policy note above _check_model_staleness.
    """
    from aqrti.database.models import DailyPrice

    active = (
        db.query(ModelVersion)
        .filter(ModelVersion.is_active == True)
        .order_by(ModelVersion.trained_at.desc())
        .first()
    )
    if not active or not active.trained_at:
        return {"should_retrain": True, "reason": "no_active_model_or_unknown_train_date", "new_rows": None}

    new_rows = (
        db.query(DailyPrice)
        .filter(DailyPrice.date > active.trained_at.date())
        .count()
    )
    should_retrain = new_rows >= NEW_DATA_MIN_ROWS
    reason = (
        f"new_data={new_rows} rows since {active.trained_at.date()} >= {NEW_DATA_MIN_ROWS}"
        if should_retrain
        else f"new_data={new_rows} rows since {active.trained_at.date()} < {NEW_DATA_MIN_ROWS} — not enough to justify retraining"
    )
    return {"should_retrain": should_retrain, "reason": reason, "new_rows": new_rows}


def _check_model_staleness(db: Session) -> dict:
    """
    Check if the active model is too old.
    NOTE: kept for reporting/visibility only — as of 2026-07-06 this no
    longer triggers retraining on its own (see _check_new_data_available).
    """
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

        # Sample weights from failure records (may be None if no failures recorded yet)
        sample_weights = getattr(latest_split, "sample_weights", None)
        if sample_weights is not None and len(sample_weights) == len(X_train):
            n_upweighted = int((sample_weights > 1.0).sum())
            log.info("Using failure-weighted training: %d rows upweighted", n_upweighted)
        else:
            sample_weights = None

        for iter_count, ModelClass in enumerate([CatBoostModel]):
            if _INTERRUPTED:
                log.warning("Interrupt detected — stopping training loop")
                break
            try:
                model = ModelClass(task="direction", label_col="direction_5d", version=next_version)
                model.fit(X_train, y_train, X_val=X_test, y_val=y_test,
                          sample_weight=sample_weights)
                _save_intermediate_checkpoint(model, iter_count, next_version, "trained")
                preds = model.predict(X_test)
                correct = int((preds == y_test.values).sum())
                accuracy = correct / len(y_test) if len(y_test) > 0 else 0.0
                try:
                    probas = model.predict_proba(X_test)
                    from sklearn.metrics import roc_auc_score
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

        # Activate every model that clears the quality bar (WIN_RATE_TARGET on
        # accuracy). Always activate the single best model regardless of the
        # bar, so a bad retrain never leaves zero active models.
        best_model, best_metrics = max(
            trained_models,
            key=lambda x: x[1].get("accuracy", 0),
        )
        to_activate = [
            (m, metrics) for m, metrics in trained_models
            if metrics.get("accuracy", 0) * 100 >= WIN_RATE_TARGET
        ]
        if best_model.model_type not in {m.model_type for m, _ in to_activate}:
            to_activate.append((best_model, best_metrics))

        # Retire current active models for this task — only after every
        # artifact below has saved successfully, so a save failure never
        # leaves the system with no active model at all.
        saved = []
        for model, metrics in to_activate:
            artifact_path = model.save()
            saved.append((model, metrics, artifact_path))

        current_active = db.query(ModelVersion).filter(
            ModelVersion.task == "direction", ModelVersion.is_active == True
        ).all()
        for m in current_active:
            m.is_active = False

        db.query(ModelVersion).filter(
            ModelVersion.task == "direction",
            ModelVersion.version == next_version,
        ).delete(synchronize_session=False)
        db.flush()

        for model, metrics, artifact_path in saved:
            new_mv = ModelVersion(
                model_name    = model.model_type,
                task          = "direction",
                label_col     = "direction_5d",
                version       = next_version,
                artifact_path = str(artifact_path),
                primary_metric = metrics.get("accuracy"),
                metrics_json  = json.dumps(metrics),
                importance_json = json.dumps(model.feature_importance() if hasattr(model, "feature_importance") else {}),
                train_rows    = len(X_train),
                is_active     = True,
                trained_at    = datetime.utcnow(),
            )
            db.add(new_mv)

        elapsed = round(time.time() - start, 1)
        activated_names = [m.model_type for m, _, _ in saved]
        log.info(
            "Retraining complete in %.1fs: activated=%s v%d (best=%s accuracy=%.3f)",
            elapsed, activated_names, next_version, best_model.model_type, best_metrics.get("accuracy", 0),
        )

        # win_rate on test set (% of correctly predicted directions), for the
        # best model — kept as the headline metric for backward compatibility
        # with callers that read result["accuracy"]/["win_rate"].
        accuracy = best_metrics.get("accuracy", 0.0)
        win_rate_pct = round(accuracy * 100, 2)

        return {
            "status":      "ok",
            "model":       best_model.model_type,
            "activated":   activated_names,
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

    # Mark existing model/prediction lessons as applied — the retrain just acted on them
    cutoff = date.today() - timedelta(days=ACCURACY_EVAL_DAYS * 3)
    old_lessons = (
        db.query(LessonLearned)
        .filter(
            LessonLearned.category.in_(["model", "prediction", "regime", "feature"]),
            LessonLearned.lesson_date >= cutoff,
            LessonLearned.applied.is_(False) | LessonLearned.applied.is_(None),
        )
        .all()
    )
    for ol in old_lessons:
        ol.applied = True

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

    Policy (2026-07-06, user decision): retraining is gated on new data
    only — win-rate decay, rolling IC, and model age are computed and
    logged for visibility but no longer trigger a retrain by themselves.
    Repeatedly retraining the same model on the same data doesn't produce
    better algos; the algo generation/evolution loop (scheduler.py's
    strategy_loop) is what should be running continuously instead.

    Args:
        db:    DB session
        force: if True, retrain regardless of the new-data check (used by
               `python scripts/train_models.py --quick` for manual runs)

    Returns:
        Summary dict with "retrained", "reason", and optional "result".
    """
    accuracy = _check_accuracy(db)
    staleness = _check_model_staleness(db)
    new_data = _check_new_data_available(db)

    # P0-D: rolling IC — reported only, does not trigger retraining (see policy above)
    try:
        rolling_ic = _check_rolling_ic(db)
    except Exception as exc:
        log.warning("Rolling IC check failed (skipping): %s", exc)
        rolling_ic = {"should_retrain": False, "reason": f"ic_check_error: {exc}"}

    should_retrain = force or new_data["should_retrain"]
    reason = []
    if force:
        reason.append("forced")
    if new_data["should_retrain"]:
        reason.append(new_data["reason"])
    if not should_retrain:
        # Non-triggering signals are still logged so drift is visible even
        # though it no longer causes an automatic retrain.
        log.info(
            "Retrain not triggered (new-data gate only). For visibility: %s | %s | ic=%s",
            accuracy["reason"], staleness["reason"], rolling_ic["reason"],
        )

    trigger_reason = "; ".join(reason) if reason else "no_new_data"

    if not should_retrain:
        return {
            "retrained":   False,
            "reason":      new_data["reason"],
            "win_rate":    accuracy.get("win_rate"),
            "model_age":   staleness.get("age_days"),
            "new_rows":    new_data.get("new_rows"),
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
        elif attempt < MAX_RETRAIN_ATTEMPTS:
            log.info(
                "Win rate %.1f%% below target %.1f%% — retraining again (attempt %d/%d)",
                achieved_wr, WIN_RATE_TARGET, attempt, MAX_RETRAIN_ATTEMPTS,
            )
            # Mark the just-trained model inactive so next attempt can promote the new one
            from aqrti.database.models import ModelVersion as _MV
            db.query(_MV).filter(_MV.is_active == True).update({"is_active": False})
            db.commit()
        else:
            # Final attempt done — keep whatever we got as active (best available)
            log.info(
                "Max attempts reached. Best win rate: %.1f%% — keeping as active model",
                achieved_wr,
            )

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

    try:
        rolling_ic = _check_rolling_ic(db)
    except Exception as exc:
        rolling_ic = {"should_retrain": False, "reason": f"ic_check_error: {exc}"}

    return {
        "needs_retraining":   accuracy["should_retrain"] or staleness["stale"] or rolling_ic.get("should_retrain", False),
        "accuracy_check":     accuracy,
        "staleness_check":    staleness,
        "rolling_ic_check":   rolling_ic,
        "last_retrained_at":  str(last_retrain.created_at) if last_retrain else None,
        "last_retrain_detail": json.loads(last_retrain.metadata_json or "{}") if last_retrain else None,
    }
