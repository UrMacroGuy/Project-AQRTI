"""
News Research Agent (7C)
Tracks breaking news, emerging themes, narrative shifts, high-impact events,
and unusual news clusters.

MAY NOT: execute trades, modify strategies, retrain models.
"""

from __future__ import annotations

import sys, os, json
from collections import Counter
from datetime import date, timedelta

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from sqlalchemy.orm import Session
from aqrti.database.models import NewsEvent, SentimentRecord
from aqrti.utils.logger import get_logger
from agents.agent_base import AgentBase
from agents.agent_registry import register_agent_class

log = get_logger("agent.news_research")


class NewsResearchAgent(AgentBase):
    agent_id    = "news_research"
    agent_type  = "news"
    name        = "News Research Agent"
    description = "Tracks breaking news, emerging themes, narrative shifts, and unusual news clusters."

    def run(self, db: Session) -> dict:
        findings        = []
        recommendations = []
        today           = date.today()
        cutoff_7d       = today - timedelta(days=7)
        cutoff_1d       = today - timedelta(days=1)

        # ── 1. News Volume ────────────────────────────────────────
        try:
            today_count = (
                db.query(NewsEvent)
                .filter(NewsEvent.timestamp >= cutoff_1d)
                .count()
            )
            week_count = (
                db.query(NewsEvent)
                .filter(NewsEvent.timestamp >= cutoff_7d)
                .count()
            )
            daily_avg = week_count / 7 if week_count else 0
            if daily_avg > 0 and today_count > daily_avg * 1.5:
                findings.append({
                    "title":       f"Unusual News Volume: {today_count} articles today (avg {daily_avg:.0f})",
                    "description": f"Today's news volume is {(today_count/daily_avg - 1)*100:.0f}% above 7-day average.",
                    "evidence":    f"today={today_count}, 7d_avg={daily_avg:.1f}",
                    "implication": "High news volume may indicate a significant market event. Increase monitoring.",
                    "urgency":     "high",
                    "subcategory": "news_volume",
                })
        except Exception as exc:
            log.debug("News volume query skipped: %s", exc)

        # ── 2. Negative Sentiment Clusters ───────────────────────
        try:
            neg_articles = (
                db.query(NewsEvent)
                .filter(
                    NewsEvent.timestamp >= cutoff_7d,
                    NewsEvent.sentiment == "negative",
                )
                .all()
            )
            if neg_articles:
                symbol_counts = Counter(
                    a.company for a in neg_articles if a.company
                )
                for symbol, count in symbol_counts.most_common(3):
                    if count >= 3:
                        findings.append({
                            "title":       f"Negative News Cluster: {symbol} ({count} articles)",
                            "description": f"{symbol} has {count} negative news articles in the last 7 days.",
                            "evidence":    f"negative_count={count}",
                            "implication": f"Monitor {symbol} predictions for sentiment headwinds.",
                            "urgency":     "high" if count >= 5 else "normal",
                            "subcategory": "negative_cluster",
                            "symbol":      symbol,
                        })
        except Exception as exc:
            log.debug("Negative cluster query skipped: %s", exc)

        # ── 3. Emerging Themes via Category Analysis ──────────────
        try:
            recent_articles = (
                db.query(NewsEvent)
                .filter(NewsEvent.timestamp >= cutoff_7d)
                .all()
            )
            category_counts = Counter(
                a.event_type for a in recent_articles if a.event_type
            )
            for cat, count in category_counts.most_common(3):
                if count >= 5:
                    findings.append({
                        "title":       f"Emerging Theme: '{cat}' ({count} articles this week)",
                        "description": f"Category '{cat}' has {count} articles in the last 7 days.",
                        "evidence":    f"category={cat}, count={count}",
                        "implication": f"Strategies sensitive to '{cat}' may experience signal drift.",
                        "urgency":     "normal",
                        "subcategory": "emerging_theme",
                    })
        except Exception as exc:
            log.debug("Theme analysis skipped: %s", exc)

        # ── 4. Sentiment Shift ────────────────────────────────────
        try:
            recent_sent = (
                db.query(SentimentRecord)
                .filter(SentimentRecord.timestamp >= cutoff_7d)
                .order_by(SentimentRecord.timestamp.desc())
                .limit(100)
                .all()
            )
            if recent_sent:
                latest_avg = sum(s.score for s in recent_sent[:10] if s.score) / min(10, len(recent_sent))
                older_avg  = sum(s.score for s in recent_sent[10:] if s.score) / max(1, len(recent_sent) - 10)
                if abs(latest_avg - older_avg) > 15:
                    direction = "improving" if latest_avg > older_avg else "deteriorating"
                    findings.append({
                        "title":       f"Sentiment Shift: {direction} ({latest_avg:.1f} vs {older_avg:.1f})",
                        "description": f"Overall sentiment has shifted {direction}. Recent avg={latest_avg:.1f}, prior avg={older_avg:.1f}.",
                        "evidence":    f"recent_avg={latest_avg:.1f}, prior_avg={older_avg:.1f}, delta={latest_avg - older_avg:.1f}",
                        "implication": "Sentiment-driven strategy signals may be transitioning.",
                        "urgency":     "normal",
                        "subcategory": "sentiment_shift",
                    })
                    recommendations.append(f"Recalibrate sentiment thresholds — market narrative is {direction}.")
        except Exception as exc:
            log.debug("Sentiment shift query skipped: %s", exc)

        summary = (
            f"News research: {len(findings)} findings. "
            f"{'[!] High urgency items detected.' if any(f['urgency'] == 'high' for f in findings) else 'No critical alerts.'}"
        )
        urgency = "high" if any(f["urgency"] == "high" for f in findings) else "normal"

        return {
            "title":           f"News Research — {date.today()}",
            "summary":         summary,
            "findings":        findings,
            "recommendations": recommendations,
            "urgency":         urgency,
        }


register_agent_class(NewsResearchAgent)
