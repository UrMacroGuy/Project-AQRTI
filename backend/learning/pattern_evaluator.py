"""
Pattern Evaluator
Assesses the overall quality of pattern-based predictions.

Computes:
  - Hit rate: fraction of pattern predictions that were correct
  - Mean return on pattern-guided predictions vs benchmark
  - IC between similarity score and actual return magnitude
  - Regime-stratified accuracy
  - Whether high-similarity patterns are more accurate

Does NOT modify pattern search logic.
"""

from __future__ import annotations

import sys
import os
from datetime import date, timedelta
from typing import Optional

import numpy as np
from scipy.stats import spearmanr
from sqlalchemy.orm import Session

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from aqrti.database.models import PatternOutcome
from aqrti.utils.logger import get_logger

log = get_logger("pattern_evaluator")

MIN_SAMPLES = 10


def evaluate_pattern_quality(db: Session, days: int = 90) -> dict:
    """
    Overall pattern prediction quality metrics.

    Returns:
      {
        "days": int,
        "total": int,
        "evaluated": int,   # rows with actual_return_5d filled
        "hit_rate": float,
        "avg_return_5d": float,
        "avg_return_10d": float,
        "nifty_outperformance_rate": float,
        "similarity_ic": float,   # IC between similarity_score and |actual_return_5d|
        "by_regime": { REGIME: { "count": n, "hit_rate": x }, ... }
      }
    """
    cutoff = date.today() - timedelta(days=days)
    rows   = (
        db.query(PatternOutcome)
        .filter(PatternOutcome.prediction_date >= cutoff)
        .all()
    )
    evaluated = [r for r in rows if r.actual_return_5d is not None]

    if len(evaluated) < MIN_SAMPLES:
        return {
            "days":      days,
            "total":     len(rows),
            "evaluated": len(evaluated),
            "available": False,
        }

    correct    = [r for r in evaluated if r.was_correct]
    hit_rate   = len(correct) / len(evaluated) * 100

    avg_5d     = sum(r.actual_return_5d  for r in evaluated) / len(evaluated)
    avg_10d    = sum((r.actual_return_10d or 0) for r in evaluated) / len(evaluated)
    nifty_out  = sum(1 for r in evaluated if r.outperformed_nifty) / len(evaluated) * 100

    # Similarity IC
    sim_scores  = [r.similarity_score or 0.0 for r in evaluated]
    abs_returns = [abs(r.actual_return_5d or 0.0) for r in evaluated]
    sim_ic      = 0.0
    if len(sim_scores) >= 5:
        result  = spearmanr(sim_scores, abs_returns)
        sim_ic  = round(float(result.correlation), 4) if not np.isnan(result.correlation) else 0.0

    # By regime
    by_regime: dict[str, dict] = {}
    for r in evaluated:
        reg = r.regime_at or "UNKNOWN"
        by_regime.setdefault(reg, {"count": 0, "correct": 0})
        by_regime[reg]["count"]   += 1
        by_regime[reg]["correct"] += int(bool(r.was_correct))

    for reg, data in by_regime.items():
        data["hit_rate"] = round(data["correct"] / data["count"] * 100, 2)

    return {
        "days":                     days,
        "total":                    len(rows),
        "evaluated":                len(evaluated),
        "available":                True,
        "hit_rate":                 round(hit_rate, 2),
        "avg_return_5d":            round(avg_5d, 4),
        "avg_return_10d":           round(avg_10d, 4),
        "nifty_outperformance_rate": round(nifty_out, 2),
        "similarity_ic":            sim_ic,
        "by_regime":                by_regime,
    }


def evaluate_by_similarity_tier(db: Session, days: int = 90) -> list[dict]:
    """
    Break down pattern accuracy by similarity tier:
      high    (>=0.85), medium (0.70-0.85), low (<0.70)
    """
    cutoff = date.today() - timedelta(days=days)
    rows   = (
        db.query(PatternOutcome)
        .filter(
            PatternOutcome.prediction_date >= cutoff,
            PatternOutcome.actual_return_5d.isnot(None),
        )
        .all()
    )

    tiers: dict[str, dict] = {
        "high":   {"min": 0.85, "max": 1.01, "count": 0, "correct": 0},
        "medium": {"min": 0.70, "max": 0.85, "count": 0, "correct": 0},
        "low":    {"min": 0.00, "max": 0.70, "count": 0, "correct": 0},
    }

    for r in rows:
        sim = r.similarity_score or 0.0
        for tier, bounds in tiers.items():
            if bounds["min"] <= sim < bounds["max"]:
                bounds["count"]   += 1
                bounds["correct"] += int(bool(r.was_correct))
                break

    results = []
    for tier, d in tiers.items():
        results.append({
            "tier":     tier,
            "count":    d["count"],
            "hit_rate": round(d["correct"] / d["count"] * 100, 2) if d["count"] else None,
        })
    return results
