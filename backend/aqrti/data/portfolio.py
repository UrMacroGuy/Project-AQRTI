"""
AQRTI Paper Portfolio Engine
Manages virtual capital, open positions, P&L tracking, and equity curve.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from aqrti.config.settings import get_settings
from aqrti.database.models import PortfolioSnapshot, Trade, DailyPrice, PaperPortfolio, PaperTrade
from aqrti.utils.logger import data_logger


def get_portfolio_summary(db: Session) -> dict:
    """Return current portfolio state — prefers live paper portfolio over legacy snapshots."""
    settings = get_settings()

    # Prefer PaperPortfolio (active paper trading engine)
    paper = db.query(PaperPortfolio).filter_by(portfolio_name="default").first()
    if paper:
        open_count = db.query(PaperTrade).filter(PaperTrade.is_open == True).count()
        invested = paper.initial_capital - paper.current_cash
        return {
            "portfolioValue":   paper.total_value,
            "paperCapitalStart": paper.initial_capital,
            "dailyPnl":         0.0,
            "dailyPnlPct":      0.0,
            "openPositions":    open_count,
            "deployedCapital":  max(invested, 0.0),
            "cashReserve":      paper.current_cash,
            "totalReturn":      (paper.total_value - paper.initial_capital) / paper.initial_capital * 100,
            "drawdown":         0.0,
            "sharpe30d":        0.0,
            "lastUpdated":      str(date.today()),
        }

    latest = (
        db.query(PortfolioSnapshot)
        .order_by(PortfolioSnapshot.date.desc())
        .first()
    )

    open_trades = db.query(Trade).filter(Trade.is_open == True).all()

    if latest:
        return {
            "portfolioValue":  latest.total_value,
            "paperCapitalStart": settings.paper_capital,
            "dailyPnl":        latest.daily_pnl or 0.0,
            "dailyPnlPct":     latest.daily_pnl_pct or 0.0,
            "openPositions":   latest.open_positions or len(open_trades),
            "deployedCapital": latest.invested or 0.0,
            "cashReserve":     latest.cash or settings.paper_capital,
            "totalReturn":     latest.total_return or 0.0,
            "drawdown":        latest.drawdown or 0.0,
            "sharpe30d":       latest.sharpe_30d or 0.0,
            "lastUpdated":     str(latest.date),
        }

    # No snapshot yet — return defaults
    return {
        "portfolioValue":   settings.paper_capital,
        "paperCapitalStart": settings.paper_capital,
        "dailyPnl":         0.0,
        "dailyPnlPct":      0.0,
        "openPositions":    0,
        "deployedCapital":  0.0,
        "cashReserve":      settings.paper_capital,
        "totalReturn":      0.0,
        "drawdown":         0.0,
        "sharpe30d":        0.0,
        "lastUpdated":      str(date.today()),
    }


def get_equity_curve(db: Session, days: int = 30) -> dict:
    """Return equity curve from portfolio snapshots."""
    cutoff = date.today() - timedelta(days=days)
    rows = (
        db.query(PortfolioSnapshot)
        .filter(PortfolioSnapshot.date >= cutoff)
        .order_by(PortfolioSnapshot.date.asc())
        .all()
    )
    if rows:
        return {
            "labels": [str(r.date) for r in rows],
            "values": [r.total_value for r in rows],
        }

    # Synthetic flat line when no data yet
    settings = get_settings()
    labels, values = [], []
    for i in range(days, -1, -1):
        d = date.today() - timedelta(days=i)
        labels.append(str(d))
        values.append(settings.paper_capital)
    return {"labels": labels, "values": values}


def get_open_positions(db: Session) -> list[dict]:
    """Return all open paper trades with current P&L calculated."""
    trades = db.query(Trade).filter(Trade.is_open == True).all()
    result = []
    for t in trades:
        # Look up latest price for live P&L
        latest_price_row = (
            db.query(DailyPrice.close)
            .filter(DailyPrice.symbol == t.symbol)
            .order_by(DailyPrice.date.desc())
            .first()
        )
        current_price = latest_price_row[0] if latest_price_row else t.entry_price
        unrealized_pnl = (current_price - t.entry_price) / t.entry_price * t.position_size
        result.append({
            "symbol":         t.symbol,
            "entryDate":      str(t.entry_date),
            "entryPrice":     t.entry_price,
            "currentPrice":   current_price,
            "positionSize":   t.position_size,
            "positionPct":    t.position_pct,
            "unrealizedPnl":  round(unrealized_pnl, 2),
            "unrealizedPct":  round((current_price - t.entry_price) / t.entry_price * 100, 2),
            "strategy":       t.strategy,
            "confidence":     t.confidence,
        })
    return result


def record_snapshot(
    db: Session,
    total_value: float,
    cash: float,
    daily_pnl: float,
    daily_pnl_pct: float,
    open_positions: int,
) -> None:
    """Upsert today's portfolio snapshot."""
    settings = get_settings()
    invested = total_value - cash
    total_return = (total_value - settings.paper_capital) / settings.paper_capital * 100

    existing = db.query(PortfolioSnapshot).filter_by(date=date.today()).first()
    if existing:
        existing.total_value    = total_value
        existing.cash           = cash
        existing.invested       = invested
        existing.daily_pnl      = daily_pnl
        existing.daily_pnl_pct  = daily_pnl_pct
        existing.total_return   = total_return
        existing.open_positions = open_positions
    else:
        db.add(PortfolioSnapshot(
            date           = date.today(),
            total_value    = total_value,
            cash           = cash,
            invested       = invested,
            daily_pnl      = daily_pnl,
            daily_pnl_pct  = daily_pnl_pct,
            total_return   = total_return,
            open_positions = open_positions,
        ))
    db.commit()
