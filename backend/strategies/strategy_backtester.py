"""
Strategy Backtester
Evaluates a StrategyDSL against historical feature data.

For each day in the backtest window:
  1. Load feature row for each symbol
  2. Evaluate entry conditions → generate signals
  3. Simulate trade: enter at next open (approx.), exit per DSL rules
  4. Compute trade-level P&L from DailyPrice data

Returns BacktestResult with all metrics.
Does NOT write to paper trades — purely analytical.
"""

from __future__ import annotations

import sys, os, json
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

import numpy as np

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from sqlalchemy.orm import Session
from aqrti.database.models import FeatureValue, DailyPrice, MarketRegime, Stock
from aqrti.utils.logger import get_logger
from strategies.strategy_dsl import StrategyDSL
from strategies.strategy_metrics import (
    compute_sharpe, compute_sortino, compute_max_drawdown,
    compute_profit_factor, compute_expectancy,
)

log = get_logger("strategy_backtester")

SLIPPAGE_PCT    = 0.05    # 5bps round-trip slippage
COMMISSION_PCT  = 0.03    # 3bps commission
POSITION_SIZE   = 0.05    # 5% of capital per trade
MAX_OPEN_TRADES = 10      # concurrent positions cap


@dataclass
class TradeRecord:
    symbol:       str
    entry_date:   date
    exit_date:    Optional[date]
    entry_price:  float
    exit_price:   Optional[float]
    pnl_pct:      Optional[float]
    exit_reason:  str = ""
    holding_days: int = 0


@dataclass
class BacktestResult:
    strategy_id:     str
    start_date:      date
    end_date:        date
    universe_size:   int
    trades:          list[TradeRecord] = field(default_factory=list)
    # Metrics — filled by compute_metrics()
    sharpe:          float = 0.0
    sortino:         float = 0.0
    win_rate:        float = 0.0
    profit_factor:   float = 1.0
    max_drawdown:    float = 0.0
    expectancy:      float = 0.0
    total_return:    float = 0.0
    trade_count:     int   = 0
    avg_holding_days: float = 0.0
    exposure_pct:    float = 0.0
    bull_sharpe:     float = 0.0
    bear_sharpe:     float = 0.0
    sideways_sharpe: float = 0.0
    volatile_sharpe: float = 0.0
    regime_trades:   dict  = field(default_factory=dict)

    def compute_metrics(self) -> None:
        closed = [t for t in self.trades if t.pnl_pct is not None]
        if not closed:
            return
        returns = [t.pnl_pct for t in closed]
        wins    = [r for r in returns if r > 0]
        losses  = [r for r in returns if r <= 0]

        self.trade_count      = len(closed)
        self.win_rate         = len(wins) / len(closed) * 100 if closed else 0.0
        self.profit_factor    = compute_profit_factor(wins, losses)
        self.expectancy       = compute_expectancy(returns)
        self.max_drawdown     = compute_max_drawdown(list(np.cumsum(returns)))
        self.total_return     = round(sum(returns), 4)
        self.avg_holding_days = round(
            sum(t.holding_days for t in closed) / len(closed), 1
        ) if closed else 0.0

        # Daily return series (approx: distribute trade return across holding days)
        daily_returns = []
        for t in closed:
            days = max(t.holding_days, 1)
            daily = t.pnl_pct / days * POSITION_SIZE
            daily_returns.extend([daily] * days)

        self.sharpe  = compute_sharpe(daily_returns)
        self.sortino = compute_sortino(daily_returns)


def _get_regime(db: Session, on_date: date) -> str:
    row = (
        db.query(MarketRegime.regime)
        .filter(MarketRegime.date <= on_date)
        .order_by(MarketRegime.date.desc())
        .first()
    )
    return row[0] if row else "BULL"


def _load_feature_row(db: Session, symbol: str, on_date: date) -> dict:
    rows = (
        db.query(FeatureValue.feature_name, FeatureValue.value)
        .filter(FeatureValue.symbol == symbol, FeatureValue.date == on_date)
        .all()
    )
    return {r[0]: r[1] for r in rows if r[1] is not None}


def _price_on(db: Session, symbol: str, on_date: date, look_ahead: int = 0) -> Optional[float]:
    target = on_date + timedelta(days=look_ahead)
    row = (
        db.query(DailyPrice.close)
        .filter(DailyPrice.symbol == symbol, DailyPrice.date >= target)
        .order_by(DailyPrice.date.asc())
        .first()
    )
    return row[0] if row else None


def backtest_strategy(
    db:         Session,
    strategy:   StrategyDSL,
    start_date: date,
    end_date:   date,
    universe:   Optional[list[str]] = None,
    max_stocks: int = 50,
) -> BacktestResult:
    """
    Run vectorised backtest for a strategy over a historical window.

    Args:
        db:         DB session
        strategy:   StrategyDSL to evaluate
        start_date: backtest start
        end_date:   backtest end
        universe:   list of symbols to test (defaults to active NSE50 stocks)
        max_stocks: cap on universe size for performance

    Returns:
        BacktestResult with all metrics filled.
    """
    sid = strategy.strategy_id()

    if universe is None:
        rows = (
            db.query(Stock.symbol)
            .filter(Stock.active == True, Stock.nifty_member == True)
            .limit(max_stocks)
            .all()
        )
        universe = [r[0] for r in rows] or ["RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK"]

    result = BacktestResult(
        strategy_id  = sid,
        start_date   = start_date,
        end_date     = end_date,
        universe_size = len(universe),
    )

    # Collect all dates in the window
    all_dates = []
    cur = start_date
    while cur <= end_date:
        all_dates.append(cur)
        cur += timedelta(days=1)

    open_positions: dict[str, dict] = {}   # symbol → {entry_date, entry_price, holding_days, regime_entry}
    regime_returns: dict[str, list[float]] = {"BULL": [], "BEAR": [], "SIDEWAYS": [], "VOLATILE": []}

    for d in all_dates:
        regime = _get_regime(db, d)

        # Check exits on open positions
        for sym in list(open_positions.keys()):
            pos    = open_positions[sym]
            pos["holding_days"] += 1
            features = _load_feature_row(db, sym, d)
            cur_price = _price_on(db, sym, d)
            if cur_price is None:
                continue
            pnl_pct = (cur_price - pos["entry_price"]) / pos["entry_price"] * 100
            should_exit, reason = strategy.should_exit(features, pos["holding_days"], pnl_pct)

            if should_exit or d == end_date:
                # Apply slippage + commission
                net_pnl = pnl_pct - SLIPPAGE_PCT - COMMISSION_PCT
                t = TradeRecord(
                    symbol       = sym,
                    entry_date   = pos["entry_date"],
                    exit_date    = d,
                    entry_price  = pos["entry_price"],
                    exit_price   = cur_price,
                    pnl_pct      = round(net_pnl, 4),
                    exit_reason  = reason or "end_of_backtest",
                    holding_days = pos["holding_days"],
                )
                result.trades.append(t)
                regime_returns[pos.get("regime_entry", "BULL")].append(net_pnl)
                del open_positions[sym]

        # Check entries
        if len(open_positions) >= MAX_OPEN_TRADES:
            continue

        for sym in universe:
            if sym in open_positions:
                continue
            features = _load_feature_row(db, sym, d)
            if not features:
                continue
            if strategy.should_enter(features, regime):
                entry_price = _price_on(db, sym, d, look_ahead=1)  # enter next day
                if entry_price:
                    open_positions[sym] = {
                        "entry_date":   d,
                        "entry_price":  entry_price * (1 + SLIPPAGE_PCT / 100),
                        "holding_days": 0,
                        "regime_entry": regime,
                    }

    result.compute_metrics()

    # Regime-stratified Sharpe
    for reg, rets in regime_returns.items():
        if len(rets) >= 5:
            s = compute_sharpe(rets)
            setattr(result, f"{reg.lower()}_sharpe", s)

    result.regime_trades = {k: len(v) for k, v in regime_returns.items()}

    log.info(
        "Backtest %s: trades=%d sharpe=%.3f win_rate=%.1f%% mdd=%.1f%%",
        sid, result.trade_count, result.sharpe, result.win_rate, result.max_drawdown,
    )
    return result


def backtest_and_update(
    db:         Session,
    strategy:   StrategyDSL,
    start_date: Optional[date] = None,
    end_date:   Optional[date] = None,
    universe:   Optional[list[str]] = None,
) -> BacktestResult:
    """Backtest a strategy and write results to StrategyV2."""
    from strategies.strategy_store import upsert_strategy

    end   = end_date   or date.today()
    start = start_date or (end - timedelta(days=365))

    result = backtest_strategy(db, strategy, start_date=start, end_date=end, universe=universe)

    upsert_strategy(db, {
        "strategy_id":      result.strategy_id,
        "sharpe":           result.sharpe,
        "sortino":          result.sortino,
        "win_rate":         result.win_rate,
        "profit_factor":    result.profit_factor,
        "max_drawdown":     result.max_drawdown,
        "expectancy":       result.expectancy,
        "trade_count":      result.trade_count,
        "avg_holding_days": result.avg_holding_days,
        "bull_sharpe":      result.bull_sharpe,
        "bear_sharpe":      result.bear_sharpe,
        "sideways_sharpe":  result.sideways_sharpe,
        "volatile_sharpe":  result.volatile_sharpe,
        "backtest_start":   start,
        "backtest_end":     end,
        "backtest_universe": result.universe_size,
        "status":           "shadow",  # moves to shadow after backtest
    })
    db.commit()
    return result
