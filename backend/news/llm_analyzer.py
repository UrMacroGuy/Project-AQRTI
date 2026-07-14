"""
NIM Batch News Analyzer
=======================
Sends unanalyzed NewsEvent rows for curated symbols to the active LLM
provider (NVIDIA NIM by default) in BATCHES — ~10 articles per request —
and refines their sentiment / event_type / relevance with LLM judgment,
replacing the keyword-only scoring for those rows.

Design constraints (non-negotiable):
  * RPM budget: the NIM key is client-side limited to 40 RPM shared with
    research_synthesizer and agents. One analyzer run is capped at
    MAX_REQUESTS_PER_RUN requests (default 6 -> <=60 articles/run), so a
    full run consumes <=15% of one minute's budget even in the worst case.
  * Anti-fabrication gate (same discipline as research_synthesizer's
    citation gate): the LLM must echo back each article's real DB id; any
    response item whose id was not in the batch we sent is discarded, and
    an article the LLM didn't return simply stays keyword-scored. Nothing
    is invented, nothing partial is guessed.
  * Provenance: rows updated here get llm_analyzed=True (migration 0006)
    so every consumer/UI can distinguish LLM-refined values from keyword
    scoring. Rows never analyzed keep llm_analyzed=False honestly.
  * LIVE PATH ONLY: this feeds the live decision layer (research synthesis,
    the paper-trading news gate, agent briefs). It must never be used to
    backfill historical sentiment for backtesting — that would be
    look-ahead contamination of the honest backtest record.
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timedelta

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from sqlalchemy.orm import Session

from aqrti.database.models import NewsEvent, Stock
from aqrti.utils.logger import get_logger

log = get_logger("news_llm_analyzer")

BATCH_SIZE           = 10   # articles per LLM request
MAX_REQUESTS_PER_RUN = 6    # hard cap per run — RPM budget protection
LOOKBACK_HOURS       = 48   # only analyze recent articles (live path)

VALID_SENTIMENTS  = {"positive", "negative", "neutral"}
VALID_EVENT_TYPES = {
    "earnings", "order_win", "buyback", "dividend", "management_change",
    "regulatory", "macro", "analyst_rating", "expansion", "litigation",
    "other",
}

_SYSTEM_PROMPT = """You are a financial news analyst for Indian (NSE) equities.
You will receive a JSON array of news articles, each with an integer "id", a "symbol", a "headline" and possibly a "summary".
For EACH article, judge:
  - sentiment: "positive" | "negative" | "neutral" — for the tagged symbol's shareholders specifically, not the general mood.
  - event_type: one of earnings | order_win | buyback | dividend | management_change | regulatory | macro | analyst_rating | expansion | litigation | other
  - relevance: 0.0-1.0 — how directly this article affects the tagged symbol's trading thesis (1.0 = company-specific material event, 0.0 = barely mentions it).
  - sentiment_score: -1.0 to 1.0 consistent with the sentiment label.
Reply with ONLY a JSON array, one object per input article, echoing each article's exact "id":
[{"id": <int>, "sentiment": "...", "sentiment_score": <float>, "event_type": "...", "relevance": <float>}, ...]
No prose, no markdown fences, no ids that were not in the input."""


def _curated_symbols(db: Session) -> set[str]:
    return {s.symbol for s in db.query(Stock.symbol).filter(Stock.active == True).all()}


def _pending_articles(db: Session, limit: int) -> list[NewsEvent]:
    """Recent, symbol-tagged, not-yet-LLM-analyzed articles (live window)."""
    cutoff = datetime.utcnow() - timedelta(hours=LOOKBACK_HOURS)
    symbols = _curated_symbols(db)
    rows = (
        db.query(NewsEvent)
        .filter(
            NewsEvent.timestamp >= cutoff,
            NewsEvent.llm_analyzed == False,   # noqa: E712
            NewsEvent.company.isnot(None),
        )
        .order_by(NewsEvent.impact_score.desc().nullslast())
        .limit(limit * 3)
        .all()
    )
    return [r for r in rows if r.company in symbols][:limit]


def _extract_json_array(text: str) -> list | None:
    """Parse the LLM reply, tolerating markdown fences around the array."""
    text = text.strip()
    m = re.search(r"\[.*\]", text, re.DOTALL)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
        return data if isinstance(data, list) else None
    except Exception:
        return None


def _analyze_batch(batch: list[NewsEvent]) -> dict[int, dict]:
    """
    One LLM request for one batch. Returns {news_event_id: verdict} for the
    ids that passed the echo-validation gate; anything else is dropped.
    """
    from aqrti.llm import provider as llm_provider

    payload = [
        {
            "id":       n.id,
            "symbol":   n.company,
            "headline": n.headline[:300],
            **({"summary": n.summary[:400]} if n.summary else {}),
        }
        for n in batch
    ]
    sent_ids = {n.id for n in batch}

    reply = llm_provider.ask(
        json.dumps(payload, ensure_ascii=False),
        system=_SYSTEM_PROMPT,
        temperature=0.2,
        max_tokens=1600,
    )
    parsed = _extract_json_array(reply)
    if parsed is None:
        log.warning("LLM reply unparseable — batch of %d stays keyword-scored", len(batch))
        return {}

    verdicts: dict[int, dict] = {}
    for item in parsed:
        if not isinstance(item, dict):
            continue
        nid = item.get("id")
        # Anti-fabrication gate: the id must be one we actually sent.
        if nid not in sent_ids:
            log.warning("LLM returned id %s not in batch — discarded", nid)
            continue
        sentiment = str(item.get("sentiment", "")).lower()
        event     = str(item.get("event_type", "")).lower()
        if sentiment not in VALID_SENTIMENTS:
            continue
        if event not in VALID_EVENT_TYPES:
            event = "other"
        try:
            score = max(-1.0, min(1.0, float(item.get("sentiment_score", 0.0))))
            rel   = max(0.0, min(1.0, float(item.get("relevance", 0.0))))
        except (TypeError, ValueError):
            continue
        verdicts[nid] = {
            "sentiment":       sentiment,
            "sentiment_score": score,
            "event_type":      event,
            "relevance":       rel,
        }
    return verdicts


def analyze_pending_news(db: Session) -> dict:
    """
    Main entry — analyze up to BATCH_SIZE * MAX_REQUESTS_PER_RUN recent
    curated-symbol articles. Idempotent: analyzed rows are flagged and
    never re-sent. Safe to call every pipeline run.
    """
    from aqrti.llm import provider as llm_provider
    if not llm_provider.is_configured():
        log.info("LLM provider not configured — news stays keyword-scored")
        return {"status": "skipped", "reason": "llm_not_configured", "analyzed": 0}

    pending = _pending_articles(db, BATCH_SIZE * MAX_REQUESTS_PER_RUN)
    if not pending:
        return {"status": "ok", "analyzed": 0, "requests": 0}

    analyzed = 0
    requests = 0
    for i in range(0, len(pending), BATCH_SIZE):
        if requests >= MAX_REQUESTS_PER_RUN:
            break
        batch = pending[i:i + BATCH_SIZE]
        try:
            verdicts = _analyze_batch(batch)
            requests += 1
        except Exception as exc:
            log.warning("NIM batch analysis failed (batch %d): %s", requests + 1, exc)
            break   # provider trouble — don't burn more budget this run

        for n in batch:
            v = verdicts.get(n.id)
            if not v:
                continue   # stays keyword-scored, honestly un-flagged
            n.sentiment       = v["sentiment"]
            n.sentiment_score = v["sentiment_score"]
            n.event_type      = v["event_type"]
            n.llm_relevance   = v["relevance"]
            n.llm_analyzed    = True
            analyzed += 1

        try:
            db.commit()
        except Exception as exc:
            db.rollback()
            log.error("Failed to persist LLM verdicts: %s", exc)

    log.info("NIM news analysis: %d articles refined in %d requests (%d pending)",
             analyzed, requests, len(pending))
    return {"status": "ok", "analyzed": analyzed, "requests": requests,
            "pending_seen": len(pending)}
