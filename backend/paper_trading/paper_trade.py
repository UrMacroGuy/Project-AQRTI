"""
Paper Trade Manager
Open, close, and query virtual positions + trades.
Prices: Finnhub real-time (primary) → yfinance (fallback) → DB EOD close.
"""

from __future__ import annotations

from contextlib import redirect_stderr
from io import StringIO
import os
from datetime import date, datetime
from typing import Optional

from sqlalchemy.orm import Session

from aqrti.database.models import PaperPosition, PaperTrade, DailyPrice, Stock
from aqrti.utils.logger import get_logger

log = get_logger("paper_trade")

PORTFOLIO_NAME = "default"

# Must match strategy_backtester.py's NSE delivery round-trip cost model
# (0.28% total, ~55/45 buy/sell split) so paper P&L is comparable to backtest
# P&L. Previously this module applied ZERO cost — every paper trade's return
# was inflated by the full round-trip vs. both the backtester and the
# strategy_shadow_runner, which do apply it.
_NSE_ROUND_TRIP_COST = 0.0028
NSE_BUY_COST_PCT  = _NSE_ROUND_TRIP_COST * 0.55
NSE_SELL_COST_PCT = _NSE_ROUND_TRIP_COST * 0.45

# NSE symbol → Yahoo Finance ticker map
_NSE_TO_YF = {
    # Original 20
    "RELIANCE":   "RELIANCE.NS",   "HDFCBANK":   "HDFCBANK.NS",   "ICICIBANK":  "ICICIBANK.NS",
    "INFY":       "INFY.NS",       "TCS":        "TCS.NS",        "AXISBANK":   "AXISBANK.NS",
    "SBIN":       "SBIN.NS",       "BAJFINANCE": "BAJFINANCE.NS", "MARUTI":     "MARUTI.NS",
    "TITAN":      "TITAN.NS",      "WIPRO":      "WIPRO.NS",      "ONGC":       "ONGC.NS",
    "SUNPHARMA":  "SUNPHARMA.NS",  "NESTLEIND":  "NESTLEIND.NS",  "BHARTIARTL": "BHARTIARTL.NS",
    "KOTAKBANK":  "KOTAKBANK.NS",  "TATASTEEL":  "TATASTEEL.NS",  "HINDALCO":   "HINDALCO.NS",
    # Expanded 30
    "HCLTECH":    "HCLTECH.NS",    "ITC":        "ITC.NS",        "LT":         "LT.NS",
    "HINDUNILVR": "HINDUNILVR.NS", "ULTRACEMCO": "ULTRACEMCO.NS", "BAJAJFINSV": "BAJAJFINSV.NS",
    "NTPC":       "NTPC.NS",       "ADANIENT":   "ADANIENT.NS",   "ADANIPORTS": "ADANIPORTS.NS",
    "JSWSTEEL":   "JSWSTEEL.NS",   "TECHM":      "TECHM.NS",      "COALINDIA":  "COALINDIA.NS",
    "BPCL":       "BPCL.NS",       "HDFCLIFE":   "HDFCLIFE.NS",   "SBILIFE":    "SBILIFE.NS",
    "INDUSINDBK": "INDUSINDBK.NS", "M&M":        "M&M.NS",        "DIVISLAB":   "DIVISLAB.NS",
    "DRREDDY":    "DRREDDY.NS",    "EICHERMOT":  "EICHERMOT.NS",  "HEROMOTOCO": "HEROMOTOCO.NS",
    "CIPLA":      "CIPLA.NS",      "BRITANNIA":  "BRITANNIA.NS",  "APOLLOHOSP": "APOLLOHOSP.NS",
    "TRENT":      "TRENT.NS",      "GRASIM":     "GRASIM.NS",     "SHREECEM":   "SHREECEM.NS",
    "BEL":        "BEL.NS",        "POWERGRID":  "POWERGRID.NS",  "ASIANPAINT": "ASIANPAINT.NS",
}

# In-process cache: symbol → (price, fetched_at_epoch) — valid for 60s
import time as _time
_price_cache: dict[str, tuple[float, float]] = {}
_CACHE_TTL = 60  # seconds


def _live_price_finnhub(symbol: str) -> Optional[float]:
    """Fetch current price from Finnhub (primary real-time source, 60s cache)."""
    try:
        from aqrti.data.finnhub_client import get_quote
        return get_quote(symbol)
    except Exception as exc:
        log.debug("Finnhub price fetch failed for %s: %s", symbol, exc)
        return None


# yfinance's underlying requests session has no default timeout -- a slow
# or unresponsive Yahoo endpoint can hang for minutes (bounded only by the
# OS TCP timeout), and get_open_positions() calls this once per open
# position sequentially. Confirmed live: with the market closed, a single
# GET /paper-portfolio request with 7 open positions hung indefinitely in a
# real browser (a direct fetch() to the same endpoint from the page's own
# JS context also hung past 20s) -- this is unacceptable for an endpoint
# the paper portfolio page calls on every visit.
#
# A custom requests.Session passed to yf.Ticker(session=...) was tried
# first but breaks yfinance 1.4.1's internal cookie/crumb auth flow
# entirely (fast_info silently returned None instead of a real price with
# no error) -- yfinance's YfData wraps its own session-management logic
# that a bare custom session doesn't replicate. Running the call in a
# worker thread with a hard wall-clock join timeout is version-independent
# and doesn't touch yfinance's internals at all: if it doesn't finish in
# time the calling thread moves on and the worker is abandoned (daemon
# thread, does not block process exit).
_YF_TIMEOUT_SECONDS = 4


def _yf_fetch_price(symbol: str) -> Optional[float]:
    """Blocking yfinance fetch — only ever called inside a bounded worker thread."""
    yf_sym = _NSE_TO_YF.get(symbol, f"{symbol}.NS")
    import yfinance as yf
    ticker = yf.Ticker(yf_sym)
    price = None
    try:
        yf_stderr = StringIO()
        with redirect_stderr(yf_stderr):
            fi = ticker.fast_info
        price = getattr(fi, "last_price", None)
        if price is not None:
            price = float(price)
    except Exception:
        pass
    if price is None:
        yf_stderr = StringIO()
        with redirect_stderr(yf_stderr):
            hist = ticker.history(period="1d", interval="1m", auto_adjust=True)
        if not hist.empty:
            price = float(hist["Close"].iloc[-1])
    return price if price and price > 0 else None


# Reused across calls (not a `with ThreadPoolExecutor() as ex:` block) --
# the executor's context-manager __exit__ calls shutdown(wait=True), which
# would block waiting for an already-abandoned, still-hanging worker thread
# and reintroduce the exact hang this is meant to prevent. A module-level
# pool lets future.result(timeout=...) return promptly on timeout while the
# stuck worker is simply left running in the background (daemon-owned by
# the pool, does not block process exit) instead of being waited on.
import concurrent.futures as _cf
_yf_executor = _cf.ThreadPoolExecutor(max_workers=4, thread_name_prefix="yf-price")


def _live_price_yf(symbol: str) -> Optional[float]:
    """Fetch current price from yfinance (fallback, 60s in-memory cache).
    Bounded to _YF_TIMEOUT_SECONDS wall-clock time via a worker thread --
    returns None on timeout instead of blocking the caller.
    """
    now = _time.time()
    cached = _price_cache.get(symbol)
    if cached and (now - cached[1]) < _CACHE_TTL:
        return cached[0]

    try:
        future = _yf_executor.submit(_yf_fetch_price, symbol)
        price = future.result(timeout=_YF_TIMEOUT_SECONDS)
    except _cf.TimeoutError:
        log.debug("yfinance price fetch timed out for %s after %ss", symbol, _YF_TIMEOUT_SECONDS)
        return None
    except Exception as e:
        log.debug("yfinance price fetch failed for %s: %s", symbol, e)
        return None

    if price:
        _price_cache[symbol] = (price, now)
    return price


def _latest_price(db: Session, symbol: str) -> Optional[float]:
    """Return most recent EOD close from DB."""
    row = (
        db.query(DailyPrice.close)
        .filter(DailyPrice.symbol == symbol)
        .order_by(DailyPrice.date.desc())
        .first()
    )
    return row[0] if row else None


# Reject any live quote that deviates more than this fraction from the DB's
# last EOD close before trusting it as a fill price. Guards against a bad
# Finnhub/yfinance tick (wrong symbol match, stale/adjusted quote, API
# glitch) closing a position at a fabricated ~99% "loss" -- this happened
# live on 2026-07-11 (HAL ~4514 -> live quote ~34, INFY ~1070 -> ~11),
# wiping ~71,000 of fake stop-loss P&L across 27 trades in one evening.
_LIVE_QUOTE_MAX_DEVIATION = 0.25  # 25% vs last close in a single tick is implausible intraday


def _sane_vs_eod(db: Session, symbol: str, price: float) -> bool:
    eod = _latest_price(db, symbol)
    if not eod or eod <= 0:
        return True  # nothing to compare against -- don't block on absence of a reference
    deviation = abs(price - eod) / eod
    if deviation > _LIVE_QUOTE_MAX_DEVIATION:
        log.warning(
            "Rejected implausible live price for %s: quote=%.2f eod_close=%.2f (%.0f%% deviation)",
            symbol, price, eod, deviation * 100,
        )
        return False
    return True


def _current_price(db: Session, symbol: str, entry_price: float) -> float:
    """
    Best available price for an open position:
    1. Finnhub real-time quote (primary — configured via AQRTI_FINNHUB_API_KEY)
    2. yfinance live price (fallback, 60s cache)
    3. Latest EOD close from DB
    4. Entry price as last resort
    Any live quote (1/2) that deviates >25% from the DB's last EOD close is
    rejected as implausible and the next source is tried instead.
    """
    finnhub = _live_price_finnhub(symbol)
    if finnhub and finnhub > 0 and _sane_vs_eod(db, symbol, finnhub):
        return finnhub
    live = _live_price_yf(symbol)
    if live and live > 0 and _sane_vs_eod(db, symbol, live):
        return live
    eod = _latest_price(db, symbol)
    if eod and eod > 0:
        return eod
    return entry_price


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
    strategy_id:     str  = None,
    strategy_name:   str  = None,
    stop_loss_pct:   Optional[float] = None,   # from the driving strategy's DSL, if any
    take_profit_pct: Optional[float] = None,
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

    # Live news gate — skip NEW entries on symbols with fresh high-conviction
    # negative news (LLM-verified). Live path only; the backtester has no
    # such gate by design (see news/live_news_gate.py docstring).
    try:
        from news.live_news_gate import news_blocks_entry
        blocked, reason = news_blocks_entry(db, symbol)
        if blocked:
            log.info("News gate blocked entry on %s — %s", symbol, reason)
            return None
    except Exception as exc:
        log.debug("News gate unavailable (fail-open): %s", exc)

    # Cost-loaded fill — matches strategy_backtester.py's entry cost model
    filled_price = entry_price * (1 + NSE_BUY_COST_PCT)
    shares    = capital / filled_price
    weight    = capital / portfolio_value * 100 if portfolio_value > 0 else 0.0
    # Use the driving strategy's OWN backtested SL/TP when available — a flat
    # 8%/max(expected_return,3%) fallback only applies when no strategy is
    # attached (pure-ML signal with no strategy match). Using the strategy's
    # actual thresholds here is what makes paper P&L attributable to "this
    # strategy works", matching what strategy_shadow_runner.py already does.
    if stop_loss_pct is not None:
        stop_loss = filled_price * (1 + stop_loss_pct / 100)   # stop_loss_pct is negative
    else:
        stop_loss = filled_price * 0.92        # 8% hard stop fallback
    if take_profit_pct is not None:
        target = filled_price * (1 + take_profit_pct / 100)
    else:
        target = filled_price * (1 + max(expected_return / 100, 0.03))

    pos = PaperPosition(
        portfolio_name   = PORTFOLIO_NAME,
        symbol           = symbol,
        sector           = sector,
        entry_date       = date.today(),
        entry_price      = filled_price,
        shares           = shares,
        capital_deployed = capital,
        weight_pct       = round(weight, 4),
        direction        = direction,
        confidence       = confidence,
        expected_return  = expected_return,
        stop_loss_price  = round(stop_loss, 4),
        target_price     = round(target, 4),
        prediction_id    = prediction_id,
        strategy_id      = strategy_id,
        strategy_name    = strategy_name,
    )
    db.add(pos)

    trade = PaperTrade(
        portfolio_name   = PORTFOLIO_NAME,
        symbol           = symbol,
        sector           = sector,
        entry_date       = date.today(),
        entry_price      = filled_price,
        shares           = shares,
        capital_deployed = capital,
        weight_pct       = round(weight, 4),
        direction        = direction,
        confidence       = confidence,
        predicted_return = expected_return,
        is_open          = True,
        prediction_id    = prediction_id,
        strategy_id      = strategy_id,
        strategy_name    = strategy_name,
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

    raw_exit_price = _current_price(db, symbol, pos.entry_price)
    # Cost-loaded fill on exit — matches strategy_backtester.py's exit cost model.
    # pos.entry_price is already cost-loaded (see open_position), so this
    # nets both legs of the round-trip, same as backtest/shadow-runner trades.
    exit_price    = raw_exit_price * (1 - NSE_SELL_COST_PCT)
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

    # Notify live validator so StrategyPerformance gets updated immediately
    if trade:
        try:
            import sys as _sys
            _backend = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            if _backend not in _sys.path:
                _sys.path.insert(0, _backend)
            from strategies.live_validator import on_trade_closed
            on_trade_closed(db, trade)
        except Exception as _exc:
            log.debug("live_validator hook failed: %s", _exc)

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
    """Return all open positions with current unrealized P&L.

    Uses the DB's last EOD close (_latest_price), NOT a live Finnhub/
    yfinance call. This is a read endpoint hit on every Paper Portfolio
    page load; calling out to two live-quote vendors per open position
    made it take ~11s with 7 positions and the market closed (each vendor
    attempt is bounded to a few seconds but they're sequential), which
    exceeded the frontend's 10s fetch timeout -- the page silently fell
    back to its honest-empty state even though the backend eventually
    responded fine. The EOD close is already refreshed daily by the
    scheduled pipeline and is accurate enough for a display/unrealized-P&L
    view; live intraday pricing still matters for the actual close/
    stop-loss execution path (close_position -> _current_price, unchanged).
    """
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
            "strategyId":      pos.strategy_id,
            "strategyName":    pos.strategy_name,
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
            "strategyId":      t.strategy_id,
            "strategyName":    t.strategy_name,
        }
        for t in trades
    ]
