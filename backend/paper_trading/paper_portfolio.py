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


# A single mark-to-market jump beyond this multiple of the last recorded
# value is treated as corrupted input (bad tick fed through mark_to_market),
# not a real portfolio move. Prevents a fabricated total_value from setting
# a false peak_value/max_drawdown_pct that then poisons every future
# drawdown reading, since max_drawdown_pct is a running min that never
# self-heals once written (2026-07-14 incident: a bad HAL quote inflated
# total_value 9x for several hours, which briefly became peak_value and
# left max_drawdown_pct stuck at -82% long after the value corrected back).
_MAX_PLAUSIBLE_VALUE_RATIO = 3.0


def update_portfolio_value(db: Session, total_value: float, cash: float) -> PaperPortfolio:
    """Recalculate total value, returns, and drawdown then persist."""
    row = get_or_create_portfolio(db)

    last_value = row.total_value or row.initial_capital
    if last_value > 0:
        ratio = max(total_value, last_value) / max(min(total_value, last_value), 1e-9)
        if ratio > _MAX_PLAUSIBLE_VALUE_RATIO:
            log.warning(
                "Rejected implausible portfolio value: last=%.2f new=%.2f (ratio=%.1fx > %.1fx) — "
                "keeping last known-good value, not persisting as peak/drawdown input",
                last_value, total_value, ratio, _MAX_PLAUSIBLE_VALUE_RATIO,
            )
            return row

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
