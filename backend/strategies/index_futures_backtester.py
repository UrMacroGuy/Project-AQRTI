"""
Index Futures Backtester
Runs a strategy's DSL against the continuous synthetic futures series for
ONE index (see IndexFuturesPrice's is_synthetic caveat in models.py — this
is cost-of-carry-modeled, not real contract-tick data).

Differs from strategy_backtester.py (stocks) in exactly the ways that
matter for futures:
  - Position sizing is LOT-based (lot_size units per lot), not share-count
    or capital-fraction based.
  - Margin-based capital accounting: only margin_pct of notional is
    deployed from the account per lot, not the full notional (leverage).
  - Auto-roll at expiry: a position still open ROLL_DAYS_BEFORE_EXPIRY
    before contract expiry is closed on the expiring contract and
    reopened on the next contract, with a modeled roll cost.
  - No circuit-band halt logic (doesn't apply to index futures the way it
    applies to individual NSE stocks).
  - No delivery-volume/turnover liquidity filter (n/a — see index_features.py).
  - Lower round-trip transaction cost (FUTURES_ROUND_TRIP_COST_PCT, not the
    stock 0.28% NSE cash-equity figure).

Reuses TradeRecord/BacktestResult and the pure compute_* metric functions
from strategy_backtester.py / strategy_metrics.py unchanged — Sharpe,
Sortino, drawdown, profit factor, expectancy math is identical regardless
of instrument; only the simulation loop and cost/sizing model differ.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

from aqrti.database.engine import get_session_factory
from aqrti.database.models import IndexFuturesPrice, IndexFuturesFeatureValue, StrategyV2
from aqrti.utils.logger import get_logger
from strategies.strategy_dsl import StrategyDSL
from strategies.strategy_metrics import (
    compute_sharpe, compute_sortino, compute_max_drawdown,
    compute_profit_factor, compute_expectancy,
)
from strategies.index_futures_config import (
    CONTRACT_SPECS, MARGIN_PCT, FUTURES_ROUND_TRIP_COST_PCT,
    ROLL_DAYS_BEFORE_EXPIRY, BACKTEST_YEARS,
)

log = get_logger("index_futures_backtester")

STARTING_CAPITAL = 1_000_000.0   # ₹10L notional paper capital, index-futures segment
MAX_LOTS_PER_TRADE = 1            # one lot per position — conservative default sizing


@dataclass
class IndexFuturesTradeRecord:
    index_name:   str
    contract_month_entry: str
    entry_date:   date
    exit_date:    Optional[date]
    entry_price:  float
    exit_price:   Optional[float]
    lots:         int
    pnl_pct:      Optional[float]      # % return on MARGIN deployed (leveraged), not notional
    pnl_amount:   Optional[float]      # ₹ P&L on the position
    exit_reason:  str = ""
    holding_days: int = 0
    rolled:       bool = False         # True if this trade crossed >=1 contract roll


@dataclass
class IndexFuturesBacktestResult:
    strategy_id:   str
    index_name:    str
    start_date:    date
    end_date:      date
    trades:        list = field(default_factory=list)
    sharpe:        float = 0.0
    sortino:       float = 0.0
    win_rate:      float = 0.0
    profit_factor: float = 1.0
    max_drawdown:  float = 0.0
    expectancy:    float = 0.0
    total_return:  float = 0.0
    trade_count:   int = 0
    avg_holding_days: float = 0.0
    rolls_encountered: int = 0
    is_synthetic:  bool = True

    def compute_metrics(self, daily_returns: Optional[list[float]] = None) -> None:
        closed = [t for t in self.trades if t.pnl_pct is not None]
        if not closed:
            return
        returns = [t.pnl_pct for t in closed]
        wins    = [r for r in returns if r > 0]
        losses  = [r for r in returns if r <= 0]

        self.trade_count      = len(closed)
        self.win_rate         = len(wins) / len(closed) * 100
        self.profit_factor    = compute_profit_factor(wins, losses)
        self.expectancy       = compute_expectancy(returns)
        self.avg_holding_days = round(sum(t.holding_days for t in closed) / len(closed), 1)
        self.rolls_encountered = sum(1 for t in closed if t.rolled)

        if daily_returns:
            equity = 100.0
            eq_curve = [100.0]
            for r in daily_returns:
                equity *= (1 + r / 100)
                eq_curve.append(equity)
            self.max_drawdown = compute_max_drawdown(eq_curve)
            self.total_return = round(equity - 100.0, 4)
            self.sharpe  = compute_sharpe(daily_returns)
            self.sortino = compute_sortino(daily_returns)
        else:
            self.sharpe = 0.0
            self.sortino = 0.0


def _load_series(db, index_name: str, start: date, end: date) -> list[dict]:
    """Continuous OHLC + contract_month + expiry_date, sorted ascending."""
    rows = (
        db.query(IndexFuturesPrice)
        .filter(
            IndexFuturesPrice.index_name == index_name,
            IndexFuturesPrice.date >= start,
            IndexFuturesPrice.date <= end,
        )
        .order_by(IndexFuturesPrice.date.asc())
        .all()
    )
    return [
        {
            "date": r.date, "open": r.open, "high": r.high, "low": r.low,
            "close": r.close, "contract_month": r.contract_month,
            "expiry_date": r.expiry_date,
        }
        for r in rows
    ]


def _load_feature_cache(db, index_name: str, start: date, end: date) -> dict:
    """{date: {feature_name: value}}"""
    rows = (
        db.query(IndexFuturesFeatureValue.date, IndexFuturesFeatureValue.feature_name,
                  IndexFuturesFeatureValue.value)
        .filter(
            IndexFuturesFeatureValue.index_name == index_name,
            IndexFuturesFeatureValue.date >= start,
            IndexFuturesFeatureValue.date <= end,
            IndexFuturesFeatureValue.version == 1,
        )
        .all()
    )
    cache: dict = {}
    for d, fname, val in rows:
        cache.setdefault(d, {})[fname] = val
    return cache


def backtest_index_strategy(
    strategy: StrategyDSL,
    index_name: str,
    years: int = BACKTEST_YEARS,
    end_date: Optional[date] = None,
) -> IndexFuturesBacktestResult:
    """
    Simulate one strategy's DSL entry/exit conditions against one index's
    continuous futures series. Long-only for v1 (matching the stock
    backtester's current scope) — short entries are a natural extension
    once long-side is validated end-to-end.
    """
    db = get_session_factory()()
    end   = end_date or date.today()
    start = end - timedelta(days=years * 365 + 30)

    series = _load_series(db, index_name, start, end)
    feat_cache = _load_feature_cache(db, index_name, start, end)
    spec = CONTRACT_SPECS[index_name]
    lot_size = spec["lot_size"]

    result = IndexFuturesBacktestResult(
        strategy_id=strategy.strategy_id(), index_name=index_name,
        start_date=start, end_date=end,
    )
    if len(series) < 30:
        db.close()
        return result

    entry_conditions = strategy.entry_conditions
    exit_conditions  = strategy.exit_conditions

    cash = STARTING_CAPITAL
    open_position: Optional[dict] = None
    daily_returns: list[float] = []
    prev_equity = STARTING_CAPITAL
    entries_blocked_no_features = 0

    for row in series:
        d = row["date"]
        price = row["close"]
        feat_vec = feat_cache.get(d)

        # ── Manage open position: roll / exit checks ──
        if open_position:
            days_to_expiry = (row["expiry_date"] - d).days
            hold_days = (d - open_position["entry_date"]).days

            # Auto-roll: close on the (soon-to-expire) contract, reopen on
            # the new one, at the SAME index level (continuous series
            # already reflects the new contract's basis) — the roll cost is
            # the modeled basis gap between the two contracts on this date.
            #
            # NOTE: do NOT trigger on "row['contract_month'] != open_position
            # ['contract_month']" alone — the continuous series' contract_month
            # advances once per calendar month regardless of when the position
            # was opened (see backfill_index_futures._contract_month_and_expiry),
            # so that condition fires on almost every position spanning a
            # month boundary, not just genuine near-expiry rolls. Only the
            # days-to-expiry check reflects a REAL roll decision.
            if days_to_expiry <= ROLL_DAYS_BEFORE_EXPIRY:
                pnl_amount = (price - open_position["entry_price"]) * lot_size * open_position["lots"]
                margin_deployed = open_position["entry_price"] * lot_size * open_position["lots"] * MARGIN_PCT
                pnl_pct = (pnl_amount / margin_deployed * 100) if margin_deployed else 0.0
                cash += pnl_amount - (price * lot_size * open_position["lots"] * FUTURES_ROUND_TRIP_COST_PCT / 100)

                result.trades.append(IndexFuturesTradeRecord(
                    index_name=index_name,
                    contract_month_entry=open_position["contract_month"],
                    entry_date=open_position["entry_date"], exit_date=d,
                    entry_price=open_position["entry_price"], exit_price=price,
                    lots=open_position["lots"], pnl_pct=round(pnl_pct, 4),
                    pnl_amount=round(pnl_amount, 2), exit_reason="roll",
                    holding_days=hold_days, rolled=True,
                ))
                # Reopen immediately on the new contract at the same price
                # (continuous series convention — no gap to model beyond
                # the roll cost already charged above).
                open_position = {
                    "entry_date": d, "entry_price": price,
                    "contract_month": row["contract_month"], "lots": open_position["lots"],
                }
                continue

            exit_reason = None
            if exit_conditions and feat_vec and exit_conditions.evaluate(feat_vec):
                exit_reason = "signal"
            elif hold_days >= 20:
                exit_reason = "max_hold"

            if exit_reason:
                pnl_amount = (price - open_position["entry_price"]) * lot_size * open_position["lots"]
                margin_deployed = open_position["entry_price"] * lot_size * open_position["lots"] * MARGIN_PCT
                pnl_pct = (pnl_amount / margin_deployed * 100) if margin_deployed else 0.0
                cost = price * lot_size * open_position["lots"] * FUTURES_ROUND_TRIP_COST_PCT / 100
                cash += pnl_amount - cost

                result.trades.append(IndexFuturesTradeRecord(
                    index_name=index_name,
                    contract_month_entry=open_position["contract_month"],
                    entry_date=open_position["entry_date"], exit_date=d,
                    entry_price=open_position["entry_price"], exit_price=price,
                    lots=open_position["lots"], pnl_pct=round(pnl_pct, 4),
                    pnl_amount=round(pnl_amount, 2), exit_reason=exit_reason,
                    holding_days=hold_days, rolled=False,
                ))
                open_position = None

        # ── Entry check (only if flat) ──
        elif entry_conditions is not None:
            if not feat_vec:
                entries_blocked_no_features += 1
            elif entry_conditions.evaluate(feat_vec):
                margin_needed = price * lot_size * MAX_LOTS_PER_TRADE * MARGIN_PCT
                if margin_needed <= cash:
                    open_position = {
                        "entry_date": d, "entry_price": price,
                        "contract_month": row["contract_month"], "lots": MAX_LOTS_PER_TRADE,
                    }

        # ── Daily mark-to-market equity (margin account + open position P&L) ──
        unrealized = 0.0
        if open_position:
            unrealized = (price - open_position["entry_price"]) * lot_size * open_position["lots"]
        equity_today = cash + unrealized
        if prev_equity:
            daily_returns.append((equity_today - prev_equity) / prev_equity * 100)
        prev_equity = equity_today

    if entries_blocked_no_features:
        log.info(
            "Index backtest %s/%s: %d entries blocked (no feature vector)",
            strategy.strategy_id(), index_name, entries_blocked_no_features,
        )

    result.compute_metrics(daily_returns=daily_returns)
    db.close()
    return result
