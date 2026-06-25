"""
Task History
Stores and retrieves task outcomes, performance analytics, and findings.
"""

from __future__ import annotations

import sys, os, json
from datetime import datetime, timedelta
from typing import Optional

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from sqlalchemy.orm import Session
from aqrti.database.models import AgentTask, AgentReport
from aqrti.utils.logger import get_logger

log = get_logger("task_history")


def record_outcome(
    db:        Session,
    task_id:   str,
    outcome:   str,              # "success"|"failure"|"skipped"
    summary:   str   = "",
    findings:  list  = None,
    duration_secs: float = None,
) -> None:
    task = db.query(AgentTask).filter(AgentTask.task_id == task_id).first()
    if not task:
        log.warning("record_outcome: task_id %s not found", task_id)
        return
    output = {
        "outcome":        outcome,
        "summary":        summary,
        "finding_count":  len(findings or []),
        "duration_secs":  duration_secs,
    }
    task.status       = "completed" if outcome == "success" else "failed"
    task.output_json  = json.dumps(output)
    task.completed_at = datetime.utcnow()


def get_agent_performance(
    db:       Session,
    agent_id: Optional[str] = None,
    days:     int           = 30,
) -> list[dict]:
    cutoff = datetime.utcnow() - timedelta(days=days)
    q = db.query(AgentTask).filter(AgentTask.created_at >= cutoff)
    if agent_id:
        q = q.filter(AgentTask.agent_id == agent_id)
    rows = q.all()

    agent_stats: dict[str, dict] = {}
    for r in rows:
        if r.status == "cancelled":
            continue  # exclude cancelled (expired/stale) tasks from stats
        aid = r.agent_id
        if aid not in agent_stats:
            agent_stats[aid] = {
                "agent_id": aid, "total": 0, "completed": 0,
                "failed": 0, "times": []
            }
        agent_stats[aid]["total"] += 1
        if r.status == "completed":
            agent_stats[aid]["completed"] += 1
        elif r.status == "failed":
            agent_stats[aid]["failed"] += 1
        if r.started_at and r.completed_at:
            agent_stats[aid]["times"].append(
                (r.completed_at - r.started_at).total_seconds()
            )

    result = []
    for aid, s in agent_stats.items():
        avg_t = round(sum(s["times"]) / len(s["times"]), 1) if s["times"] else None
        result.append({
            "agent_id":     aid,
            "total_tasks":  s["total"],
            "completed":    s["completed"],
            "failed":       s["failed"],
            "success_rate": round(s["completed"] / s["total"] * 100, 1) if s["total"] else 0,
            "avg_duration_secs": avg_t,
        })
    return sorted(result, key=lambda x: x["total_tasks"], reverse=True)
