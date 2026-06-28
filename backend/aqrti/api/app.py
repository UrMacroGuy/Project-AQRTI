"""
AQRTI FastAPI Application
Main entry point for the backend API server.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Only import what's needed at module level — everything else is lazy-loaded
# inside create_app() so Python doesn't pay the import cost until the app starts.
from aqrti.config.settings import get_settings
from aqrti.database.engine import init_db, checkpoint_wal
from aqrti.data.scheduler import start_scheduler, stop_scheduler
from aqrti.utils.logger import api_logger
import threading
import time as _time

# ── Boot progress state (shared across threads, read by /system/status) ──────
_BOOT_STATUS = {
    "booting": True,
    "started_at": None,
    "steps": {},   # step_name -> {"status": "pending"|"running"|"done"|"error", "msg": ""}
    "current_step": None,
    "done": False,
}
_BOOT_LOCK = threading.Lock()

_BOOT_STEPS = [
    "market_data",
    "features",
    "news",
    "sentiment",
    "predictions",
    "paper_trading",
    "agents",
    "strategy_research",
    "learning",
]

def _boot_step(name: str, status: str, msg: str = ""):
    with _BOOT_LOCK:
        _BOOT_STATUS["steps"][name] = {"status": status, "msg": msg}
        if status == "running":
            _BOOT_STATUS["current_step"] = name


def _run_boot_sequence():
    """
    Full startup pipeline — runs once in background immediately after backend starts.
    Ensures all data is fresh when the user opens the frontend.
    Each step is independently guarded so one failure doesn't block the rest.
    """
    import sys, os
    backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)

    with _BOOT_LOCK:
        _BOOT_STATUS["booting"] = True
        _BOOT_STATUS["started_at"] = _time.time()
        _BOOT_STATUS["done"] = False
        for s in _BOOT_STEPS:
            _BOOT_STATUS["steps"][s] = {"status": "pending", "msg": ""}

    api_logger.info("=== BOOT SEQUENCE STARTED ===")

    # Step 1 — Market Data
    _boot_step("market_data", "running")
    try:
        from aqrti.data.market_data import run_daily_ingestion, run_new_symbol_backfill
        # Backfill 3-year history for any new symbols before normal incremental ingest
        bf = run_new_symbol_backfill(years=3)
        if bf["backfilled"]:
            api_logger.info("Boot — Backfilled %d rows for %d new symbols", bf["backfilled"], len(bf["symbols"]))
        report = run_daily_ingestion()
        _boot_step("market_data", "done", f"status={report.get('status','?')}")
        api_logger.info("Boot step 1 — Market data: %s", report.get("status"))
    except Exception as e:
        _boot_step("market_data", "error", str(e))
        api_logger.error("Boot step 1 — Market data failed: %s", e)

    # Step 2 — Feature Engineering
    _boot_step("features", "running")
    try:
        from aqrti.database.engine import get_db as _get_db
        from aqrti.database.models import FeatureValue as _FV
        with _get_db() as _db:
            _fv_count = _db.query(_FV).count()
        if _fv_count < 1000:
            # DB is nearly empty — run full generation to backfill all history
            api_logger.info("Boot step 2 — feature_values nearly empty (%d rows), running full generation", _fv_count)
            from features.feature_generator import run_full_feature_generation
            r = run_full_feature_generation()
        else:
            from features.feature_generator import run_incremental_feature_generation
            r = run_incremental_feature_generation()
        _boot_step("features", "done", f"status={r.get('status','?')}")
        api_logger.info("Boot step 2 — Features: %s rows=%d", r.get("status"), r.get("total_rows_written", 0))
    except Exception as e:
        _boot_step("features", "error", str(e))
        api_logger.error("Boot step 2 — Features failed: %s", e)

    # Step 3 — News
    _boot_step("news", "running")
    try:
        from news.news_pipeline import run_news_pipeline
        r = run_news_pipeline()
        _boot_step("news", "done", f"stored={r.get('stored',0)}")
        api_logger.info("Boot step 3 — News: stored=%d", r.get("stored", 0))
    except Exception as e:
        _boot_step("news", "error", str(e))
        api_logger.error("Boot step 3 — News failed: %s", e)

    # Step 4 — Sentiment & Regime
    _boot_step("sentiment", "running")
    try:
        from sentiment.sentiment_engine import run_sentiment_pipeline
        r = run_sentiment_pipeline()
        _boot_step("sentiment", "done", f"regime={r.get('regime','?')}")
        api_logger.info("Boot step 4 — Sentiment: regime=%s", r.get("regime"))
    except Exception as e:
        _boot_step("sentiment", "error", str(e))
        api_logger.error("Boot step 4 — Sentiment failed: %s", e)

    # Step 5 — Predictions (skip if today's predictions already exist)
    _boot_step("predictions", "running")
    try:
        from datetime import date as _date
        from aqrti.database.engine import get_db as _get_db
        from aqrti.database.models import Prediction as _Pred
        with _get_db() as _db:
            _today_count = _db.query(_Pred).filter(_Pred.date == _date.today()).count()
        if _today_count >= 10:
            _boot_step("predictions", "done", f"cached={_today_count} (skipped re-run)")
            api_logger.info("Boot step 5 — Predictions: %d already exist for today, skipping", _today_count)
        else:
            from ml.prediction_pipeline import run_prediction_pipeline
            r = run_prediction_pipeline()
            _boot_step("predictions", "done", f"written={r.get('predictions_written',0)}")
            api_logger.info("Boot step 5 — Predictions: written=%d", r.get("predictions_written", 0))
    except Exception as e:
        _boot_step("predictions", "error", str(e))
        api_logger.error("Boot step 5 — Predictions failed: %s", e)

    # Step 6 — Paper Trading (skip if already ran today)
    _boot_step("paper_trading", "running")
    try:
        from datetime import date as _date2
        from aqrti.database.engine import get_db as _get_db2
        from aqrti.database.models import PaperTrade as _PT
        with _get_db2() as _db2:
            _pt_today = _db2.query(_PT).filter(_PT.entry_date == _date2.today()).count()
        if _pt_today > 0:
            _boot_step("paper_trading", "done", f"already ran today ({_pt_today} trades)")
            api_logger.info("Boot step 6 — Paper trading: skipped, already ran today")
        else:
            from paper_trading.paper_engine import run_paper_trading_cycle
            r = run_paper_trading_cycle()
            _boot_step("paper_trading", "done",
                       f"opened={len(r.get('opened',[]))} value={r.get('portfolioValue',0):.0f}")
            api_logger.info("Boot step 6 — Paper trading: opened=%d value=%.2f",
                            len(r.get("opened", [])), r.get("portfolioValue", 0))
    except Exception as e:
        _boot_step("paper_trading", "error", str(e))
        api_logger.error("Boot step 6 — Paper trading failed: %s", e)

    # Step 7 — Agent Pipeline (skip on boot — scheduler runs this every hour)
    _boot_step("agents", "done", "deferred to hourly scheduler")
    api_logger.info("Boot step 7 — Agents: deferred to hourly scheduler")

    # Step 8 — Strategy Research (skip on boot — scheduler runs this every 5 min)
    _boot_step("strategy_research", "done", "deferred to 5-min scheduler")
    api_logger.info("Boot step 8 — Strategy research: deferred to 5-min scheduler")

    # Step 9 — Learning Loop (lightweight — just scoring, not full retrain)
    _boot_step("learning", "running")
    try:
        from learning.learning_loop import run_daily_learning
        r = run_daily_learning(days=7)
        score = r.get("steps", {}).get("knowledge_score", {}).get("overall_score", 0)
        filled = r.get("steps", {}).get("prediction_backfill", {}).get("filled", 0)
        _boot_step("learning", "done", f"score={score:.1f} backfilled={filled}")
        api_logger.info("Boot step 9 — Learning: score=%.1f backfilled=%d", score, filled)
    except Exception as e:
        _boot_step("learning", "error", str(e))
        api_logger.error("Boot step 9 — Learning failed: %s", e)

    # Step 10 — Fix inflated-Sharpe strategies (backtested before the POSITION_SIZE bug fix)
    #           and rescore everything with corrected fitness parameters
    try:
        from strategies.fitness_engine import rescore_all
        from strategies.strategy_lifecycle import run_lifecycle_sweep
        from strategies.strategy_backtester import backtest_and_update
        from aqrti.database.engine import get_session_factory
        _db = get_session_factory()()
        try:
            # Re-backtest any strategy with Sharpe > 5 (clearly from the old bug)
            from aqrti.database.models import StrategyV2
            import json
            stale = _db.query(StrategyV2).filter(StrategyV2.sharpe > 5).all()
            api_logger.info("Boot step 10 — Re-backtesting %d inflated-Sharpe strategies", len(stale))
            rebt = 0
            for s in stale:
                try:
                    dsl = json.loads(s.dsl_json) if s.dsl_json else {}
                    dsl["strategy_id"] = s.strategy_id
                    backtest_and_update(_db, dsl)
                    rebt += 1
                except Exception as _be:
                    api_logger.debug("Re-backtest %s failed: %s", s.strategy_id, _be)
            _db.commit()
            api_logger.info("Boot step 10 — Re-backtested %d strategies", rebt)

            # Rescore all with corrected MIN_TRADES/TARGET_TRADES
            r = rescore_all(_db)
            lc = run_lifecycle_sweep(_db)
            _db.commit()
            api_logger.info(
                "Boot step 10 — Rescore: %d strategies rescored, %d promoted, %d retired",
                r.get("total", 0), len(lc.get("promoted", [])), len(lc.get("retired", []))
            )
        finally:
            _db.close()
    except Exception as e:
        api_logger.error("Boot step 10 — Rescore/rebacktest failed: %s", e)

    with _BOOT_LOCK:
        _BOOT_STATUS["booting"] = False
        _BOOT_STATUS["done"] = True
        _BOOT_STATUS["current_step"] = None

    elapsed = _time.time() - _BOOT_STATUS["started_at"]
    api_logger.info("=== BOOT SEQUENCE COMPLETE in %.0fs ===", elapsed)


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="AQRTI Intelligence Terminal API",
        description="Autonomous Quantitative Research & Trading Intelligence — Backend API",
        version="0.8.5",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # ── CORS — allow the UI (file:// or localhost:3000) ──────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Startup / Shutdown ───────────────────────────────────────
    @app.on_event("startup")
    async def on_startup():
        api_logger.info("AQRTI Backend starting up …")
        init_db()
        checkpoint_wal()
        start_scheduler()
        api_logger.info("AQRTI Backend ready — boot pipeline starting in background")
        # Defer boot sequence by 1s so uvicorn fully binds and /health responds first
        def _deferred_boot():
            _time.sleep(1)
            _run_boot_sequence()
        t = threading.Thread(target=_deferred_boot, name="boot-sequence", daemon=True)
        t.start()

    @app.on_event("shutdown")
    async def on_shutdown():
        stop_scheduler()
        checkpoint_wal()
        api_logger.info("AQRTI Backend shut down.")

    # ── Lazy route imports (deferred so startup is fast) ─────────
    from aqrti.api.routes import (
        overview, market, predictions, news,
        sentiment, strategies, models, learning, risk, portfolio,
    )
    from aqrti.api.routes import features as features_router
    from aqrti.api.routes import market_regime as market_regime_router
    from aqrti.api.routes import confidence as confidence_router
    from aqrti.api.routes import patterns as patterns_router
    from aqrti.api.routes import paper_portfolio as paper_portfolio_router
    from aqrti.api.routes import paper_trades as paper_trades_router
    from aqrti.api.routes import performance as performance_router
    from aqrti.api.routes import equity_curve as equity_curve_router
    from aqrti.api.routes import rebalance as rebalance_router
    from aqrti.api.routes import failures as failures_router
    from aqrti.api.routes import knowledge as knowledge_router
    from aqrti.api.routes import drift as drift_router
    from aqrti.api.routes import feature_intelligence as feature_intelligence_router
    from aqrti.api.routes import lessons as lessons_router
    from aqrti.api.routes import strategy_performance as strategy_performance_router
    from aqrti.api.routes import strategy_evolution as strategy_evolution_router
    from aqrti.api.routes import graveyard as graveyard_router
    from aqrti.api.routes import research as research_router
    from aqrti.api.routes import agents as agents_router
    from aqrti.api.routes import research_briefs as research_briefs_router
    from aqrti.api.routes import research_findings as research_findings_router
    from aqrti.api.routes import intelligence as intelligence_router
    from aqrti.api.routes import vault as vault_router
    from aqrti.api.routes import replay as replay_router
    from aqrti.api.routes import archives as archives_router
    from aqrti.api.routes import vault_briefs as vault_briefs_router
    from aqrti.api.routes import vault_export as vault_export_router
    from aqrti.api.routes import backups as backups_router
    from aqrti.api.routes import corporate as corporate_router
    from aqrti.api.routes import fii_dii as fii_dii_router
    from aqrti.api.routes import options_intelligence as options_intelligence_router
    from aqrti.api.routes import market_breadth as market_breadth_router
    from aqrti.api.routes import sector_rotation as sector_rotation_router
    from aqrti.api.routes import earnings as earnings_router
    from aqrti.api.routes import data_quality as data_quality_router
    from aqrti.api.routes import screener as screener_router
    from aqrti.api.routes import watchlist as watchlist_router
    from aqrti.api.routes import stress_test as stress_test_router
    from aqrti.api.routes import universe as universe_router
    from aqrti.api.routes import regime_discovery as regime_discovery_router
    from aqrti.api.routes import counterfactual as counterfactual_router
    from aqrti.api.routes import strategy_dna as strategy_dna_router
    from aqrti.api.routes import feature_discovery as feature_discovery_router
    from aqrti.api.routes import knowledge_graph as knowledge_graph_router
    from aqrti.api.routes import hypothesis as hypothesis_router
    from aqrti.api.routes import champion_challenger as champion_challenger_router
    from aqrti.api.routes import uncertainty as uncertainty_router
    from aqrti.api.routes import multi_agent as multi_agent_router
    from aqrti.api.routes import arena as arena_router
    # ── Routes ───────────────────────────────────────────────────
    PREFIX = "/api/v1"

    app.include_router(overview.router,     prefix=f"{PREFIX}/overview",    tags=["Overview"])
    app.include_router(market.router,       prefix=f"{PREFIX}/market",      tags=["Market"])
    app.include_router(predictions.router,  prefix=f"{PREFIX}/predictions", tags=["Predictions"])
    app.include_router(news.router,         prefix=f"{PREFIX}/news",        tags=["News"])
    app.include_router(sentiment.router,    prefix=f"{PREFIX}/sentiment",   tags=["Sentiment"])
    app.include_router(strategies.router,   prefix=f"{PREFIX}/strategies",  tags=["Strategies"])
    app.include_router(models.router,       prefix=f"{PREFIX}/models",      tags=["Models"])
    app.include_router(learning.router,     prefix=f"{PREFIX}/learning",    tags=["Learning"])
    app.include_router(risk.router,         prefix=f"{PREFIX}/risk",        tags=["Risk"])
    app.include_router(portfolio.router,         prefix=f"{PREFIX}/portfolio",     tags=["Portfolio"])
    app.include_router(features_router.router,      prefix=f"{PREFIX}/features",      tags=["Features"])
    app.include_router(market_regime_router.router, prefix=f"{PREFIX}/market-regime", tags=["Market Regime"])
    app.include_router(confidence_router.router,       prefix=f"{PREFIX}/confidence",     tags=["Confidence"])
    app.include_router(patterns_router.router,         prefix=f"{PREFIX}/patterns",       tags=["Patterns"])
    app.include_router(paper_portfolio_router.router,  prefix=f"{PREFIX}/paper-portfolio", tags=["Paper Portfolio"])
    app.include_router(paper_trades_router.router,     prefix=f"{PREFIX}/paper-trades",    tags=["Paper Trades"])
    app.include_router(performance_router.router,      prefix=f"{PREFIX}/performance",     tags=["Performance"])
    app.include_router(equity_curve_router.router,     prefix=f"{PREFIX}/equity-curve",    tags=["Equity Curve"])
    app.include_router(rebalance_router.router,        prefix=f"{PREFIX}/rebalance",       tags=["Rebalance"])
    app.include_router(failures_router.router,         prefix=f"{PREFIX}/failures",         tags=["Failures"])
    app.include_router(knowledge_router.router,        prefix=f"{PREFIX}/knowledge",        tags=["Knowledge"])
    app.include_router(drift_router.router,            prefix=f"{PREFIX}/drift",            tags=["Drift"])
    app.include_router(feature_intelligence_router.router, prefix=f"{PREFIX}/feature-intelligence", tags=["Feature Intelligence"])
    app.include_router(lessons_router.router,          prefix=f"{PREFIX}/lessons",          tags=["Lessons"])
    app.include_router(strategy_performance_router.router, prefix=f"{PREFIX}/strategy-performance", tags=["Strategy Performance"])
    app.include_router(strategy_evolution_router.router,   prefix=f"{PREFIX}/strategy-evolution",   tags=["Strategy Evolution"])
    app.include_router(graveyard_router.router,            prefix=f"{PREFIX}/graveyard",            tags=["Graveyard"])
    app.include_router(research_router.router,             prefix=f"{PREFIX}/research",             tags=["Research"])
    app.include_router(agents_router.router,               prefix=f"{PREFIX}/agents",               tags=["Agents"])
    app.include_router(research_briefs_router.router,      prefix=f"{PREFIX}/research-briefs",      tags=["Research Briefs"])
    app.include_router(research_findings_router.router,    prefix=f"{PREFIX}/research-findings",    tags=["Research Findings"])
    app.include_router(vault_router.router,                prefix=f"{PREFIX}/vault",                tags=["Vault"])
    app.include_router(replay_router.router,               prefix=f"{PREFIX}/replay",               tags=["Replay"])
    app.include_router(archives_router.router,             prefix=f"{PREFIX}/archives",             tags=["Archives"])
    app.include_router(vault_briefs_router.router,         prefix=f"{PREFIX}/vault-briefs",         tags=["Vault Briefs"])
    app.include_router(vault_export_router.router,         prefix=f"{PREFIX}/vault-export",         tags=["Vault Export"])
    app.include_router(backups_router.router,              prefix=f"{PREFIX}/backups",              tags=["Backups"])
    app.include_router(corporate_router.router,            prefix=f"{PREFIX}/corporate",            tags=["Corporate"])
    app.include_router(fii_dii_router.router,              prefix=f"{PREFIX}/fii-dii",              tags=["FII DII"])
    app.include_router(options_intelligence_router.router, prefix=f"{PREFIX}/options-intelligence", tags=["Options"])
    app.include_router(market_breadth_router.router,       prefix=f"{PREFIX}/market-breadth",       tags=["Market Breadth"])
    app.include_router(sector_rotation_router.router,      prefix=f"{PREFIX}/sector-rotation",      tags=["Sector Rotation"])
    app.include_router(earnings_router.router,             prefix=f"{PREFIX}/earnings",             tags=["Earnings"])
    app.include_router(data_quality_router.router,         prefix=f"{PREFIX}/data-quality",         tags=["Data Quality"])
    app.include_router(screener_router.router,             prefix=f"{PREFIX}/screener",              tags=["Screener"])
    app.include_router(watchlist_router.router,            prefix=f"{PREFIX}/watchlist",             tags=["Watchlist"])
    app.include_router(stress_test_router.router,          prefix=f"{PREFIX}/stress-test",           tags=["StressTest"])
    app.include_router(universe_router.router,             prefix=f"{PREFIX}/universe",               tags=["Universe"])

    # ── Phase 8.5: Historical Intelligence Training System ────────
    HI = f"{PREFIX}"
    app.include_router(intelligence_router.router, prefix=HI, tags=["Historical Intelligence"])

    # ── Phase 9: Self-Learning Intelligence Upgrade ───────────────
    app.include_router(regime_discovery_router.router,    prefix=f"{PREFIX}/regime-discovery",    tags=["Regime Discovery"])
    app.include_router(counterfactual_router.router,      prefix=f"{PREFIX}/counterfactual",      tags=["Counterfactual"])
    app.include_router(strategy_dna_router.router,        prefix=f"{PREFIX}/strategy-dna",        tags=["Strategy DNA"])
    app.include_router(feature_discovery_router.router,   prefix=f"{PREFIX}/feature-discovery",   tags=["Feature Discovery"])
    app.include_router(knowledge_graph_router.router,     prefix=f"{PREFIX}/knowledge-graph",     tags=["Knowledge Graph"])
    app.include_router(hypothesis_router.router,          prefix=f"{PREFIX}/hypothesis",          tags=["Hypothesis"])
    app.include_router(champion_challenger_router.router, prefix=f"{PREFIX}/champion-challenger", tags=["Champion Challenger"])
    app.include_router(uncertainty_router.router,         prefix=f"{PREFIX}/uncertainty",         tags=["Uncertainty"])
    app.include_router(multi_agent_router.router,         prefix=f"{PREFIX}/multi-agent",         tags=["Multi Agent"])

    # ── Phase 10: Strategy Arena — autonomous self-learning loop ──
    app.include_router(arena_router.router,               prefix=f"{PREFIX}/arena",               tags=["Arena"])

    # ── System Status (boot progress) ────────────────────────────
    @app.get("/api/v1/system/status", tags=["System"])
    async def system_status():
        """Boot pipeline progress — frontend polls this until done=true."""
        with _BOOT_LOCK:
            return dict(_BOOT_STATUS)

    # ── Admin Endpoints ──────────────────────────────────────────
    @app.post("/admin/ingest", tags=["Admin"])
    async def trigger_ingestion():
        """Manually trigger full market data ingestion."""
        import asyncio
        from fastapi.responses import JSONResponse
        from aqrti.data.market_data import run_daily_ingestion as _ingest
        api_logger.info("Manual ingestion triggered via admin endpoint.")
        try:
            result = await asyncio.to_thread(_ingest)
            return result
        except Exception as exc:
            api_logger.error("Admin ingest failed: %s", exc)
            return JSONResponse(status_code=500, content={"error": str(exc), "status": "failed"})

    @app.post("/admin/backfill", tags=["Admin"])
    async def trigger_backfill(years: int = 3):
        """
        Pull historical price data going back `years` years (default 3).
        Safe to run multiple times — only inserts missing dates.
        After backfill completes, run /admin/features to compute features
        for all historical dates, then /admin/train to train ML models.
        """
        import asyncio
        from datetime import date, timedelta
        from fastapi.responses import JSONResponse
        from aqrti.data.market_data import run_daily_ingestion as _ingest
        start = date.today() - timedelta(days=int(years) * 365)
        api_logger.info("Historical backfill triggered: %d years back to %s", years, start)
        def _run():
            report = _ingest(start_override=start)
            report["backfill_start"] = str(start)
            report["years_requested"] = years
            return report
        try:
            return await asyncio.to_thread(_run)
        except Exception as exc:
            api_logger.error("Admin backfill failed: %s", exc)
            return JSONResponse(status_code=500, content={"error": str(exc), "status": "failed"})

    @app.get("/admin/data-status", tags=["Admin"])
    async def data_status():
        """Show how many rows of price/feature data exist per symbol."""
        from aqrti.database.engine import get_db_dependency
        from aqrti.database.models import DailyPrice, FeatureValue
        from sqlalchemy import func as sqlfunc
        with get_db() as db:
            price_counts = (
                db.query(DailyPrice.symbol, sqlfunc.count(DailyPrice.id).label("rows"),
                         sqlfunc.min(DailyPrice.date).label("oldest"),
                         sqlfunc.max(DailyPrice.date).label("newest"))
                .group_by(DailyPrice.symbol)
                .all()
            )
            try:
                feat_counts = (
                    db.query(FeatureValue.symbol, sqlfunc.count(FeatureValue.id).label("rows"))
                    .group_by(FeatureValue.symbol)
                    .all()
                )
                feat_map = {r.symbol: r.rows for r in feat_counts}
            except Exception:
                feat_map = {}
        return {
            "symbols": [
                {
                    "symbol":        r.symbol,
                    "price_rows":    r.rows,
                    "feature_rows":  feat_map.get(r.symbol, 0),
                    "oldest_date":   str(r.oldest),
                    "newest_date":   str(r.newest),
                }
                for r in sorted(price_counts, key=lambda x: x.symbol)
            ],
            "total_price_rows":   sum(r.rows for r in price_counts),
            "total_feature_rows": sum(feat_map.values()),
        }

    @app.post("/admin/features", tags=["Admin"])
    async def trigger_features():
        """Manually trigger incremental feature generation (latest date only per symbol)."""
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
        from features.feature_generator import run_incremental_feature_generation
        import asyncio
        api_logger.info("Manual feature generation triggered.")
        return await asyncio.to_thread(run_incremental_feature_generation)

    @app.post("/admin/features-full", tags=["Admin"])
    async def trigger_features_full():
        """
        Compute features for ALL historical dates per symbol (not just latest).
        Run this after /admin/backfill to populate the full feature history
        needed for ML model training. Can take several minutes.
        """
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
        from features.feature_generator import run_full_feature_generation
        import asyncio
        api_logger.info("Full historical feature generation triggered.")
        return await asyncio.to_thread(run_full_feature_generation)

    @app.post("/admin/news", tags=["Admin"])
    async def trigger_news():
        """Manually trigger news collection pipeline."""
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
        from news.news_pipeline import run_news_pipeline
        import asyncio
        api_logger.info("Manual news pipeline triggered.")
        return await asyncio.to_thread(run_news_pipeline)

    @app.post("/admin/sentiment", tags=["Admin"])
    async def trigger_sentiment():
        """Manually trigger sentiment computation pipeline."""
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
        from sentiment.sentiment_engine import run_sentiment_pipeline
        import asyncio
        api_logger.info("Manual sentiment pipeline triggered.")
        return await asyncio.to_thread(run_sentiment_pipeline)

    @app.post("/admin/train", tags=["Admin"])
    async def trigger_training():
        """Run full model training pipeline (walk-forward + final models)."""
        import sys, os
        backend_dir = os.path.join(os.path.dirname(__file__), "..", "..", "..")
        sys.path.insert(0, backend_dir)
        from ml.validation.backtest_validator import run_full_training
        from ml.ensemble.ensemble_engine import reload_ensemble
        import asyncio
        api_logger.info("Manual model training triggered.")
        result = await asyncio.to_thread(run_full_training)
        reload_ensemble()
        return result

    @app.post("/admin/predict", tags=["Admin"])
    async def trigger_predictions():
        """Run prediction pipeline using current trained models."""
        import sys, os
        backend_dir = os.path.join(os.path.dirname(__file__), "..", "..", "..")
        sys.path.insert(0, backend_dir)
        from ml.prediction_pipeline import run_prediction_pipeline
        import asyncio
        api_logger.info("Manual prediction pipeline triggered.")
        return await asyncio.to_thread(run_prediction_pipeline)

    @app.post("/admin/paper-trade", tags=["Admin"])
    async def trigger_paper_trade():
        """Run a full paper trading cycle using the best promoted strategy."""
        import sys, os, importlib
        backend_dir = os.path.join(os.path.dirname(__file__), "..", "..", "..")
        sys.path.insert(0, backend_dir)
        import portfolio.risk_allocator as _ra
        importlib.reload(_ra)
        import portfolio.portfolio_builder as _pb
        importlib.reload(_pb)
        from paper_trading.paper_engine import run_paper_trading_cycle
        import asyncio
        api_logger.info("Manual paper trading cycle triggered.")
        return await asyncio.to_thread(run_paper_trading_cycle)

    @app.post("/admin/paper-trade-strategy", tags=["Admin"])
    async def trigger_paper_trade_strategy(body: dict = None):
        """Run a paper trading cycle using a specific strategy ID.

        Body: {"strategy_id": "AQRTI_STR_XXXXXXXX"}
        """
        import sys, os, importlib
        backend_dir = os.path.join(os.path.dirname(__file__), "..", "..", "..")
        sys.path.insert(0, backend_dir)
        import portfolio.risk_allocator as _ra
        importlib.reload(_ra)
        import portfolio.portfolio_builder as _pb
        importlib.reload(_pb)
        from paper_trading.paper_engine import run_paper_trading_cycle
        import asyncio
        strategy_id = (body or {}).get("strategy_id") if body else None
        if not strategy_id:
            return {"status": "error", "error": "strategy_id is required in request body"}
        api_logger.info("Paper trading cycle triggered for strategy %s.", strategy_id)
        return await asyncio.to_thread(run_paper_trading_cycle, 1, strategy_id)

    @app.post("/admin/paper-mtm", tags=["Admin"])
    async def trigger_paper_mtm():
        """Intraday mark-to-market: check SL/TP/expiry on open positions, update NAV. No rebalance."""
        import sys, os
        backend_dir = os.path.join(os.path.dirname(__file__), "..", "..", "..")
        sys.path.insert(0, backend_dir)
        from aqrti.database.engine import get_db
        from paper_trading.paper_execution import mark_to_market
        import asyncio
        def _run_mtm():
            with get_db() as db:
                result = mark_to_market(db)
                db.commit()
            return result
        api_logger.info("Intraday mark-to-market triggered.")
        return await asyncio.to_thread(_run_mtm)

    @app.post("/admin/lifecycle", tags=["Admin"])
    async def trigger_lifecycle():
        """Run strategy lifecycle sweep: promote/retire based on fitness scores."""
        import sys, os
        backend_dir = os.path.join(os.path.dirname(__file__), "..", "..", "..")
        sys.path.insert(0, backend_dir)
        from strategies.strategy_lifecycle import run_lifecycle_sweep
        from aqrti.database.engine import get_db
        import asyncio
        api_logger.info("Manual lifecycle sweep triggered.")
        def _run_lc():
            with get_db() as db:
                result = run_lifecycle_sweep(db)
                db.commit()
            return result
        return await asyncio.to_thread(_run_lc)

    @app.post("/admin/retrain-loop", tags=["Admin"])
    async def trigger_retrain_loop(force: bool = False):
        """
        Check paper trading win rate. If below 70%, auto-retrain ML models,
        refresh predictions, and re-run strategy research until target is met
        (up to 5 iterations). Pass ?force=true to retrain regardless of win rate.
        """
        import asyncio
        from paper_trading.retrain_loop import run_retrain_loop
        api_logger.info("Retrain loop triggered (force=%s).", force)
        return await asyncio.to_thread(run_retrain_loop, force)

    @app.post("/admin/learning", tags=["Admin"])
    async def trigger_learning():
        """Manually trigger the daily learning loop."""
        import sys, os
        backend_dir = os.path.join(os.path.dirname(__file__), "..", "..", "..")
        sys.path.insert(0, backend_dir)
        from learning.learning_loop import run_daily_learning
        import asyncio
        api_logger.info("Manual learning loop triggered.")
        return await asyncio.to_thread(run_daily_learning, 7)

    @app.post("/admin/strategy-research", tags=["Admin"])
    async def trigger_strategy_research():
        """Manually trigger the full strategy research loop (all 8 steps)."""
        import sys, os
        backend_dir = os.path.join(os.path.dirname(__file__), "..", "..", "..")
        sys.path.insert(0, backend_dir)
        from strategies.strategy_research_loop import run_daily_strategy_research
        import asyncio
        api_logger.info("Manual strategy research loop triggered.")
        import functools
        return await asyncio.to_thread(functools.partial(run_daily_strategy_research, generate_n=50, evolve_n=20))

    @app.post("/admin/agent-pipeline", tags=["Admin"])
    async def trigger_agent_pipeline():
        """Manually trigger the full daily agent research pipeline."""
        import sys, os
        backend_dir = os.path.join(os.path.dirname(__file__), "..", "..", "..")
        sys.path.insert(0, backend_dir)
        from aqrti.database.engine import get_session_factory
        from agents.agent_scheduler import run_daily_pipeline
        import asyncio
        api_logger.info("Manual agent pipeline triggered.")
        def _run_ap():
            db = get_session_factory()()
            try:
                result = run_daily_pipeline(db)
                db.commit()
                return result
            finally:
                db.close()
        return await asyncio.to_thread(_run_ap)

    @app.post("/admin/vault", tags=["Admin"])
    async def trigger_vault():
        """Manually trigger the full vault archival for today."""
        import sys, os
        backend_dir = os.path.join(os.path.dirname(__file__), "..", "..", "..")
        sys.path.insert(0, backend_dir)
        from vault.vault_manager import run_daily_vault
        import asyncio
        api_logger.info("Manual vault archive triggered.")
        return await asyncio.to_thread(run_daily_vault)

    @app.post("/admin/intelligence", tags=["Admin"])
    async def trigger_intelligence_pipeline():
        """Manually trigger the full Historical Intelligence Training pipeline."""
        import asyncio, sys, os
        backend_dir = os.path.join(os.path.dirname(__file__), "..", "..", "..")
        sys.path.insert(0, backend_dir)
        from intelligence_training.intelligence_pipeline import run_historical_intelligence_pipeline
        api_logger.info("Manual historical intelligence pipeline triggered.")
        return await asyncio.to_thread(run_historical_intelligence_pipeline)

    @app.post("/admin/data-supremacy", tags=["Admin"])
    async def trigger_data_supremacy():
        """Manually trigger the full Phase 8 Data Supremacy pipeline."""
        import sys, os
        backend_dir = os.path.join(os.path.dirname(__file__), "..", "..", "..")
        sys.path.insert(0, backend_dir)
        from data_supremacy.pipeline import run_data_supremacy_pipeline
        import asyncio
        api_logger.info("Manual data supremacy pipeline triggered.")
        return await asyncio.to_thread(run_data_supremacy_pipeline)

    @app.get("/health", tags=["Admin"])
    async def health():
        return {"status": "ok", "version": "0.8.0"}

    return app


app = create_app()
