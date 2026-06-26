"""
Phase 8C — Options Intelligence Engine
Scrapes NSE options chain: PCR, max pain, IV skew, OI concentration.
Supports NIFTY, BANKNIFTY, and top equity derivatives.
"""

from __future__ import annotations

import sys, os

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import json
import time
import logging
import requests
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from aqrti.database.models import OptionsChain
from data_supremacy.scraper_base import (
    record_source_health,
)

logger = logging.getLogger("data_supremacy.options")

NSE_OPTION_CHAIN_URL = "https://www.nseindia.com/api/option-chain-indices"
NSE_EQUITY_OC_URL    = "https://www.nseindia.com/api/option-chain-equities"

INDICES_TO_SCRAPE = ["NIFTY", "BANKNIFTY", "FINNIFTY"]
TOP_EQUITY_SYMBOLS = ["RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK"]


def _nse_session() -> requests.Session:
    """Create a requests session with NSE cookies by visiting the homepage first."""
    import requests as req
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-IN,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Cache-Control": "max-age=0",
    }
    s = req.Session()
    s.headers.update(headers)
    try:
        s.get("https://www.nseindia.com", timeout=15)
        time.sleep(1.5)
        s.get("https://www.nseindia.com/option-chain", timeout=15)
        time.sleep(1.0)
    except Exception:
        pass
    return s


def scrape_option_chain(db: Session, symbol: str = "NIFTY",
                         is_index: bool = True) -> dict:
    t0 = time.time()
    session = _nse_session()

    url = NSE_OPTION_CHAIN_URL if is_index else NSE_EQUITY_OC_URL
    api_headers = {
        "Referer": "https://www.nseindia.com/option-chain",
        "Accept": "application/json, text/plain, */*",
        "X-Requested-With": "XMLHttpRequest",
    }
    try:
        resp = session.get(url, params={"symbol": symbol}, headers=api_headers, timeout=20)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning("NSE options %s failed: %s", symbol, exc)
        data = None

    if not data:
        record_source_health(db, "options", "down",
                              error=f"No data for {symbol}")
        db.commit()
        return {"status": "error", "symbol": symbol, "error": "no_data"}

    snapshot = _parse_chain(data, symbol)
    if not snapshot:
        return {"status": "error", "symbol": symbol, "error": "parse_failed"}

    today = date.today()
    existing = db.query(OptionsChain).filter(
        OptionsChain.symbol        == symbol,
        OptionsChain.snapshot_date == today,
        OptionsChain.expiry_date   == snapshot.get("expiry_date"),
    ).first()

    if existing:
        # Update existing
        for k, v in snapshot.items():
            if hasattr(existing, k) and k not in ("id", "scraped_at"):
                setattr(existing, k, v)
    else:
        row = OptionsChain(snapshot_date=today, symbol=symbol, **snapshot)
        db.add(row)

    db.commit()
    duration_ms = int((time.time() - t0) * 1000)
    record_source_health(db, "options", "ok", records=1, duration_ms=duration_ms)
    db.commit()
    return {"status": "ok", "symbol": symbol, "pcr_oi": snapshot.get("pcr_oi"),
            "max_pain": snapshot.get("max_pain"), "atm_iv": snapshot.get("atm_iv")}


def _parse_chain(data: dict, symbol: str) -> dict | None:
    try:
        records = data.get("records", {})
        oc_data = records.get("data", [])
        spot    = records.get("underlyingValue", 0)

        expiry_dates = records.get("expiryDates", [])
        nearest_expiry_str = expiry_dates[0] if expiry_dates else None
        try:
            expiry_date = datetime.strptime(nearest_expiry_str, "%d-%b-%Y").date() if nearest_expiry_str else None
        except Exception:
            expiry_date = None

        # Filter to nearest expiry
        near = [r for r in oc_data if r.get("expiryDate") == nearest_expiry_str] if nearest_expiry_str else oc_data

        total_call_oi = 0.0
        total_put_oi  = 0.0
        call_oi_by_strike: dict[float, float] = {}
        put_oi_by_strike:  dict[float, float] = {}
        atm_iv = None
        atm_strike = None

        if spot:
            # find ATM = strike closest to spot
            strikes = sorted(set(r.get("strikePrice", 0) for r in near if r.get("strikePrice")))
            if strikes:
                atm_strike = min(strikes, key=lambda s: abs(s - spot))

        for item in near:
            sp = item.get("strikePrice", 0)
            ce = item.get("CE", {}) or {}
            pe = item.get("PE", {}) or {}

            c_oi = ce.get("openInterest", 0) or 0
            p_oi = pe.get("openInterest", 0) or 0
            total_call_oi += c_oi
            total_put_oi  += p_oi
            call_oi_by_strike[sp] = c_oi
            put_oi_by_strike[sp]  = p_oi

            if sp == atm_strike:
                atm_iv = ce.get("impliedVolatility") or pe.get("impliedVolatility")

        pcr_oi = total_put_oi / total_call_oi if total_call_oi > 0 else None

        highest_call_oi_strike = max(call_oi_by_strike, key=call_oi_by_strike.get) if call_oi_by_strike else None
        highest_put_oi_strike  = max(put_oi_by_strike,  key=put_oi_by_strike.get)  if put_oi_by_strike  else None

        max_pain = _compute_max_pain(call_oi_by_strike, put_oi_by_strike)

        # IV skew: OTM put IV (ATM - 5%) vs OTM call IV (ATM + 5%)
        iv_skew = None
        if atm_strike and spot:
            otm_put_strike  = atm_strike * 0.95
            otm_call_strike = atm_strike * 1.05
            otm_p_strike = min(put_oi_by_strike.keys(), key=lambda s: abs(s - otm_put_strike), default=None)
            otm_c_strike = min(call_oi_by_strike.keys(), key=lambda s: abs(s - otm_call_strike), default=None)
            put_iv  = next((r.get("PE", {}).get("impliedVolatility") for r in near if r.get("strikePrice") == otm_p_strike), None)
            call_iv = next((r.get("CE", {}).get("impliedVolatility") for r in near if r.get("strikePrice") == otm_c_strike), None)
            if put_iv and call_iv:
                iv_skew = put_iv - call_iv

        # Store top 10 strikes each side
        sorted_strikes = sorted(call_oi_by_strike.keys())
        atm_idx = sorted_strikes.index(atm_strike) if atm_strike in sorted_strikes else len(sorted_strikes)//2
        top_strikes = sorted_strikes[max(0, atm_idx-5): atm_idx+6]
        chain_summary = [
            {
                "strike": s,
                "call_oi": call_oi_by_strike.get(s, 0),
                "put_oi": put_oi_by_strike.get(s, 0),
            }
            for s in top_strikes
        ]

        return {
            "expiry_date":            expiry_date,
            "spot_price":             float(spot) if spot else None,
            "pcr_oi":                 round(pcr_oi, 4) if pcr_oi else None,
            "max_pain":               max_pain,
            "atm_strike":             float(atm_strike) if atm_strike else None,
            "atm_iv":                 float(atm_iv) if atm_iv else None,
            "iv_skew":                round(iv_skew, 4) if iv_skew else None,
            "total_call_oi":          float(total_call_oi),
            "total_put_oi":           float(total_put_oi),
            "highest_call_oi_strike": float(highest_call_oi_strike) if highest_call_oi_strike else None,
            "highest_put_oi_strike":  float(highest_put_oi_strike)  if highest_put_oi_strike  else None,
            "chain_json":             json.dumps(chain_summary),
        }
    except Exception as exc:
        logger.warning("Chain parse failed for %s: %s", symbol, exc)
        return None


def _compute_max_pain(call_oi: dict, put_oi: dict) -> float | None:
    if not call_oi or not put_oi:
        return None
    strikes = sorted(set(list(call_oi.keys()) + list(put_oi.keys())))
    min_pain_strike = None
    min_pain_value  = float("inf")
    for test_strike in strikes:
        pain = 0.0
        for s, oi in call_oi.items():
            if test_strike > s:
                pain += (test_strike - s) * oi
        for s, oi in put_oi.items():
            if test_strike < s:
                pain += (s - test_strike) * oi
        if pain < min_pain_value:
            min_pain_value  = pain
            min_pain_strike = test_strike
    return float(min_pain_strike) if min_pain_strike else None


def scrape_all_options(db: Session) -> dict:
    results = []
    for idx in INDICES_TO_SCRAPE:
        r = scrape_option_chain(db, symbol=idx, is_index=True)
        results.append(r)
        time.sleep(1.5)
    for sym in TOP_EQUITY_SYMBOLS:
        r = scrape_option_chain(db, symbol=sym, is_index=False)
        results.append(r)
        time.sleep(1.5)
    ok = sum(1 for r in results if r.get("status") == "ok")
    return {"status": "ok", "scraped": len(results), "successful": ok}


def get_options_snapshot(db: Session, symbol: str = "NIFTY") -> dict | None:
    row = db.query(OptionsChain).filter(
        OptionsChain.symbol == symbol
    ).order_by(OptionsChain.snapshot_date.desc()).first()
    if not row:
        return None
    return _to_dict(row)


def get_options_history(db: Session, symbol: str = "NIFTY", days: int = 30) -> list[dict]:
    cutoff = date.today() - timedelta(days=days)
    rows = db.query(OptionsChain).filter(
        OptionsChain.symbol == symbol,
        OptionsChain.snapshot_date >= cutoff,
    ).order_by(OptionsChain.snapshot_date.asc()).all()
    return [_to_dict(r) for r in rows]


def _to_dict(r: OptionsChain) -> dict:
    try:
        chain = json.loads(r.chain_json) if r.chain_json else []
    except Exception:
        chain = []
    return {
        "symbol":        r.symbol,
        "snapshot_date": str(r.snapshot_date),
        "expiry_date":   str(r.expiry_date) if r.expiry_date else None,
        "spot_price":    r.spot_price,
        "pcr_oi":        r.pcr_oi,
        "pcr_volume":    r.pcr_volume,
        "max_pain":      r.max_pain,
        "atm_strike":    r.atm_strike,
        "atm_iv":        r.atm_iv,
        "iv_skew":       r.iv_skew,
        "total_call_oi": r.total_call_oi,
        "total_put_oi":  r.total_put_oi,
        "highest_call_oi_strike": r.highest_call_oi_strike,
        "highest_put_oi_strike":  r.highest_put_oi_strike,
        "chain":         chain,
    }
