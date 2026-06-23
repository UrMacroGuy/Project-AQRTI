"""Research Findings API — /api/v1/research-findings"""

from __future__ import annotations

import sys, os

backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from aqrti.database.engine import get_db_dependency
from aqrti.database.models import ResearchFinding

router = APIRouter()


@router.get("")
def list_findings(
    days:     int        = Query(default=7, ge=1, le=90),
    agent_id: str | None = Query(default=None),
    category: str | None = Query(default=None),
    urgency:  str | None = Query(default=None),
    symbol:   str | None = Query(default=None),
    limit:    int        = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db_dependency),
):
    cutoff = date.today() - timedelta(days=days)
    q = db.query(ResearchFinding).filter(ResearchFinding.finding_date >= cutoff)
    if agent_id:
        q = q.filter(ResearchFinding.agent_id == agent_id)
    if category:
        q = q.filter(ResearchFinding.category == category)
    if urgency:
        q = q.filter(ResearchFinding.urgency == urgency)
    if symbol:
        q = q.filter(ResearchFinding.symbol == symbol)
    rows = q.order_by(ResearchFinding.finding_date.desc(), ResearchFinding.urgency).limit(limit).all()
    return {
        "findings": [_finding_to_dict(r) for r in rows],
        "total": len(rows),
    }


@router.get("/summary")
def findings_summary(
    days: int = Query(default=7, ge=1, le=90),
    db: Session = Depends(get_db_dependency),
):
    cutoff = date.today() - timedelta(days=days)
    rows   = db.query(ResearchFinding).filter(ResearchFinding.finding_date >= cutoff).all()
    by_urgency:  dict[str, int] = {}
    by_agent:    dict[str, int] = {}
    by_category: dict[str, int] = {}
    for r in rows:
        by_urgency[r.urgency]   = by_urgency.get(r.urgency, 0) + 1
        by_agent[r.agent_id]    = by_agent.get(r.agent_id, 0) + 1
        by_category[r.category] = by_category.get(r.category, 0) + 1

    critical = [_finding_to_dict(r) for r in rows if r.urgency == "critical"]
    high     = [_finding_to_dict(r) for r in rows if r.urgency == "high"]

    return {
        "total":       len(rows),
        "by_urgency":  by_urgency,
        "by_agent":    by_agent,
        "by_category": by_category,
        "critical":    critical[:5],
        "high":        high[:10],
    }


@router.patch("/{finding_id}/action")
def mark_actioned(finding_id: int, db: Session = Depends(get_db_dependency)):
    row = db.query(ResearchFinding).filter(ResearchFinding.id == finding_id).first()
    if not row:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Finding not found")
    row.actioned = True
    db.commit()
    return {"finding_id": finding_id, "actioned": True}


@router.get("/tasks/queue")
def task_queue_status(db: Session = Depends(get_db_dependency)):
    from agents.task_queue import queue_depth
    return queue_depth(db)


@router.get("/tasks/stats")
def task_stats(
    days: int = Query(default=7, ge=1, le=90),
    db: Session = Depends(get_db_dependency),
):
    from agents.research_tasks import get_task_stats
    return get_task_stats(db, days=days)


@router.get("/tasks/history")
def task_history(
    days:     int        = Query(default=7, ge=1, le=90),
    agent_id: str | None = Query(default=None),
    status:   str | None = Query(default=None),
    limit:    int        = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db_dependency),
):
    from agents.research_tasks import get_task_history
    return {"tasks": get_task_history(db, agent_id=agent_id, days=days, status=status, limit=limit)}


def _finding_to_dict(r: ResearchFinding) -> dict:
    import json
    try:
        meta = json.loads(r.metadata_json) if r.metadata_json else {}
    except Exception:
        meta = {}
    return {
        "id":          r.id,
        "date":        str(r.finding_date),
        "agent_id":    r.agent_id,
        "category":    r.category,
        "subcategory": r.subcategory,
        "title":       r.title,
        "description": r.description,
        "evidence":    r.evidence,
        "implication": r.implication,
        "urgency":     r.urgency,
        "symbol":      r.symbol,
        "regime":      r.regime,
        "actioned":    r.actioned,
        "metadata":    meta,
        "created_at":  r.created_at.isoformat() if r.created_at else None,
    }
