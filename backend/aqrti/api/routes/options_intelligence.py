"""Options Intelligence API — /api/v1/options-intelligence"""

from __future__ import annotations

import sys, os, time as _time
from datetime import datetime, timezone

backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from aqrti.database.engine import get_db_dependency

router = APIRouter()

# In-memory cache: keyed by (symbol, expiry_offset)
_chain_cache: dict = {}
_CHAIN_TTL = 90  # seconds


def _is_market_open() -> bool:
    """True if NSE is likely open (Mon-Fri 09:15-15:30 IST)."""
    from datetime import timezone, timedelta
    ist = timezone(timedelta(hours=5, minutes=30))
    now = datetime.now(ist)
    if now.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    h, m = now.hour, now.minute
    return (h == 9 and m >= 15) or (10 <= h <= 14) or (h == 15 and m <= 30)


def _fetch_chain_from_nse(symbol: str, expiry_offset: int) -> dict:
    """Fetch live options chain from NSE with cookie seeding."""
    import json as _json
    from data_supremacy.options_scraper import _nse_session

    # Determine if index or equity
    _INDICES = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50"}
    is_index = symbol.upper() in _INDICES

    session = _nse_session()

    if is_index:
        url = "https://www.nseindia.com/api/option-chain-indices"
    else:
        url = "https://www.nseindia.com/api/option-chain-equities"

    try:
        resp = session.get(url, params={"symbol": symbol.upper()}, timeout=25)
        if not resp.ok or not resp.content or resp.content == b"{}":
            return {"status": "market_closed", "symbol": symbol,
                    "message": "NSE returned no data — market may be closed or outside trading hours"}
        data = resp.json()
    except Exception as exc:
        return {"status": "error", "symbol": symbol, "message": str(exc)}

    records = data.get("records", {})
    oc_data = records.get("data", [])
    spot = float(records.get("underlyingValue") or 0)
    expiry_dates = records.get("expiryDates", [])

    if not oc_data or not expiry_dates:
        return {"status": "market_closed", "symbol": symbol,
                "message": "No options data — market may be closed",
                "spot_price": spot or None}

    # Pick expiry by offset
    expiry_offset = min(expiry_offset, len(expiry_dates) - 1)
    expiry = expiry_dates[expiry_offset]

    # Filter to chosen expiry
    rows = [r for r in oc_data if r.get("expiryDate") == expiry]
    if not rows:
        rows = oc_data  # fallback: use all

    # Build strike-keyed dicts
    calls, puts = {}, {}
    for row in rows:
        strike = float(row.get("strikePrice", 0))
        if "CE" in row:
            calls[strike] = row["CE"]
        if "PE" in row:
            puts[strike] = row["PE"]

    all_strikes = sorted(set(calls.keys()) | set(puts.keys()))
    if not all_strikes:
        return {"status": "no_data", "symbol": symbol, "expiry": expiry, "spot_price": spot}

    # ATM strike
    atm = min(all_strikes, key=lambda s: abs(s - spot)) if spot else all_strikes[len(all_strikes) // 2]

    # PCR
    total_call_oi = sum(float(c.get("openInterest", 0) or 0) for c in calls.values())
    total_put_oi  = sum(float(p.get("openInterest", 0) or 0) for p in puts.values())
    pcr = round(total_put_oi / total_call_oi, 3) if total_call_oi > 0 else None

    # Max pain
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

    # Filter ±12 strikes around ATM
    atm_idx = all_strikes.index(atm) if atm in all_strikes else len(all_strikes) // 2
    lo = max(0, atm_idx - 12)
    hi = min(len(all_strikes), atm_idx + 13)
    filtered = all_strikes[lo:hi]

    chain = []
    for strike in filtered:
        c = calls.get(strike, {})
        p = puts.get(strike, {})
        call_oi = int(c.get("openInterest", 0) or 0)
        put_oi  = int(p.get("openInterest", 0) or 0)
        chain.append({
            "strike":        strike,
            "call_oi":       call_oi,
            "call_vol":      int(c.get("totalTradedVolume", 0) or 0),
            "call_iv":       round(float(c.get("impliedVolatility", 0) or 0), 1),
            "call_ltp":      round(float(c.get("lastPrice", 0) or 0), 2),
            "put_oi":        put_oi,
            "put_vol":       int(p.get("totalTradedVolume", 0) or 0),
            "put_iv":        round(float(p.get("impliedVolatility", 0) or 0), 1),
            "put_ltp":       round(float(p.get("lastPrice", 0) or 0), 2),
            "total_oi":      call_oi + put_oi,
            "pcr_at_strike": round(put_oi / call_oi, 3) if call_oi > 0 else None,
        })

    return {
        "status":      "ok",
        "symbol":      symbol,
        "expiry":      expiry,
        "expiry_dates": expiry_dates[:4],
        "spot_price":  spot,
        "pcr":         pcr,
        "max_pain":    max_pain,
        "atm_strike":  atm,
        "chain":       chain,
    }


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


@router.get("/chain")
def get_options_chain(
    symbol: str = Query(default="NIFTY"),
    expiry_offset: int = Query(default=0, ge=0, le=3),
):
    """Live options chain from NSE. Cached 90s. Shows market status when closed."""
    global _chain_cache
    cache_key = f"{symbol.upper()}_{expiry_offset}"
    now = _time.time()

    cached = _chain_cache.get(cache_key)
    if cached and (now - cached["ts"]) < _CHAIN_TTL and cached["data"].get("status") == "ok":
        return cached["data"]

    result = _fetch_chain_from_nse(symbol, expiry_offset)
    _chain_cache[cache_key] = {"ts": now, "data": result}
    return result
