"""
Market Research Agent (7B)
Monitors market breadth, sector rotation, volatility, regime changes, anomalies.
Produces daily market intelligence findings.

MAY NOT: execute trades, modify strategies, retrain models.
"""

from __future__ import annotations

import sys, os, json
from datetime import date, timedelta
from typing import Optional

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from sqlalchemy.orm import Session
from sqlalchemy import func
from aqrti.database.models import (
    MarketRegime, DailyPrice, Stock, SentimentRecord,
)
from aqrti.utils.logger import get_logger
from agents.agent_base import AgentBase
from agents.agent_registry import register_agent_class

log = get_logger("agent.market_research")


class MarketResearchAgent(AgentBase):
    agent_id    = "market_research"
    agent_type  = "market"
    name        = "Market Research Agent"
    description = "Monitors market breadth, sector rotation, volatility, regime changes, and anomalies."

    def run(self, db: Session) -> dict:
        findings      = []
        recommendations = []

        # ── 1. Regime Change Detection ────────────────────────────
        regimes = (
            db.query(MarketRegime)
            .order_by(MarketRegime.date.desc())
            .limit(10)
            .all()
        )
        if regimes:
            current = regimes[0]
            prior   = regimes[1] if len(regimes) > 1 else None
            if prior and current.regime != prior.regime:
                findings.append({
                    "title":       f"Regime Change: {prior.regime} → {current.regime}",
                    "description": (
                        f"Market regime shifted from {prior.regime} to {current.regime} "
                        f"on {current.date}. Confidence: {current.confidence:.0f}%."
                    ),
                    "evidence":    f"Prior: {prior.regime} ({prior.date}). Current: {current.regime} ({current.date}).",
                    "implication": "Strategy allocations and signal thresholds may need review.",
                    "urgency":     "high",
                    "subcategory": "regime_change",
                    "regime":      current.regime,
                })
                recommendations.append(
                    f"Review active strategies for compatibility with {current.regime} regime."
                )

        current_regime  = regimes[0].regime if regimes else "UNKNOWN"
        current_conf    = regimes[0].confidence if regimes else 0.0

        # ── 2. Volatility Analysis ────────────────────────────────
        cutoff = date.today() - timedelta(days=30)
        recent_regimes = [r for r in regimes if r.date >= cutoff]
        volatile_days  = sum(1 for r in recent_regimes if r.regime == "VOLATILE")
        if volatile_days > 10:
            findings.append({
                "title":       f"Elevated Volatility: {volatile_days} VOLATILE days in 30d",
                "description": f"Market has been in VOLATILE regime for {volatile_days} of the last 30 days.",
                "evidence":    f"volatile_days={volatile_days}/30",
                "implication": "Reduce position sizes; prefer defensive strategies.",
                "urgency":     "high",
                "subcategory": "volatility",
            })
            recommendations.append("Consider reducing portfolio exposure during elevated volatility.")

        # ── 3. Regime Confidence ──────────────────────────────────
        if current_conf < 60:
            findings.append({
                "title":       f"Low Regime Confidence: {current_conf:.0f}%",
                "description": f"Current {current_regime} regime has only {current_conf:.0f}% confidence.",
                "evidence":    f"regime={current_regime}, confidence={current_conf:.1f}%",
                "implication": "Regime transition may be imminent. Monitor closely.",
                "urgency":     "normal",
                "subcategory": "regime_confidence",
            })

        # ── 4. Sector Rotation via Sentiment ─────────────────────
        try:
            cutoff_sent = date.today() - timedelta(days=7)
            sector_query = (
                db.query(SentimentRecord.entity, func.avg(SentimentRecord.score).label("avg_sent"))
                .filter(
                    SentimentRecord.entity_type == "sector",
                    SentimentRecord.timestamp >= cutoff_sent,
                )
                .group_by(SentimentRecord.entity)
                .order_by(func.avg(SentimentRecord.score).desc())
                .limit(5)
                .all()
            )
            if sector_query:
                top_sector    = sector_query[0][0]
                top_score     = sector_query[0][1]
                bottom_sector = sector_query[-1][0]
                bottom_score  = sector_query[-1][1]
                if top_score and bottom_score and (top_score - bottom_score) > 20:
                    findings.append({
                        "title":       f"Sector Rotation Signal: {top_sector} leading",
                        "description": (
                            f"{top_sector} sentiment avg={top_score:.1f} vs "
                            f"{bottom_sector} avg={bottom_score:.1f}. Spread={top_score - bottom_score:.1f}."
                        ),
                        "evidence":    f"top={top_sector}:{top_score:.1f}, bottom={bottom_sector}:{bottom_score:.1f}",
                        "implication": f"Overweight {top_sector}; reduce {bottom_sector} exposure.",
                        "urgency":     "normal",
                        "subcategory": "sector_rotation",
                    })
        except Exception as exc:
            log.debug("Sector rotation query skipped: %s", exc)

        # ── 5. Anomaly Detection — unusual regime run ─────────────
        if len(regimes) >= 5:
            same_regime_streak = 1
            for i in range(1, len(regimes)):
                if regimes[i].regime == regimes[0].regime:
                    same_regime_streak += 1
                else:
                    break
            if same_regime_streak >= 7:
                findings.append({
                    "title":       f"Extended {current_regime} Streak: {same_regime_streak} consecutive days",
                    "description": f"Market has been in {current_regime} for {same_regime_streak} consecutive days.",
                    "evidence":    f"streak={same_regime_streak} days in {current_regime}",
                    "implication": "Mean-reversion strategies may become more viable soon.",
                    "urgency":     "normal",
                    "subcategory": "anomaly",
                })

        summary = (
            f"Market: {current_regime} (conf={current_conf:.0f}%). "
            f"{len(findings)} findings. "
            f"{'Regime change detected.' if any(f['subcategory'] == 'regime_change' for f in findings) else ''}"
        ).strip()

        urgency = "high" if any(f["urgency"] == "high" for f in findings) else "normal"

        return {
            "title":           f"Market Research — {date.today()}",
            "summary":         summary,
            "findings":        findings,
            "recommendations": recommendations,
            "urgency":         urgency,
            "metadata": {
                "current_regime":     current_regime,
                "regime_confidence":  current_conf,
                "regimes_analyzed":   len(regimes),
            },
        }


register_agent_class(MarketResearchAgent)
