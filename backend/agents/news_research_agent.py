"""
News Research Agent
Fetches and presents real-world market news in plain, readable format.
Auto-triggers news ingestion if DB is stale (>2 hours old).
Surfaces top stories, company-specific news, sector themes, and market-moving events
in language a non-expert can read and act on.

MAY NOT: execute trades, modify strategies, retrain models.
"""

from __future__ import annotations

import sys, os
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone

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
    # Original 20
    "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "WIPRO", "AXISBANK",
    "LTIM", "NESTLEIND", "BAJFINANCE", "MARUTI", "SUNPHARMA", "TATASTEEL",
    "TATAMOTORS", "KOTAKBANK", "TITAN", "ONGC", "HINDALCO", "SBIN", "BHARTIARTL",
    # Expanded 30
    "HCLTECH", "ITC", "LT", "HINDUNILVR", "ULTRACEMCO",
    "BAJAJFINSV", "NTPC", "ADANIENT", "ADANIPORTS", "JSWSTEEL",
    "TECHM", "COALINDIA", "BPCL", "HDFCLIFE", "SBILIFE",
    "INDUSINDBK", "M&M", "DIVISLAB", "DRREDDY", "EICHERMOT",
    "HEROMOTOCO", "CIPLA", "BRITANNIA", "APOLLOHOSP", "TRENT",
    "GRASIM", "SHREECEM", "BEL", "POWERGRID", "ASIANPAINT",
]

SOURCE_FRIENDLY = {
    "moneycontrol":    "MoneyControl",
    "economictimes":   "Economic Times",
    "livemint":        "LiveMint",
    "business_standard": "Business Standard",
    "financial_express": "Financial Express",
    "nse_announcement": "NSE Official",
}

SENTIMENT_EMOJI = {"positive": "↑", "negative": "↓", "neutral": "→"}
IMPACT_LABEL    = {(0, 40): "Low", (40, 65): "Medium", (65, 80): "High", (80, 101): "Critical"}


def _impact_label(score) -> str:
    s = score or 0
    for (lo, hi), label in IMPACT_LABEL.items():
        if lo <= s < hi:
            return label
    return "Unknown"


def _age_label(ts: datetime) -> str:
    if ts is None:
        return "unknown time"
    now  = datetime.utcnow()
    diff = now - ts
    mins = int(diff.total_seconds() / 60)
    if mins < 60:
        return f"{mins}m ago"
    hrs = mins // 60
    if hrs < 24:
        return f"{hrs}h ago"
    return f"{diff.days}d ago"


class NewsResearchAgent(AgentBase):
    agent_id    = "news_research"
    agent_type  = "news"
    name        = "News Research Agent"
    description = (
        "Fetches live market news and presents top stories in plain readable language. "
        "Auto-refreshes if news is stale. Shows what happened, which stocks are affected, "
        "and what it means for trading."
    )

    def run(self, db: Session) -> dict:
        findings        = []
        recommendations = []
        today           = date.today()
        cutoff_2h       = datetime.utcnow() - timedelta(hours=2)
        cutoff_24h      = datetime.utcnow() - timedelta(hours=24)
        cutoff_7d       = today - timedelta(days=7)

        # ── Auto-trigger ingestion if news is stale ─────────────────
        ingested_now = False
        try:
            latest = db.query(NewsEvent).order_by(NewsEvent.timestamp.desc()).first()
            needs_refresh = (
                latest is None or
                (latest.timestamp and latest.timestamp < cutoff_2h)
            )
            if needs_refresh:
                log.info("News DB stale — triggering live ingestion …")
                try:
                    from news.news_pipeline import run_news_pipeline
                    report = run_news_pipeline()
                    ingested_now = True
                    log.info("News ingestion complete: stored=%d", report.get("stored", 0))
                    # Refresh latest pointer
                    latest = db.query(NewsEvent).order_by(NewsEvent.timestamp.desc()).first()
                except Exception as exc:
                    log.warning("Auto-ingestion failed: %s", exc)
        except Exception as exc:
            log.debug("Staleness check failed: %s", exc)

        # ── How many news items do we have? ─────────────────────────
        try:
            total_news   = db.query(NewsEvent).count()
            today_news   = db.query(NewsEvent).filter(NewsEvent.timestamp >= cutoff_24h).count()
            news_available = total_news > 0
        except Exception:
            total_news = today_news = 0
            news_available = False

        # ═══════════════════════════════════════════════════════════
        # 1. TOP STORIES TODAY — highest impact, most readable
        # ═══════════════════════════════════════════════════════════
        if news_available:
            try:
                top_stories = (
                    db.query(NewsEvent)
                    .filter(NewsEvent.timestamp >= cutoff_24h)
                    .order_by(NewsEvent.impact_score.desc())
                    .limit(8)
                    .all()
                )
                if not top_stories:
                    # fall back to 7 days
                    top_stories = (
                        db.query(NewsEvent)
                        .order_by(NewsEvent.impact_score.desc())
                        .limit(8)
                        .all()
                    )

                if top_stories:
                    story_lines = []
                    for n in top_stories:
                        sent_arrow = SENTIMENT_EMOJI.get(n.sentiment or "neutral", "→")
                        source_str = SOURCE_FRIENDLY.get(n.source or "", n.source or "Unknown")
                        age_str    = _age_label(n.timestamp)
                        impact_str = _impact_label(n.impact_score)
                        company_str = f" [{n.company}]" if n.company else ""
                        summary_str = (
                            f" — {n.summary[:160].rstrip()}…"
                            if n.summary and len(n.summary) > 20 else ""
                        )
                        story_lines.append(
                            f"{sent_arrow} [{impact_str}]{company_str} {n.headline}{summary_str}"
                            f"  ({source_str}, {age_str})"
                        )

                    most_critical = top_stories[0]
                    findings.append({
                        "title": f"Top Market News ({today_news} stories today)",
                        "description": "\n\n".join(story_lines),
                        "evidence":    f"total_today={today_news}, total_db={total_news}",
                        "implication": (
                            f"Most impactful: {most_critical.headline[:100]} "
                            f"[{_impact_label(most_critical.impact_score)} impact, "
                            f"{most_critical.sentiment or 'neutral'} sentiment]"
                        ),
                        "urgency":     (
                            "high"   if any(n.impact_score and n.impact_score >= 75 for n in top_stories) else
                            "normal" if any(n.impact_score and n.impact_score >= 50 for n in top_stories) else
                            "low"
                        ),
                        "subcategory": "top_stories",
                        "category":    "news",
                    })
            except Exception as exc:
                log.debug("Top stories query failed: %s", exc)

            # ═══════════════════════════════════════════════════════
            # 2. CRITICAL / HIGH-IMPACT ALERTS
            # ═══════════════════════════════════════════════════════
            try:
                critical = (
                    db.query(NewsEvent)
                    .filter(
                        NewsEvent.timestamp >= cutoff_24h,
                        NewsEvent.impact_score >= 75,
                    )
                    .order_by(NewsEvent.impact_score.desc())
                    .all()
                )
                if critical:
                    for n in critical[:4]:
                        source_str  = SOURCE_FRIENDLY.get(n.source or "", n.source or "?")
                        company_str = n.company or "Market"
                        summary_str = n.summary[:300] if n.summary else "No summary available."
                        findings.append({
                            "title":       f"ALERT [{company_str}]: {n.headline[:100]}",
                            "description": (
                                f"Source: {source_str} | Sentiment: {n.sentiment or 'neutral'} | "
                                f"Impact: {n.impact_score:.0f}/100 | Published: {_age_label(n.timestamp)}\n\n"
                                f"{summary_str}"
                            ),
                            "evidence":    f"impact={n.impact_score}, sentiment={n.sentiment}, source={n.source}",
                            "implication": (
                                f"This is a high-impact event for {company_str}. "
                                f"{'Positive catalyst — monitor for buying opportunity.' if n.sentiment == 'positive' else 'Negative event — consider risk reduction.' if n.sentiment == 'negative' else 'Monitor for follow-through.'}"
                            ),
                            "urgency":     "high",
                            "subcategory": "high_impact_alert",
                            "category":    "news",
                        })
            except Exception as exc:
                log.debug("Critical news query failed: %s", exc)

            # ═══════════════════════════════════════════════════════
            # 3. COMPANY-SPECIFIC NEWS DIGEST
            # ═══════════════════════════════════════════════════════
            try:
                company_news = (
                    db.query(NewsEvent)
                    .filter(
                        NewsEvent.timestamp >= cutoff_24h,
                        NewsEvent.company.isnot(None),
                    )
                    .order_by(NewsEvent.impact_score.desc())
                    .limit(60)
                    .all()
                )
                if company_news:
                    by_company: dict[str, list] = defaultdict(list)
                    for n in company_news:
                        if n.company:
                            by_company[n.company].append(n)

                    # Find companies with negative news clusters
                    negative_clusters = {
                        co: items for co, items in by_company.items()
                        if sum(1 for n in items if n.sentiment == "negative") >= 2
                    }
                    # Find companies with positive momentum
                    positive_leaders = {
                        co: items for co, items in by_company.items()
                        if sum(1 for n in items if n.sentiment == "positive") >= 2
                    }

                    if negative_clusters:
                        worst_co  = max(negative_clusters, key=lambda c: len(negative_clusters[c]))
                        worst_items = negative_clusters[worst_co]
                        headlines   = [n.headline for n in sorted(worst_items, key=lambda x: x.impact_score or 0, reverse=True)[:3]]
                        findings.append({
                            "title": f"Negative News Cluster: {worst_co} ({len(worst_items)} stories)",
                            "description": (
                                f"{worst_co} has {len(worst_items)} news stories in the last 24h, "
                                f"{sum(1 for n in worst_items if n.sentiment=='negative')} negative.\n\n"
                                + "\n".join(f"  • {h}" for h in headlines)
                            ),
                            "evidence":    f"company={worst_co}, total={len(worst_items)}, negative={sum(1 for n in worst_items if n.sentiment=='negative')}",
                            "implication": f"Negative sentiment clustering around {worst_co} — AQRTI may reduce confidence on bullish signals for this stock.",
                            "urgency":     "high",
                            "subcategory": "company_news",
                            "category":    "news",
                        })

                    if positive_leaders:
                        best_co    = max(positive_leaders, key=lambda c: len(positive_leaders[c]))
                        best_items = positive_leaders[best_co]
                        headlines  = [n.headline for n in sorted(best_items, key=lambda x: x.impact_score or 0, reverse=True)[:3]]
                        findings.append({
                            "title": f"Positive News Leader: {best_co} ({len(best_items)} stories)",
                            "description": (
                                f"{best_co} has {len(best_items)} positive stories in 24h:\n\n"
                                + "\n".join(f"  • {h}" for h in headlines)
                            ),
                            "evidence":    f"company={best_co}, total={len(best_items)}, positive={sum(1 for n in best_items if n.sentiment=='positive')}",
                            "implication": f"Strong positive news flow for {best_co} — may support bullish momentum strategies.",
                            "urgency":     "low",
                            "subcategory": "company_news",
                            "category":    "news",
                        })
            except Exception as exc:
                log.debug("Company news digest failed: %s", exc)

            # ═══════════════════════════════════════════════════════
            # 4. SECTOR THEMES
            # ═══════════════════════════════════════════════════════
            try:
                sector_news = (
                    db.query(NewsEvent)
                    .filter(
                        NewsEvent.timestamp >= cutoff_24h,
                        NewsEvent.sector.isnot(None),
                    )
                    .all()
                )
                if sector_news:
                    sector_sentiment: dict[str, list[str]] = defaultdict(list)
                    for n in sector_news:
                        if n.sector and n.sentiment:
                            sector_sentiment[n.sector].append(n.sentiment)

                    sector_scores = {}
                    for sector, sents in sector_sentiment.items():
                        if len(sents) < 2:
                            continue
                        pos = sents.count("positive")
                        neg = sents.count("negative")
                        sector_scores[sector] = {
                            "total": len(sents), "positive": pos, "negative": neg,
                            "score": (pos - neg) / len(sents) * 100,
                        }

                    if sector_scores:
                        best_sector  = max(sector_scores, key=lambda s: sector_scores[s]["score"])
                        worst_sector = min(sector_scores, key=lambda s: sector_scores[s]["score"])
                        bs = sector_scores[best_sector]
                        ws = sector_scores[worst_sector]

                        findings.append({
                            "title": f"Sector Themes: {best_sector} leading, {worst_sector} under pressure",
                            "description": (
                                f"Best sector: {best_sector} — {bs['positive']} positive, {bs['negative']} negative, {bs['total']} total stories.\n"
                                f"Worst sector: {worst_sector} — {ws['positive']} positive, {ws['negative']} negative, {ws['total']} total stories.\n\n"
                                f"Sector breakdown: " +
                                ", ".join(
                                    f"{s}: +{d['positive']}/-{d['negative']}"
                                    for s, d in sorted(sector_scores.items(), key=lambda kv: kv[1]["score"], reverse=True)[:6]
                                )
                            ),
                            "evidence":    f"best={best_sector}(score={bs['score']:.0f}), worst={worst_sector}(score={ws['score']:.0f})",
                            "implication": (
                                f"Rotate toward {best_sector} stocks — positive news tailwind. "
                                f"Reduce exposure to {worst_sector} — negative news pressure."
                            ),
                            "urgency":     "normal",
                            "subcategory": "sector_themes",
                            "category":    "news",
                        })
            except Exception as exc:
                log.debug("Sector theme analysis failed: %s", exc)

            # ═══════════════════════════════════════════════════════
            # 5. SENTIMENT TREND (improving or deteriorating?)
            # ═══════════════════════════════════════════════════════
            try:
                recent_sent = (
                    db.query(SentimentRecord)
                    .filter(SentimentRecord.timestamp >= cutoff_7d)
                    .order_by(SentimentRecord.timestamp.desc())
                    .limit(100)
                    .all()
                )
                if len(recent_sent) >= 10:
                    latest10 = [s.score for s in recent_sent[:10]  if s.score is not None]
                    older    = [s.score for s in recent_sent[10:]   if s.score is not None]
                    if latest10 and older:
                        latest_avg = sum(latest10) / len(latest10)
                        older_avg  = sum(older)    / len(older)
                        delta      = latest_avg - older_avg
                        if abs(delta) > 8:
                            direction = "improving" if delta > 0 else "deteriorating"
                            mood      = "positive" if latest_avg > 55 else "negative" if latest_avg < 40 else "neutral"
                            findings.append({
                                "title": (
                                    f"Market Mood {direction.title()}: sentiment {latest_avg:.0f}/100 "
                                    f"({'up' if delta > 0 else 'down'} {abs(delta):.0f} pts)"
                                ),
                                "description": (
                                    f"Overall market sentiment has shifted {direction} this week. "
                                    f"Recent score: {latest_avg:.1f}/100 (prior: {older_avg:.1f}/100, change: {delta:+.1f}). "
                                    f"Current mood: {mood}.\n\n"
                                    f"What this means: "
                                    + (
                                        "News flow is becoming more optimistic — investors are seeing good news. Good environment for momentum strategies." if direction == "improving"
                                        else "News flow is worsening — more negative events. Be cautious with new positions."
                                    )
                                ),
                                "evidence":    f"latest_avg={latest_avg:.1f}, older_avg={older_avg:.1f}, delta={delta:.1f}",
                                "implication": (
                                    "Positive sentiment shift supports bullish momentum." if direction == "improving"
                                    else "Deteriorating sentiment — reduce position sizes, wait for stabilisation."
                                ),
                                "urgency":     "normal",
                                "subcategory": "sentiment_trend",
                                "category":    "news",
                            })
            except Exception as exc:
                log.debug("Sentiment trend query failed: %s", exc)

            # ═══════════════════════════════════════════════════════
            # 6. NSE ANNOUNCEMENTS (official filings)
            # ═══════════════════════════════════════════════════════
            try:
                nse_news = (
                    db.query(NewsEvent)
                    .filter(
                        NewsEvent.timestamp >= cutoff_24h,
                        NewsEvent.source == "nse_announcement",
                    )
                    .order_by(NewsEvent.impact_score.desc())
                    .limit(5)
                    .all()
                )
                if nse_news:
                    lines = []
                    for n in nse_news:
                        lines.append(
                            f"  • {n.headline[:130]} ({_age_label(n.timestamp)})"
                        )
                    findings.append({
                        "title": f"NSE Official Filings Today ({len(nse_news)} announcements)",
                        "description": (
                            "Official NSE corporate announcements — highest reliability:\n\n"
                            + "\n".join(lines)
                        ),
                        "evidence":    f"nse_count={len(nse_news)}",
                        "implication": "These are directly from NSE — high reliability. Check for earnings, dividends, board meetings.",
                        "urgency":     "normal",
                        "subcategory": "official_filings",
                        "category":    "news",
                    })
            except Exception as exc:
                log.debug("NSE announcements query failed: %s", exc)

        # ═══════════════════════════════════════════════════════════
        # 7. PRICE-BASED NEWS PROXIES (always run as supplementary)
        # ═══════════════════════════════════════════════════════════
        try:
            cutoff_30d    = today - timedelta(days=30)
            large_movers  = []
            volume_spikes = []

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

            if large_movers:
                large_movers.sort(key=lambda x: abs(x[1]), reverse=True)
                mover_lines = []
                for sym, ret, dt in large_movers[:5]:
                    direction = "surged" if ret > 0 else "fell"
                    reason    = (
                        "likely driven by positive news or earnings beat" if ret > 0
                        else "likely driven by negative news or sector weakness"
                    )
                    mover_lines.append(
                        f"  • {sym} {direction} {abs(ret):.1f}% on {dt} — {reason}"
                    )
                findings.append({
                    "title":       f"Price-Based News Signals: {len(large_movers)} large moves detected",
                    "description": (
                        "Stocks with significant price moves (likely news-driven):\n\n"
                        + "\n".join(mover_lines)
                        + ("\n\n(These are price signals — run news ingestion for actual headlines.)" if not news_available else "")
                    ),
                    "evidence":    f"large_movers={len(large_movers)}, volume_spikes={len(volume_spikes)}",
                    "implication": "Large moves suggest news catalysts. Check these stocks in the Market tab for details.",
                    "urgency":     "high" if any(abs(r) >= 5 for _, r, _ in large_movers) else "normal",
                    "subcategory": "price_signals",
                    "category":    "news",
                })

            if volume_spikes:
                volume_spikes.sort(key=lambda x: x[1], reverse=True)
                sym, ratio, dt = volume_spikes[0]
                findings.append({
                    "title": f"Unusual Volume: {sym} traded {ratio:.1f}x normal ({dt})",
                    "description": (
                        f"{sym} had {ratio:.1f}x its 20-day average volume on {dt}.\n\n"
                        f"What this means: When volume is this high, it usually means big investors "
                        f"(institutions, FIIs) are buying or selling aggressively. "
                        f"This is often a sign that important news is driving the stock."
                    ),
                    "evidence":    f"symbol={sym}, volume_ratio={ratio:.2f}x, date={dt}",
                    "implication": f"Investigate {sym} for news catalyst — high volume rarely happens without reason.",
                    "urgency":     "normal",
                    "subcategory": "volume_signal",
                    "category":    "news",
                })
        except Exception as exc:
            log.debug("Price-based proxy analysis failed: %s", exc)

        # ── Ingestion status notice ──────────────────────────────────
        if ingested_now:
            findings.insert(0, {
                "title":       f"News Refreshed: {today_news} new stories fetched",
                "description": (
                    f"News database was stale — live ingestion was triggered automatically. "
                    f"Fetched from MoneyControl, Economic Times, LiveMint, Business Standard, "
                    f"Financial Express, and NSE announcements."
                ),
                "evidence":    f"ingested_now=True, today_news={today_news}",
                "implication": "Fresh news data — findings below reflect latest market events.",
                "urgency":     "low",
                "subcategory": "data_freshness",
                "category":    "news",
            })
        elif not news_available:
            findings.append({
                "title":       "News Database Empty — Showing Price Signals Only",
                "description": (
                    "No news articles in the database yet. Price-based signals above are being used as proxies.\n\n"
                    "To get real news: make sure the backend is running at market hours (9am–4pm IST) "
                    "so the hourly agent can pull live headlines from RSS feeds."
                ),
                "evidence":    "news_events_count=0",
                "implication": "Price signals are less reliable than actual news — treat with caution.",
                "urgency":     "low",
                "subcategory": "data_freshness",
                "category":    "news",
            })
            recommendations.append("Ensure backend runs during market hours for automatic news ingestion.")

        if not findings:
            findings.append({
                "title":       "No Significant News Today",
                "description": "No high-impact news events detected. Market appears quiet.",
                "evidence":    f"total_today={today_news}",
                "implication": "Quiet news day — rely on price action and technical signals.",
                "urgency":     "low",
                "subcategory": "baseline",
                "category":    "news",
            })

        urgency  = "high" if any(f.get("urgency") == "high" for f in findings) else "normal"
        summary  = (
            f"News research: {len(findings)} findings. "
            f"{today_news} articles today. "
            f"{'[!] High-impact events detected.' if urgency == 'high' else 'No critical alerts.'}"
        )

        return {
            "title":           f"News Research — {today}",
            "summary":         summary,
            "findings":        findings,
            "recommendations": recommendations,
            "urgency":         urgency,
            "metadata": {
                "total_news":    total_news,
                "today_news":    today_news,
                "ingested_now":  ingested_now,
                "news_available": news_available,
            },
        }


register_agent_class(NewsResearchAgent)
