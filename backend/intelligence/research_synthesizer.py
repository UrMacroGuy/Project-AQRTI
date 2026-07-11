"""
Research Synthesizer — LLM research-to-strategy funnel, Step 2 (LLM Synthesis).

Pulls point-in-time news / sentiment / corporate-filing / earnings rows for a
symbol, asks the active LLM provider to produce a structured thesis, and
persists it to `research_synthesis` — but ONLY if every cited source ID is a
real row that was actually shown to the LLM and dated on/before as_of_date.
This citation gate is the anti-fabrication control (CLAUDE.md hard rule: no
fabricated data, ever) — a response that cites anything else is rejected
outright and nothing is written to the DB.

Usage:
    from intelligence.research_synthesizer import synthesize_symbol, synthesize_all

    synthesize_symbol(db, "HDFCBANK", date.today())
    synthesize_all(db)   # all NSE-scrapable universe symbols, defaults to today
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime, timedelta
from typing import Any, Optional

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from sqlalchemy.orm import Session

from aqrti.database.engine import get_session_factory
from aqrti.database.models import (
    NewsEvent, SentimentRecord, NSECorporateFiling, EarningsEvent, ResearchSynthesis, Stock,
)
from aqrti.llm import provider as llm_provider
from aqrti.utils.logger import get_logger

log = get_logger("research_synthesizer")

# US tickers held in the curated universe (VOO, QQQ) are not NSE-listed — no
# NSE news/filings/earnings source covers them. Same exclusion set used by
# agents/market_research_agent.py and agents/news_research_agent.py; reused
# here (not re-derived) so the "NSE-scrapable universe" stays one definition.
NON_NSE_SYMBOLS = {"VOO", "QQQ"}

# Look-back windows. News and sentiment move fast and go stale quickly, so a
# short window keeps the synthesis current. Earnings are quarterly, so two
# quarters (~185 days) ensures the most recent print is always in scope even
# right before the next one is due. Filings (results/dividends/board actions/
# announcements) are lower-frequency than news but higher-frequency than
# earnings, so 90 days is a middle ground.
NEWS_LOOKBACK_DAYS = 30
SENTIMENT_LOOKBACK_DAYS = 30
FILING_LOOKBACK_DAYS = 90
EARNINGS_LOOKBACK_DAYS = 185

VALID_DIRECTIONS = {"bullish", "bearish", "neutral"}


def _stock_universe(db: Session, nse_only: bool = False) -> list[str]:
    """DB-driven active universe (curated 12-symbol set, 2026-07 prune)."""
    syms = [s.symbol for s in db.query(Stock.symbol).filter(Stock.active == True).all()]
    if nse_only:
        syms = [s for s in syms if s not in NON_NSE_SYMBOLS]
    return syms


# ══════════════════════════════════════════════════════════════
# Source-row collection (point-in-time only: date <= as_of_date)
# ══════════════════════════════════════════════════════════════

def _collect_sources(db: Session, symbol: str, as_of_date: date) -> dict[str, list]:
    """
    Pull all candidate source rows for `symbol`, strictly <= as_of_date on
    each model's own date column (they differ per table). Returns a dict
    keyed by table name -> list of ORM rows, used both to build the prompt
    and, later, to validate the LLM's cited IDs against.
    """
    as_of_dt_end = datetime.combine(as_of_date, datetime.max.time())

    news_since = datetime.combine(as_of_date - timedelta(days=NEWS_LOOKBACK_DAYS), datetime.min.time())
    news_rows = (
        db.query(NewsEvent)
        .filter(NewsEvent.company == symbol)
        .filter(NewsEvent.timestamp >= news_since, NewsEvent.timestamp <= as_of_dt_end)
        .order_by(NewsEvent.timestamp.desc())
        .all()
    )

    sent_since = datetime.combine(as_of_date - timedelta(days=SENTIMENT_LOOKBACK_DAYS), datetime.min.time())
    sentiment_rows = (
        db.query(SentimentRecord)
        .filter(SentimentRecord.entity == symbol)
        .filter(SentimentRecord.timestamp >= sent_since, SentimentRecord.timestamp <= as_of_dt_end)
        .order_by(SentimentRecord.timestamp.desc())
        .all()
    )

    filing_since = as_of_date - timedelta(days=FILING_LOOKBACK_DAYS)
    filing_rows = (
        db.query(NSECorporateFiling)
        .filter(NSECorporateFiling.symbol == symbol)
        .filter(NSECorporateFiling.filing_date >= filing_since, NSECorporateFiling.filing_date <= as_of_date)
        .order_by(NSECorporateFiling.filing_date.desc())
        .all()
    )

    earnings_since = as_of_date - timedelta(days=EARNINGS_LOOKBACK_DAYS)
    earnings_rows = (
        db.query(EarningsEvent)
        .filter(EarningsEvent.symbol == symbol)
        .filter(EarningsEvent.earnings_date >= earnings_since, EarningsEvent.earnings_date <= as_of_date)
        .order_by(EarningsEvent.earnings_date.desc())
        .all()
    )

    return {
        "NewsEvent": news_rows,
        "SentimentRecord": sentiment_rows,
        "NSECorporateFiling": filing_rows,
        "EarningsEvent": earnings_rows,
    }


def _has_any_sources(sources: dict[str, list]) -> bool:
    return any(len(rows) > 0 for rows in sources.values())


# ══════════════════════════════════════════════════════════════
# Prompt construction
# ══════════════════════════════════════════════════════════════

def _format_source_line(table: str, row: Any) -> str:
    tag = f"[{table}:{row.id}]"
    if table == "NewsEvent":
        return f"{tag} {row.timestamp.date()} — {row.headline} (sentiment={row.sentiment}, impact={row.impact_score})"
    if table == "SentimentRecord":
        return f"{tag} {row.timestamp.date()} — score={row.score}, positive={row.positive}, negative={row.negative}, source={row.source}"
    if table == "NSECorporateFiling":
        return f"{tag} {row.filing_date} — {row.filing_type}: {row.subject or ''}"
    if table == "EarningsEvent":
        return (
            f"{tag} {row.earnings_date} ({row.quarter or row.period}) — "
            f"revenue_yoy={row.revenue_yoy_pct}%, pat_yoy={row.pat_yoy_pct}%, eps_yoy={row.eps_yoy_pct}%"
        )
    return f"{tag} <unrecognized source row>"


def _build_prompt(symbol: str, as_of_date: date, sources: dict[str, list]) -> str:
    lines: list[str] = []
    for table, rows in sources.items():
        if not rows:
            continue
        lines.append(f"\n{table} ({len(rows)} rows):")
        for row in rows:
            lines.append("  " + _format_source_line(table, row))

    source_block = "\n".join(lines)

    return f"""You are a research analyst producing a point-in-time thesis for the NSE-listed \
stock {symbol}, as of {as_of_date.isoformat()}. Use ONLY the source rows listed below — do not \
use any outside knowledge, and do not assume any event happened that isn't listed here.

SOURCE ROWS:
{source_block}

Respond with STRICT JSON ONLY (no markdown fences, no prose before or after) matching exactly \
this schema:
{{
  "sentiment_score": <float, -1.0 to 1.0>,
  "thesis_direction": <"bullish" | "bearish" | "neutral">,
  "key_catalysts": [<string>, ...],
  "risk_flags": [<string>, ...],
  "management_change_flag": <bool>,
  "source_event_ids": [{{"table": <string>, "id": <int>}}, ...],
  "confidence": <float, 0.0 to 1.0>
}}

CRITICAL RULES:
- "source_event_ids" MUST list only the exact [table:id] pairs shown above that you actually \
used to form your thesis. Do not invent, guess, or cite any ID that is not shown above.
- "source_event_ids" must not be empty — cite at least one row.
- Do not cite the same source table with a made-up id. Every id must match a row shown above exactly.
- Output valid JSON only.
"""


# ══════════════════════════════════════════════════════════════
# Response parsing
# ══════════════════════════════════════════════════════════════

def _strip_code_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        # Drop the opening fence line (``` or ```json) and the closing fence.
        lines = t.split("\n")
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        t = "\n".join(lines).strip()
    return t


def _parse_llm_response(raw_text: str) -> Optional[dict]:
    """Parse the LLM's raw text into a dict. Returns None on any parse failure."""
    cleaned = _strip_code_fences(raw_text)
    try:
        parsed = json.loads(cleaned)
    except (json.JSONDecodeError, TypeError) as exc:
        log.warning("research_synthesizer: JSON parse failed: %s | raw=%r", exc, raw_text[:500])
        return None
    if not isinstance(parsed, dict):
        log.warning("research_synthesizer: parsed response is not a JSON object: %r", parsed)
        return None
    return parsed


# ══════════════════════════════════════════════════════════════
# Citation validation — the anti-fabrication gate
# ══════════════════════════════════════════════════════════════

def _validate_citations(
    cited_ids: Any,
    shown_sources: dict[str, list],
    as_of_date: date,
) -> tuple[bool, list[dict]]:
    """
    Verify every {table, id} the LLM cited is:
      1. well-formed ({"table": str, "id": int})
      2. a table name we actually queried
      3. a row ID that was actually shown to the LLM in this prompt
      4. dated on or before as_of_date (defense in depth — shown_sources is
         already filtered to as_of_date, so this should never trip in
         practice, but a row-level re-check costs nothing and guards against
         future refactors of _collect_sources introducing a leak)

    Returns (is_valid, bad_entries). is_valid is True only if cited_ids is a
    non-empty list and every entry passes all checks.
    """
    date_col = {
        "NewsEvent": "timestamp",
        "SentimentRecord": "timestamp",
        "NSECorporateFiling": "filing_date",
        "EarningsEvent": "earnings_date",
    }

    if not isinstance(cited_ids, list) or len(cited_ids) == 0:
        return False, [{"reason": "source_event_ids is empty or not a list"}]

    # Index shown rows by (table, id) for O(1) lookup.
    shown_by_key: dict[tuple[str, int], Any] = {}
    for table, rows in shown_sources.items():
        for row in rows:
            shown_by_key[(table, row.id)] = row

    bad_entries: list[dict] = []
    for entry in cited_ids:
        if not isinstance(entry, dict) or "table" not in entry or "id" not in entry:
            bad_entries.append({"reason": "malformed citation entry", "entry": entry})
            continue

        table = entry.get("table")
        raw_id = entry.get("id")
        try:
            row_id = int(raw_id)
        except (TypeError, ValueError):
            bad_entries.append({"reason": "non-integer id", "entry": entry})
            continue

        if table not in date_col:
            bad_entries.append({"reason": "unknown source table", "entry": entry})
            continue

        row = shown_by_key.get((table, row_id))
        if row is None:
            bad_entries.append({"reason": "id not in the set of rows shown to the LLM", "entry": entry})
            continue

        row_date = getattr(row, date_col[table])
        row_date_only = row_date.date() if isinstance(row_date, datetime) else row_date
        if row_date_only is None or row_date_only > as_of_date:
            bad_entries.append({"reason": "cited row is dated after as_of_date", "entry": entry})
            continue

    return (len(bad_entries) == 0), bad_entries


def _validate_synthesis_fields(parsed: dict) -> Optional[str]:
    """Returns an error string if required fields are missing/out of range, else None."""
    sentiment_score = parsed.get("sentiment_score")
    if not isinstance(sentiment_score, (int, float)) or not (-1.0 <= sentiment_score <= 1.0):
        return f"sentiment_score missing or out of range [-1,1]: {sentiment_score!r}"

    thesis_direction = parsed.get("thesis_direction")
    if thesis_direction not in VALID_DIRECTIONS:
        return f"thesis_direction missing or invalid: {thesis_direction!r}"

    confidence = parsed.get("confidence")
    if confidence is not None and (not isinstance(confidence, (int, float)) or not (0.0 <= confidence <= 1.0)):
        return f"confidence out of range [0,1]: {confidence!r}"

    return None


# ══════════════════════════════════════════════════════════════
# Public API
# ══════════════════════════════════════════════════════════════

def synthesize_symbol(db: Session, symbol: str, as_of_date: date) -> Optional[ResearchSynthesis]:
    """
    Build and persist a point-in-time ResearchSynthesis row for `symbol` as of
    `as_of_date`, or return None (no insert) if there's no source data, the
    LLM call fails, the response doesn't parse, or any cited source ID fails
    validation. Never fabricates a synthesis from nothing.
    """
    sources = _collect_sources(db, symbol, as_of_date)
    if not _has_any_sources(sources):
        log.info("research_synthesizer: no source data for %s as of %s, skipping", symbol, as_of_date)
        return None

    prompt = _build_prompt(symbol, as_of_date, sources)

    try:
        raw_text = llm_provider.ask(prompt, max_tokens=1024)
    except Exception as exc:
        log.warning("research_synthesizer: LLM call failed for %s (%s): %s", symbol, as_of_date, exc)
        return None

    parsed = _parse_llm_response(raw_text)
    if parsed is None:
        return None

    field_error = _validate_synthesis_fields(parsed)
    if field_error:
        log.warning("research_synthesizer: rejecting response for %s (%s) — %s", symbol, as_of_date, field_error)
        return None

    cited_ids = parsed.get("source_event_ids")
    is_valid, bad_entries = _validate_citations(cited_ids, sources, as_of_date)
    if not is_valid:
        log.warning(
            "research_synthesizer: REJECTED synthesis for %s (%s) — invalid citations: %s | cited=%r",
            symbol, as_of_date, bad_entries, cited_ids,
        )
        return None

    model_used = f"{llm_provider.active_provider()}:{_active_model_name()}"

    existing = (
        db.query(ResearchSynthesis)
        .filter(ResearchSynthesis.symbol == symbol, ResearchSynthesis.synthesis_date == as_of_date)
        .first()
    )

    try:
        if existing is not None:
            existing.sentiment_score = float(parsed["sentiment_score"])
            existing.thesis_direction = parsed["thesis_direction"]
            existing.key_catalysts = json.dumps(parsed.get("key_catalysts") or [])
            existing.risk_flags = json.dumps(parsed.get("risk_flags") or [])
            existing.management_change_flag = bool(parsed.get("management_change_flag", False))
            existing.source_event_ids = json.dumps(cited_ids)
            existing.raw_response = raw_text
            existing.model_used = model_used
            existing.confidence = parsed.get("confidence")
            row = existing
        else:
            row = ResearchSynthesis(
                symbol=symbol,
                synthesis_date=as_of_date,
                sentiment_score=float(parsed["sentiment_score"]),
                thesis_direction=parsed["thesis_direction"],
                key_catalysts=json.dumps(parsed.get("key_catalysts") or []),
                risk_flags=json.dumps(parsed.get("risk_flags") or []),
                management_change_flag=bool(parsed.get("management_change_flag", False)),
                source_event_ids=json.dumps(cited_ids),
                raw_response=raw_text,
                model_used=model_used,
                confidence=parsed.get("confidence"),
            )
            db.add(row)
        db.commit()
    except Exception as exc:
        db.rollback()
        log.error("research_synthesizer: DB commit failed for %s (%s): %s", symbol, as_of_date, exc)
        return None

    log.info(
        "research_synthesizer: synthesized %s as of %s — %s (sentiment=%.2f, %d citations)",
        symbol, as_of_date, row.thesis_direction, row.sentiment_score, len(cited_ids),
    )
    return row


def _active_model_name() -> str:
    """Model name string for the currently active provider, without importing
    provider internals beyond the documented env-var convention each client uses."""
    active = llm_provider.active_provider()
    if active == "openrouter":
        return os.getenv("OPENROUTER_MODEL", "tencent/hy3:free")
    if active == "nvidia_nim":
        return os.getenv("NVIDIA_NIM_MODEL", "z-ai/glm-5.2")
    return "unknown"


def synthesize_all(
    db: Session,
    as_of_date: Optional[date] = None,
    symbols: Optional[list[str]] = None,
) -> dict[str, Any]:
    """
    Batch driver — runs synthesize_symbol for the NSE-scrapable universe
    (VOO/QQQ excluded, same NON_NSE_SYMBOLS filter used elsewhere). Idempotent
    per day via the (symbol, synthesis_date) upsert, so this is safe to call
    from a daily cron.
    """
    as_of_date = as_of_date or date.today()
    target_symbols = symbols if symbols is not None else _stock_universe(db, nse_only=True)

    results: dict[str, Any] = {"as_of_date": as_of_date.isoformat(), "synthesized": [], "skipped": []}
    for symbol in target_symbols:
        try:
            row = synthesize_symbol(db, symbol, as_of_date)
        except Exception as exc:
            log.error("research_synthesizer: unexpected error synthesizing %s: %s", symbol, exc)
            db.rollback()
            row = None
        if row is not None:
            results["synthesized"].append(symbol)
        else:
            results["skipped"].append(symbol)

    log.info(
        "research_synthesizer: batch complete for %s — %d synthesized, %d skipped",
        as_of_date, len(results["synthesized"]), len(results["skipped"]),
    )
    return results


if __name__ == "__main__":
    # backend/.env is only auto-loaded by main.py/app.py's load_dotenv() call
    # (see docs/RESEARCH_DRIVEN_REARCHITECTURE.md's ".env loading" pitfall
    # note) — running this module standalone otherwise silently falls back
    # to AQRTI_LLM_PROVIDER's default (openrouter, usually unconfigured)
    # instead of the .env-configured provider.
    from pathlib import Path
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")

    _db = get_session_factory()()
    try:
        print(synthesize_all(_db))
    finally:
        _db.close()
