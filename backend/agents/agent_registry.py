"""
Agent Registry
Central directory of all AQRTI research agents.
Provides lookup, bulk-registration, and health summary.
"""

from __future__ import annotations

import sys, os
from typing import Optional

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from sqlalchemy.orm import Session
from aqrti.database.models import Agent, AgentReport, AgentTask
from aqrti.utils.logger import get_logger

log = get_logger("agent_registry")

# Populated lazily when agents import themselves
_AGENT_CLASSES: dict[str, type] = {}


def register_agent_class(cls) -> None:
    """Called by each agent module to register itself."""
    _AGENT_CLASSES[cls.agent_id] = cls


def get_agent_class(agent_id: str):
    return _AGENT_CLASSES.get(agent_id)


def all_agent_classes() -> dict[str, type]:
    return dict(_AGENT_CLASSES)


def get_all_agents(db: Session) -> list[dict]:
    rows = db.query(Agent).order_by(Agent.agent_type).all()
    return [
        {
            "agent_id":        r.agent_id,
            "name":            r.name,
            "agent_type":      r.agent_type,
            "description":     r.description,
            "status":          r.status,
            "last_run_at":     r.last_run_at.isoformat() if r.last_run_at else None,
            "last_run_status": r.last_run_status,
            "last_run_summary": r.last_run_summary,
            "run_count":       r.run_count,
            "error_count":     r.error_count,
        }
        for r in rows
    ]


def get_agent(db: Session, agent_id: str) -> Optional[dict]:
    row = db.query(Agent).filter(Agent.agent_id == agent_id).first()
    if not row:
        return None
    pending_tasks = (
        db.query(AgentTask)
        .filter(AgentTask.agent_id == agent_id, AgentTask.status == "pending")
        .count()
    )
    recent_reports = (
        db.query(AgentReport)
        .filter(AgentReport.agent_id == agent_id)
        .order_by(AgentReport.created_at.desc())
        .limit(5)
        .all()
    )
    return {
        "agent_id":        row.agent_id,
        "name":            row.name,
        "agent_type":      row.agent_type,
        "description":     row.description,
        "status":          row.status,
        "last_run_at":     row.last_run_at.isoformat() if row.last_run_at else None,
        "last_run_status": row.last_run_status,
        "last_run_summary": row.last_run_summary,
        "run_count":       row.run_count,
        "error_count":     row.error_count,
        "pending_tasks":   pending_tasks,
        "recent_reports":  [
            {"id": r.id, "title": r.title, "urgency": r.urgency, "created_at": r.created_at.isoformat()}
            for r in recent_reports
        ],
    }


def health_summary(db: Session) -> dict:
    rows   = db.query(Agent).all()
    total  = len(rows)
    idle   = sum(1 for r in rows if r.status == "idle")
    running = sum(1 for r in rows if r.status == "running")
    errored = sum(1 for r in rows if r.status == "error")
    disabled = sum(1 for r in rows if r.status == "disabled")
    total_runs   = sum(r.run_count or 0 for r in rows)
    total_errors = sum(r.error_count or 0 for r in rows)
    error_rate   = round(total_errors / total_runs * 100, 1) if total_runs else 0.0

    return {
        "total":       total,
        "idle":        idle,
        "running":     running,
        "errored":     errored,
        "disabled":    disabled,
        "total_runs":  total_runs,
        "total_errors": total_errors,
        "error_rate_pct": error_rate,
    }


def ensure_all_registered(db: Session) -> int:
    """Register all known agent classes in DB if not already present."""
    # Import all agent modules so they self-register
    _import_all_agents()
    count = 0
    for agent_id, cls in _AGENT_CLASSES.items():
        existing = db.query(Agent).filter(Agent.agent_id == agent_id).first()
        if not existing:
            db.add(Agent(
                agent_id    = agent_id,
                name        = cls.name,
                agent_type  = cls.agent_type,
                description = cls.description,
                status      = "idle",
            ))
            count += 1
    db.commit()
    log.info("Registered %d new agents", count)
    return count


def _import_all_agents():
    """Trigger imports so each module calls register_agent_class()."""
    import importlib
    for mod in [
        "agents.market_research_agent",
        "agents.news_research_agent",
        "agents.strategy_research_agent",
        "agents.model_research_agent",
        "agents.risk_research_agent",
        "agents.pattern_research_agent",
        "agents.cro_agent",
        # Phase 9: Autonomous Research Division
        "agents.feature_discovery_agent",
        "agents.failure_scientist_agent",
        "agents.model_scientist_agent",
        "agents.data_quality_agent",
        "agents.macro_intelligence_agent",
        "agents.sector_intelligence_agent",
        "agents.alert_agent",
    ]:
        try:
            importlib.import_module(mod)
        except Exception as exc:
            log.warning("Could not import %s: %s", mod, exc)
