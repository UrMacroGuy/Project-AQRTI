"""
Phase 8F — Earnings Intelligence Engine
Scrapes quarterly results from NSE corporate filings, detects beat/miss,
computes YoY/QoQ changes, tracks market reaction.
"""

from __future__ import annotations

import sys, os

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import json
import re
import time
import logging
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from aqrti.database.models import EarningsEvent, NSECorporateFiling, DailyPrice
from data_supremacy.scraper_base import (
    make_session, safe_get, safe_json, nse_headers,
    record_source_health,
)

logger = logging.getLogger("data_supremacy.earnings")

NSE_RESULTS_URL = "https://www.nseindia.com/api/corporates-financial-results"


def scrape_earnings(db: Session, from_date: date | None = None,
                    to_date: date | None = None) -> dict:
    t0 = time.time()
    if not to_date:
        to_date = date.today()
    if not from_date:
        from_date = to_date - timedelta(days=30)

    session = make_session()
    safe_get(session, "https://www.nseindia.com", headers={"Accept": "text/html"})
    time.sleep(1)

    params = {
        "index":     "equities",
        "period":    "Quarterly",
        "from_date": from_date.strftime("%d-%m-%Y"),
        "to_date":   to_date.strftime("%d-%m-%Y"),
    }
    resp = safe_get(session, NSE_RESULTS_URL, params=params, headers=nse_headers())
    data = safe_json(resp)

    stored = 0
    skipped = 0
    errors = 0

    if not data:
        # Fallback: mine from corporate filings already scraped
        stored, skipped = _mine_from_filings(db, from_date, to_date)
        record_source_health(db, "earnings", "degraded", records=stored,
                              error="NSE results API unavailable, mined from filings")
        db.commit()
        return {"status": "degraded", "stored": stored, "skipped": skipped,
                "source": "filings_fallback"}

    rows = data if isinstance(data, list) else data.get("data", [])

    for item in rows:
        try:
            symbol = (item.get("symbol") or "").upper().strip()
            if not symbol:
                continue

            raw_date = item.get("broadCastDate") or item.get("meetingDate") or ""
            try:
                earn_date = datetime.strptime(raw_date, "%d-%b-%Y").date()
            except Exception:
                earn_date = to_date

            period_str = item.get("period") or "Q"
            quarter    = item.get("periodEnded") or _infer_quarter(earn_date)

            existing = db.query(EarningsEvent).filter(
                EarningsEvent.symbol       == symbol,
                EarningsEvent.earnings_date == earn_date,
                EarningsEvent.period        == period_str,
            ).first()
            if existing:
                skipped += 1
                continue

            # Parse financials from the item
            revenue  = _parse_float(item.get("income"))
            pat      = _parse_float(item.get("profit"))
            eps      = _parse_float(item.get("eps"))

            row = EarningsEvent(
                symbol          = symbol,
                company_name    = item.get("companyName"),
                earnings_date   = earn_date,
                period          = period_str,
                quarter         = quarter,
                revenue_actual  = revenue,
                pat_actual      = pat,
                eps_actual      = eps,
                result_status   = "declared",
            )
            db.add(row)
            stored += 1

        except Exception as exc:
            errors += 1
            logger.debug("Earnings row error: %s", exc)

    db.commit()

    # Compute YoY/QoQ changes for newly added records
    _fill_yoy_qoq(db, from_date)

    # Fill market reaction for past events
    _fill_market_reaction(db, from_date)

    db.commit()

    duration_ms = int((time.time() - t0) * 1000)
    record_source_health(db, "earnings", "ok" if errors == 0 else "degraded",
                          records=stored, duration_ms=duration_ms)
    db.commit()

    return {"status": "ok", "stored": stored, "skipped": skipped, "errors": errors}


def _mine_from_filings(db: Session, from_date: date, to_date: date) -> tuple[int, int]:
    filings = db.query(NSECorporateFiling).filter(
        NSECorporateFiling.filing_type == "results",
        NSECorporateFiling.filing_date.between(from_date, to_date),
    ).all()

    stored = 0
    skipped = 0
    for f in filings:
        q = _infer_quarter(f.filing_date)
        existing = db.query(EarningsEvent).filter(
            EarningsEvent.symbol        == f.symbol,
            EarningsEvent.earnings_date == f.filing_date,
        ).first()
        if existing:
            skipped += 1
            continue
        row = EarningsEvent(
            symbol         = f.symbol,
            company_name   = f.company_name,
            earnings_date  = f.filing_date,
            period         = "Quarterly",
            quarter        = q,
            result_status  = "declared",
        )
        db.add(row)
        stored += 1
    return stored, skipped


def _fill_yoy_qoq(db: Session, from_date: date) -> None:
    events = db.query(EarningsEvent).filter(
        EarningsEvent.earnings_date >= from_date,
        EarningsEvent.pat_actual.isnot(None),
    ).all()

    for ev in events:
        # YoY: same quarter last year
        yoy_cutoff_start = ev.earnings_date - timedelta(days=400)
        yoy_cutoff_end   = ev.earnings_date - timedelta(days=270)
        yoy = db.query(EarningsEvent).filter(
            EarningsEvent.symbol == ev.symbol,
            EarningsEvent.earnings_date.between(yoy_cutoff_start, yoy_cutoff_end),
            EarningsEvent.pat_actual.isnot(None),
        ).order_by(EarningsEvent.earnings_date.desc()).first()

        if yoy and yoy.pat_actual and yoy.pat_actual != 0:
            ev.pat_yoy_pct = round((ev.pat_actual - yoy.pat_actual) / abs(yoy.pat_actual) * 100, 2)
        if yoy and yoy.revenue_actual and yoy.revenue_actual != 0 and ev.revenue_actual:
            ev.revenue_yoy_pct = round((ev.revenue_actual - yoy.revenue_actual) / abs(yoy.revenue_actual) * 100, 2)
        if yoy and yoy.eps_actual and yoy.eps_actual != 0 and ev.eps_actual:
            ev.eps_yoy_pct = round((ev.eps_actual - yoy.eps_actual) / abs(yoy.eps_actual) * 100, 2)

        # QoQ: previous quarter (~90 days back)
        qoq = db.query(EarningsEvent).filter(
            EarningsEvent.symbol == ev.symbol,
            EarningsEvent.earnings_date.between(
                ev.earnings_date - timedelta(days=130),
                ev.earnings_date - timedelta(days=60),
            ),
            EarningsEvent.pat_actual.isnot(None),
        ).order_by(EarningsEvent.earnings_date.desc()).first()

        if qoq and qoq.pat_actual and qoq.pat_actual != 0 and ev.pat_actual:
            ev.pat_qoq_pct = round((ev.pat_actual - qoq.pat_actual) / abs(qoq.pat_actual) * 100, 2)
        if qoq and qoq.revenue_actual and qoq.revenue_actual != 0 and ev.revenue_actual:
            ev.revenue_qoq_pct = round((ev.revenue_actual - qoq.revenue_actual) / abs(qoq.revenue_actual) * 100, 2)


def _fill_market_reaction(db: Session, from_date: date) -> None:
    events = db.query(EarningsEvent).filter(
        EarningsEvent.earnings_date >= from_date,
        EarningsEvent.price_reaction_1d.is_(None),
    ).all()

    for ev in events:
        next_day = ev.earnings_date + timedelta(days=1)
        p_next   = db.query(DailyPrice).filter(
            DailyPrice.symbol == ev.symbol,
            DailyPrice.date   == next_day,
        ).first()
        if p_next and p_next.daily_return is not None:
            ev.price_reaction_1d = round(p_next.daily_return, 3)  # already stored as %


def _infer_quarter(d: date) -> str:
    m = d.month
    y = d.year
    if m <= 3:   return f"Q4FY{y}"      # Jan-Mar belongs to Q4 of FY ending that year
    if m <= 6:   return f"Q1FY{y+1}"
    if m <= 9:   return f"Q2FY{y+1}"
    return f"Q3FY{y+1}"


def _parse_float(v) -> float | None:
    if v is None:
        return None
    try:
        return float(str(v).replace(",", "").strip())
    except Exception:
        return None


def get_earnings_calendar(db: Session, days_ahead: int = 14) -> list[dict]:
    cutoff = date.today() + timedelta(days=days_ahead)
    rows = db.query(EarningsEvent).filter(
        EarningsEvent.earnings_date.between(date.today(), cutoff),
        EarningsEvent.result_status == "scheduled",
    ).order_by(EarningsEvent.earnings_date.asc()).all()
    return [_to_dict(r) for r in rows]


def get_recent_results(db: Session, days: int = 30, beat_miss: str | None = None,
                        limit: int = 100) -> list[dict]:
    cutoff = date.today() - timedelta(days=days)
    q = db.query(EarningsEvent).filter(
        EarningsEvent.earnings_date >= cutoff,
        EarningsEvent.result_status == "declared",
    )
    if beat_miss:
        q = q.filter(EarningsEvent.beat_miss == beat_miss)
    rows = q.order_by(EarningsEvent.earnings_date.desc()).limit(limit).all()
    return [_to_dict(r) for r in rows]


def get_earnings_summary(db: Session, days: int = 90) -> dict:
    cutoff = date.today() - timedelta(days=days)
    rows = db.query(EarningsEvent).filter(
        EarningsEvent.earnings_date >= cutoff,
        EarningsEvent.result_status == "declared",
    ).all()

    by_beat: dict[str, int] = {}
    high_surprise = []
    for r in rows:
        bm = r.beat_miss or "UNKNOWN"
        by_beat[bm] = by_beat.get(bm, 0) + 1
        if r.surprise_pct and abs(r.surprise_pct) >= 15:
            high_surprise.append(_to_dict(r))

    high_surprise.sort(key=lambda x: abs(x.get("surprise_pct") or 0), reverse=True)
    return {
        "total":        len(rows),
        "by_beat_miss": by_beat,
        "beat_rate":    round(by_beat.get("BEAT", 0) / max(len(rows), 1) * 100, 1),
        "high_surprise":high_surprise[:10],
        "days":         days,
    }


def _to_dict(r: EarningsEvent) -> dict:
    return {
        "id":                r.id,
        "symbol":            r.symbol,
        "company_name":      r.company_name,
        "earnings_date":     str(r.earnings_date),
        "quarter":           r.quarter,
        "period":            r.period,
        "revenue_actual":    r.revenue_actual,
        "pat_actual":        r.pat_actual,
        "eps_actual":        r.eps_actual,
        "revenue_yoy_pct":   r.revenue_yoy_pct,
        "pat_yoy_pct":       r.pat_yoy_pct,
        "eps_yoy_pct":       r.eps_yoy_pct,
        "revenue_qoq_pct":   r.revenue_qoq_pct,
        "pat_qoq_pct":       r.pat_qoq_pct,
        "beat_miss":         r.beat_miss,
        "surprise_pct":      r.surprise_pct,
        "price_reaction_1d": r.price_reaction_1d,
        "price_reaction_5d": r.price_reaction_5d,
        "result_status":     r.result_status,
    }
