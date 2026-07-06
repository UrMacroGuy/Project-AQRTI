"""
AQRTI FastAPI Application
Main entry point for the backend API server.
"""

from __future__ import annotations

from fastapi import FastAPI, Depends, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware

# Only import what's needed at module level — everything else is lazy-loaded
# inside create_app() so Python doesn't pay the import cost until the app starts.
from aqrti.config.settings import get_settings
from aqrti.database.engine import init_db, checkpoint_wal
from aqrti.data.scheduler import start_scheduler, stop_scheduler
from aqrti.utils.logger import api_logger
import os
import threading
import time as _time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as _TimeoutError

# ── External scheduler detection ─────────────────────────────────────────────

def _scheduler_pid_file() -> str:
    """Absolute path to the external scheduler PID file."""
    backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(backend_dir, "scheduler.pid")


def _external_scheduler_pid() -> int | None:
    """Return the PID from scheduler.pid if the process is alive, else None."""
    pid_path = _scheduler_pid_file()
    if not os.path.exists(pid_path):
        return None
    try:
        with open(pid_path) as f:
            pid = int(f.read().strip())
    except (OSError, ValueError):
        return None
    # Probe liveness without sending a real signal (signal 0 = existence check).
    try:
        os.kill(pid, 0)
        return pid
    except OSError:
        # Process not found or permission denied — treat as stale PID.
        return None


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
    "rescore",
]

def _boot_step(name: str, status: str, msg: str = ""):
    with _BOOT_LOCK:
        _BOOT_STATUS["steps"][name] = {"status": status, "msg": msg}
        if status == "running":
            _BOOT_STATUS["current_step"] = name


# ── Timeout helper for boot steps ──────────────────────────────────────────────
_STEP_TIMEOUT = 600  # 10 min per step — prevents hanging boot from blocking API

def _run_with_timeout(name: str, fn, timeout: int = _STEP_TIMEOUT):
    """Run `fn` in a thread with a timeout. Returns (True, result) or (False, error_msg)."""
    with ThreadPoolExecutor(max_workers=1) as pool:
        fut = pool.submit(fn)
        try:
            result = fut.result(timeout=timeout)
            return True, result
        except _TimeoutError:
            fut.cancel()
            return False, f"TIMEOUT after {timeout}s"
        except Exception as e:
            return False, str(e)


def _boot_market_data():
    from aqrti.data.market_data import run_daily_ingestion, run_new_symbol_backfill
    bf = run_new_symbol_backfill(years=3)
    if bf["backfilled"]:
        api_logger.info("Boot — Backfilled %d rows for %d new symbols", bf["backfilled"], len(bf["symbols"]))
    return run_daily_ingestion()


def _boot_features():
    from aqrti.database.engine import get_db as _get_db
    from aqrti.database.models import FeatureValue as _FV
    with _get_db() as _db:
        _fv_count = _db.query(_FV).count()
    if _fv_count < 1000:
        api_logger.info("Boot step 2 — feature_values nearly empty (%d rows), running full generation", _fv_count)
        from features.feature_generator import run_full_feature_generation
        return run_full_feature_generation()
    from features.feature_generator import run_incremental_feature_generation
    return run_incremental_feature_generation()


def _boot_news():
    from news.news_pipeline import run_news_pipeline
    return run_news_pipeline()


def _boot_sentiment():
    from sentiment.sentiment_engine import run_sentiment_pipeline
    return run_sentiment_pipeline()


def _boot_predictions():
    from datetime import date as _date
    from aqrti.database.engine import get_db as _get_db
    from aqrti.database.models import Prediction as _Pred
    with _get_db() as _db:
        _today_count = _db.query(_Pred).filter(_Pred.date == _date.today()).count()
    if _today_count >= 10:
        return f"skip — {_today_count} already exist for today"
    from ml.prediction_pipeline import run_prediction_pipeline
    return run_prediction_pipeline()


def _boot_paper_trading():
    from datetime import date as _date2
    from aqrti.database.engine import get_db as _get_db2
    from aqrti.database.models import PaperTrade as _PT
    with _get_db2() as _db2:
        _pt_today = _db2.query(_PT).filter(_PT.entry_date == _date2.today()).count()
    if _pt_today > 0:
        return f"skip — already ran today ({_pt_today} trades)"
    from paper_trading.paper_engine import run_paper_trading_cycle
    return run_paper_trading_cycle()


def _boot_learning():
    from learning.learning_loop import run_daily_learning
    return run_daily_learning(days=7)


def _boot_rescore():
    from strategies.fitness_engine import rescore_all
    from strategies.strategy_lifecycle import run_lifecycle_sweep
    from strategies.strategy_backtester import backtest_and_update
    from aqrti.database.engine import get_session_factory
    _db = get_session_factory()()
    try:
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
        r = rescore_all(_db)
        lc = run_lifecycle_sweep(_db)
        _db.commit()
        return f"{r.get('total', 0)} rescored, {len(lc.get('promoted', []))} promoted, {len(lc.get('retired', []))} retired"
    finally:
        _db.close()


def _run_boot_sequence():
    """
    Full startup pipeline — runs once in background immediately after backend starts.
    Ensures all data is fresh when the user opens the frontend.
    Each step is independently guarded so one failure doesn't block the rest.
    Each step has a timeout to prevent a hanging external API from blocking the API.
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
    ok, res = _run_with_timeout("market_data", lambda: _boot_market_data())
    if ok:
        _boot_step("market_data", "done", f"status={res.get('status','?')}")
        api_logger.info("Boot step 1 — Market data: %s", res.get("status"))
    else:
        _boot_step("market_data", "error", str(res))
        api_logger.error("Boot step 1 — Market data failed: %s", res)

    # Step 2 — Feature Engineering
    _boot_step("features", "running")
    ok, res = _run_with_timeout("features", lambda: _boot_features())
    if ok:
        _boot_step("features", "done", f"status={res.get('status','?')}")
        api_logger.info("Boot step 2 — Features: %s rows=%d", res.get("status"), res.get("total_rows_written", 0))
    else:
        _boot_step("features", "error", str(res))
        api_logger.error("Boot step 2 — Features failed: %s", res)

    # Step 3 — News
    _boot_step("news", "running")
    ok, res = _run_with_timeout("news", lambda: _boot_news())
    if ok:
        _boot_step("news", "done", f"stored={res.get('stored',0)}")
        api_logger.info("Boot step 3 — News: stored=%d", res.get("stored", 0))
    else:
        _boot_step("news", "error", str(res))
        api_logger.error("Boot step 3 — News failed: %s", res)

    # Step 4 — Sentiment & Regime
    _boot_step("sentiment", "running")
    ok, res = _run_with_timeout("sentiment", lambda: _boot_sentiment())
    if ok:
        _boot_step("sentiment", "done", f"regime={res.get('regime','?')}")
        api_logger.info("Boot step 4 — Sentiment: regime=%s", res.get("regime"))
    else:
        _boot_step("sentiment", "error", str(res))
        api_logger.error("Boot step 4 — Sentiment failed: %s", res)

    # Step 5 — Predictions (skip if today's predictions already exist)
    _boot_step("predictions", "running")
    ok, res = _run_with_timeout("predictions", lambda: _boot_predictions())
    if ok:
        _boot_step("predictions", "done", f"written={res.get('predictions_written',0)}")
        api_logger.info("Boot step 5 — Predictions: written=%d", res.get("predictions_written", 0))
    elif res and "skip" in str(res):
        _boot_step("predictions", "done", f"cached (skipped)")
        api_logger.info("Boot step 5 — Predictions: %s", res)
    else:
        _boot_step("predictions", "error", str(res))
        api_logger.error("Boot step 5 — Predictions failed: %s", res)

    # Step 6 — Paper Trading (skip if already ran today)
    _boot_step("paper_trading", "running")
    ok, res = _run_with_timeout("paper_trading", lambda: _boot_paper_trading())
    if ok:
        _boot_step("paper_trading", "done",
                   f"opened={len(res.get('opened',[]))} value={res.get('portfolioValue',0):.0f}")
        api_logger.info("Boot step 6 — Paper trading: opened=%d value=%.2f",
                        len(res.get("opened", [])), res.get("portfolioValue", 0))
    elif res and "skip" in str(res):
        _boot_step("paper_trading", "done", res)
        api_logger.info("Boot step 6 — Paper trading: %s", res)
    else:
        _boot_step("paper_trading", "error", str(res))
        api_logger.error("Boot step 6 — Paper trading failed: %s", res)

    # Step 7 — Agent Pipeline (skip on boot — scheduler runs this every hour)
    _boot_step("agents", "done", "deferred to hourly scheduler")
    api_logger.info("Boot step 7 — Agents: deferred to hourly scheduler")

    # Step 8 — Strategy Research (skip on boot — scheduler runs this every 5 min)
    _boot_step("strategy_research", "done", "deferred to 5-min scheduler")
    api_logger.info("Boot step 8 — Strategy research: deferred to 5-min scheduler")

    # Step 9 — Learning Loop (lightweight — just scoring, not full retrain)
    _boot_step("learning", "running")
    ok, res = _run_with_timeout("learning", lambda: _boot_learning())
    if ok:
        score = res.get("steps", {}).get("knowledge_score", {}).get("overall_score", 0)
        filled = res.get("steps", {}).get("prediction_backfill", {}).get("filled", 0)
        _boot_step("learning", "done", f"score={score:.1f} backfilled={filled}")
        api_logger.info("Boot step 9 — Learning: score=%.1f backfilled=%d", score, filled)
    else:
        _boot_step("learning", "error", str(res))
        api_logger.error("Boot step 9 — Learning failed: %s", res)

    # Step 10 — Fix inflated-Sharpe strategies + rescore
    _boot_step("rescore", "running")
    ok, res = _run_with_timeout("rescore", lambda: _boot_rescore())
    if ok:
        _boot_step("rescore", "done", res)
        api_logger.info("Boot step 10 — Rescore: %s", res)
    else:
        _boot_step("rescore", "error", str(res))
        api_logger.error("Boot step 10 — Rescore failed: %s", res)

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
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000", "null"],
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
        ext_pid = _external_scheduler_pid()
        if ext_pid is not None:
            api_logger.info(
                "External scheduler detected (PID=%d) — not starting embedded scheduler.",
                ext_pid,
            )
        else:
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
        if _external_scheduler_pid() is None:
            # Only stop the embedded scheduler; the external process manages itself.
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

    # ── GO-3: System Health (pipeline self-check) ─────────────────
    from aqrti.api.routes import system_health as system_health_router
    app.include_router(system_health_router.router, prefix=PREFIX, tags=["System Health"])

    # ── GO-1 / GO-7 / GO-8: Go/No-Go Scorecard ───────────────────
    from aqrti.api.routes import go_nogo as go_nogo_router
    app.include_router(go_nogo_router.router, prefix=PREFIX, tags=["Go/No-Go"])

    # ── GO-7: Morning Decision Screen ────────────────────────────
    from aqrti.api.routes import morning as morning_router
    app.include_router(morning_router.router, prefix=PREFIX, tags=["Morning Decision"])

    # ── System Status (boot progress) ────────────────────────────
    @app.get("/api/v1/system/status", tags=["System"])
    async def system_status():
        """Boot pipeline progress — frontend polls this until done=true."""
        with _BOOT_LOCK:
            return dict(_BOOT_STATUS)

    @app.get("/api/v1/system/scheduler-status", tags=["System"])
    async def scheduler_status():
        """
        Report whether the scheduler is running as an external process or embedded
        inside this API process, or not running at all.

        Returns:
          mode: "external" | "embedded" | "none"
          pid:  integer PID of the external scheduler process, or null
          pid_file_exists: whether scheduler.pid is present on disk (even if stale)
        """
        pid_path = _scheduler_pid_file()
        pid_file_exists = os.path.exists(pid_path)
        ext_pid = _external_scheduler_pid()

        if ext_pid is not None:
            mode = "external"
            pid = ext_pid
        else:
            # Determine whether the embedded scheduler is running by checking the
            # module-level _scheduler object in aqrti.data.scheduler.
            try:
                from aqrti.data import scheduler as _sched_mod
                embedded_running = (
                    _sched_mod._scheduler is not None
                    and _sched_mod._scheduler.running
                )
            except Exception:
                embedded_running = False
            mode = "embedded" if embedded_running else "none"
            pid = None

        return {"mode": mode, "pid": pid, "pid_file_exists": pid_file_exists}

    # ── ARCH-8: Admin token auth ─────────────────────────────────
    # When AQRTI_ADMIN_TOKEN is set in .env, every /admin/* route requires
    # the caller to pass "X-Admin-Token: <token>" header. When the env var
    # is empty (default, localhost-only), the check is skipped entirely —
    # the localhost binding is the security boundary in that case.
    _admin_token_cfg = settings.admin_token

    def _require_admin_token(x_admin_token: str = Header(default="")):
        if _admin_token_cfg and x_admin_token != _admin_token_cfg:
            raise HTTPException(status_code=401, detail="Invalid or missing X-Admin-Token header")

    # ── Admin Endpoints ──────────────────────────────────────────
    @app.post("/admin/ingest", tags=["Admin"], dependencies=[Depends(_require_admin_token)])
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

    @app.post("/admin/backfill", tags=["Admin"], dependencies=[Depends(_require_admin_token)])
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

    @app.get("/admin/data-status", tags=["Admin"], dependencies=[Depends(_require_admin_token)])
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

    @app.post("/admin/features", tags=["Admin"], dependencies=[Depends(_require_admin_token)])
    async def trigger_features():
        """Manually trigger incremental feature generation (latest date only per symbol)."""
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
        from features.feature_generator import run_incremental_feature_generation
        import asyncio
        api_logger.info("Manual feature generation triggered.")
        return await asyncio.to_thread(run_incremental_feature_generation)

    @app.post("/admin/features-full", tags=["Admin"], dependencies=[Depends(_require_admin_token)])
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

    @app.post("/admin/shadow-paper", tags=["Admin"], dependencies=[Depends(_require_admin_token)])
    async def trigger_shadow_paper():
        """
        Run one shadow paper-trading cycle: forward-tests every promoted/
        active strategy's own DSL rules against today's data. Builds the
        quarantine evidence required before human approval to 'active'.
        """
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
        from paper_trading.strategy_shadow_runner import run_shadow_paper_cycle
        import asyncio
        api_logger.info("Shadow paper cycle triggered.")
        return await asyncio.to_thread(run_shadow_paper_cycle)

    @app.post("/admin/integrity-sweep", tags=["Admin"], dependencies=[Depends(_require_admin_token)])
    async def trigger_integrity_sweep():
        """
        Run the price integrity sweep: detect split-adjustment drift per
        symbol (incremental fetch + auto_adjust leaves old rows on the wrong
        adjustment basis) and heal drifted symbols with a full re-download
        + feature regeneration. Can take several minutes.
        """
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
        from aqrti.data.integrity_check import run_integrity_sweep
        import asyncio
        api_logger.info("Price integrity sweep triggered.")
        return await asyncio.to_thread(run_integrity_sweep)

    @app.post("/admin/news", tags=["Admin"], dependencies=[Depends(_require_admin_token)])
    async def trigger_news():
        """Manually trigger news collection pipeline."""
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
        from news.news_pipeline import run_news_pipeline
        import asyncio
        api_logger.info("Manual news pipeline triggered.")
        return await asyncio.to_thread(run_news_pipeline)

    @app.post("/admin/sentiment", tags=["Admin"], dependencies=[Depends(_require_admin_token)])
    async def trigger_sentiment():
        """Manually trigger sentiment computation pipeline."""
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
        from sentiment.sentiment_engine import run_sentiment_pipeline
        import asyncio
        api_logger.info("Manual sentiment pipeline triggered.")
        return await asyncio.to_thread(run_sentiment_pipeline)

    @app.post("/admin/train", tags=["Admin"], dependencies=[Depends(_require_admin_token)])
    async def trigger_training():
        """
        Launch model training as a SEPARATE PROCESS (scripts/train_models.py),
        not in-thread. Training (esp. AQRTINet's 7-fold stacking + 4 regime
        experts) is heavy enough that running it in-process — even on a
        thread via asyncio.to_thread — meant it fought the live backend for
        the same RAM/CPU with no way to isolate one from the other. This
        endpoint now just spawns the standalone script and returns
        immediately; check the returned log_file or model_versions for new
        rows to see when it's done.
        """
        import sys, os, subprocess
        backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
        script_path = os.path.join(backend_dir, "scripts", "train_models.py")
        python_exe  = sys.executable
        log_path    = os.path.join(backend_dir, "scripts", "train_models_log.txt")

        with open(log_path, "w") as log_file:
            proc = subprocess.Popen(
                [python_exe, script_path],
                cwd=backend_dir,
                stdout=log_file,
                stderr=subprocess.STDOUT,
            )
        api_logger.info("Manual model training launched as separate process (pid=%d), log=%s", proc.pid, log_path)
        return {"status": "started", "pid": proc.pid, "log_file": log_path}

    @app.post("/admin/predict", tags=["Admin"], dependencies=[Depends(_require_admin_token)])
    async def trigger_predictions():
        """Run prediction pipeline using current trained models."""
        import sys, os
        backend_dir = os.path.join(os.path.dirname(__file__), "..", "..", "..")
        sys.path.insert(0, backend_dir)
        from ml.prediction_pipeline import run_prediction_pipeline
        import asyncio
        api_logger.info("Manual prediction pipeline triggered.")
        return await asyncio.to_thread(run_prediction_pipeline)

    @app.post("/admin/paper-trade", tags=["Admin"], dependencies=[Depends(_require_admin_token)])
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

    @app.post("/admin/paper-trade-strategy", tags=["Admin"], dependencies=[Depends(_require_admin_token)])
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

    @app.post("/admin/paper-mtm", tags=["Admin"], dependencies=[Depends(_require_admin_token)])
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

    @app.post("/admin/lifecycle", tags=["Admin"], dependencies=[Depends(_require_admin_token)])
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

    @app.post("/admin/retrain-loop", tags=["Admin"], dependencies=[Depends(_require_admin_token)])
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

    @app.post("/admin/learning", tags=["Admin"], dependencies=[Depends(_require_admin_token)])
    async def trigger_learning():
        """Manually trigger the daily learning loop."""
        import sys, os
        backend_dir = os.path.join(os.path.dirname(__file__), "..", "..", "..")
        sys.path.insert(0, backend_dir)
        from learning.learning_loop import run_daily_learning
        import asyncio
        api_logger.info("Manual learning loop triggered.")
        return await asyncio.to_thread(run_daily_learning, 7)

    @app.post("/admin/strategy-research", tags=["Admin"], dependencies=[Depends(_require_admin_token)])
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

    @app.post("/admin/agent-pipeline", tags=["Admin"], dependencies=[Depends(_require_admin_token)])
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

    @app.post("/admin/vault", tags=["Admin"], dependencies=[Depends(_require_admin_token)])
    async def trigger_vault():
        """Manually trigger the full vault archival for today."""
        import sys, os
        backend_dir = os.path.join(os.path.dirname(__file__), "..", "..", "..")
        sys.path.insert(0, backend_dir)
        from vault.vault_manager import run_daily_vault
        import asyncio
        api_logger.info("Manual vault archive triggered.")
        return await asyncio.to_thread(run_daily_vault)

    @app.post("/admin/intelligence", tags=["Admin"], dependencies=[Depends(_require_admin_token)])
    async def trigger_intelligence_pipeline():
        """Manually trigger the full Historical Intelligence Training pipeline."""
        import asyncio, sys, os
        backend_dir = os.path.join(os.path.dirname(__file__), "..", "..", "..")
        sys.path.insert(0, backend_dir)
        from intelligence_training.intelligence_pipeline import run_historical_intelligence_pipeline
        api_logger.info("Manual historical intelligence pipeline triggered.")
        return await asyncio.to_thread(run_historical_intelligence_pipeline)

    @app.post("/admin/data-supremacy", tags=["Admin"], dependencies=[Depends(_require_admin_token)])
    async def trigger_data_supremacy():
        """Manually trigger the full Phase 8 Data Supremacy pipeline."""
        import sys, os
        backend_dir = os.path.join(os.path.dirname(__file__), "..", "..", "..")
        sys.path.insert(0, backend_dir)
        from data_supremacy.pipeline import run_data_supremacy_pipeline
        import asyncio
        api_logger.info("Manual data supremacy pipeline triggered.")
        return await asyncio.to_thread(run_data_supremacy_pipeline)

    @app.post("/admin/obsidian-export", tags=["Admin"], dependencies=[Depends(_require_admin_token)])
    async def trigger_obsidian_export(full: bool = False):
        """
        Manually trigger the Obsidian vault export.
        full=true regenerates all history; default exports today + last 7 days touched.
        No-op (returns {"skipped": "vault_path_unset"}) if settings.obsidian_vault_path is unset.
        """
        import sys, os
        backend_dir = os.path.join(os.path.dirname(__file__), "..", "..", "..")
        sys.path.insert(0, backend_dir)
        from obsidian.vault_exporter import export_vault
        import asyncio
        api_logger.info("Manual Obsidian export triggered (full=%s).", full)
        return await asyncio.to_thread(export_vault, full)

    @app.get("/health", tags=["Admin"])
    async def health():
        """
        Basic liveness + data-freshness check. The daily scheduler wraps every
        step in try/except and logs-and-continues on failure (by design, so
        one bad step doesn't block the rest) — but that means a broken price
        feed can silently leave predictions/paper-trading running on stale
        data with nothing surfacing it. This endpoint is the single place a
        user or the UI can check "is the data actually current."
        """
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
        from datetime import date, datetime, timedelta, timezone
        from aqrti.database.engine import get_db
        from aqrti.database.models import DailyPrice, FeatureValue, KnowledgeEvent, StrategyV2

        result = {"status": "ok", "version": "0.8.0"}
        now_utc = datetime.now(timezone.utc)
        result["server_time"] = now_utc.isoformat()
        problems = []
        try:
            with get_db() as db:
                today = date.today()

                # 1. Price/feature data freshness — is daily ingestion still running?
                latest_price = db.query(DailyPrice.date).order_by(DailyPrice.date.desc()).first()
                latest_feat  = db.query(FeatureValue.date).filter(FeatureValue.version == 1).order_by(FeatureValue.date.desc()).first()
                price_date = latest_price[0] if latest_price else None
                feat_date  = latest_feat[0] if latest_feat else None
                price_stale_days = (today - price_date).days if price_date else None
                feat_stale_days  = (today - feat_date).days if feat_date else None
                # >3 calendar days covers weekends/holidays without false-alarming
                data_stale = (price_stale_days is not None and price_stale_days > 3)
                result["data_freshness"] = {
                    "latest_price_date":   str(price_date) if price_date else None,
                    "latest_feature_date": str(feat_date) if feat_date else None,
                    "price_stale_days":    price_stale_days,
                    "feature_stale_days":  feat_stale_days,
                    "stale":               data_stale,
                }
                if data_stale:
                    problems.append("price/feature data is stale — daily ingestion may have stopped")

                # 2. Strategy research loop — is the daily population snapshot
                # still being written? Silence here means Step 8 of the daily
                # job (generate/backtest/evolve/promote) has stopped running,
                # even if price ingestion is fine.
                date_cutoff = today - timedelta(days=3)
                dt_cutoff   = now_utc - timedelta(days=3)
                last_snapshot = (
                    db.query(KnowledgeEvent.event_date)
                    .filter(KnowledgeEvent.event_type == "population_snapshot")
                    .order_by(KnowledgeEvent.event_date.desc())
                    .first()
                )
                snapshot_stale = last_snapshot is None or last_snapshot[0] < date_cutoff
                result["strategy_research"] = {
                    "last_snapshot_date": str(last_snapshot[0]) if last_snapshot else None,
                    "stale":              snapshot_stale,
                }
                if snapshot_stale:
                    problems.append("strategy research loop hasn't produced a population snapshot in 3+ days")

                # 3. Is anything actually being promoted/evolved, or has the
                # population gone stagnant (no status changes recently)?
                recent_promotions = (
                    db.query(StrategyV2)
                    .filter(StrategyV2.promoted_at.isnot(None),
                            StrategyV2.promoted_at >= dt_cutoff)
                    .count()
                )
                recent_candidates = (
                    db.query(StrategyV2)
                    .filter(StrategyV2.created_at >= dt_cutoff)
                    .count()
                )
                result["evolution_activity"] = {
                    "new_candidates_last_3d": recent_candidates,
                    "new_promotions_last_3d": recent_promotions,
                }
                if recent_candidates == 0:
                    problems.append("no new strategy candidates generated in 3+ days — evolution loop may have stalled")

                # 4. Arena — is it producing any activity? The arena runs
                # hourly (arena/arena_engine.py); silence for 6+ hours means
                # either the scheduler's arena_cycle job stopped firing, or
                # every eligible strategy exhausted MAX_ROUNDS with nothing
                # new promoted/active to feed it (itself worth surfacing,
                # not just an error state).
                from aqrti.database.models import ArenaRun
                arena_cutoff = now_utc - timedelta(hours=6)
                recent_arena_runs = db.query(ArenaRun).filter(
                    ArenaRun.completed_at.isnot(None),
                    ArenaRun.completed_at >= arena_cutoff,
                ).count()
                eligible_for_arena = db.query(StrategyV2).filter(
                    StrategyV2.status.in_(["promoted", "active"]),
                    StrategyV2.dsl_json.isnot(None),
                ).count()
                champions_total = db.query(StrategyV2).filter(
                    StrategyV2.arena_status == "champion"
                ).count()
                result["arena_activity"] = {
                    "runs_last_6h":        recent_arena_runs,
                    "eligible_strategies": eligible_for_arena,
                    "champions_total":     champions_total,
                }
                if eligible_for_arena > 0 and recent_arena_runs == 0:
                    problems.append("arena has eligible strategies but produced no runs in 6+ hours — hourly arena_cycle job may have stopped")

                # 5. Meta-learner — sanity-check its own shrinkage isn't
                # producing a degenerate all-zero or all-max family-weight
                # distribution, which would mean either a bug in the
                # computation or a graveyard/evolution-history table that's
                # gone empty/corrupt. Cheap to compute (same query
                # compute_meta_state uses), read-only.
                try:
                    from strategies.meta_learner import get_latest_meta_state
                    meta = get_latest_meta_state(db)
                    weights = meta.get("family_weights", {})
                    degenerate = bool(weights) and (
                        max(weights.values()) > 0.9 or
                        len({round(w, 3) for w in weights.values()}) == 1
                    )
                    result["meta_learner"] = {
                        "family_weights_computed": len(weights),
                        "degenerate":              degenerate,
                    }
                    if degenerate:
                        problems.append("meta-learner family weights look degenerate (all-equal or one family dominating >90%)")
                except Exception as meta_exc:
                    result["meta_learner"] = {"error": str(meta_exc)}
                    problems.append(f"meta-learner health check failed: {meta_exc}")

            if problems:
                result["status"] = "degraded"
                result["problems"] = problems
        except Exception as exc:
            result["error"] = str(exc)
        return result

    return app


app = create_app()
