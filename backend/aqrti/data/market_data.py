"""
AQRTI Market Data Pipeline
Downloads OHLCV + index data from Yahoo Finance (yfinance).
Stores to daily_prices and index_data tables.
Computes daily returns and basic derived fields.
"""

from __future__ import annotations

from contextlib import redirect_stderr
from datetime import date, datetime, timedelta
from io import StringIO
from typing import Optional

import pandas as pd
import yfinance as yf
from sqlalchemy.orm import Session
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from aqrti.config.settings import get_settings
from aqrti.database.engine import get_db
from aqrti.database.models import DailyPrice, IndexData, Stock
from aqrti.utils.logger import data_logger


# ── Stock Universe Seed Data ──────────────────────────────────
STOCK_META: dict[str, dict] = {
    # ── Original 20 ───────────────────────────────────────────────
    "RELIANCE":   {"name": "Reliance Industries Ltd",         "sector": "Energy",       "industry": "Oil & Gas",          "nifty": True},
    "TCS":        {"name": "Tata Consultancy Services Ltd",   "sector": "IT",           "industry": "IT Services",         "nifty": True},
    "INFY":       {"name": "Infosys Ltd",                     "sector": "IT",           "industry": "IT Services",         "nifty": True},
    "HDFCBANK":   {"name": "HDFC Bank Ltd",                   "sector": "Banking",      "industry": "Private Bank",        "nifty": True},
    "ICICIBANK":  {"name": "ICICI Bank Ltd",                  "sector": "Banking",      "industry": "Private Bank",        "nifty": True},
    "WIPRO":      {"name": "Wipro Ltd",                       "sector": "IT",           "industry": "IT Services",         "nifty": True},
    "AXISBANK":   {"name": "Axis Bank Ltd",                   "sector": "Banking",      "industry": "Private Bank",        "nifty": True},
    "NESTLEIND":  {"name": "Nestle India Ltd",                "sector": "FMCG",         "industry": "Food Products",       "nifty": True},
    "BAJFINANCE": {"name": "Bajaj Finance Ltd",               "sector": "NBFC",         "industry": "Finance",             "nifty": True},
    "MARUTI":     {"name": "Maruti Suzuki India Ltd",         "sector": "Auto",         "industry": "Automobiles",         "nifty": True},
    "SUNPHARMA":  {"name": "Sun Pharmaceutical Industries",   "sector": "Pharma",       "industry": "Pharmaceuticals",     "nifty": True},
    "TATASTEEL":  {"name": "Tata Steel Ltd",                  "sector": "Metal",        "industry": "Steel",               "nifty": True},
    "KOTAKBANK":  {"name": "Kotak Mahindra Bank Ltd",         "sector": "Banking",      "industry": "Private Bank",        "nifty": True},
    "TITAN":      {"name": "Titan Company Ltd",               "sector": "Consumer",     "industry": "Consumer Durables",   "nifty": True},
    "ONGC":       {"name": "Oil & Natural Gas Corporation",   "sector": "Energy",       "industry": "Oil & Gas",           "nifty": True},
    "HINDALCO":   {"name": "Hindalco Industries Ltd",         "sector": "Metal",        "industry": "Aluminium",           "nifty": True},
    "SBIN":       {"name": "State Bank of India",             "sector": "Banking",      "industry": "PSU Bank",            "nifty": True},
    "BHARTIARTL": {"name": "Bharti Airtel Ltd",               "sector": "Telecom",      "industry": "Telecom",             "nifty": True},
    # ── Expanded 30 (top NIFTY50 by market cap) ──────────────────
    "HCLTECH":    {"name": "HCL Technologies Ltd",            "sector": "IT",           "industry": "IT Services",         "nifty": True},
    "ITC":        {"name": "ITC Ltd",                         "sector": "FMCG",         "industry": "Cigarettes & FMCG",   "nifty": True},
    "LT":         {"name": "Larsen & Toubro Ltd",             "sector": "Infra",        "industry": "Engineering",         "nifty": True},
    "HINDUNILVR": {"name": "Hindustan Unilever Ltd",          "sector": "FMCG",         "industry": "Personal Products",   "nifty": True},
    "ULTRACEMCO": {"name": "UltraTech Cement Ltd",            "sector": "Cement",       "industry": "Cement",              "nifty": True},
    "BAJAJFINSV": {"name": "Bajaj Finserv Ltd",               "sector": "NBFC",         "industry": "Insurance",           "nifty": True},
    "NTPC":       {"name": "NTPC Ltd",                        "sector": "Power",        "industry": "Power Generation",    "nifty": True},
    "ADANIENT":   {"name": "Adani Enterprises Ltd",           "sector": "Conglomerate", "industry": "Diversified",         "nifty": True},
    "ADANIPORTS": {"name": "Adani Ports & SEZ Ltd",           "sector": "Infra",        "industry": "Ports",               "nifty": True},
    "JSWSTEEL":   {"name": "JSW Steel Ltd",                   "sector": "Metal",        "industry": "Steel",               "nifty": True},
    "TECHM":      {"name": "Tech Mahindra Ltd",               "sector": "IT",           "industry": "IT Services",         "nifty": True},
    "COALINDIA":  {"name": "Coal India Ltd",                  "sector": "Energy",       "industry": "Coal",                "nifty": True},
    "BPCL":       {"name": "Bharat Petroleum Corp Ltd",       "sector": "Energy",       "industry": "Oil & Gas",           "nifty": True},
    "HDFCLIFE":   {"name": "HDFC Life Insurance Co Ltd",      "sector": "Insurance",    "industry": "Life Insurance",      "nifty": True},
    "SBILIFE":    {"name": "SBI Life Insurance Co Ltd",       "sector": "Insurance",    "industry": "Life Insurance",      "nifty": True},
    "INDUSINDBK": {"name": "IndusInd Bank Ltd",               "sector": "Banking",      "industry": "Private Bank",        "nifty": True},
    "M&M":        {"name": "Mahindra & Mahindra Ltd",         "sector": "Auto",         "industry": "Automobiles",         "nifty": True},
    "DIVISLAB":   {"name": "Divi's Laboratories Ltd",         "sector": "Pharma",       "industry": "Pharmaceuticals",     "nifty": True},
    "DRREDDY":    {"name": "Dr. Reddy's Laboratories Ltd",    "sector": "Pharma",       "industry": "Pharmaceuticals",     "nifty": True},
    "EICHERMOT":  {"name": "Eicher Motors Ltd",               "sector": "Auto",         "industry": "Motorcycles",         "nifty": True},
    "HEROMOTOCO": {"name": "Hero MotoCorp Ltd",               "sector": "Auto",         "industry": "Motorcycles",         "nifty": True},
    "CIPLA":      {"name": "Cipla Ltd",                       "sector": "Pharma",       "industry": "Pharmaceuticals",     "nifty": True},
    "BRITANNIA":  {"name": "Britannia Industries Ltd",        "sector": "FMCG",         "industry": "Food Products",       "nifty": True},
    "APOLLOHOSP": {"name": "Apollo Hospitals Enterprise Ltd", "sector": "Healthcare",   "industry": "Hospitals",           "nifty": True},
    "TRENT":      {"name": "Trent Ltd",                       "sector": "Consumer",     "industry": "Retail",              "nifty": True},
    "GRASIM":     {"name": "Grasim Industries Ltd",           "sector": "Cement",       "industry": "Diversified",         "nifty": True},
    "SHREECEM":   {"name": "Shree Cement Ltd",                "sector": "Cement",       "industry": "Cement",              "nifty": True},
    "BEL":        {"name": "Bharat Electronics Ltd",          "sector": "Defence",      "industry": "Electronics",         "nifty": True},
    "POWERGRID":  {"name": "Power Grid Corporation of India", "sector": "Power",        "industry": "Power Transmission",  "nifty": True},
    "ASIANPAINT": {"name": "Asian Paints Ltd",                "sector": "Consumer",     "industry": "Paints",              "nifty": True},
    # ── NSE Extended Universe ─────────────────────────────────────
    "MPHASIS":    {"name": "Mphasis Ltd",                        "sector": "IT",           "industry": "IT Services",         "nifty": False},
    "PERSISTENT": {"name": "Persistent Systems Ltd",             "sector": "IT",           "industry": "IT Services",         "nifty": False},
    "COFORGE":    {"name": "Coforge Ltd",                        "sector": "IT",           "industry": "IT Services",         "nifty": False},
    "LTTS":       {"name": "L&T Technology Services Ltd",        "sector": "IT",           "industry": "IT Services",         "nifty": False},
    "BAJAJ-AUTO": {"name": "Bajaj Auto Ltd",                     "sector": "Auto",         "industry": "Two Wheelers",        "nifty": False},
    "TVSMOTOR":   {"name": "TVS Motor Company Ltd",              "sector": "Auto",         "industry": "Two Wheelers",        "nifty": False},
    "BOSCHLTD":   {"name": "Bosch Ltd",                          "sector": "Auto",         "industry": "Auto Components",     "nifty": False},
    "MOTHERSON":  {"name": "Samvardhana Motherson International","sector": "Auto",         "industry": "Auto Components",     "nifty": False},
    "BANDHANBNK": {"name": "Bandhan Bank Ltd",                   "sector": "Banking",      "industry": "Private Bank",        "nifty": False},
    "FEDERALBNK": {"name": "Federal Bank Ltd",                   "sector": "Banking",      "industry": "Private Bank",        "nifty": False},
    "IDFCFIRSTB": {"name": "IDFC First Bank Ltd",                "sector": "Banking",      "industry": "Private Bank",        "nifty": False},
    "BANKBARODA": {"name": "Bank of Baroda",                     "sector": "Banking",      "industry": "PSU Bank",            "nifty": False},
    "PNB":        {"name": "Punjab National Bank",               "sector": "Banking",      "industry": "PSU Bank",            "nifty": False},
    "CANBK":      {"name": "Canara Bank",                        "sector": "Banking",      "industry": "PSU Bank",            "nifty": False},
    "UNIONBANK":  {"name": "Union Bank of India",                "sector": "Banking",      "industry": "PSU Bank",            "nifty": False},
    "CHOLAFIN":   {"name": "Cholamandalam Investment & Finance", "sector": "NBFC",         "industry": "Finance",             "nifty": False},
    "MUTHOOTFIN": {"name": "Muthoot Finance Ltd",                "sector": "NBFC",         "industry": "Finance",             "nifty": False},
    "AUROPHARMA": {"name": "Aurobindo Pharma Ltd",               "sector": "Pharma",       "industry": "Pharmaceuticals",     "nifty": False},
    "LUPIN":      {"name": "Lupin Ltd",                          "sector": "Pharma",       "industry": "Pharmaceuticals",     "nifty": False},
    "TORNTPHARM": {"name": "Torrent Pharmaceuticals Ltd",        "sector": "Pharma",       "industry": "Pharmaceuticals",     "nifty": False},
    "ALKEM":      {"name": "Alkem Laboratories Ltd",             "sector": "Pharma",       "industry": "Pharmaceuticals",     "nifty": False},
    "DABUR":      {"name": "Dabur India Ltd",                    "sector": "FMCG",         "industry": "FMCG",                "nifty": False},
    "MARICO":     {"name": "Marico Ltd",                         "sector": "FMCG",         "industry": "FMCG",                "nifty": False},
    "COLPAL":     {"name": "Colgate-Palmolive (India) Ltd",      "sector": "FMCG",         "industry": "FMCG",                "nifty": False},
    "GODREJCP":   {"name": "Godrej Consumer Products Ltd",       "sector": "FMCG",         "industry": "FMCG",                "nifty": False},
    "EMAMILTD":   {"name": "Emami Ltd",                          "sector": "FMCG",         "industry": "FMCG",                "nifty": False},
    "TATACONSUM": {"name": "Tata Consumer Products Ltd",         "sector": "FMCG",         "industry": "Food Products",       "nifty": False},
    "VEDL":       {"name": "Vedanta Ltd",                        "sector": "Metal",        "industry": "Diversified Metals",  "nifty": False},
    "NATIONALUM": {"name": "National Aluminium Company Ltd",     "sector": "Metal",        "industry": "Aluminium",           "nifty": False},
    "SAIL":       {"name": "Steel Authority of India Ltd",       "sector": "Metal",        "industry": "Steel",               "nifty": False},
    "HINDCOPPER": {"name": "Hindustan Copper Ltd",               "sector": "Metal",        "industry": "Copper",              "nifty": False},
    "IOC":        {"name": "Indian Oil Corporation Ltd",         "sector": "Energy",       "industry": "Oil & Gas",           "nifty": False},
    "GAIL":       {"name": "GAIL (India) Ltd",                   "sector": "Energy",       "industry": "Gas Distribution",    "nifty": False},
    "ADANIPOWER": {"name": "Adani Power Ltd",                    "sector": "Utilities",    "industry": "Power Generation",    "nifty": False},
    "ADANIGREEN": {"name": "Adani Green Energy Ltd",             "sector": "Utilities",    "industry": "Solar",               "nifty": False},
    "DMART":      {"name": "Avenue Supermarts Ltd",              "sector": "Retail",       "industry": "Supermarkets",        "nifty": False},
    "NYKAA":      {"name": "FSN E-Commerce Ventures Ltd",        "sector": "Retail",       "industry": "Online Retail",       "nifty": False},
    "ZOMATO":     {"name": "Zomato Ltd",                         "sector": "Technology",   "industry": "Internet Services",   "nifty": False},
    "PAYTM":      {"name": "One 97 Communications Ltd",          "sector": "Fintech",      "industry": "Digital Payments",    "nifty": False},
    "POLICYBZR":  {"name": "PB Fintech Ltd",                     "sector": "Fintech",      "industry": "Insurance Tech",      "nifty": False},
    "IRCTC":      {"name": "IRCTC Ltd",                          "sector": "Services",     "industry": "Travel",              "nifty": False},
    "INDHOTEL":   {"name": "Indian Hotels Co Ltd",               "sector": "Services",     "industry": "Hotels",              "nifty": False},
    "HAL":        {"name": "Hindustan Aeronautics Ltd",          "sector": "Defence",      "industry": "Aerospace & Defense", "nifty": False},
    "BHEL":       {"name": "Bharat Heavy Electricals Ltd",       "sector": "Industrials",  "industry": "Heavy Engineering",   "nifty": False},
    "SIEMENS":    {"name": "Siemens India Ltd",                  "sector": "Industrials",  "industry": "Electrical Equipment","nifty": False},
    "ABB":        {"name": "ABB India Ltd",                      "sector": "Industrials",  "industry": "Electrical Equipment","nifty": False},
    "AIAENG":     {"name": "AIA Engineering Ltd",                "sector": "Industrials",  "industry": "Industrial Machinery","nifty": False},
    "GRINDWELL":  {"name": "Grindwell Norton Ltd",               "sector": "Industrials",  "industry": "Abrasives",           "nifty": False},
    "PIIND":      {"name": "PI Industries Ltd",                  "sector": "Chemicals",    "industry": "Agrochemicals",       "nifty": False},
    "UPL":        {"name": "UPL Ltd",                            "sector": "Chemicals",    "industry": "Agrochemicals",       "nifty": False},
    "SRF":        {"name": "SRF Ltd",                            "sector": "Chemicals",    "industry": "Specialty Chemicals", "nifty": False},
    "AARTIIND":   {"name": "Aarti Industries Ltd",               "sector": "Chemicals",    "industry": "Specialty Chemicals", "nifty": False},
    "DEEPAKNTR":  {"name": "Deepak Nitrite Ltd",                 "sector": "Chemicals",    "industry": "Specialty Chemicals", "nifty": False},
    "NAVINFLUOR": {"name": "Navin Fluorine International Ltd",   "sector": "Chemicals",    "industry": "Specialty Chemicals", "nifty": False},
    "PHOENIXLTD": {"name": "Phoenix Mills Ltd",                  "sector": "Real Estate",  "industry": "Retail REITs",        "nifty": False},
    "OBEROIRLTY": {"name": "Oberoi Realty Ltd",                  "sector": "Real Estate",  "industry": "Real Estate",         "nifty": False},
    "GODREJPROP": {"name": "Godrej Properties Ltd",              "sector": "Real Estate",  "industry": "Real Estate",         "nifty": False},
    "PRESTIGE":   {"name": "Prestige Estates Projects Ltd",      "sector": "Real Estate",  "industry": "Real Estate",         "nifty": False},
    "DLF":        {"name": "DLF Ltd",                            "sector": "Real Estate",  "industry": "Real Estate",         "nifty": False},
}

INDEX_META: dict[str, str] = {
    "^NSEI":    "NIFTY50",
    "^NSEBANK": "BANKNIFTY",
}

LEGACY_SYMBOLS: set[str] = {"LTIM", "TATAMOTORS", "LTM", "TMPV"}


# ══════════════════════════════════════════════════════════════
# SEED UNIVERSE
# ══════════════════════════════════════════════════════════════
def seed_stock_universe(db: Session) -> None:
    """Insert stock metadata rows if not already present."""
    for symbol, meta in STOCK_META.items():
        existing = db.query(Stock).filter_by(symbol=symbol).first()
        if not existing:
            db.add(Stock(
                symbol       = symbol,
                name         = meta["name"],
                sector       = meta["sector"],
                industry     = meta["industry"],
                nifty_member = meta["nifty"],
                active       = True,
            ))
        else:
            existing.name = meta["name"]
            existing.sector = meta["sector"]
            existing.industry = meta["industry"]
            existing.nifty_member = meta["nifty"]
            existing.active = True
    for symbol in LEGACY_SYMBOLS:
        existing = db.query(Stock).filter_by(symbol=symbol).first()
        if existing:
            existing.active = False
    db.commit()
    data_logger.info("Stock universe seeded — %d stocks.", len(STOCK_META))


# ══════════════════════════════════════════════════════════════
# DOWNLOAD HELPERS
# ══════════════════════════════════════════════════════════════
def _latest_date_in_db(db: Session, symbol: str) -> Optional[date]:
    row = (
        db.query(DailyPrice.date)
        .filter(DailyPrice.symbol == symbol)
        .order_by(DailyPrice.date.desc())
        .first()
    )
    return row[0] if row else None


def _latest_index_date(db: Session, index_name: str) -> Optional[date]:
    row = (
        db.query(IndexData.date)
        .filter(IndexData.index_name == index_name)
        .order_by(IndexData.date.desc())
        .first()
    )
    return row[0] if row else None


def _compute_returns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values("Date")
    df["daily_return"] = df["Close"].pct_change(fill_method=None) * 100
    return df


def _valid_price_row(symbol: str, row, close_val: float) -> bool:
    """
    Sanity-check one OHLCV row before insert. Rejects impossible bars
    (non-positive prices, high < low, close outside [low, high] range,
    negative volume). Logs and flags — extreme moves (>25%) are kept but
    logged as possible split artifacts.
    """
    o = _safe_float(row.get("Open"))
    h = _safe_float(row.get("High"))
    l = _safe_float(row.get("Low"))
    v = _safe_float(row.get("Volume"))

    if close_val <= 0:
        data_logger.warning("%s: rejected row (close<=0: %s)", symbol, close_val)
        return False
    if h is not None and l is not None:
        if h < l:
            data_logger.warning("%s: rejected row (high %s < low %s)", symbol, h, l)
            return False
        # allow tiny float tolerance
        if close_val > h * 1.001 or close_val < l * 0.999:
            data_logger.warning("%s: rejected row (close %s outside [%s, %s])", symbol, close_val, l, h)
            return False
    if (o is not None and o <= 0) or (h is not None and h <= 0) or (l is not None and l <= 0):
        data_logger.warning("%s: rejected row (non-positive OHLC)", symbol)
        return False
    if v is not None and v < 0:
        data_logger.warning("%s: rejected row (negative volume %s)", symbol, v)
        return False

    ret = _safe_float(row.get("daily_return"))
    if ret is not None and abs(ret) > 25:
        data_logger.warning("%s: extreme move %.1f%% on %s — possible split artifact, kept but flagged",
                            symbol, ret, row.get("Date"))
    return True


# ══════════════════════════════════════════════════════════════
# DOWNLOAD STOCK PRICES
# ══════════════════════════════════════════════════════════════
def download_stock_prices(
    db: Session,
    symbols_ns: list[str],
    start_override: Optional[date] = None,
) -> dict[str, int]:
    """
    Download OHLCV for each symbol.
    Returns {symbol: rows_inserted}.
    Performs incremental updates — only fetches dates after last stored date.
    """
    results: dict[str, int] = {}
    settings = get_settings()

    for ticker_ns in symbols_ns:
        symbol = ticker_ns.replace(".NS", "")
        try:
            # No SELECT-then-INSERT: always fetch a recent window and rely on
            # ON CONFLICT to handle any existing rows. The old _latest_date_in_db
            # check created a race condition when two processes ran concurrently.
            fetch_start = start_override or (date.today() - timedelta(days=5))

            if fetch_start > date.today():
                data_logger.debug("%s: skip (fetch_start after today).", symbol)
                results[symbol] = 0
                continue

            data_logger.info("Downloading %s from %s …", ticker_ns, fetch_start)
            yf_stderr = StringIO()
            with redirect_stderr(yf_stderr):
                df = yf.download(
                    ticker_ns,
                    start=str(fetch_start),
                    end=str(date.today() + timedelta(days=1)),
                    progress=False,
                    auto_adjust=True,
                )
            yf_noise = yf_stderr.getvalue().strip()
            if yf_noise:
                data_logger.debug("%s yfinance detail: %s", ticker_ns, yf_noise)

            if df.empty:
                data_logger.warning("%s: no data returned.", ticker_ns)
                results[symbol] = 0
                continue

            df = df.reset_index()
            # yfinance multi-level columns when downloading single ticker
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)

            df = _compute_returns(df)
            rows_inserted = 0

            for _, row in df.iterrows():
                close_val = _safe_float(row.get("Close"))
                if close_val is None:
                    continue  # skip incomplete/in-progress trading day
                if not _valid_price_row(symbol, row, close_val):
                    continue  # bad OHLC — logged inside the validator
                row_date = row["Date"].date() if hasattr(row["Date"], "date") else row["Date"]
                stmt = sqlite_insert(DailyPrice).values(
                    symbol       = symbol,
                    date         = row_date,
                    open         = _safe_float(row.get("Open")),
                    high         = _safe_float(row.get("High")),
                    low          = _safe_float(row.get("Low")),
                    close        = close_val,
                    adj_close    = close_val,
                    volume       = _safe_float(row.get("Volume")),
                    daily_return = _safe_float(row.get("daily_return")),
                ).on_conflict_do_update(
                    index_elements=["symbol", "date"],
                    set_={
                        "open":         _safe_float(row.get("Open")),
                        "high":         _safe_float(row.get("High")),
                        "low":          _safe_float(row.get("Low")),
                        "close":        close_val,
                        "adj_close":    close_val,
                        "volume":       _safe_float(row.get("Volume")),
                        "daily_return": _safe_float(row.get("daily_return")),
                    }
                )
                db.execute(stmt)
                rows_inserted += 1

            db.commit()
            results[symbol] = rows_inserted
            data_logger.info("%s: inserted/updated %d rows.", symbol, rows_inserted)

        except Exception as exc:
            db.rollback()
            data_logger.error("%s download failed: %s", ticker_ns, exc)
            results[symbol] = -1

    return results


# ══════════════════════════════════════════════════════════════
# DOWNLOAD INDEX DATA
# ══════════════════════════════════════════════════════════════
def download_index_data(db: Session, start_override: Optional[date] = None) -> dict[str, int]:
    """Download NIFTY50 and BANKNIFTY OHLCV data."""
    results: dict[str, int] = {}

    for ticker, index_name in INDEX_META.items():
        try:
            # No SELECT-then-INSERT; rely on ON CONFLICT for dedup.
            fetch_start = start_override or (date.today() - timedelta(days=5))

            if fetch_start > date.today():
                results[index_name] = 0
                continue

            data_logger.info("Downloading index %s from %s …", index_name, fetch_start)
            yf_stderr = StringIO()
            with redirect_stderr(yf_stderr):
                df = yf.download(
                    ticker,
                    start=str(fetch_start),
                    end=str(date.today() + timedelta(days=1)),
                    progress=False,
                    auto_adjust=True,
                )
            yf_noise = yf_stderr.getvalue().strip()
            if yf_noise:
                data_logger.debug("%s yfinance detail: %s", ticker, yf_noise)

            if df.empty:
                data_logger.warning("%s: no index data.", index_name)
                results[index_name] = 0
                continue

            df = df.reset_index()
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)

            df = _compute_returns(df)
            rows_inserted = 0

            for _, row in df.iterrows():
                close_val = _safe_float(row.get("Close"))
                if close_val is None:
                    continue  # skip incomplete day
                row_date = row["Date"].date() if hasattr(row["Date"], "date") else row["Date"]
                from sqlalchemy.dialects.sqlite import insert as _sqlite_insert
                stmt = _sqlite_insert(IndexData).values(
                    index_name = index_name,
                    date       = row_date,
                    open       = _safe_float(row.get("Open")),
                    high       = _safe_float(row.get("High")),
                    low        = _safe_float(row.get("Low")),
                    close      = close_val,
                    volume     = _safe_float(row.get("Volume")),
                    returns    = _safe_float(row.get("daily_return")),
                ).on_conflict_do_update(
                    index_elements=["index_name", "date"],
                    set_={
                        "open":    _safe_float(row.get("Open")),
                        "high":    _safe_float(row.get("High")),
                        "low":     _safe_float(row.get("Low")),
                        "close":   close_val,
                        "volume":  _safe_float(row.get("Volume")),
                        "returns": _safe_float(row.get("daily_return")),
                    }
                )
                db.execute(stmt)
                rows_inserted += 1

            db.commit()
            results[index_name] = rows_inserted
            data_logger.info("%s: inserted/updated %d rows.", index_name, rows_inserted)

        except Exception as exc:
            db.rollback()
            data_logger.error("%s index download failed: %s", index_name, exc)
            results[index_name] = -1

    return results


# ══════════════════════════════════════════════════════════════
# FULL DAILY INGESTION
# ══════════════════════════════════════════════════════════════
def run_daily_ingestion(start_override: Optional[date] = None) -> dict:
    """
    Master ingestion function — called by scheduler after market close.
    Step 1: Download market data
    Step 2: Download index data
    Step 3: Seed universe if needed
    Returns summary report.
    """
    settings = get_settings()
    data_logger.info("=== DAILY INGESTION STARTED ===")

    with get_db() as db:
        seed_stock_universe(db)
        stock_results  = download_stock_prices(db, settings.universe_list, start_override)
        index_results  = download_index_data(db, start_override)

    total_stock_rows = sum(v for v in stock_results.values() if v > 0)
    total_index_rows = sum(v for v in index_results.values() if v > 0)
    errors           = [k for k, v in {**stock_results, **index_results}.items() if v == -1]

    report = {
        "timestamp": datetime.utcnow().isoformat(),
        "stocks_updated": total_stock_rows,
        "indices_updated": total_index_rows,
        "errors": errors,
        "status": "COMPLETED" if not errors else "COMPLETED_WITH_ERRORS",
    }
    data_logger.info("=== DAILY INGESTION %s | stocks:%d idx:%d errors:%d ===",
                     report["status"], total_stock_rows, total_index_rows, len(errors))
    return report


def run_new_symbol_backfill(years: int = 3) -> dict:
    """
    Download full history for any symbol in the universe that has no price data yet.
    Called once on boot after universe is expanded; safe to call repeatedly (no-op for
    symbols already in DB).
    """
    from datetime import timedelta
    settings = get_settings()
    backfill_start = date.today() - timedelta(days=years * 365)
    data_logger.info("=== NEW SYMBOL BACKFILL START (from %s) ===", backfill_start)

    new_symbols: list[str] = []
    with get_db() as db:
        seed_stock_universe(db)
        for ticker_ns in settings.universe_list:
            symbol = ticker_ns.replace(".NS", "")
            if not _latest_date_in_db(db, symbol):
                new_symbols.append(ticker_ns)

    if not new_symbols:
        data_logger.info("No new symbols to backfill.")
        return {"backfilled": 0, "symbols": []}

    data_logger.info("Backfilling %d new symbols: %s", len(new_symbols), new_symbols)
    with get_db() as db:
        results = download_stock_prices(db, new_symbols, start_override=backfill_start)

    total = sum(v for v in results.values() if v > 0)
    errors = [k for k, v in results.items() if v == -1]
    data_logger.info("=== BACKFILL DONE | rows=%d errors=%d ===", total, len(errors))
    return {"backfilled": total, "symbols": [s.replace(".NS", "") for s in new_symbols], "errors": errors}


# ══════════════════════════════════════════════════════════════
# QUERY HELPERS (used by API routes)
# ══════════════════════════════════════════════════════════════
def get_latest_prices(db: Session, symbols: list[str]) -> dict[str, dict]:
    """Return latest OHLCV row for each symbol."""
    result = {}
    for symbol in symbols:
        row = (
            db.query(DailyPrice)
            .filter(DailyPrice.symbol == symbol)
            .order_by(DailyPrice.date.desc())
            .first()
        )
        if row:
            result[symbol] = {
                "symbol":       row.symbol,
                "date":         str(row.date),
                "open":         row.open,
                "high":         row.high,
                "low":          row.low,
                "close":        row.close,
                "volume":       row.volume,
                "daily_return": row.daily_return,
            }
    return result


def get_price_history(
    db: Session,
    symbol: str,
    days: int = 30,
) -> list[dict]:
    """Return last N days of OHLCV for a symbol, oldest first."""
    cutoff = date.today() - timedelta(days=days)
    rows = (
        db.query(DailyPrice)
        .filter(DailyPrice.symbol == symbol, DailyPrice.date >= cutoff)
        .order_by(DailyPrice.date.asc())
        .all()
    )
    return [
        {
            "date":         str(r.date),
            "open":         r.open,
            "high":         r.high,
            "low":          r.low,
            "close":        r.close,
            "volume":       r.volume,
            "daily_return": r.daily_return,
        }
        for r in rows
    ]


_INDEX_YF_MAP = {"NIFTY50": "^NSEI", "BANKNIFTY": "^NSEBANK"}


def _fetch_live_index(index_name: str) -> Optional[dict]:
    """Fetch today's index value from yfinance when DB is stale."""
    yf_sym = _INDEX_YF_MAP.get(index_name)
    if not yf_sym:
        return None
    import yfinance as yf
    ticker = yf.Ticker(yf_sym)
    try:
        yf_stderr = StringIO()
        with redirect_stderr(yf_stderr):
            fi = ticker.fast_info
        price = getattr(fi, "last_price", None)
        prev  = getattr(fi, "previous_close", None)
        if price is None:
            yf_stderr = StringIO()
            with redirect_stderr(yf_stderr):
                hist = ticker.history(period="2d", interval="1d", auto_adjust=True)
            if not hist.empty:
                price = float(hist["Close"].iloc[-1])
                prev  = float(hist["Close"].iloc[-2]) if len(hist) >= 2 else None
        if price:
            ret = ((float(price) - float(prev)) / float(prev) * 100) if prev else 0.0
            return {
                "index_name": index_name,
                "date":       str(date.today()),
                "open":       None,
                "high":       None,
                "low":        None,
                "close":      round(float(price), 2),
                "returns":    round(ret, 4),
            }
    except Exception:
        pass
    finally:
        try:
            ticker.session.close()
        except Exception:
            pass
    return None


def get_latest_index(db: Session, index_name: str) -> Optional[dict]:
    row = (
        db.query(IndexData)
        .filter(IndexData.index_name == index_name)
        .order_by(IndexData.date.desc())
        .first()
    )
    today = date.today()
    # If DB data is stale (more than 1 calendar day old on a weekday), try live
    if row and (today - row.date).days > 1:
        live = _fetch_live_index(index_name)
        if live:
            return live
    if not row:
        return _fetch_live_index(index_name)
    return {
        "index_name": row.index_name,
        "date":       str(row.date),
        "open":       row.open,
        "high":       row.high,
        "low":        row.low,
        "close":      row.close,
        "returns":    row.returns,
    }


def get_index_history(db: Session, index_name: str, days: int = 30) -> list[dict]:
    cutoff = date.today() - timedelta(days=days)
    rows = (
        db.query(IndexData)
        .filter(IndexData.index_name == index_name, IndexData.date >= cutoff)
        .order_by(IndexData.date.asc())
        .all()
    )
    return [
        {"date": str(r.date), "close": r.close, "returns": r.returns}
        for r in rows
    ]


# ══════════════════════════════════════════════════════════════
# UTILS
# ══════════════════════════════════════════════════════════════
def _safe_float(val) -> Optional[float]:
    try:
        f = float(val)
        return None if pd.isna(f) else round(f, 4)
    except (TypeError, ValueError):
        return None
