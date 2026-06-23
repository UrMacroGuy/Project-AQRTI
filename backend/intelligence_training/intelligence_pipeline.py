"""
AQRTI Historical Intelligence Pipeline — Phase 8.5N
Daily orchestrator for the complete Historical Intelligence Training System.

Market Close → Update Historical Vault → Update Regime Datasets →
Update AQRTI History Dataset → Update Meta Learning Dataset →
Analyze Failures → Generate Feature Proposals → Update Model Memory →
Update Strategy Memory → Update Research Memory → Generate Intelligence Report
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Dict

from aqrti.utils.logger import get_logger

logger = get_logger("intelligence_pipeline")


def run_historical_intelligence_pipeline(
    run_date: date = None,
) -> Dict[str, Any]:
    """
    Full daily Historical Intelligence Training pipeline.
    Each step is independently guarded — a failure in one step never blocks the rest.
    """
    if run_date is None:
        run_date = date.today()

    report: Dict[str, Any] = {
        "run_date": run_date.isoformat(),
        "started_at": datetime.utcnow().isoformat(),
        "steps": {},
        "status": "running",
    }

    logger.info("=== HISTORICAL INTELLIGENCE PIPELINE STARTED [%s] ===", run_date)

    # ── Step 1: Update Historical Vault (replay today) ──────────────
    logger.info("Step HI-1: Historical Vault update")
    try:
        from intelligence_training.historical_replay import replay_day
        snapshot = replay_day(run_date)
        report["steps"]["historical_vault"] = {
            "status": "ok",
            "symbols": len(snapshot.market_data),
            "news": len(snapshot.news_events),
            "predictions": len(snapshot.predictions_at_date),
        }
    except Exception as exc:
        logger.error("Step HI-1 failed: %s", exc)
        report["steps"]["historical_vault"] = {"status": "error", "error": str(exc)}

    # ── Step 2: Update Regime Datasets ──────────────────────────────
    logger.info("Step HI-2: Regime datasets update")
    try:
        from intelligence_training.regime_dataset_builder import run_regime_dataset_pipeline
        r2 = run_regime_dataset_pipeline(horizon_days=5)
        report["steps"]["regime_datasets"] = {
            "status": r2.get("status", "ok"),
            "regimes_built": r2.get("regimes_built", 0),
        }
    except Exception as exc:
        logger.error("Step HI-2 failed: %s", exc)
        report["steps"]["regime_datasets"] = {"status": "error", "error": str(exc)}

    # ── Step 3: Update AQRTI History Dataset ────────────────────────
    logger.info("Step HI-3: AQRTI history dataset update")
    try:
        from intelligence_training.aqrti_history_builder import run_aqrti_history_pipeline
        r3 = run_aqrti_history_pipeline(days_back=365)
        report["steps"]["aqrti_history"] = {
            "status": r3.get("status", "ok"),
            "total_records": r3.get("total_records", 0),
        }
    except Exception as exc:
        logger.error("Step HI-3 failed: %s", exc)
        report["steps"]["aqrti_history"] = {"status": "error", "error": str(exc)}

    # ── Step 4: Update Meta Learning Dataset ────────────────────────
    logger.info("Step HI-4: Meta learning analysis")
    try:
        from intelligence_training.meta_learning_engine import run_meta_learning_analysis
        r4 = run_meta_learning_analysis(days_back=365)
        report["steps"]["meta_learning"] = {
            "status": r4.get("status", "ok"),
            "insights": r4.get("summary", {}).get("insights_generated", 0),
            "high_severity": r4.get("summary", {}).get("high_severity", 0),
        }
    except Exception as exc:
        logger.error("Step HI-4 failed: %s", exc)
        report["steps"]["meta_learning"] = {"status": "error", "error": str(exc)}

    # ── Step 5: Analyze Failures ─────────────────────────────────────
    logger.info("Step HI-5: Failure analysis")
    try:
        from intelligence_training.feature_discovery import analyze_failures_for_feature_ideas
        triggers = analyze_failures_for_feature_ideas(days_back=180)
        report["steps"]["failure_analysis"] = {
            "status": "ok",
            "failure_triggers": len(triggers),
        }
    except Exception as exc:
        logger.error("Step HI-5 failed: %s", exc)
        report["steps"]["failure_analysis"] = {"status": "error", "error": str(exc)}

    # ── Step 6: Generate Feature Proposals ───────────────────────────
    logger.info("Step HI-6: Feature proposals generation")
    try:
        from intelligence_training.feature_discovery import run_feature_discovery_pipeline
        r6 = run_feature_discovery_pipeline(days_back=180)
        report["steps"]["feature_proposals"] = {
            "status": r6.get("status", "ok"),
            "proposals": r6.get("proposals_generated", 0),
            "note": r6.get("note", ""),
        }
    except Exception as exc:
        logger.error("Step HI-6 failed: %s", exc)
        report["steps"]["feature_proposals"] = {"status": "error", "error": str(exc)}

    # ── Step 7: Update Model Memory ──────────────────────────────────
    logger.info("Step HI-7: Model memory update")
    try:
        from intelligence_training.model_memory import run_model_memory_pipeline
        r7 = run_model_memory_pipeline()
        report["steps"]["model_memory"] = {
            "status": r7.get("status", "ok"),
            "models_evaluated": r7.get("models_evaluated", 0),
        }
    except Exception as exc:
        logger.error("Step HI-7 failed: %s", exc)
        report["steps"]["model_memory"] = {"status": "error", "error": str(exc)}

    # ── Step 8: Update Strategy Memory ──────────────────────────────
    logger.info("Step HI-8: Strategy memory update")
    try:
        from intelligence_training.strategy_memory_training import run_strategy_memory_pipeline
        r8 = run_strategy_memory_pipeline()
        report["steps"]["strategy_memory"] = {
            "status": r8.get("status", "ok"),
            "strategies_processed": r8.get("strategies_processed", 0),
            "decayed": r8.get("decayed", 0),
        }
    except Exception as exc:
        logger.error("Step HI-8 failed: %s", exc)
        report["steps"]["strategy_memory"] = {"status": "error", "error": str(exc)}

    # ── Step 9: Update Research Memory ──────────────────────────────
    logger.info("Step HI-9: Research memory update")
    try:
        from intelligence_training.research_learning import run_research_learning_pipeline
        r9 = run_research_learning_pipeline()
        report["steps"]["research_memory"] = {
            "status": r9.get("status", "ok"),
            "total_records": r9.get("summary", {}).get("total_research_records", 0),
        }
    except Exception as exc:
        logger.error("Step HI-9 failed: %s", exc)
        report["steps"]["research_memory"] = {"status": "error", "error": str(exc)}

    # ── Step 10: Train Meta Models ───────────────────────────────────
    logger.info("Step HI-10: Meta model training")
    try:
        from intelligence_training.prediction_quality_model import get_prediction_quality_model
        from intelligence_training.confidence_quality_model import get_confidence_quality_model
        from intelligence_training.failure_probability_model import get_failure_probability_model

        pq_metrics = get_prediction_quality_model().train(days_back=365)
        cq_metrics = get_confidence_quality_model().train(days_back=365)
        fp_metrics = get_failure_probability_model().train(days_back=365)

        report["steps"]["meta_models"] = {
            "status": "ok",
            "prediction_quality": pq_metrics,
            "confidence_quality": cq_metrics,
            "failure_probability": fp_metrics,
        }
    except Exception as exc:
        logger.error("Step HI-10 failed: %s", exc)
        report["steps"]["meta_models"] = {"status": "error", "error": str(exc)}

    # ── Finalize ─────────────────────────────────────────────────────
    errors = sum(1 for s in report["steps"].values() if s.get("status") == "error")
    report["status"] = "complete" if errors == 0 else f"complete_with_{errors}_errors"
    report["completed_at"] = datetime.utcnow().isoformat()
    report["errors"] = errors

    logger.info("=== HISTORICAL INTELLIGENCE PIPELINE COMPLETE: %d steps, %d errors ===",
                len(report["steps"]), errors)
    return report
