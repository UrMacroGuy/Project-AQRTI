"""Risk Center API — /api/v1/risk"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

import numpy as np
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from aqrti.database.engine import get_db_dependency
from aqrti.database.models import DailyPrice, EquityCurvePoint, Trade, PaperPosition, PaperPortfolio
from aqrti.data.market_data import STOCK_META
from aqrti.config.settings import get_settings

router = APIRouter()


def _compute_var(returns: list[float], capital: float, confidence: float = 0.95) -> float:
    """Historical VaR at given confidence level."""
    if not returns:
        return 0.0
    arr = np.array(returns)
    percentile = np.percentile(arr, (1 - confidence) * 100)
    return round(percentile / 100 * capital, 2)


def _compute_sharpe(returns: list[float], risk_free: float = 0.065) -> float:
    """Annualised Sharpe from daily returns (%)."""
    if len(returns) < 5:
        return 0.0
    arr = np.array(returns) / 100
    daily_rf = risk_free / 252
    excess = arr - daily_rf
    if excess.std() == 0:
        return 0.0
    return round(float(excess.mean() / excess.std() * (252 ** 0.5)), 2)


@router.get("")
def get_risk(db: Session = Depends(get_db_dependency)):
    settings = get_settings()
    capital  = settings.paper_capital

    # Latest equity curve point — PortfolioSnapshot (portfolio_snapshots) is
    # dead: record_snapshot() that would populate it is defined but never
    # called anywhere in the pipeline, so the table has 0 rows and every
    # metric sourced from it (VaR, Sharpe, 30d drawdown, drawdown history)
    # silently rendered as 0.00/empty as if that were a real "no risk"
    # reading. EquityCurvePoint is the table the paper-trading pipeline
    # actually writes to every cycle (see performance_tracker.py).
    snap = (
        db.query(EquityCurvePoint)
        .filter_by(portfolio_name="default")
        .order_by(EquityCurvePoint.date.desc())
        .first()
    )
    drawdown = snap.drawdown_pct if snap else 0.0

    # Use paper portfolio for positions and value
    paper_port = db.query(PaperPortfolio).filter_by(portfolio_name="default").first()
    total_value  = paper_port.total_value if paper_port else capital
    current_cash = paper_port.current_cash if paper_port else capital

    # Open paper positions → sector exposure
    open_trades = db.query(PaperPosition).filter_by(portfolio_name="default").all()
    total_deploy = sum(p.capital_deployed for p in open_trades)
    exposure_pct = total_deploy / total_value * 100 if total_value else 0.0

    sector_exposure: dict[str, float] = {}
    for p in open_trades:
        sector = p.sector or STOCK_META.get(p.symbol, {}).get("sector", "Other")
        sector_exposure[sector] = sector_exposure.get(sector, 0) + (p.capital_deployed or 0)

    sector_list = [
        {
            "sector": sector,
            "weight": round(amt / total_value * 100, 1) if total_value else 0.0,
            "limit":  settings.max_sector_pct,
        }
        for sector, amt in sorted(sector_exposure.items(), key=lambda x: -x[1])
    ]
    # Add cash
    cash_pct = max(0.0, round(100 - exposure_pct, 1))
    sector_list.append({"sector": "Cash", "weight": cash_pct, "limit": None})

    # Portfolio returns for VaR + Sharpe
    cutoff = date.today() - timedelta(days=30)
    snaps_30 = (
        db.query(EquityCurvePoint)
        .filter(EquityCurvePoint.portfolio_name == "default", EquityCurvePoint.date >= cutoff)
        .order_by(EquityCurvePoint.date.asc())
        .all()
    )
    portfolio_returns = [s.daily_return_pct for s in snaps_30 if s.daily_return_pct is not None]

    var_daily = _compute_var(portfolio_returns, total_value) if portfolio_returns else 0.0
    sharpe    = _compute_sharpe(portfolio_returns)

    # Max drawdown history
    dd_history = [
        {"date": str(s.date), "drawdown": s.drawdown_pct or 0.0}
        for s in snaps_30
    ]

    # Position risk table (from paper positions)
    positions = []
    for p in open_trades:
        price_rows = (
            db.query(DailyPrice.daily_return)
            .filter(DailyPrice.symbol == p.symbol, DailyPrice.date >= cutoff)
            .order_by(DailyPrice.date.asc())
            .all()
        )
        sym_returns = [r[0] for r in price_rows if r[0] is not None]
        sym_vol     = float(np.std(sym_returns) * (252 ** 0.5)) if len(sym_returns) >= 5 else 0.0
        sym_var     = _compute_var(sym_returns, p.capital_deployed or 0)
        risk_level  = "Low" if sym_vol < 20 else "Medium" if sym_vol < 30 else "High"
        weight_pct  = round(p.capital_deployed / total_value * 100, 1) if total_value else 0.0

        positions.append({
            "symbol":     p.symbol,
            "weight":     f"{weight_pct:.1f}%",
            "var":        sym_var,
            "volatility": round(sym_vol, 1),
            "riskLevel":  risk_level,
        })

    # Circuit breaker status
    daily_dd = min(portfolio_returns[-1], 0) if portfolio_returns else 0
    circuit_breakers = {
        "daily":   {"triggered": daily_dd < -3.0,  "limit": -3.0,  "current": daily_dd},
        "weekly":  {"triggered": drawdown < -6.0,   "limit": -6.0,  "current": drawdown},
        "monthly": {"triggered": drawdown < -12.0,  "limit": -12.0, "current": drawdown},
    }
    any_triggered = any(v["triggered"] for v in circuit_breakers.values())

    return {
        "exposure":        round(exposure_pct, 1),
        "varDaily":        var_daily,
        "varPct":          round(var_daily / total_value * 100, 2) if total_value else 0,
        "maxDrawdown30d":  round(drawdown, 2) if drawdown else 0.0,
        "sharpe":          sharpe,
        "profitFactor":    None,
        "sectorExposure":  sector_list,
        "drawdownHistory": dd_history,
        "positions":       positions,
        "circuitBreakers": circuit_breakers,
        "circuitStatus":   "TRIGGERED" if any_triggered else "CLEAR",
    }
