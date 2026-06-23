"""
Weight Optimizer
Computes recommended ensemble weights from rolling model performance.

This module:
  - Reads ModelDriftHistory and ModelMetric for recent windows
  - Applies softmax-over-IC to compute proportional weights
  - Returns recommended weights WITHOUT applying them automatically
  - Logs a KnowledgeEvent for the suggested rebalance

Does NOT retrain models. Does NOT write to model_weights table.
Call apply_weights() only when explicitly requested.
"""

from __future__ import annotations

import sys
import os
import json
from datetime import date, timedelta
from typing import Optional

import numpy as np
from sqlalchemy.orm import Session

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from aqrti.database.models import ModelDriftHistory, ModelWeight, KnowledgeEvent
from aqrti.utils.logger import get_logger

log = get_logger("weight_optimizer")

WEIGHT_FLOOR  = 0.05     # minimum weight any model receives
WEIGHT_CAP    = 0.60     # maximum weight any single model receives
SOFTMAX_TEMP  = 0.5      # temperature for softmax; lower = sharper difference


def _softmax(scores: list[float], temperature: float = 1.0) -> list[float]:
    arr = np.array(scores, dtype=float) / temperature
    arr -= arr.max()                   # numerical stability
    exp  = np.exp(arr)
    return (exp / exp.sum()).tolist()


def _clamp_weights(raw_weights: dict[str, float]) -> dict[str, float]:
    """Apply floor and cap then renormalise so weights sum to 1.0."""
    clamped = {k: max(WEIGHT_FLOOR, min(WEIGHT_CAP, v)) for k, v in raw_weights.items()}
    total   = sum(clamped.values())
    return {k: round(v / total, 6) for k, v in clamped.items()}


def compute_recommended_weights(
    db:      Session,
    task:    str   = "direction",
    days:    int   = 30,
) -> dict:
    """
    Compute optimal ensemble weights for all active models for a given task.

    Strategy:
      1. Fetch most recent drift snapshot per model for the requested window
      2. Use IC as the primary quality signal (accuracy as fallback)
      3. Apply softmax to IC scores → proportional weights
      4. Clamp to [WEIGHT_FLOOR, WEIGHT_CAP] and renormalise

    Returns:
      {
        "task": ...,
        "days": ...,
        "recommended": { model_name: weight, ... },
        "current":     { model_name: weight, ... },
        "signal_used": "ic"|"accuracy",
        "model_scores": { model_name: score, ... },
      }
    """
    cutoff = date.today() - timedelta(days=days)

    # Latest snapshot per model
    rows = (
        db.query(ModelDriftHistory)
        .filter(
            ModelDriftHistory.task         == task,
            ModelDriftHistory.measured_date >= cutoff,
        )
        .order_by(ModelDriftHistory.model_name, ModelDriftHistory.measured_date.desc())
        .all()
    )

    seen     = set()
    latest   = []
    for r in rows:
        if r.model_name not in seen:
            latest.append(r)
            seen.add(r.model_name)

    if not latest:
        log.info("No drift history for task=%s in last %d days", task, days)
        return {"task": task, "days": days, "recommended": {}, "current": {}}

    # Determine which signal to use
    use_ic    = all(r.ic is not None for r in latest)
    signal    = "ic" if use_ic else "accuracy"
    raw_scores = {r.model_name: float(r.ic or 0) if use_ic else float(r.accuracy or 50) for r in latest}

    # For IC, shift to [0, 1] so softmax is well-behaved
    if use_ic:
        shifted = {k: v + 1.0 for k, v in raw_scores.items()}
    else:
        shifted = raw_scores

    names  = list(shifted.keys())
    scores = [shifted[n] for n in names]
    sm     = _softmax(scores, SOFTMAX_TEMP)
    raw_w  = dict(zip(names, sm))
    rec_w  = _clamp_weights(raw_w)

    # Current weights
    cur_rows = db.query(ModelWeight).filter(ModelWeight.task == task).all()
    cur_w    = {r.model_name: r.weight for r in cur_rows}

    log.info("Weight recommendation for task=%s: %s", task, rec_w)
    return {
        "task":          task,
        "days":          days,
        "recommended":   rec_w,
        "current":       cur_w,
        "signal_used":   signal,
        "model_scores":  raw_scores,
    }


def record_weight_recommendation(db: Session, task: str = "direction", days: int = 30) -> dict:
    """
    Compute weights and log a KnowledgeEvent for the suggested rebalance.
    Does NOT apply the weights.
    """
    result = compute_recommended_weights(db, task=task, days=days)
    if not result.get("recommended"):
        return result

    rec   = result["recommended"]
    cur   = result.get("current", {})
    delta = {k: round(rec.get(k, 0) - cur.get(k, 0), 4) for k in set(rec) | set(cur)}

    event = KnowledgeEvent(
        event_date  = date.today(),
        category    = "model",
        event_type  = "weight_recommendation",
        description = (
            f"Optimal ensemble weights computed for task={task}. "
            f"Signal: {result['signal_used']}. "
            f"Recommended: {json.dumps(rec)}."
        ),
        outcome     = "neutral",
        magnitude   = max(abs(v) for v in delta.values()) * 100 if delta else 0.0,
        metadata_json = json.dumps({
            "task":          task,
            "recommended":   rec,
            "current":       cur,
            "delta":         delta,
            "signal":        result["signal_used"],
        }),
    )
    db.add(event)
    db.commit()
    result["event_id"] = event.id
    log.info("Weight recommendation event logged for task=%s", task)
    return result


def apply_weights(
    db:      Session,
    weights: dict[str, float],
    task:    str = "direction",
) -> dict:
    """
    Write recommended weights to ModelWeight table.
    This is intentionally separate from compute_recommended_weights so that
    auto-apply is never triggered by analysis runs.

    Call this explicitly when the architect approves the recommendation.
    """
    for model_name, weight in weights.items():
        row = (
            db.query(ModelWeight)
            .filter(ModelWeight.model_name == model_name, ModelWeight.task == task)
            .first()
        )
        if row:
            row.weight = weight
        else:
            db.add(ModelWeight(model_name=model_name, task=task, weight=weight))

    db.commit()
    log.info("Weights applied for task=%s: %s", task, weights)
    return {"applied": True, "task": task, "weights": weights}
