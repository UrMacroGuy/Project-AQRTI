"""
Phase 8D — Market Breadth Engine
Computes advance/decline, 52W highs/lows, DMA counts, McClellan oscillator,
breadth thrust, and sector breadth from daily price data.
No scraping needed — computed from AQRTI's own DailyPrice table.
"""

from __future__ import annotations

import sys, os

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import json
import logging
from datetime import date, timedelta
from typing import Any

from sqlalchemy.orm import Session
from sqlalchemy import func

from aqrti.database.models import MarketBreadth, DailyPrice, Stock

logger = logging.getLogger("data_supremacy.breadth")


def compute_breadth(db: Session, target_date: date | None = None) -> dict:
    target = target_date or date.today()

    existing = db.query(MarketBreadth).filter(
        MarketBreadth.breadth_date == target,
        MarketBreadth.universe == "NIFTY500",
    ).first()
    if existing:
        return {"status": "already_exists", "date": str(target)}

    prices_today = db.query(DailyPrice).filter(DailyPrice.date == target).all()
    if not prices_today:
        return {"status": "no_data", "date": str(target)}

    advancing = sum(1 for p in prices_today if p.daily_return and p.daily_return > 0)
    declining  = sum(1 for p in prices_today if p.daily_return and p.daily_return < 0)
    unchanged  = len(prices_today) - advancing - declining
    total      = len(prices_today)
    ad_ratio   = advancing / max(declining, 1)

    # 52-week high/low + MA counts — batch load all history in a single query
    year_ago = target - timedelta(days=365)
    symbols_today = [p.symbol for p in prices_today]
    all_hist = db.query(DailyPrice).filter(
        DailyPrice.symbol.in_(symbols_today),
        DailyPrice.date.between(year_ago, target),
    ).order_by(DailyPrice.symbol.asc(), DailyPrice.date.asc()).all()

    # Group by symbol
    hist_by_sym: dict[str, list] = {}
    for h in all_hist:
        hist_by_sym.setdefault(h.symbol, []).append(h)

    today_by_sym = {p.symbol: p for p in prices_today}

    new_highs = 0
    new_lows  = 0
    above_20  = 0
    above_50  = 0
    above_200 = 0

    for symbol, hist in hist_by_sym.items():
        p = today_by_sym.get(symbol)
        if p is None:
            continue
        closes = [h.close for h in hist if h.close]
        if not closes:
            continue

        yr_high = max(closes)
        yr_low  = min(closes)
        if p.close and p.close >= yr_high * 0.995:
            new_highs += 1
        if p.close and p.close <= yr_low * 1.005:
            new_lows += 1

        def _sma(n, c=closes):
            return sum(c[-n:]) / n if len(c) >= n else None

        ma20  = _sma(20)
        ma50  = _sma(50)
        ma200 = _sma(200)
        if ma20  and p.close and p.close > ma20:  above_20  += 1
        if ma50  and p.close and p.close > ma50:  above_50  += 1
        if ma200 and p.close and p.close > ma200: above_200 += 1

    # McClellan oscillator (simplified: 19-day EMA(A-D) - 39-day EMA(A-D))
    mcclellan = _compute_mcclellan(db, target)

    # Breadth thrust (Zweig): 10-day EMA of advancing/total > 0.615
    thrust = _compute_breadth_thrust(db, target)

    # Sector breadth
    sector_breadth = _compute_sector_breadth(db, target)

    signal = _breadth_signal(ad_ratio, above_200 / max(total, 1) * 100)

    row = MarketBreadth(
        breadth_date          = target,
        universe              = "NIFTY500",
        total_stocks          = total,
        advancing             = advancing,
        declining             = declining,
        unchanged             = unchanged,
        advance_decline_ratio = round(ad_ratio, 4),
        new_52w_high          = new_highs,
        new_52w_low           = new_lows,
        above_ma20            = above_20,
        above_ma50            = above_50,
        above_ma200           = above_200,
        mcclellan_osc         = mcclellan,
        breadth_thrust        = thrust,
        sector_breadth_json   = json.dumps(sector_breadth),
        breadth_signal        = signal,
    )
    db.add(row)
    db.commit()

    return {
        "status":    "computed",
        "date":      str(target),
        "total":     total,
        "advancing": advancing,
        "declining": declining,
        "ad_ratio":  round(ad_ratio, 4),
        "new_highs": new_highs,
        "new_lows":  new_lows,
        "signal":    signal,
    }


def _compute_mcclellan(db: Session, target: date) -> float | None:
    try:
        past_days = []
        for i in range(39):
            d = target - timedelta(days=i)
            prices = db.query(DailyPrice).filter(DailyPrice.date == d).all()
            if prices:
                adv = sum(1 for p in prices if p.daily_return and p.daily_return > 0)
                dec = sum(1 for p in prices if p.daily_return and p.daily_return < 0)
                past_days.append(adv - dec)
        if len(past_days) < 10:
            return None
        def _ema(data, period):
            k = 2 / (period + 1)
            ema = data[0]
            for v in data[1:]:
                ema = v * k + ema * (1 - k)
            return ema
        past_days = list(reversed(past_days))
        ema19 = _ema(past_days[-19:], 19)
        ema39 = _ema(past_days, 39)
        return round(ema19 - ema39, 2)
    except Exception:
        return None


def _compute_breadth_thrust(db: Session, target: date) -> float | None:
    try:
        vals = []
        for i in range(10):
            d = target - timedelta(days=i)
            prices = db.query(DailyPrice).filter(DailyPrice.date == d).all()
            if prices:
                adv = sum(1 for p in prices if p.daily_return and p.daily_return > 0)
                total = len(prices)
                vals.append(adv / total if total else 0)
        if not vals:
            return None
        # 10-day EMA of (adv/total)
        k = 2 / 11
        ema = vals[-1]
        for v in reversed(vals[:-1]):
            ema = v * k + ema * (1 - k)
        return round(ema, 4)
    except Exception:
        return None


def _compute_sector_breadth(db: Session, target: date) -> dict:
    try:
        stocks = db.query(Stock).filter(Stock.active == True).all()
        sector_map: dict[str, str] = {s.symbol: (s.sector or "Unknown") for s in stocks}

        prices = db.query(DailyPrice).filter(DailyPrice.date == target).all()
        sectors: dict[str, dict] = {}
        for p in prices:
            sector = sector_map.get(p.symbol, "Unknown")
            if sector not in sectors:
                sectors[sector] = {"adv": 0, "dec": 0, "total": 0}
            sectors[sector]["total"] += 1
            if p.daily_return and p.daily_return > 0:
                sectors[sector]["adv"] += 1
            elif p.daily_return and p.daily_return < 0:
                sectors[sector]["dec"] += 1

        return {
            s: {
                "advancing": d["adv"],
                "declining": d["dec"],
                "ratio":     round(d["adv"] / max(d["dec"], 1), 2),
            }
            for s, d in sectors.items()
        }
    except Exception:
        return {}


def _breadth_signal(ad_ratio: float, pct_above_200: float) -> str:
    if ad_ratio >= 2.5 and pct_above_200 >= 60:
        return "STRONG_BULL"
    if ad_ratio >= 1.5 and pct_above_200 >= 45:
        return "BULL"
    if ad_ratio <= 0.4 and pct_above_200 <= 30:
        return "STRONG_BEAR"
    if ad_ratio <= 0.7 and pct_above_200 <= 40:
        return "BEAR"
    return "NEUTRAL"


def get_breadth_latest(db: Session) -> dict | None:
    row = db.query(MarketBreadth).order_by(MarketBreadth.breadth_date.desc()).first()
    if not row:
        return None
    return _to_dict(row)


def get_breadth_history(db: Session, days: int = 30) -> list[dict]:
    cutoff = date.today() - timedelta(days=days)
    rows = db.query(MarketBreadth).filter(
        MarketBreadth.breadth_date >= cutoff
    ).order_by(MarketBreadth.breadth_date.asc()).all()
    return [_to_dict(r) for r in rows]


def _to_dict(r: MarketBreadth) -> dict:
    try:
        sector_breadth = json.loads(r.sector_breadth_json) if r.sector_breadth_json else {}
    except Exception:
        sector_breadth = {}
    return {
        "breadth_date":         str(r.breadth_date),
        "universe":             r.universe,
        "total_stocks":         r.total_stocks,
        "advancing":            r.advancing,
        "declining":            r.declining,
        "unchanged":            r.unchanged,
        "advance_decline_ratio":r.advance_decline_ratio,
        "new_52w_high":         r.new_52w_high,
        "new_52w_low":          r.new_52w_low,
        "above_ma20":           r.above_ma20,
        "above_ma50":           r.above_ma50,
        "above_ma200":          r.above_ma200,
        "mcclellan_osc":        r.mcclellan_osc,
        "breadth_thrust":       r.breadth_thrust,
        "breadth_signal":       r.breadth_signal,
        "sector_breadth":       sector_breadth,
    }
