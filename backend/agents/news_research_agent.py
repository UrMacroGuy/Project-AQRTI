"""
News Research Agent (7C)
Tracks breaking news, emerging themes, narrative shifts, high-impact events,
and unusual news clusters.

When news_events / sentiment_records are empty, pivots to price-anomaly detection
from daily_prices — large single-day moves, volume spikes, and price gaps are
treated as "newsworthy" market events until news ingestion runs.

MAY NOT: execute trades, modify strategies, retrain models.
"""

from __future__ import annotations

import sys, os
from collections import Counter, defaultdict
from datetime import date, timedelta

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from sqlalchemy.orm import Session
from sqlalchemy import func
from aqrti.database.models import NewsEvent, SentimentRecord, DailyPrice
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

        news_available = False

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
            if week_count > 0:
                news_available = True
                daily_avg = week_count / 7
                if today_count > daily_avg * 1.5:
                    findings.append({
                        "title":       f"Unusual News Volume: {today_count} articles today (avg {daily_avg:.0f})",
                        "description": f"Today's news volume is {(today_count / daily_avg - 1) * 100:.0f}% above 7-day average.",
                        "evidence":    f"today={today_count}, 7d_avg={daily_avg:.1f}",
                        "implication": "High news volume may indicate a significant market event. Increase monitoring.",
                        "urgency":     "high",
                        "subcategory": "news_volume",
                    })
        except Exception as exc:
            log.debug("News volume query skipped: %s", exc)

        # ── 2. Negative Sentiment Clusters ───────────────────────
        try:
            if news_available:
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
            if news_available:
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
                news_available = True
                latest_avg = sum(s.score for s in recent_sent[:10] if s.score) / max(1, sum(1 for s in recent_sent[:10] if s.score))
                older_avg  = sum(s.score for s in recent_sent[10:] if s.score) / max(1, sum(1 for s in recent_sent[10:] if s.score))
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

        # ── 5. Price-based "news proxy" when news DB is empty ─────
        if not news_available:
            try:
                cutoff_30d = today - timedelta(days=35)
                # Fetch recent 2 days and 30-day history per symbol
                recent_prices = (
                    db.query(DailyPrice.symbol, DailyPrice.date, DailyPrice.close,
                             DailyPrice.open, DailyPrice.volume, DailyPrice.daily_return)
                    .filter(DailyPrice.date >= cutoff_30d)
                    .order_by(DailyPrice.symbol, DailyPrice.date.asc())
                    .all()
                )

                sym_data: dict[str, list] = defaultdict(list)
                for row in recent_prices:
                    sym_data[row.symbol].append({
                        "date": row.date,
                        "close": row.close,
                        "open": row.open,
                        "volume": row.volume,
                        "ret": row.daily_return,
                    })

                large_moves  = []
                vol_spikes   = []
                price_gaps   = []

                for sym, history in sym_data.items():
                    if len(history) < 5:
                        continue

                    # Large single-day move on most recent session
                    latest = history[-1]
                    ret    = latest["ret"]
                    if ret is not None and abs(ret) >= 3.0:
                        large_moves.append((sym, ret, latest["date"]))

                    # Volume spike: latest volume vs 20-day avg
                    volumes = [h["volume"] for h in history[:-1] if h["volume"] and h["volume"] > 0]
                    if volumes and latest["volume"] and latest["volume"] > 0:
                        avg_vol = sum(volumes) / len(volumes)
                        vol_ratio = latest["volume"] / avg_vol
                        if vol_ratio >= 2.5:
                            vol_spikes.append((sym, vol_ratio, latest["date"]))

                    # Price gap: open vs previous close >= 2%
                    if len(history) >= 2:
                        prev_close = history[-2]["close"]
                        curr_open  = latest["open"]
                        if prev_close and curr_open and prev_close > 0:
                            gap_pct = (curr_open / prev_close - 1) * 100
                            if abs(gap_pct) >= 2.0:
                                price_gaps.append((sym, gap_pct, latest["date"]))

                large_moves.sort(key=lambda x: abs(x[1]), reverse=True)
                vol_spikes.sort(key=lambda x: x[1], reverse=True)
                price_gaps.sort(key=lambda x: abs(x[1]), reverse=True)

                if large_moves:
                    top = large_moves[:3]
                    names_desc = ", ".join(
                        f"{s} ({r:+.1f}%)" for s, r, _ in top
                    )
                    findings.append({
                        "title":       f"Large Price Moves Detected: {len(large_moves)} stocks moved >3%",
                        "description": (
                            f"{len(large_moves)} stocks recorded single-day moves exceeding ±3%: {names_desc}. "
                            "These are likely driven by news or order flow not yet captured in the news database."
                        ),
                        "evidence":    f"large_move_count={len(large_moves)}, top_movers={names_desc}",
                        "implication": "Investigate catalysts for these stocks; news database ingestion is pending.",
                        "urgency":     "high" if any(abs(r) >= 5.0 for _, r, _ in large_moves) else "normal",
                        "subcategory": "price_anomaly",
                    })
                    recommendations.append("Run news ingestion — large price moves suggest significant events pending capture.")

                if vol_spikes:
                    top_vs = vol_spikes[:3]
                    vs_desc = ", ".join(
                        f"{s} ({ratio:.1f}x)" for s, ratio, _ in top_vs
                    )
                    findings.append({
                        "title":       f"Volume Spikes: {len(vol_spikes)} stocks with >2.5× average volume",
                        "description": (
                            f"Unusual trading volume detected: {vs_desc}. "
                            "High volume without confirmed news is a sentinel signal."
                        ),
                        "evidence":    f"spike_count={len(vol_spikes)}, top_spikes={vs_desc}",
                        "implication": "Monitor these stocks for news catalysts; elevated volume precedes price moves.",
                        "urgency":     "normal",
                        "subcategory": "volume_anomaly",
                    })

                if price_gaps:
                    top_gaps = price_gaps[:3]
                    gap_desc = ", ".join(
                        f"{s} ({g:+.1f}%)" for s, g, _ in top_gaps
                    )
                    findings.append({
                        "title":       f"Price Gaps at Open: {len(price_gaps)} stocks gapped >2%",
                        "description": (
                            f"Opening price gaps vs prior close: {gap_desc}. "
                            "Gaps often reflect pre-market news or corporate events."
                        ),
                        "evidence":    f"gap_count={len(price_gaps)}, top_gaps={gap_desc}",
                        "implication": "Confirm whether gaps are news-driven before entering positions.",
                        "urgency":     "normal",
                        "subcategory": "price_gap",
                    })

            except Exception as exc:
                log.debug("Price-proxy news analysis failed: %s", exc)

        # ── Fallback: ensure at least 1 finding ───────────────────
        if not findings:
            findings.append({
                "title":       "News Database Empty — No Events Captured Yet",
                "description": "Neither news_events nor sentiment_records contain data. News ingestion has not run.",
                "evidence":    "news_count=0, sentiment_count=0, no price anomalies detected",
                "implication": "Schedule news ingestion to populate event-driven signals.",
                "urgency":     "low",
                "subcategory": "data_coverage",
            })

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
