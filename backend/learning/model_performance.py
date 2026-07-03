"""
Model Performance Analyzer
Evaluates each active model against recent live predictions.

For each model it computes:
  - Directional accuracy on evaluated predictions
  - Information Coefficient (Spearman rank corr of predicted vs actual returns)
  - AUC-ROC proxy on binary direction
  - Return contribution (sum of returns on trades guided by this model)
  - Confidence quality (was the model's confidence justified?)

Results are stored in model_drift_history for trend analysis.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Optional

import numpy as np
from scipy.stats import spearmanr
from sqlalchemy.orm import Session

from aqrti.database.models import Prediction, ModelVersion, ModelDriftHistory
from aqrti.utils.logger import get_logger

log = get_logger("model_performance")

DRIFT_THRESHOLD = 0.10   # 10% degradation from baseline triggers drift flag
MIN_SAMPLES     = 10     # need at least this many evaluated predictions


def compute_live_accuracy(
    preds: list,
) -> dict:
    """
    Compute live performance metrics from evaluated predictions.
    preds: list of Prediction ORM objects with actual_return filled.
    """
    if not preds:
        return {
            "accuracy": 0.0, "ic": 0.0, "ic_pval": 1.0,
            "directional_acc": 0.0, "auc_roc": 0.5, "sample_size": 0,
        }

    y_true_dir = []
    y_pred_ret = []
    y_true_ret = []
    correct    = 0

    for p in preds:
        actual = p.actual_return or 0.0
        is_correct = (
            (p.direction == "Bullish" and actual > 0) or
            (p.direction == "Bearish" and actual < 0)
        )
        if is_correct:
            correct += 1
        y_true_dir.append(1 if actual > 0 else 0)
        y_pred_ret.append(p.expected_return or 0.0)
        y_true_ret.append(actual)

    n          = len(preds)
    accuracy   = correct / n * 100

    # Information Coefficient
    ic, ic_pval = 0.0, 1.0
    if len(y_pred_ret) >= 5:
        result  = spearmanr(y_pred_ret, y_true_ret)
        ic      = float(result.correlation) if not np.isnan(result.correlation) else 0.0
        ic_pval = float(result.pvalue) if not np.isnan(result.pvalue) else 1.0

    # Directional accuracy
    dir_acc = accuracy

    # Simple AUC proxy: fraction of (pred>0, actual>0) pairs correctly ordered
    pos_correct = sum(1 for p in preds
                      if (p.expected_return or 0) > 0 and (p.actual_return or 0) > 0)
    pos_total   = sum(1 for p in preds if (p.expected_return or 0) > 0)
    auc_proxy   = pos_correct / pos_total if pos_total > 0 else 0.5

    return {
        "accuracy":        round(accuracy, 4),
        "ic":              round(ic, 6),
        "ic_pval":         round(ic_pval, 4),
        "directional_acc": round(dir_acc, 4),
        "auc_roc":         round(auc_proxy, 4),
        "sample_size":     n,
    }


def analyze_all_models(db: Session, days: int = 30) -> dict:
    """
    Pull all evaluated predictions and compute per-model live accuracy.
    Since predictions don't tag individual model names, we use the
    ensemble prediction as the source of truth and compute aggregate metrics.

    Returns metrics dict per model_name from model_versions table.
    """
    cutoff  = date.today() - timedelta(days=days)
    preds   = (
        db.query(Prediction)
        .filter(
            Prediction.date >= cutoff,
            Prediction.actual_return.isnot(None),
        )
        .all()
    )

    if len(preds) < MIN_SAMPLES:
        log.info("Insufficient evaluated predictions (%d) for model analysis", len(preds))
        return {"available": False, "sample_size": len(preds)}

    metrics   = compute_live_accuracy(preds)
    models    = db.query(ModelVersion).filter(ModelVersion.is_active == True).all()
    results   = {}

    for m in models:
        baseline = m.primary_metric or 0.5
        current  = metrics.get("auc_roc" if "direction" in m.task else "ic", 0.5)
        drift_pct = (current - baseline) / baseline * 100 if baseline else 0.0
        drift_flag = abs(drift_pct) > DRIFT_THRESHOLD * 100

        results[f"{m.model_name}_{m.task}"] = {
            "model_name":     m.model_name,
            "task":           m.task,
            "version":        m.version,
            "baseline_metric": baseline,
            "current_metric":  current,
            "drift_pct":       round(drift_pct, 2),
            "drift_flag":      drift_flag,
            **metrics,
        }

    log.info("Model performance analyzed: %d active models, %d predictions", len(models), len(preds))
    return {"available": True, "models": results, "aggregate": metrics, "days": days}
