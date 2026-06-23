"""
Confidence Audit
Generates calibration curves and per-bucket statistics.

For each confidence bucket (50-60, 60-70, 70-80, 80-90, 90+) it computes:
  - Count of predictions
  - Average stated confidence
  - Actual accuracy in that bucket
  - Calibration gap (stated - actual)
  - Whether overconfidence or underconfidence

Does NOT modify any weights or predictions.
"""

from __future__ import annotations

import sys
import os

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from datetime import date, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from aqrti.database.models import Prediction
from aqrti.utils.logger import get_logger

log = get_logger("confidence_audit")

BUCKETS = [
    ("50-60",  50, 60),
    ("60-70",  60, 70),
    ("70-80",  70, 80),
    ("80-90",  80, 90),
    ("90+",    90, 101),
]


def _bucket_for(conf: float) -> str:
    for label, lo, hi in BUCKETS:
        if lo <= conf < hi:
            return label
    return "50-60"


def build_calibration_curve(db: Session, days: int = 30) -> dict:
    """
    Compute calibration curve: stated confidence vs actual accuracy per bucket.

    Returns:
      {
        "days": ...,
        "total": ...,
        "evaluated": ...,
        "ece": float,
        "buckets": [
          {
            "bucket": "70-80", "count": 23, "avg_confidence": 74.2,
            "accuracy": 61.5, "gap": 12.7, "bias": "overconfident"
          }, ...
        ],
        "overall_accuracy": ...,
        "recommendation": str
      }
    """
    cutoff = date.today() - timedelta(days=days)
    preds  = (
        db.query(Prediction)
        .filter(
            Prediction.date >= cutoff,
            Prediction.confidence.isnot(None),
            Prediction.actual_return.isnot(None),
        )
        .all()
    )

    data: dict[str, dict] = {b[0]: {"conf_sum": 0.0, "correct": 0, "n": 0} for b in BUCKETS}

    for p in preds:
        c   = p.confidence or 50.0
        bkt = _bucket_for(c)
        ok  = (
            (p.direction == "Bullish" and (p.actual_return or 0) > 0) or
            (p.direction == "Bearish" and (p.actual_return or 0) < 0)
        )
        data[bkt]["conf_sum"] += c
        data[bkt]["correct"]  += int(ok)
        data[bkt]["n"]        += 1

    total = len(preds)
    results = []
    ece     = 0.0
    overall_correct = 0

    for label, lo, hi in BUCKETS:
        d = data[label]
        n = d["n"]
        if n == 0:
            results.append({"bucket": label, "count": 0, "avg_confidence": (lo + hi) / 2,
                             "accuracy": None, "gap": None, "bias": "unknown"})
            continue
        avg_conf = d["conf_sum"] / n
        accuracy = d["correct"] / n * 100
        gap      = avg_conf - accuracy
        bias     = "overconfident" if gap > 2 else ("underconfident" if gap < -2 else "well-calibrated")
        overall_correct += d["correct"]
        ece += (n / total) * abs(gap / 100)
        results.append({
            "bucket":         label,
            "count":          n,
            "avg_confidence": round(avg_conf, 2),
            "accuracy":       round(accuracy, 2),
            "gap":            round(gap, 2),
            "bias":           bias,
        })

    overall_acc = overall_correct / total * 100 if total else 0.0

    # Recommendation
    worst_gap = max((abs(r["gap"]) for r in results if r["gap"] is not None), default=0.0)
    if worst_gap > 15:
        rec = "Significant miscalibration detected. Retrain calibration layer with recent data."
    elif worst_gap > 8:
        rec = "Moderate overconfidence in upper buckets. Apply Platt scaling on 80-90 and 90+ buckets."
    else:
        rec = "Calibration is within acceptable range. Continue monitoring."

    log.info("Calibration audit: total=%d ece=%.4f overall_acc=%.1f%%", total, ece, overall_acc)
    return {
        "days":             days,
        "total":            total,
        "evaluated":        total,
        "ece":              round(ece, 6),
        "buckets":          results,
        "overall_accuracy": round(overall_acc, 2),
        "recommendation":   rec,
    }


def get_overconfidence_symbols(db: Session, days: int = 30, min_count: int = 3) -> list[dict]:
    """
    Return symbols that are systematically overconfident — high confidence predictions
    that repeatedly fail.
    """
    cutoff = date.today() - timedelta(days=days)
    preds  = (
        db.query(Prediction)
        .filter(
            Prediction.date      >= cutoff,
            Prediction.confidence >= 75,
            Prediction.actual_return.isnot(None),
        )
        .all()
    )

    by_symbol: dict[str, dict] = {}
    for p in preds:
        s  = p.symbol
        ok = (
            (p.direction == "Bullish" and (p.actual_return or 0) > 0) or
            (p.direction == "Bearish" and (p.actual_return or 0) < 0)
        )
        bs = by_symbol.setdefault(s, {"n": 0, "correct": 0, "conf_sum": 0.0})
        bs["n"]        += 1
        bs["correct"]  += int(ok)
        bs["conf_sum"] += (p.confidence or 75)

    results = []
    for sym, stats in by_symbol.items():
        if stats["n"] < min_count:
            continue
        acc      = stats["correct"] / stats["n"] * 100
        avg_conf = stats["conf_sum"] / stats["n"]
        gap      = avg_conf - acc
        if gap > 10:
            results.append({
                "symbol":       sym,
                "predictions":  stats["n"],
                "accuracy":     round(acc, 2),
                "avg_confidence": round(avg_conf, 2),
                "calibration_gap": round(gap, 2),
            })

    results.sort(key=lambda x: x["calibration_gap"], reverse=True)
    return results
