"""
Confidence Retrainer
Computes per-bucket confidence scaling adjustments based on calibration audit.

Does NOT modify ML model weights. Stores scaling coefficients as KnowledgeEvents
so future prediction pipelines can query and apply them.

Scaling strategy:
  - If bucket accuracy < stated confidence → scale down (overcorrect)
  - If bucket accuracy > stated confidence → scale up
  - Linear interpolation between bucket midpoints for smoothing
"""

from __future__ import annotations

import sys
import os
import json
from datetime import date

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from sqlalchemy.orm import Session

from aqrti.database.models import KnowledgeEvent
from aqrti.utils.logger import get_logger
from learning.confidence_audit import build_calibration_curve

log = get_logger("confidence_retrainer")

ADJUSTMENT_CAP = 0.20   # max +/- 20 pp adjustment per bucket


def compute_scaling_table(db: Session, days: int = 30) -> dict:
    """
    Derive a confidence scaling table from the calibration audit.

    For each bucket with enough data, computes:
      scale_factor = actual_accuracy / stated_confidence

    Returns:
      {
        "days": ...,
        "ece": ...,
        "scaling_table": {
          "50-60": { "scale_factor": 0.92, "adjustment": -4.2, "samples": 15 },
          ...
        },
        "apply_recommended": True|False
      }
    """
    curve  = build_calibration_curve(db, days=days)
    table  = {}

    for b in curve["buckets"]:
        if b["count"] < 5 or b["accuracy"] is None:
            table[b["bucket"]] = {"scale_factor": 1.0, "adjustment": 0.0, "samples": b["count"]}
            continue

        stated  = b["avg_confidence"] / 100.0
        actual  = b["accuracy"]       / 100.0
        if stated == 0:
            sf = 1.0
        else:
            sf = min(max(actual / stated, 0.5), 1.5)

        # Adjustment in percentage points
        adj = (actual - stated) * 100
        adj = max(-ADJUSTMENT_CAP * 100, min(ADJUSTMENT_CAP * 100, adj))

        table[b["bucket"]] = {
            "scale_factor": round(sf, 4),
            "adjustment":   round(adj, 2),
            "samples":      b["count"],
        }

    apply_rec = curve["ece"] > 0.05   # recommend applying if ECE > 5%

    log.info("Scaling table computed: ece=%.4f apply_recommended=%s", curve["ece"], apply_rec)
    return {
        "days":               days,
        "ece":                curve["ece"],
        "overall_accuracy":   curve["overall_accuracy"],
        "scaling_table":      table,
        "apply_recommended":  apply_rec,
        "recommendation":     curve["recommendation"],
    }


def record_scaling_recommendation(db: Session, days: int = 30) -> dict:
    """
    Compute scaling table and persist it as a KnowledgeEvent.
    The prediction pipeline can query for the latest weight_recommendation
    event of type confidence_scaling to get the current scaling table.
    """
    result = compute_scaling_table(db, days=days)

    event = KnowledgeEvent(
        event_date    = date.today(),
        category      = "model",
        event_type    = "confidence_scaling",
        description   = (
            f"Confidence scaling table computed over {days} days. "
            f"ECE={result['ece']:.4f}. "
            f"Apply recommended: {result['apply_recommended']}."
        ),
        outcome       = "neutral",
        magnitude     = result["ece"] * 100,
        metadata_json = json.dumps({
            "scaling_table":     result["scaling_table"],
            "ece":               result["ece"],
            "apply_recommended": result["apply_recommended"],
            "days":              days,
        }),
    )
    db.add(event)
    db.commit()
    result["event_id"] = event.id
    log.info("Confidence scaling recommendation recorded (event_id=%d)", event.id)
    return result


def get_latest_scaling_table(db: Session) -> dict | None:
    """
    Return the most recently recorded confidence scaling table.
    Used by the prediction pipeline to apply real-time corrections.
    """
    row = (
        db.query(KnowledgeEvent)
        .filter(
            KnowledgeEvent.category   == "model",
            KnowledgeEvent.event_type == "confidence_scaling",
        )
        .order_by(KnowledgeEvent.created_at.desc())
        .first()
    )
    if not row or not row.metadata_json:
        return None
    try:
        return json.loads(row.metadata_json)
    except (json.JSONDecodeError, TypeError):
        return None
