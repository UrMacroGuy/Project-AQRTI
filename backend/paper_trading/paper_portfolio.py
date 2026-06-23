"""
Paper Portfolio State Manager
Manages the master portfolio record: cash, total value, drawdown tracking.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy.orm import Session

from aqrti.config.settings import get_settings
from aqrti.database.models import PaperPortfolio
from aqrti.utils.logger import get_logger

log = get_logger("paper_portfolio")

PORTFOLIO_NAME = "default"


def get_or_create_portfolio(db: Session) -> PaperPortfolio:
    """Load the active portfolio row, or seed it from settings if first run."""
    row = db.query(PaperPortfolio).filter_by(portfolio_name=PORTFOLIO_NAME).first()
    if row is None:
        capital = get_settings().paper_capital
        row = PaperPortfolio(
            portfolio_name  = PORTFOLIO_NAME,
            initial_capital = capital,
            current_cash    = capital,
            total_value     = capital,
            peak_value      = capital,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        log.info("Seeded paper portfolio with capital=%.2f", capital)
    return row


def update_portfolio_value(db: Session, total_value: float, cash: float) -> PaperPortfolio:
    """Recalculate total value, returns, and drawdown then persist."""
    row = get_or_create_portfolio(db)

    if total_value > (row.peak_value or row.initial_capital):
        row.peak_value = total_value

    peak = row.peak_value or row.initial_capital
    row.total_value      = total_value
    row.current_cash     = cash
    row.total_return_pct = (total_value - row.initial_capital) / row.initial_capital * 100
    row.max_drawdown_pct = min(
        row.max_drawdown_pct or 0.0,
        (total_value - peak) / peak * 100,
    )
    row.updated_at = datetime.utcnow()
    db.commit()
    return row


def get_portfolio_summary(db: Session) -> dict:
    """Return full portfolio state as API-friendly dict."""
    row = get_or_create_portfolio(db)
    invested = row.total_value - row.current_cash
    return {
        "portfolioName":    row.portfolio_name,
        "initialCapital":   row.initial_capital,
        "currentCash":      round(row.current_cash, 2),
        "totalValue":       round(row.total_value, 2),
        "investedCapital":  round(invested, 2),
        "cashPct":          round(row.current_cash / row.total_value * 100, 2) if row.total_value else 100.0,
        "totalReturnPct":   round(row.total_return_pct or 0.0, 4),
        "maxDrawdownPct":   round(row.max_drawdown_pct or 0.0, 4),
        "peakValue":        round(row.peak_value or row.initial_capital, 2),
        "updatedAt":        str(row.updated_at.date()) if row.updated_at else str(date.today()),
    }
