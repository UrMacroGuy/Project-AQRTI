"""
Rebalancer
Compares the current portfolio (open positions) against the target weights
and generates a diff: what to open, what to close, what to hold.

Does NOT execute any trades — returns instructions only.
Execution is performed by paper_trading.paper_execution.
"""

from __future__ import annotations

from datetime import date
from sqlalchemy.orm import Session

from aqrti.utils.logger import get_logger

log = get_logger("rebalancer")

DRIFT_THRESHOLD = 2.0    # percent — don't rebalance if weight drift < this


def compute_rebalance_diff(
    current_positions: list[dict],    # from paper_trade.get_open_positions()
    target_weights:    dict[str, float],
    portfolio_value:   float,
) -> dict:
    """
    Compute what changes are needed to move from current → target.

    Returns:
      {
        to_open:  [{symbol, target_weight_pct, reason}],
        to_close: [{symbol, current_weight_pct, reason}],
        to_hold:  [{symbol, current_weight_pct, target_weight_pct, drift}],
        no_change: bool,
      }
    """
    current_weights = {
        p["symbol"]: p["currentValue"] / portfolio_value * 100
        for p in current_positions
        if portfolio_value > 0
    }

    current_set = set(current_weights.keys())
    target_set  = set(target_weights.keys())

    to_open  = []
    to_close = []
    to_hold  = []

    for sym in target_set - current_set:
        to_open.append({
            "symbol":          sym,
            "targetWeightPct": round(target_weights[sym], 2),
            "reason":          "new_signal",
        })

    for sym in current_set - target_set:
        to_close.append({
            "symbol":          sym,
            "currentWeightPct": round(current_weights[sym], 2),
            "reason":          "signal_removed",
        })

    for sym in current_set & target_set:
        drift = abs(current_weights[sym] - target_weights[sym])
        to_hold.append({
            "symbol":          sym,
            "currentWeightPct": round(current_weights[sym], 2),
            "targetWeightPct":  round(target_weights[sym], 2),
            "drift":            round(drift, 2),
        })

    no_change = (len(to_open) == 0 and len(to_close) == 0)
    log.info(
        "Rebalance diff: open=%d  close=%d  hold=%d  no_change=%s",
        len(to_open), len(to_close), len(to_hold), no_change,
    )
    return {
        "to_open":   to_open,
        "to_close":  to_close,
        "to_hold":   to_hold,
        "no_change": no_change,
        "date":      str(date.today()),
    }


def get_rebalance_preview(db: Session, version: int = 1) -> dict:
    """
    Generate a rebalance preview without executing anything.
    Useful for the UI /api/v1/rebalance GET endpoint.
    """
    import sys, os
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)

    from portfolio.portfolio_builder import build_target_portfolio
    from paper_trading.paper_trade import get_open_positions
    from paper_trading.paper_portfolio import get_or_create_portfolio

    portfolio   = get_or_create_portfolio(db)
    current_pos = get_open_positions(db)
    target      = build_target_portfolio(db, version=version)
    diff        = compute_rebalance_diff(
        current_pos, target["weights"], portfolio.total_value
    )
    return {
        "target":     target,
        "diff":       diff,
        "portfolioValue": portfolio.total_value,
    }
