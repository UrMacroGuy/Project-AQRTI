"""
Data Quality Agent
Monitors all data sources, flags gaps, null prices, and stale FII/DII data.

MAY NOT: modify data, retrain models, execute trades.
"""

from __future__ import annotations

import sys, os
from datetime import date, timedelta

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from sqlalchemy import func
from sqlalchemy.orm import Session
from aqrti.database.models import DailyPrice, FIIDIIFlow
from aqrti.utils.logger import get_logger
from agents.agent_base import AgentBase
from agents.agent_registry import register_agent_class

log = get_logger("agent.data_quality")


class DataQualityAgent(AgentBase):
    agent_id    = "data_quality"
    agent_type  = "data_quality"
    name        = "Data Quality Agent"
    description = "Monitors all data sources for gaps, nulls, and staleness. Blocks bad data from learning pipeline."

    def run(self, db: Session) -> dict:
        findings        = []
        recommendations = []
        today           = date.today()
        yesterday       = today - timedelta(days=1)
        day_before      = today - timedelta(days=2)
        critical_failure = False

        # ── 1. Wrap quality_engine ────────────────────────────────
        try:
            from data_supremacy.quality_engine import run_quality_checks
            qresult = run_quality_checks(db, target_date=today)
            issues  = qresult.get("issues", [])
            score   = qresult.get("avg_score", 100.0)
            if score < 70:
                findings.append({
                    "title":       f"Data Quality Score Low: {score:.1f}/100",
                    "description": f"Quality engine reports avg score {score:.1f}. {len(issues)} issues found.",
                    "evidence":    f"avg_score={score:.1f}, issues={len(issues)}",
                    "implication": "Low quality data may corrupt learning pipeline outputs.",
                    "urgency":     "high" if score < 50 else "normal",
                    "subcategory": "quality_score",
                })
        except Exception as exc:
            log.debug("Quality engine skipped: %s", exc)

        # ── 2. DailyPrice gap check: today vs yesterday count ─────
        try:
            count_today = (
                db.query(func.count(DailyPrice.id))
                .filter(DailyPrice.date == today)
                .scalar() or 0
            )
            count_yesterday = (
                db.query(func.count(DailyPrice.id))
                .filter(DailyPrice.date == yesterday)
                .scalar() or 0
            )
            if count_yesterday > 0 and count_today < count_yesterday * 0.5:
                critical_failure = True
                findings.append({
                    "title":       f"Data Gap: Only {count_today}/{count_yesterday} prices loaded today",
                    "description": (
                        f"Today's DailyPrice count ({count_today}) is less than 50% of yesterday's "
                        f"({count_yesterday}). Possible incomplete ingestion."
                    ),
                    "evidence":    f"today={count_today}, yesterday={count_yesterday}, ratio={count_today/max(count_yesterday,1):.2f}",
                    "implication": "CRITICAL: Incomplete price data will break signal generation and backtesting.",
                    "urgency":     "critical",
                    "subcategory": "data_gap",
                })
                recommendations.append("Re-run daily ingestion pipeline immediately.")
            elif count_today > 0:
                findings.append({
                    "title":       f"Daily Price Coverage: {count_today} symbols ({today})",
                    "description": f"{count_today} price records loaded for today vs {count_yesterday} yesterday.",
                    "evidence":    f"today={count_today}, yesterday={count_yesterday}",
                    "implication": "Price data coverage is healthy.",
                    "urgency":     "low",
                    "subcategory": "data_coverage",
                })
        except Exception as exc:
            log.debug("DailyPrice gap check skipped: %s", exc)

        # ── 3. Null close price check (last 2 days) ────────────────
        try:
            null_closes = (
                db.query(DailyPrice.symbol, DailyPrice.date)
                .filter(
                    DailyPrice.date >= day_before,
                    DailyPrice.close == None,
                )
                .limit(10)
                .all()
            )
            if null_closes:
                symbols_affected = list(set(r.symbol for r in null_closes))[:5]
                findings.append({
                    "title":       f"Null Close Prices: {len(null_closes)} records (last 2 days)",
                    "description": (
                        f"Found {len(null_closes)} DailyPrice records with null close price "
                        f"in last 2 days. Affected: {', '.join(symbols_affected)}."
                    ),
                    "evidence":    f"null_close_count={len(null_closes)}, symbols={symbols_affected}",
                    "implication": "Null prices cause NaN in feature computation and prediction failures.",
                    "urgency":     "high",
                    "subcategory": "null_prices",
                })
                recommendations.append(f"Investigate null close prices for: {', '.join(symbols_affected)}.")
        except Exception as exc:
            log.debug("Null price check skipped: %s", exc)

        # ── 4. FII/DII freshness check ─────────────────────────────
        try:
            latest_flow = (
                db.query(FIIDIIFlow)
                .order_by(FIIDIIFlow.flow_date.desc())
                .first()
            )
            if latest_flow:
                days_stale = (today - latest_flow.flow_date).days
                if days_stale > 3:
                    findings.append({
                        "title":       f"FII/DII Data Stale: Last record {days_stale} days old",
                        "description": (
                            f"FIIDIIFlow last record is from {latest_flow.flow_date} "
                            f"({days_stale} days ago). Expected within 3 days."
                        ),
                        "evidence":    f"last_flow_date={latest_flow.flow_date}, days_stale={days_stale}",
                        "implication": "Stale FII/DII data means macro sentiment signals are outdated.",
                        "urgency":     "high" if days_stale > 7 else "normal",
                        "subcategory": "fii_dii_freshness",
                    })
                    recommendations.append("Re-scrape FII/DII flows from NSE CDN.")
            else:
                findings.append({
                    "title":       "FII/DII Data Missing",
                    "description": "No FII/DII flow records found in database.",
                    "evidence":    "fii_dii_rows=0",
                    "implication": "Macro flow data unavailable. Run data_supremacy FII scraper.",
                    "urgency":     "normal",
                    "subcategory": "fii_dii_freshness",
                })
        except Exception as exc:
            log.debug("FII/DII freshness check skipped: %s", exc)

        # ── 5. Alert CRO if critical failure ──────────────────────
        if critical_failure:
            try:
                self.send_message(
                    db,
                    to_agent     = "cro",
                    subject      = "URGENT: Critical data gap detected — price data incomplete",
                    body         = "Today's DailyPrice count is <50% of yesterday. Ingestion may have failed.",
                    message_type = "alert",
                    priority     = 1,
                )
            except Exception as exc:
                log.debug("CRO alert skipped: %s", exc)

        summary = (
            f"Data quality: {len(findings)} findings, "
            f"critical={critical_failure}, "
            f"null_prices={len([f for f in findings if f.get('subcategory') == 'null_prices'])}."
        )
        return {
            "title":           f"Data Quality Report — {today}",
            "summary":         summary,
            "findings":        findings,
            "recommendations": recommendations,
            "urgency":         "critical" if critical_failure else ("high" if any(f.get("urgency") == "high" for f in findings) else "normal"),
        }


register_agent_class(DataQualityAgent)
