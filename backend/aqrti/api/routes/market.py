"""Market Intelligence API — /api/v1/market"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from aqrti.database.engine import get_db_dependency
from aqrti.database.models import DailyPrice, IndexData
from aqrti.data.market_data import (
    get_latest_index,
    get_index_history,
    get_latest_prices,
    STOCK_META,
)
from aqrti.config.settings import get_settings

router = APIRouter()


def _sector_strength(db: Session, symbols: list[str]) -> list[dict]:
    """
    Compute sector strength score for each sector in the universe.
    Score = average of (30d RS + 14d momentum + last 1d return rescaled to 0-100).
    """
    sector_data: dict[str, list[float]] = {}

    for symbol in symbols:
        meta = STOCK_META.get(symbol)
        if not meta:
            continue
        sector = meta["sector"]

        cutoff = date.today() - timedelta(days=30)
        rows = (
            db.query(DailyPrice.close, DailyPrice.daily_return)
            .filter(DailyPrice.symbol == symbol, DailyPrice.date >= cutoff)
            .order_by(DailyPrice.date.asc())
            .all()
        )
        if len(rows) < 5:
            continue

        closes  = [r[0] for r in rows if r[0]]
        returns = [r[1] for r in rows if r[1] is not None]

        # 30-day cumulative return (0-100 normalized)
        if len(closes) >= 2 and closes[0]:
            cum_ret = (closes[-1] - closes[0]) / closes[0] * 100
        else:
            cum_ret = 0.0

        # Avg return last 5 days
        momentum = sum(returns[-5:]) / 5 if len(returns) >= 5 else 0.0

        # Simple composite: shift to 0-100 range
        score = 50 + cum_ret * 2 + momentum * 3
        score = max(0, min(100, score))

        sector_data.setdefault(sector, []).append(score)

    result = []
    for sector, scores in sector_data.items():
        avg_score = round(sum(scores) / len(scores), 1)
        result.append({
            "name":     sector,
            "score":    avg_score,
            "rs":       min(100, round(avg_score * 1.05, 1)),
            "momentum": min(100, round(avg_score * 0.95, 1)),
        })

    result.sort(key=lambda x: x["score"], reverse=True)
    return result


@router.get("")
def get_market(db: Session = Depends(get_db_dependency)):
    settings = get_settings()
    symbols  = settings.universe_clean

    nifty     = get_latest_index(db, "NIFTY50")
    banknifty = get_latest_index(db, "BANKNIFTY")

    # Top movers: stocks with highest absolute daily return today
    latest_prices = get_latest_prices(db, symbols)
    movers = sorted(
        [
            {
                "symbol":  sym,
                "sector":  STOCK_META.get(sym, {}).get("sector", ""),
                "price":   data["close"],
                "change":  data["daily_return"],
                "direction": "up" if (data["daily_return"] or 0) >= 0 else "down",
            }
            for sym, data in latest_prices.items()
            if data.get("daily_return") is not None
        ],
        key=lambda x: abs(x["change"]),
        reverse=True,
    )[:10]

    sector_strength = _sector_strength(db, symbols)

    return {
        "indices": {
            "nifty50":   {
                "value":     nifty["close"]   if nifty else None,
                "returns":   nifty["returns"] if nifty else None,
                "date":      nifty["date"]    if nifty else None,
            },
            "banknifty": {
                "value":     banknifty["close"]   if banknifty else None,
                "returns":   banknifty["returns"] if banknifty else None,
                "date":      banknifty["date"]    if banknifty else None,
            },
        },
        "sectorStrength": sector_strength,
        "topMovers":      movers,
        "lastUpdated":    str(date.today()),
    }


_LIVE_INDEX_MAP = {
    "nifty50":   ("^NSEI",    "Nifty 50"),
    "sensex":    ("^BSESN",   "Sensex"),
    "banknifty": ("^NSEBANK", "Bank Nifty"),
    "niftyit":   ("^CNXIT",   "Nifty IT"),
    "vix":       ("^INDIAVIX","India VIX"),
    "usdinr":    ("USDINR=X", "USD/INR"),
    "gold":      ("GC=F",     "Gold (USD)"),
    "crude":     ("CL=F",     "Crude Oil"),
}

# Topbar needs only these 4 — fetched fast, cached for 4 seconds
_TOPBAR_MAP = {
    "nifty50":   ("^NSEI",    "Nifty 50"),
    "banknifty": ("^NSEBANK", "Bank Nifty"),
    "vix":       ("^INDIAVIX","India VIX"),
    "usdinr":    ("USDINR=X", "USD/INR"),
}

import time as _time
_topbar_cache: dict = {"ts": 0, "data": None}
_TOPBAR_TTL = 4  # seconds — matches 5s frontend poll with 1s buffer


def _fetch_price(key: str, sym: str, label: str) -> dict:
    """Fetch a single live price with fast_info → 1m history fallback."""
    try:
        import yfinance as yf
        ticker = yf.Ticker(sym)
        price, prev = None, None

        try:
            fi = ticker.fast_info
            price = getattr(fi, "last_price", None)
            prev  = getattr(fi, "previous_close", None)
            if price is not None:
                price = float(price)
            if prev is not None:
                prev = float(prev)
        except Exception:
            pass

        if price is None:
            hist = ticker.history(period="2d", interval="1m", auto_adjust=True)
            if not hist.empty:
                price = float(hist["Close"].iloc[-1])
                today = hist.index[-1].date()
                prior = hist[hist.index.date < today]
                prev = float(prior["Close"].iloc[-1]) if not prior.empty else None

        if price is None:
            raise ValueError("no price")

        if prev is None:
            daily = ticker.history(period="5d", interval="1d", auto_adjust=True)
            if len(daily) >= 2:
                prev = float(daily["Close"].iloc[-2])
            elif len(daily) == 1:
                prev = float(daily["Open"].iloc[-1])

        change     = (price - prev) if prev else 0.0
        change_pct = (change / prev * 100) if prev else 0.0
        return {
            "key":       key,
            "label":     label,
            "price":     round(price, 2),
            "prev":      round(prev, 2) if prev else None,
            "change":    round(change, 2),
            "changePct": round(change_pct, 2),
        }
    except Exception:
        return {"key": key, "label": label, "price": None, "prev": None, "change": None, "changePct": None}


def _fetch_parallel(index_map: dict, timeout: int = 12) -> list:
    from concurrent.futures import ThreadPoolExecutor, as_completed
    items = list(index_map.items())
    results_by_key = {}
    with ThreadPoolExecutor(max_workers=len(items)) as pool:
        futures = {pool.submit(_fetch_price, key, sym, label): key for key, (sym, label) in items}
        for fut in as_completed(futures, timeout=timeout):
            r = fut.result()
            results_by_key[r["key"]] = r
    return [results_by_key.get(key, {"key": key, "label": label, "price": None, "prev": None, "change": None, "changePct": None})
            for key, (sym, label) in items]


@router.get("/topbar")
def get_topbar_prices():
    """Fast endpoint: only the 4 topbar symbols, server-side cached for 4s."""
    global _topbar_cache
    try:
        import yfinance  # noqa — confirm installed
    except ImportError:
        raise HTTPException(status_code=503, detail="yfinance not installed")

    now = _time.time()
    if _topbar_cache["data"] and (now - _topbar_cache["ts"]) < _TOPBAR_TTL:
        return _topbar_cache["data"]

    data = _fetch_parallel(_TOPBAR_MAP, timeout=12)
    _topbar_cache = {"ts": now, "data": data}
    return data


_NSE_STOCKS_MAP = {
    "RELIANCE":   ("RELIANCE.NS",   "Reliance"),
    "HDFCBANK":   ("HDFCBANK.NS",   "HDFC Bank"),
    "ICICIBANK":  ("ICICIBANK.NS",  "ICICI Bank"),
    "INFY":       ("INFY.NS",       "Infosys"),
    "TCS":        ("TCS.NS",        "TCS"),
    "AXISBANK":   ("AXISBANK.NS",   "Axis Bank"),
    "SBIN":       ("SBIN.NS",       "SBI"),
    "BAJFINANCE": ("BAJFINANCE.NS", "Bajaj Finance"),
    "MARUTI":     ("MARUTI.NS",     "Maruti"),
    "TITAN":      ("TITAN.NS",      "Titan"),
    "WIPRO":      ("WIPRO.NS",      "Wipro"),
    "ONGC":       ("ONGC.NS",       "ONGC"),
    "SUNPHARMA":  ("SUNPHARMA.NS",  "Sun Pharma"),
    "NESTLEIND":  ("NESTLEIND.NS",  "Nestle"),
    "BHARTIARTL": ("BHARTIARTL.NS", "Bharti Airtel"),
    "KOTAKBANK":  ("KOTAKBANK.NS",  "Kotak Bank"),
    "TATASTEEL":  ("TATASTEEL.NS",  "Tata Steel"),
    "HINDALCO":   ("HINDALCO.NS",   "Hindalco"),
}

_stocks_cache: dict = {"ts": 0, "data": None}
_STOCKS_TTL = 60  # 60s — live price cache for stocks


@router.get("/live/stocks")
def get_live_stock_prices():
    """Live prices for all 18 NSE stocks in the universe (60s server-side cache)."""
    now = _time.time()
    if _stocks_cache["data"] and (now - _stocks_cache["ts"]) < _STOCKS_TTL:
        return _stocks_cache["data"]
    try:
        import yfinance  # noqa
    except ImportError:
        raise HTTPException(status_code=503, detail="yfinance not installed")

    data = _fetch_parallel(_NSE_STOCKS_MAP, timeout=25)
    _stocks_cache["ts"]   = now
    _stocks_cache["data"] = data
    return data


@router.get("/live")
def get_live_prices():
    """Fetch real-time prices for all 8 symbols via yfinance (parallel)."""
    try:
        import yfinance  # noqa
    except ImportError:
        raise HTTPException(status_code=503, detail="yfinance not installed")

    return _fetch_parallel(_LIVE_INDEX_MAP, timeout=20)


@router.get("/history/{index_name}")
def get_index_history_route(
    index_name: str,
    days: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(get_db_dependency),
):
    return get_index_history(db, index_name, days)
