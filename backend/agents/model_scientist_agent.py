"""
Model Scientist Agent
Drift detection, champion vs challenger analysis, retraining recommendations.

MAY NOT: retrain models, deploy models, execute trades.
"""

from __future__ import annotations

import sys, os
from datetime import date, timedelta, datetime

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from sqlalchemy.orm import Session
from aqrti.database.models import ModelRecord, ModelDriftHistory
from aqrti.utils.logger import get_logger
from agents.agent_base import AgentBase
from agents.agent_registry import register_agent_class

log = get_logger("agent.model_scientist")


class ModelScientistAgent(AgentBase):
    agent_id    = "model_scientist"
    agent_type  = "model_scientist"
    name        = "Model Scientist Agent"
    description = "Monitors model drift, champion vs challenger accuracy, and flags models needing retraining."

    def run(self, db: Session) -> dict:
        findings        = []
        recommendations = []
        today           = date.today()
        cutoff_30d      = today - timedelta(days=30)

        # ── 1. Wrap drift detection ────────────────────────────────
        try:
            from learning.model_drift import run_drift_detection
            drift_result = run_drift_detection(db)
            flagged = drift_result.get("flagged", [])
            for model_name in (flagged or []):
                findings.append({
                    "title":       f"Drift Flagged: {model_name}",
                    "description": f"Model '{model_name}' has been flagged for drift by drift detection engine.",
                    "evidence":    f"model={model_name}, drift_flag=True",
                    "implication": "Consider retraining or replacing this model.",
                    "urgency":     "high",
                    "subcategory": "drift_alert",
                })
        except Exception as exc:
            log.debug("Drift detection skipped: %s", exc)

        # ── 2. Check ModelRecord: accuracy < 0.52 or ECE > 0.15 ──
        try:
            models = db.query(ModelRecord).filter(ModelRecord.is_active == True).all()
            for m in models:
                issues = []
                if m.accuracy is not None and m.accuracy < 0.52:
                    issues.append(f"accuracy={m.accuracy:.3f} < 0.52")
                if m.calibration_ece is not None and m.calibration_ece > 0.15:
                    issues.append(f"ECE={m.calibration_ece:.3f} > 0.15")

                if issues:
                    findings.append({
                        "title":       f"Model Degraded: {m.model_id} ({', '.join(issues)})",
                        "description": (
                            f"Active model '{m.model_id}' (type={m.model_type}) "
                            f"shows: {'; '.join(issues)}."
                        ),
                        "evidence":    f"model_id={m.model_id}, accuracy={m.accuracy}, ece={m.calibration_ece}",
                        "implication": "Model performance is below minimum thresholds. Retraining recommended.",
                        "urgency":     "high",
                        "subcategory": "model_degradation",
                    })
                    recommendations.append(f"Retrain model {m.model_id} — {', '.join(issues)}.")
        except Exception as exc:
            log.debug("ModelRecord check skipped: %s", exc)

        # ── 3. Champion vs Challenger: last 30d accuracy ──────────
        try:
            drift_rows = (
                db.query(ModelDriftHistory)
                .filter(ModelDriftHistory.measured_date >= cutoff_30d)
                .order_by(ModelDriftHistory.measured_date.desc())
                .all()
            )
            # Group by (model_name, task) and compare active vs shadow
            model_acc: dict[tuple, list] = {}
            for row in drift_rows:
                key = (row.model_name, row.task)
                model_acc.setdefault(key, []).append(row.accuracy or 0.0)

            if len(model_acc) >= 2:
                scored = {k: sum(v) / len(v) for k, v in model_acc.items()}
                best   = max(scored, key=scored.get)
                worst  = min(scored, key=scored.get)
                gap    = scored[best] - scored[worst]
                if gap > 0.05:
                    findings.append({
                        "title":       f"Champion vs Challenger: {best[0]} leads by {gap:.3f}",
                        "description": (
                            f"Model '{best[0]}' (task={best[1]}) averages {scored[best]:.3f} accuracy "
                            f"vs '{worst[0]}' at {scored[worst]:.3f} over 30 days."
                        ),
                        "evidence":    f"champion={best[0]}, challenger={worst[0]}, gap={gap:.3f}",
                        "implication": "Consider retiring the weaker model or reducing its ensemble weight.",
                        "urgency":     "normal",
                        "subcategory": "champion_challenger",
                    })

            # Retraining recommendation if any drift_score > 0.3
            retraining_needed = (
                db.query(ModelDriftHistory)
                .filter(
                    ModelDriftHistory.measured_date >= cutoff_30d,
                    ModelDriftHistory.drift_pct > 30.0,
                    ModelDriftHistory.drift_flag == True,
                )
                .all()
            )
            for row in retraining_needed[:3]:
                findings.append({
                    "title":       f"Retraining Needed: {row.model_name} drift={row.drift_pct:.1f}%",
                    "description": (
                        f"Model '{row.model_name}' (task={row.task}) shows {row.drift_pct:.1f}% drift "
                        f"from baseline as of {row.measured_date}."
                    ),
                    "evidence":    f"model={row.model_name}, drift_pct={row.drift_pct:.2f}, date={row.measured_date}",
                    "implication": "Schedule retraining in next available window.",
                    "urgency":     "high",
                    "subcategory": "drift_retraining",
                })
                recommendations.append(f"Schedule retraining for {row.model_name} (drift={row.drift_pct:.1f}%).")
        except Exception as exc:
            log.debug("Champion/challenger analysis skipped: %s", exc)

        if not findings:
            findings.append({
                "title":       "All Models Within Thresholds",
                "description": "No drift, degradation, or retraining signals detected.",
                "evidence":    "drift_flags=0, degraded=0",
                "implication": "Model ensemble is healthy.",
                "urgency":     "low",
                "subcategory": "model_health",
            })

        summary = (
            f"Model scientist: {len(findings)} findings, "
            f"retraining_needed={len([f for f in findings if f.get('subcategory') == 'drift_retraining'])}."
        )
        return {
            "title":           f"Model Science Report — {today}",
            "summary":         summary,
            "findings":        findings,
            "recommendations": recommendations,
            "urgency":         "high" if any(f.get("urgency") == "high" for f in findings) else "normal",
        }


register_agent_class(ModelScientistAgent)
