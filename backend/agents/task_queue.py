"""
Task Queue
In-order task execution from the pending queue.
Executes pending tasks for a given agent (or all agents).
"""

from __future__ import annotations

import sys, os, json
from datetime import datetime

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from sqlalchemy.orm import Session
from aqrti.database.models import AgentTask
from aqrti.utils.logger import get_logger

log = get_logger("task_queue")


def drain_queue(db: Session, agent_id: str = None, limit: int = 10) -> dict:
    """
    Execute all pending tasks (optionally for a specific agent).
    Returns summary of results.
    """
    q = db.query(AgentTask).filter(AgentTask.status == "pending")
    if agent_id:
        q = q.filter(AgentTask.agent_id == agent_id)
    tasks = q.order_by(AgentTask.priority, AgentTask.created_at).limit(limit).all()

    if not tasks:
        return {"drained": 0, "results": []}

    from agents.agent_scheduler import run_agent
    results = []
    for task in tasks:
        task.status     = "running"
        task.started_at = datetime.utcnow()
        db.commit()
        try:
            findings = run_agent(db, task.agent_id, task_id=task.task_id)
            task.status       = "completed"
            task.output_json  = json.dumps({"findings": len(findings.get("findings", []))})
            task.completed_at = datetime.utcnow()
            results.append({"task_id": task.task_id, "status": "completed"})
        except Exception as exc:
            task.status        = "failed"
            task.error_message = str(exc)
            task.completed_at  = datetime.utcnow()
            results.append({"task_id": task.task_id, "status": "failed", "error": str(exc)})
            log.error("Task %s failed: %s", task.task_id, exc)
        db.commit()

    return {"drained": len(results), "results": results}


def queue_depth(db: Session) -> dict:
    """Return pending task counts per agent."""
    tasks = db.query(AgentTask).filter(AgentTask.status == "pending").all()
    by_agent: dict[str, int] = {}
    for t in tasks:
        by_agent[t.agent_id] = by_agent.get(t.agent_id, 0) + 1
    return {"total_pending": len(tasks), "by_agent": by_agent}
