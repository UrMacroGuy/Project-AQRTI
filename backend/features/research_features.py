"""
AQRTI Research & Event-Catalyst Features
Computes point-in-time features from the research-to-strategy funnel:
  - research_synthesis (LLM-derived daily thesis per symbol)
  - earnings_events (scheduled/actual results, beat/miss)
  - nse_corporate_filings (buyback/dividend/etc corporate actions)
  - news_events (classified news, incl. LargeOrder/ManagementChange/Buyback/Dividend)
  - markov_chain_daily (observable Markov regime label, backend/markov module)

Point-in-time correctness is mandatory (CLAUDE.md): every lookup for date d
only reads rows with a date/timestamp <= d, and a lookback window bounds how
stale a signal is allowed to be before it is treated as absent (null/0).

If a source table is empty or has no row within the lookback window, the
feature is None/0 — never fabricated. This mirrors fii_features.py's
"honesty over imputation" pattern (cache-once, lookup-per-date).
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

# Lookback windows (calendar days) — how stale a signal may be before it's
# treated as absent. Chosen to match the architecture doc's defaults; each
# is documented at its point of use below.
RESEARCH_LOOKBACK_DAYS       = 5    # research_synthesis: daily job, so a short window
CATALYST_LOOKBACK_DAYS       = 10   # buyback/order-win/dividend filings — stay "recent" for ~2 trading weeks
EARNINGS_BEAT_LOOKBACK_DAYS  = 5    # PEAD window: react to a beat within days of the print
MANAGEMENT_CHANGE_BLOCK_DAYS = 10   # architecture doc: "blocks new entries for N days post-change"
EARNINGS_HORIZON_DAYS        = 90   # days_to_earnings / days_since_earnings search horizon


# ══════════════════════════════════════════════════════════════
# CACHES — loaded once per generation run, queried per (symbol, date)
# ══════════════════════════════════════════════════════════════
class ResearchSynthesisCache:
    """symbol -> sorted list of (synthesis_date, sentiment_score, confidence, risk_flags_nonempty)."""

    def __init__(self, rows):
        self._by_symbol: dict[str, list[tuple]] = {}
        for r in rows:
            has_risk = bool(r.risk_flags) and r.risk_flags not in ("[]", "null", None)
            self._by_symbol.setdefault(r.symbol, []).append(
                (r.synthesis_date, r.sentiment_score, r.confidence, has_risk)
            )
        for sym in self._by_symbol:
            self._by_symbol[sym].sort(key=lambda t: t[0])

    def latest_as_of(self, symbol: str, as_of_date: date, lookback_days: int) -> Optional[tuple]:
        entries = self._by_symbol.get(symbol)
        if not entries:
            return None
        earliest_allowed = as_of_date - timedelta(days=lookback_days)
        best = None
        for d, sentiment, confidence, has_risk in entries:
            if d > as_of_date:
                break
            if d >= earliest_allowed:
                best = (d, sentiment, confidence, has_risk)
        return best


class EarningsEventCache:
    """symbol -> sorted list of (earnings_date, beat_miss)."""

    def __init__(self, rows):
        self._by_symbol: dict[str, list[tuple]] = {}
        for r in rows:
            self._by_symbol.setdefault(r.symbol, []).append((r.earnings_date, r.beat_miss))
        for sym in self._by_symbol:
            self._by_symbol[sym].sort(key=lambda t: t[0])

    def beat_within_lookback(self, symbol: str, as_of_date: date, lookback_days: int) -> bool:
        entries = self._by_symbol.get(symbol)
        if not entries:
            return False
        earliest_allowed = as_of_date - timedelta(days=lookback_days)
        return any(
            earliest_allowed <= d <= as_of_date and (bm or "").upper() == "BEAT"
            for d, bm in entries
        )

    def days_to_next(self, symbol: str, as_of_date: date, horizon_days: int) -> Optional[int]:
        entries = self._by_symbol.get(symbol)
        if not entries:
            return None
        horizon = as_of_date + timedelta(days=horizon_days)
        upcoming = [d for d, _ in entries if as_of_date <= d <= horizon]
        if not upcoming:
            return None
        return (min(upcoming) - as_of_date).days

    def days_since_last(self, symbol: str, as_of_date: date, horizon_days: int) -> Optional[int]:
        entries = self._by_symbol.get(symbol)
        if not entries:
            return None
        earliest = as_of_date - timedelta(days=horizon_days)
        past = [d for d, _ in entries if earliest <= d <= as_of_date]
        if not past:
            return None
        return (as_of_date - max(past)).days


class CorporateFilingCache:
    """symbol -> sorted list of (filing_date, filing_type)."""

    def __init__(self, rows):
        self._by_symbol: dict[str, list[tuple]] = {}
        for r in rows:
            self._by_symbol.setdefault(r.symbol, []).append((r.filing_date, r.filing_type))
        for sym in self._by_symbol:
            self._by_symbol[sym].sort(key=lambda t: t[0])

    def has_type_within_lookback(self, symbol: str, as_of_date: date, filing_type: str, lookback_days: int) -> bool:
        entries = self._by_symbol.get(symbol)
        if not entries:
            return False
        earliest_allowed = as_of_date - timedelta(days=lookback_days)
        return any(
            earliest_allowed <= d <= as_of_date and ft == filing_type
            for d, ft in entries
        )


class NewsEventCache:
    """symbol (company) -> sorted list of (date, event_type)."""

    def __init__(self, rows):
        self._by_symbol: dict[str, list[tuple]] = {}
        for r in rows:
            d = r.timestamp.date() if hasattr(r.timestamp, "date") else r.timestamp
            self._by_symbol.setdefault(r.company, []).append((d, r.event_type))
        for sym in self._by_symbol:
            self._by_symbol[sym].sort(key=lambda t: t[0])

    def has_type_within_lookback(self, symbol: str, as_of_date: date, event_type: str, lookback_days: int) -> bool:
        entries = self._by_symbol.get(symbol)
        if not entries:
            return False
        earliest_allowed = as_of_date - timedelta(days=lookback_days)
        return any(
            earliest_allowed <= d <= as_of_date and et == event_type
            for d, et in entries
        )


class MarkovRegimeCache:
    """date -> regime_state (BULL|BEAR|SIDEWAYS), from markov_chain_daily. Market-wide, not per-symbol."""

    def __init__(self, rows):
        # rows: list of (date, regime_state), any order
        self._sorted = sorted(((r[0], r[1]) for r in rows), key=lambda t: t[0])

    def as_of(self, as_of_date: date) -> Optional[str]:
        best = None
        for d, state in self._sorted:
            if d > as_of_date:
                break
            best = state
        return best


# ══════════════════════════════════════════════════════════════
# CACHE LOADERS
# ══════════════════════════════════════════════════════════════
def load_research_caches(symbols: list[str]) -> dict:
    """
    Load all rows needed for research/event/regime features for the given
    symbol universe, once per generation run. Returns a dict of caches;
    any cache load failure degrades to an empty cache (all-None features),
    never raises and never fabricates data.
    """
    caches: dict = {
        "research":  ResearchSynthesisCache([]),
        "earnings":  EarningsEventCache([]),
        "filings":   CorporateFilingCache([]),
        "news":      NewsEventCache([]),
        "regime":    MarkovRegimeCache([]),
    }
    if not symbols:
        return caches

    try:
        from aqrti.database.engine import get_db
        from aqrti.database.models import (
            ResearchSynthesis, EarningsEvent, NSECorporateFiling, NewsEvent,
        )

        with get_db() as db:
            rs_rows = (
                db.query(ResearchSynthesis.symbol, ResearchSynthesis.synthesis_date,
                         ResearchSynthesis.sentiment_score, ResearchSynthesis.confidence,
                         ResearchSynthesis.risk_flags)
                .filter(ResearchSynthesis.symbol.in_(symbols))
                .all()
            )
            caches["research"] = ResearchSynthesisCache(rs_rows)

            ee_rows = (
                db.query(EarningsEvent.symbol, EarningsEvent.earnings_date, EarningsEvent.beat_miss)
                .filter(EarningsEvent.symbol.in_(symbols))
                .all()
            )
            caches["earnings"] = EarningsEventCache(ee_rows)

            ncf_rows = (
                db.query(NSECorporateFiling.symbol, NSECorporateFiling.filing_date,
                         NSECorporateFiling.filing_type)
                .filter(NSECorporateFiling.symbol.in_(symbols))
                .all()
            )
            caches["filings"] = CorporateFilingCache(ncf_rows)

            ne_rows = (
                db.query(NewsEvent.company, NewsEvent.timestamp, NewsEvent.event_type)
                .filter(NewsEvent.company.in_(symbols))
                .all()
            )
            caches["news"] = NewsEventCache(ne_rows)
    except Exception:
        # Leave research/earnings/filings/news caches empty (all-None downstream) —
        # honest gap, never fabricated data.
        pass

    try:
        from markov.db import get_markov_db
        from markov.models import MarkovChainDaily

        with get_markov_db() as mdb:
            mc_rows = mdb.query(MarkovChainDaily.date, MarkovChainDaily.regime_state).all()
        caches["regime"] = MarkovRegimeCache([(r[0], r[1]) for r in mc_rows])
    except Exception:
        # Markov module may be inactive/uninitialized this run — regime_markov
        # stays null for all dates rather than guessing.
        pass

    return caches


# ══════════════════════════════════════════════════════════════
# PUBLIC ENTRY POINT
# ══════════════════════════════════════════════════════════════
def compute_research_features(
    symbol: str,
    as_of_date: date,
    caches: Optional[dict] = None,
) -> dict[str, Optional[float]]:
    """
    Return the research/event/regime feature vector for (symbol, as_of_date).
    caches: dict from load_research_caches(); if None, all features are None
    (fail-closed rather than doing a slow uncached per-call DB query — callers
    running batch generation MUST pass a pre-loaded cache, matching the
    fii_dii_cache contract in feature_generator.py).
    """
    if caches is None:
        return _empty_features()

    research_cache: ResearchSynthesisCache = caches["research"]
    earnings_cache: EarningsEventCache     = caches["earnings"]
    filing_cache:   CorporateFilingCache   = caches["filings"]
    news_cache:     NewsEventCache         = caches["news"]
    regime_cache:   MarkovRegimeCache      = caches["regime"]

    latest = research_cache.latest_as_of(symbol, as_of_date, RESEARCH_LOOKBACK_DAYS)
    if latest is not None:
        _, sentiment, confidence, has_risk = latest
        research_sentiment  = float(sentiment) if sentiment is not None else None
        research_confidence = float(confidence) if confidence is not None else None
        research_risk_flag_negative = 1 if has_risk else 0
    else:
        research_sentiment = research_confidence = None
        research_risk_flag_negative = 0

    catalyst_earnings_beat = 1 if earnings_cache.beat_within_lookback(
        symbol, as_of_date, EARNINGS_BEAT_LOOKBACK_DAYS
    ) else 0

    buyback_filing = filing_cache.has_type_within_lookback(symbol, as_of_date, "buyback", CATALYST_LOOKBACK_DAYS)
    buyback_news    = news_cache.has_type_within_lookback(symbol, as_of_date, "Buyback", CATALYST_LOOKBACK_DAYS)
    catalyst_buyback = 1 if (buyback_filing or buyback_news) else 0

    catalyst_order_win = 1 if news_cache.has_type_within_lookback(
        symbol, as_of_date, "LargeOrder", CATALYST_LOOKBACK_DAYS
    ) else 0

    dividend_filing = filing_cache.has_type_within_lookback(symbol, as_of_date, "dividend", CATALYST_LOOKBACK_DAYS)
    dividend_news    = news_cache.has_type_within_lookback(symbol, as_of_date, "Dividend", CATALYST_LOOKBACK_DAYS)
    catalyst_dividend_hike = 1 if (dividend_filing or dividend_news) else 0

    management_change_recent = 1 if news_cache.has_type_within_lookback(
        symbol, as_of_date, "ManagementChange", MANAGEMENT_CHANGE_BLOCK_DAYS
    ) else 0

    days_to_earnings   = earnings_cache.days_to_next(symbol, as_of_date, EARNINGS_HORIZON_DAYS)
    days_since_earnings = earnings_cache.days_since_last(symbol, as_of_date, EARNINGS_HORIZON_DAYS)

    regime_markov = _encode_regime(regime_cache.as_of(as_of_date))

    return {
        "research_sentiment":          research_sentiment,
        "research_confidence":         research_confidence,
        "research_risk_flag_negative": research_risk_flag_negative,
        "catalyst_earnings_beat":      catalyst_earnings_beat,
        "catalyst_buyback":            catalyst_buyback,
        "catalyst_order_win":          catalyst_order_win,
        "catalyst_dividend_hike":      catalyst_dividend_hike,
        "management_change_recent":    management_change_recent,
        "days_to_earnings":            days_to_earnings,
        "days_since_earnings":         days_since_earnings,
        "regime_markov":               regime_markov,
    }


# FeatureValue.value is a Float column (every feature in this system is
# numeric) — regime_markov's underlying label ("BULL"/"BEAR"/"SIDEWAYS") must
# be encoded as a number before it can be written. A bad string value in the
# save_feature_vector() bulk INSERT fails the whole (symbol, date) batch, not
# just this one feature, so this encoding is load-bearing for every other
# feature written alongside it.
REGIME_MARKOV_CODES = {"BULL": 1.0, "BEAR": -1.0, "SIDEWAYS": 0.0}


def _encode_regime(label: Optional[str]) -> Optional[float]:
    if label is None:
        return None
    return REGIME_MARKOV_CODES.get(label.upper())


def _empty_features() -> dict[str, Optional[float]]:
    return {
        "research_sentiment":          None,
        "research_confidence":         None,
        "research_risk_flag_negative": 0,
        "catalyst_earnings_beat":      0,
        "catalyst_buyback":            0,
        "catalyst_order_win":          0,
        "catalyst_dividend_hike":      0,
        "management_change_recent":    0,
        "days_to_earnings":            None,
        "days_since_earnings":         None,
        "regime_markov":               None,
    }
