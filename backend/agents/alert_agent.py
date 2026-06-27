"""
Alert Agent
Aggregates critical alerts from all agents into a unified daily alert summary.

MAY NOT: modify strategies, execute trades, retrain models.
"""

from __future__ import annotations

import sys, os, json
from datetime import date, datetime, timedelta

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from sqlalchemy.orm import Session
from aqrti.database.models import (
    AgentMessage, ResearchFinding, StrategyV2,
    KnowledgeScore, EquityCurvePoint, ResearchBrief,
)
from aqrti.utils.logger import get_logger
from agents.agent_base import AgentBase
from agents.agent_registry import register_agent_class

log = get_logger("agent.alert")


class AlertAgent(AgentBase):
    agent_id    = "alert"
    agent_type  = "alert"
    name        = "Alert Agent"
    description = "Aggregates critical alerts from all agents into a unified daily alert summary."

    def run(self, db: Session) -> dict:
        findings        = []
        recommendations = []
        today           = date.today()
        cutoff_24h      = datetime.utcnow() - timedelta(hours=24)
        alert_count     = 0

        # ── 1. Unread URGENT messages (last 24h) ──────────────────
        try:
            urgent_msgs = (
                db.query(AgentMessage)
                .filter(
                    AgentMessage.created_at >= cutoff_24h,
                    AgentMessage.priority == 1,
                    AgentMessage.read == False,
                )
                .order_by(AgentMessage.created_at.desc())
                .limit(20)
                .all()
            )
            for msg in urgent_msgs:
                alert_count += 1
                findings.append({
                    "title":       f"URGENT Message: [{msg.from_agent}] {msg.subject}",
                    "description": msg.body or "No body.",
                    "evidence":    f"from={msg.from_agent}, type={msg.message_type}, created={msg.created_at}",
                    "implication": "Urgent inter-agent alert requires immediate review.",
                    "urgency":     "critical",
                    "subcategory": "urgent_message",
                })
        except Exception as exc:
            log.debug("Urgent message scan skipped: %s", exc)

        # ── 2. CRITICAL ResearchFindings (last 24h) ───────────────
        try:
            critical_findings = (
                db.query(ResearchFinding)
                .filter(
                    ResearchFinding.finding_date >= today - timedelta(days=1),
                    ResearchFinding.urgency.in_(["critical", "CRITICAL"]),
                    ResearchFinding.actioned == False,
                )
                .order_by(ResearchFinding.finding_date.desc())
                .limit(10)
                .all()
            )
            for rf in critical_findings:
                alert_count += 1
                findings.append({
                    "title":       f"CRITICAL Finding: [{rf.agent_id}] {rf.title}",
                    "description": rf.description or "",
                    "evidence":    f"agent={rf.agent_id}, category={rf.category}, date={rf.finding_date}",
                    "implication": rf.implication or "Requires immediate investigation.",
                    "urgency":     "critical",
                    "subcategory": "critical_finding",
                    "symbol":      rf.symbol,
                })
        except Exception as exc:
            log.debug("Critical findings scan skipped: %s", exc)

        # ── 3. Strategy sharpe < -0.5 (last 30d) ─────────────────
        try:
            bad_strategies = (
                db.query(StrategyV2.strategy_id, StrategyV2.name, StrategyV2.sharpe_ratio)
                .filter(
                    StrategyV2.sharpe_ratio < -0.5,
                    StrategyV2.status.in_(["promoted", "shadow"]),
                )
                .order_by(StrategyV2.sharpe_ratio.asc())
                .limit(5)
                .all()
            )
            if bad_strategies:
                for strat in bad_strategies:
                    alert_count += 1
                    findings.append({
                        "title":       f"Poor Strategy: {strat.name or strat.strategy_id} (Sharpe={strat.sharpe_ratio:.2f})",
                        "description": f"Strategy '{strat.strategy_id}' has Sharpe ratio {strat.sharpe_ratio:.2f} < -0.5.",
                        "evidence":    f"strategy_id={strat.strategy_id}, sharpe={strat.sharpe_ratio:.3f}",
                        "implication": "This strategy is destroying value. Demote or retire immediately.",
                        "urgency":     "high",
                        "subcategory": "poor_strategy",
                    })
                recommendations.append(f"Demote {len(bad_strategies)} strategies with Sharpe < -0.5.")
        except Exception as exc:
            log.debug("Strategy sharpe check skipped: %s", exc)

        # ── 4. KnowledgeScore < 40 ────────────────────────────────
        try:
            ks = db.query(KnowledgeScore).order_by(KnowledgeScore.date.desc()).first()
            if ks and ks.overall_score is not None and ks.overall_score < 40:
                alert_count += 1
                findings.append({
                    "title":       f"Knowledge Score Critical: {ks.overall_score:.1f}/100",
                    "description": (
                        f"AQRTI knowledge score dropped to {ks.overall_score:.1f}/100 "
                        f"as of {ks.date}. System intelligence is degrading."
                    ),
                    "evidence":    (
                        f"overall={ks.overall_score:.1f}, prediction={ks.prediction_quality}, "
                        f"portfolio={ks.portfolio_quality}, learning={ks.learning_quality}"
                    ),
                    "implication": "System is below intelligence threshold. Manual review required.",
                    "urgency":     "critical",
                    "subcategory": "knowledge_score_critical",
                })
                recommendations.append("Trigger manual learning loop — knowledge score critically low.")
        except Exception as exc:
            log.debug("KnowledgeScore check skipped: %s", exc)

        # ── 5. EquityCurve drawdown < -10% ────────────────────────
        try:
            eq = db.query(EquityCurvePoint).order_by(EquityCurvePoint.date.desc()).first()
            if eq and eq.drawdown_pct is not None and eq.drawdown_pct < -10:
                alert_count += 1
                findings.append({
                    "title":       f"Portfolio Drawdown Alert: {eq.drawdown_pct:.1f}% (as of {eq.date})",
                    "description": (
                        f"Portfolio '{eq.portfolio_name}' is in {eq.drawdown_pct:.1f}% drawdown. "
                        f"Current value: {eq.total_value:,.0f}."
                    ),
                    "evidence":    f"drawdown={eq.drawdown_pct:.2f}%, total_value={eq.total_value:.0f}, date={eq.date}",
                    "implication": "Drawdown exceeds -10% threshold. Review open positions and strategy health.",
                    "urgency":     "critical" if eq.drawdown_pct < -20 else "high",
                    "subcategory": "drawdown_alert",
                })
                recommendations.append(f"Review portfolio — drawdown at {eq.drawdown_pct:.1f}%.")
        except Exception as exc:
            log.debug("Equity curve check skipped: %s", exc)

        # ── 6. Mark URGENT messages as read ───────────────────────
        try:
            urgent_msgs_to_mark = (
                db.query(AgentMessage)
                .filter(
                    AgentMessage.created_at >= cutoff_24h,
                    AgentMessage.priority == 1,
                    AgentMessage.read == False,
                )
                .all()
            )
            for msg in urgent_msgs_to_mark:
                msg.read = True
        except Exception as exc:
            log.debug("Message read-mark skipped: %s", exc)

        # ── 7. Write AlertSummary as ResearchBrief (update if exists) ───
        try:
            if findings and alert_count > 0:
                import json as _json
                alert_items = [
                    {"urgency": f.get("urgency"), "title": f["title"], "agent": f.get("subcategory")}
                    for f in findings
                ]
                existing_brief = db.query(ResearchBrief).filter(ResearchBrief.brief_date == today).first()
                if existing_brief:
                    # Append alert summary to existing brief's action_items
                    existing_brief.action_items = _json.dumps([r for r in recommendations])
                else:
                    brief = ResearchBrief(
                        brief_date     = today,
                        title          = f"Alert Summary — {today} ({alert_count} alerts)",
                        market_summary = f"{alert_count} alerts across all research agents.",
                        major_risks    = _json.dumps(alert_items[:10]),
                        action_items   = _json.dumps([r for r in recommendations]),
                    )
                    db.add(brief)
        except Exception as exc:
            log.debug("Alert brief write skipped: %s", exc)

        if not findings:
            findings.append({
                "title":       "No Alerts — All Systems Normal",
                "description": "No urgent messages, critical findings, poor strategies, or portfolio issues detected.",
                "evidence":    "alerts=0",
                "implication": "System is operating within normal parameters.",
                "urgency":     "low",
                "subcategory": "all_clear",
            })

        summary = (
            f"Alert agent: {alert_count} active alerts, "
            f"critical={len([f for f in findings if f.get('urgency') == 'critical'])}, "
            f"high={len([f for f in findings if f.get('urgency') == 'high'])}."
        )
        return {
            "title":           f"Alert Summary — {today}",
            "summary":         summary,
            "findings":        findings,
            "recommendations": recommendations,
            "urgency":         "critical" if any(f.get("urgency") == "critical" for f in findings) else "normal",
        }


register_agent_class(AlertAgent)
