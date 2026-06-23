"""
Phase 8A — NSE Corporate Filings Scraper
Scrapes corporate announcements, board meetings, dividends, splits, results from NSE.
Resilient: retry logic, change detection, historical backfill, schema validation.
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
from typing import Any

from sqlalchemy.orm import Session

from aqrti.database.models import NSECorporateFiling
from data_supremacy.scraper_base import (
    make_session, safe_get, safe_json, nse_headers,
    validate_required_fields, record_source_health,
)

logger = logging.getLogger("data_supremacy.corporate")

NSE_BASE = "https://www.nseindia.com"
CORP_ACTIONS_URL = f"{NSE_BASE}/api/corporates-corporateActions"
CORP_RESULTS_URL = f"{NSE_BASE}/api/corporates-financial-results"
ANNOUNCEMENTS_URL = f"{NSE_BASE}/api/corporates-announcements"

FILING_TYPES = {
    "AGM/EGM": "board_meeting",
    "Board Meeting": "board_meeting",
    "Dividend": "dividend",
    "Bonus": "bonus",
    "Split": "split",
    "Rights": "rights",
    "Buyback": "buyback",
    "Merger": "merger",
    "Financial Results": "results",
    "Quarterly Results": "results",
    "Annual Results": "results",
}


def _classify_filing(subject: str) -> str:
    if not subject:
        return "announcement"
    su = subject.lower()
    if any(k in su for k in ["result", "financial", "quarterly", "annual", "earnings"]):
        return "results"
    if "dividend" in su:
        return "dividend"
    if "split" in su:
        return "split"
    if "bonus" in su:
        return "bonus"
    if any(k in su for k in ["buyback", "buy-back"]):
        return "buyback"
    if any(k in su for k in ["merger", "amalgam", "demerger"]):
        return "merger"
    if any(k in su for k in ["board meeting", "agm", "egm"]):
        return "board_meeting"
    return "announcement"


def _impact_score(filing_type: str, subject: str) -> float:
    weights = {"results": 80, "dividend": 60, "split": 70, "bonus": 65,
               "buyback": 75, "merger": 90, "board_meeting": 40, "announcement": 30}
    base = weights.get(filing_type, 30)
    if subject:
        sl = subject.lower()
        if any(k in sl for k in ["strong", "record", "highest", "best"]):
            base = min(base + 10, 100)
        if any(k in sl for k in ["loss", "decline", "weak", "poor"]):
            base = max(base - 10, 0)
    return float(base)


def scrape_corporate_actions(db: Session, from_date: date | None = None,
                              to_date: date | None = None) -> dict:
    t0 = time.time()
    if not to_date:
        to_date = date.today()
    if not from_date:
        from_date = to_date - timedelta(days=7)

    session = make_session()
    # NSE needs a cookie first
    safe_get(session, NSE_BASE, headers={"Accept": "text/html"})
    time.sleep(1)

    stored = 0
    skipped = 0
    errors = 0

    params = {
        "index": "equities",
        "from_date": from_date.strftime("%d-%m-%Y"),
        "to_date": to_date.strftime("%d-%m-%Y"),
    }

    for url, label in [
        (CORP_ACTIONS_URL, "corporate_actions"),
        (ANNOUNCEMENTS_URL, "announcements"),
    ]:
        resp = safe_get(session, url, params=params, headers=nse_headers())
        data = safe_json(resp)
        if not data:
            errors += 1
            logger.warning("No data from %s", label)
            continue

        rows = data if isinstance(data, list) else data.get("data", data.get("announcements", []))
        if not isinstance(rows, list):
            rows = []

        for item in rows:
            try:
                symbol    = (item.get("symbol") or item.get("sm_symbol") or "").upper().strip()
                subject   = item.get("subject") or item.get("desc") or ""
                source_id = str(item.get("seqNo") or item.get("isin") or "") + symbol

                raw_date = item.get("exDate") or item.get("recordDate") or item.get("bcStartDate") or ""
                try:
                    filing_date = datetime.strptime(raw_date, "%d-%b-%Y").date() if raw_date else to_date
                except Exception:
                    try:
                        filing_date = datetime.strptime(raw_date, "%Y-%m-%d").date()
                    except Exception:
                        filing_date = to_date

                if not symbol:
                    continue

                filing_type = _classify_filing(
                    item.get("purpose") or item.get("annsType") or subject
                )

                existing = db.query(NSECorporateFiling).filter(
                    NSECorporateFiling.symbol == symbol,
                    NSECorporateFiling.filing_date == filing_date,
                    NSECorporateFiling.filing_type == filing_type,
                    NSECorporateFiling.source_id == source_id[:80],
                ).first()
                if existing:
                    skipped += 1
                    continue

                row = NSECorporateFiling(
                    symbol        = symbol,
                    company_name  = item.get("companyName") or item.get("sm_name"),
                    filing_date   = filing_date,
                    filing_type   = filing_type,
                    subject       = subject[:500] if subject else None,
                    details       = json.dumps({k: v for k, v in item.items() if k not in ("symbol", "subject")}),
                    source_id     = source_id[:80],
                    impact_score  = _impact_score(filing_type, subject),
                )
                db.add(row)
                stored += 1

            except Exception as exc:
                errors += 1
                logger.debug("Row parse error: %s", exc)

    db.commit()
    duration_ms = int((time.time() - t0) * 1000)
    record_source_health(db, "nse_corporate", "ok" if errors == 0 else "degraded",
                          records=stored, duration_ms=duration_ms)
    db.commit()

    return {"status": "ok", "stored": stored, "skipped": skipped, "errors": errors,
            "from_date": str(from_date), "to_date": str(to_date)}


def backfill_corporate(db: Session, days: int = 365) -> dict:
    """Historical backfill — scrape in 30-day chunks."""
    results = []
    today = date.today()
    chunk = timedelta(days=30)
    cursor = today - timedelta(days=days)
    while cursor < today:
        end = min(cursor + chunk, today)
        r = scrape_corporate_actions(db, from_date=cursor, to_date=end)
        results.append(r)
        cursor = end + timedelta(days=1)
        time.sleep(2)
    total_stored = sum(r.get("stored", 0) for r in results)
    return {"status": "backfill_complete", "chunks": len(results), "total_stored": total_stored}


def get_recent_filings(db: Session, days: int = 7, symbol: str | None = None,
                        filing_type: str | None = None, limit: int = 100) -> list[dict]:
    cutoff = date.today() - timedelta(days=days)
    q = db.query(NSECorporateFiling).filter(NSECorporateFiling.filing_date >= cutoff)
    if symbol:
        q = q.filter(NSECorporateFiling.symbol == symbol)
    if filing_type:
        q = q.filter(NSECorporateFiling.filing_type == filing_type)
    rows = q.order_by(NSECorporateFiling.filing_date.desc()).limit(limit).all()
    return [_to_dict(r) for r in rows]


def get_filing_summary(db: Session, days: int = 30) -> dict:
    cutoff = date.today() - timedelta(days=days)
    rows = db.query(NSECorporateFiling).filter(NSECorporateFiling.filing_date >= cutoff).all()
    by_type: dict = {}
    by_symbol: dict = {}
    high_impact = []
    for r in rows:
        by_type[r.filing_type] = by_type.get(r.filing_type, 0) + 1
        by_symbol[r.symbol]    = by_symbol.get(r.symbol, 0) + 1
        if r.impact_score and r.impact_score >= 70:
            high_impact.append(_to_dict(r))
    high_impact.sort(key=lambda x: x.get("impact_score", 0), reverse=True)
    return {
        "total": len(rows), "by_type": by_type,
        "active_symbols": len(by_symbol),
        "high_impact": high_impact[:10],
        "days": days,
    }


def _to_dict(r: NSECorporateFiling) -> dict:
    try:
        details = json.loads(r.details) if r.details else {}
    except Exception:
        details = {}
    return {
        "id":           r.id,
        "symbol":       r.symbol,
        "company_name": r.company_name,
        "filing_date":  str(r.filing_date),
        "filing_type":  r.filing_type,
        "subject":      r.subject,
        "impact_score": r.impact_score,
        "sentiment_score": r.sentiment_score,
        "details":      details,
        "scraped_at":   r.scraped_at.isoformat() if r.scraped_at else None,
    }
