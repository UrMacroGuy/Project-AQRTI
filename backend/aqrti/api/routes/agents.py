"""Agents API — /api/v1/agents"""

from __future__ import annotations

import sys, os

backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session

from aqrti.database.engine import get_db_dependency
from aqrti.database.models import AgentReport, AgentMessage
from agents.agent_registry import get_all_agents, get_agent, health_summary, ensure_all_registered
from agents.agent_scheduler import run_agent, run_daily_pipeline
from agents.agent_messaging import get_all_messages, get_message_summary, mark_read
from agents.research_tasks import get_task_stats
from agents.task_history import get_agent_performance

router = APIRouter()


@router.get("")
def list_agents(db: Session = Depends(get_db_dependency)):
    return {
        "agents":  get_all_agents(db),
        "health":  health_summary(db),
    }


@router.get("/health")
def agents_health(db: Session = Depends(get_db_dependency)):
    return health_summary(db)


@router.get("/{agent_id}")
def get_agent_detail(agent_id: str, db: Session = Depends(get_db_dependency)):
    detail = get_agent(db, agent_id)
    if not detail:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
    return detail


@router.post("/{agent_id}/run")
def run_single_agent(agent_id: str, db: Session = Depends(get_db_dependency)):
    """Manually trigger a single agent."""
    try:
        result = run_agent(db, agent_id)
        return {"agent_id": agent_id, "status": "ok", "findings": len(result.get("findings", [])), "summary": result.get("summary", "")}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/admin/run-pipeline")
def run_pipeline(db: Session = Depends(get_db_dependency)):
    """Manually trigger the full daily agent pipeline."""
    return run_daily_pipeline(db)


@router.post("/admin/register-all")
def register_all(db: Session = Depends(get_db_dependency)):
    count = ensure_all_registered(db)
    return {"registered": count}


@router.get("/{agent_id}/reports")
def get_agent_reports(
    agent_id: str,
    days:  int = Query(default=30, ge=1, le=365),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db_dependency),
):
    import json
    from datetime import date, timedelta
    cutoff = date.today() - timedelta(days=days)
    rows = (
        db.query(AgentReport)
        .filter(AgentReport.agent_id == agent_id, AgentReport.report_date >= cutoff)
        .order_by(AgentReport.created_at.desc())
        .limit(limit)
        .all()
    )
    return {
        "reports": [
            {
                "id":          r.id,
                "date":        str(r.report_date),
                "title":       r.title,
                "summary":     r.summary,
                "urgency":     r.urgency,
                "findings":    _safe_json(r.findings_json),
                "recommendations": _safe_json(r.recommendations_json),
                "created_at":  r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
    }


@router.get("/messages/all")
def list_messages(
    days:  int = Query(default=7, ge=1, le=30),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db_dependency),
):
    return {"messages": get_all_messages(db, days=days, limit=limit)}


@router.get("/messages/summary")
def messages_summary(
    days: int = Query(default=7, ge=1, le=30),
    db: Session = Depends(get_db_dependency),
):
    return get_message_summary(db, days=days)


@router.patch("/messages/{message_id}/read")
def mark_message_read(message_id: int, db: Session = Depends(get_db_dependency)):
    mark_read(db, message_id)
    db.commit()
    return {"message_id": message_id, "read": True}


@router.get("/performance/stats")
def performance_stats(
    days: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(get_db_dependency),
):
    return get_agent_performance(db, days=days)


def _safe_json(s):
    import json
    try:
        return json.loads(s) if s else []
    except Exception:
        return []
