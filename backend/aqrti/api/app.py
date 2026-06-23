"""
AQRTI FastAPI Application
Main entry point for the backend API server.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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
from aqrti.config.settings import get_settings
from aqrti.database.engine import init_db
from aqrti.data.market_data import run_daily_ingestion
from aqrti.data.scheduler import start_scheduler, stop_scheduler
from aqrti.utils.logger import api_logger


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
        start_scheduler()
        api_logger.info("AQRTI Backend ready on port %d", settings.port)

    @app.on_event("shutdown")
    async def on_shutdown():
        stop_scheduler()
        api_logger.info("AQRTI Backend shut down.")

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

    # ── Phase 8.5: Historical Intelligence Training System ────────
    HI = f"{PREFIX}"
    app.include_router(intelligence_router.router, prefix=HI, tags=["Historical Intelligence"])

    # ── Admin Endpoints ──────────────────────────────────────────
    @app.post("/admin/ingest", tags=["Admin"])
    async def trigger_ingestion():
        """Manually trigger full market data ingestion."""
        api_logger.info("Manual ingestion triggered via admin endpoint.")
        report = run_daily_ingestion()
        return report

    @app.post("/admin/backfill", tags=["Admin"])
    async def trigger_backfill(years: int = 3):
        """
        Pull historical price data going back `years` years (default 3).
        Safe to run multiple times — only inserts missing dates.
        After backfill completes, run /admin/features to compute features
        for all historical dates, then /admin/train to train ML models.
        """
        from datetime import date, timedelta
        start = date.today() - timedelta(days=int(years) * 365)
        api_logger.info("Historical backfill triggered: %d years back to %s", years, start)
        report = run_daily_ingestion(start_override=start)
        report["backfill_start"] = str(start)
        report["years_requested"] = years
        return report

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
        api_logger.info("Manual feature generation triggered.")
        return run_incremental_feature_generation()

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
        api_logger.info("Full historical feature generation triggered.")
        return run_full_feature_generation()

    @app.post("/admin/news", tags=["Admin"])
    async def trigger_news():
        """Manually trigger news collection pipeline."""
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
        from news.news_pipeline import run_news_pipeline
        api_logger.info("Manual news pipeline triggered.")
        return run_news_pipeline()

    @app.post("/admin/sentiment", tags=["Admin"])
    async def trigger_sentiment():
        """Manually trigger sentiment computation pipeline."""
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
        from sentiment.sentiment_engine import run_sentiment_pipeline
        api_logger.info("Manual sentiment pipeline triggered.")
        return run_sentiment_pipeline()

    @app.post("/admin/train", tags=["Admin"])
    async def trigger_training():
        """Run full model training pipeline (walk-forward + final models)."""
        import sys, os
        backend_dir = os.path.join(os.path.dirname(__file__), "..", "..", "..")
        sys.path.insert(0, backend_dir)
        from ml.validation.backtest_validator import run_full_training
        from ml.ensemble.ensemble_engine import reload_ensemble
        api_logger.info("Manual model training triggered.")
        result = run_full_training()
        reload_ensemble()
        return result

    @app.post("/admin/predict", tags=["Admin"])
    async def trigger_predictions():
        """Run prediction pipeline using current trained models."""
        import sys, os
        backend_dir = os.path.join(os.path.dirname(__file__), "..", "..", "..")
        sys.path.insert(0, backend_dir)
        from ml.prediction_pipeline import run_prediction_pipeline
        api_logger.info("Manual prediction pipeline triggered.")
        return run_prediction_pipeline()

    @app.post("/admin/paper-trade", tags=["Admin"])
    async def trigger_paper_trade():
        """Run a full paper trading cycle: portfolio build → execute → mark-to-market → performance."""
        import sys, os, importlib
        backend_dir = os.path.join(os.path.dirname(__file__), "..", "..", "..")
        sys.path.insert(0, backend_dir)
        # Force reload risk_allocator so direction-filter fix is always active
        import portfolio.risk_allocator as _ra
        importlib.reload(_ra)
        import portfolio.portfolio_builder as _pb
        importlib.reload(_pb)
        from paper_trading.paper_engine import run_paper_trading_cycle
        api_logger.info("Manual paper trading cycle triggered.")
        return run_paper_trading_cycle()

    @app.post("/admin/lifecycle", tags=["Admin"])
    async def trigger_lifecycle():
        """Run strategy lifecycle sweep: promote/retire based on fitness scores."""
        import sys, os
        backend_dir = os.path.join(os.path.dirname(__file__), "..", "..", "..")
        sys.path.insert(0, backend_dir)
        from strategies.strategy_lifecycle import run_lifecycle_sweep
        from aqrti.database.engine import get_db
        api_logger.info("Manual lifecycle sweep triggered.")
        with get_db() as db:
            result = run_lifecycle_sweep(db)
            db.commit()
        return result

    @app.post("/admin/learning", tags=["Admin"])
    async def trigger_learning():
        """Manually trigger the daily learning loop."""
        import sys, os
        backend_dir = os.path.join(os.path.dirname(__file__), "..", "..", "..")
        sys.path.insert(0, backend_dir)
        from learning.learning_loop import run_daily_learning
        api_logger.info("Manual learning loop triggered.")
        return run_daily_learning(days=7)

    @app.post("/admin/strategy-research", tags=["Admin"])
    async def trigger_strategy_research():
        """Manually trigger the full strategy research loop (all 8 steps)."""
        import sys, os
        backend_dir = os.path.join(os.path.dirname(__file__), "..", "..", "..")
        sys.path.insert(0, backend_dir)
        from strategies.strategy_research_loop import run_daily_strategy_research
        api_logger.info("Manual strategy research loop triggered.")
        return run_daily_strategy_research(generate_n=50, evolve_n=20)

    @app.post("/admin/agent-pipeline", tags=["Admin"])
    async def trigger_agent_pipeline():
        """Manually trigger the full daily agent research pipeline."""
        import sys, os
        backend_dir = os.path.join(os.path.dirname(__file__), "..", "..", "..")
        sys.path.insert(0, backend_dir)
        from aqrti.database.engine import get_session_factory
        from agents.agent_scheduler import run_daily_pipeline
        api_logger.info("Manual agent pipeline triggered.")
        db = get_session_factory()()
        try:
            result = run_daily_pipeline(db)
            db.commit()
            return result
        finally:
            db.close()

    @app.post("/admin/vault", tags=["Admin"])
    async def trigger_vault():
        """Manually trigger the full vault archival for today."""
        import sys, os
        backend_dir = os.path.join(os.path.dirname(__file__), "..", "..", "..")
        sys.path.insert(0, backend_dir)
        from vault.vault_manager import run_daily_vault
        api_logger.info("Manual vault archive triggered.")
        return run_daily_vault()

    @app.post("/admin/intelligence", tags=["Admin"])
    async def trigger_intelligence_pipeline():
        """Manually trigger the full Historical Intelligence Training pipeline."""
        import sys, os
        backend_dir = os.path.join(os.path.dirname(__file__), "..", "..", "..")
        sys.path.insert(0, backend_dir)
        from intelligence_training.intelligence_pipeline import run_historical_intelligence_pipeline
        api_logger.info("Manual historical intelligence pipeline triggered.")
        return run_historical_intelligence_pipeline()

    @app.post("/admin/data-supremacy", tags=["Admin"])
    async def trigger_data_supremacy():
        """Manually trigger the full Phase 8 Data Supremacy pipeline."""
        import sys, os
        backend_dir = os.path.join(os.path.dirname(__file__), "..", "..", "..")
        sys.path.insert(0, backend_dir)
        from data_supremacy.pipeline import run_data_supremacy_pipeline
        api_logger.info("Manual data supremacy pipeline triggered.")
        return run_data_supremacy_pipeline()

    @app.get("/health", tags=["Admin"])
    async def health():
        return {"status": "ok", "version": "0.8.0"}

    return app


app = create_app()
