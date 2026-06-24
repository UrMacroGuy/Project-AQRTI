"""
News Research Agent
Tracks breaking news, high-impact events, unusual price moves, and sentiment shifts.
Falls back to price-based anomaly detection when news DB tables are empty.

MAY NOT: execute trades, modify strategies, retrain models.
"""

from __future__ import annotations

import sys, os
from collections import Counter
from datetime import date, timedelta

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from sqlalchemy.orm import Session
from aqrti.database.models import NewsEvent, SentimentRecord, DailyPrice
from aqrti.utils.logger import get_logger
from agents.agent_base import AgentBase
from agents.agent_registry import register_agent_class

log = get_logger("agent.news_research")

STOCK_UNIVERSE = [
    "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "WIPRO", "AXISBANK",
    "LTIM", "NESTLEIND", "BAJFINANCE", "MARUTI", "SUNPHARMA", "TATASTEEL",
    "TATAMOTORS", "KOTAKBANK", "TITAN", "ONGC", "HINDALCO", "SBIN", "BHARTIARTL",
]


class NewsResearchAgent(AgentBase):
    agent_id    = "news_research"
    agent_type  = "news"
    name        = "News Research Agent"
    description = "Tracks breaking news, sentiment shifts, and price anomalies as news proxies."

    def run(self, db: Session) -> dict:
        findings        = []
        recommendations = []
        today           = date.today()
        cutoff_7d       = today - timedelta(days=7)
        cutoff_1d       = today - timedelta(days=1)
        cutoff_30d      = today - timedelta(days=30)
        cutoff_52w      = today - timedelta(weeks=52)

        news_available = False

        # ── 1. News Volume ────────────────────────────────────────
        try:
            today_count = db.query(NewsEvent).filter(NewsEvent.timestamp >= cutoff_1d).count()
            week_count  = db.query(NewsEvent).filter(NewsEvent.timestamp >= cutoff_7d).count()
            if week_count > 0:
                news_available = True
                daily_avg = week_count / 7
                if daily_avg > 0 and today_count > daily_avg * 1.5:
                    findings.append({
                        "title":       f"Unusual News Volume: {today_count} articles today (7d avg {daily_avg:.0f})",
                        "description": f"Today's news volume is {(today_count / daily_avg - 1) * 100:.0f}% above 7-day average.",
                        "evidence":    f"today={today_count}, 7d_avg={daily_avg:.1f}",
                        "implication": "High news volume may indicate a significant market event. Increase monitoring.",
                        "urgency":     "high",
                        "subcategory": "news_volume",
                    })
        except Exception as exc:
            log.debug("News volume query skipped: %s", exc)

        # ── 2. Negative Clusters ──────────────────────────────────
        if news_available:
            try:
                neg_articles = (
                    db.query(NewsEvent)
                    .filter(NewsEvent.timestamp >= cutoff_7d, NewsEvent.sentiment == "negative")
                    .all()
                )
                if neg_articles:
                    symbol_counts = Counter(a.company for a in neg_articles if a.company)
                    for symbol, count in symbol_counts.most_common(3):
                        if count >= 3:
                            findings.append({
                                "title":       f"Negative News Cluster: {symbol} ({count} articles, 7d)",
                                "description": f"{symbol} has {count} negative news articles in the last 7 days.",
                                "evidence":    f"negative_count={count}, symbol={symbol}",
                                "implication": f"Monitor {symbol} predictions for sentiment headwinds.",
                                "urgency":     "high" if count >= 5 else "normal",
                                "subcategory": "negative_cluster",
                                "symbol":      symbol,
                            })
            except Exception as exc:
                log.debug("Negative cluster query skipped: %s", exc)

            try:
                recent_articles = db.query(NewsEvent).filter(NewsEvent.timestamp >= cutoff_7d).all()
                category_counts = Counter(a.event_type for a in recent_articles if a.event_type)
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

            try:
                recent_sent = (
                    db.query(SentimentRecord)
                    .filter(SentimentRecord.timestamp >= cutoff_7d)
                    .order_by(SentimentRecord.timestamp.desc())
                    .limit(100)
                    .all()
                )
                if len(recent_sent) >= 10:
                    latest_avg = sum(s.score for s in recent_sent[:10] if s.score) / min(10, len(recent_sent))
                    older_avg  = sum(s.score for s in recent_sent[10:] if s.score) / max(1, len(recent_sent) - 10)
                    if abs(latest_avg - older_avg) > 15:
                        direction = "improving" if latest_avg > older_avg else "deteriorating"
                        findings.append({
                            "title":       f"Sentiment Shift: {direction} ({latest_avg:.1f} vs {older_avg:.1f})",
                            "description": (
                                f"Overall sentiment has shifted {direction}. "
                                f"Recent avg={latest_avg:.1f}, prior avg={older_avg:.1f}."
                            ),
                            "evidence":    f"recent_avg={latest_avg:.1f}, prior_avg={older_avg:.1f}",
                            "implication": "Sentiment-driven strategy signals may be transitioning.",
                            "urgency":     "normal",
                            "subcategory": "sentiment_shift",
                        })
                        recommendations.append(f"Recalibrate sentiment thresholds — market narrative is {direction}.")
            except Exception as exc:
                log.debug("Sentiment shift query skipped: %s", exc)

        # ── 3. Price-Based News Proxies ───────────────────────────
        try:
            large_movers  = []
            volume_spikes = []
            gap_events    = []

            for symbol in STOCK_UNIVERSE:
                rows = (
                    db.query(DailyPrice)
                    .filter(DailyPrice.symbol == symbol, DailyPrice.date >= cutoff_30d)
                    .order_by(DailyPrice.date.desc())
                    .limit(22)
                    .all()
                )
                if len(rows) < 2:
                    continue

                latest = rows[0]
                prev   = rows[1]

                if latest.daily_return is not None and abs(latest.daily_return) >= 3.0:
                    large_movers.append((symbol, latest.daily_return, latest.date))

                if latest.volume and len(rows) >= 10:
                    vol_list = [r.volume for r in rows[1:] if r.volume]
                    avg_vol  = sum(vol_list) / len(vol_list) if vol_list else 0
                    if avg_vol > 0 and latest.volume > avg_vol * 2.5:
                        volume_spikes.append((symbol, latest.volume / avg_vol, latest.date))

                if latest.open and prev.close and prev.close > 0:
                    gap = (latest.open - prev.close) / prev.close * 100
                    if abs(gap) >= 2.5:
                        gap_events.append((symbol, gap, latest.date))

            if large_movers:
                large_movers.sort(key=lambda x: abs(x[1]), reverse=True)
                for sym, ret, dt in large_movers[:3]:
                    findings.append({
                        "title":       f"Large Price Move: {sym} {ret:+.1f}% on {dt}",
                        "description": (
                            f"{sym} moved {ret:+.1f}% in a single session — likely driven by "
                            f"{'positive catalyst (earnings beat, upgrade, or sector tailwind)' if ret > 0 else 'negative catalyst (earnings miss, downgrade, or macro pressure)'}."
                        ),
                        "evidence":    f"symbol={sym}, daily_return={ret:.2f}%, date={dt}",
                        "implication": f"{'Monitor for follow-through buying.' if ret > 0 else 'Monitor for continued selling pressure.'}",
                        "urgency":     "high" if abs(ret) >= 5 else "normal",
                        "subcategory": "large_price_move",
                        "symbol":      sym,
                    })

            if volume_spikes:
                volume_spikes.sort(key=lambda x: x[1], reverse=True)
                sym, ratio, dt = volume_spikes[0]
                findings.append({
                    "title":       f"Volume Spike: {sym} traded {ratio:.1f}x normal on {dt}",
                    "description": (
                        f"{sym} had {ratio:.1f}x its 20-day average volume — "
                        f"signals institutional accumulation or distribution."
                    ),
                    "evidence":    f"symbol={sym}, volume_ratio={ratio:.2f}x, date={dt}",
                    "implication": f"Unusual volume in {sym} suggests informed trading. Monitor price direction.",
                    "urgency":     "normal",
                    "subcategory": "volume_spike",
                    "symbol":      sym,
                })

            if gap_events:
                gap_events.sort(key=lambda x: abs(x[1]), reverse=True)
                sym, gap, dt = gap_events[0]
                gap_type = "gap-up" if gap > 0 else "gap-down"
                findings.append({
                    "title":       f"Price Gap: {sym} {gap_type} {gap:+.1f}% on {dt}",
                    "description": (
                        f"{sym} opened {gap:+.1f}% vs prior close on {dt}. "
                        f"{'Positive overnight catalyst.' if gap > 0 else 'Negative overnight catalyst.'}"
                    ),
                    "evidence":    f"symbol={sym}, gap_pct={gap:.2f}%, date={dt}",
                    "implication": f"{'Gap-ups on volume often continue intraday.' if gap > 0 else 'Gap-downs signal sustained weakness.'}",
                    "urgency":     "normal",
                    "subcategory": "price_gap",
                    "symbol":      sym,
                })
        except Exception as exc:
            log.debug("Price-based proxy analysis skipped: %s", exc)

        # ── 4. 52-Week Extremes ───────────────────────────────────
        try:
            highs_52w = []
            lows_52w  = []
            for symbol in STOCK_UNIVERSE:
                rows = (
                    db.query(DailyPrice.close, DailyPrice.date)
                    .filter(DailyPrice.symbol == symbol, DailyPrice.date >= cutoff_52w)
                    .order_by(DailyPrice.date.asc())
                    .all()
                )
                if len(rows) < 30:
                    continue
                closes  = [r.close for r in rows if r.close]
                if not closes:
                    continue
                latest  = closes[-1]
                max_52w = max(closes)
                min_52w = min(closes)
                if latest >= max_52w * 0.98:
                    highs_52w.append(symbol)
                elif latest <= min_52w * 1.02:
                    lows_52w.append(symbol)

            if highs_52w:
                findings.append({
                    "title":       f"{len(highs_52w)} stocks at 52-week highs: {', '.join(highs_52w[:4])}",
                    "description": f"{', '.join(highs_52w)} trading near 52-week highs — momentum leaders.",
                    "evidence":    f"52w_highs={highs_52w}",
                    "implication": "Breakout candidates. Momentum strategies may generate bullish signals.",
                    "urgency":     "low",
                    "subcategory": "52w_high",
                })

            if lows_52w:
                findings.append({
                    "title":       f"{len(lows_52w)} stocks at 52-week lows: {', '.join(lows_52w[:4])}",
                    "description": f"{', '.join(lows_52w)} trading near 52-week lows — potential distress.",
                    "evidence":    f"52w_lows={lows_52w}",
                    "implication": "Avoid or close long positions in 52-week low stocks.",
                    "urgency":     "normal" if len(lows_52w) >= 3 else "low",
                    "subcategory": "52w_low",
                })
        except Exception as exc:
            log.debug("52-week high/low analysis skipped: %s", exc)

        if not findings:
            findings.append({
                "title":       "News Database Empty — No Price Anomalies Detected",
                "description": "news_events table is empty and no significant price anomalies found in the last 30 days.",
                "evidence":    "news_events_count=0, no_price_spikes",
                "implication": "Run the news ingestion pipeline from Research Ops to populate data.",
                "urgency":     "low",
                "subcategory": "data_coverage",
            })
            recommendations.append("Trigger news ingestion from Research Ops page.")

        if not news_available and findings:
            recommendations.append("News DB empty — price moves above are surrogates. Run ingestion for full analysis.")

        summary = (
            f"News research: {len(findings)} findings. "
            f"{'[!] High urgency items detected.' if any(f['urgency'] == 'high' for f in findings) else 'No critical alerts.'}"
        )
        urgency = "high" if any(f["urgency"] == "high" for f in findings) else "normal"

        return {
            "title":           f"News Research — {today}",
            "summary":         summary,
            "findings":        findings,
            "recommendations": recommendations,
            "urgency":         urgency,
        }


register_agent_class(NewsResearchAgent)
