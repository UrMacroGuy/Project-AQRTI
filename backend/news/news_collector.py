"""
AQRTI News Collector
Fetches raw news items from RSS feeds and NSE announcement pages.
Returns a list of RawNewsItem — no parsing, no classification, just raw data.

Sources:
  - MoneyControl RSS
  - Economic Times RSS
  - LiveMint RSS
  - Business Standard RSS
  - NSE Corporate Announcements (HTML page scrape)
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional
from email.utils import parsedate_to_datetime

import httpx
import xml.etree.ElementTree as ET

from aqrti.utils.logger import get_logger

log = get_logger("news_collector")

# Request timeout in seconds
_TIMEOUT = 10
_MAX_ITEMS_PER_SOURCE = 50


@dataclass
class RawNewsItem:
    source: str
    headline: str
    url: str
    published_at: datetime
    summary: Optional[str] = None
    content_hash: str = ""     # dedup key: sha256(source+headline)
    # Set by symbol-targeted collectors (google_news): the curated symbol the
    # query was FOR. Used only as a fallback when the entity extractor finds
    # no symbol in the text itself — the article was retrieved by searching
    # this company's name, so the association is real, not guessed.
    symbol_hint: Optional[str] = None

    def __post_init__(self):
        if not self.content_hash:
            raw = f"{self.source}:{self.headline}"
            self.content_hash = hashlib.sha256(raw.encode()).hexdigest()[:16]


# ══════════════════════════════════════════════════════════════
# RSS FEED DEFINITIONS
# ══════════════════════════════════════════════════════════════
RSS_SOURCES = [
    {
        "name":    "moneycontrol",
        "url":     "https://www.moneycontrol.com/rss/latestnews.xml",
        "weight":  0.8,
    },
    {
        "name":    "economictimes",
        "url":     "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
        "weight":  0.9,
    },
    {
        "name":    "livemint",
        "url":     "https://www.livemint.com/rss/markets",
        "weight":  0.85,
    },
    {
        "name":    "business_standard",
        "url":     "https://www.business-standard.com/rss/markets-106.rss",
        "weight":  0.85,
    },
    {
        "name":    "financial_express",
        "url":     "https://www.financialexpress.com/market/feed/",
        "weight":  0.75,
    },
]

# Source weight lookup (used by impact_scoring)
SOURCE_WEIGHTS: dict[str, float] = {s["name"]: s["weight"] for s in RSS_SOURCES}
SOURCE_WEIGHTS["nse_announcement"] = 1.0   # highest trust
SOURCE_WEIGHTS["google_news"] = 0.7        # aggregator — underlying outlet varies


# ══════════════════════════════════════════════════════════════
# RSS COLLECTOR
# ══════════════════════════════════════════════════════════════
def collect_rss_feed(source_cfg: dict) -> List[RawNewsItem]:
    """Fetch and parse one RSS feed. Returns list of RawNewsItem."""
    name = source_cfg["name"]
    url  = source_cfg["url"]
    items: List[RawNewsItem] = []

    try:
        response = httpx.get(url, timeout=_TIMEOUT, follow_redirects=True,
                             headers={"User-Agent": "AQRTI/1.0 (financial research bot)"})
        response.raise_for_status()
        root = ET.fromstring(response.content)
    except Exception as exc:
        log.warning("RSS fetch failed [%s]: %s", name, exc)
        return []

    # Handle both RSS 2.0 (<channel><item>) and Atom (<feed><entry>)
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    rss_items  = root.findall(".//item")
    atom_items = root.findall(".//atom:entry", ns)
    raw_items  = rss_items or atom_items

    for elem in raw_items[:_MAX_ITEMS_PER_SOURCE]:
        try:
            headline = _text(elem, "title") or _text(elem, "atom:title", ns)
            if not headline:
                continue
            headline = headline.strip()

            link     = _text(elem, "link") or _text(elem, "atom:link", ns) or ""
            summary  = _text(elem, "description") or _text(elem, "atom:summary", ns)
            pub_str  = _text(elem, "pubDate") or _text(elem, "atom:published", ns)

            pub_dt = _parse_date(pub_str)
            if pub_dt is None:
                pub_dt = datetime.now(tz=timezone.utc)

            items.append(RawNewsItem(
                source       = name,
                headline     = headline,
                url          = link.strip(),
                published_at = pub_dt,
                summary      = summary,
            ))
        except Exception as exc:
            log.debug("RSS item parse error [%s]: %s", name, exc)
            continue

    log.info("[%s] collected %d items.", name, len(items))
    return items


def collect_all_rss() -> List[RawNewsItem]:
    """Collect from all RSS sources. Deduplicates by content_hash."""
    all_items: List[RawNewsItem] = []
    seen: set[str] = set()

    for source_cfg in RSS_SOURCES:
        items = collect_rss_feed(source_cfg)
        for item in items:
            if item.content_hash not in seen:
                seen.add(item.content_hash)
                all_items.append(item)
        # polite delay between sources
        time.sleep(0.5)

    log.info("Total raw items collected: %d (deduplicated).", len(all_items))
    return all_items


# ══════════════════════════════════════════════════════════════
# GOOGLE NEWS — SYMBOL-TARGETED SCRAPER
# ══════════════════════════════════════════════════════════════
# The 5 generic market feeds above skew heavily toward banks/IT megacaps;
# BEL/NTPC/CDSL/DRREDDY/LT/HAL got near-zero coverage from them (confirmed
# 2026-07-12: entity_mentions had 0 rows for all six). Google News RSS
# search is free, keyless, and returns per-company articles from hundreds
# of Indian outlets — this is the coverage fix for the research funnel.
_GOOGLE_NEWS_URL = (
    "https://news.google.com/rss/search?q={query}&hl=en-IN&gl=IN&ceid=IN:en"
)
_MAX_ITEMS_PER_SYMBOL = 15   # per-symbol cap — recency matters more than depth


def _symbol_queries() -> dict[str, str]:
    """
    Build one Google News query per curated NSE symbol from the entity map's
    primary (longest, most specific) alias, quoted for exact-phrase matching,
    with 'NSE OR stock' to bias toward market coverage. Sector pseudo-symbols
    (__IT__ etc.) are excluded.
    """
    from news.entity_extractor import ENTITY_MAP
    queries: dict[str, str] = {}
    for sym, (_sector, aliases) in ENTITY_MAP.items():
        if sym.startswith("__"):
            continue
        primary = max(aliases, key=len)   # most specific alias
        queries[sym] = f'"{primary}" (NSE OR stock OR shares)'
    return queries


def collect_google_news_for_symbols() -> List[RawNewsItem]:
    """
    Fetch Google News RSS per curated symbol. Each item carries symbol_hint
    so the pipeline can attribute it even when the headline uses a name
    variant the entity extractor doesn't know.
    """
    import urllib.parse

    items: List[RawNewsItem] = []
    for sym, query in _symbol_queries().items():
        url = _GOOGLE_NEWS_URL.format(query=urllib.parse.quote(query))
        try:
            response = httpx.get(url, timeout=_TIMEOUT, follow_redirects=True,
                                 headers={"User-Agent": "AQRTI/1.0 (financial research bot)"})
            response.raise_for_status()
            root = ET.fromstring(response.content)
        except Exception as exc:
            log.warning("Google News fetch failed [%s]: %s", sym, exc)
            continue

        count = 0
        for elem in root.findall(".//item"):
            if count >= _MAX_ITEMS_PER_SYMBOL:
                break
            try:
                headline = _text(elem, "title")
                if not headline:
                    continue
                link    = _text(elem, "link") or ""
                pub_dt  = _parse_date(_text(elem, "pubDate"))
                if pub_dt is None:
                    pub_dt = datetime.now(tz=timezone.utc)
                # Google News wraps the description in tracking HTML — the
                # parser strips tags later; the <source> tag names the outlet.
                outlet  = _text(elem, "source")
                summary = _text(elem, "description")

                items.append(RawNewsItem(
                    source       = "google_news",
                    headline     = headline.strip(),
                    url          = link.strip(),
                    published_at = pub_dt,
                    summary      = f"[{outlet}] {summary}" if outlet and summary else summary,
                    symbol_hint  = sym,
                ))
                count += 1
            except Exception as exc:
                log.debug("Google News item parse error [%s]: %s", sym, exc)
                continue

        log.info("[google_news:%s] collected %d items.", sym, count)
        time.sleep(0.5)   # polite delay between symbol queries

    return items


# ══════════════════════════════════════════════════════════════
# NSE ANNOUNCEMENT SCRAPER
# ══════════════════════════════════════════════════════════════
_NSE_CORP_URL = "https://www.nseindia.com/api/corporate-announcements?index=equities"
_NSE_HEADERS  = {
    "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept":          "application/json, text/plain, */*",
    "Referer":         "https://www.nseindia.com/companies-listing/corporate-filings-announcements",
    "Accept-Language": "en-US,en;q=0.9",
}


def collect_nse_announcements() -> List[RawNewsItem]:
    """
    Fetch corporate announcements from NSE India API.
    NSE requires a session cookie — first GET the homepage to seed it.
    """
    items: List[RawNewsItem] = []

    try:
        with httpx.Client(timeout=_TIMEOUT, follow_redirects=True,
                          headers=_NSE_HEADERS) as client:
            # seed cookie
            client.get("https://www.nseindia.com/", timeout=5)
            time.sleep(1)

            resp = client.get(_NSE_CORP_URL, timeout=_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()

    except Exception as exc:
        log.warning("NSE announcement fetch failed: %s", exc)
        return []

    announcements = data if isinstance(data, list) else data.get("data", [])

    for entry in announcements[:_MAX_ITEMS_PER_SOURCE]:
        try:
            headline = (
                entry.get("desc") or
                entry.get("subject") or
                entry.get("headline") or ""
            ).strip()
            if not headline:
                continue

            symbol   = (entry.get("symbol") or "").strip().upper()
            url      = entry.get("attchmntFile") or entry.get("url") or ""
            pub_str  = entry.get("exchdisstime") or entry.get("bm_timestamp") or ""
            pub_dt   = _parse_date(pub_str)
            if pub_dt is None:
                pub_dt = datetime.now(tz=timezone.utc)

            items.append(RawNewsItem(
                source       = "nse_announcement",
                headline     = f"[{symbol}] {headline}" if symbol else headline,
                url          = url,
                published_at = pub_dt,
                summary      = entry.get("desc"),
            ))
        except Exception as exc:
            log.debug("NSE entry parse error: %s", exc)
            continue

    log.info("[nse_announcement] collected %d items.", len(items))
    return items


# ══════════════════════════════════════════════════════════════
# FULL COLLECTION RUN
# ══════════════════════════════════════════════════════════════
def collect_all_news() -> List[RawNewsItem]:
    """Collect from all sources — RSS + Google News per symbol + NSE announcements."""
    rss_items    = collect_all_rss()
    google_items = collect_google_news_for_symbols()
    nse_items    = collect_nse_announcements()

    seen: set[str] = set()
    combined: List[RawNewsItem] = []
    # Google/NSE first in the dedup order: when a story appears both in a
    # generic feed and a symbol-targeted feed, keep the one carrying the
    # symbol_hint / official-source attribution.
    for item in google_items + nse_items + rss_items:
        if item.content_hash not in seen:
            seen.add(item.content_hash)
            combined.append(item)

    combined.sort(key=lambda x: x.published_at, reverse=True)
    log.info("Combined collection: %d unique news items.", len(combined))
    return combined


# ── Helpers ───────────────────────────────────────────────────
def _text(elem, tag: str, ns: dict | None = None) -> Optional[str]:
    child = elem.find(tag, ns or {})
    if child is None:
        return None
    text = (child.text or "").strip()
    return text if text else None


def _parse_date(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    s = s.strip()
    # Try RFC 2822 (RSS pubDate)
    try:
        return parsedate_to_datetime(s)
    except Exception:
        pass
    # Try ISO 8601
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S",
                "%d %b %Y %H:%M:%S %z", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(s[:len(fmt)], fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            pass
    return None
