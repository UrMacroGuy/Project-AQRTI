"""
Phase 8B — FII/DII Flow Engine
Scrapes daily FII/DII equity buy/sell data from NSE.
Computes rolling signals and net flow trends.
"""

from __future__ import annotations

import sys, os

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import json
import time
import logging
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from aqrti.database.models import FIIDIIFlow
from data_supremacy.scraper_base import (
    make_session, safe_get, safe_json, nse_headers,
    record_source_health,
)

logger = logging.getLogger("data_supremacy.fii_dii")

NSE_FII_URL   = "https://www.nseindia.com/api/fiidiiTradeReact"
# Fallback: SEBI publishes FII/DII via moneycontrol/BSE patterns too
MC_FII_URL    = "https://www.moneycontrol.com/stocks/marketstats/fii_dii_activity/index.php"


def _flow_signal(net_5d: float | None, net_20d: float | None) -> str:
    if net_5d is None:
        return "NEUTRAL"
    if net_5d > 2000 and (net_20d is None or net_20d > 0):
        return "BULLISH"
    if net_5d < -2000 and (net_20d is None or net_20d < 0):
        return "BEARISH"
    return "NEUTRAL"


def _parse_crore(val) -> float | None:
    if val is None:
        return None
    try:
        v = str(val).replace(",", "").strip()
        if v.startswith("(") and v.endswith(")"):
            return -float(v[1:-1])
        return float(v)
    except Exception:
        return None


def scrape_fii_dii(db: Session, target_date: date | None = None) -> dict:
    t0 = time.time()
    target = target_date or date.today()

    session = make_session()
    safe_get(session, "https://www.nseindia.com", headers={"Accept": "text/html"})
    time.sleep(1.2)

    stored = 0
    skipped = 0

    resp = safe_get(session, NSE_FII_URL, headers=nse_headers())
    data = safe_json(resp)

    if not data:
        record_source_health(db, "fii_dii", "down", error="No response from NSE FII API")
        db.commit()
        return {"status": "error", "error": "No data from NSE"}

    # NSE returns list of rows: date + FII/DII buy/sell
    rows = data if isinstance(data, list) else data.get("data", [])

    for item in rows:
        try:
            raw_date = item.get("date") or item.get("tradeDate") or ""
            try:
                row_date = datetime.strptime(raw_date, "%d-%b-%Y").date()
            except Exception:
                try:
                    row_date = datetime.strptime(raw_date, "%Y-%m-%d").date()
                except Exception:
                    row_date = target

            for category in ["FII", "DII"]:
                cat_key = category.lower()
                gross_buy  = _parse_crore(item.get(f"{cat_key}BuyValue")  or item.get(f"{category}_buy"))
                gross_sell = _parse_crore(item.get(f"{cat_key}SellValue") or item.get(f"{category}_sell"))
                if gross_buy is None and gross_sell is None:
                    continue
                net = (gross_buy or 0) - (gross_sell or 0)

                existing = db.query(FIIDIIFlow).filter(
                    FIIDIIFlow.flow_date == row_date,
                    FIIDIIFlow.category  == category,
                ).first()
                if existing:
                    skipped += 1
                    continue

                flow = FIIDIIFlow(
                    flow_date    = row_date,
                    category     = category,
                    gross_buy    = gross_buy,
                    gross_sell   = gross_sell,
                    net_investment = net,
                    segment      = "equity",
                )
                db.add(flow)
                stored += 1

        except Exception as exc:
            logger.debug("FII/DII row error: %s", exc)

    db.commit()

    # Compute rolling signals for today's rows
    _update_rolling_signals(db)
    db.commit()

    duration_ms = int((time.time() - t0) * 1000)
    record_source_health(db, "fii_dii", "ok", records=stored, duration_ms=duration_ms)
    db.commit()

    return {"status": "ok", "stored": stored, "skipped": skipped, "date": str(target)}


def _update_rolling_signals(db: Session, days_back: int = 30) -> None:
    cutoff = date.today() - timedelta(days=days_back)
    rows = db.query(FIIDIIFlow).filter(FIIDIIFlow.flow_date >= cutoff)\
             .order_by(FIIDIIFlow.flow_date.asc()).all()

    # group by category
    by_cat: dict[str, list] = {}
    for r in rows:
        by_cat.setdefault(r.category, []).append(r)

    for category, cat_rows in by_cat.items():
        for i, row in enumerate(cat_rows):
            nets = [r.net_investment for r in cat_rows[max(0, i-4):i+1] if r.net_investment is not None]
            nets20 = [r.net_investment for r in cat_rows[max(0, i-19):i+1] if r.net_investment is not None]
            net_5d  = sum(nets)   if nets   else None
            net_20d = sum(nets20) if nets20 else None
            row.net_5d       = net_5d
            row.net_20d      = net_20d
            row.flow_signal  = _flow_signal(net_5d, net_20d)


def backfill_fii_dii(db: Session, days: int = 365) -> dict:
    """Pull all available history from NSE in one call (NSE returns ~60 days)."""
    result = scrape_fii_dii(db)
    return {"status": "backfill_complete", "result": result}


def get_fii_dii_latest(db: Session, days: int = 30) -> dict:
    cutoff = date.today() - timedelta(days=days)
    rows = db.query(FIIDIIFlow).filter(
        FIIDIIFlow.flow_date >= cutoff
    ).order_by(FIIDIIFlow.flow_date.desc()).all()

    fii = [_to_dict(r) for r in rows if r.category == "FII"]
    dii = [_to_dict(r) for r in rows if r.category == "DII"]

    # Today's signal
    today_fii = fii[0] if fii else {}
    today_dii = dii[0] if dii else {}

    return {
        "fii": fii,
        "dii": dii,
        "latest_fii": today_fii,
        "latest_dii": today_dii,
        "combined_signal": _combined_signal(today_fii, today_dii),
        "fii_5d_net":  today_fii.get("net_5d"),
        "dii_5d_net":  today_dii.get("net_5d"),
    }


def _combined_signal(fii: dict, dii: dict) -> str:
    fs = fii.get("flow_signal", "NEUTRAL")
    ds = dii.get("flow_signal", "NEUTRAL")
    if fs == "BULLISH" and ds == "BULLISH":
        return "STRONG_BULL"
    if fs == "BEARISH" and ds == "BEARISH":
        return "STRONG_BEAR"
    if fs == "BULLISH" or ds == "BULLISH":
        return "BULL"
    if fs == "BEARISH" or ds == "BEARISH":
        return "BEAR"
    return "NEUTRAL"


def _to_dict(r: FIIDIIFlow) -> dict:
    return {
        "flow_date":      str(r.flow_date),
        "category":       r.category,
        "gross_buy":      r.gross_buy,
        "gross_sell":     r.gross_sell,
        "net_investment": r.net_investment,
        "net_5d":         r.net_5d,
        "net_20d":        r.net_20d,
        "flow_signal":    r.flow_signal,
        "segment":        r.segment,
    }
