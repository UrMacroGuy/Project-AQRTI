"""
Finnhub real-time data client for AQRTI.

Provides:
  - get_quote(symbol)  → live NSE price (primary source for open-position monitoring)
  - get_news(symbol, days) → company news headlines (for sentiment pipeline)

All calls are guarded — any failure returns None so callers can fall back to
yfinance without crashing. Requires AQRTI_FINNHUB_API_KEY in .env.

NSE symbols are mapped to Finnhub's BSE:SYMBOL format (Finnhub indexes NSE
equities under the BSE exchange prefix on their free tier). If a BSE lookup
fails, a bare SYMBOL attempt is made as last resort.

Rate limit: free tier = 60 req/min. The monitor loop runs every 5 min and
checks ≤12 open positions → well within limits.
"""

from __future__ import annotations

import time
from typing import Optional

from aqrti.utils.logger import get_logger

log = get_logger("finnhub_client")

# In-process quote cache: symbol → (price, fetched_epoch)
_quote_cache: dict[str, tuple[float, float]] = {}
_CACHE_TTL = 60  # seconds — same as yfinance cache in paper_trade.py

# Finnhub quote endpoint
_QUOTE_URL = "https://finnhub.io/api/v1/quote"
_NEWS_URL  = "https://finnhub.io/api/v1/company-news"


def _api_key() -> str:
    """Return Finnhub API key from settings. Empty string when not configured."""
    try:
        from aqrti.config.settings import get_settings
        return get_settings().finnhub_api_key or ""
    except Exception:
        return ""


def _finnhub_symbol(nse_symbol: str) -> str:
    """Convert NSE bare symbol to Finnhub exchange-qualified symbol (BSE:SYMBOL)."""
    return f"BSE:{nse_symbol}"


def get_quote(symbol: str) -> Optional[float]:
    """
    Return the latest trade price for an NSE symbol via Finnhub.
    Returns None when:
      - API key is not configured
      - Network error or non-200 response
      - Finnhub returns price = 0 (market closed / unknown symbol)
    Always safe to call — never raises.
    """
    key = _api_key()
    if not key:
        return None

    now = time.time()
    cached = _quote_cache.get(symbol)
    if cached and (now - cached[1]) < _CACHE_TTL:
        return cached[0]

    price = _fetch_quote(symbol, key)
    if price and price > 0:
        _quote_cache[symbol] = (price, now)
        log.debug("Finnhub quote %s → %.2f", symbol, price)
        return price

    log.debug("Finnhub returned no price for %s", symbol)
    return None


def _fetch_quote(symbol: str, key: str) -> Optional[float]:
    """Internal: try BSE:SYMBOL first, then bare symbol."""
    import urllib.request
    import json

    for fh_sym in (_finnhub_symbol(symbol), symbol):
        try:
            url = f"{_QUOTE_URL}?symbol={fh_sym}&token={key}"
            req = urllib.request.Request(url, headers={"User-Agent": "AQRTI/1.0"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode())
            price = data.get("c") or data.get("l")  # current; fallback to last close
            if price and float(price) > 0:
                return float(price)
        except Exception as exc:
            log.debug("Finnhub fetch failed for %s: %s", fh_sym, exc)
    return None


def get_news(symbol: str, days: int = 3) -> list[dict]:
    """
    Return recent company news from Finnhub for the given NSE symbol.
    Each item: {"datetime": int_epoch, "headline": str, "summary": str, "url": str}
    Returns empty list on any error or when API key is not configured.

    Used by the sentiment pipeline to supplement or replace existing news sources.
    """
    key = _api_key()
    if not key:
        return []

    import urllib.request
    import json
    from datetime import date, timedelta

    end_date   = date.today().isoformat()
    start_date = (date.today() - timedelta(days=days)).isoformat()
    fh_sym     = _finnhub_symbol(symbol)

    try:
        url = (
            f"{_NEWS_URL}?symbol={fh_sym}"
            f"&from={start_date}&to={end_date}&token={key}"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "AQRTI/1.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            items = json.loads(resp.read().decode())
        if not isinstance(items, list):
            return []
        return [
            {
                "datetime": item.get("datetime"),
                "headline": item.get("headline", ""),
                "summary":  item.get("summary", ""),
                "url":      item.get("url", ""),
                "source":   item.get("source", ""),
            }
            for item in items
            if item.get("headline")
        ]
    except Exception as exc:
        log.debug("Finnhub news fetch failed for %s: %s", symbol, exc)
        return []


def is_configured() -> bool:
    """True when a Finnhub API key is present in settings."""
    return bool(_api_key())
