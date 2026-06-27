"""Options Intelligence API — /api/v1/options-intelligence"""

from __future__ import annotations

from contextlib import redirect_stderr
from io import StringIO
import sys, os

backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from aqrti.database.engine import get_db_dependency

router = APIRouter()


@router.get("")
def get_snapshot(
    symbol: str = Query(default="NIFTY"),
    db: Session = Depends(get_db_dependency),
):
    from data_supremacy.options_scraper import get_options_snapshot
    snap = get_options_snapshot(db, symbol=symbol)
    if not snap:
        return {"status": "no_data", "symbol": symbol}
    return snap


@router.get("/history")
def get_history(
    symbol: str = Query(default="NIFTY"),
    days:   int = Query(default=30, ge=1, le=365),
    db: Session = Depends(get_db_dependency),
):
    from data_supremacy.options_scraper import get_options_history
    return {"symbol": symbol, "history": get_options_history(db, symbol=symbol, days=days)}


@router.post("/scrape")
def trigger_scrape(
    symbol:   str  = Query(default="NIFTY"),
    is_index: bool = Query(default=True),
    db: Session = Depends(get_db_dependency),
):
    from data_supremacy.options_scraper import scrape_option_chain
    return scrape_option_chain(db, symbol=symbol, is_index=is_index)


@router.post("/scrape-all")
def trigger_scrape_all(db: Session = Depends(get_db_dependency)):
    from data_supremacy.options_scraper import scrape_all_options
    return scrape_all_options(db)


_chain_cache: dict = {"ts": 0, "key": "", "data": None}
_CHAIN_TTL = 60

@router.get("/chain")
def get_options_chain(
    symbol: str = Query(default="NIFTY"),
    expiry_offset: int = Query(default=0, ge=0, le=2),
):
    """Live options chain via yfinance. Cached 60s."""
    import time as _time
    global _chain_cache

    cache_key = f"{symbol}_{expiry_offset}"
    now = _time.time()
    if _chain_cache["data"] and _chain_cache["key"] == cache_key and (now - _chain_cache["ts"]) < _CHAIN_TTL:
        return _chain_cache["data"]

    try:
        import yfinance as yf

        _YF_MAP = {
            "NIFTY": "^NSEI", "BANKNIFTY": "^NSEBANK",
            "RELIANCE": "RELIANCE.NS", "HDFCBANK": "HDFCBANK.NS",
            "INFY": "INFY.NS", "TCS": "TCS.NS",
            "ICICIBANK": "ICICIBANK.NS", "AXISBANK": "AXISBANK.NS",
        }
        yf_sym = _YF_MAP.get(symbol.upper(), symbol.upper() + ".NS")
        ticker = yf.Ticker(yf_sym)

        # Get spot price
        try:
            yf_stderr = StringIO()
            with redirect_stderr(yf_stderr):
                fi = ticker.fast_info
            spot = float(getattr(fi, "last_price", None) or 0)
        except Exception:
            spot = None

        # Get expiry dates
        try:
            expiries = ticker.options
        except Exception:
            expiries = []

        if not expiries or expiry_offset >= len(expiries):
            result = {"symbol": symbol, "expiry": None, "spot_price": spot, "pcr": None, "max_pain": None, "atm_strike": None, "chain": []}
            _chain_cache = {"ts": now, "key": cache_key, "data": result}
            return result

        expiry = expiries[expiry_offset]
        opt = ticker.option_chain(expiry)
        calls_df = opt.calls
        puts_df  = opt.puts

        if calls_df.empty or puts_df.empty:
            result = {"symbol": symbol, "expiry": expiry, "spot_price": spot, "pcr": None, "max_pain": None, "atm_strike": None, "chain": []}
            _chain_cache = {"ts": now, "key": cache_key, "data": result}
            return result

        # Build strike-keyed dicts
        calls = {float(r["strike"]): r for _, r in calls_df.iterrows()}
        puts  = {float(r["strike"]): r for _, r in puts_df.iterrows()}
        all_strikes = sorted(set(calls.keys()) | set(puts.keys()))

        # ATM strike
        atm = min(all_strikes, key=lambda s: abs(s - (spot or s))) if spot else all_strikes[len(all_strikes)//2]

        # PCR
        total_call_oi = sum(float(r.get("openInterest", 0) or 0) for r in calls.values())
        total_put_oi  = sum(float(r.get("openInterest", 0) or 0) for r in puts.values())
        pcr = round(total_put_oi / total_call_oi, 3) if total_call_oi > 0 else None

        # Max pain — minimize total option writer P&L
        max_pain = None
        if spot:
            best_loss = float("inf")
            for test_price in all_strikes:
                call_loss = sum(max(0, test_price - s) * float(calls[s].get("openInterest", 0) or 0) for s in calls)
                put_loss  = sum(max(0, s - test_price) * float(puts[s].get("openInterest", 0) or 0) for s in puts)
                total = call_loss + put_loss
                if total < best_loss:
                    best_loss = total
                    max_pain = test_price

        # Filter ±10 strikes around ATM
        atm_idx = all_strikes.index(atm) if atm in all_strikes else len(all_strikes) // 2
        lo = max(0, atm_idx - 10)
        hi = min(len(all_strikes), atm_idx + 11)
        filtered = all_strikes[lo:hi]

        chain = []
        for strike in filtered:
            c = calls.get(strike, {})
            p = puts.get(strike, {})
            call_oi = int(c.get("openInterest", 0) or 0)
            put_oi  = int(p.get("openInterest", 0) or 0)
            chain.append({
                "strike":       strike,
                "call_oi":      call_oi,
                "call_vol":     int(c.get("volume", 0) or 0),
                "call_iv":      round(float(c.get("impliedVolatility", 0) or 0) * 100, 1),
                "call_ltp":     round(float(c.get("lastPrice", 0) or 0), 2),
                "put_oi":       put_oi,
                "put_vol":      int(p.get("volume", 0) or 0),
                "put_iv":       round(float(p.get("impliedVolatility", 0) or 0) * 100, 1),
                "put_ltp":      round(float(p.get("lastPrice", 0) or 0), 2),
                "total_oi":     call_oi + put_oi,
                "pcr_at_strike": round(put_oi / call_oi, 3) if call_oi > 0 else None,
            })

        result = {
            "symbol":     symbol,
            "expiry":     expiry,
            "spot_price": spot,
            "pcr":        pcr,
            "max_pain":   max_pain,
            "atm_strike": atm,
            "chain":      chain,
        }
        _chain_cache = {"ts": now, "key": cache_key, "data": result}
        return result

    except Exception as e:
        result = {"symbol": symbol, "expiry": None, "spot_price": None, "pcr": None, "max_pain": None, "atm_strike": None, "chain": [], "error": str(e)}
        return result
