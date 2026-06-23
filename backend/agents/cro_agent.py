"""
Chief Research Officer Agent (7H)
Coordinates all agents, aggregates reports, generates the AQRTI Daily Intelligence Brief,
and assigns follow-up research tasks.

The CRO agent runs LAST in the pipeline — after all specialist agents.
It reads their AgentReports and ResearchFindings to synthesize the Daily Brief.

MAY NOT: deploy models, activate strategies, execute trades, modify capital.
"""

from __future__ import annotations

import sys, os, json
from datetime import date, timedelta
from typing import Optional

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from sqlalchemy.orm import Session
from aqrti.database.models import (
    AgentReport, ResearchFinding, ResearchBrief, KnowledgeScore,
    MarketRegime, KnowledgeEvent, Agent,
)
from aqrti.utils.logger import get_logger
from agents.agent_base import AgentBase
from agents.agent_registry import register_agent_class
from agents.agent_memory import get_cross_agent_findings, get_recurring_themes

log = get_logger("agent.cro")

BRIEF_SECTIONS = [
    "market_summary",
    "top_opportunities",
    "major_risks",
    "model_insights",
    "strategy_insights",
    "research_findings",
    "lessons_learned",
    "action_items",
]


class CROAgent(AgentBase):
    agent_id    = "cro"
    agent_type  = "cro"
    name        = "Chief Research Officer"
    description = "Coordinates all agents, aggregates findings, generates the Daily Intelligence Brief."

    def run(self, db: Session) -> dict:
        findings        = []
        recommendations = []
        today           = date.today()

        # ── Collect today's agent reports ─────────────────────────
        today_reports = (
            db.query(AgentReport)
            .filter(AgentReport.report_date == today)
            .order_by(AgentReport.created_at)
            .all()
        )

        # ── Collect all findings from today ──────────────────────
        today_findings = (
            db.query(ResearchFinding)
            .filter(ResearchFinding.finding_date == today)
            .order_by(ResearchFinding.urgency, ResearchFinding.created_at.desc())
            .all()
        )

        critical_findings = [f for f in today_findings if f.urgency == "critical"]
        high_findings     = [f for f in today_findings if f.urgency == "high"]
        normal_findings   = [f for f in today_findings if f.urgency == "normal"]

        # ── Get context for the brief ─────────────────────────────
        regime_row = db.query(MarketRegime).order_by(MarketRegime.date.desc()).first()
        current_regime = regime_row.regime if regime_row else "UNKNOWN"
        ks = db.query(KnowledgeScore).order_by(KnowledgeScore.date.desc()).first()
        knowledge_score = ks.overall_score if ks else 0.0

        # ── Build brief sections ──────────────────────────────────
        market_summary   = self._build_market_summary(today_reports, current_regime, today_findings)
        top_opportunities = self._extract_opportunities(today_findings)
        major_risks       = self._extract_risks(today_findings)
        model_insights    = self._extract_by_category(today_findings, "model")
        strategy_insights = self._extract_by_category(today_findings, "strategy")
        research_findings = self._top_findings(today_findings)
        lessons_learned   = self._extract_lessons(db)
        action_items      = self._build_action_items(critical_findings + high_findings)

        # ── Recurring themes (cross-agent) ───────────────────────
        themes = get_recurring_themes(db, days=3)
        if themes:
            for t in themes[:2]:
                findings.append({
                    "title":       f"Cross-Agent Theme: {t['category']} ({t['agent_count']} agents reporting)",
                    "description": f"Multiple agents ({t['agents']}) flagged issues in '{t['category']}' category.",
                    "evidence":    f"agent_count={t['agent_count']}, finding_count={t['finding_count']}",
                    "implication": "This is a systemic signal — not an isolated observation.",
                    "urgency":     "high" if t["agent_count"] >= 3 else "normal",
                    "subcategory": "cross_agent_theme",
                })

        # ── CRO summary finding ───────────────────────────────────
        findings.append({
            "title":       f"Daily Brief Issued — {today}",
            "description": (
                f"CRO synthesized {len(today_reports)} agent reports, "
                f"{len(today_findings)} findings. "
                f"Critical: {len(critical_findings)}, High: {len(high_findings)}."
            ),
            "evidence":    f"reports={len(today_reports)}, findings={len(today_findings)}",
            "implication": "See Daily Intelligence Brief for full details.",
            "urgency":     "normal" if not critical_findings else "critical",
            "subcategory": "brief_issued",
        })

        # ── Write the Research Brief ──────────────────────────────
        self._write_brief(
            db,
            today            = today,
            market_summary   = market_summary,
            top_opportunities = top_opportunities,
            major_risks       = major_risks,
            model_insights    = model_insights,
            strategy_insights = strategy_insights,
            research_findings = research_findings,
            lessons_learned   = lessons_learned,
            action_items      = action_items,
            regime_at         = current_regime,
            knowledge_score   = knowledge_score,
            report_ids        = [r.id for r in today_reports],
        )

        # ── Assign follow-up tasks for critical items ─────────────
        followups = self._assign_followups(db, critical_findings + high_findings[:3])
        if followups:
            recommendations.append(f"Assigned {len(followups)} follow-up research tasks.")

        # ── Broadcast CRO summary ─────────────────────────────────
        self.broadcast(
            db,
            subject=f"Daily Brief issued — {len(critical_findings)} critical, {len(high_findings)} high priority findings",
            body=market_summary,
            payload={"critical": len(critical_findings), "high": len(high_findings), "date": str(today)},
        )

        summary = (
            f"CRO brief for {today}: {len(today_reports)} reports aggregated. "
            f"{len(critical_findings)} critical findings. "
            f"Knowledge score: {knowledge_score:.1f}. "
            f"Regime: {current_regime}."
        )

        urgency = "critical" if critical_findings else "high" if high_findings else "normal"

        return {
            "title":           f"CRO Daily Brief — {today}",
            "summary":         summary,
            "findings":        findings,
            "recommendations": recommendations,
            "urgency":         urgency,
            "metadata": {
                "reports_aggregated": len(today_reports),
                "total_findings":     len(today_findings),
                "critical_findings":  len(critical_findings),
                "knowledge_score":    knowledge_score,
                "regime":             current_regime,
            },
        }

    def _build_market_summary(self, reports, regime, findings) -> str:
        market_rep = next((r for r in reports if r.agent_id == "market_research"), None)
        news_rep   = next((r for r in reports if r.agent_id == "news_research"),   None)
        parts = [f"Regime: {regime}."]
        if market_rep and market_rep.summary:
            parts.append(market_rep.summary)
        if news_rep and news_rep.summary:
            parts.append(news_rep.summary)
        regime_changes = [f for f in findings if "regime" in f.subcategory.lower() if f.subcategory]
        if regime_changes:
            parts.append(f"[!] Regime change detected: {regime_changes[0].title}")
        return " ".join(parts)

    def _extract_opportunities(self, findings) -> list[str]:
        opps = []
        for f in findings:
            if any(kw in (f.title or "").lower() for kw in ["leading", "strong", "resurrection", "opportunity", "outperform"]):
                opps.append(f"{f.agent_id}: {f.title}")
        return opps[:5]

    def _extract_risks(self, findings) -> list[str]:
        risks = []
        for f in findings:
            if f.urgency in ("high", "critical"):
                risks.append(f"[{f.urgency.upper()}] {f.agent_id}: {f.title}")
        return risks[:8]

    def _extract_by_category(self, findings, category: str) -> list[str]:
        return [
            f"{f.title} — {f.description[:120]}"
            for f in findings
            if f.category == category
        ][:5]

    def _top_findings(self, findings) -> list[str]:
        priority_order = {"critical": 0, "high": 1, "normal": 2, "low": 3}
        sorted_f = sorted(findings, key=lambda x: priority_order.get(x.urgency, 2))
        return [f"{f.agent_id}: {f.title}" for f in sorted_f[:10]]

    def _extract_lessons(self, db: Session) -> list[str]:
        from aqrti.database.models import LessonLearned
        cutoff = date.today() - timedelta(days=3)
        rows = (
            db.query(LessonLearned)
            .filter(LessonLearned.lesson_date >= cutoff)
            .order_by(LessonLearned.created_at.desc())
            .limit(5)
            .all()
        )
        return [f"[{r.category}] {r.title}" for r in rows]

    def _build_action_items(self, high_findings) -> list[str]:
        actions = []
        for f in high_findings[:6]:
            if f.urgency == "critical":
                actions.append(f"[URGENT]: {f.title} -- requires immediate human review")
            else:
                actions.append(f"[REVIEW]: {f.title}")
        return actions

    def _write_brief(
        self, db, today, market_summary, top_opportunities, major_risks,
        model_insights, strategy_insights, research_findings, lessons_learned,
        action_items, regime_at, knowledge_score, report_ids
    ) -> None:
        existing = db.query(ResearchBrief).filter(ResearchBrief.brief_date == today).first()
        if existing:
            existing.market_summary     = market_summary
            existing.top_opportunities  = json.dumps(top_opportunities)
            existing.major_risks        = json.dumps(major_risks)
            existing.model_insights     = json.dumps(model_insights)
            existing.strategy_insights  = json.dumps(strategy_insights)
            existing.research_findings  = json.dumps(research_findings)
            existing.lessons_learned    = json.dumps(lessons_learned)
            existing.action_items       = json.dumps(action_items)
            existing.regime_at          = regime_at
            existing.knowledge_score    = knowledge_score
            existing.agent_reports_used = json.dumps(report_ids)
        else:
            brief = ResearchBrief(
                brief_date          = today,
                title               = f"AQRTI Daily Intelligence Brief — {today}",
                market_summary      = market_summary,
                top_opportunities   = json.dumps(top_opportunities),
                major_risks         = json.dumps(major_risks),
                model_insights      = json.dumps(model_insights),
                strategy_insights   = json.dumps(strategy_insights),
                research_findings   = json.dumps(research_findings),
                lessons_learned     = json.dumps(lessons_learned),
                action_items        = json.dumps(action_items),
                regime_at           = regime_at,
                knowledge_score     = knowledge_score,
                agent_reports_used  = json.dumps(report_ids),
            )
            db.add(brief)

    def _assign_followups(self, db: Session, priority_findings) -> list[str]:
        from agents.agent_scheduler import create_task
        CATEGORY_AGENT_MAP = {
            "model":    "model_research",
            "strategy": "strategy_research",
            "risk":     "risk_research",
            "market":   "market_research",
            "news":     "news_research",
            "pattern":  "pattern_research",
        }
        assigned = []
        for f in priority_findings[:3]:
            target_agent = CATEGORY_AGENT_MAP.get(f.category, "cro")
            try:
                task = create_task(
                    db,
                    agent_id    = target_agent,
                    title       = f"Follow-up: {f.title[:100]}",
                    task_type   = "follow_up",
                    assigned_by = "cro",
                    priority    = 2,
                    description = f"CRO-assigned follow-up based on {f.urgency} finding: {f.description[:200]}",
                )
                assigned.append(task.task_id)
            except Exception as exc:
                log.warning("Follow-up task creation failed: %s", exc)
        return assigned


register_agent_class(CROAgent)
