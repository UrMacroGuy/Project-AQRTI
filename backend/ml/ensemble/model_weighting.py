"""
AQRTI Model Weighting
Computes dynamic weights for ensemble members based on recent validation performance.
Better-performing models get higher influence in the ensemble.

Weighting strategy:
  - Primary metric per task: AUC-ROC (classification) or IC (regression)
  - Weights computed from latest fold metrics stored in model_metrics table
  - Softmax normalization ensures weights sum to 1.0
  - Minimum weight floor of 0.10 prevents complete exclusion of any model
"""

from __future__ import annotations

import numpy as np
from aqrti.utils.logger import get_logger

log = get_logger("model_weighting")

MIN_WEIGHT    = 0.10
SOFTMAX_TEMP  = 2.0   # temperature: lower = more winner-takes-all

# Fallback equal weights when no performance data exists
EQUAL_WEIGHTS = {"catboost": 1/3, "ngboost": 1/3, "aqrtinet": 1/3}


def _softmax(scores: dict[str, float], temperature: float = SOFTMAX_TEMP) -> dict[str, float]:
    """Softmax with temperature scaling."""
    models = list(scores.keys())
    vals   = np.array([scores[m] for m in models], dtype=float)
    vals   = vals / temperature
    vals   = vals - vals.max()          # numerical stability
    exps   = np.exp(vals)
    probs  = exps / exps.sum()
    return dict(zip(models, probs.tolist()))


def compute_weights_from_metrics(
    fold_metrics: dict[str, float],
    task: str,
) -> dict[str, float]:
    """
    Compute ensemble weights from a dict of {model_name: primary_metric_value}.

    Args:
        fold_metrics: {model_name: metric_value} — higher is better for all metrics
        task:         "direction" | "expected_return" | "outperformance"

    Returns:
        {model_name: weight} normalized to sum=1.0 with min floor applied
    """
    if not fold_metrics:
        return EQUAL_WEIGHTS.copy()

    # Apply softmax
    weights = _softmax(fold_metrics)

    # Apply minimum weight floor
    total_floor = MIN_WEIGHT * len(weights)
    if total_floor >= 1.0:
        return {m: 1.0 / len(weights) for m in weights}

    deficit = 0.0
    floored = {}
    for m, w in weights.items():
        if w < MIN_WEIGHT:
            deficit += MIN_WEIGHT - w
            floored[m] = MIN_WEIGHT
        else:
            floored[m] = w

    # Redistribute deficit from above-floor models
    above = {m: w for m, w in floored.items() if w > MIN_WEIGHT}
    above_total = sum(above.values())
    if above_total > 0:
        for m in above:
            floored[m] -= deficit * (floored[m] / above_total)

    # Normalize to exactly 1.0
    total = sum(floored.values())
    return {m: w / total for m, w in floored.items()}


def load_dynamic_weights(task: str, version: int = 1) -> dict[str, float]:
    """
    Load latest walk-forward metrics from DB and compute dynamic weights.
    Falls back to equal weights if no data exists.
    """
    try:
        from aqrti.database.engine import get_db
        from aqrti.database.models import ModelMetric

        primary = "auc_roc" if task == "direction" else "ic"

        with get_db() as db:
            # LightGBM/XGBoost were removed from the active ensemble 2026-06-27
            # (sub-coin-flip accuracy) — the training loop only ever produces
            # catboost/ngboost/aqrtinet versions now (model_retrainer.py), so
            # computing weights for the retired two was always a no-op that
            # produced misleading log output.
            model_names = ["catboost", "ngboost", "aqrtinet"]
            scores = {}
            for model_name in model_names:
                # Most recent test-fold metric
                row = (
                    db.query(ModelMetric)
                    .filter_by(model_name=model_name, task=task, version=version,
                               metric_name=primary, split="test")
                    .order_by(ModelMetric.computed_at.desc())
                    .first()
                )
                if row:
                    scores[model_name] = float(row.metric_value)

        if not scores:
            log.info("No metric data for task=%s — using equal weights", task)
            return EQUAL_WEIGHTS.copy()

        weights = compute_weights_from_metrics(scores, task)
        log.info("Dynamic weights for task=%s: %s", task,
                 {m: round(w, 3) for m, w in weights.items()})
        return weights

    except Exception as exc:
        log.warning("load_dynamic_weights failed (%s) — using equal weights", exc)
        return EQUAL_WEIGHTS.copy()
