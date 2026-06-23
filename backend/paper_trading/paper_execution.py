"""
Paper Execution Engine
Converts target portfolio weights into open/close actions.
No live market access — uses daily_prices close as fill price.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from sqlalchemy.orm import Session

from aqrti.database.models import DailyPrice
from aqrti.utils.logger import get_logger
from paper_trading.paper_portfolio import get_or_create_portfolio, update_portfolio_value
from paper_trading.paper_trade import (
    open_position, close_position, get_open_positions,
)

log = get_logger("paper_execution")


def _get_fill_price(db: Session, symbol: str) -> Optional[float]:
    """Use latest close as fill price — simulates market-on-close execution."""
    row = (
        db.query(DailyPrice.close)
        .filter(DailyPrice.symbol == symbol)
        .order_by(DailyPrice.date.desc())
        .first()
    )
    return row[0] if row else None


def execute_rebalance(
    db:              Session,
    target_weights:  dict[str, float],   # {symbol: weight_pct}
    reason:          str = "rebalance",
) -> dict:
    """
    Compare current positions against target_weights and execute trades.

    Rules:
    - Symbols in target_weights but not in portfolio → open new position
    - Symbols in portfolio but not in target_weights → close position
    - Portfolio value is recalculated after each close before new opens

    Returns execution report dict.
    """
    portfolio  = get_or_create_portfolio(db)
    current    = {p["symbol"] for p in get_open_positions(db)}
    target_set = set(target_weights.keys())

    to_close = current - target_set
    to_open  = target_set - current

    closed_pnl  = 0.0
    closed_list = []
    opened_list = []
    errors      = []

    # ── Close exits first to free up cash ────────────────────────
    for symbol in sorted(to_close):
        result = close_position(db, symbol, exit_reason=reason)
        if result:
            closed_pnl  += result["grossPnl"]
            closed_list.append(result["symbol"])

    # ── Refresh portfolio after closes ────────────────────────────
    portfolio = get_or_create_portfolio(db)

    # ── Open new positions ────────────────────────────────────────
    for symbol in sorted(to_open):
        weight    = target_weights[symbol]
        fill      = _get_fill_price(db, symbol)
        if not fill:
            errors.append({"symbol": symbol, "error": "no_price"})
            log.warning("No price for %s — skipping open", symbol)
            continue

        capital = portfolio.current_cash * (weight / 100)

        # Check we have enough cash (with 1% buffer)
        if capital > portfolio.current_cash * 0.99:
            capital = portfolio.current_cash * 0.95

        if capital < 100:
            errors.append({"symbol": symbol, "error": "insufficient_cash"})
            continue

        pos = open_position(
            db              = db,
            symbol          = symbol,
            capital         = capital,
            portfolio_value = portfolio.total_value,
            entry_price     = fill,
            direction       = "Bullish",
        )
        if pos:
            portfolio.current_cash -= capital
            opened_list.append(symbol)

    # ── Recalculate total portfolio value ─────────────────────────
    open_pos   = get_open_positions(db)
    invested   = sum(p["currentValue"] for p in open_pos)
    total_val  = portfolio.current_cash + invested
    update_portfolio_value(db, total_val, portfolio.current_cash)

    log.info(
        "Rebalance: closed=%d opened=%d errors=%d  new_value=%.2f",
        len(closed_list), len(opened_list), len(errors), total_val,
    )
    return {
        "date":         str(date.today()),
        "closed":       closed_list,
        "opened":       opened_list,
        "closedPnl":    round(closed_pnl, 2),
        "errors":       errors,
        "portfolioValue": round(total_val, 2),
    }


def mark_to_market(db: Session) -> dict:
    """
    Recalculate current portfolio value using latest prices.
    Call this daily after market close to update equity curve.
    """
    portfolio = get_or_create_portfolio(db)
    open_pos  = get_open_positions(db)

    invested  = sum(p["currentValue"] for p in open_pos)
    total_val = portfolio.current_cash + invested
    update_portfolio_value(db, total_val, portfolio.current_cash)

    return {
        "date":           str(date.today()),
        "totalValue":     round(total_val, 2),
        "cash":           round(portfolio.current_cash, 2),
        "invested":       round(invested, 2),
        "openPositions":  len(open_pos),
    }
