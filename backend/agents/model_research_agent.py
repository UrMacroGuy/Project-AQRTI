"""
Model Research Agent
Monitors model performance, drift, calibration quality, prediction accuracy,
and feature importance — using live model registry and prediction tables.

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
    ModelVersion, Prediction, PaperTrade, PerformanceSnapshot,
)
from aqrti.utils.logger import get_logger
from agents.agent_base import AgentBase
from agents.agent_registry import register_agent_class

log = get_logger("agent.model_research")


class ModelResearchAgent(AgentBase):
    agent_id    = "model_research"
    agent_type  = "model"
    name        = "Model Research Agent"
    description = "Monitors model performance, prediction quality, and calibration using live registry and prediction data."

    def run(self, db: Session) -> dict:
        findings        = []
        recommendations = []
        today           = date.today()
        cutoff_30d      = today - timedelta(days=30)
        cutoff_7d       = today - timedelta(days=7)

        # ── 1. Model Registry Status ──────────────────────────────
        try:
            all_models    = db.query(ModelVersion).all()
            active_models = [m for m in all_models if m.is_active]
            inactive      = [m for m in all_models if not m.is_active]

            if not all_models:
                findings.append({
                    "title":       "No Models in Registry",
                    "description": "model_versions table is empty — no trained models found.",
                    "evidence":    "model_count=0",
                    "implication": "Run the ML training pipeline to register models before predictions can be generated.",
                    "urgency":     "normal",
                    "subcategory": "registry_empty",
                })
                recommendations.append("Run the ML training pipeline to populate the model registry.")
            else:
                total_count  = len(all_models)
                active_count = len(active_models)

                findings.append({
                    "title":       f"Model Registry: {active_count} active of {total_count} total models",
                    "description": (
                        f"Model registry contains {total_count} model versions. "
                        f"{active_count} are active (is_active=True), {len(inactive)} are inactive/shadow."
                    ),
                    "evidence":    f"total={total_count}, active={active_count}, inactive={len(inactive)}",
                    "implication": "Active models are generating predictions. Inactive models are in shadow/testing.",
                    "urgency":     "low",
                    "subcategory": "registry_status",
                })

                # Check for stale models (not retrained in 30d)
                stale_models = [
                    m for m in active_models
                    if m.trained_at and (today - m.trained_at.date()).days > 30
                ]
                if stale_models:
                    names = [f"{m.model_name}/{m.task}" for m in stale_models[:3]]
                    findings.append({
                        "title":       f"Stale Models: {len(stale_models)} active models not retrained in 30+ days",
                        "description": f"Active models {names} have not been retrained in over 30 days.",
                        "evidence":    f"stale_count={len(stale_models)}, models={names}",
                        "implication": "Models may have drifted from current market conditions. Retraining recommended.",
                        "urgency":     "normal",
                        "subcategory": "model_staleness",
                    })
                    recommendations.append(f"{len(stale_models)} models need retraining (>30 days old).")

                # Best model accuracy
                best = max(active_models, key=lambda m: m.primary_metric or 0, default=None)
                if best and best.primary_metric is not None:
                    perf_label = "Good" if best.primary_metric >= 0.65 else ("Acceptable" if best.primary_metric >= 0.55 else "Poor")
                    findings.append({
                        "title":       f"Best Active Model: {best.model_name}/{best.task} — {best.primary_metric * 100:.1f}% ({perf_label})",
                        "description": (
                            f"Highest-performing active model is {best.model_name} (task={best.task}), "
                            f"primary metric={best.primary_metric * 100:.1f}%."
                        ),
                        "evidence":    f"model={best.model_name}, task={best.task}, primary_metric={best.primary_metric:.4f}",
                        "implication": f"{'Model performing well.' if best.primary_metric >= 0.65 else 'Model performance is marginal. Consider retraining.' if best.primary_metric < 0.60 else 'Model performance acceptable.'}",
                        "urgency":     "high" if best.primary_metric < 0.55 else "normal",
                        "subcategory": "model_accuracy",
                    })
                    if best.primary_metric < 0.55:
                        recommendations.append(f"Best model {best.model_name} is below 55% — retrain or replace.")
        except Exception as exc:
            log.debug("Model registry query skipped: %s", exc)
            findings.append({
                "title":       "Model Registry Unavailable",
                "description": f"Could not query model_versions table: {exc}",
                "evidence":    f"error={str(exc)[:100]}",
                "implication": "Model health cannot be assessed until registry is accessible.",
                "urgency":     "normal",
                "subcategory": "registry_error",
            })

        # ── 2. Prediction Quality Analysis ───────────────────────
        try:
            total_preds = db.query(Prediction).count()
            recent_preds = (
                db.query(Prediction)
                .filter(Prediction.date >= cutoff_30d)
                .all()
            )

            if not recent_preds:
                findings.append({
                    "title":       "No Recent Predictions",
                    "description": f"No predictions found in the last 30 days (total in DB: {total_preds}).",
                    "evidence":    f"recent_predictions=0, total_predictions={total_preds}",
                    "implication": "Prediction pipeline may not be running. Check scheduler.",
                    "urgency":     "normal" if total_preds == 0 else "low",
                    "subcategory": "prediction_volume",
                })
            else:
                # Confidence distribution
                high_conf = [p for p in recent_preds if (p.confidence or 0) >= 80]
                med_conf  = [p for p in recent_preds if 65 <= (p.confidence or 0) < 80]
                low_conf  = [p for p in recent_preds if (p.confidence or 0) < 65]
                avg_conf  = sum(p.confidence or 0 for p in recent_preds) / len(recent_preds)

                findings.append({
                    "title":       f"Prediction Volume: {len(recent_preds)} predictions (30d), avg confidence {avg_conf:.1f}%",
                    "description": (
                        f"{len(recent_preds)} predictions generated in last 30 days. "
                        f"High confidence (≥80%): {len(high_conf)}, "
                        f"Medium (65-79%): {len(med_conf)}, "
                        f"Low (<65%): {len(low_conf)}."
                    ),
                    "evidence":    f"total={len(recent_preds)}, high={len(high_conf)}, med={len(med_conf)}, low={len(low_conf)}, avg_conf={avg_conf:.1f}",
                    "implication": f"{'Good confidence spread.' if len(high_conf) >= 5 else 'Very few high-confidence signals — market may be ambiguous.'}",
                    "urgency":     "normal",
                    "subcategory": "prediction_volume",
                })

                # Outcome accuracy (if actual_return filled)
                evaluated = [p for p in recent_preds if p.success is not None]
                if evaluated:
                    wins    = sum(1 for p in evaluated if p.success)
                    win_rate = wins / len(evaluated) * 100
                    findings.append({
                        "title":       f"Prediction Win Rate: {win_rate:.1f}% ({wins}/{len(evaluated)} correct)",
                        "description": (
                            f"Of {len(evaluated)} evaluated predictions, {wins} were correct "
                            f"(win_rate={win_rate:.1f}%)."
                        ),
                        "evidence":    f"wins={wins}, total_evaluated={len(evaluated)}, win_rate={win_rate:.1f}%",
                        "implication": f"{'Strong prediction accuracy.' if win_rate >= 60 else 'Prediction accuracy is below threshold — model review needed.' if win_rate < 50 else 'Acceptable prediction accuracy.'}",
                        "urgency":     "high" if win_rate < 50 else "normal",
                        "subcategory": "prediction_accuracy",
                    })
                    if win_rate < 50:
                        recommendations.append(f"Win rate {win_rate:.1f}% is below 50% — investigate model quality.")

                # Direction bias check
                bullish = sum(1 for p in recent_preds if p.direction == "Bullish")
                bearish = sum(1 for p in recent_preds if p.direction == "Bearish")
                if len(recent_preds) >= 10:
                    bull_pct = bullish / len(recent_preds) * 100
                    if bull_pct > 80 or bull_pct < 20:
                        findings.append({
                            "title":       f"Prediction Direction Bias: {bull_pct:.0f}% Bullish",
                            "description": (
                                f"Strong directional bias in predictions: {bullish} Bullish vs {bearish} Bearish "
                                f"({bull_pct:.0f}% bullish)."
                            ),
                            "evidence":    f"bullish={bullish}, bearish={bearish}, bull_pct={bull_pct:.1f}%",
                            "implication": "Extreme directional bias may indicate model overfit to recent market trend.",
                            "urgency":     "normal",
                            "subcategory": "direction_bias",
                        })
        except Exception as exc:
            log.debug("Prediction analysis skipped: %s", exc)

        # ── 3. Paper Trade Win Rate as Model Proxy ────────────────
        try:
            closed_trades = (
                db.query(PaperTrade)
                .filter(PaperTrade.is_open == False, PaperTrade.exit_date >= cutoff_30d)
                .all()
            )
            if closed_trades:
                winners = [t for t in closed_trades if (t.actual_return or 0) > 0]
                win_rate = len(winners) / len(closed_trades) * 100
                avg_ret  = sum(t.actual_return or 0 for t in closed_trades) / len(closed_trades)
                findings.append({
                    "title":       f"Live Trade Win Rate: {win_rate:.1f}% ({len(winners)}/{len(closed_trades)} trades)",
                    "description": (
                        f"Paper trading: {len(closed_trades)} closed trades in 30d, "
                        f"win rate={win_rate:.1f}%, avg return={avg_ret:+.2f}%."
                    ),
                    "evidence":    f"closed_trades={len(closed_trades)}, win_rate={win_rate:.1f}%, avg_return={avg_ret:.2f}%",
                    "implication": f"{'Model translating to profitable trades.' if win_rate >= 55 else 'Models producing losing trades — recalibration recommended.' if win_rate < 45 else 'Trade performance marginal.'}",
                    "urgency":     "high" if win_rate < 40 else "normal",
                    "subcategory": "trade_win_rate",
                })
        except Exception as exc:
            log.debug("Trade win rate query skipped: %s", exc)

        # ── 4. Performance Snapshot ───────────────────────────────
        try:
            perf = (
                db.query(PerformanceSnapshot)
                .order_by(PerformanceSnapshot.date.desc())
                .first()
            )
            if perf and perf.win_rate_pct is not None:
                if perf.win_rate_pct < 45:
                    findings.append({
                        "title":       f"Low Win Rate in Performance Snapshot: {perf.win_rate_pct:.1f}%",
                        "description": f"Overall win rate from performance snapshot is {perf.win_rate_pct:.1f}% (target ≥55%).",
                        "evidence":    f"win_rate_pct={perf.win_rate_pct:.1f}%, date={perf.date}",
                        "implication": "Below-target win rate suggests model or strategy quality issue.",
                        "urgency":     "high" if perf.win_rate_pct < 40 else "normal",
                        "subcategory": "performance_win_rate",
                    })
        except Exception as exc:
            log.debug("Performance snapshot query skipped: %s", exc)

        if not findings:
            findings.append({
                "title":       "Model Data Baseline — No Issues Detected",
                "description": "Model registry and prediction tables are accessible with no critical issues flagged.",
                "evidence":    "all_checks_passed",
                "implication": "Continue monitoring. Run prediction pipeline daily.",
                "urgency":     "low",
                "subcategory": "all_clear",
            })

        summary = (
            f"Model health: {len([f for f in findings if f['urgency'] == 'high'])} high-urgency findings. "
            f"{len(findings)} total findings."
        )
        urgency = "high" if any(f["urgency"] == "high" for f in findings) else "normal"

        return {
            "title":           f"Model Research — {today}",
            "summary":         summary,
            "findings":        findings,
            "recommendations": recommendations,
            "urgency":         urgency,
        }


register_agent_class(ModelResearchAgent)
