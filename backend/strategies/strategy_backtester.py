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


# Symbols in the DB are stored WITHOUT the yfinance suffix (e.g. "RELIANCE",
# not "RELIANCE.NS"), so suffix detection alone maps every Indian stock to US
# costs (0.10% instead of 0.28% — a serious backtest inflation). Build a set
# of known Indian symbols from the universe definitions for correct lookup.
_INDIA_SYMBOLS: Optional[set] = None


def _india_symbol_set() -> set:
    global _INDIA_SYMBOLS
    if _INDIA_SYMBOLS is None:
        syms: set[str] = set()
        try:
            from aqrti.data.global_universe import GLOBAL_UNIVERSE
            for t, meta in GLOBAL_UNIVERSE.items():
                if t.endswith((".NS", ".BO")) or meta.get("region") == "India":
                    syms.add(t.rsplit(".", 1)[0] if "." in t else t)
        except Exception:
            pass
        try:
            from aqrti.data.market_data import STOCK_META
            syms.update(STOCK_META.keys())
        except Exception:
            pass
        _INDIA_SYMBOLS = syms
    return _INDIA_SYMBOLS


def _detect_exchange(symbol: str) -> str:
    """Detect exchange: known-Indian-symbol lookup first, then suffix."""
    if symbol.rsplit(".", 1)[0] in _india_symbol_set():
        return "NSE"
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
    "WIPRO", "AXISBANK", "NESTLEIND", "BAJFINANCE",
    "MARUTI", "SUNPHARMA", "TATASTEEL", "KOTAKBANK",
    "TITAN", "ONGC", "HINDALCO", "SBIN", "BHARTIARTL",
    # Expanded 30
    "HCLTECH", "ITC", "LT", "HINDUNILVR", "ULTRACEMCO",
    "BAJAJFINSV", "NTPC", "ADANIENT", "ADANIPORTS", "JSWSTEEL",
    "TECHM", "COALINDIA", "BPCL", "HDFCLIFE", "SBILIFE",
    "INDUSINDBK", "M&M", "DIVISLAB", "DRREDDY", "EICHERMOT",
    "HEROMOTOCO", "CIPLA", "BRITANNIA", "APOLLOHOSP", "TRENT",
    "GRASIM", "SHREECEM", "BEL", "POWERGRID", "ASIANPAINT",
]


# Minimum average daily traded value for a symbol to be backtestable/tradeable.
# 5 crore INR (~50M). Illiquid names produce fills a real order could never get
# (your order IS the volume) and are the worst survivorship-bias offenders.
MIN_AVG_TURNOVER = 5e7


def get_backtest_universe(db: Session, min_price_rows: int = 50,
                          min_avg_turnover: float = MIN_AVG_TURNOVER) -> list[str]:
    """
    Return all active symbols with sufficient price history AND liquidity
    (average close×volume over the stored window >= min_avg_turnover).
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
        .having(_func.avg(DailyPrice.close * DailyPrice.volume) >= min_avg_turnover)
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
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
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
    if len(closes) >= 6 and closes[-6] != 0:
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

    def compute_metrics(self, daily_returns: Optional[list[float]] = None) -> None:
        """
        Compute trade-level stats and portfolio-level risk metrics.

        `daily_returns` must be a REAL mark-to-market daily portfolio return
        series (percent units) from build_daily_portfolio_returns(). The old
        approach of repeating each trade's per-day average `holding_days`
        times collapsed intra-trade variance and inflated Sharpe — never
        reintroduce it.
        """
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
        self.avg_holding_days = round(
            sum(t.holding_days for t in closed) / len(closed), 1
        )

        if daily_returns:
            # Portfolio-level equity from the daily mark-to-market series
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
            # No daily series available: report position-sized trade-chain
            # equity, and leave sharpe/sortino at 0 rather than fabricate.
            equity = 100.0
            eq_curve = [100.0]
            for r in returns:
                equity *= (1 + (r / 100) * POSITION_SIZE)
                eq_curve.append(equity)
            self.max_drawdown = compute_max_drawdown(eq_curve)
            self.total_return = round(equity - 100.0, 4)
            self.sharpe  = 0.0
            self.sortino = 0.0


def build_daily_portfolio_returns(
    trades:              list,
    closes_by_sym:       dict,
    sorted_dates_by_sym: dict,
    position_size:       float = POSITION_SIZE,
) -> tuple[list[float], float]:
    """
    Build a REAL mark-to-market daily portfolio return series (percent units).

    For each closed trade, construct its per-day price path:
      entry_price (cost-loaded) → daily closes → final value implied by the
      recorded net pnl_pct (so per-trade daily returns compound EXACTLY to
      the trade's net-of-cost result).
    Portfolio daily return = position_size × Σ(open-trade daily returns);
    uninvested capital earns 0. Days between the first entry and last exit
    with no open positions contribute 0.0 (honest exposure accounting).

    Returns (daily_returns_pct, exposure_pct).
    """
    import bisect as _bisect

    closed = [t for t in trades if t.pnl_pct is not None and t.exit_date is not None]
    if not closed:
        return [], 0.0

    # Per-trade daily return contributions keyed by mark date
    contrib: dict[date, float] = {}
    active_days: set[date] = set()

    for t in closed:
        sym_dates = sorted_dates_by_sym.get(t.symbol, [])
        if not sym_dates:
            continue
        # Mark dates: trading days strictly after signal date, up to exit date.
        # The first mark day is the fill day (entry at that day's close).
        lo = _bisect.bisect_right(sym_dates, t.entry_date)
        hi = _bisect.bisect_right(sym_dates, t.exit_date)
        mark_dates = sym_dates[lo:hi]
        if not mark_dates:
            mark_dates = [t.exit_date]

        sym_closes = closes_by_sym.get(t.symbol, {})
        final_value = t.entry_price * (1 + t.pnl_pct / 100)

        prev = t.entry_price
        for i, md in enumerate(mark_dates):
            if i == len(mark_dates) - 1:
                price = final_value          # exit fill, net of all costs
            else:
                price = sym_closes.get(md, prev)
            if prev > 0:
                r = (price - prev) / prev * 100
                contrib[md] = contrib.get(md, 0.0) + r
                active_days.add(md)
            prev = price

    if not contrib:
        return [], 0.0

    first_day = min(active_days)
    last_day  = max(active_days)

    # Use the union of all symbols' trading dates in [first_day, last_day]
    all_days: set[date] = set()
    for sym_dates in sorted_dates_by_sym.values():
        lo = _bisect.bisect_left(sym_dates, first_day)
        hi = _bisect.bisect_right(sym_dates, last_day)
        all_days.update(sym_dates[lo:hi])

    series = []
    for dd in sorted(all_days):
        series.append(position_size * contrib.get(dd, 0.0))

    exposure = round(len(active_days) / max(len(all_days), 1) * 100, 2)
    return series, exposure


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


def _preload_prices(
    db: Session, universe: list[str], start: date, end: date
) -> tuple[dict, dict, dict]:
    """
    Bulk-load all prices for universe in one query.
    Returns:
      closes_by_sym:  {symbol: {date: close}}
      sorted_dates_by_sym: {symbol: [date, ...]} sorted asc
      hilo_by_sym:    {symbol: {date: (open, high, low)}} — intrabar SL/TP checks
    """
    rows = (
        db.query(DailyPrice.symbol, DailyPrice.date, DailyPrice.close,
                 DailyPrice.open, DailyPrice.high, DailyPrice.low)
        .filter(
            DailyPrice.symbol.in_(universe),
            DailyPrice.date >= start - timedelta(days=180),  # extra history for technicals
            DailyPrice.date <= end + timedelta(days=3),       # extra days for next-day entry
            DailyPrice.close.isnot(None),
        )
        .order_by(DailyPrice.symbol, DailyPrice.date.asc())
        .all()
    )
    closes_by_sym: dict[str, dict[date, float]] = {}
    hilo_by_sym:   dict[str, dict[date, tuple]] = {}
    for sym, dt, close, open_, high, low in rows:
        closes_by_sym.setdefault(sym, {})[dt] = close
        if high is not None and low is not None:
            hilo_by_sym.setdefault(sym, {})[dt] = (open_, high, low)

    sorted_dates_by_sym: dict[str, list[date]] = {
        sym: sorted(d.keys()) for sym, d in closes_by_sym.items()
    }
    return closes_by_sym, sorted_dates_by_sym, hilo_by_sym


def _price_on_cached(closes_by_sym: dict, sorted_dates: dict, symbol: str, on_date: date, look_ahead: int = 0) -> Optional[float]:
    """Get close on or after on_date + look_ahead days from cache using bisect."""
    import bisect
    target = on_date + timedelta(days=look_ahead)
    dates = sorted_dates.get(symbol, [])
    if not dates:
        return None
    idx = bisect.bisect_left(dates, target)
    if idx < len(dates):
        return closes_by_sym[symbol][dates[idx]]
    return None


def _price_before_cached(closes_by_sym: dict, sorted_dates: dict, symbol: str, on_date: date) -> Optional[float]:
    """Get most recent close on or before on_date from cache using bisect."""
    import bisect
    dates = sorted_dates.get(symbol, [])
    if not dates:
        return None
    idx = bisect.bisect_right(dates, on_date) - 1
    if idx >= 0:
        return closes_by_sym[symbol][dates[idx]]
    return None


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
        effective_threshold += 2
    elif regime == "BEAR":
        effective_threshold += 4
    elif regime == "VOLATILE":
        effective_threshold += 3

    # Soft NIFTY-trend penalty: raises bar instead of hard block
    if nifty_trend == "DOWN":
        effective_threshold += 3

    # Hard cap: technical signals score 62–90; prevent threshold from
    # choking off all entries when min_confidence is already high
    effective_threshold = min(effective_threshold, 72.0)

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
    min_confidence:   float = 50.0,
    stop_loss_pct:    float = -7.0,
    take_profit_pct:  float = 12.0,
    max_holding_days: int   = 20,
    allowed_regimes:  Optional[list[str]] = None,
    use_technical_fallback: bool = True,
    entry_conditions: Optional[object] = None,   # ConditionGroup from StrategyDSL
    exit_conditions:  Optional[object] = None,   # ConditionGroup from StrategyDSL
    use_ml_predictions: bool = False,
    shared_feature_cache: Optional[dict] = None,  # pre-built {(sym,date): {fname: val}} for batch runs
    shared_price_data: Optional[tuple] = None,    # pre-built (closes_by_sym, sorted_dates_by_sym, hilo_by_sym)
    shared_signal_cache: Optional[dict] = None,   # memoized {(sym,date): technical signal} across strategies
) -> BacktestResult:
    """
    Signal-driven backtest using ML predictions + price technicals.

    When ML predictions exist for a date/symbol, they take priority.
    When they don't (sparse historical data), falls back to RSI+EMA signals
    computed from price history — enabling real backtests even before the
    system has run predictions for every historical date.

    Entry: signal Bullish >= min_confidence, regime allowed, NIFTY not falling
           + DSL entry_conditions evaluated against feature vectors (if available)
    Exit:  stop-loss | take-profit | max-hold | bearish signal flip | DSL exit_conditions
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

    # Pre-load ALL price data in one bulk query (replaces per-day/per-sym DB calls in hot loop)
    if shared_price_data is not None:
        closes_by_sym, sorted_dates_by_sym, hilo_by_sym = shared_price_data
    else:
        closes_by_sym, sorted_dates_by_sym, hilo_by_sym = _preload_prices(db, universe, start_date, end_date)

    # Pre-load feature vectors for DSL condition evaluation (only when DSL has conditions)
    feature_cache: dict[tuple, dict] = {}
    if shared_feature_cache is not None:
        feature_cache = shared_feature_cache   # batch runs: one load, many backtests
    elif entry_conditions is not None or exit_conditions is not None:
        from aqrti.database.models import FeatureValue
        feat_rows = (
            db.query(FeatureValue.symbol, FeatureValue.date, FeatureValue.feature_name, FeatureValue.value)
            .filter(
                FeatureValue.symbol.in_(universe),
                FeatureValue.date >= start_date,
                FeatureValue.date <= end_date,
                FeatureValue.version == 1,
            )
            .all()
        )
        for sym, dt, fname, fval in feat_rows:
            key = (sym, dt)
            if key not in feature_cache:
                feature_cache[key] = {}
            feature_cache[key][fname] = fval

    # Pre-load ML predictions — DISABLED by default: Prediction rows are only
    # written with date.today() by models trained on full history, so any
    # historical prediction row is look-ahead. Backtests are technical+DSL
    # only unless explicitly opted in (e.g. for recent-window live analysis).
    ml_preds = _load_ml_predictions(db, start_date, end_date, universe) if use_ml_predictions else {}
    has_ml = bool(ml_preds)

    # Pre-load regimes and NIFTY trend for all dates in one pass
    all_regimes = (
        db.query(MarketRegime.date, MarketRegime.regime)
        .filter(MarketRegime.date >= start_date - timedelta(days=30), MarketRegime.date <= end_date)
        .order_by(MarketRegime.date.asc())
        .all()
    )
    regime_by_date: dict[date, str] = {}
    last_regime = "BULL"
    for rd, rg in all_regimes:
        regime_by_date[rd] = rg
        last_regime = rg

    nifty_rows = (
        db.query(IndexData.date, IndexData.returns)
        .filter(IndexData.index_name == "NIFTY50",
                IndexData.date >= start_date - timedelta(days=30),
                IndexData.date <= end_date)
        .order_by(IndexData.date.asc())
        .all()
    )
    nifty_ret_by_date: dict[date, float] = {r[0]: r[1] for r in nifty_rows if r[1] is not None}
    nifty_dates_sorted = sorted(nifty_ret_by_date.keys())

    # Build a price-based regime map for all trading dates not in the DB
    # Uses NIFTY returns: 20d trend + 20d volatility → BULL/BEAR/SIDEWAYS/VOLATILE
    _all_nifty_dates = nifty_dates_sorted
    def _price_regime(d: date) -> str:
        past = [nifty_ret_by_date[nd] for nd in _all_nifty_dates if nd <= d][-20:]
        if len(past) < 5:
            return "BULL"
        import statistics
        mean_ret = sum(past) / len(past)
        try:
            vol = statistics.stdev(past)
        except Exception:
            vol = 0.0
        # Returns stored as percentage (e.g. 0.83 = 0.83%) — see market_data._compute_returns
        if vol > 1.6:             # 20d stdev > 1.6%/day → VOLATILE
            return "VOLATILE"
        if mean_ret > 0.05:       # avg +0.05%/day ≈ +1%/month → BULL
            return "BULL"
        if mean_ret < -0.05:      # avg -0.05%/day → BEAR
            return "BEAR"
        return "SIDEWAYS"

    _regime_dates_sorted = sorted(regime_by_date.keys())

    def _regime_on(d: date) -> str:
        """Regime on or before date d — DB first, price-based fallback."""
        import bisect
        idx = bisect.bisect_right(_regime_dates_sorted, d) - 1
        if idx >= 0:
            return regime_by_date[_regime_dates_sorted[idx]]
        # No DB entry for this date: use NIFTY-derived regime as-is.
        # (Previously SIDEWAYS was remapped to BULL, which let BULL-only
        # strategies trade sideways markets by fiat — removed.)
        return _price_regime(d)

    def _nifty_trend_on(d: date, lookback: int = 5) -> str:
        rets = [nifty_ret_by_date[nd] for nd in nifty_dates_sorted if nd <= d][-lookback:]
        if not rets:
            return "FLAT"
        positive = sum(1 for r in rets if r > 0)
        if positive >= len(rets) * 0.7:
            return "UP"
        if positive <= len(rets) * 0.3:
            return "DOWN"
        return "FLAT"

    open_positions: dict[str, dict] = {}
    entries_blocked_no_features = 0
    _bad_bar_trades = 0
    regime_returns: dict[str, list[float]] = {
        "BULL": [], "BEAR": [], "SIDEWAYS": [], "VOLATILE": []
    }

    for d in all_dates:
        regime      = _regime_on(d)
        nifty_trend = _nifty_trend_on(d)
        ml_day      = ml_preds.get(d, {})

        # ── Process exits ──────────────────────────────────
        for sym in list(open_positions.keys()):
            pos = open_positions[sym]
            pos["holding_days"] += 1
            cur_price = _price_before_cached(closes_by_sym, sorted_dates_by_sym, sym, d)
            if cur_price is None:
                continue

            entry_px = pos["entry_price"]
            if entry_px <= 0:
                continue

            exit_reason = ""
            exit_fill   = cur_price   # default: exit at close

            # ── Intrabar SL/TP using the day's open/high/low ──
            # Skip the fill bar itself (entry happened at its close),
            # and skip if OHLC not available for the day.
            bar = hilo_by_sym.get(sym, {}).get(d)
            if bar is not None and d > pos.get("fill_date", pos["entry_date"]):
                bar_open, bar_high, bar_low = bar
                # Circuit-locked bar (high == low): the stock is pinned at an
                # NSE circuit band — no counterparty, you CANNOT exit. Carry
                # the position; close-based checks below also skipped for SL/TP
                # realism (a locked stock fills at neither stop nor target).
                locked = (bar_high is not None and bar_low is not None
                          and bar_high == bar_low)
                if not locked:
                    sl_level = entry_px * (1 + stop_loss_pct / 100)
                    tp_level = entry_px * (1 + take_profit_pct / 100)
                    # Conservative ordering: stop-loss checked before take-profit
                    if bar_open is not None and bar_open <= sl_level:
                        exit_reason, exit_fill = "stop_loss", bar_open    # gap through stop
                    elif bar_low is not None and bar_low <= sl_level:
                        exit_reason, exit_fill = "stop_loss", sl_level
                    elif bar_open is not None and bar_open >= tp_level:
                        exit_reason, exit_fill = "take_profit", bar_open  # gap through target
                    elif bar_high is not None and bar_high >= tp_level:
                        exit_reason, exit_fill = "take_profit", tp_level

            if not exit_reason:
                pnl_close = (cur_price - entry_px) / entry_px * 100
                if pnl_close <= stop_loss_pct:
                    exit_reason = "stop_loss"        # close-based fallback (no OHLC)
                elif pnl_close >= take_profit_pct:
                    exit_reason = "take_profit"
                elif pos["holding_days"] >= max_holding_days:
                    exit_reason = "max_holding_days"
                elif d == end_date:
                    exit_reason = "end_of_backtest"
                else:
                    # Bearish ML flip — exit early (only if ML enabled)
                    flip = ml_day.get(sym, {})
                    if flip.get("direction") == "Bearish" and flip.get("confidence", 0) >= 65:
                        exit_reason = "bearish_flip"
                    # DSL exit conditions evaluated against feature vectors
                    elif exit_conditions is not None:
                        feat_vec = feature_cache.get((sym, d), {})
                        if feat_vec and exit_conditions.evaluate(feat_vec):
                            exit_reason = "exit_rule"

            if exit_reason:
                pnl_pct = (exit_fill - entry_px) / entry_px * 100
                # Corrupt-bar guard: a long delivery trade cannot plausibly
                # return beyond a sane bound. A blowout (e.g. +15,000%) means
                # the exit or entry price is a bad tick / unhealed split
                # artifact. Clamp to the take-profit ceiling so one garbage
                # bar can't dominate expectancy, Sharpe, and the daily series.
                sane_ceiling = max(take_profit_pct * 2.0, 60.0)
                if pnl_pct > sane_ceiling or pnl_pct < -99.0:
                    _bad_bar_trades += 1
                    pnl_pct = min(max(pnl_pct, -99.0), take_profit_pct)
                    exit_fill = entry_px * (1 + pnl_pct / 100)
                exit_cost_pct = _transaction_cost("sell", sym) * 100
                net_pnl = pnl_pct - exit_cost_pct
                t = TradeRecord(
                    symbol        = sym,
                    entry_date    = pos["entry_date"],
                    exit_date     = d,
                    entry_price   = entry_px,
                    exit_price    = exit_fill,
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
                # Technical signal depends only on (symbol, date) — memoize
                # across strategies in batch runs via shared_signal_cache.
                sig = shared_signal_cache.get((sym, d)) if shared_signal_cache is not None else None
                if sig is None:
                    import bisect
                    sym_dates = sorted_dates_by_sym.get(sym, [])
                    sym_closes = closes_by_sym.get(sym, {})
                    if sym_dates:
                        end_idx = bisect.bisect_right(sym_dates, d)
                        hist_closes = [sym_closes[sym_dates[i]] for i in range(max(0, end_idx-120), end_idx)]
                        if len(hist_closes) >= 22:
                            sig = _technical_signal(hist_closes)
                            sig["source"] = "technical"
                            if shared_signal_cache is not None:
                                shared_signal_cache[(sym, d)] = sig
                if sig is not None:
                    signals.append((sym, sig))

        # Sort by confidence descending — highest conviction first
        signals.sort(key=lambda x: x[1]["confidence"], reverse=True)

        for sym, signal in signals:
            if len(open_positions) >= MAX_OPEN_TRADES:
                break

            if not _should_enter(signal, regime, nifty_trend, min_confidence, allowed_regimes):
                continue

            # Evaluate DSL entry conditions — FAIL-CLOSED. A strategy's rules
            # are its identity; if the feature vector is missing for this
            # (symbol, date) we must NOT trade on the generic fallback, or the
            # backtest measures the fallback rather than the strategy.
            if entry_conditions is not None:
                feat_vec = feature_cache.get((sym, d))
                if not feat_vec:
                    entries_blocked_no_features += 1
                    continue
                if not entry_conditions.evaluate(feat_vec):
                    continue  # DSL conditions not met — skip

            # Enter at next-day close; fall back to same-day if not available
            import bisect as _b
            sym_dates_e = sorted_dates_by_sym.get(sym, [])
            fill_idx = _b.bisect_left(sym_dates_e, d + timedelta(days=1))
            if fill_idx < len(sym_dates_e):
                fill_date   = sym_dates_e[fill_idx]
                entry_price = closes_by_sym[sym][fill_date]
            else:
                fill_date   = d
                entry_price = _price_before_cached(closes_by_sym, sorted_dates_by_sym, sym, d)
            if entry_price is None or entry_price <= 0:
                continue

            entry_cost_pct = _transaction_cost("buy", sym)
            open_positions[sym] = {
                "entry_date":   d,
                "fill_date":    fill_date,
                "entry_price":  entry_price * (1 + entry_cost_pct),
                "holding_days": 0,
                "regime_entry": regime,
                "confidence":   signal["confidence"],
                "signal_source": signal.get("source", "ml"),
            }

    # Force-close remaining positions at end_date
    for sym, pos in open_positions.items():
        cur_price = _price_before_cached(closes_by_sym, sorted_dates_by_sym, sym, end_date)
        if cur_price is None or pos["entry_price"] <= 0:
            continue
        pnl_pct = (cur_price - pos["entry_price"]) / pos["entry_price"] * 100
        # Same corrupt-bar guard as the main exit path
        sane_ceiling = max(take_profit_pct * 2.0, 60.0)
        if pnl_pct > sane_ceiling or pnl_pct < -99.0:
            _bad_bar_trades += 1
            pnl_pct = min(max(pnl_pct, -99.0), take_profit_pct)
            cur_price = pos["entry_price"] * (1 + pnl_pct / 100)
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

    # Real mark-to-market daily portfolio return series (percent units)
    daily_series, exposure = build_daily_portfolio_returns(
        result.trades, closes_by_sym, sorted_dates_by_sym
    )
    result.compute_metrics(daily_returns=daily_series)
    result.exposure_pct = exposure

    # Regime-stratified Sharpe
    for reg, rets in regime_returns.items():
        if len(rets) >= 3:
            s = compute_sharpe(rets)
            setattr(result, f"{reg.lower()}_sharpe", s)

    result.regime_trades = {k: len(v) for k, v in regime_returns.items()}

    if entries_blocked_no_features:
        log.info(
            "Backtest %s: %d entries blocked (no feature vector — fail-closed DSL)",
            strategy_id, entries_blocked_no_features,
        )
    if _bad_bar_trades:
        log.warning(
            "Backtest %s: %d trades clamped for corrupt price bars (bad tick / unhealed split) — "
            "run /admin/integrity-sweep to heal source data",
            strategy_id, _bad_bar_trades,
        )
    log.info(
        "Backtest %s: trades=%d sharpe=%.3f win_rate=%.1f%% mdd=%.1f%% exposure=%.0f%%",
        strategy_id, result.trade_count, result.sharpe,
        result.win_rate, result.max_drawdown, result.exposure_pct,
    )
    return result


def _walk_forward_oos_check(
    db:               Session,
    strategy,
    full_end:         date,
    oos_months:       int = 6,
    min_oos_trades:   int = 5,
    min_oos_win_rate: float = 50.0,
    shared_feature_cache: Optional[dict] = None,
    shared_price_data: Optional[tuple] = None,
    shared_signal_cache: Optional[dict] = None,
) -> dict:
    """
    Quick out-of-sample check: re-run the strategy on the last `oos_months` of data
    that were EXCLUDED from the main backtest (last 6 months → in-sample used the preceding 4.5yr).

    A strategy that degrades badly in the most recent period is likely overfit to
    older market conditions. We store the OOS result as strategy metadata but do NOT
    use it as a hard reject here — that's the fitness engine's job. We do penalise
    fitness via the result dict if OOS win rate is >10pp below in-sample.

    Returns: { "oos_win_rate", "oos_trades", "oos_sharpe", "oos_passed", "oos_penalty" }
    """
    oos_end   = full_end
    oos_start = full_end - timedelta(days=oos_months * 30)

    try:
        entry_conds = getattr(strategy, "entry_conditions", None)
        exit_conds  = getattr(strategy, "exit_conditions",  None)
        sid         = strategy.strategy_id() if hasattr(strategy, "strategy_id") else strategy.get("strategy_id", "OOS")
        min_conf    = getattr(strategy, "min_confidence",   50.0)
        sl          = getattr(strategy, "stop_loss_pct",    -7.0)
        tp          = getattr(strategy, "take_profit_pct",  12.0)
        hold        = getattr(strategy, "max_holding_days", 20)
        regimes     = getattr(strategy, "allowed_regimes",  ["BULL", "SIDEWAYS", "BEAR", "VOLATILE"])

        oos_result = backtest_strategy(
            db               = db,
            strategy_id      = f"{sid}_oos",
            start_date       = oos_start,
            end_date         = oos_end,
            min_confidence   = min_conf,
            stop_loss_pct    = sl,
            take_profit_pct  = tp,
            max_holding_days = hold,
            allowed_regimes  = regimes,
            use_technical_fallback = True,
            entry_conditions = entry_conds,
            exit_conditions  = exit_conds,
            shared_feature_cache = shared_feature_cache,
            shared_price_data    = shared_price_data,
            shared_signal_cache  = shared_signal_cache,
        )
        oos_wr     = oos_result.win_rate
        oos_trades = oos_result.trade_count
        oos_sharpe = oos_result.sharpe
        # Hard pass requires: enough trades, win rate >= 50%, and positive
        # net expectancy in the held-out window (profitable after costs).
        oos_passed = (
            oos_trades >= min_oos_trades
            and oos_wr >= min_oos_win_rate
            and oos_result.expectancy > 0
        )
    except Exception as e:
        log.debug("OOS check failed (non-fatal): %s", e)
        return {"oos_win_rate": None, "oos_trades": 0, "oos_sharpe": None, "oos_passed": None, "oos_penalty": 0.0}

    return {
        "oos_win_rate": round(oos_wr, 2),
        "oos_trades":   oos_trades,
        "oos_sharpe":   round(oos_sharpe, 4),
        "oos_passed":   oos_passed,
        "oos_penalty":  0.0,
    }


def backtest_and_update(
    db:         Session,
    strategy,                    # StrategyDSL or dict with strategy params
    start_date: Optional[date] = None,
    end_date:   Optional[date] = None,
    universe:   Optional[list[str]] = None,
    shared_feature_cache: Optional[dict] = None,
    shared_price_data: Optional[tuple] = None,
    shared_signal_cache: Optional[dict] = None,
) -> BacktestResult:
    """Backtest a strategy and write results to StrategyV2 + individual trades."""
    from strategies.strategy_store import upsert_strategy
    from aqrti.database.models import StrategyBacktestTrade

    end   = end_date   or date.today()
    start = start_date or (end - timedelta(days=5*365))

    # Extract params from StrategyDSL if provided
    entry_conds = None
    exit_conds  = None
    if hasattr(strategy, "strategy_id"):
        sid               = strategy.strategy_id()
        min_confidence    = getattr(strategy, "min_confidence",   50.0)
        stop_loss_pct     = getattr(strategy, "stop_loss_pct",    -7.0)
        take_profit_pct   = getattr(strategy, "take_profit_pct",  12.0)
        max_holding_days  = getattr(strategy, "max_holding_days", 20)
        allowed_regimes   = getattr(strategy, "allowed_regimes",  ["BULL", "SIDEWAYS", "BEAR", "VOLATILE"])
        family            = getattr(strategy, "family",           "hybrid")
        name              = getattr(strategy, "name",             "")
        entry_conds       = getattr(strategy, "entry_conditions", None)
        exit_conds        = getattr(strategy, "exit_conditions",  None)
    else:
        sid               = strategy.get("strategy_id", "UNKNOWN")
        min_confidence    = strategy.get("min_confidence",   50.0)
        stop_loss_pct     = strategy.get("stop_loss_pct",    -7.0)
        take_profit_pct   = strategy.get("take_profit_pct",  12.0)
        max_holding_days  = strategy.get("max_holding_days", 20)
        allowed_regimes   = strategy.get("allowed_regimes",  ["BULL", "SIDEWAYS", "BEAR", "VOLATILE"])
        family            = strategy.get("family",           "hybrid")
        name              = strategy.get("name",             "")

    # Walk-forward split: in-sample = start → (oos_end - 6mo - embargo), where
    # the embargo (= max holding period) prevents trades opened near the
    # boundary from leaking into the out-of-sample window.
    #
    # Anti-leak rotation: a single fixed holdout shared by thousands of
    # evolved candidates gets overfit BY SELECTION even though no individual
    # strategy saw it. Shift each strategy's holdout end by a deterministic
    # 0-59 day offset derived from its ID, so the population is graded on
    # staggered windows rather than one leaky one.
    import hashlib
    oos_months   = 6
    embargo_days = int(max_holding_days or 20)
    shift_days   = int(hashlib.md5(sid.encode()).hexdigest()[:8], 16) % 60
    oos_end      = end - timedelta(days=shift_days)
    is_end       = oos_end - timedelta(days=oos_months * 30 + embargo_days)

    result = backtest_strategy(
        db               = db,
        strategy_id      = sid,
        start_date       = start,
        end_date         = is_end,        # in-sample only
        universe         = universe,
        min_confidence   = min_confidence,
        stop_loss_pct    = stop_loss_pct,
        take_profit_pct  = take_profit_pct,
        max_holding_days = max_holding_days,
        allowed_regimes  = allowed_regimes,
        use_technical_fallback = True,
        entry_conditions = entry_conds,
        exit_conditions  = exit_conds,
        shared_feature_cache = shared_feature_cache,
        shared_price_data    = shared_price_data,
        shared_signal_cache  = shared_signal_cache,
    )

    # Walk-forward OOS check on the held-out (rotated) 6-month window
    oos = _walk_forward_oos_check(db, strategy, full_end=oos_end, oos_months=oos_months,
                                  shared_feature_cache=shared_feature_cache,
                                  shared_price_data=shared_price_data,
                                  shared_signal_cache=shared_signal_cache)
    oos_win_rate = oos.get("oos_win_rate")
    oos_passed   = oos.get("oos_passed")

    # If OOS win rate degrades >12pp vs in-sample → overfit flag; penalise Sharpe
    # so fitness scoring naturally demotes the strategy below promotion threshold
    if oos_win_rate is not None and result.win_rate > 0:
        wr_gap = result.win_rate - oos_win_rate
        if wr_gap > 12.0:
            # Penalise Sharpe proportional to the overfit gap
            penalty_factor = max(0.5, 1.0 - (wr_gap - 12.0) / 50.0)
            result.sharpe  = round(result.sharpe * penalty_factor, 4)
            result.sortino = round(result.sortino * penalty_factor, 4)
            log.info(
                "OOS overfit detected %s: IS_WR=%.1f%% OOS_WR=%.1f%% gap=%.1fpp -> sharpe penalised x%.2f",
                sid, result.win_rate, oos_win_rate, wr_gap, penalty_factor,
            )

    # Write results in a dedicated short-lived session to avoid holding the
    # long read session open during the commit (prevents SQLite "database is locked").
    from aqrti.database.engine import get_db as _get_write_db
    from aqrti.database.models import StrategyV2 as _SV2
    with _get_write_db() as write_db:
        # Preserve the strategy's current lifecycle status — a re-backtest
        # must not silently demote promoted/active strategies. Demotion is
        # the lifecycle sweep's job, based on the fresh metrics.
        existing = write_db.query(_SV2.status).filter(_SV2.strategy_id == result.strategy_id).first()
        current_status = existing[0] if existing else "shadow"

        upsert_strategy(write_db, {
            "strategy_id":       result.strategy_id,
            "sharpe":            result.sharpe,
            "sortino":           result.sortino,
            "win_rate":          result.win_rate,
            "profit_factor":     result.profit_factor,
            "max_drawdown":      result.max_drawdown,
            "expectancy":        result.expectancy,
            "trade_count":       result.trade_count,
            "avg_holding_days":  result.avg_holding_days,
            "exposure_pct":      result.exposure_pct,
            "bull_sharpe":       result.bull_sharpe,
            "bear_sharpe":       result.bear_sharpe,
            "sideways_sharpe":   result.sideways_sharpe,
            "volatile_sharpe":   result.volatile_sharpe,
            "oos_sharpe":        oos.get("oos_sharpe"),
            "oos_win_rate":      oos_win_rate,
            "oos_trades":        oos.get("oos_trades", 0),
            "oos_passed":        oos_passed,
            "backtest_start":    start,
            "backtest_end":      end,
            "backtest_universe": result.universe_size,
            "status":            current_status,
            "family":            family,
            "name":              name,
        })

        # Persist individual trades — delete stale, insert fresh
        write_db.query(StrategyBacktestTrade).filter_by(strategy_id=result.strategy_id).delete()
        for t in result.trades:
            write_db.add(StrategyBacktestTrade(
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

    return result
