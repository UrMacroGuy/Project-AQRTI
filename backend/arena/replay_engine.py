"""
Arena Replay Engine — v2
=========================
Walks 2 years of historical price data day-by-day, simulating paper trading
for a single isolated strategy portfolio.

v2 improvements over v1:
- Batch price load per day (single query for all symbols, not N queries)
- Volume filter using 20-day average volume (prevents entering on thin days)
- EMA spread gate (trend must be strong enough to enter)
- Regime-aware params (reads arena_v2.regime_routing from child DSL)
- Better RSI: uses Wilder smoothing (true RSI, not simple average)
- ATR-based stop loss (adapts to recent volatility, tighter in calm markets)
- Signal quality score: only takes top 5 signals per day (not 8)
- Position sizing: risk-fixed (risk 1% of portfolio per trade via ATR)
- Tracks both trade-level and day-level win/loss (important for merger)
"""

from __future__ import annotations

import json
import sys
import os
from datetime import date, timedelta
from typing import Optional

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from aqrti.database.models import (
    DailyPrice, StrategyV2, PaperPortfolio, PaperTrade,
    PaperPosition, EquityCurvePoint,
)
from aqrti.utils.logger import get_logger

log = get_logger("replay_engine_v2")

INITIAL_CAPITAL   = 100_000.0   # ₹1,00,000 per strategy
REPLAY_YEARS      = 2
MAX_OPEN_POSITIONS = 6          # reduced from 8 — concentrate in best signals
RISK_PER_TRADE_PCT = 1.0        # risk 1% of portfolio per trade (position sizing via ATR)
MIN_SIGNALS_TO_OPEN = 1         # open if there's at least 1 quality signal
LOOKBACK_DAYS      = 120        # days of history to fetch per symbol

# NSE delivery-equity round-trip transaction cost (STT + brokerage + exchange
# charges + stamp duty + GST + slippage) — same 0.28% figure used everywhere
# else in the system (strategy_backtester.ROUND_TRIP_COST,
# promotion_config.py's rationale comments). Split ~55/45 buy/sell to match
# strategy_backtester._transaction_cost's split (buy carries stamp duty).
#
# Previously this module applied NO transaction cost at all — every
# PaperTrade.gross_pnl / gross_pnl_pct here was pure price delta with zero
# cost drag, and portfolio.current_cash was credited with that same gross
# PnL. The arena's champion gates (120% return, <25% drawdown, >52% win
# rate — see arena_engine.MAX_DRAWDOWN_GATE etc.) graded strategies entirely
# on this gross series, so a high-turnover strategy could clear "champion"
# purely because costs were never deducted. Every other backtest path in the
# codebase (strategy_backtester.py, paper_trade.py, continuous_monitor.py —
# see BUG_HUNTING.md C1) enforces the 0.28% round-trip; the arena replay was
# the one path where it was silently absent.
NSE_ROUND_TRIP_COST = 0.0028
NSE_BUY_COST_PCT    = NSE_ROUND_TRIP_COST * 0.55
NSE_SELL_COST_PCT   = NSE_ROUND_TRIP_COST * 0.45


# ── Portfolio management ───────────────────────────────────────────────────

def _ensure_portfolio(db: Session, portfolio_name: str) -> PaperPortfolio:
    p = db.query(PaperPortfolio).filter_by(portfolio_name=portfolio_name).first()
    if not p:
        p = PaperPortfolio(
            portfolio_name  = portfolio_name,
            initial_capital = INITIAL_CAPITAL,
            current_cash    = INITIAL_CAPITAL,
            total_value     = INITIAL_CAPITAL,
            peak_value      = INITIAL_CAPITAL,
        )
        db.add(p)
        db.commit()
        db.refresh(p)
    return p


def _wipe_portfolio(db: Session, portfolio_name: str):
    db.query(PaperTrade).filter_by(portfolio_name=portfolio_name).delete()
    db.query(PaperPosition).filter_by(portfolio_name=portfolio_name).delete()
    db.query(EquityCurvePoint).filter_by(portfolio_name=portfolio_name).delete()
    p = db.query(PaperPortfolio).filter_by(portfolio_name=portfolio_name).first()
    if p:
        p.current_cash     = INITIAL_CAPITAL
        p.total_value      = INITIAL_CAPITAL
        p.peak_value       = INITIAL_CAPITAL
        p.total_return_pct = 0.0
        p.max_drawdown_pct = 0.0
    db.commit()


# ── Date / price helpers ───────────────────────────────────────────────────

def _get_trading_dates(db: Session, years: int = REPLAY_YEARS) -> list[date]:
    cutoff = date.today() - timedelta(days=years * 365)
    rows = (
        db.query(DailyPrice.date)
        .filter(DailyPrice.date >= cutoff)
        .distinct()
        .order_by(DailyPrice.date)
        .all()
    )
    return [r[0] for r in rows]


def _batch_prices(db: Session, sim_date: date) -> dict[str, dict]:
    """
    Single query to get all prices for sim_date.
    Returns {symbol: {close, open, high, low, volume}} where available.
    Only DailyPrice columns that exist are returned.
    """
    rows = db.query(DailyPrice).filter(
        DailyPrice.date == sim_date,
        DailyPrice.close.isnot(None),
    ).all()
    result = {}
    for r in rows:
        result[r.symbol] = {
            "close":  float(r.close),
            "open":   float(r.open)   if getattr(r, "open", None) is not None else float(r.close),
            "high":   float(r.high)   if getattr(r, "high", None) is not None else float(r.close),
            "low":    float(r.low)    if getattr(r, "low", None)  is not None else float(r.close),
            "volume": float(r.volume) if getattr(r, "volume", None) is not None else 0.0,
        }
    return result


def _batch_history(
    db: Session,
    symbols: list[str],
    end_date: date,
    lookback: int = LOOKBACK_DAYS,
) -> dict[str, list[dict]]:
    """
    Fetch close/high/low/volume for up to `lookback` days before end_date
    for the given symbols, in a single query.
    Returns {symbol: [{close, high, low, volume, date}, ...]} ordered oldest→newest.
    """
    start = end_date - timedelta(days=lookback)
    rows = db.query(
        DailyPrice.symbol,
        DailyPrice.date,
        DailyPrice.close,
        DailyPrice.high,
        DailyPrice.low,
        DailyPrice.volume,
    ).filter(
        DailyPrice.symbol.in_(symbols),
        DailyPrice.date  >= start,
        DailyPrice.date  <  end_date,
        DailyPrice.close.isnot(None),
    ).order_by(DailyPrice.symbol, DailyPrice.date).all()

    result: dict[str, list[dict]] = {}
    for r in rows:
        sym = r[0]
        if sym not in result:
            result[sym] = []
        result[sym].append({
            "date":   r[1],
            "close":  float(r[2]),
            "high":   float(r[3]) if r[3] else float(r[2]),
            "low":    float(r[4]) if r[4] else float(r[2]),
            "volume": float(r[5]) if r[5] else 0.0,
        })
    return result


# ── Technical indicators ───────────────────────────────────────────────────

def _wilder_rsi(closes: list[float], period: int = 14) -> Optional[float]:
    """Wilder's smoothed RSI — standard implementation."""
    if len(closes) < period + 1:
        return None
    deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    gains  = [max(d, 0) for d in deltas]
    losses = [max(-d, 0) for d in deltas]

    # Seed
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss < 1e-10:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)


def _ema(closes: list[float], period: int) -> Optional[float]:
    if len(closes) < period:
        return None
    k = 2 / (period + 1)
    ema = sum(closes[:period]) / period
    for c in closes[period:]:
        ema = c * k + ema * (1 - k)
    return round(ema, 4)


def _atr(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> Optional[float]:
    if len(closes) < period + 1:
        return None
    trs = []
    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i-1]),
            abs(lows[i]  - closes[i-1]),
        )
        trs.append(tr)
    if len(trs) < period:
        return None
    # Wilder ATR
    atr = sum(trs[:period]) / period
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period
    return round(atr, 4)


def _avg_volume(volumes: list[float], period: int = 20) -> float:
    if not volumes:
        return 0.0
    recent = volumes[-period:] if len(volumes) >= period else volumes
    return sum(recent) / len(recent)


# ── Current regime for a date ──────────────────────────────────────────────

def _get_regime(db: Session, sim_date: date) -> Optional[str]:
    try:
        from aqrti.database.models import MarketRegime
        r = db.query(MarketRegime.regime).filter(
            MarketRegime.date <= sim_date
        ).order_by(MarketRegime.date.desc()).first()
        return r[0] if r else None
    except Exception:
        return None


def _params_for_regime(dsl: dict, regime: Optional[str]) -> dict:
    """
    Select parameter set from arena_v2.regime_routing based on current regime.
    Falls back to top-level DSL params if no routing block exists.
    """
    # rsi_entry_below=None means "no RSI gate" (e.g. sentiment strategies don't use RSI)
    _rsi_raw = dsl.get("rsi_entry_below")
    _ema_spread_raw = dsl.get("ema_spread_min_pct")
    _vol_mult_raw   = dsl.get("volume_min_multiplier")
    base = {
        "stop_loss_pct":        float(dsl.get("stop_loss_pct",         5.0)),
        "take_profit_pct":      float(dsl.get("take_profit_pct",       14.0)),
        "rsi_entry_below":      float(_rsi_raw) if _rsi_raw is not None else None,
        "min_confidence":       float(dsl.get("min_confidence",         55.0)),
        "max_hold_days":        int(dsl.get("max_hold_days",            20)),
        "ema_spread_min_pct":   float(_ema_spread_raw) if _ema_spread_raw is not None else 0.0,
        "volume_min_multiplier":float(_vol_mult_raw)   if _vol_mult_raw   is not None else 1.0,
    }
    if not regime:
        return base

    routing = dsl.get("arena_v2", {}).get("regime_routing", {})
    if regime in routing:
        override = routing[regime]
        for k in base:
            if k in override:
                try:
                    if k == "max_hold_days":
                        base[k] = int(override[k])
                    elif k == "rsi_entry_below":
                        # Preserve None if original had no RSI gate
                        base[k] = float(override[k]) if base[k] is not None else None
                    else:
                        base[k] = float(override[k])
                except Exception:
                    pass
    return base


# ── Signal generation (vectorised per-symbol, batch history) ───────────────

def _score_signals(
    dsl: dict,
    today_prices: dict[str, dict],
    history: dict[str, list[dict]],
    params: dict,
) -> list[dict]:
    """
    Score every symbol and return ranked entry signals.
    - Only enters if: RSI<gate AND EMA20>EMA50 AND EMA spread > min AND volume surge
    - Signal quality = composite score (not just confidence)
    - ATR-based stop loss and target
    """
    sl_pct        = params["stop_loss_pct"]
    tp_pct        = params["take_profit_pct"]
    rsi_gate      = params["rsi_entry_below"]
    min_conf      = params["min_confidence"]
    ema_spread    = params["ema_spread_min_pct"]
    vol_mult      = params["volume_min_multiplier"]

    signals = []

    for sym, today in today_prices.items():
        hist = history.get(sym)
        if not hist or len(hist) < 22:
            continue

        closes  = [h["close"]  for h in hist]
        highs   = [h["high"]   for h in hist]
        lows    = [h["low"]    for h in hist]
        volumes = [h["volume"] for h in hist]

        cur = today["close"]
        closes_with_today = closes + [cur]

        # RSI gate — skipped for strategies that don't use RSI (e.g. sentiment)
        rsi = _wilder_rsi(closes_with_today)
        if rsi_gate is not None:
            if rsi is None or rsi >= rsi_gate:
                continue

        # EMA trend
        ema20 = _ema(closes_with_today, 20)
        ema50 = _ema(closes_with_today, 50) if len(closes_with_today) >= 50 else None

        if ema20 is None or ema50 is None:
            continue
        if ema20 <= ema50:
            continue  # not in uptrend
        if ema50 > 0:
            actual_spread = (ema20 - ema50) / ema50 * 100
            if actual_spread < ema_spread:
                continue  # trend not strong enough

        if cur < ema20:
            continue  # price must be above EMA20

        # Volume filter
        avg_vol = _avg_volume(volumes)
        today_vol = today.get("volume", 0.0)
        if avg_vol > 0 and today_vol > 0:
            vol_ratio = today_vol / avg_vol
            if vol_ratio < vol_mult:
                continue

        # ATR for dynamic SL/TP
        atr = _atr(highs, lows, closes)

        if atr and atr > 0:
            # SL = current - 1.5 ATR (but not less than percentage-based SL)
            sl_atr   = cur - 1.5 * atr
            sl_pct_v = cur * (1 - sl_pct / 100)
            sl       = round(max(sl_atr, sl_pct_v), 2)
            # TP = current + 3.0 ATR (R:R >= 2:1 guaranteed)
            tp_atr   = cur + 3.0 * atr
            tp_pct_v = cur * (1 + tp_pct / 100)
            target   = round(max(tp_atr, tp_pct_v), 2)
        else:
            sl     = round(cur * (1 - sl_pct / 100), 2)
            target = round(cur * (1 + tp_pct / 100), 2)

        # Signal quality score (0–100): lower RSI + stronger EMA spread + higher vol = better
        if rsi_gate is not None and rsi is not None and rsi_gate > 0:
            rsi_score = max(0, (rsi_gate - rsi) / rsi_gate * 40)
        else:
            rsi_score = 20.0  # no RSI gate → neutral bonus
        ema_score  = min(actual_spread * 5, 30) if ema50 > 0 else 0
        vol_score  = min((vol_ratio - 1) * 10, 20) if avg_vol > 0 and today_vol > 0 else 0
        quality    = round(rsi_score + ema_score + vol_score + 10, 1)  # base 10

        # Map quality → confidence (must pass min_conf gate)
        if quality < min_conf:
            continue

        rr = (target - cur) / max(cur - sl, 0.01)
        if rr < 1.5:
            continue  # skip if risk/reward < 1.5

        signals.append({
            "symbol":      sym,
            "direction":   "Bullish",
            "confidence":  min(quality, 99.0),
            "entry_price": round(cur, 2),
            "stop_loss":   sl,
            "target":      target,
            "rsi":         rsi,
            "ema_spread":  round(actual_spread, 2) if ema50 > 0 else 0.0,
            "rr":          round(rr, 2),
            "atr":         round(atr, 2) if atr else None,
        })

    # Rank by: R:R first, then quality
    signals.sort(key=lambda x: (x["rr"], x["confidence"]), reverse=True)
    return signals[:5]  # top 5 signals per day


# ── Simulate one day ───────────────────────────────────────────────────────

def _simulate_day(
    db: Session,
    portfolio_name: str,
    sim_date: date,
    strategy: StrategyV2,
    today_prices: dict[str, dict],
    history: dict[str, list[dict]],
    portfolio: PaperPortfolio,
    params: dict,
) -> dict:
    """One trading day. Exits first, then enters."""
    opened = []
    closed = []
    max_hold = params["max_hold_days"]
    sl_pct   = params["stop_loss_pct"]
    tp_pct   = params["take_profit_pct"]

    # ── Exits ────────────────────────────────────────────────────
    open_positions = db.query(PaperPosition).filter_by(
        portfolio_name=portfolio_name
    ).all()

    for pos in open_positions:
        today = today_prices.get(pos.symbol)
        if today is None:
            continue
        cur_price  = today["close"]
        hold_days  = (sim_date - pos.entry_date).days
        exit_reason = None

        if cur_price <= pos.stop_loss_price:
            exit_reason = "stop_loss"
        elif cur_price >= pos.target_price:
            exit_reason = "take_profit"
        elif hold_days >= max_hold:
            exit_reason = "max_hold"

        if exit_reason:
            # NSE round-trip cost: pos.entry_price is already the buy-cost-
            # loaded fill (see entry section below); exit_fill nets out the
            # sell-side cost so both gross_pnl/gross_pnl_pct AND the cash
            # credited to the portfolio are honest NSE-cost-adjusted figures,
            # matching strategy_backtester.py's treatment.
            exit_fill = cur_price * (1 - NSE_SELL_COST_PCT)
            pnl     = (exit_fill - pos.entry_price) * pos.shares
            pnl_pct = (exit_fill - pos.entry_price) / pos.entry_price * 100

            db.add(PaperTrade(
                portfolio_name   = portfolio_name,
                symbol           = pos.symbol,
                entry_date       = pos.entry_date,
                exit_date        = sim_date,
                entry_price      = pos.entry_price,
                exit_price       = exit_fill,
                shares           = pos.shares,
                capital_deployed = pos.capital_deployed,
                gross_pnl        = pnl,
                gross_pnl_pct    = pnl_pct,
                direction        = "Bullish",
                exit_reason      = exit_reason,
                is_open          = False,
                holding_days     = hold_days,
                strategy_id      = strategy.strategy_id,
                strategy_name    = strategy.name,
            ))
            portfolio.current_cash += pos.capital_deployed + pnl
            db.delete(pos)
            closed.append({
                "symbol":      pos.symbol,
                "pnl":         round(pnl, 2),
                "pnl_pct":     round(pnl_pct, 2),
                "exit_reason": exit_reason,
            })

    db.flush()

    # ── Entries ───────────────────────────────────────────────────
    open_count = db.query(PaperPosition).filter_by(portfolio_name=portfolio_name).count()
    slots = MAX_OPEN_POSITIONS - open_count

    if slots > 0 and portfolio.current_cash > 3000:
        dsl     = json.loads(strategy.dsl_json or "{}")
        signals = _score_signals(dsl, today_prices, history, params)

        held = {p.symbol for p in db.query(PaperPosition).filter_by(
            portfolio_name=portfolio_name).all()}
        signals = [s for s in signals if s["symbol"] not in held]

        for sig in signals[:slots]:
            # Risk-fixed position sizing: risk 1% of portfolio per trade
            risk_capital   = portfolio.current_cash * (RISK_PER_TRADE_PCT / 100)
            entry          = sig["entry_price"]
            sl_price       = sig["stop_loss"]
            risk_per_share = max(entry - sl_price, entry * 0.01)
            shares         = risk_capital / risk_per_share
            alloc          = shares * entry

            # Cap: max 15% of portfolio per position
            max_alloc = portfolio.current_cash * 0.15
            if alloc > max_alloc:
                alloc  = max_alloc
                shares = alloc / entry

            if alloc < 500 or alloc > portfolio.current_cash:
                continue

            # NSE buy-side cost loaded into the stored cost-basis entry_price
            # (used for PnL/cash accounting) — stop_loss_price/target_price
            # stay computed off the raw signal price so SL/TP still trigger
            # against real market prices, matching strategy_backtester.py.
            entry_fill = entry * (1 + NSE_BUY_COST_PCT)

            db.add(PaperPosition(
                portfolio_name   = portfolio_name,
                symbol           = sig["symbol"],
                entry_date       = sim_date,
                entry_price      = entry_fill,
                shares           = shares,
                capital_deployed = alloc,
                stop_loss_price  = sig["stop_loss"],
                target_price     = sig["target"],
                direction        = "Bullish",
                confidence       = sig["confidence"],
                strategy_id      = strategy.strategy_id,
                strategy_name    = strategy.name,
            ))
            portfolio.current_cash -= alloc
            opened.append(sig["symbol"])

    db.flush()

    # ── Mark to market ─────────────────────────────────────────────
    invested = 0.0
    for pos in db.query(PaperPosition).filter_by(portfolio_name=portfolio_name).all():
        cur = today_prices.get(pos.symbol, {}).get("close", pos.entry_price)
        invested += pos.shares * cur

    total_value = portfolio.current_cash + invested
    portfolio.total_value      = total_value
    portfolio.total_return_pct = (total_value - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100
    if total_value > (portfolio.peak_value or INITIAL_CAPITAL):
        portfolio.peak_value = total_value
    peak = portfolio.peak_value or INITIAL_CAPITAL
    dd   = (total_value - peak) / peak * 100 if peak > 0 else 0.0
    if dd < (portfolio.max_drawdown_pct or 0.0):
        portfolio.max_drawdown_pct = dd

    existing_ec = db.query(EquityCurvePoint).filter_by(
        portfolio_name=portfolio_name, date=sim_date
    ).first()
    if not existing_ec:
        db.add(EquityCurvePoint(
            portfolio_name        = portfolio_name,
            date                  = sim_date,
            total_value           = round(total_value, 2),
            cash                  = round(portfolio.current_cash, 2),
            invested              = round(invested, 2),
            cumulative_return_pct = round(portfolio.total_return_pct, 4),
            drawdown_pct          = round(dd, 4),
            open_positions        = db.query(PaperPosition).filter_by(
                portfolio_name=portfolio_name).count(),
        ))

    try:
        db.commit()
    except IntegrityError:
        # Two concurrent arena cycles replaying the same portfolio_name/date
        # (overlapping hourly job + boot kick, or a rapid restart racing an
        # in-flight run) can both pass the "not existing_ec" check above
        # before either commits — the second commit then hits the
        # (portfolio_name, date) UNIQUE constraint. That's a duplicate write
        # attempt, not a real failure: another writer already recorded this
        # exact point, so roll back and continue rather than aborting the
        # whole arena run for this strategy.
        db.rollback()
        log.warning(
            "Equity curve point for %s/%s already recorded by a concurrent run — skipping duplicate write",
            portfolio_name, sim_date,
        )
    return {
        "date":            str(sim_date),
        "opened":          opened,
        "closed":          closed,
        "portfolio_value": round(total_value, 2),
        "return_pct":      round(portfolio.total_return_pct, 2),
    }


# ── Main replay function ───────────────────────────────────────────────────

def _bucket_trades_by_date(closed_trades, boundary: Optional[date]):
    """Split closed trades into (in_sample, out_of_sample) by exit_date vs boundary.
    If boundary is None, everything is in-sample."""
    if boundary is None:
        return list(closed_trades), []
    is_trades  = [t for t in closed_trades if (t.exit_date or t.entry_date) < boundary]
    oos_trades = [t for t in closed_trades if (t.exit_date or t.entry_date) >= boundary]
    return is_trades, oos_trades


def _grade_trade_set(trades) -> dict:
    if not trades:
        return {"trades": 0, "win_rate": 0.0, "total_return_pct": 0.0}
    wins = [t for t in trades if (t.gross_pnl or 0) > 0]
    total_pnl_pct = sum((t.gross_pnl_pct or 0.0) for t in trades)
    return {
        "trades":           len(trades),
        "win_rate":         round(len(wins) / len(trades) * 100, 1),
        "total_return_pct": round(total_pnl_pct, 2),
    }


def _regime_buckets(daily_results: list[dict]) -> dict[str, dict]:
    """
    Aggregate day-level PnL per regime bucket — used for robustness grading
    (a champion must not be net-negative in any well-sampled regime).
    Regime is tagged per-day already (see _get_regime call in run_replay).
    """
    buckets: dict[str, dict] = {}
    for d in daily_results:
        reg = d.get("regime") or "UNKNOWN"
        b = buckets.setdefault(reg, {"days": 0, "net_pnl": 0.0, "winning_days": 0})
        b["days"] += 1
        b["net_pnl"] += d.get("day_pnl", 0.0)
        if d.get("day_pnl", 0.0) > 0:
            b["winning_days"] += 1
    for reg, b in buckets.items():
        b["net_pnl"] = round(b["net_pnl"], 2)
        b["win_day_rate"] = round(b["winning_days"] / b["days"] * 100, 1) if b["days"] else 0.0
    return buckets


def run_replay(
    db: Session,
    strategy: StrategyV2,
    years: int = REPLAY_YEARS,
    fresh: bool = True,
    oos_months: int = 0,
) -> dict:
    """
    Run full historical replay for a strategy over `years` of data.

    oos_months > 0 additionally splits the SAME single simulation into an
    in-sample segment (everything before the trailing oos_months) and an
    out-of-sample segment (the trailing oos_months) — trades and daily
    results are bucketed by exit date relative to that boundary. This does
    NOT re-run the simulation twice; the strategy trades continuously across
    the full window exactly as before, we just grade the tail separately so
    a strategy can be judged on data its own merge/refinement history never
    "saw the result of" before being graded. Returns include `is_stats` and
    `oos_stats` sub-dicts, plus `regime_buckets` (per-regime day-level PnL,
    for robustness grading) in addition to all pre-existing top-level keys
    (kept unchanged for backward compatibility with existing callers).
    """
    portfolio_name = f"arena_{strategy.strategy_id}"
    log.info("Replay START — %s  portfolio=%s", strategy.name, portfolio_name)

    if fresh:
        _wipe_portfolio(db, portfolio_name)

    portfolio    = _ensure_portfolio(db, portfolio_name)
    trade_dates  = _get_trading_dates(db, years=years)

    if not trade_dates:
        return {"status": "no_price_data", "strategy_id": strategy.strategy_id}

    try:
        dsl = json.loads(strategy.dsl_json or "{}")
    except Exception:
        dsl = {}

    # Pre-fetch all symbols available in the date range
    cutoff = date.today() - timedelta(days=years * 365)
    all_symbols = [
        r[0] for r in db.query(DailyPrice.symbol).filter(
            DailyPrice.date >= cutoff,
            DailyPrice.close.isnot(None),
        ).distinct().all()
    ]
    # Sort for determinism; limit to top 120 most liquid (by data completeness)
    all_symbols = all_symbols[:120]

    daily_results = []
    winning_days  = []
    losing_days   = []
    prev_value    = INITIAL_CAPITAL

    oos_boundary = (date.today() - timedelta(days=oos_months * 30)) if oos_months > 0 else None

    for sim_date in trade_dates:
        # Batch price fetch for all symbols on this date
        today_prices = _batch_prices(db, sim_date)
        active_syms  = list(today_prices.keys())
        if not active_syms:
            continue

        # Fetch lookback history for all active symbols in one query
        history = _batch_history(db, active_syms, end_date=sim_date, lookback=LOOKBACK_DAYS)

        # Resolve regime-aware params
        regime = _get_regime(db, sim_date)
        params = _params_for_regime(dsl, regime)

        try:
            result    = _simulate_day(db, portfolio_name, sim_date, strategy,
                                      today_prices, history, portfolio, params)
            daily_pnl = result["portfolio_value"] - prev_value
            daily_results.append({
                "date":       result["date"],
                "return_pct": result["return_pct"],
                "day_pnl":    round(daily_pnl, 2),
                "opened":     result["opened"],
                "closed":     result["closed"],
                "regime":     regime,
            })

            # A "winning day" = portfolio value rose (even slightly)
            if daily_pnl > 10:        # >₹10 gain
                winning_days.append(result["date"])
            elif daily_pnl < -100:    # >₹100 loss (not just noise)
                losing_days.append(result["date"])

            prev_value = result["portfolio_value"]
        except Exception as exc:
            log.warning("Replay error on %s: %s", sim_date, exc)
            continue

    db.refresh(portfolio)
    closed_trades = db.query(PaperTrade).filter_by(
        portfolio_name=portfolio_name, is_open=False
    ).all()
    winning_trades = [t for t in closed_trades if (t.gross_pnl or 0) > 0]
    win_rate = len(winning_trades) / len(closed_trades) * 100 if closed_trades else 0.0

    is_trades, oos_trades = _bucket_trades_by_date(closed_trades, oos_boundary)
    is_stats  = _grade_trade_set(is_trades)
    oos_stats = _grade_trade_set(oos_trades)
    regime_buckets = _regime_buckets(daily_results)

    log.info(
        "Replay DONE — %s | return=%.1f%% | DD=%.1f%% | trades=%d | wr=%.0f%% | days=%d"
        + (" | IS: %d trades %.0f%%wr | OOS: %d trades %.0f%%wr" if oos_months > 0 else ""),
        *((strategy.name, portfolio.total_return_pct or 0, portfolio.max_drawdown_pct or 0,
           len(closed_trades), win_rate, len(daily_results))
          + ((is_stats["trades"], is_stats["win_rate"], oos_stats["trades"], oos_stats["win_rate"])
             if oos_months > 0 else ())),
    )

    return {
        "strategy_id":            strategy.strategy_id,
        "strategy_name":          strategy.name,
        "portfolio_name":         portfolio_name,
        "total_return_pct":       round(portfolio.total_return_pct or 0, 2),
        "max_drawdown_pct":       round(portfolio.max_drawdown_pct or 0, 2),
        "final_value":            round(portfolio.total_value, 2),
        "total_trades":           len(closed_trades),
        "winning_trades":         len(winning_trades),
        "win_rate":               round(win_rate, 1),
        "trading_days_simulated": len(daily_results),
        "daily_results":          daily_results,
        "winning_days":           winning_days,
        "losing_days":            losing_days,
        "is_stats":               is_stats,
        "oos_stats":              oos_stats,
        "regime_buckets":         regime_buckets,
    }
