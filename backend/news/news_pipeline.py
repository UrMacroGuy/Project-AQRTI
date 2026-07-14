"""
AQRTI News Pipeline — Orchestrator
Collects → Parses → Extracts Entities → Classifies → Scores → Stores.
Called by the scheduler after market data ingestion.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from aqrti.database.engine import get_db
from aqrti.database.models import NewsEvent, EntityMention
from aqrti.utils.logger import get_logger

from news.news_collector   import collect_all_news
from news.news_parser      import parse_news_batch
from news.entity_extractor import extract_entities
from news.event_classifier import classify_event_str
from news.impact_scoring   import compute_impact_scores

log = get_logger("news_pipeline")


# ══════════════════════════════════════════════════════════════
# MAIN PIPELINE
# ══════════════════════════════════════════════════════════════
def run_news_pipeline() -> dict:
    """
    Full pipeline run. Returns summary report.
    Deduplicates by content_hash — safe to run multiple times.
    """
    log.info("=== NEWS PIPELINE STARTED ===")

    raw_items = collect_all_news()
    parsed    = parse_news_batch(raw_items)
    log.info("Parsed %d items from %d raw.", len(parsed), len(raw_items))

    with get_db() as db:
        stored, skipped = _process_and_store(db, parsed)

    report = {
        "timestamp":   datetime.utcnow().isoformat(),
        "raw_fetched": len(raw_items),
        "parsed":      len(parsed),
        "stored":      stored,
        "skipped":     skipped,
        "status":      "COMPLETED",
    }
    log.info("=== NEWS PIPELINE COMPLETE: stored=%d skipped=%d ===", stored, skipped)
    return report


# ══════════════════════════════════════════════════════════════
# STORE LOOP
# ══════════════════════════════════════════════════════════════
def _process_and_store(db: Session, parsed_items) -> tuple[int, int]:
    stored  = 0
    skipped = 0

    # Build set of existing hashes for dedup
    existing_hashes: set[str] = set()
    try:
        rows = db.query(NewsEvent).with_entities(NewsEvent.url).limit(10000).all()
    except Exception:
        rows = []

    # Use URL as a proxy dedup key (URL is unique per article)
    existing_urls: set[str] = {r[0] for r in rows if r[0]}

    for item in parsed_items:
        if item.url and item.url in existing_urls:
            skipped += 1
            continue

        try:
            entities    = extract_entities(item.headline, item.summary)
            # Symbol-targeted collectors (google_news) searched FOR a specific
            # company — if the extractor found no symbol in the text (name
            # variant it doesn't know), the search attribution itself is the
            # evidence. Only fill the gap; never override an extracted match.
            hint = getattr(item, "symbol_hint", None)
            if hint and not entities.get("primary_symbol"):
                from news.entity_extractor import ENTITY_MAP
                if hint in ENTITY_MAP:
                    entities["primary_symbol"] = hint
                    entities.setdefault("mention_types", {})[hint] = "search_target"
                    entities["sector"] = entities.get("sector") or ENTITY_MAP[hint][0]
            event_type  = classify_event_str(item.headline, item.summary)
            scores      = compute_impact_scores(
                headline       = item.headline,
                summary        = item.summary,
                event_type     = event_type,
                source         = item.source,
                published_at   = item.published_at,
                primary_symbol = entities.get("primary_symbol"),
            )

            pub_naive = item.published_at.replace(tzinfo=None) if item.published_at.tzinfo else item.published_at

            news_row = NewsEvent(
                timestamp        = pub_naive,
                headline         = item.headline,
                summary          = item.summary,
                source           = item.source,
                company          = entities.get("primary_symbol"),
                sector           = entities.get("sector"),
                event_type       = event_type,
                sentiment        = scores["sentiment_label"],
                sentiment_score  = scores["sentiment_score"],
                impact_score     = scores["impact_score"],
                importance_score = scores["importance_score"],
                url              = item.url or None,
            )
            db.add(news_row)
            db.flush()  # get news_row.id

            # Store entity mentions
            mention_types = entities.get("mention_types", {})
            for sym, mtype in mention_types.items():
                from news.entity_extractor import ENTITY_MAP
                sector = ENTITY_MAP.get(sym, ("Unknown", []))[0]
                db.add(EntityMention(
                    news_event_id = news_row.id,
                    symbol        = sym,
                    sector        = sector,
                    mention_type  = mtype,
                ))

            if item.url:
                existing_urls.add(item.url)
            stored += 1

        except Exception as exc:
            log.error("Failed to store news item [%s]: %s", item.headline[:60], exc)
            db.rollback()
            continue

    db.commit()
    return stored, skipped


# ══════════════════════════════════════════════════════════════
# QUERY HELPERS (used by API routes)
# ══════════════════════════════════════════════════════════════
def get_recent_news(
    db: Session,
    limit: int = 50,
    company: str | None = None,
    event_type: str | None = None,
    min_impact: float = 0.0,
) -> list[dict]:
    q = db.query(NewsEvent)
    if company:
        q = q.filter(NewsEvent.company == company.upper())
    if event_type:
        q = q.filter(NewsEvent.event_type == event_type)
    if min_impact > 0:
        q = q.filter(NewsEvent.impact_score >= min_impact)
    rows = q.order_by(NewsEvent.timestamp.desc()).limit(limit).all()

    return [
        {
            "id":               r.id,
            "headline":         r.headline,
            "summary":          r.summary,
            "source":           r.source,
            "company":          r.company,
            "sector":           r.sector,
            "event_type":       r.event_type,
            "sentiment":        r.sentiment,
            "sentiment_score":  r.sentiment_score,
            "impact_score":     r.impact_score,
            "importance_score": r.importance_score,
            "timestamp":        r.timestamp.isoformat() if r.timestamp else None,
            "url":              r.url,
            "llm_analyzed":     bool(getattr(r, "llm_analyzed", False)),
            "llm_relevance":    getattr(r, "llm_relevance", None),
        }
        for r in rows
    ]


def get_news_stats(db: Session) -> dict:
    from sqlalchemy import func
    total = db.query(func.count(NewsEvent.id)).scalar() or 0
    by_type = (
        db.query(NewsEvent.event_type, func.count(NewsEvent.id))
        .group_by(NewsEvent.event_type)
        .all()
    )
    by_sentiment = (
        db.query(NewsEvent.sentiment, func.count(NewsEvent.id))
        .group_by(NewsEvent.sentiment)
        .all()
    )
    avg_impact = db.query(func.avg(NewsEvent.impact_score)).scalar() or 0.0

    return {
        "total_events":    total,
        "avg_impact_score": round(float(avg_impact), 1),
        "by_event_type":   {t: c for t, c in by_type if t},
        "by_sentiment":    {s: c for s, c in by_sentiment if s},
    }
