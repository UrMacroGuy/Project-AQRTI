"""Equity Screener API — /api/v1/screener"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from aqrti.database.engine import get_db_dependency
from aqrti.database.models import DailyPrice
from aqrti.data.market_data import STOCK_META
from aqrti.config.settings import get_settings

router = APIRouter()


# ── Technical Indicator Helpers ──────────────────────────────────

def _compute_rsi(closes: list[float], period: int = 14) -> float:
    """Compute RSI from a list of closing prices (oldest first)."""
    if len(closes) < period + 1:
        return 50.0
    # Use the last period+1 closes
    relevant = closes[-(period + 1):]
    gains = []
    losses = []
    for i in range(1, len(relevant)):
        diff = relevant[i] - relevant[i - 1]
        if diff > 0:
            gains.append(diff)
            losses.append(0.0)
        else:
            gains.append(0.0)
            losses.append(abs(diff))
    avg_gain = sum(gains) / period if gains else 0.0
    avg_loss = sum(losses) / period if losses else 0.0
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100.0 - (100.0 / (1.0 + rs)), 2)


def _compute_ema(closes: list[float], period: int) -> float:
    """Compute EMA from a list of closes (oldest first) using standard formula."""
    if not closes:
        return 0.0
    if len(closes) < period:
        return closes[-1]
    k = 2.0 / (period + 1)
    ema = closes[0]
    for price in closes[1:]:
        ema = price * k + ema * (1 - k)
    return round(ema, 2)


def _compute_signal(rsi: float, above_ema20: bool) -> str:
    if rsi > 55 and above_ema20:
        return "bullish"
    elif rsi < 45 and not above_ema20:
        return "bearish"
    else:
        return "neutral"


def _compute_score(rsi: float, above_ema20: bool, above_ema50: bool, volume_ratio: float) -> float:
    """0-100 composite: RSI momentum 40%, trend alignment 30%, volume confirmation 30%."""
    # RSI momentum (0-40): higher RSI = more momentum up to 70; penalise extremes
    rsi_score = 0.0
    if rsi <= 100:
        if rsi >= 50:
            # 50→70 maps 0→40; cap at 70
            rsi_score = min(40.0, (rsi - 50) / 20.0 * 40.0)
        else:
            # 50→30 maps 0→-20 but floored at 0
            rsi_score = max(0.0, (rsi - 30) / 20.0 * 20.0)

    # Trend alignment (0-30)
    trend_score = 0.0
    if above_ema20:
        trend_score += 15.0
    if above_ema50:
        trend_score += 15.0

    # Volume confirmation (0-30): vol_ratio 1.5x = full marks; scales linearly
    vol_score = min(30.0, (volume_ratio / 1.5) * 30.0)

    return round(min(100.0, rsi_score + trend_score + vol_score), 1)


# ── Main Screener Endpoint ───────────────────────────────────────

@router.get("")
def screen_stocks(
    min_rsi:        Optional[float] = Query(None),
    max_rsi:        Optional[float] = Query(None),
    min_pe:         Optional[float] = Query(None),
    max_pe:         Optional[float] = Query(None),
    min_change_pct: Optional[float] = Query(None),
    max_change_pct: Optional[float] = Query(None),
    min_volume_ratio: Optional[float] = Query(None),
    above_ema20:    Optional[bool]  = Query(None),
    above_ema50:    Optional[bool]  = Query(None),
    sector:         Optional[str]   = Query(None),
    signal:         Optional[str]   = Query(None),  # bullish/bearish/neutral/all
    db: Session = Depends(get_db_dependency),
):
    settings = get_settings()
    symbols = list(STOCK_META.keys())

    # We need at least 52w of daily data — fetch last 260 trading days worth
    cutoff = date.today() - timedelta(days=380)
    results = []

    for symbol in symbols:
        try:
            meta = STOCK_META.get(symbol, {})
            sym_sector = meta.get("sector", "")
            sym_name   = meta.get("name", symbol)

            # Sector filter early-out
            if sector and sym_sector.lower() != sector.lower():
                continue

            rows = (
                db.query(DailyPrice.date, DailyPrice.close, DailyPrice.volume, DailyPrice.daily_return)
                .filter(DailyPrice.symbol == symbol, DailyPrice.date >= cutoff)
                .order_by(DailyPrice.date.asc())
                .all()
            )

            if len(rows) < 5:
                continue

            closes  = [r[1] for r in rows if r[1] is not None]
            volumes = [r[2] for r in rows if r[2] is not None]

            if len(closes) < 2:
                continue

            last_close  = closes[-1]
            prev_close  = closes[-2]
            change_pct  = ((last_close - prev_close) / prev_close * 100) if prev_close else 0.0

            # RSI (14-period)
            rsi = _compute_rsi(closes, period=14)

            # EMA20 and EMA50
            ema20 = _compute_ema(closes, period=20)
            ema50 = _compute_ema(closes, period=50)
            is_above_ema20 = last_close > ema20
            is_above_ema50 = last_close > ema50

            # Volume ratio = last vol / avg of last 20 vols
            last_vol = volumes[-1] if volumes else 0.0
            avg20_vol = sum(volumes[-20:]) / len(volumes[-20:]) if len(volumes) >= 2 else last_vol
            volume_ratio = (last_vol / avg20_vol) if avg20_vol > 0 else 1.0

            # 52-week high/low
            closes_52w = closes[-252:] if len(closes) >= 252 else closes
            week52_high = max(closes_52w)
            week52_low  = min(closes_52w)
            pct_from_52h = ((last_close - week52_high) / week52_high * 100) if week52_high else 0.0

            # Signal + score
            sig   = _compute_signal(rsi, is_above_ema20)
            score = _compute_score(rsi, is_above_ema20, is_above_ema50, volume_ratio)

            # ── Apply filters ───────────────────────────────────
            if min_rsi is not None and rsi < min_rsi:
                continue
            if max_rsi is not None and rsi > max_rsi:
                continue
            if min_change_pct is not None and change_pct < min_change_pct:
                continue
            if max_change_pct is not None and change_pct > max_change_pct:
                continue
            if min_volume_ratio is not None and volume_ratio < min_volume_ratio:
                continue
            if above_ema20 is not None and is_above_ema20 != above_ema20:
                continue
            if above_ema50 is not None and is_above_ema50 != above_ema50:
                continue
            if signal and signal != "all" and sig != signal:
                continue

            results.append({
                "symbol":       symbol,
                "name":         sym_name,
                "sector":       sym_sector,
                "price":        round(last_close, 2),
                "change_pct":   round(change_pct, 2),
                "rsi":          rsi,
                "ema20":        ema20,
                "ema50":        ema50,
                "above_ema20":  is_above_ema20,
                "above_ema50":  is_above_ema50,
                "volume_ratio": round(volume_ratio, 3),
                "week52_high":  round(week52_high, 2),
                "week52_low":   round(week52_low, 2),
                "pct_from_52h": round(pct_from_52h, 2),
                "signal":       sig,
                "score":        score,
            })

        except Exception:
            continue

    # Sort by score descending
    results.sort(key=lambda x: x["score"], reverse=True)

    return {"stocks": results, "total": len(results)}


# ── Presets Endpoint ─────────────────────────────────────────────

@router.get("/presets")
def get_screener_presets():
    presets = [
        {
            "name": "Momentum Breakout",
            "description": "RSI > 60, above EMA20, volume > 1.5x average",
            "filters": {
                "min_rsi": 60,
                "above_ema20": True,
                "min_volume_ratio": 1.5,
            },
        },
        {
            "name": "Oversold Bounce",
            "description": "RSI < 35 — potentially oversold stocks",
            "filters": {
                "max_rsi": 35,
            },
        },
        {
            "name": "52W High Hunters",
            "description": "Stocks within 3% of their 52-week high",
            "filters": {
                "min_change_pct": -3,
            },
        },
        {
            "name": "Value Dip",
            "description": "RSI 40–55, below EMA50 — pullback in uptrend",
            "filters": {
                "min_rsi": 40,
                "max_rsi": 55,
                "above_ema50": False,
            },
        },
        {
            "name": "Strong Trend",
            "description": "Above both EMA20 and EMA50 — confirmed uptrend",
            "filters": {
                "above_ema20": True,
                "above_ema50": True,
            },
        },
    ]
    return {"presets": presets}
