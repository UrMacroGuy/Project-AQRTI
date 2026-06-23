"""
AQRTI Validation Metrics
All metrics used to evaluate prediction quality.

For classification (direction prediction):
  - Accuracy, F1, AUC-ROC, Hit Rate

For regression (return prediction):
  - MAE, RMSE, IC (Information Coefficient = Spearman rank correlation),
    Directional Accuracy, Mean Return @ Top Quintile

Quantitative finance standard: IC >= 0.05 is useful, IC >= 0.10 is strong.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.metrics import (
    accuracy_score, f1_score, roc_auc_score,
    mean_absolute_error, mean_squared_error,
)

from aqrti.utils.logger import get_logger

log = get_logger("metrics")


def compute_classification_metrics(
    y_true: np.ndarray | pd.Series,
    y_pred: np.ndarray,
    y_proba: np.ndarray,
) -> dict:
    """
    Classification metrics for direction prediction.

    Returns:
        accuracy, f1, auc_roc, hit_rate (= accuracy for binary),
        positive_precision, positive_recall
    """
    y_true = np.array(y_true)
    y_pred = np.array(y_pred)
    y_proba = np.array(y_proba)

    metrics: dict = {}

    try:
        metrics["accuracy"]  = float(accuracy_score(y_true, y_pred))
        metrics["hit_rate"]  = metrics["accuracy"]
        metrics["f1"]        = float(f1_score(y_true, y_pred, zero_division=0))
    except Exception:
        metrics["accuracy"]  = 0.0
        metrics["hit_rate"]  = 0.0
        metrics["f1"]        = 0.0

    try:
        if len(np.unique(y_true)) == 2:
            metrics["auc_roc"] = float(roc_auc_score(y_true, y_proba))
        else:
            metrics["auc_roc"] = 0.5
    except Exception:
        metrics["auc_roc"] = 0.5

    # Precision / recall on positive class
    tp = np.sum((y_pred == 1) & (y_true == 1))
    fp = np.sum((y_pred == 1) & (y_true == 0))
    fn = np.sum((y_pred == 0) & (y_true == 1))
    metrics["positive_precision"] = float(tp / (tp + fp)) if (tp + fp) > 0 else 0.0
    metrics["positive_recall"]    = float(tp / (tp + fn)) if (tp + fn) > 0 else 0.0

    return metrics


def compute_regression_metrics(
    y_true: np.ndarray | pd.Series,
    y_pred: np.ndarray,
) -> dict:
    """
    Regression metrics for return prediction.

    Returns:
        mae, rmse, ic (Information Coefficient), directional_accuracy,
        mean_return_top_quintile, sharpe_proxy
    """
    y_true = np.array(y_true, dtype=float)
    y_pred = np.array(y_pred, dtype=float)

    metrics: dict = {}

    try:
        metrics["mae"]  = float(mean_absolute_error(y_true, y_pred))
        metrics["rmse"] = float(np.sqrt(mean_squared_error(y_true, y_pred)))
    except Exception:
        metrics["mae"]  = float("inf")
        metrics["rmse"] = float("inf")

    # Information Coefficient (Spearman rank correlation)
    try:
        ic, ic_pval = stats.spearmanr(y_pred, y_true)
        metrics["ic"]      = float(ic) if not np.isnan(ic) else 0.0
        metrics["ic_pval"] = float(ic_pval) if not np.isnan(ic_pval) else 1.0
    except Exception:
        metrics["ic"]      = 0.0
        metrics["ic_pval"] = 1.0

    # Directional accuracy: do signs agree?
    try:
        sign_agree = np.sign(y_pred) == np.sign(y_true)
        metrics["directional_accuracy"] = float(sign_agree.mean())
    except Exception:
        metrics["directional_accuracy"] = 0.5

    # Mean return at top quintile (rank by prediction, take top 20% of predicted)
    try:
        if len(y_pred) >= 10:
            threshold = np.percentile(y_pred, 80)
            top_mask  = y_pred >= threshold
            metrics["mean_return_top_quintile"] = float(y_true[top_mask].mean())
        else:
            metrics["mean_return_top_quintile"] = float(y_true.mean())
    except Exception:
        metrics["mean_return_top_quintile"] = 0.0

    # Sharpe proxy: mean predicted return / std of actual returns (simplified)
    try:
        if y_true.std() > 0:
            metrics["sharpe_proxy"] = float(y_true[y_pred > 0].mean() / y_true.std())
        else:
            metrics["sharpe_proxy"] = 0.0
    except Exception:
        metrics["sharpe_proxy"] = 0.0

    return metrics


def compute_metrics(
    y_true: np.ndarray | pd.Series,
    y_pred: np.ndarray,
    y_proba: np.ndarray,
    task: str,
) -> dict:
    """
    Dispatch to the correct metric set based on task.

    Args:
        task: "direction" → classification metrics
              "expected_return" | "outperformance" → regression metrics
    """
    if task == "direction":
        return compute_classification_metrics(y_true, y_pred, y_proba)
    else:
        return compute_regression_metrics(y_true, y_pred)


def aggregate_fold_metrics(fold_metrics: list[dict]) -> dict:
    """
    Aggregate per-fold metrics into mean ± std across all folds.
    Used to summarize walk-forward results.
    """
    if not fold_metrics:
        return {}

    keys = fold_metrics[0].keys()
    result = {}
    for key in keys:
        values = [m[key] for m in fold_metrics if key in m and m[key] is not None]
        if values:
            result[f"{key}_mean"] = float(np.mean(values))
            result[f"{key}_std"]  = float(np.std(values))
            result[f"{key}_min"]  = float(np.min(values))
            result[f"{key}_max"]  = float(np.max(values))
    return result
