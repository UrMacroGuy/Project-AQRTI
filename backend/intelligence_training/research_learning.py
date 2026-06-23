"""
Research Learning Engine — Phase 8.5H
Extracts patterns and lessons from accumulated research to improve future predictions.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from aqrti.database.engine import get_session_factory
from aqrti.utils.logger import get_logger
from intelligence_training.research_dataset_builder import build_all_research_datasets

logger = get_logger("research_learning")


def extract_recurring_themes(datasets: Dict) -> List[Dict[str, Any]]:
    """Find themes that recur across research reports."""
    theme_counts: Dict[str, int] = {}
    theme_examples: Dict[str, List[str]] = {}

    for source, ds in datasets.items():
        for rec in ds.records:
            title = rec.get("title", "") or ""
            summary = rec.get("summary", "") or ""
            text = (title + " " + summary).lower()

            themes = {
                "regime_transition": ["regime", "transition", "shift"],
                "overconfidence": ["overconfident", "confidence", "calibrat"],
                "model_drift": ["drift", "decay", "performance"],
                "sector_rotation": ["rotation", "sector", "leadership"],
                "breadth_divergence": ["breadth", "diverge", "narrow"],
                "liquidity": ["liquidity", "volume", "institutional"],
                "sentiment_reversal": ["sentiment", "reversal", "surprise"],
            }
            for theme, keywords in themes.items():
                if any(k in text for k in keywords):
                    theme_counts[theme] = theme_counts.get(theme, 0) + 1
                    theme_examples.setdefault(theme, []).append(title[:80])

    result = []
    for theme, count in sorted(theme_counts.items(), key=lambda x: -x[1]):
        result.append({
            "theme": theme,
            "frequency": count,
            "examples": theme_examples.get(theme, [])[:3],
        })
    return result


def build_research_memory_summary(db=None) -> Dict[str, Any]:
    """
    Synthesize all research into a compact memory summary for AQRTI.
    Stored in research_memory table for retrieval.
    """
    own_session = db is None
    if own_session:
        db = get_session_factory()()
    try:
        datasets = build_all_research_datasets()
        themes = extract_recurring_themes(datasets)

        # Count lessons applied vs pending
        lesson_rows = db.execute(
            "SELECT applied, COUNT(*) as cnt FROM lessons_learned GROUP BY applied"
        ).fetchall()
        lesson_stats = {str(r.applied): r.cnt for r in lesson_rows}

        # Count findings by urgency
        finding_rows = db.execute(
            "SELECT urgency, COUNT(*) as cnt FROM research_findings GROUP BY urgency"
        ).fetchall()
        finding_stats = {r.urgency: r.cnt for r in finding_rows}

        # Recent knowledge score trend
        ks_rows = db.execute(
            "SELECT date, overall_score FROM knowledge_scores ORDER BY date DESC LIMIT 30"
        ).fetchall()
        ks_trend = [{"date": str(r.date), "score": r.overall_score} for r in ks_rows]

        summary = {
            "total_research_records": sum(ds.record_count for ds in datasets.values()),
            "recurring_themes": themes[:10],
            "lesson_stats": lesson_stats,
            "finding_urgency": finding_stats,
            "knowledge_score_trend": ks_trend,
            "sources": {k: ds.record_count for k, ds in datasets.items()},
            "generated_at": datetime.utcnow().isoformat(),
        }

        # Persist to research_memory table
        try:
            db.execute(
                """
                INSERT INTO research_memory
                    (memory_date, summary_json, themes_json, total_records, created_at)
                VALUES (:d, :summary, :themes, :total, :now)
                ON CONFLICT(memory_date) DO UPDATE SET
                    summary_json = excluded.summary_json,
                    themes_json = excluded.themes_json,
                    total_records = excluded.total_records,
                    created_at = excluded.created_at
                """,
                {
                    "d": date.today().isoformat(),
                    "summary": json.dumps(summary),
                    "themes": json.dumps(themes),
                    "total": sum(ds.record_count for ds in datasets.values()),
                    "now": datetime.utcnow().isoformat(),
                },
            )
            db.commit()
        except Exception as exc:
            logger.warning("Could not save research memory: %s", exc)

        logger.info("Research memory built: %d records, %d themes",
                    summary["total_research_records"], len(themes))
        return summary
    finally:
        if own_session:
            db.close()


def run_research_learning_pipeline() -> Dict[str, Any]:
    logger.info("Starting research learning pipeline")
    summary = build_research_memory_summary()
    return {"status": "complete", "summary": summary}
