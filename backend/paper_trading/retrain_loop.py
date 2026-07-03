"""
Paper Trading Retrain Loop
Monitors live paper trading win rate. If it falls below WIN_RATE_TARGET,
automatically triggers:
  1. ML model retrain on latest data
  2. Full strategy research cycle (backtest → score → lifecycle → evolve)
  3. Repeat until win rate >= WIN_RATE_TARGET or MAX_ITERATIONS reached

Called by the scheduler and POST /admin/retrain-loop.
"""

from __future__ import annotations

import sys
import os
from datetime import date, datetime

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from aqrti.database.engine import get_db
from aqrti.database.models import PaperTrade, StrategyV2
from aqrti.utils.logger import get_logger

log = get_logger("retrain_loop")

from strategies.promotion_config import RETRAIN_WIN_RATE_TARGET

WIN_RATE_TARGET  = RETRAIN_WIN_RATE_TARGET   # % — keep retraining until this is hit
MIN_TRADES_EVAL  = 10     # need at least this many closed trades before evaluating
MAX_ITERATIONS   = 5      # cap retrain cycles per call to avoid runaway


def _get_live_win_rate(db) -> tuple[float, int]:
    """Return (win_rate_pct, closed_trade_count) from paper trades."""
    total = db.query(PaperTrade).filter(PaperTrade.is_open == False).count()
    if total == 0:
        return 0.0, 0
    wins = db.query(PaperTrade).filter(
        PaperTrade.is_open == False,
        PaperTrade.gross_pnl_pct > 0,
    ).count()
    return round(wins / total * 100, 1), total


def _retrain_ml(version: int = 1) -> dict:
    """Retrain ML models on the latest feature data via the working retrainer."""
    try:
        from ml.model_retrainer import check_and_retrain
        with get_db() as db:
            result = check_and_retrain(db, force=True)
        log.info("ML retrain complete: %s", result)
        return result if isinstance(result, dict) else {"result": str(result)}
    except Exception as exc:
        log.error("ML retrain failed: %s", exc)
        return {"error": str(exc)}


def _run_strategy_research() -> dict:
    """Run the full strategy research loop: backtest → score → promote → evolve."""
    try:
        from strategies.strategy_research_loop import run_daily_strategy_research
        result = run_daily_strategy_research(generate_n=30, evolve_n=10)
        log.info("Strategy research complete: %s", {k: v for k, v in result.get("steps", {}).items() if "error" not in str(v)})
        return result
    except Exception as exc:
        log.error("Strategy research failed: %s", exc)
        return {"error": str(exc)}


def _refresh_predictions(version: int = 1) -> dict:
    """Generate fresh predictions with newly trained models."""
    try:
        from ml.prediction_pipeline import run_prediction_pipeline
        result = run_prediction_pipeline(version=version)
        log.info("Predictions refreshed: %s", result)
        return result
    except Exception as exc:
        log.error("Prediction refresh failed: %s", exc)
        return {"error": str(exc)}


def run_retrain_loop(force: bool = False) -> dict:
    """
    Check live win rate. If below WIN_RATE_TARGET, retrain and re-evolve
    until target is met or MAX_ITERATIONS exhausted.

    Args:
        force: if True, retrain even if win rate is already >= target

    Returns:
        Report dict with iterations, final win rate, actions taken.
    """
    log.info("=== RETRAIN LOOP STARTED (target=%.0f%%) ===", WIN_RATE_TARGET)
    report = {
        "date":            str(date.today()),
        "target_win_rate": WIN_RATE_TARGET,
        "iterations":      [],
        "final_win_rate":  None,
        "final_trade_count": None,
        "converged":       False,
    }

    with get_db() as db:
        win_rate, trade_count = _get_live_win_rate(db)
        report["initial_win_rate"] = win_rate
        report["initial_trade_count"] = trade_count

    log.info("Current live win rate: %.1f%% over %d closed trades", win_rate, trade_count)

    if trade_count < MIN_TRADES_EVAL and not force:
        log.info("Not enough closed trades (%d < %d) to evaluate — skipping retrain", trade_count, MIN_TRADES_EVAL)
        report["skipped"] = f"insufficient_trades ({trade_count} < {MIN_TRADES_EVAL})"
        report["final_win_rate"] = win_rate
        return report

    if win_rate >= WIN_RATE_TARGET and not force:
        log.info("Win rate %.1f%% already at target %.0f%% — no retrain needed", win_rate, WIN_RATE_TARGET)
        report["converged"] = True
        report["final_win_rate"] = win_rate
        return report

    for iteration in range(1, MAX_ITERATIONS + 1):
        log.info("--- Retrain iteration %d/%d ---", iteration, MAX_ITERATIONS)
        iter_report = {"iteration": iteration, "win_rate_before": win_rate}

        # Step 1: Retrain ML models
        ml_result = _retrain_ml()
        iter_report["ml_retrain"] = "ok" if "error" not in ml_result else ml_result.get("error")

        # Step 2: Refresh predictions with new models
        pred_result = _refresh_predictions()
        iter_report["predictions"] = "ok" if "error" not in pred_result else pred_result.get("error")

        # Step 3: Run strategy research (backtest → score → promote → evolve)
        research_result = _run_strategy_research()
        steps = research_result.get("steps", {})
        iter_report["strategies_scored"] = steps.get("scoring", {}).get("scored", 0)
        iter_report["strategies_promoted"] = len(steps.get("lifecycle", {}).get("promoted", []))
        iter_report["strategies_evolved"]  = steps.get("evolution", {}).get("created", 0)

        # Check new win rate
        with get_db() as db:
            win_rate, trade_count = _get_live_win_rate(db)
        iter_report["win_rate_after"]  = win_rate
        iter_report["trade_count"]     = trade_count
        report["iterations"].append(iter_report)

        log.info(
            "Iteration %d complete: win_rate=%.1f%% trades=%d promoted=%d",
            iteration, win_rate, trade_count,
            iter_report.get("strategies_promoted", 0),
        )

        if win_rate >= WIN_RATE_TARGET:
            log.info("Target win rate %.0f%% reached after %d iteration(s)!", WIN_RATE_TARGET, iteration)
            report["converged"] = True
            break

    report["final_win_rate"]    = win_rate
    report["final_trade_count"] = trade_count
    log.info(
        "=== RETRAIN LOOP COMPLETE: win_rate=%.1f%% converged=%s iterations=%d ===",
        win_rate, report["converged"], len(report["iterations"]),
    )
    return report
