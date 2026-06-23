"""
Agent Memory
Persistent institutional memory for agents.
Agents store observations, prior findings, and pattern-of-thought
so each run builds on previous knowledge.

Backed by KnowledgeEvent table (category="agent") + AgentReport history.
"""

from __future__ import annotations

import sys, os, json
from datetime import date, timedelta
from typing import Optional

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from sqlalchemy.orm import Session
from aqrti.database.models import KnowledgeEvent, AgentReport, ResearchFinding
from aqrti.utils.logger import get_logger

log = get_logger("agent_memory")


def record_agent_observation(
    db:       Session,
    agent_id: str,
    title:    str,
    body:     str,
    outcome:  str   = "neutral",
    magnitude: float = None,
    metadata: dict  = None,
) -> KnowledgeEvent:
    """Write a single agent observation to institutional memory."""
    event = KnowledgeEvent(
        event_date    = date.today(),
        category      = "agent",
        event_type    = f"observation:{agent_id}",
        description   = f"[{agent_id}] {title} — {body[:300]}",
        outcome       = outcome,
        magnitude     = magnitude,
        metadata_json = json.dumps(metadata or {}),
    )
    db.add(event)
    return event


def get_agent_history(
    db:       Session,
    agent_id: str,
    days:     int = 30,
) -> list[dict]:
    """Recent reports from this agent."""
    cutoff = date.today() - timedelta(days=days)
    rows = (
        db.query(AgentReport)
        .filter(
            AgentReport.agent_id    == agent_id,
            AgentReport.report_date >= cutoff,
        )
        .order_by(AgentReport.report_date.desc())
        .limit(50)
        .all()
    )
    return [
        {
            "id":          r.id,
            "date":        str(r.report_date),
            "title":       r.title,
            "summary":     r.summary,
            "urgency":     r.urgency,
            "findings":    _safe_json(r.findings_json),
        }
        for r in rows
    ]


def get_cross_agent_findings(
    db:       Session,
    days:     int      = 7,
    urgency:  str | None = None,
    category: str | None = None,
) -> list[dict]:
    """All findings from all agents in the last N days."""
    cutoff = date.today() - timedelta(days=days)
    q = db.query(ResearchFinding).filter(ResearchFinding.finding_date >= cutoff)
    if urgency:
        q = q.filter(ResearchFinding.urgency == urgency)
    if category:
        q = q.filter(ResearchFinding.category == category)

    rows = q.order_by(ResearchFinding.finding_date.desc()).limit(200).all()
    return [
        {
            "id":          r.id,
            "date":        str(r.finding_date),
            "agent_id":    r.agent_id,
            "category":    r.category,
            "title":       r.title,
            "description": r.description,
            "evidence":    r.evidence,
            "implication": r.implication,
            "urgency":     r.urgency,
            "symbol":      r.symbol,
            "regime":      r.regime,
        }
        for r in rows
    ]


def get_recurring_themes(db: Session, days: int = 14) -> list[dict]:
    """
    Find topics that multiple agents have flagged independently
    — a sign of a cross-cutting issue.
    Returns themes sorted by agent_count desc.
    """
    findings = get_cross_agent_findings(db, days=days)
    theme_map: dict[str, dict] = {}

    for f in findings:
        key = f["category"]
        if key not in theme_map:
            theme_map[key] = {"category": key, "agents": set(), "count": 0, "latest": f["date"]}
        theme_map[key]["agents"].add(f["agent_id"])
        theme_map[key]["count"] += 1

    themes = sorted(
        [
            {
                "category":    t["category"],
                "agent_count": len(t["agents"]),
                "agents":      sorted(t["agents"]),
                "finding_count": t["count"],
            }
            for t in theme_map.values()
            if len(t["agents"]) > 1
        ],
        key=lambda x: x["agent_count"],
        reverse=True,
    )
    return themes


def _safe_json(s):
    try:
        return json.loads(s) if s else []
    except Exception:
        return []
