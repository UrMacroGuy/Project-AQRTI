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

    # Step 1A: Global universe (NSE + BSE + international) — incremental, only new dates
    try:
        from aqrti.data.global_universe import seed_global_universe, download_global_universe
        from aqrti.database.engine import get_db as _get_db
        with _get_db() as _gdb:
            seed_global_universe(_gdb)
        gu = download_global_universe()
        scheduler_logger.info(
            "Step 1A — Global Universe: inserted=%d symbols=%d errors=%d",
            sum(gu.get("inserted", {}).values()),
            gu.get("symbols_attempted", 0),
            gu.get("errors", 0),
        )
    except Exception as exc:
        scheduler_logger.error("Step 1A — Global Universe failed: %s", exc)

    # Step 1B: Bhavcopy supplement — adds delivery volume from NSE CDN
    try:
        from data_supremacy.bhavcopy_scraper import run_daily_bhavcopy
        bv = run_daily_bhavcopy()
        scheduler_logger.info("Step 1B — Bhavcopy: status=%s inserted=%s", bv.get("status"), bv.get("inserted", 0))
    except Exception as exc:
        scheduler_logger.error("Step 1B — Bhavcopy failed: %s", exc)

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
        n_written = preport.get("predictions_written", 0)
        if n_written == 0:
            scheduler_logger.warning(
                "Step 5 — Predictions: written=0 — no active models or empty feature store. "
                "Run /admin/train to produce models."
            )
        else:
            scheduler_logger.info("Step 5 — Predictions: written=%d", n_written)
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

    # Step 6B: Strategy shadow paper trading — forward-tests each promoted/
    # active strategy's OWN DSL rules daily. This is the quarantine evidence
    # required before a strategy can be human-approved to 'active'.
    try:
        from paper_trading.strategy_shadow_runner import run_shadow_paper_cycle
        sreport = run_shadow_paper_cycle()
        scheduler_logger.info(
            "Step 6B — Shadow Paper: strategies=%d opened=%d closed=%d",
            sreport.get("strategies", 0), sreport.get("opened", 0),
            sreport.get("closed", 0),
        )
    except Exception as exc:
        scheduler_logger.error("Step 6B — Shadow Paper failed: %s", exc)

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

    # Step 7A: Live strategy validation sweep — demotes strategies underperforming vs backtest
    try:
        from aqrti.database.engine import get_db as _get_db
        from strategies.live_validator import run_daily_validation_sweep
        with _get_db() as _vdb:
            r7a = run_daily_validation_sweep(_vdb, days_back=90)
        scheduler_logger.info(
            "Step 7A — Live Validation: written=%d demoted=%d flagged=%d",
            r7a.get("rows_written", 0), len(r7a.get("demoted", [])), len(r7a.get("flagged", [])),
        )
    except Exception as exc:
        scheduler_logger.error("Step 7A — Live Validation failed: %s", exc)

    # Step 7A2: Drift-triggered retraining — if drift flagged in 30d window, trigger retrain
    try:
        from aqrti.database.engine import get_db as _get_db
        from aqrti.database.models import ModelDriftHistory
        from datetime import date as _date, timedelta as _td
        with _get_db() as _ddb:
            cutoff = _date.today() - _td(days=3)
            recent_flags = _ddb.query(ModelDriftHistory).filter(
                ModelDriftHistory.drift_flag   == True,
                ModelDriftHistory.measured_date >= cutoff,
                ModelDriftHistory.window_days   == 30,
            ).count()
        if recent_flags > 0:
            scheduler_logger.warning(
                "Step 7A2 — Drift detected (%d flagged models in 30d window) — triggering retrain",
                recent_flags,
            )
            import threading as _threading
            from ml.model_retrainer import check_and_retrain
            def _drift_retrain():
                from aqrti.database.engine import get_db as _g
                with _g() as _db:
                    check_and_retrain(_db, force=True)
            _threading.Thread(target=_drift_retrain, daemon=True).start()
        else:
            scheduler_logger.info("Step 7A2 — No drift flags in last 3 days — skipping retrain")
    except Exception as exc:
        scheduler_logger.error("Step 7A2 — Drift-triggered retrain check failed: %s", exc)

    # Step 7B: Regime Discovery (K-Means unsupervised)
    try:
        from aqrti.database.engine import get_db as _get_db
        from intelligence.regime_discovery import run_regime_discovery
        with _get_db() as _db:
            r7b = run_regime_discovery(_db)
        scheduler_logger.info("Step 7B — Regime Discovery: %s", r7b.get("status"))
    except Exception as exc:
        scheduler_logger.error("Step 7B — Regime Discovery failed: %s", exc)

    # Step 7C: Counterfactual Analysis
    try:
        from aqrti.database.engine import get_db as _get_db
        from intelligence.counterfactual_engine import run_counterfactual_analysis
        with _get_db() as _db:
            r7c = run_counterfactual_analysis(_db, days=14)
        scheduler_logger.info("Step 7C — Counterfactual: sims=%d lessons=%d",
                              r7c.get("simulations_written", 0), r7c.get("lessons_generated", 0))
    except Exception as exc:
        scheduler_logger.error("Step 7C — Counterfactual failed: %s", exc)

    # Step 7D: Strategy DNA Sync
    try:
        from aqrti.database.engine import get_db as _get_db
        from intelligence.strategy_dna import sync_strategy_dna
        with _get_db() as _db:
            r7d = sync_strategy_dna(_db, limit=200)
        scheduler_logger.info("Step 7D — Strategy DNA: created=%d updated=%d",
                              r7d.get("created", 0), r7d.get("updated", 0))
    except Exception as exc:
        scheduler_logger.error("Step 7D — Strategy DNA failed: %s", exc)

    # Step 7E: Feature Discovery
    try:
        from aqrti.database.engine import get_db as _get_db
        from intelligence.feature_discovery import run_feature_discovery
        with _get_db() as _db:
            r7e = run_feature_discovery(_db)
        scheduler_logger.info("Step 7E — Feature Discovery: approved=%d",
                              r7e.get("approved", 0))
    except Exception as exc:
        scheduler_logger.error("Step 7E — Feature Discovery failed: %s", exc)

    # Step 7F: Knowledge Graph Update
    try:
        from aqrti.database.engine import get_db as _get_db
        from intelligence.knowledge_graph_engine import run_full_graph_update
        with _get_db() as _db:
            r7f = run_full_graph_update(_db)
        scheduler_logger.info("Step 7F — Knowledge Graph: nodes=%d edges=%d",
                              r7f.get("nodes", 0), r7f.get("edges", 0))
    except Exception as exc:
        scheduler_logger.error("Step 7F — Knowledge Graph failed: %s", exc)

    # Step 7G: Hypothesis Engine
    try:
        from aqrti.database.engine import get_db as _get_db
        from intelligence.hypothesis_engine import run_hypothesis_cycle
        with _get_db() as _db:
            r7g = run_hypothesis_cycle(_db)
        scheduler_logger.info("Step 7G — Hypothesis: generated=%d experiments=%d",
                              r7g.get("hypotheses_generated", 0), r7g.get("experiments_run", 0))
    except Exception as exc:
        scheduler_logger.error("Step 7G — Hypothesis Engine failed: %s", exc)

    # Step 7H: Champion-Challenger Arena
    try:
        from aqrti.database.engine import get_db as _get_db
        from intelligence.champion_challenger import run_arena_evaluation
        with _get_db() as _db:
            r7h = run_arena_evaluation(_db)
        scheduler_logger.info("Step 7H — Arena: arenas=%d results=%d",
                              r7h.get("arenas_evaluated", 0), len(r7h.get("results", [])))
    except Exception as exc:
        scheduler_logger.error("Step 7H — Arena evaluation failed: %s", exc)

    # Step 7I: Bayesian Uncertainty (active model)
    try:
        from aqrti.database.engine import get_db as _get_db
        from intelligence.bayesian_uncertainty import estimate_uncertainty
        from aqrti.database.models import ModelRecord
        with _get_db() as _db:
            model = _db.query(ModelRecord).filter(ModelRecord.is_active == True).first()
            if model:
                r7i = estimate_uncertainty(_db, model_id=model.model_id)
                scheduler_logger.info("Step 7I — Uncertainty: %s", r7i.get("label"))
            else:
                scheduler_logger.info("Step 7I — Uncertainty: no active model")
    except Exception as exc:
        scheduler_logger.error("Step 7I — Uncertainty estimation failed: %s", exc)

    # Step 7J: Multi-Agent Decision (top 5 symbols)
    try:
        from aqrti.database.engine import get_db as _get_db
        from intelligence.multi_agent_decision import run_multi_agent_decision
        from aqrti.database.models import Stock
        with _get_db() as _db:
            top_syms = [s.symbol for s in _db.query(Stock).limit(5).all()]
        decisions = []
        for sym in top_syms:
            try:
                with _get_db() as _db:
                    d = run_multi_agent_decision(_db, symbol=sym)
                decisions.append(f"{sym}:{d.get('direction','?')}")
            except Exception:
                pass
        scheduler_logger.info("Step 7J — Multi-Agent: %s", " | ".join(decisions))
    except Exception as exc:
        scheduler_logger.error("Step 7J — Multi-Agent failed: %s", exc)

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

    # Step 9: Multi-agent research pipeline — handled by hourly_agents job (runs every 1 hr)
    scheduler_logger.info("Step 9 — Agent pipeline runs via hourly_agents job (skipped in daily to avoid double-run)")

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


def _hourly_agent_job():
    """
    Runs the full 7-agent research pipeline every hour.
    Includes follow-up task execution at the end.
    Separate from the daily pipeline so agents produce fresh findings
    throughout the day, not just once after market close.
    """
    import sys, os
    backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)

    try:
        from aqrti.database.engine import get_session_factory
        from agents.agent_scheduler import run_daily_pipeline
        _db = get_session_factory()()
        try:
            report = run_daily_pipeline(_db)
            _db.commit()
            scheduler_logger.info(
                "Hourly agents — follow_ups_run=%d",
                report.get("follow_ups_run", 0),
            )
        finally:
            _db.close()
    except Exception as exc:
        scheduler_logger.error("Hourly agent job failed: %s", exc)


def _strategy_loop_job():
    """
    Continuous strategy research micro-loop — runs every 5 minutes.
    Priority: clear the backtest backlog first. Only generates new candidates
    when the backlog is small (< 200 unscored). Uses family-balanced backtest
    selection so all families get evaluated proportionally.
    """
    import sys, os
    backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)

    try:
        from aqrti.database.session import get_db_session
        from aqrti.database.models import StrategyV2
        from strategies.strategy_generator import run_generation_cycle
        from strategies.fitness_engine import score_all_strategies
        from strategies.evolution_engine import evolve_population
        from strategies.strategy_research_loop import _backtest_unscored

        # How many unscored candidates are waiting?
        with get_db_session() as db:
            unscored = db.query(StrategyV2).filter(
                StrategyV2.fitness_score.is_(None),
                StrategyV2.status.in_(["candidate", "shadow"]),
                StrategyV2.dsl_json.isnot(None),
            ).count()

        new_count = 0
        # Only generate when backlog is small — otherwise we fall further behind
        if unscored < 200:
            with get_db_session() as db:
                gen = run_generation_cycle(db, n=20, generation=0)
            new_count = gen.get("persisted", 0)

        # Backtest 100 per cycle, family-balanced across all families
        with get_db_session() as db:
            bt = _backtest_unscored(db, max_stocks=100)
        backtested = bt.get("backtested", 0)

        # Score everything that has trades but no score
        with get_db_session() as db:
            scored = score_all_strategies(db)

        # Evolve only when backlog is manageable
        evo_count = 0
        if unscored < 500:
            with get_db_session() as db:
                evo = evolve_population(db, n_offspring=10)
            evo_count = evo.get("created", 0)

        scheduler_logger.info(
            "Strategy loop — unscored=%d generated=%d backtested=%d scored=%d evolved=%d",
            unscored, new_count, backtested,
            scored.get("scored", 0),
            evo_count,
        )
    except Exception as exc:
        scheduler_logger.error("Strategy loop failed: %s", exc)


def _alert_check_job():
    """Fast 5-min alert scan — checks for critical events without full agent run."""
    import sys, os
    backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)
    try:
        from aqrti.database.engine import get_db
        from aqrti.database.models import EquityCurvePoint, KnowledgeScore
        with get_db() as db:
            eq = db.query(EquityCurvePoint).order_by(EquityCurvePoint.date.desc()).first()
            ks = db.query(KnowledgeScore).order_by(KnowledgeScore.date.desc()).first()
            if eq and eq.drawdown_pct and eq.drawdown_pct < -15:
                scheduler_logger.warning("ALERT: Portfolio drawdown %.1f%% exceeded -15%% threshold", eq.drawdown_pct)
            if ks and ks.overall_score and ks.overall_score < 35:
                scheduler_logger.warning("ALERT: Knowledge score %.1f below 35 — system degrading", ks.overall_score)
    except Exception as exc:
        scheduler_logger.error("Alert check failed: %s", exc)


def _arena_job():
    """Hourly arena cycle — auto-promote + self-learning refinement."""
    import sys, os
    backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)
    try:
        from arena.arena_engine import run_arena_cycle
        run_arena_cycle()
    except Exception as exc:
        scheduler_logger.error("Arena job failed: %s", exc)


def _integrity_sweep_job():
    """Weekly price integrity sweep — detect + heal split-adjustment drift."""
    import sys, os
    backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)
    try:
        from aqrti.data.integrity_check import run_integrity_sweep
        result = run_integrity_sweep()
        scheduler_logger.info(
            "Integrity sweep: checked=%d drifted=%d healed=%d",
            result.get("checked", 0), len(result.get("drifted", [])),
            len(result.get("healed", [])),
        )
    except Exception as exc:
        scheduler_logger.error("Integrity sweep failed: %s", exc)


def _paper_trading_monitor_job():
    """
    Continuous 5-min paper trading monitor.
    - Checks stop-loss / take-profit / max-hold on all open positions using live prices
    - Opens new positions when slots are free and high-confidence signals exist
    - Runs 24/7 (not just during market hours) using latest available prices
    """
    import sys, os
    backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)
    try:
        from paper_trading.continuous_monitor import run_continuous_monitor
        result = run_continuous_monitor()
        if result.get("closed") or result.get("opened"):
            scheduler_logger.info(
                "Paper monitor: closed=%d opened=%d value=%.0f",
                len(result.get("closed", [])),
                len(result.get("opened", [])),
                result.get("portfolio_value", 0),
            )
    except Exception as exc:
        scheduler_logger.error("Paper trading monitor failed: %s", exc)


def start_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler and _scheduler.running:
        return _scheduler

    settings = get_settings()
    parts = settings.ingest_cron.split()
    if len(parts) == 5:
        minute, hour, day, month, day_of_week = parts
    else:
        minute, hour, day, month, day_of_week = "30", "15", "*", "*", "1-5"

    _scheduler = BackgroundScheduler(timezone="Asia/Kolkata")

    # Daily full pipeline — runs once after NSE close
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

    # Hourly agent pipeline
    _scheduler.add_job(
        _hourly_agent_job,
        trigger="interval",
        hours=1,
        id="hourly_agents",
        name="Hourly Agent Pipeline",
        replace_existing=True,
        misfire_grace_time=600,
        max_instances=1,
    )

    # Continuous strategy loop — every 5 minutes
    _scheduler.add_job(
        _strategy_loop_job,
        trigger="interval",
        minutes=5,
        id="strategy_loop",
        name="Strategy Research Loop",
        replace_existing=True,
        misfire_grace_time=300,
        max_instances=1,
    )

    # Fast alert check — every 5 minutes, very lightweight
    _scheduler.add_job(
        _alert_check_job,
        trigger="interval",
        minutes=5,
        id="alert_check",
        name="5-Min Alert Check",
        replace_existing=True,
        misfire_grace_time=120,
        max_instances=1,
    )

    # Arena self-learning — runs every hour, non-blocking (spawns daemon thread)
    _scheduler.add_job(
        _arena_job,
        trigger="interval",
        hours=1,
        id="arena_cycle",
        name="Strategy Arena Self-Learning",
        replace_existing=True,
        misfire_grace_time=1800,
        max_instances=1,
    )

    # Continuous paper trading monitor — every 5 minutes
    # Checks SL/TP/max-hold on open positions + opens new entries when slots free
    _scheduler.add_job(
        _paper_trading_monitor_job,
        trigger="interval",
        minutes=5,
        id="paper_trading_monitor",
        name="Continuous Paper Trading Monitor",
        replace_existing=True,
        misfire_grace_time=120,
        max_instances=1,
    )

    # Weekly price integrity sweep — Saturday 10:00 IST (off-market, avoids
    # colliding with daily ingestion). Detects and heals split-adjustment
    # drift caused by incremental fetch + auto_adjust.
    _scheduler.add_job(
        _integrity_sweep_job,
        trigger=CronTrigger(day_of_week="sat", hour=10, minute=0, timezone="Asia/Kolkata"),
        id="integrity_sweep",
        name="Weekly Price Integrity Sweep",
        replace_existing=True,
        misfire_grace_time=7200,
        max_instances=1,
    )

    _scheduler.start()

    # Kick off arena immediately on boot (non-blocking)
    try:
        from arena.arena_engine import run_arena_cycle
        run_arena_cycle()
        scheduler_logger.info("Arena cycle kicked off on boot")
    except Exception as exc:
        scheduler_logger.warning("Arena boot kick failed (non-fatal): %s", exc)

    # Kick off paper trading monitor immediately on boot
    try:
        from paper_trading.continuous_monitor import run_continuous_monitor
        result = run_continuous_monitor()
        scheduler_logger.info(
            "Paper monitor boot run: closed=%d opened=%d value=%.0f",
            len(result.get("closed", [])),
            len(result.get("opened", [])),
            result.get("portfolio_value", 0),
        )
    except Exception as exc:
        scheduler_logger.warning("Paper monitor boot kick failed (non-fatal): %s", exc)

    # Seed global universe (BSE + NSE + international) on boot — fast, no download
    try:
        from aqrti.data.global_universe import seed_global_universe
        from aqrti.database.engine import get_db as _get_db
        with _get_db() as _gdb:
            seed_result = seed_global_universe(_gdb)
        scheduler_logger.info(
            "Global universe seeded on boot: added=%d updated=%d total=%d",
            seed_result.get("added", 0), seed_result.get("updated", 0), seed_result.get("total", 0),
        )
    except Exception as exc:
        scheduler_logger.warning("Global universe seed on boot failed (non-fatal): %s", exc)
    scheduler_logger.info(
        "Scheduler started. Daily cron: %s IST | Agents: every 1 hr | Strategy loop: every 5 min",
        settings.ingest_cron,
    )
    return _scheduler


def stop_scheduler():
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        scheduler_logger.info("Scheduler stopped.")
