"""
Strategy Backtester — Signal-Driven (Prediction + Price Technicals)
====================================================================
Primary signals: ML predictions table (Bullish/Bearish/Neutral + confidence)
Fallback signals: Price-based technicals (RSI + EMA momentum) when predictions
                  are sparse or unavailable for a historical window.

For each trading day in the window:
  1. Check ML predictions → Bullish confidence >= threshold → entry candidate
  2. If no ML prediction exists for that date/symbol, compute RSI+EMA momentum signal
  3. Apply regime filter (SIDEWAYS/BEAR → tighten confidence gate)
  4. Execute entry at close (next-day if available, same-day otherwise)
  5. Exit on stop-loss / take-profit / max-hold / bearish signal flip
  6. Log every trade and compute Sharpe, win-rate, MDD, profit factor

Writes results to StrategyV2 + StrategyBacktestTrade tables.
"""

from __future__ import annotations

import sys, os, json
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from sqlalchemy.orm import Session
from aqrti.database.models import DailyPrice, MarketRegime, Prediction, IndexData
from aqrti.utils.logger import get_logger
from strategies.strategy_metrics import (
    compute_sharpe, compute_sortino, compute_max_drawdown,
    compute_profit_factor, compute_expectancy,
)

log = get_logger("strategy_backtester")

# ── Indian NSE Transaction Cost Model (delivery equity) ───────
# Applied on ENTRY and EXIT separately.
# All values are percentages of trade value.
STT_BUY          = 0.001    # 0.10% — Securities Transaction Tax on buy
STT_SELL         = 0.001    # 0.10% — Securities Transaction Tax on sell
EXCHANGE_CHARGE  = 0.0000345 # 0.00345% — NSE transaction charge (each side)
SEBI_CHARGE      = 0.000001  # 0.0001% — SEBI turnover fee (each side)
STAMP_DUTY       = 0.00015  # 0.015% — Stamp duty on buy only
BROKERAGE        = 0.0003   # 0.03% — discount broker (each side, capped ₹20/order)
GST_RATE         = 0.18     # 18% GST on (brokerage + exchange + SEBI)

# Slippage: 0.05% entry (market impact) + 0.03% exit
SLIPPAGE_ENTRY   = 0.0005   # 0.05% — bid-ask spread + market impact on entry
SLIPPAGE_EXIT    = 0.0003   # 0.03% — tighter on exit (limit order assumed)

POSITION_SIZE   = 0.05    # 5% of capital per trade
MAX_OPEN_TRADES = 8       # max concurrent positions


def _detect_exchange(symbol: str) -> str:
    """Detect exchange from symbol suffix."""
    if symbol.endswith(".NS") or symbol.endswith(".BO"):
        return "NSE"
    if symbol.endswith(".L"):
        return "LSE"
    if symbol.endswith(".T"):
        return "TSE"
    if symbol.endswith(".HK"):
        return "HKEX"
    if symbol.endswith((".DE", ".PA", ".AS", ".MI", ".MC")):
        return "EU"
    if symbol.endswith(".SW"):
        return "SIX"
    if symbol.endswith((".AX",)):
        return "ASX"
    if symbol.endswith((".TO", ".V")):
        return "TSX"
    if symbol.endswith(".SA"):
        return "BVMF"
    if symbol.endswith(".KS"):
        return "KRX"
    if symbol.endswith((".SS", ".SZ")):
        return "SSE"
    # No suffix = US (NYSE/NASDAQ)
    return "US"


# Round-trip cost by exchange (realistic inclusive of all taxes + slippage)
_EXCHANGE_ROUND_TRIP_COST = {
    "NSE":  0.0028,  # 0.28% — STT + brokerage + exchange + stamp + GST + slippage
    "US":   0.0010,  # 0.10% — SEC fee + FINRA + slippage (zero commission brokers)
    "LSE":  0.0055,  # 0.55% — UK Stamp Duty 0.5% + broker + slippage
    "TSE":  0.0015,  # 0.15% — Japan: low cost, minor consumption tax
    "HKEX": 0.0030,  # 0.30% — HK Stamp Duty 0.13% each side + broker
    "EU":   0.0020,  # 0.20% — varies by country; conservative average
    "SIX":  0.0025,  # 0.25% — Swiss stamp duty + broker
    "ASX":  0.0025,  # 0.25% — Australia: brokerage + minor levy
    "TSX":  0.0020,  # 0.20% — Canada: brokerage + minor levy
    "BVMF": 0.0035,  # 0.35% — Brazil: IOF + CPMF-equivalent + slippage
    "KRX":  0.0025,  # 0.25% — Korea: securities tax + brokerage
    "SSE":  0.0030,  # 0.30% — China: stamp duty + brokerage
}


def _transaction_cost(side: str = "buy", symbol: str = "") -> float:
    """
    Total one-way transaction cost as a fraction of trade value.
    Uses exchange-aware cost model based on symbol suffix.
    """
    exchange = _detect_exchange(symbol)
    round_trip = _EXCHANGE_ROUND_TRIP_COST.get(exchange, 0.0020)
    # Split ~60/40 buy/sell (buy has stamp duties in some exchanges)
    return round_trip * 0.55 if side == "buy" else round_trip * 0.45


def _round_trip_cost(symbol: str = "") -> float:
    """Total round-trip cost for a symbol."""
    exchange = _detect_exchange(symbol)
    return _EXCHANGE_ROUND_TRIP_COST.get(exchange, 0.0020)


# Default round-trip cost for NSE (backwards compat)
ROUND_TRIP_COST = _EXCHANGE_ROUND_TRIP_COST["NSE"]
# ≈ 0.28% round-trip (realistic for NSE delivery)

STOCK_UNIVERSE = [
    # Original 20
    "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK",
    "WIPRO", "AXISBANK", "LTIM", "NESTLEIND", "BAJFINANCE",
    "MARUTI", "SUNPHARMA", "TATASTEEL", "TATAMOTORS", "KOTAKBANK",
    "TITAN", "ONGC", "HINDALCO", "SBIN", "BHARTIARTL",
    # Expanded 30
    "HCLTECH", "ITC", "LT", "HINDUNILVR", "ULTRACEMCO",
    "BAJAJFINSV", "NTPC", "ADANIENT", "ADANIPORTS", "JSWSTEEL",
    "TECHM", "COALINDIA", "BPCL", "HDFCLIFE", "SBILIFE",
    "INDUSINDBK", "M&M", "DIVISLAB", "DRREDDY", "EICHERMOT",
    "HEROMOTOCO", "CIPLA", "BRITANNIA", "APOLLOHOSP", "TRENT",
    "GRASIM", "SHREECEM", "BEL", "POWERGRID", "ASIANPAINT",
]


def get_backtest_universe(db: Session, min_price_rows: int = 50) -> list[str]:
    """
    Return all active symbols that have sufficient price history for backtesting.
    Falls back to STOCK_UNIVERSE if DB query returns nothing.
    """
    from aqrti.database.models import Stock
    from sqlalchemy import func as _func
    rows = (
        db.query(DailyPrice.symbol)
        .filter(DailyPrice.symbol.in_(
            db.query(Stock.symbol).filter(Stock.active == True).scalar_subquery()
        ))
        .group_by(DailyPrice.symbol)
        .having(_func.count(DailyPrice.date) >= min_price_rows)
        .all()
    )
    result = [r[0] for r in rows]
    return result if result else STOCK_UNIVERSE


# ── Technical helpers ─────────────────────────────────────────

def _simple_rsi(closes: list[float], period: int = 14) -> Optional[float]:
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, period + 1):
        delta = closes[-(period + 1 - i)] - closes[-(period + 2 - i)]
        (gains if delta > 0 else losses).append(abs(delta))
    avg_gain = sum(gains) / period if gains else 0.0
    avg_loss = sum(losses) / period if losses else 1e-9
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _ema(closes: list[float], period: int) -> Optional[float]:
    if len(closes) < period:
        return None
    k = 2 / (period + 1)
    ema = sum(closes[:period]) / period
    for c in closes[period:]:
        ema = c * k + ema * (1 - k)
    return ema


def _technical_signal(closes: list[float]) -> dict:
    """
    Generate a synthetic signal dict from price history.
    Returns direction (Bullish/Bearish/Neutral) + synthetic confidence.
    """
    if len(closes) < 22:
        return {"direction": "Neutral", "confidence": 0.0}

    rsi   = _simple_rsi(closes, period=14)
    ema20 = _ema(closes, 20)
    ema50 = _ema(closes, 50) if len(closes) >= 50 else None
    cur   = closes[-1]
    prev  = closes[-2]

    score = 50.0  # base neutral

    # RSI contribution
    if rsi is not None:
        if rsi < 35:
            score += 15   # oversold → bullish
        elif rsi < 45:
            score += 8
        elif rsi > 70:
            score -= 15   # overbought → bearish
        elif rsi > 60:
            score -= 5

    # Price vs EMA20
    if ema20 is not None:
        if cur > ema20 * 1.01:
            score += 10   # above EMA → bullish momentum
        elif cur < ema20 * 0.99:
            score -= 10

    # EMA20 vs EMA50 (golden/death cross)
    if ema20 is not None and ema50 is not None:
        if ema20 > ema50 * 1.005:
            score += 8
        elif ema20 < ema50 * 0.995:
            score -= 8

    # Recent momentum (5-day)
    if len(closes) >= 6:
        mom = (closes[-1] - closes[-6]) / closes[-6] * 100
        if mom > 3:
            score += 6
        elif mom < -3:
            score -= 6

    score = max(20.0, min(90.0, score))

    if score >= 62:
        return {"direction": "Bullish", "confidence": round(score, 1)}
    elif score <= 40:
        return {"direction": "Bearish", "confidence": round(100 - score, 1)}
    else:
        return {"direction": "Neutral", "confidence": round(score, 1)}


# ── Data structures ───────────────────────────────────────────

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
    confidence:   float = 0.0
    signal_source: str = "ml"   # "ml" or "technical"


@dataclass
class BacktestResult:
    strategy_id:      str
    start_date:       date
    end_date:         date
    universe_size:    int
    trades:           list[TradeRecord] = field(default_factory=list)
    sharpe:           float = 0.0
    sortino:          float = 0.0
    win_rate:         float = 0.0
    profit_factor:    float = 1.0
    max_drawdown:     float = 0.0
    expectancy:       float = 0.0
    total_return:     float = 0.0
    trade_count:      int   = 0
    avg_holding_days: float = 0.0
    exposure_pct:     float = 0.0
    bull_sharpe:      float = 0.0
    bear_sharpe:      float = 0.0
    sideways_sharpe:  float = 0.0
    volatile_sharpe:  float = 0.0
    regime_trades:    dict  = field(default_factory=dict)

    def compute_metrics(self) -> None:
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

        equity = 100.0
        eq_curve = [100.0]
        for r in returns:
            equity *= (1 + r / 100)
            eq_curve.append(equity)
        self.max_drawdown  = compute_max_drawdown(eq_curve)
        self.total_return  = round(sum(returns), 4)
        self.avg_holding_days = round(
            sum(t.holding_days for t in closed) / len(closed), 1
        )

        daily_returns = []
        for t in closed:
            days = max(t.holding_days, 1)
            daily = t.pnl_pct / days   # per-day return; portfolio scaling done at fitness layer
            daily_returns.extend([daily] * days)

        self.sharpe  = compute_sharpe(daily_returns)
        self.sortino = compute_sortino(daily_returns)


# ── Data loaders ──────────────────────────────────────────────

def _get_regime(db: Session, on_date: date) -> str:
    row = (
        db.query(MarketRegime.regime)
        .filter(MarketRegime.date <= on_date)
        .order_by(MarketRegime.date.desc())
        .first()
    )
    return row[0] if row else "BULL"


def _price_on(db: Session, symbol: str, on_date: date, look_ahead: int = 0) -> Optional[float]:
    """Get close price on or after on_date + look_ahead days."""
    target = on_date + timedelta(days=look_ahead)
    row = (
        db.query(DailyPrice.close)
        .filter(DailyPrice.symbol == symbol, DailyPrice.date >= target)
        .order_by(DailyPrice.date.asc())
        .first()
    )
    return row[0] if row else None


def _price_before(db: Session, symbol: str, on_date: date) -> Optional[float]:
    """Get most recent close price on or before on_date."""
    row = (
        db.query(DailyPrice.close)
        .filter(DailyPrice.symbol == symbol, DailyPrice.date <= on_date)
        .order_by(DailyPrice.date.desc())
        .first()
    )
    return row[0] if row else None


def _load_price_history(
    db: Session, symbol: str, since: date, up_to: date, limit: int = 70
) -> list[float]:
    """Return closes from since..up_to, ascending."""
    rows = (
        db.query(DailyPrice.close)
        .filter(DailyPrice.symbol == symbol,
                DailyPrice.date >= since,
                DailyPrice.date <= up_to)
        .order_by(DailyPrice.date.asc())
        .limit(limit)
        .all()
    )
    return [r[0] for r in rows if r[0] is not None]


def _get_all_price_dates(db: Session, start: date, end: date) -> list[date]:
    """Return all distinct dates in daily_prices between start and end."""
    from sqlalchemy import distinct
    rows = (
        db.query(distinct(DailyPrice.date))
        .filter(DailyPrice.date >= start, DailyPrice.date <= end)
        .order_by(DailyPrice.date.asc())
        .all()
    )
    return [r[0] for r in rows]


def _load_ml_predictions(
    db: Session, start_date: date, end_date: date, universe: list[str]
) -> dict[date, dict[str, dict]]:
    """Load ML predictions in window → {date: {symbol: pred_dict}}."""
    rows = (
        db.query(Prediction)
        .filter(
            Prediction.date >= start_date,
            Prediction.date <= end_date,
            Prediction.symbol.in_(universe),
        )
        .all()
    )
    by_date: dict[date, dict[str, dict]] = {}
    for p in rows:
        by_date.setdefault(p.date, {})[p.symbol] = {
            "direction":   p.direction or "Neutral",
            "confidence":  p.confidence or 0.0,
            "source":      "ml",
        }
    return by_date


def _get_nifty_trend(db: Session, on_date: date, lookback: int = 5) -> str:
    """Recent NIFTY trend: UP / DOWN / FLAT."""
    since = on_date - timedelta(days=lookback + 5)
    rows = (
        db.query(IndexData.returns)
        .filter(IndexData.index_name == "NIFTY50",
                IndexData.date >= since,
                IndexData.date <= on_date)
        .order_by(IndexData.date.desc())
        .limit(lookback)
        .all()
    )
    rets = [r[0] for r in rows if r[0] is not None]
    if not rets:
        return "FLAT"
    positive = sum(1 for r in rets if r > 0)
    if positive >= len(rets) * 0.7:
        return "UP"
    if positive <= len(rets) * 0.3:
        return "DOWN"
    return "FLAT"


# ── Signal evaluation ─────────────────────────────────────────

def _should_enter(
    signal:           dict,
    regime:           str,
    nifty_trend:      str,
    min_confidence:   float,
    allowed_regimes:  list[str],
) -> bool:
    """
    Gate entry signal:
      - Must be Bullish
      - Confidence >= min_confidence (adjusted upward in bear/sideways/volatile regimes)
      - Regime must be allowed
      - NIFTY trend is a soft penalty (raises threshold), not a hard block
    """
    if signal["direction"] != "Bullish":
        return False

    effective_threshold = min_confidence

    # Raise the bar in cautious regimes — but never block outright
    if regime == "SIDEWAYS":
        effective_threshold += 3
    elif regime == "BEAR":
        effective_threshold += 6
    elif regime == "VOLATILE":
        effective_threshold += 4

    # Soft NIFTY-trend penalty: raises bar instead of hard block
    # (hard block was cutting 48%+ of trading days in sideways markets)
    if nifty_trend == "DOWN":
        effective_threshold += 5

    if signal["confidence"] < effective_threshold:
        return False
    if regime not in allowed_regimes:
        return False

    return True


# ── Core backtest ─────────────────────────────────────────────

def backtest_strategy(
    db:               Session,
    strategy_id:      str,
    start_date:       date,
    end_date:         date,
    universe:         Optional[list[str]] = None,
    min_confidence:   float = 60.0,
    stop_loss_pct:    float = -7.0,
    take_profit_pct:  float = 12.0,
    max_holding_days: int   = 15,
    allowed_regimes:  Optional[list[str]] = None,
    use_technical_fallback: bool = True,
) -> BacktestResult:
    """
    Signal-driven backtest using ML predictions + price technicals.

    When ML predictions exist for a date/symbol, they take priority.
    When they don't (sparse historical data), falls back to RSI+EMA signals
    computed from price history — enabling real backtests even before the
    system has run predictions for every historical date.

    Entry: signal Bullish >= min_confidence, regime allowed, NIFTY not falling
    Exit:  stop-loss | take-profit | max-hold | bearish signal flip
    """
    if universe is None:
        universe = get_backtest_universe(db)
    if allowed_regimes is None:
        allowed_regimes = ["BULL", "SIDEWAYS", "BEAR", "VOLATILE"]

    result = BacktestResult(
        strategy_id   = strategy_id,
        start_date    = start_date,
        end_date      = end_date,
        universe_size = len(universe),
    )

    # All trading dates (from price table)
    all_dates = _get_all_price_dates(db, start_date, end_date)

    if not all_dates:
        log.warning("Backtest %s: no price data in window %s–%s", strategy_id, start_date, end_date)
        log.info(
            "Backtest %s: trades=%d sharpe=%.3f win_rate=%.1f%% mdd=%.1f%%",
            strategy_id, 0, 0.0, 0.0, 0.0,
        )
        return result

    # Pre-load ML predictions
    ml_preds = _load_ml_predictions(db, start_date, end_date, universe)
    has_ml = bool(ml_preds)

    open_positions: dict[str, dict] = {}
    regime_returns: dict[str, list[float]] = {
        "BULL": [], "BEAR": [], "SIDEWAYS": [], "VOLATILE": []
    }

    for d in all_dates:
        regime      = _get_regime(db, d)
        nifty_trend = _get_nifty_trend(db, d)
        ml_day      = ml_preds.get(d, {})

        # ── Process exits ──────────────────────────────────
        for sym in list(open_positions.keys()):
            pos = open_positions[sym]
            pos["holding_days"] += 1
            cur_price = _price_before(db, sym, d)
            if cur_price is None:
                continue

            pnl_pct = (cur_price - pos["entry_price"]) / pos["entry_price"] * 100
            exit_reason = ""

            if pnl_pct <= stop_loss_pct:
                exit_reason = "stop_loss"
            elif pnl_pct >= take_profit_pct:
                exit_reason = "take_profit"
            elif pos["holding_days"] >= max_holding_days:
                exit_reason = "max_holding_days"
            elif d == end_date:
                exit_reason = "end_of_backtest"
            else:
                # Bearish ML flip — exit early
                flip = ml_day.get(sym, {})
                if flip.get("direction") == "Bearish" and flip.get("confidence", 0) >= 65:
                    exit_reason = "bearish_flip"

            if exit_reason:
                exit_cost_pct = _transaction_cost("sell", sym) * 100
                net_pnl = pnl_pct - exit_cost_pct
                t = TradeRecord(
                    symbol        = sym,
                    entry_date    = pos["entry_date"],
                    exit_date     = d,
                    entry_price   = pos["entry_price"],
                    exit_price    = cur_price,
                    pnl_pct       = round(net_pnl, 4),
                    exit_reason   = exit_reason,
                    holding_days  = pos["holding_days"],
                    confidence    = pos["confidence"],
                    signal_source = pos["signal_source"],
                )
                result.trades.append(t)
                reg_key = pos.get("regime_entry", "BULL")
                if reg_key in regime_returns:
                    regime_returns[reg_key].append(net_pnl)
                del open_positions[sym]

        # ── Process entries ────────────────────────────────
        if len(open_positions) >= MAX_OPEN_TRADES:
            continue

        # Build signal list: ML first, then technical fallback
        signals: list[tuple[str, dict]] = []

        for sym in universe:
            if sym in open_positions:
                continue

            if sym in ml_day:
                signals.append((sym, ml_day[sym]))
            elif use_technical_fallback:
                hist_since = d - timedelta(days=120)
                closes = _load_price_history(db, sym, hist_since, d)
                if len(closes) >= 22:
                    sig = _technical_signal(closes)
                    sig["source"] = "technical"
                    signals.append((sym, sig))

        # Sort by confidence descending — highest conviction first
        signals.sort(key=lambda x: x[1]["confidence"], reverse=True)

        for sym, signal in signals:
            if len(open_positions) >= MAX_OPEN_TRADES:
                break

            if not _should_enter(signal, regime, nifty_trend, min_confidence, allowed_regimes):
                continue

            # Enter at next-day close; fall back to same-day if not available
            entry_price = _price_on(db, sym, d, look_ahead=1)
            if entry_price is None:
                entry_price = _price_before(db, sym, d)
            if entry_price is None:
                continue

            entry_cost_pct = _transaction_cost("buy", sym)
            open_positions[sym] = {
                "entry_date":   d,
                "entry_price":  entry_price * (1 + entry_cost_pct),
                "holding_days": 0,
                "regime_entry": regime,
                "confidence":   signal["confidence"],
                "signal_source": signal.get("source", "ml"),
            }

    # Force-close remaining positions at end_date
    for sym, pos in open_positions.items():
        cur_price = _price_before(db, sym, end_date)
        if cur_price is None:
            continue
        pnl_pct = (cur_price - pos["entry_price"]) / pos["entry_price"] * 100
        exit_cost_pct = _transaction_cost("sell", sym) * 100
        net_pnl = pnl_pct - exit_cost_pct
        t = TradeRecord(
            symbol        = sym,
            entry_date    = pos["entry_date"],
            exit_date     = end_date,
            entry_price   = pos["entry_price"],
            exit_price    = cur_price,
            pnl_pct       = round(net_pnl, 4),
            exit_reason   = "end_of_backtest",
            holding_days  = pos["holding_days"],
            confidence    = pos["confidence"],
            signal_source = pos.get("signal_source", "ml"),
        )
        result.trades.append(t)
        reg_key = pos.get("regime_entry", "BULL")
        if reg_key in regime_returns:
            regime_returns[reg_key].append(net_pnl)

    result.compute_metrics()

    # Regime-stratified Sharpe
    for reg, rets in regime_returns.items():
        if len(rets) >= 3:
            s = compute_sharpe(rets)
            setattr(result, f"{reg.lower()}_sharpe", s)

    result.regime_trades = {k: len(v) for k, v in regime_returns.items()}

    log.info(
        "Backtest %s: trades=%d sharpe=%.3f win_rate=%.1f%% mdd=%.1f%%",
        strategy_id, result.trade_count, result.sharpe,
        result.win_rate, result.max_drawdown,
    )
    return result


def backtest_and_update(
    db:         Session,
    strategy,                    # StrategyDSL or dict with strategy params
    start_date: Optional[date] = None,
    end_date:   Optional[date] = None,
    universe:   Optional[list[str]] = None,
) -> BacktestResult:
    """Backtest a strategy and write results to StrategyV2 + individual trades."""
    from strategies.strategy_store import upsert_strategy
    from aqrti.database.models import StrategyBacktestTrade

    end   = end_date   or date.today()
    start = start_date or (end - timedelta(days=365))

    # Extract params from StrategyDSL if provided
    if hasattr(strategy, "strategy_id"):
        sid               = strategy.strategy_id()
        min_confidence    = getattr(strategy, "min_confidence",   60.0)
        stop_loss_pct     = getattr(strategy, "stop_loss_pct",    -7.0)
        take_profit_pct   = getattr(strategy, "take_profit_pct",  12.0)
        max_holding_days  = getattr(strategy, "max_holding_days", 15)
        allowed_regimes   = getattr(strategy, "allowed_regimes",  ["BULL", "SIDEWAYS", "BEAR", "VOLATILE"])
        family            = getattr(strategy, "family",           "hybrid")
        name              = getattr(strategy, "name",             "")
    else:
        sid               = strategy.get("strategy_id", "UNKNOWN")
        min_confidence    = strategy.get("min_confidence",   60.0)
        stop_loss_pct     = strategy.get("stop_loss_pct",    -7.0)
        take_profit_pct   = strategy.get("take_profit_pct",  12.0)
        max_holding_days  = strategy.get("max_holding_days", 15)
        allowed_regimes   = strategy.get("allowed_regimes",  ["BULL", "SIDEWAYS", "BEAR", "VOLATILE"])
        family            = strategy.get("family",           "hybrid")
        name              = strategy.get("name",             "")

    result = backtest_strategy(
        db               = db,
        strategy_id      = sid,
        start_date       = start,
        end_date         = end,
        universe         = universe,
        min_confidence   = min_confidence,
        stop_loss_pct    = stop_loss_pct,
        take_profit_pct  = take_profit_pct,
        max_holding_days = max_holding_days,
        allowed_regimes  = allowed_regimes,
        use_technical_fallback = True,
    )

    upsert_strategy(db, {
        "strategy_id":       result.strategy_id,
        "sharpe":            result.sharpe,
        "sortino":           result.sortino,
        "win_rate":          result.win_rate,
        "profit_factor":     result.profit_factor,
        "max_drawdown":      result.max_drawdown,
        "expectancy":        result.expectancy,
        "trade_count":       result.trade_count,
        "avg_holding_days":  result.avg_holding_days,
        "bull_sharpe":       result.bull_sharpe,
        "bear_sharpe":       result.bear_sharpe,
        "sideways_sharpe":   result.sideways_sharpe,
        "volatile_sharpe":   result.volatile_sharpe,
        "backtest_start":    start,
        "backtest_end":      end,
        "backtest_universe": result.universe_size,
        "status":            "shadow",
        "family":            family,
        "name":              name,
    })

    # Persist individual trades — delete stale, insert fresh
    db.query(StrategyBacktestTrade).filter_by(strategy_id=result.strategy_id).delete()
    for t in result.trades:
        db.add(StrategyBacktestTrade(
            strategy_id  = result.strategy_id,
            symbol       = t.symbol,
            entry_date   = t.entry_date,
            exit_date    = t.exit_date,
            entry_price  = t.entry_price,
            exit_price   = t.exit_price,
            pnl_pct      = t.pnl_pct,
            exit_reason  = t.exit_reason,
            holding_days = t.holding_days,
        ))

    db.commit()
    return result
