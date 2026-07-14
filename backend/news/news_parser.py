"""
AQRTI News Parser
Normalises raw RawNewsItem objects into structured ParsedNewsItem.
Cleans HTML, trims text, ensures consistent field types.
No classification or scoring here — that happens in later stages.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from news.news_collector import RawNewsItem


@dataclass
class ParsedNewsItem:
    source:         str
    headline:       str
    summary:        Optional[str]
    url:            str
    published_at:   datetime
    content_hash:   str
    symbol_hint:    Optional[str] = None   # from symbol-targeted collectors


# ══════════════════════════════════════════════════════════════
# PARSER
# ══════════════════════════════════════════════════════════════
def parse_news_item(raw: RawNewsItem) -> Optional[ParsedNewsItem]:
    """
    Convert RawNewsItem → ParsedNewsItem.
    Returns None if the item is invalid (empty headline, too short, etc.).
    """
    headline = _clean_text(raw.headline)
    if not headline or len(headline) < 10:
        return None

    # Reject clearly non-financial content by keyword absence
    if _is_irrelevant(headline):
        return None

    summary = _clean_text(raw.summary) if raw.summary else None
    if summary and len(summary) < 10:
        summary = None

    # Ensure UTC timezone
    pub_at = raw.published_at
    if pub_at.tzinfo is None:
        pub_at = pub_at.replace(tzinfo=timezone.utc)

    return ParsedNewsItem(
        source       = raw.source.lower().strip(),
        headline     = headline[:500],
        summary      = summary[:2000] if summary else None,
        url          = raw.url.strip()[:1000],
        published_at = pub_at,
        content_hash = raw.content_hash,
        symbol_hint  = getattr(raw, "symbol_hint", None),
    )


def parse_news_batch(raw_items: list[RawNewsItem]) -> list[ParsedNewsItem]:
    """Parse a batch of raw items, filtering out invalid ones."""
    results = []
    for raw in raw_items:
        parsed = parse_news_item(raw)
        if parsed is not None:
            results.append(parsed)
    return results


# ── Helpers ───────────────────────────────────────────────────
_HTML_TAG_RE    = re.compile(r"<[^>]+>")
_MULTI_SPACE_RE = re.compile(r"\s{2,}")
_CDATA_RE       = re.compile(r"<!\[CDATA\[(.*?)]]>", re.DOTALL)

def _clean_text(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    # Strip CDATA
    text = _CDATA_RE.sub(r"\1", text)
    # Strip HTML tags
    text = _HTML_TAG_RE.sub(" ", text)
    # Decode common HTML entities
    text = (
        text
        .replace("&amp;",  "&")
        .replace("&lt;",   "<")
        .replace("&gt;",   ">")
        .replace("&quot;", '"')
        .replace("&#39;",  "'")
        .replace("&nbsp;", " ")
        .replace("\xa0",   " ")
    )
    # Normalise whitespace
    text = _MULTI_SPACE_RE.sub(" ", text).strip()
    return text if text else None


# Keywords that indicate the item is NOT financial market news
_NOISE_KEYWORDS = {
    "cricket", "football", "bollywood", "movie", "film", "recipe",
    "weather", "lifestyle", "fashion", "celebrity", "astrology",
    "horoscope", "sports", "health tips", "travel", "tourism",
}

def _is_irrelevant(headline: str) -> bool:
    lower = headline.lower()
    return any(kw in lower for kw in _NOISE_KEYWORDS)
