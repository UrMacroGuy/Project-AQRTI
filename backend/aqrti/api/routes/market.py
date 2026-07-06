"""Market Intelligence API — /api/v1/market"""

from __future__ import annotations

from contextlib import redirect_stderr
from datetime import date, timedelta
from io import StringIO
import threading
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
_YF_LIVE_LOCK = threading.Lock()


def _latest_stock_quote(db: Session, symbol: str, label: str) -> dict:
    rows = (
        db.query(DailyPrice.close, DailyPrice.date)
        .filter(DailyPrice.symbol == symbol)
        .order_by(DailyPrice.date.desc())
        .limit(2)
        .all()
    )
    if not rows:
        return {"key": symbol, "label": label, "price": None, "prev": None, "change": None, "changePct": None}
    price = float(rows[0][0] or 0.0)
    prev = float(rows[1][0] or 0.0) if len(rows) > 1 and rows[1][0] else None
    change = (price - prev) if prev else 0.0
    change_pct = (change / prev * 100) if prev else 0.0
    return {
        "key": symbol,
        "label": label,
        "price": round(price, 2),
        "prev": round(prev, 2) if prev else None,
        "change": round(change, 2),
        "changePct": round(change_pct, 2),
        "source": "database",
        "asOf": str(rows[0][1]),
    }


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

    if nifty is None and banknifty is None:
        return {"error": "No data available"}

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
            yf_stderr = StringIO()
            with _YF_LIVE_LOCK, redirect_stderr(yf_stderr):
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
            yf_stderr = StringIO()
            with _YF_LIVE_LOCK, redirect_stderr(yf_stderr):
                hist = ticker.history(period="2d", interval="1m", auto_adjust=True)
            if not hist.empty:
                price = float(hist["Close"].iloc[-1])
                today = hist.index[-1].date()
                prior = hist[hist.index.date < today]
                prev = float(prior["Close"].iloc[-1]) if not prior.empty else None

        if price is None:
            raise ValueError("no price")

        if prev is None:
            yf_stderr = StringIO()
            with _YF_LIVE_LOCK, redirect_stderr(yf_stderr):
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
            "source":    "yfinance",
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
def get_live_stock_prices(db: Session = Depends(get_db_dependency)):
    """Live prices for all 18 NSE stocks in the universe (60s server-side cache)."""
    now = _time.time()
    if _stocks_cache["data"] and (now - _stocks_cache["ts"]) < _STOCKS_TTL:
        return _stocks_cache["data"]
    try:
        import yfinance  # noqa
    except ImportError:
        raise HTTPException(status_code=503, detail="yfinance not installed")

    data = _fetch_parallel(_NSE_STOCKS_MAP, timeout=25)
    data = [
        item if item.get("price") is not None else _latest_stock_quote(db, item["key"], item["label"])
        for item in data
    ]
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


def _ema(values: list, period: int) -> list:
    """Compute EMA with None-padding for warmup. Returns list same length as values."""
    result = [None] * len(values)
    k = 2.0 / (period + 1)
    ema_val = None
    for i, v in enumerate(values):
        if v is None:
            continue
        if ema_val is None:
            ema_val = v
        else:
            ema_val = v * k + ema_val * (1 - k)
        result[i] = round(ema_val, 4)
    return result


def _compute_indicators(closes: list) -> dict:
    """Compute all technical indicators from a list of close prices."""
    n = len(closes)

    # EMA20 and EMA50
    ema20 = _ema(closes, 20)
    ema50 = _ema(closes, 50)

    # Bollinger Bands (20-period SMA ± 2 std dev)
    bb_upper = [None] * n
    bb_lower = [None] * n
    bb_mid   = [None] * n
    for i in range(19, n):
        window = [c for c in closes[i-19:i+1] if c is not None]
        if len(window) < 20:
            continue
        mean = sum(window) / 20
        variance = sum((x - mean) ** 2 for x in window) / 20
        std = variance ** 0.5
        bb_mid[i]   = round(mean, 4)
        bb_upper[i] = round(mean + 2 * std, 4)
        bb_lower[i] = round(mean - 2 * std, 4)

    # RSI (14-period Wilder's)
    rsi = [None] * n
    if n >= 15:
        gains, losses = [], []
        for i in range(1, n):
            if closes[i] is None or closes[i-1] is None:
                continue
            diff = closes[i] - closes[i-1]
            gains.append(max(diff, 0))
            losses.append(max(-diff, 0))
        if len(gains) >= 14:
            avg_gain = sum(gains[:14]) / 14
            avg_loss = sum(losses[:14]) / 14
            # First RSI value at index 14
            offset = 0
            for i in range(1, n):
                if closes[i] is None or closes[i-1] is None:
                    continue
                if offset < 14:
                    offset += 1
                    continue
                if avg_loss == 0:
                    rsi[i] = 100.0
                else:
                    rs = avg_gain / avg_loss
                    rsi[i] = round(100 - (100 / (1 + rs)), 2)
                diff = closes[i] - closes[i-1]
                avg_gain = (avg_gain * 13 + max(diff, 0)) / 14
                avg_loss = (avg_loss * 13 + max(-diff, 0)) / 14

    # MACD: EMA12 - EMA26, signal = EMA9 of MACD, hist = MACD - signal
    ema12 = _ema(closes, 12)
    ema26 = _ema(closes, 26)
    macd_line = [
        round(e12 - e26, 4) if e12 is not None and e26 is not None else None
        for e12, e26 in zip(ema12, ema26)
    ]
    signal_line = _ema(macd_line, 9)
    macd_hist = [
        round(m - s, 4) if m is not None and s is not None else None
        for m, s in zip(macd_line, signal_line)
    ]

    return {
        "ema20":       ema20,
        "ema50":       ema50,
        "bb_upper":    bb_upper,
        "bb_lower":    bb_lower,
        "bb_mid":      bb_mid,
        "rsi":         rsi,
        "macd":        macd_line,
        "macd_signal": signal_line,
        "macd_hist":   macd_hist,
    }


def _pearson(xs, ys):
    n = len(xs)
    if n < 5:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = sum((x - mx) ** 2 for x in xs) ** 0.5
    dy = sum((y - my) ** 2 for y in ys) ** 0.5
    if dx == 0 or dy == 0:
        return None
    return round(num / (dx * dy), 3)


@router.get("/correlation")
def get_correlation_matrix(
    days: int = Query(default=60, ge=1, le=180),
    db: Session = Depends(get_db_dependency),
):
    """Return Pearson correlation matrix of daily returns for all 18 NSE stocks."""
    from aqrti.config.settings import get_settings
    settings = get_settings()
    symbols = settings.universe_clean

    cutoff = date.today() - timedelta(days=days + 5)  # +5 for weekend buffer
    rows = (
        db.query(DailyPrice.symbol, DailyPrice.date, DailyPrice.close)
        .filter(DailyPrice.symbol.in_(symbols), DailyPrice.date >= cutoff)
        .order_by(DailyPrice.symbol.asc(), DailyPrice.date.asc())
        .all()
    )

    # Build {symbol: [close, ...]} dict sorted by date
    from collections import defaultdict
    price_map: dict[str, list] = defaultdict(list)
    for r in rows:
        if r.close is not None:
            price_map[r.symbol].append(float(r.close))

    # Compute returns for each symbol
    def _returns(closes):
        if len(closes) < 2:
            return []
        result = []
        for i in range(1, len(closes)):
            prev = closes[i - 1]
            if prev == 0:
                result.append(0.0)
            else:
                result.append((closes[i] - prev) / prev)
        return result

    returns_map: dict[str, list] = {}
    for sym in symbols:
        closes = price_map.get(sym, [])
        rets = _returns(closes)
        returns_map[sym] = rets if len(rets) >= 10 else []

    # Build matrix
    n = len(symbols)
    matrix = []
    for i, sym_i in enumerate(symbols):
        row = []
        for j, sym_j in enumerate(symbols):
            if i == j:
                row.append(1.0)
            elif not returns_map[sym_i] or not returns_map[sym_j]:
                row.append(None)
            else:
                xs = returns_map[sym_i]
                ys = returns_map[sym_j]
                # Align to common length
                min_len = min(len(xs), len(ys))
                row.append(_pearson(xs[-min_len:], ys[-min_len:]))
        matrix.append(row)

    return {"symbols": symbols, "matrix": matrix, "days": days}


@router.get("/breadth/by-sector")
def get_sector_breadth(db: Session = Depends(get_db_dependency)):
    """Return % of stocks above 20MA, 50MA, 200MA per sector."""
    from aqrti.config.settings import get_settings
    settings = get_settings()
    symbols = settings.universe_clean

    cutoff = date.today() - timedelta(days=210)  # ~200 trading + buffer
    rows = (
        db.query(DailyPrice.symbol, DailyPrice.date, DailyPrice.close)
        .filter(DailyPrice.symbol.in_(symbols), DailyPrice.date >= cutoff)
        .order_by(DailyPrice.symbol.asc(), DailyPrice.date.asc())
        .all()
    )

    from collections import defaultdict
    price_map: dict[str, list] = defaultdict(list)
    for r in rows:
        if r.close is not None:
            price_map[r.symbol].append(float(r.close))

    def _sma(closes, period):
        if len(closes) < period:
            return None
        return sum(closes[-period:]) / period

    # Build sector → stocks mapping
    sector_map: dict[str, list] = defaultdict(list)
    for sym in symbols:
        meta = STOCK_META.get(sym)
        if meta:
            sector_map[meta["sector"]].append(sym)

    sectors_result = []
    for sector_name, sector_syms in sorted(sector_map.items()):
        stocks_data = []
        above_20_count = 0
        above_50_count = 0
        above_200_count = 0
        valid_20 = 0
        valid_50 = 0
        valid_200 = 0

        for sym in sector_syms:
            closes = price_map.get(sym, [])
            if len(closes) < 2:
                stocks_data.append({"symbol": sym, "above_20": None, "above_50": None, "above_200": None})
                continue

            latest = closes[-1]
            sma20  = _sma(closes, 20)
            sma50  = _sma(closes, 50)
            sma200 = _sma(closes, 200)

            above_20  = (latest > sma20)  if sma20  is not None else None
            above_50  = (latest > sma50)  if sma50  is not None else None
            above_200 = (latest > sma200) if sma200 is not None else None

            if above_20 is not None:
                valid_20 += 1
                if above_20:
                    above_20_count += 1
            if above_50 is not None:
                valid_50 += 1
                if above_50:
                    above_50_count += 1
            if above_200 is not None:
                valid_200 += 1
                if above_200:
                    above_200_count += 1

            stocks_data.append({
                "symbol":    sym,
                "above_20":  above_20,
                "above_50":  above_50,
                "above_200": above_200,
            })

        sectors_result.append({
            "name":           sector_name,
            "stocks_total":   len(sector_syms),
            "above_20ma_pct": round(above_20_count / valid_20 * 100, 1) if valid_20 else 0.0,
            "above_50ma_pct": round(above_50_count / valid_50 * 100, 1) if valid_50 else 0.0,
            "above_200ma_pct": round(above_200_count / valid_200 * 100, 1) if valid_200 else 0.0,
            "stocks":         stocks_data,
        })

    return {"sectors": sectors_result}


@router.post("/backfill/bhavcopy")
def trigger_bhavcopy_backfill(
    years: int = Query(default=2, ge=1, le=5),
    db: Session = Depends(get_db_dependency),
):
    """
    Trigger NSE Bhavcopy historical backfill.
    Downloads daily bhavcopies (OHLCV + delivery volume) from NSE archives.
    years=2 fills last 2 years; years=5 fills full 5Y history (~1200 days, ~30 min).
    Runs in background thread — returns immediately with job status.
    """
    import threading
    from datetime import date, timedelta
    from data_supremacy.bhavcopy_scraper import run_historical_backfill

    from_date = date.today() - timedelta(days=365 * years)
    to_date   = date.today() - timedelta(days=1)

    def _run():
        try:
            result = run_historical_backfill(from_date=from_date, to_date=to_date)
            import logging
            logging.getLogger("bhavcopy_scraper").info("Backfill job done: %s", result)
        except Exception as e:
            import logging
            logging.getLogger("bhavcopy_scraper").error("Backfill job failed: %s", e)

    t = threading.Thread(target=_run, daemon=True, name="bhavcopy_backfill")
    t.start()

    return {
        "status":    "started",
        "from_date": str(from_date),
        "to_date":   str(to_date),
        "message":   f"Backfill running in background for {years} years of data. Check server logs for progress.",
    }


@router.get("/backfill/status")
def get_backfill_status(db: Session = Depends(get_db_dependency)):
    """Return current price data coverage stats."""
    from sqlalchemy import func as sqlfunc
    total   = db.query(sqlfunc.count(DailyPrice.id)).scalar()
    min_dt  = db.query(sqlfunc.min(DailyPrice.date)).scalar()
    max_dt  = db.query(sqlfunc.max(DailyPrice.date)).scalar()
    symbols = db.query(sqlfunc.count(DailyPrice.symbol.distinct())).scalar()
    with_delivery = db.query(sqlfunc.count(DailyPrice.id)).filter(
        DailyPrice.delivery_volume != None
    ).scalar()
    return {
        "total_rows":       total,
        "symbols_covered":  symbols,
        "date_from":        str(min_dt) if min_dt else None,
        "date_to":          str(max_dt) if max_dt else None,
        "rows_with_delivery": with_delivery,
        "delivery_coverage_pct": round(with_delivery / total * 100, 1) if total else 0,
    }


@router.get("/ohlcv/{symbol}")
def get_stock_ohlcv(
    symbol: str,
    days: int = Query(default=90, ge=1, le=365),
    db: Session = Depends(get_db_dependency),
):
    """Return OHLCV candles + technical indicators for a single stock symbol."""
    cutoff = date.today() - timedelta(days=days)
    rows = (
        db.query(
            DailyPrice.date,
            DailyPrice.open,
            DailyPrice.high,
            DailyPrice.low,
            DailyPrice.close,
            DailyPrice.volume,
        )
        .filter(DailyPrice.symbol == symbol.upper(), DailyPrice.date >= cutoff)
        .order_by(DailyPrice.date.asc())
        .all()
    )

    if not rows:
        raise HTTPException(status_code=404, detail=f"No price data found for symbol: {symbol}")

    candles = [
        {
            "date":   str(r.date),
            "open":   float(r.open)   if r.open   is not None else None,
            "high":   float(r.high)   if r.high   is not None else None,
            "low":    float(r.low)    if r.low    is not None else None,
            "close":  float(r.close)  if r.close  is not None else None,
            "volume": float(r.volume) if r.volume is not None else None,
        }
        for r in rows
    ]

    closes = [c["close"] for c in candles]
    indicators = _compute_indicators(closes)

    return {
        "symbol":      symbol.upper(),
        "candles":     candles,
        **indicators,
    }
