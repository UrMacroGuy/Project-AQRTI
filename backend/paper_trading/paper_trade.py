"""
Paper Trade Manager
Open, close, and query virtual positions + trades.
All prices come from the daily_prices table — no live market feeds.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy.orm import Session

from aqrti.database.models import PaperPosition, PaperTrade, DailyPrice, Stock
from aqrti.utils.logger import get_logger

log = get_logger("paper_trade")

PORTFOLIO_NAME = "default"


def _latest_price(db: Session, symbol: str) -> Optional[float]:
    row = (
        db.query(DailyPrice.close)
        .filter(DailyPrice.symbol == symbol)
        .order_by(DailyPrice.date.desc())
        .first()
    )
    return row[0] if row else None


def open_position(
    db:              Session,
    symbol:          str,
    capital:         float,          # rupees to deploy
    portfolio_value: float,
    entry_price:     float,
    direction:       str  = "Bullish",
    confidence:      float = 0.0,
    expected_return: float = 0.0,
    sector:          str  = None,
    prediction_id:   int  = None,
) -> Optional[PaperPosition]:
    """
    Open a new paper position. Idempotent — no-op if symbol already open.
    Returns the PaperPosition row, or None if price is unavailable.
    """
    existing = (
        db.query(PaperPosition)
        .filter_by(portfolio_name=PORTFOLIO_NAME, symbol=symbol)
        .first()
    )
    if existing:
        log.debug("Position already open for %s — skipping open", symbol)
        return existing

    if entry_price <= 0:
        log.warning("Invalid entry price %.4f for %s", entry_price, symbol)
        return None

    shares    = capital / entry_price
    weight    = capital / portfolio_value * 100 if portfolio_value > 0 else 0.0
    stop_loss = entry_price * 0.92        # 8% hard stop
    target    = entry_price * (1 + max(expected_return / 100, 0.03))

    pos = PaperPosition(
        portfolio_name   = PORTFOLIO_NAME,
        symbol           = symbol,
        sector           = sector,
        entry_date       = date.today(),
        entry_price      = entry_price,
        shares           = shares,
        capital_deployed = capital,
        weight_pct       = round(weight, 4),
        direction        = direction,
        confidence       = confidence,
        expected_return  = expected_return,
        stop_loss_price  = round(stop_loss, 4),
        target_price     = round(target, 4),
        prediction_id    = prediction_id,
    )
    db.add(pos)

    trade = PaperTrade(
        portfolio_name   = PORTFOLIO_NAME,
        symbol           = symbol,
        sector           = sector,
        entry_date       = date.today(),
        entry_price      = entry_price,
        shares           = shares,
        capital_deployed = capital,
        weight_pct       = round(weight, 4),
        direction        = direction,
        confidence       = confidence,
        predicted_return = expected_return,
        is_open          = True,
        prediction_id    = prediction_id,
    )
    db.add(trade)
    db.commit()
    log.info("Opened position: %s  shares=%.4f  capital=%.2f", symbol, shares, capital)
    return pos


def close_position(
    db:          Session,
    symbol:      str,
    exit_reason: str = "rebalance",
) -> Optional[dict]:
    """
    Close an open position using the latest available price.
    Returns a dict with realized P&L, or None if no open position.
    """
    pos = (
        db.query(PaperPosition)
        .filter_by(portfolio_name=PORTFOLIO_NAME, symbol=symbol)
        .first()
    )
    if not pos:
        return None

    exit_price = _latest_price(db, symbol) or pos.entry_price
    gross_pnl     = (exit_price - pos.entry_price) / pos.entry_price * pos.capital_deployed
    gross_pnl_pct = (exit_price - pos.entry_price) / pos.entry_price * 100
    actual_return  = gross_pnl_pct
    holding_days  = (date.today() - pos.entry_date).days

    trade = (
        db.query(PaperTrade)
        .filter_by(portfolio_name=PORTFOLIO_NAME, symbol=symbol, is_open=True)
        .order_by(PaperTrade.entry_date.desc())
        .first()
    )
    if trade:
        trade.exit_date      = date.today()
        trade.exit_price     = exit_price
        trade.gross_pnl      = round(gross_pnl, 4)
        trade.gross_pnl_pct  = round(gross_pnl_pct, 4)
        trade.actual_return  = round(actual_return, 4)
        trade.exit_reason    = exit_reason
        trade.is_open        = False
        trade.holding_days   = holding_days

    db.delete(pos)
    db.commit()
    log.info(
        "Closed position: %s  exit=%.2f  pnl=%.2f (%.2f%%)  reason=%s",
        symbol, exit_price, gross_pnl, gross_pnl_pct, exit_reason,
    )
    return {
        "symbol":        symbol,
        "exitPrice":     exit_price,
        "grossPnl":      round(gross_pnl, 4),
        "grossPnlPct":   round(gross_pnl_pct, 4),
        "holdingDays":   holding_days,
        "exitReason":    exit_reason,
    }


def _get_sector(db: Session, symbol: str) -> str:
    row = db.query(Stock.sector).filter_by(symbol=symbol).first()
    return row[0] if row and row[0] else "—"


def get_open_positions(db: Session) -> list[dict]:
    """Return all open positions with current unrealized P&L."""
    positions = (
        db.query(PaperPosition)
        .filter_by(portfolio_name=PORTFOLIO_NAME)
        .order_by(PaperPosition.capital_deployed.desc())
        .all()
    )
    result = []
    for pos in positions:
        current_price = _latest_price(db, pos.symbol) or pos.entry_price
        unrealized_pct = (current_price - pos.entry_price) / pos.entry_price * 100
        unrealized_pnl = unrealized_pct / 100 * pos.capital_deployed
        current_value  = pos.capital_deployed + unrealized_pnl
        sector = pos.sector if (pos.sector and 'â' not in pos.sector) else _get_sector(db, pos.symbol)
        result.append({
            "symbol":          pos.symbol,
            "sector":          sector,
            "entryDate":       str(pos.entry_date),
            "entryPrice":      round(pos.entry_price, 4),
            "currentPrice":    round(current_price, 4),
            "shares":          round(pos.shares, 4),
            "capitalDeployed": round(pos.capital_deployed, 2),
            "currentValue":    round(current_value, 2),
            "weightPct":       round(pos.weight_pct or 0.0, 2),
            "unrealizedPnl":   round(unrealized_pnl, 2),
            "unrealizedPct":   round(unrealized_pct, 4),
            "direction":       pos.direction or "Bullish",
            "confidence":      round(pos.confidence or 0.0, 1),
            "expectedReturn":  round(pos.expected_return or 0.0, 4),
            "stopLoss":        round(pos.stop_loss_price or 0.0, 4),
            "target":          round(pos.target_price or 0.0, 4),
        })
    return result


def get_trade_history(db: Session, limit: int = 100, symbol: str = None) -> list[dict]:
    """Return closed trades ordered by exit date desc."""
    q = (
        db.query(PaperTrade)
        .filter_by(portfolio_name=PORTFOLIO_NAME, is_open=False)
        .order_by(PaperTrade.exit_date.desc())
    )
    if symbol:
        q = q.filter(PaperTrade.symbol == symbol)
    trades = q.limit(limit).all()

    return [
        {
            "symbol":          t.symbol,
            "sector":          t.sector or "—",
            "entryDate":       str(t.entry_date),
            "exitDate":        str(t.exit_date) if t.exit_date else None,
            "entryPrice":      round(t.entry_price, 4),
            "exitPrice":       round(t.exit_price or 0, 4),
            "shares":          round(t.shares, 4),
            "capitalDeployed": round(t.capital_deployed, 2),
            "grossPnl":        round(t.gross_pnl or 0, 2),
            "grossPnlPct":     round(t.gross_pnl_pct or 0, 4),
            "direction":       t.direction or "—",
            "confidence":      round(t.confidence or 0, 1),
            "predictedReturn": round(t.predicted_return or 0, 4),
            "actualReturn":    round(t.actual_return or 0, 4),
            "exitReason":      t.exit_reason or "—",
            "holdingDays":     t.holding_days or 0,
        }
        for t in trades
    ]
