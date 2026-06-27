"""
Paper Engine — Daily Orchestrator
Runs the full daily paper trading cycle:
  1. Load today's predictions
  2. Build target portfolio via portfolio module
  3. Execute rebalance (close exits, open entries)
  4. Mark all positions to market
  5. Record equity curve point
  6. Compute and save performance snapshot

Called by the scheduler (Step 6) and POST /admin/paper-trade.
"""

from __future__ import annotations

import sys
import os
from datetime import date, datetime
from typing import Optional

from aqrti.database.engine import get_db
from aqrti.database.models import DailyPrice, IndexData
from aqrti.utils.logger import get_logger

log = get_logger("paper_engine")

PORTFOLIO_NAME = "default"


def _get_nifty_close(db) -> Optional[float]:
    row = (
        db.query(IndexData.close)
        .filter(IndexData.index_name == "^NSEI")
        .order_by(IndexData.date.desc())
        .first()
    )
    return row[0] if row else None


def run_paper_trading_cycle(version: int = 1, strategy_id: str | None = None) -> dict:
    """
    Full daily paper trading cycle.

    Returns a report dict:
      {status, date, opened, closed, rebalance_errors,
       portfolioValue, totalReturnPct, openPositions, timestamp}

    If strategy_id is provided, use that specific strategy's parameters instead of
    the best promoted strategy.
    """
    if strategy_id:
        log.info("=== PAPER TRADING CYCLE STARTED (strategy=%s) ===", strategy_id)
    else:
        log.info("=== PAPER TRADING CYCLE STARTED ===")
    today  = date.today()

    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)

    try:
        from portfolio.portfolio_builder import build_target_portfolio
        from paper_trading.paper_execution import execute_rebalance, mark_to_market
        from paper_trading.paper_portfolio import get_or_create_portfolio
        from paper_trading.performance_tracker import (
            record_equity_point, compute_and_save_snapshot,
        )
    except ImportError as exc:
        log.error("Import failed: %s", exc)
        return {"status": "import_error", "error": str(exc)}

    with get_db() as db:
        # ── Step 1: Load portfolio and check for predictions ──────
        portfolio = get_or_create_portfolio(db)

        # ── Step 2: Build target weights from predictions ─────────
        target = build_target_portfolio(db, version=version, strategy_id=strategy_id)
        if not target.get("weights"):
            log.warning("No target weights generated — skipping rebalance")
            mtm = mark_to_market(db)
            nifty = _get_nifty_close(db)
            record_equity_point(db, mtm["totalValue"], mtm["cash"], nifty_close=nifty)
            compute_and_save_snapshot(db)
            return {
                "status":         "no_signals",
                "date":           str(today),
                "portfolioValue": mtm["totalValue"],
                "opened":         [],
                "closed":         [],
            }

        # ── Step 3: Execute rebalance ──────────────────────────────
        rebalance_result = execute_rebalance(
            db, target["weights"], reason="daily_rebalance",
            candidates=target.get("candidates", []),
        )

        # ── Step 4: Mark to market ─────────────────────────────────
        mtm = mark_to_market(db)

        # ── Step 5: Record equity curve point ─────────────────────
        nifty = _get_nifty_close(db)
        record_equity_point(db, mtm["totalValue"], mtm["cash"], nifty_close=nifty)

        # ── Step 6: Compute performance snapshot ──────────────────
        snap = compute_and_save_snapshot(db)
        # Read snap attributes while session is still open to avoid DetachedInstanceError
        total_return_pct = snap.total_return_pct if snap else 0.0
        sharpe_ratio     = snap.sharpe_ratio if snap else 0.0

    log.info(
        "=== PAPER TRADING CYCLE COMPLETE: opened=%d closed=%d value=%.2f ===",
        len(rebalance_result.get("opened", [])),
        len(rebalance_result.get("closed", [])),
        mtm["totalValue"],
    )
    return {
        "status":           "ok",
        "date":             str(today),
        "opened":           rebalance_result.get("opened", []),
        "closed":           rebalance_result.get("closed", []),
        "closedPnl":        rebalance_result.get("closedPnl", 0.0),
        "rebalanceErrors":  rebalance_result.get("errors", []),
        "portfolioValue":   mtm["totalValue"],
        "cash":             mtm["cash"],
        "openPositions":    mtm["openPositions"],
        "totalReturnPct":   total_return_pct,
        "sharpeRatio":      sharpe_ratio,
        "timestamp":        datetime.utcnow().isoformat(),
    }
