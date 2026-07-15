"""
Continuous Paper Trading Monitor
=================================
Runs every 5 minutes via the scheduler.

Two jobs:
  1. EXIT monitor — check all open positions for SL/TP/max-hold hits
  2. ENTRY monitor — open new positions when slots are free and signals exist

Uses live yfinance prices (with 60-second cache) so positions are managed
in real-time, not just at end-of-day.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Optional

from aqrti.database.engine import get_db
from aqrti.database.models import (
    PaperPortfolio, PaperPosition, PaperTrade, Prediction, StrategyV2, Stock,
)
from aqrti.utils.logger import get_logger
from paper_trading.paper_trade import NSE_BUY_COST_PCT, NSE_SELL_COST_PCT

log = get_logger("paper_monitor")

PORTFOLIO_NAME    = "default"
MAX_POSITIONS     = 12
MIN_CONFIDENCE    = 60.0   # floor applied to all paper trades — GO-12: verified correct (60, not 50)
MAX_HOLD_DAYS     = 20
CAPITAL_PER_TRADE = 0.07   # 7% of portfolio per new position
MIN_TRADE_CAPITAL = 500.0

# A single trade's exit/entry price ratio implausible beyond this multiple is
# treated as corrupted data (bad tick), not a real market move -- guards
# against a fabricated few-thousand-percent gain/loss reaching current_cash
# even if it slipped past the live-quote deviation check (2026-07-13 HAL
# incident: fake ~35 quote produced a fabricated +823,302 "gain").
MAX_PLAUSIBLE_PRICE_RATIO = 4.0


# ── Price helpers ──────────────────────────────────────────────────────────────

def _get_live_price(db, symbol: str, entry_price: float) -> float:
    """Live yfinance price with fallback to DB EOD close. Reuses the
    caller's session instead of opening a new one per position/call."""
    try:
        from paper_trading.paper_trade import _current_price
        return _current_price(db, symbol, entry_price)
    except Exception:
        return entry_price


def _get_fill_price(db, symbol: str) -> Optional[float]:
    """Latest EOD close from DB."""
    from aqrti.database.models import DailyPrice
    row = (
        db.query(DailyPrice.close)
        .filter(DailyPrice.symbol == symbol)
        .order_by(DailyPrice.date.desc())
        .first()
    )
    return float(row[0]) if row and row[0] else None


# ── Portfolio helpers ──────────────────────────────────────────────────────────

def _get_portfolio(db) -> Optional[PaperPortfolio]:
    return db.query(PaperPortfolio).filter_by(portfolio_name=PORTFOLIO_NAME).first()


def _portfolio_value(db, portfolio: PaperPortfolio, positions: Optional[list] = None) -> float:
    """Current portfolio value = cash + sum of live position values.
    Pass pre-loaded `positions` to avoid re-querying when the caller already has them."""
    invested = 0.0
    if positions is None:
        positions = db.query(PaperPosition).filter_by(portfolio_name=PORTFOLIO_NAME).all()
    for pos in positions:
        price = _get_live_price(db, pos.symbol, pos.entry_price)
        invested += pos.shares * price
    return (portfolio.current_cash or 0.0) + invested


# ── Exit monitor ───────────────────────────────────────────────────────────────

def _check_exits(db) -> tuple[list[dict], set[str]]:
    """
    Check every open position for:
    - Stop-loss hit (price <= stop_loss_price)
    - Take-profit hit (price >= target_price)
    - Max hold days exceeded
    Returns list of closed position dicts.
    """
    portfolio = _get_portfolio(db)
    if not portfolio:
        return [], set()

    closed = []
    today  = date.today()
    closed_symbols_this_cycle: set[str] = set()

    positions = db.query(PaperPosition).filter_by(portfolio_name=PORTFOLIO_NAME).all()
    for pos in positions:
        price      = _get_live_price(db, pos.symbol, pos.entry_price)
        hold_days  = (today - pos.entry_date).days if pos.entry_date else 0
        exit_reason = None

        if pos.stop_loss_price and price <= pos.stop_loss_price:
            exit_reason = "stop_loss"
        elif pos.target_price and price >= pos.target_price:
            exit_reason = "take_profit"
        elif hold_days >= MAX_HOLD_DAYS:
            exit_reason = "max_hold"

        if not exit_reason:
            continue

        # Reject implausible price swings outright rather than trusting them as a
        # real stop-loss/take-profit trigger — a bad tick that slips past the
        # live-quote deviation guard should never close a position on a fabricated
        # multi-hundred-percent move.
        ratio = max(price, pos.entry_price) / max(min(price, pos.entry_price), 1e-9)
        if ratio > MAX_PLAUSIBLE_PRICE_RATIO:
            log.warning(
                "Skipping implausible exit for %s: entry=%.2f live=%.2f (ratio=%.1fx > %.1fx) — treating as bad tick, not a real move",
                pos.symbol, pos.entry_price, price, ratio, MAX_PLAUSIBLE_PRICE_RATIO,
            )
            continue

        # Execute close — apply sell cost to exit price (matches paper_trade.py)
        exit_price = price * (1 - NSE_SELL_COST_PCT)
        pnl        = (exit_price - pos.entry_price) * pos.shares
        pnl_pct    = (exit_price - pos.entry_price) / pos.entry_price * 100

        trade = (
            db.query(PaperTrade)
            .filter_by(portfolio_name=PORTFOLIO_NAME, symbol=pos.symbol, is_open=True)
            .order_by(PaperTrade.entry_date.desc())
            .first()
        )
        if trade:
            trade.exit_date     = today
            trade.exit_price    = round(exit_price, 4)
            trade.gross_pnl     = round(pnl, 4)
            trade.gross_pnl_pct = round(pnl_pct, 4)
            trade.actual_return = round(pnl_pct, 4)
            trade.exit_reason   = exit_reason
            trade.is_open       = False
            trade.holding_days  = hold_days

        portfolio.current_cash = (portfolio.current_cash or 0.0) + pos.capital_deployed + pnl
        db.delete(pos)
        closed_symbols_this_cycle.add(pos.symbol)

        log.info(
            "CLOSE %s @ %.2f  reason=%s  pnl=%.2f (%.1f%%)",
            pos.symbol, exit_price, exit_reason, pnl, pnl_pct,
        )
        closed.append({
            "symbol":      pos.symbol,
            "exit_price":  round(exit_price, 2),
            "pnl":         round(pnl, 2),
            "pnl_pct":     round(pnl_pct, 2),
            "exit_reason": exit_reason,
        })

        # Notify live validator
        if trade:
            try:
                from strategies.live_validator import on_trade_closed
                on_trade_closed(db, trade)
            except Exception:
                pass

    if closed:
        db.commit()

    return closed, closed_symbols_this_cycle


# ── Entry monitor ──────────────────────────────────────────────────────────────

def _get_best_strategy(db) -> dict:
    """Load best promoted/active strategy parameters."""
    try:
        row = (
            db.query(StrategyV2)
            .filter(
                StrategyV2.status.in_(["promoted", "active"]),
                StrategyV2.win_rate >= 50.0,
                StrategyV2.trade_count >= 500,
            )
            .order_by(StrategyV2.fitness_score.desc())
            .first()
        )
        if row:
            dsl = json.loads(row.dsl_json or "{}")
            return {
                "min_confidence": float(dsl.get("min_confidence") or MIN_CONFIDENCE),
                "stop_loss_pct":  float(dsl.get("stop_loss_pct")  or 8.0),
                "take_profit_pct":float(dsl.get("take_profit_pct") or 15.0),
                "strategy_id":    row.strategy_id,
                "strategy_name":  row.name,
            }
    except Exception:
        pass
    return {
        "min_confidence":  MIN_CONFIDENCE,
        "stop_loss_pct":   8.0,
        "take_profit_pct": 15.0,
        "strategy_id":     None,
        "strategy_name":   None,
    }


def _get_sector(db, symbol: str) -> str:
    row = db.query(Stock.sector).filter_by(symbol=symbol).first()
    return row[0] if row and row[0] else "Unknown"


def _check_entries(db, skip_symbols: Optional[set[str]] = None) -> list[dict]:
    """
    Open new positions when portfolio has free slots and bullish signals exist.
    Uses latest predictions (most recent date available).

    `skip_symbols` excludes symbols closed earlier in the same cycle by
    _check_exits — re-entering immediately risks compounding a bad tick that
    just fabricated the exit (see MAX_PLAUSIBLE_PRICE_RATIO note above).
    """
    portfolio = _get_portfolio(db)
    if not portfolio:
        return []

    open_positions = db.query(PaperPosition).filter_by(portfolio_name=PORTFOLIO_NAME).all()
    slots          = MAX_POSITIONS - len(open_positions)
    if slots <= 0:
        return []

    strategy = _get_best_strategy(db)
    min_conf  = strategy["min_confidence"]

    # Get latest prediction date
    latest_row = db.query(Prediction.date).order_by(Prediction.date.desc()).first()
    if not latest_row:
        return []

    preds = (
        db.query(Prediction)
        .filter(
            Prediction.date      == latest_row[0],
            Prediction.confidence >= min_conf,
        )
        .order_by(Prediction.confidence.desc())
        .all()
    )

    # Filter out already-open symbols and symbols just closed this cycle
    held = {p.symbol for p in open_positions}
    skip = held | (skip_symbols or set())
    candidates = [
        p for p in preds
        if p.symbol not in skip
        and (p.direction or "").lower() not in ("bearish", "sell", "short")
    ]

    opened = []
    pv     = _portfolio_value(db, portfolio, positions=open_positions)

    for pred in candidates[:slots]:
        fill = _get_fill_price(db, pred.symbol)
        if not fill or fill <= 0:
            continue

        capital = pv * CAPITAL_PER_TRADE
        capital = max(min(capital, portfolio.current_cash * 0.15), MIN_TRADE_CAPITAL)
        if capital > portfolio.current_cash or portfolio.current_cash < MIN_TRADE_CAPITAL:
            break

        filled_price = fill * (1 + NSE_BUY_COST_PCT)
        shares    = capital / filled_price
        sl_price  = round(filled_price * (1 - strategy["stop_loss_pct"] / 100), 4)
        tp_price  = round(filled_price * (1 + strategy["take_profit_pct"] / 100), 4)
        sector    = _get_sector(db, pred.symbol)

        pos = PaperPosition(
            portfolio_name   = PORTFOLIO_NAME,
            symbol           = pred.symbol,
            sector           = sector,
            entry_date       = date.today(),
            entry_price      = round(filled_price, 4),
            shares           = shares,
            capital_deployed = round(capital, 2),
            weight_pct       = round(capital / pv * 100, 4) if pv > 0 else 0.0,
            direction        = pred.direction or "Bullish",
            confidence       = pred.confidence,
            expected_return  = pred.expected_return or 0.0,
            stop_loss_price  = sl_price,
            target_price     = tp_price,
            prediction_id    = pred.id,
            strategy_id      = strategy["strategy_id"],
            strategy_name    = strategy["strategy_name"],
        )
        db.add(pos)

        trade = PaperTrade(
            portfolio_name   = PORTFOLIO_NAME,
            symbol           = pred.symbol,
            sector           = sector,
            entry_date       = date.today(),
            entry_price      = round(filled_price, 4),
            shares           = shares,
            capital_deployed = round(capital, 2),
            weight_pct       = round(capital / pv * 100, 4) if pv > 0 else 0.0,
            direction        = pred.direction or "Bullish",
            confidence       = pred.confidence,
            predicted_return = pred.expected_return or 0.0,
            is_open          = True,
            prediction_id    = pred.id,
            strategy_id      = strategy["strategy_id"],
            strategy_name    = strategy["strategy_name"],
        )
        db.add(trade)

        portfolio.current_cash -= capital

        log.info(
            "OPEN %s @ %.2f  conf=%.1f%%  capital=%.0f  sl=%.2f  tp=%.2f",
            pred.symbol, fill, pred.confidence, capital, sl_price, tp_price,
        )
        opened.append({
            "symbol":     pred.symbol,
            "entry_price":round(fill, 2),
            "capital":    round(capital, 2),
            "confidence": round(pred.confidence or 0, 1),
        })

    if opened:
        db.commit()

    return opened


# ── MTM update ─────────────────────────────────────────────────────────────────

def _mark_to_market(db) -> float:
    """Update portfolio total_value with current prices. Returns current value."""
    portfolio = _get_portfolio(db)
    if not portfolio:
        return 0.0

    invested = 0.0
    positions = db.query(PaperPosition).filter_by(portfolio_name=PORTFOLIO_NAME).all()
    for pos in positions:
        price = _get_live_price(db, pos.symbol, pos.entry_price)
        invested += pos.shares * price

    total = (portfolio.current_cash or 0.0) + invested
    portfolio.total_value      = round(total, 2)
    portfolio.total_return_pct = round((total - (portfolio.initial_capital or 100_000)) / (portfolio.initial_capital or 100_000) * 100, 4)

    peak = portfolio.peak_value or portfolio.initial_capital or 100_000
    if total > peak:
        portfolio.peak_value = total
    dd = (total - peak) / peak * 100 if peak > 0 else 0.0
    if dd < (portfolio.max_drawdown_pct or 0.0):
        portfolio.max_drawdown_pct = round(dd, 4)

    db.commit()
    return total


# ── Main entry point ───────────────────────────────────────────────────────────

def run_continuous_monitor() -> dict:
    """
    5-minute paper trading heartbeat.
    Returns {closed, opened, portfolio_value, open_positions, timestamp}.
    """
    with get_db() as db:
        closed, closed_symbols = _check_exits(db)
        opened  = _check_entries(db, skip_symbols=closed_symbols)
        pv      = _mark_to_market(db)
        n_open  = db.query(PaperPosition).filter_by(portfolio_name=PORTFOLIO_NAME).count()

    return {
        "closed":          closed,
        "opened":          opened,
        "portfolio_value": pv,
        "open_positions":  n_open,
        "timestamp":       datetime.utcnow().isoformat(),
    }
