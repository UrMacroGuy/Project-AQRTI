"""
AQRTI Scheduler
APScheduler-based task runner — fires daily data ingestion after NSE close.
"""

from __future__ import annotations

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from aqrti.config.settings import get_settings
from aqrti.data.market_data import run_daily_ingestion
from aqrti.utils.logger import scheduler_logger

_scheduler: BackgroundScheduler | None = None


def _daily_job():
    """
    Full post-market pipeline:
      1. Market data ingestion (OHLCV from yfinance)
      2. Feature engineering (incremental update)
      3. News collection + classification
      4. Sentiment computation + regime classification
    """
    import sys
    import os
    backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)

    scheduler_logger.info("=== DAILY PIPELINE STARTED ===")

    # Step 1: Market data
    try:
        report = run_daily_ingestion()
        scheduler_logger.info("Step 1 — Market data: %s", report["status"])
    except Exception as exc:
        scheduler_logger.error("Step 1 — Market data failed: %s", exc)

    # Step 2: Features
    try:
        from features.feature_generator import run_incremental_feature_generation
        freport = run_incremental_feature_generation()
        scheduler_logger.info("Step 2 — Features: %s", freport["status"])
    except Exception as exc:
        scheduler_logger.error("Step 2 — Features failed: %s", exc)

    # Step 3: News
    try:
        from news.news_pipeline import run_news_pipeline
        nreport = run_news_pipeline()
        scheduler_logger.info("Step 3 — News: stored=%d", nreport.get("stored", 0))
    except Exception as exc:
        scheduler_logger.error("Step 3 — News failed: %s", exc)

    # Step 4: Sentiment
    try:
        from sentiment.sentiment_engine import run_sentiment_pipeline
        sreport = run_sentiment_pipeline()
        scheduler_logger.info("Step 4 — Sentiment: regime=%s", sreport.get("regime", "?"))
    except Exception as exc:
        scheduler_logger.error("Step 4 — Sentiment failed: %s", exc)

    # Step 5: Predictions (requires trained models — skips gracefully if none)
    try:
        from ml.prediction_pipeline import run_prediction_pipeline
        preport = run_prediction_pipeline()
        scheduler_logger.info(
            "Step 5 — Predictions: written=%d", preport.get("predictions_written", 0)
        )
    except Exception as exc:
        scheduler_logger.error("Step 5 — Predictions failed: %s", exc)

    # Step 6: Paper trading cycle
    try:
        from paper_trading.paper_engine import run_paper_trading_cycle
        ptreport = run_paper_trading_cycle()
        scheduler_logger.info(
            "Step 6 — Paper Trading: opened=%d closed=%d value=%.2f",
            len(ptreport.get("opened", [])),
            len(ptreport.get("closed", [])),
            ptreport.get("portfolioValue", 0.0),
        )
    except Exception as exc:
        scheduler_logger.error("Step 6 — Paper Trading failed: %s", exc)

    # Step 7: Daily learning loop
    try:
        from learning.learning_loop import run_daily_learning
        lreport = run_daily_learning(days=7)
        scheduler_logger.info(
            "Step 7 — Learning: score=%.1f failures=%d status=%s",
            lreport.get("steps", {}).get("knowledge_score", {}).get("overall_score", 0.0),
            lreport.get("steps", {}).get("failure_analysis", {}).get("failures_processed", 0),
            lreport.get("status", "unknown"),
        )
    except Exception as exc:
        scheduler_logger.error("Step 7 — Learning loop failed: %s", exc)

    # Step 8: Strategy research loop
    try:
        from strategies.strategy_research_loop import run_daily_strategy_research
        srreport = run_daily_strategy_research(generate_n=50, evolve_n=20)
        snap = srreport.get("steps", {}).get("snapshot", {})
        res  = srreport.get("steps", {}).get("research", {})
        scheduler_logger.info(
            "Step 8 — Strategy Research: population=%d active=%d reports=%d",
            snap.get("total", 0),
            snap.get("active_count", 0),
            len(res.get("reports", [])),
        )
    except Exception as exc:
        scheduler_logger.error("Step 8 — Strategy research loop failed: %s", exc)

    # Step 9: Multi-agent research pipeline
    try:
        from aqrti.database.engine import get_session_factory
        from agents.agent_scheduler import run_daily_pipeline
        _db = get_session_factory()()
        try:
            pipeline_report = run_daily_pipeline(_db)
            _db.commit()
            scheduler_logger.info(
                "Step 9 — Agent Pipeline: agents=%d findings=%d brief=%s",
                pipeline_report.get("agents_run", 0),
                pipeline_report.get("total_findings", 0),
                "issued" if pipeline_report.get("brief_generated") else "skipped",
            )
        finally:
            _db.close()
    except Exception as exc:
        scheduler_logger.error("Step 9 — Agent pipeline failed: %s", exc)

    # Step 10: Historical Intelligence Vault — archive everything
    try:
        from vault.vault_manager import run_daily_vault
        vault_report = run_daily_vault()
        steps = vault_report.get("steps", {})
        scheduler_logger.info(
            "Step 10 — Vault Archive: status=%s snapshots=%s predictions=%s",
            vault_report.get("status", "?"),
            steps.get("market_snapshot", {}).get("status", "?"),
            steps.get("prediction_archive", {}).get("status", "?"),
        )
    except Exception as exc:
        scheduler_logger.error("Step 10 — Vault archive failed: %s", exc)

    # Step 11: Data Supremacy Layer (Phase 8)
    try:
        from data_supremacy.pipeline import run_data_supremacy_pipeline
        ds_report = run_data_supremacy_pipeline()
        quality = ds_report.get("steps", {}).get("quality", {})
        scheduler_logger.info(
            "Step 11 — Data Supremacy: status=%s quality_score=%.1f passing=%d/%d",
            ds_report.get("status", "?"),
            quality.get("avg_score", 0.0),
            quality.get("passing", 0),
            quality.get("total", 0),
        )
    except Exception as exc:
        scheduler_logger.error("Step 11 — Data Supremacy pipeline failed: %s", exc)

    # Step 12: Historical Intelligence Training System
    try:
        from intelligence_training.intelligence_pipeline import run_historical_intelligence_pipeline
        hireport = run_historical_intelligence_pipeline()
        scheduler_logger.info(
            "Step 12 — Historical Intelligence: steps=%d status=%s",
            len(hireport.get("steps", {})),
            hireport.get("status", "unknown"),
        )
    except Exception as exc:
        scheduler_logger.error("Step 12 — Historical Intelligence pipeline failed: %s", exc)

    scheduler_logger.info("=== DAILY PIPELINE COMPLETE ===")


def start_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler and _scheduler.running:
        return _scheduler

    settings = get_settings()
    parts = settings.ingest_cron.split()
    # cron string: "minute hour day month day_of_week"
    if len(parts) == 5:
        minute, hour, day, month, day_of_week = parts
    else:
        minute, hour, day, month, day_of_week = "30", "15", "*", "*", "1-5"

    _scheduler = BackgroundScheduler(timezone="Asia/Kolkata")
    _scheduler.add_job(
        _daily_job,
        trigger=CronTrigger(
            minute=minute,
            hour=hour,
            day=day,
            month=month,
            day_of_week=day_of_week,
            timezone="Asia/Kolkata",
        ),
        id="daily_ingestion",
        name="NSE Daily Ingestion",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    _scheduler.start()
    scheduler_logger.info(
        "Scheduler started. Daily ingestion cron: %s (IST)", settings.ingest_cron
    )
    return _scheduler


def stop_scheduler():
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        scheduler_logger.info("Scheduler stopped.")
