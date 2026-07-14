"""
Live News Gate
==============
Blocks NEW paper-trade entries on a symbol carrying fresh, high-conviction
negative news. LIVE EXECUTION PATH ONLY — this reads the news table at the
moment of a live entry decision. It must never be wired into the backtester:
historical news coverage is too thin to simulate this gate honestly, and
injecting it retroactively would contaminate the honest backtest record
(user decision 2026-07-14: news informs live/arena trading, not backtests).

Blocking rule (deliberately narrow — the gate should rarely fire):
  an article within the last NEWS_GATE_LOOKBACK_HOURS tagged to the symbol,
  LLM-analyzed (provenance-verified judgment, not keyword scoring), with
  negative sentiment, sentiment_score <= -0.5, and llm_relevance >= 0.6.

A blocked entry is a skip, not a close — existing positions are managed by
their own SL/TP/time-stop rules, which already encode the strategy's tested
exit logic.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from aqrti.database.models import NewsEvent
from aqrti.utils.logger import get_logger

log = get_logger("live_news_gate")

NEWS_GATE_LOOKBACK_HOURS = 24
MIN_NEGATIVE_SCORE       = -0.5   # sentiment_score at or below this
MIN_RELEVANCE            = 0.6    # llm_relevance at or above this


def news_blocks_entry(db: Session, symbol: str) -> tuple[bool, str]:
    """
    Returns (blocked, reason). Fail-open: any query problem returns
    (False, "") — a broken news table must not silently halt live trading,
    it just removes the extra protection.
    """
    try:
        cutoff = datetime.utcnow() - timedelta(hours=NEWS_GATE_LOOKBACK_HOURS)
        row = (
            db.query(NewsEvent)
            .filter(
                NewsEvent.company == symbol,
                NewsEvent.timestamp >= cutoff,
                NewsEvent.llm_analyzed == True,   # noqa: E712
                NewsEvent.sentiment == "negative",
                NewsEvent.sentiment_score <= MIN_NEGATIVE_SCORE,
                NewsEvent.llm_relevance >= MIN_RELEVANCE,
            )
            .order_by(NewsEvent.sentiment_score.asc())
            .first()
        )
    except Exception as exc:
        log.debug("News gate query failed (fail-open): %s", exc)
        return False, ""

    if row is None:
        return False, ""

    reason = (
        f"fresh negative news (score={row.sentiment_score:+.2f}, "
        f"relevance={row.llm_relevance:.2f}): {row.headline[:90]}"
    )
    return True, reason
