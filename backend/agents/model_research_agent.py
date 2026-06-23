"""
Model Research Agent (7E)
Monitors model drift, calibration quality, prediction quality, feature importance changes.

MAY NOT: retrain models, modify weights, deploy model changes.
"""

from __future__ import annotations

import sys, os
from datetime import date, timedelta

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from sqlalchemy.orm import Session
from aqrti.database.models import (
    ModelDriftHistory, FeatureDecayHistory, KnowledgeScore,
    FailureRecord,
)
from aqrti.utils.logger import get_logger
from agents.agent_base import AgentBase
from agents.agent_registry import register_agent_class

log = get_logger("agent.model_research")


class ModelResearchAgent(AgentBase):
    agent_id    = "model_research"
    agent_type  = "model"
    name        = "Model Research Agent"
    description = "Monitors model drift, calibration quality, prediction accuracy, and feature importance shifts."

    def run(self, db: Session) -> dict:
        findings        = []
        recommendations = []
        cutoff_30d      = date.today() - timedelta(days=30)

        # ── 1. Model Drift ───────────────────────────────────────
        drift_rows = (
            db.query(ModelDriftHistory)
            .filter(ModelDriftHistory.measured_date >= cutoff_30d)
            .order_by(ModelDriftHistory.measured_date.desc())
            .all()
        )
        drifted_models = [r for r in drift_rows if r.drift_flag]
        if drifted_models:
            for r in drifted_models[:3]:
                findings.append({
                    "title":       f"Model Drift Detected: {r.model_name} drift={r.drift_pct:.1f}%",
                    "description": (
                        f"Model {r.model_name} ({r.task}) has drifted {r.drift_pct:.1f}% "
                        f"from baseline. Current accuracy={r.accuracy}, baseline={r.baseline_metric}."
                    ),
                    "evidence":    f"drift_pct={r.drift_pct:.1f}, accuracy={r.accuracy}, baseline={r.baseline_metric}",
                    "implication": "Model retraining is recommended (requires human approval).",
                    "urgency":     "high",
                    "subcategory": "model_drift",
                    "metadata":    {"model": r.model_name, "drift_pct": r.drift_pct},
                })
            recommendations.append(
                f"{len(drifted_models)} models show significant drift. "
                "Request human approval for retraining."
            )
        else:
            findings.append({
                "title":       "Model Drift: All Clear",
                "description": f"No significant drift detected across {len(set(r.model_name for r in drift_rows))} models.",
                "evidence":    f"drift_rows_checked={len(drift_rows)}",
                "implication": "Models are performing within expected parameters.",
                "urgency":     "low",
                "subcategory": "model_drift",
            })

        # ── 2. Calibration Quality ──────────────────────────────
        recent_score = (
            db.query(KnowledgeScore)
            .order_by(KnowledgeScore.date.desc())
            .first()
        )
        if recent_score and recent_score.calibration_quality is not None:
            cal = recent_score.calibration_quality
            if cal < 40:
                findings.append({
                    "title":       f"Poor Calibration Quality: {cal:.1f}/100",
                    "description": f"Calibration quality score is {cal:.1f}. Confidence predictions are unreliable.",
                    "evidence":    f"calibration_quality={cal:.1f}",
                    "implication": "Confidence-gated strategy entries may be firing incorrectly.",
                    "urgency":     "high",
                    "subcategory": "calibration",
                })
                recommendations.append("Run confidence audit and recalibrate scaling table.")
            elif cal < 60:
                findings.append({
                    "title":       f"Moderate Calibration Quality: {cal:.1f}/100",
                    "description": f"Calibration quality {cal:.1f} is below target of 70.",
                    "evidence":    f"calibration_quality={cal:.1f}",
                    "implication": "Monitor confidence threshold tightness.",
                    "urgency":     "normal",
                    "subcategory": "calibration",
                })

        # ── 3. Feature Decay ─────────────────────────────────────
        decayed_features = (
            db.query(FeatureDecayHistory)
            .filter(
                FeatureDecayHistory.measured_date >= cutoff_30d,
                FeatureDecayHistory.decay_flag == True,
            )
            .order_by(FeatureDecayHistory.measured_date.desc())
            .limit(10)
            .all()
        )
        if decayed_features:
            severe = [f for f in decayed_features if f.decay_severity == "severe"]
            if severe:
                names = [f.feature_name for f in severe[:3]]
                findings.append({
                    "title":       f"Severe Feature Decay: {len(severe)} features",
                    "description": f"Features with severe IC decay: {names}.",
                    "evidence":    f"severe_count={len(severe)}, features={names}",
                    "implication": "These features may be hurting model performance. Flag for review.",
                    "urgency":     "high",
                    "subcategory": "feature_decay",
                })
                recommendations.append(f"Flag {len(severe)} severely decayed features for engineering review.")
            else:
                findings.append({
                    "title":       f"Feature Decay: {len(decayed_features)} features flagged (mild/moderate)",
                    "description": f"{len(decayed_features)} features show mild-to-moderate decay.",
                    "evidence":    f"decayed_count={len(decayed_features)}",
                    "implication": "Monitor IC trends — no immediate action required.",
                    "urgency":     "normal",
                    "subcategory": "feature_decay",
                })

        # ── 4. Prediction Failure Rate ───────────────────────────
        recent_failures = (
            db.query(FailureRecord)
            .filter(
                FailureRecord.failure_date >= cutoff_30d,
                FailureRecord.failure_category.in_(["false_positive", "false_negative", "overconfidence"]),
            )
            .count()
        )
        if recent_failures > 20:
            findings.append({
                "title":       f"High Prediction Failure Rate: {recent_failures} failures (30d)",
                "description": f"{recent_failures} prediction-type failures recorded in the last 30 days.",
                "evidence":    f"failure_count={recent_failures}",
                "implication": "Model predictions may have systematically degraded.",
                "urgency":     "high" if recent_failures > 50 else "normal",
                "subcategory": "prediction_quality",
            })
            recommendations.append("Investigate root cause of elevated prediction failures.")

        pred_quality = recent_score.prediction_quality if recent_score else None
        summary = (
            f"Model health: {len(drifted_models)} drifted models, "
            f"{len(decayed_features)} decayed features, "
            f"{recent_failures} recent failures. "
            f"Calibration={f'{recent_score.calibration_quality:.1f}' if recent_score and recent_score.calibration_quality else 'N/A'}."
        )
        urgency = "high" if any(f["urgency"] == "high" for f in findings) else "normal"

        return {
            "title":           f"Model Research — {date.today()}",
            "summary":         summary,
            "findings":        findings,
            "recommendations": recommendations,
            "urgency":         urgency,
            "metadata": {
                "drifted_models":      len(drifted_models),
                "decayed_features":    len(decayed_features),
                "recent_failures":     recent_failures,
                "calibration_quality": pred_quality,
            },
        }


register_agent_class(ModelResearchAgent)
