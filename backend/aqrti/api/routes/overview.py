"""Overview API — /api/v1/overview"""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from aqrti.database.engine import get_db_dependency
from aqrti.database.models import (
    KnowledgeScore, Mistake, Prediction, Strategy, StrategyV2, Trade, PaperTrade,
)
from aqrti.data.market_data import get_latest_index
from aqrti.data.portfolio import get_portfolio_summary, get_equity_curve
from aqrti.utils.logger import api_logger

router = APIRouter()


@router.get("")
def get_overview(db: Session = Depends(get_db_dependency)):
    """
    Master overview endpoint.
    Returns portfolio state, regime, knowledge score, and equity curve.
    """
    portfolio = get_portfolio_summary(db)

    # Knowledge score
    ks = db.query(KnowledgeScore).order_by(KnowledgeScore.date.desc()).first()
    knowledge_score = ks.overall_score if ks else 0.0

    # Active predictions count + avg confidence
    today_preds = db.query(Prediction).filter(Prediction.actual_return == None).all()
    avg_conf = (
        sum(p.confidence for p in today_preds if p.confidence) / len(today_preds)
        if today_preds else 0.0
    )

    # Win rate last 30 days — from paper trades (closed positions)
    cutoff30 = date.today() - timedelta(days=30)
    closed_trades = db.query(PaperTrade).filter(
        PaperTrade.portfolio_name == "default",
        PaperTrade.is_open == False,
        PaperTrade.exit_date != None,
    ).all()
    recent_closed = [t for t in closed_trades if t.exit_date and t.exit_date >= cutoff30]
    recent_wins   = [t for t in recent_closed if (t.gross_pnl or 0) > 0]
    win_rate      = (len(recent_wins) / len(recent_closed) * 100) if recent_closed else 0.0
    total_trades_30d = len(recent_closed)

    # Regime from latest index data
    nifty = get_latest_index(db, "NIFTY50")
    regime = "BULL MARKET"
    regime_conf = 85.0
    if nifty and nifty.get("returns") is not None:
        ret = nifty["returns"]
        if ret < -0.5:
            regime = "BEAR MARKET"
        elif abs(ret) < 0.2:
            regime = "RANGE BOUND"

    # Open positions — prefer PaperTrade (active paper trading), fall back to old Trade model
    open_trades = db.query(PaperTrade).filter(PaperTrade.is_open == True).count()
    if open_trades == 0:
        open_trades = db.query(Trade).filter(Trade.is_open == True).count()

    # Strategies active — check StrategyV2 (evolution engine) first, fall back to old table
    active_strats = db.query(StrategyV2).filter(
        StrategyV2.status.in_(["active", "promoted", "shadow"])
    ).count()
    if active_strats == 0:
        active_strats = db.query(Strategy).filter(
            Strategy.status.in_(["production", "paper", "institutional"])
        ).count()

    equity = get_equity_curve(db, days=30)

    return {
        "portfolioValue":    portfolio["portfolioValue"],
        "paperCapitalStart": portfolio["paperCapitalStart"],
        "dailyPnl":          portfolio["dailyPnl"],
        "dailyPnlPct":       portfolio["dailyPnlPct"],
        "openPositions":     open_trades,
        "deployedCapital":   portfolio["deployedCapital"],
        "activePredictions": len(today_preds),
        "avgConfidence":     round(avg_conf, 1),
        "winRate30d":        round(win_rate, 1),
        "totalTrades30d":    total_trades_30d,
        "knowledgeScore":    knowledge_score,
        "activeStrategies":  active_strats,
        "regime":            regime,
        "regimeConf":        regime_conf,
        "equityCurve":       equity,
        "lastUpdated":       portfolio["lastUpdated"],
    }
