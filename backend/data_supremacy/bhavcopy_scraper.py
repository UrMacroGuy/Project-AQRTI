"""
NSE Bhavcopy Historical Backfill Scraper
=========================================
Downloads NSE daily bhavcopies (OHLCV) + MTO files (delivery volume)
for all trading dates. Fills gaps in our DailyPrice table going back to 2021.

Sources (no auth, no bot protection):
  New format (2024+): archives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_YYYYMMDD_F_0000.csv.zip
  Old format (<2024): archives.nseindia.com/content/historical/EQUITIES/YYYY/MMM/cmDDMMMYYYYbhav.csv.zip
  MTO delivery:       archives.nseindia.com/archives/equities/mto/MTO_DDMMYYYY.DAT

Column mapping (new format):
  TckrSymb → symbol, SctySrs → series, TradDt → date
  OpnPric → open, HghPric → high, LwPric → low, ClsPric → close
  LastPric → last, PrvsClsgPric → prev_close
  TtlTradgVol → volume, TtlTrfVal → turnover, TtlNbOfTxsExctd → trades
  ISIN → isin

Column mapping (old format):
  SYMBOL, SERIES, DATE, PREV CLOSE, OPEN PRICE, HIGH PRICE, LOW PRICE,
  LAST PRICE, CLOSE PRICE, AVERAGE PRICE, TOTAL TRADED QUANTITY, TURNOVER (LACS),
  NO OF TRADES, DELIVERABLE QTY, % DLY QT TO TRADED QTY
"""
from __future__ import annotations

import io
import csv
import logging
import time
import zipfile
from datetime import date, timedelta
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy import func

from aqrti.database.engine import get_db
from aqrti.database.models import DailyPrice, Stock
from aqrti.utils.logger import get_logger

log = get_logger("bhavcopy_scraper")

import requests as _requests  # always use plain requests — CDN has no bot protection


# ── URL builders ──────────────────────────────────────────────────────────────

def _bhavcopy_urls(dt: date) -> list[str]:
    dd   = dt.strftime('%d')
    mm   = dt.strftime('%m')
    mmm  = dt.strftime('%b').upper()
    yyyy = dt.strftime('%Y')
    return [
        # New format (2024 onwards)
        f'https://archives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{yyyy}{mm}{dd}_F_0000.csv.zip',
        # Old format (pre-2024)
        f'https://archives.nseindia.com/content/historical/EQUITIES/{yyyy}/{mmm}/cm{dd}{mmm}{yyyy}bhav.csv.zip',
    ]


def _mto_url(dt: date) -> str:
    dd = dt.strftime('%d'); mm = dt.strftime('%m'); yyyy = dt.strftime('%Y')
    return f'https://archives.nseindia.com/archives/equities/mto/MTO_{dd}{mm}{yyyy}.DAT'


# ── HTTP session ──────────────────────────────────────────────────────────────

def _make_session():
    s = _requests.Session()
    s.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    })
    return s


# ── Parsers ───────────────────────────────────────────────────────────────────

def _parse_bhavcopy(content: bytes) -> list[dict]:
    """Parse a bhavcopy CSV (new or old format). Returns list of EQ-series rows."""
    try:
        z     = zipfile.ZipFile(io.BytesIO(content))
        text  = z.read(z.namelist()[0]).decode('utf-8', errors='replace')
    except Exception as e:
        log.warning("Bhavcopy unzip failed: %s", e)
        return []

    reader = csv.DictReader(io.StringIO(text))
    rows   = list(reader)
    if not rows:
        return []

    # Detect format by column names
    if 'TckrSymb' in rows[0]:
        return _parse_new_format(rows)
    elif 'SYMBOL' in rows[0]:
        return _parse_old_format(rows)
    else:
        log.warning("Unknown bhavcopy format — columns: %s", list(rows[0].keys())[:6])
        return []


def _f(val: str) -> Optional[float]:
    """Safe float parse — returns None on empty/invalid."""
    v = (val or '').strip()
    if not v:
        return None
    try:
        return float(v)
    except ValueError:
        return None


def _parse_new_format(rows: list[dict]) -> list[dict]:
    result = []
    for r in rows:
        if r.get('SctySrs') != 'EQ':
            continue
        sym = (r.get('TckrSymb') or '').strip()
        if not sym:
            continue
        row_date_str = (r.get('TradDt') or r.get('BizDt') or '').strip()
        try:
            row_date = date.fromisoformat(row_date_str)
        except Exception:
            continue
        result.append({
            'symbol':          sym,
            'date':            row_date,
            'open':            _f(r.get('OpnPric')),
            'high':            _f(r.get('HghPric')),
            'low':             _f(r.get('LwPric')),
            'close':           _f(r.get('ClsPric')),
            'last':            _f(r.get('LastPric')),
            'prev_close':      _f(r.get('PrvsClsgPric')),
            'volume':          _f(r.get('TtlTradgVol')),
            'turnover':        _f(r.get('TtlTrfVal')),
            'trades':          _f(r.get('TtlNbOfTxsExctd')),
            'isin':            (r.get('ISIN') or '').strip(),
            'delivery_volume': None,
            'delivery_pct':    None,
        })
    return result


def _parse_old_format(rows: list[dict]) -> list[dict]:
    result = []
    for r in rows:
        if r.get('SERIES') != 'EQ':
            continue
        sym = (r.get('SYMBOL') or '').strip()
        if not sym:
            continue
        raw_date = (r.get('DATE1') or r.get('DATE') or r.get('TIMESTAMP') or '').strip()
        try:
            row_date = date.fromisoformat(raw_date[:10]) if len(raw_date) >= 10 and raw_date[2] == '-' and raw_date[5] == '-' else \
                       _parse_old_date(raw_date)
        except Exception:
            continue
        result.append({
            'symbol':          sym,
            'date':            row_date,
            'open':            _f(r.get('OPEN PRICE') or r.get('OPEN')),
            'high':            _f(r.get('HIGH PRICE') or r.get('HIGH')),
            'low':             _f(r.get('LOW PRICE') or r.get('LOW')),
            'close':           _f(r.get('CLOSE PRICE') or r.get('CLOSE')),
            'last':            _f(r.get('LAST PRICE') or r.get('LAST')),
            'prev_close':      _f(r.get('PREV CLOSE') or r.get('PREVCLOSE')),
            'volume':          _f(r.get('TOTAL TRADED QUANTITY') or r.get('TOTTRDQTY')),
            'turnover':        _f(r.get('TURNOVER (LACS)') or r.get('TOTTRDVAL')),
            'trades':          _f(r.get('NO OF TRADES') or r.get('TOTALTRADES')),
            'isin':            (r.get('ISIN') or '').strip(),
            'delivery_volume': _f(r.get('DELIVERABLE QTY') or r.get('DELIV_QTY')),
            'delivery_pct':    _f(r.get('% DLY QT TO TRADED QTY') or r.get('DELIV_PER')),
        })
    return result


def _parse_old_date(s: str) -> date:
    """Parse DD-Mon-YYYY, DD-MON-YYYY, DDMONYYYY, YYYY-MM-DD."""
    from datetime import datetime
    s_title = s.title() if s else s  # normalise JAN -> Jan
    for src, fmt in [(s_title, '%d-%b-%Y'), (s_title, '%d%b%Y'), (s, '%Y-%m-%d')]:
        try:
            return datetime.strptime(src, fmt).date()
        except Exception:
            pass
    raise ValueError(f"Cannot parse date: {s}")


def _parse_mto(content: bytes) -> dict[str, dict]:
    """
    Parse MTO .DAT file. Format:
    Record type, Sr No, SYMBOL, SERIES, TOTAL_TRADED_QTY, DELIVERABLE_QTY, DELIV_PCT
    Returns {symbol: {delivery_volume, delivery_pct}}
    """
    result = {}
    try:
        text = content.decode('utf-8', errors='replace')
        for line in text.splitlines():
            parts = [p.strip() for p in line.split(',')]
            if len(parts) < 7:
                continue
            # Skip header / summary lines
            if parts[0] not in ('20', '40'):
                continue
            sym         = parts[2].strip()
            series      = parts[3].strip()
            if series != 'EQ':
                continue
            total_qty   = _f(parts[4])
            deliv_qty   = _f(parts[5])
            deliv_pct   = _f(parts[6])
            result[sym] = {
                'delivery_volume': deliv_qty,
                'delivery_pct':    deliv_pct,
            }
    except Exception as e:
        log.warning("MTO parse error: %s", e)
    return result


# ── Main fetch ────────────────────────────────────────────────────────────────

def fetch_day(session, dt: date) -> tuple[list[dict], dict[str, dict]]:
    """Fetch bhavcopy + MTO for a single date. Returns (rows, mto_map)."""
    bhavcopy_data = None
    for url in _bhavcopy_urls(dt):
        try:
            r = session.get(url, timeout=15)
            if r.status_code == 200 and r.content:
                bhavcopy_data = r.content
                break
        except Exception as e:
            log.debug("Bhavcopy fetch failed %s: %s", url[-50:], e)
            continue

    if not bhavcopy_data:
        return [], {}

    rows    = _parse_bhavcopy(bhavcopy_data)
    mto_map: dict[str, dict] = {}

    try:
        mto_r = session.get(_mto_url(dt), timeout=12)
        if mto_r.status_code == 200 and mto_r.content:
            mto_map = _parse_mto(mto_r.content)
            for row in rows:
                m = mto_map.get(row['symbol'])
                if m:
                    row['delivery_volume'] = m['delivery_volume']
                    row['delivery_pct']    = m['delivery_pct']
    except Exception as e:
        log.debug("MTO fetch failed for %s: %s", dt, e)

    return rows, mto_map


# ── DB write ──────────────────────────────────────────────────────────────────

def _upsert_rows(db: Session, rows: list[dict], our_symbols: set[str]) -> tuple[int, int]:
    """
    Insert/update DailyPrice rows for symbols in our universe.
    Returns (inserted, skipped).
    """
    inserted = 0
    skipped  = 0

    for row in rows:
        sym = row['symbol']
        if sym not in our_symbols:
            skipped += 1
            continue

        dt = row['date']
        existing = db.query(DailyPrice).filter(
            DailyPrice.symbol == sym,
            DailyPrice.date   == dt,
        ).first()

        close     = row.get('close')
        prev_close = row.get('prev_close')
        daily_ret  = None
        if close and prev_close and prev_close > 0:
            daily_ret = (close - prev_close) / prev_close

        if existing:
            # Only update if we have better data
            if existing.delivery_volume is None and row.get('delivery_volume'):
                existing.delivery_volume = row['delivery_volume']
            skipped += 1
        else:
            dp = DailyPrice(
                symbol          = sym,
                date            = dt,
                open            = row.get('open'),
                high            = row.get('high'),
                low             = row.get('low'),
                close           = close,
                volume          = int(row['volume']) if row.get('volume') else None,
                delivery_volume = int(row['delivery_volume']) if row.get('delivery_volume') else None,
                daily_return    = round(daily_ret, 6) if daily_ret is not None else None,
            )
            db.add(dp)
            inserted += 1

    return inserted, skipped


# ── Public API ────────────────────────────────────────────────────────────────

def run_historical_backfill(
    from_date: date | None = None,
    to_date:   date | None = None,
    batch_commit: int = 5,
) -> dict:
    """
    Download NSE bhavcopies from from_date to to_date and fill gaps in DailyPrice.
    Defaults: from = 5 years ago, to = yesterday.
    Opens a fresh short-lived DB connection per batch to avoid holding long locks.
    """
    if from_date is None:
        from_date = date.today() - timedelta(days=365 * 5)
    if to_date is None:
        to_date = date.today() - timedelta(days=1)

    log.info("=== BHAVCOPY BACKFILL: %s to %s ===", from_date, to_date)

    # Load universe symbols in a short transaction, then close
    with get_db() as db:
        stocks = db.query(Stock).filter(Stock.active == True).all()
        our_symbols = {s.symbol for s in stocks}
    log.info("Universe: %d symbols", len(our_symbols))

    http_session = _make_session()

    total_inserted = 0
    total_errors   = 0
    dates_processed = 0
    dates_skipped   = 0

    current  = from_date
    batch    = []  # list of (date, rows) to commit together

    def _flush_batch(items):
        """Write a batch of day-rows to DB in one short transaction."""
        nonlocal total_inserted
        with get_db() as db:
            for _dt, day_rows in items:
                ins, _ = _upsert_rows(db, day_rows, our_symbols)
                total_inserted += ins

    while current <= to_date:
        # Skip weekends
        if current.weekday() >= 5:
            current += timedelta(days=1)
            continue

        try:
            rows, _ = fetch_day(http_session, current)
            if not rows:
                log.debug("No bhavcopy for %s (holiday or future)", current)
                dates_skipped += 1
                current += timedelta(days=1)
                time.sleep(0.3)
                continue

            batch.append((current, rows))
            dates_processed += 1
            log.info("Day %s: bhav_rows=%d batch_size=%d total_inserted=%d",
                     current, len(rows), len(batch), total_inserted)

            if len(batch) >= batch_commit:
                _flush_batch(batch)
                batch = []

        except Exception as e:
            log.error("Error for %s: %s", current, e)
            total_errors += 1

        current += timedelta(days=1)
        time.sleep(0.25)  # polite delay — NSE CDN rate limit

    # Flush remaining
    if batch:
        _flush_batch(batch)

    result = {
        'status':          'COMPLETED',
        'from_date':       str(from_date),
        'to_date':         str(to_date),
        'dates_processed': dates_processed,
        'dates_skipped':   dates_skipped,
        'rows_inserted':   total_inserted,
        'errors':          total_errors,
    }
    log.info("=== BACKFILL COMPLETE: %s ===", result)
    return result


def run_daily_bhavcopy(target_date: date | None = None) -> dict:
    """
    Fetch yesterday's (or target_date's) bhavcopy and upsert into DailyPrice.
    Called daily after market close as a supplement to yfinance.
    Advantage over yfinance: includes delivery volume from MTO.
    """
    dt = target_date or (date.today() - timedelta(days=1))
    # Skip weekends
    if dt.weekday() >= 5:
        return {'status': 'skipped', 'reason': 'weekend', 'date': str(dt)}

    with get_db() as db:
        stocks      = db.query(Stock).filter(Stock.active == True).all()
        our_symbols = {s.symbol for s in stocks}
        session     = _make_session()
        rows, _     = fetch_day(session, dt)

        if not rows:
            return {'status': 'error', 'date': str(dt), 'error': 'no_bhavcopy'}

        inserted, skipped = _upsert_rows(db, rows, our_symbols)
        db.commit()

    return {
        'status':   'ok',
        'date':     str(dt),
        'inserted': inserted,
        'skipped':  skipped,
        'total_rows_in_bhavcopy': len(rows),
    }
