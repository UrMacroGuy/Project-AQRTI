"""
Model Drift Detector
Computes rolling accuracy windows per model and writes to ModelDriftHistory.
Drift is flagged when current accuracy degrades >10% from the baseline.

Does NOT modify model weights or trigger retraining.
"""

from __future__ import annotations

import sys
import os

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from datetime import date, timedelta

from sqlalchemy.orm import Session

from aqrti.database.models import ModelVersion, ModelDriftHistory, Prediction
from aqrti.utils.logger import get_logger
from learning.model_performance import compute_live_accuracy, MIN_SAMPLES

log = get_logger("model_drift")

DRIFT_THRESHOLD_PCT = 10.0   # flag if accuracy drops >10% below baseline
WINDOW_OPTIONS      = [7, 14, 30, 60, 90]


def _predictions_for_window(db: Session, days: int) -> list:
    cutoff = date.today() - timedelta(days=days)
    return (
        db.query(Prediction)
        .filter(
            Prediction.date >= cutoff,
            Prediction.actual_return.isnot(None),
        )
        .all()
    )


def _already_recorded(db: Session, model_name: str, task: str, version: str,
                       measured_date: date, window_days: int) -> bool:
    return bool(
        db.query(ModelDriftHistory.id)
        .filter(
            ModelDriftHistory.model_name    == model_name,
            ModelDriftHistory.task          == task,
            ModelDriftHistory.version       == version,
            ModelDriftHistory.measured_date == measured_date,
            ModelDriftHistory.window_days   == window_days,
        )
        .first()
    )


def record_drift_snapshot(
    db:          Session,
    model:       ModelVersion,
    window_days: int = 30,
    today:       date | None = None,
) -> ModelDriftHistory | None:
    """
    Compute live metrics for one model over window_days and write a drift row.
    Returns None if there aren't enough evaluated predictions.
    """
    today = today or date.today()

    if _already_recorded(db, model.model_name, model.task, model.version, today, window_days):
        log.debug("Drift snapshot already exists for %s/%s w=%d", model.model_name, model.task, window_days)
        return None

    preds = _predictions_for_window(db, window_days)
    if len(preds) < MIN_SAMPLES:
        log.info("Skipping drift snapshot for %s — only %d predictions", model.model_name, len(preds))
        return None

    m           = compute_live_accuracy(preds)
    baseline    = model.primary_metric or 0.5
    current     = m.get("auc_roc", 0.5) if "direction" in (model.task or "") else m.get("ic", 0.0)
    drift_pct   = (current - baseline) / abs(baseline) * 100 if baseline else 0.0
    drift_flag  = drift_pct < -DRIFT_THRESHOLD_PCT

    row = ModelDriftHistory(
        model_name     = model.model_name,
        task           = model.task,
        version        = model.version,
        measured_date  = today,
        window_days    = window_days,
        accuracy       = m.get("accuracy"),
        auc_roc        = m.get("auc_roc"),
        ic             = m.get("ic"),
        directional_acc= m.get("directional_acc"),
        baseline_metric= baseline,
        drift_pct      = round(drift_pct, 2),
        drift_flag     = drift_flag,
        sample_size    = m.get("sample_size", 0),
    )
    db.add(row)
    log.info(
        "Drift snapshot: %s/%s w=%d acc=%.1f drift=%.1f%% flag=%s",
        model.model_name, model.task, window_days,
        m.get("accuracy", 0), drift_pct, drift_flag,
    )
    return row


def run_drift_detection(
    db:      Session,
    windows: list[int] | None = None,
) -> dict:
    """
    Run drift detection across all active models and all requested windows.
    Commits results to ModelDriftHistory.

    Returns summary of what was recorded.
    """
    windows   = windows or [30, 90]
    models    = db.query(ModelVersion).filter(ModelVersion.is_active == True).all()
    recorded  = 0
    skipped   = 0
    flagged   = []

    for m in models:
        for w in windows:
            row = record_drift_snapshot(db, m, window_days=w)
            if row is None:
                skipped += 1
            else:
                recorded += 1
                if row.drift_flag:
                    flagged.append({
                        "model":    m.model_name,
                        "task":     m.task,
                        "window":   w,
                        "drift_pct": row.drift_pct,
                    })

    db.commit()
    log.info("Drift detection: recorded=%d skipped=%d flagged=%d", recorded, skipped, len(flagged))
    return {
        "models_checked": len(models),
        "windows":        windows,
        "recorded":       recorded,
        "skipped":        skipped,
        "flagged":        flagged,
    }


def get_drift_summary(db: Session, days: int = 90) -> dict:
    """Return recent drift history grouped by model for API/dashboard use."""
    cutoff = date.today() - timedelta(days=days)
    rows   = (
        db.query(ModelDriftHistory)
        .filter(ModelDriftHistory.measured_date >= cutoff)
        .order_by(ModelDriftHistory.measured_date.desc())
        .all()
    )

    by_model: dict[str, list[dict]] = {}
    for r in rows:
        key = f"{r.model_name}_{r.task}"
        by_model.setdefault(key, []).append({
            "date":         str(r.measured_date),
            "window_days":  r.window_days,
            "accuracy":     r.accuracy,
            "ic":           r.ic,
            "auc_roc":      r.auc_roc,
            "drift_pct":    r.drift_pct,
            "drift_flag":   r.drift_flag,
            "sample_size":  r.sample_size,
        })

    flagged_count = sum(1 for r in rows if r.drift_flag)
    return {
        "days":          days,
        "total_snapshots": len(rows),
        "flagged_count": flagged_count,
        "by_model":      by_model,
    }
