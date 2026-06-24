"""
Model Research Agent (7E)
Monitors model drift, calibration quality, prediction quality, feature importance changes.

When drift/decay tables are empty (fresh install), pivots to querying model_versions,
predictions, and paper_trades for proxy signals about model health.

MAY NOT: retrain models, modify weights, deploy model changes.
"""

from __future__ import annotations

import sys, os
from datetime import date, timedelta

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from sqlalchemy.orm import Session
from sqlalchemy import func
from aqrti.database.models import (
    ModelDriftHistory, FeatureDecayHistory, KnowledgeScore,
    FailureRecord, ModelVersion, Prediction, PaperTrade,
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

        # ── 1. Model Version Registry ─────────────────────────────
        try:
            total_models  = db.query(ModelVersion).count()
            active_models = db.query(ModelVersion).filter(ModelVersion.is_active == True).count()
            latest_model  = (
                db.query(ModelVersion)
                .filter(ModelVersion.trained_at.isnot(None))
                .order_by(ModelVersion.trained_at.desc())
                .first()
            )

            if total_models > 0:
                model_desc = (
                    f"{active_models} active models in registry (total: {total_models}). "
                    + (
                        f"Most recently trained: {latest_model.model_name} v{latest_model.version} "
                        f"on {latest_model.trained_at.date()} "
                        f"(metric={latest_model.primary_metric:.3f})."
                        if latest_model and latest_model.primary_metric is not None
                        else ""
                    )
                )
                urgency_reg = "normal" if active_models > 0 else "high"
                findings.append({
                    "title":       f"Model Registry: {total_models} models, {active_models} active",
                    "description": model_desc,
                    "evidence":    f"total_models={total_models}, active_models={active_models}",
                    "implication": (
                        "Model infrastructure is operational."
                        if active_models > 0 else
                        "No active models — predictions may be stale or unavailable."
                    ),
                    "urgency":     urgency_reg,
                    "subcategory": "model_registry",
                })
                if active_models == 0:
                    recommendations.append("Activate at least one trained model to enable live predictions.")
            else:
                findings.append({
                    "title":       "Model Registry Empty — No Models Trained Yet",
                    "description": "model_versions table has no entries. ML training has not run.",
                    "evidence":    "total_models=0",
                    "implication": "Run ML training pipeline to populate the model registry.",
                    "urgency":     "normal",
                    "subcategory": "model_registry",
                })
        except Exception as exc:
            log.debug("Model registry query failed: %s", exc)

        # ── 2. Model Drift ───────────────────────────────────────
        try:
            drift_rows = (
                db.query(ModelDriftHistory)
                .filter(ModelDriftHistory.measured_date >= cutoff_30d)
                .order_by(ModelDriftHistory.measured_date.desc())
                .all()
            )
            drifted_models = [r for r in drift_rows if r.drift_flag]
            if drift_rows:
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
                    unique_models = len(set(r.model_name for r in drift_rows))
                    findings.append({
                        "title":       "Model Drift: All Clear",
                        "description": f"No significant drift detected across {unique_models} monitored models.",
                        "evidence":    f"drift_rows_checked={len(drift_rows)}, drifted=0",
                        "implication": "Models are performing within expected parameters.",
                        "urgency":     "low",
                        "subcategory": "model_drift",
                    })
        except Exception as exc:
            log.debug("Drift history query failed: %s", exc)

        # ── 3. Prediction Confidence Distribution ────────────────
        try:
            pred_total = db.query(Prediction).count()
            if pred_total > 0:
                high_conf = (
                    db.query(Prediction)
                    .filter(Prediction.confidence >= 70)
                    .count()
                )
                low_conf = (
                    db.query(Prediction)
                    .filter(Prediction.confidence < 40)
                    .count()
                )
                avg_conf_row = db.query(func.avg(Prediction.confidence)).scalar()
                avg_conf = avg_conf_row if avg_conf_row is not None else 0.0

                high_pct = high_conf / pred_total * 100
                low_pct  = low_conf  / pred_total * 100

                findings.append({
                    "title":       f"Prediction Confidence Distribution: avg={avg_conf:.1f}%",
                    "description": (
                        f"Out of {pred_total} predictions: {high_conf} high-confidence (≥70%, {high_pct:.0f}%), "
                        f"{low_conf} low-confidence (<40%, {low_pct:.0f}%). Average confidence: {avg_conf:.1f}%."
                    ),
                    "evidence":    f"total_preds={pred_total}, high_conf={high_conf}, low_conf={low_conf}, avg_conf={avg_conf:.1f}",
                    "implication": (
                        "High proportion of low-confidence predictions — consider raising entry thresholds."
                        if low_pct > 40 else
                        "Prediction confidence distribution looks healthy."
                    ),
                    "urgency":     "normal" if low_pct <= 40 else "high",
                    "subcategory": "prediction_quality",
                })
        except Exception as exc:
            log.debug("Prediction confidence query failed: %s", exc)

        # ── 4. Trade Win Rate as Model Quality Proxy ─────────────
        try:
            closed_trades = (
                db.query(PaperTrade)
                .filter(
                    PaperTrade.is_open == False,
                    PaperTrade.actual_return.isnot(None),
                )
                .all()
            )
            if closed_trades:
                wins     = sum(1 for t in closed_trades if (t.actual_return or 0) > 0)
                losses   = len(closed_trades) - wins
                win_rate = wins / len(closed_trades) * 100
                avg_win  = sum(t.actual_return for t in closed_trades if (t.actual_return or 0) > 0) / max(wins, 1)
                avg_loss = sum(t.actual_return for t in closed_trades if (t.actual_return or 0) <= 0) / max(losses, 1)

                win_urgency = "high" if win_rate < 40 else "normal" if win_rate < 55 else "low"
                findings.append({
                    "title":       f"Paper Trade Win Rate: {win_rate:.1f}% ({wins}W/{losses}L)",
                    "description": (
                        f"Closed paper trade win rate: {win_rate:.1f}% over {len(closed_trades)} trades. "
                        f"Avg win: {avg_win:+.2f}%, avg loss: {avg_loss:+.2f}%."
                    ),
                    "evidence":    f"win_rate={win_rate:.1f}%, wins={wins}, losses={losses}, avg_win={avg_win:.2f}%, avg_loss={avg_loss:.2f}%",
                    "implication": (
                        "Win rate below 40% — model signal quality needs investigation."
                        if win_rate < 40 else
                        "Win rate is acceptable."
                    ),
                    "urgency":     win_urgency,
                    "subcategory": "prediction_quality",
                })
                if win_rate < 40:
                    recommendations.append(f"Win rate {win_rate:.1f}% is below threshold — investigate model signals.")
        except Exception as exc:
            log.debug("Trade win-rate query failed: %s", exc)

        # ── 5. Calibration Quality ──────────────────────────────
        try:
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
        except Exception as exc:
            log.debug("Calibration quality query skipped: %s", exc)

        # ── 6. Feature Decay ─────────────────────────────────────
        try:
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
        except Exception as exc:
            log.debug("Feature decay query skipped: %s", exc)

        # ── 7. Prediction Failure Rate ───────────────────────────
        try:
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
        except Exception as exc:
            log.debug("Failure rate query skipped: %s", exc)

        # ── Fallback ──────────────────────────────────────────────
        if not findings:
            findings.append({
                "title":       "Model System Initialising — No History Yet",
                "description": "Model drift, feature decay, and prediction tables are all empty. System is in early operation.",
                "evidence":    "drift_rows=0, decay_rows=0, prediction_rows=0",
                "implication": "Complete at least one ML training and prediction cycle to enable model health monitoring.",
                "urgency":     "low",
                "subcategory": "data_coverage",
            })

        summary = (
            f"Model health: {sum(1 for f in findings if f.get('subcategory') == 'model_drift' and 'Drift Detected' in f.get('title',''))} drifted models, "
            f"{sum(1 for f in findings if 'decay' in f.get('subcategory',''))} decay findings. "
            f"{len(findings)} total findings."
        )
        urgency = (
            "critical" if any(f["urgency"] == "critical" for f in findings) else
            "high"     if any(f["urgency"] == "high"     for f in findings) else
            "normal"
        )

        return {
            "title":           f"Model Research — {date.today()}",
            "summary":         summary,
            "findings":        findings,
            "recommendations": recommendations,
            "urgency":         urgency,
            "metadata": {
                "total_findings": len(findings),
            },
        }


register_agent_class(ModelResearchAgent)
