"""
Research Task System (7I)
Manages task creation, assignment, completion, and outcome tracking.
"""

from __future__ import annotations

import sys, os, json, uuid
from datetime import date, datetime, timedelta
from typing import Optional

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from sqlalchemy.orm import Session
from aqrti.database.models import AgentTask, Agent
from aqrti.utils.logger import get_logger

log = get_logger("research_tasks")


def create_task(
    db:          Session,
    agent_id:    str,
    title:       str,
    task_type:   str   = "daily_run",
    assigned_by: str   = "scheduler",
    priority:    int   = 5,
    description: str   = "",
    input_data:  dict  = None,
    due_date:    Optional[date] = None,
) -> AgentTask:
    task = AgentTask(
        task_id     = f"task_{agent_id}_{uuid.uuid4().hex[:8]}",
        agent_id    = agent_id,
        assigned_by = assigned_by,
        task_type   = task_type,
        title       = title,
        description = description,
        priority    = priority,
        status      = "pending",
        input_json  = json.dumps(input_data or {}),
        due_date    = due_date or date.today(),
    )
    db.add(task)
    db.flush()
    return task


def complete_task(db: Session, task_id: str, output: dict, success: bool = True) -> None:
    task = db.query(AgentTask).filter(AgentTask.task_id == task_id).first()
    if task:
        task.status       = "completed" if success else "failed"
        task.output_json  = json.dumps(output)
        task.completed_at = datetime.utcnow()
        if not success:
            task.error_message = output.get("error", "Unknown error")


def cancel_task(db: Session, task_id: str, reason: str = "") -> bool:
    task = db.query(AgentTask).filter(AgentTask.task_id == task_id).first()
    if not task or task.status not in ("pending",):
        return False
    task.status        = "cancelled"
    task.error_message = reason
    return True


def get_pending_tasks(db: Session, agent_id: Optional[str] = None, limit: int = 50) -> list[dict]:
    q = db.query(AgentTask).filter(AgentTask.status == "pending")
    if agent_id:
        q = q.filter(AgentTask.agent_id == agent_id)
    rows = q.order_by(AgentTask.priority, AgentTask.created_at).limit(limit).all()
    return [_task_to_dict(r) for r in rows]


def get_task_history(
    db:          Session,
    agent_id:    Optional[str] = None,
    days:        int           = 7,
    status:      Optional[str] = None,
    limit:       int           = 100,
) -> list[dict]:
    cutoff = datetime.utcnow() - timedelta(days=days)
    q = db.query(AgentTask).filter(AgentTask.created_at >= cutoff)
    if agent_id:
        q = q.filter(AgentTask.agent_id == agent_id)
    if status:
        q = q.filter(AgentTask.status == status)
    rows = q.order_by(AgentTask.created_at.desc()).limit(limit).all()
    return [_task_to_dict(r) for r in rows]


def get_task_stats(db: Session, days: int = 7) -> dict:
    cutoff = datetime.utcnow() - timedelta(days=days)
    rows = db.query(AgentTask).filter(AgentTask.created_at >= cutoff).all()
    by_status: dict[str, int] = {}
    by_agent:  dict[str, int] = {}
    completion_times = []

    for r in rows:
        by_status[r.status]   = by_status.get(r.status, 0) + 1
        by_agent[r.agent_id]  = by_agent.get(r.agent_id, 0) + 1
        if r.completed_at and r.started_at:
            secs = (r.completed_at - r.started_at).total_seconds()
            completion_times.append(secs)

    avg_completion = round(sum(completion_times) / len(completion_times), 1) if completion_times else None
    completed = by_status.get("completed", 0)
    failed    = by_status.get("failed", 0)
    total     = len(rows)

    return {
        "total":          total,
        "by_status":      by_status,
        "by_agent":       by_agent,
        "success_rate":   round(completed / total * 100, 1) if total else 0.0,
        "avg_completion_secs": avg_completion,
    }


def _task_to_dict(r: AgentTask) -> dict:
    try:
        output = json.loads(r.output_json) if r.output_json else None
    except Exception:
        output = None
    return {
        "task_id":     r.task_id,
        "agent_id":    r.agent_id,
        "assigned_by": r.assigned_by,
        "task_type":   r.task_type,
        "title":       r.title,
        "description": r.description,
        "priority":    r.priority,
        "status":      r.status,
        "due_date":    str(r.due_date) if r.due_date else None,
        "started_at":  r.started_at.isoformat() if r.started_at else None,
        "completed_at": r.completed_at.isoformat() if r.completed_at else None,
        "error_message": r.error_message,
        "created_at":  r.created_at.isoformat() if r.created_at else None,
        "output":      output,
    }
