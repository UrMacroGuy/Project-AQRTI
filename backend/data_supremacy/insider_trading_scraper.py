"""
Phase 8H — NSE Insider Trading (PIT) Disclosure Scraper
Scrapes SEBI PIT (Prohibition of Insider Trading) regulation 7(2) disclosures
— promoter/insider/KMP trades in listed securities — from NSE's real
corporates-pit API (verified live 2026-07-14, see plans/CHANGELOG.md).

Endpoint verified by hand: https://www.nseindia.com/api/corporates-pit
Same session/cookie/header pattern as corporate_scraper.py — NSE needs a
homepage visit first to mint the AKA_A2 cookie, then a Referer matching the
actual insider-trading page. Params are snake_case, dates are %d-%m-%Y,
matching corporates-corporateActions exactly (same API family).
"""

from __future__ import annotations

import sys, os

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import time
import logging
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from aqrti.database.models import NSEInsiderTrading
from data_supremacy.scraper_base import (
    make_session, safe_get, safe_json, nse_headers,
    record_source_health,
)

logger = logging.getLogger("data_supremacy.insider_trading")

NSE_BASE = "https://www.nseindia.com"
PIT_URL = f"{NSE_BASE}/api/corporates-pit"
# NSE's insider-trading disclosure page — used as Referer, same role as
# corporate_scraper.py's homepage referer.
PIT_REFERER = f"{NSE_BASE}/companies-listing/corporate-filings-insider-trading"


def _parse_num(val) -> float | None:
    if val is None:
        return None
    try:
        s = str(val).replace(",", "").strip()
        if s in ("", "-", "NA", "N/A"):
            return None
        return float(s)
    except Exception:
        return None


def _parse_nse_date(raw: str, fallback: date) -> date:
    if not raw:
        return fallback
    # NSE "date" field includes a time component: "06-Apr-2026 16:07"
    raw = raw.split(" ")[0].strip()
    for fmt in ("%d-%b-%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except Exception:
            continue
    return fallback


def _classify_transaction(item: dict) -> str:
    """Derive buy/sell/other from NSE's transaction-type + buy/sell value fields."""
    tdp = (item.get("tdpTransactionType") or "").strip().lower()
    if tdp in ("buy", "sell"):
        return tdp
    buy_val = _parse_num(item.get("buyValue")) or 0
    sell_val = _parse_num(item.get("sellValue")) or 0
    buy_qty = _parse_num(item.get("buyQuantity")) or 0
    sell_qty = _parse_num(item.get("sellquantity")) or 0
    if buy_val > 0 or buy_qty > 0:
        return "buy"
    if sell_val > 0 or sell_qty > 0:
        return "sell"
    mode = (item.get("acqMode") or "").strip().lower()
    if "pledge" in mode:
        return "pledge"
    return "other"


def scrape_insider_trading(db: Session, symbols: list[str] | None = None,
                            from_date: date | None = None,
                            to_date: date | None = None) -> dict:
    """
    Scrape NSE PIT disclosures for the given symbols (defaults to the active
    curated universe, NSE-listed only — VOO/QQQ have no NSE PIT feed).
    NSE's corporates-pit endpoint requires a `symbol` param per call (unlike
    corporates-corporateActions, which accepts an unscoped index=equities
    sweep) — verified empirically: an unscoped call returns the full-market
    acqNameList but per-symbol filtering must be done via `symbol=`.
    """
    t0 = time.time()
    if not to_date:
        to_date = date.today()
    if not from_date:
        from_date = to_date - timedelta(days=90)

    if symbols is None:
        from aqrti.database.models import Stock
        NON_NSE = {"VOO", "QQQ"}
        symbols = [s.symbol for s in db.query(Stock.symbol).filter(Stock.active == True).all()
                   if s.symbol not in NON_NSE]

    session = make_session()
    safe_get(session, NSE_BASE, headers={"Accept": "text/html"})
    time.sleep(1)
    # Seed cookies scoped to the insider-trading page, same defensive pattern
    # as corporate_scraper's homepage-then-API sequence.
    safe_get(session, PIT_REFERER, headers={"Accept": "text/html"})
    time.sleep(1)

    stored = 0
    skipped = 0
    errors = 0
    per_symbol_counts: dict[str, int] = {}

    params_base = {
        "index": "equities",
        "from_date": from_date.strftime("%d-%m-%Y"),
        "to_date": to_date.strftime("%d-%m-%Y"),
    }

    for symbol in symbols:
        params = dict(params_base, symbol=symbol)
        resp = safe_get(session, PIT_URL, params=params, headers=nse_headers())
        data = safe_json(resp)
        if not data:
            errors += 1
            logger.warning("No PIT data response for %s", symbol)
            time.sleep(1)
            continue

        rows = data.get("data", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
        if not isinstance(rows, list):
            rows = []

        sym_stored = 0
        for item in rows:
            try:
                sym = (item.get("symbol") or symbol).upper().strip()
                person_name = (item.get("acqName") or "").strip()
                if not sym or not person_name:
                    continue

                disclosure_date = _parse_nse_date(item.get("date"), to_date)
                source_id = f"{item.get('did') or ''}_{item.get('pid') or ''}"[:80]

                existing = db.query(NSEInsiderTrading).filter(
                    NSEInsiderTrading.symbol == sym,
                    NSEInsiderTrading.disclosure_date == disclosure_date,
                    NSEInsiderTrading.person_name == person_name,
                    NSEInsiderTrading.source_id == source_id,
                ).first()
                if existing:
                    skipped += 1
                    continue

                row = NSEInsiderTrading(
                    symbol              = sym,
                    company_name        = item.get("company"),
                    disclosure_date     = disclosure_date,
                    acq_from_date       = _parse_nse_date(item.get("acqfromDt"), disclosure_date) if item.get("acqfromDt") else None,
                    acq_to_date         = _parse_nse_date(item.get("acqtoDt"), disclosure_date) if item.get("acqtoDt") else None,
                    person_name         = person_name[:150],
                    person_category     = (item.get("personCategory") or None),
                    transaction_type    = _classify_transaction(item),
                    mode_of_acquisition = item.get("acqMode"),
                    security_type       = item.get("secType") or item.get("securitiesTypePost"),
                    quantity            = _parse_num(item.get("secAcq")),
                    value_inr           = _parse_num(item.get("secVal")),
                    shares_before_no    = _parse_num(item.get("befAcqSharesNo")),
                    shares_before_pct   = _parse_num(item.get("befAcqSharesPer")),
                    shares_after_no     = _parse_num(item.get("afterAcqSharesNo")),
                    shares_after_pct    = _parse_num(item.get("afterAcqSharesPer")),
                    regulation          = item.get("anex"),
                    attachment_url      = item.get("xbrl"),
                    source_id           = source_id,
                )
                db.add(row)
                stored += 1
                sym_stored += 1

            except Exception as exc:
                errors += 1
                logger.debug("PIT row parse error for %s: %s", symbol, exc)

        if sym_stored:
            per_symbol_counts[symbol] = sym_stored
        time.sleep(1)  # be polite between per-symbol calls

    db.commit()
    duration_ms = int((time.time() - t0) * 1000)
    record_source_health(db, "nse_insider_trading", "ok" if errors == 0 else "degraded",
                          records=stored, duration_ms=duration_ms)
    db.commit()

    return {
        "status": "ok", "stored": stored, "skipped": skipped, "errors": errors,
        "from_date": str(from_date), "to_date": str(to_date),
        "symbols_scanned": len(symbols), "per_symbol": per_symbol_counts,
    }


def backfill_insider_trading(db: Session, days: int = 365) -> dict:
    """Historical backfill — NSE's corporates-pit accepts a wide date range in
    one call per symbol (verified: a 1-year+ range returned data fine), so no
    chunking is needed here unlike the multi-symbol corporate_scraper sweep."""
    to_date = date.today()
    from_date = to_date - timedelta(days=days)
    r = scrape_insider_trading(db, from_date=from_date, to_date=to_date)
    return {"status": "backfill_complete", "result": r}


def get_recent_insider_trades(db: Session, days: int = 90, symbol: str | None = None,
                               limit: int = 100) -> list[dict]:
    cutoff = date.today() - timedelta(days=days)
    q = db.query(NSEInsiderTrading).filter(NSEInsiderTrading.disclosure_date >= cutoff)
    if symbol:
        q = q.filter(NSEInsiderTrading.symbol == symbol)
    rows = q.order_by(NSEInsiderTrading.disclosure_date.desc()).limit(limit).all()
    return [_to_dict(r) for r in rows]


def _to_dict(r: NSEInsiderTrading) -> dict:
    return {
        "id":                  r.id,
        "symbol":              r.symbol,
        "company_name":        r.company_name,
        "disclosure_date":     str(r.disclosure_date),
        "person_name":         r.person_name,
        "person_category":     r.person_category,
        "transaction_type":    r.transaction_type,
        "mode_of_acquisition": r.mode_of_acquisition,
        "quantity":            r.quantity,
        "value_inr":           r.value_inr,
        "shares_before_pct":   r.shares_before_pct,
        "shares_after_pct":    r.shares_after_pct,
        "attachment_url":      r.attachment_url,
        "scraped_at":          r.scraped_at.isoformat() if r.scraped_at else None,
    }
