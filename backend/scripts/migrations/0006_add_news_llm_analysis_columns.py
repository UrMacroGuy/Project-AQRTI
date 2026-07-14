"""
Migration 0006 — LLM-analysis provenance columns on news_events

The NIM batch news analyzer (news/llm_analyzer.py) refines keyword-derived
sentiment/event_type with LLM judgment. Provenance must be explicit so a
reader can always tell which rows carry LLM-refined values vs raw keyword
scoring (CLAUDE.md rule: derived data is flagged wherever displayed).

  llm_analyzed  — 1 if this row's sentiment/event_type came from the LLM pass
  llm_relevance — 0..1 LLM-judged relevance of the article to its tagged
                  symbol's trading thesis (null until analyzed)
"""

MIGRATION_ID = "0006_add_news_llm_analysis_columns"
DESCRIPTION = "Add llm_analyzed + llm_relevance provenance columns to news_events"


def _has_column(conn, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r[1] == column for r in rows)


def up(conn):
    if not _has_column(conn, "news_events", "llm_analyzed"):
        conn.execute(
            "ALTER TABLE news_events ADD COLUMN llm_analyzed BOOLEAN NOT NULL DEFAULT 0"
        )
    if not _has_column(conn, "news_events", "llm_relevance"):
        conn.execute(
            "ALTER TABLE news_events ADD COLUMN llm_relevance FLOAT"
        )
