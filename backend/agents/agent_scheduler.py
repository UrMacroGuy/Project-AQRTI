"""
Agent Scheduler
Manages the ordered execution of agents in the daily research pipeline.

Pipeline order (Step 9 in the main scheduler):
  1. Market Research Agent
  2. News Research Agent
  3. Pattern Research Agent
  4. Model Research Agent
  5. Strategy Research Agent
  6. Risk Research Agent
  7. CRO Agent (aggregates all above + generates Daily Brief)

Each agent runs sequentially so later agents can read earlier agents' findings.
"""

from __future__ import annotations

import sys, os, uuid
from datetime import datetime, date
from typing import Optional

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from sqlalchemy.orm import Session
from aqrti.database.models import AgentTask
from aqrti.utils.logger import get_logger

log = get_logger("agent_scheduler")

PIPELINE_ORDER = [
    "market_research",
    "news_research",
    "pattern_research",
    "model_research",
    "strategy_research",
    "risk_research",
    "cro",
    # Phase 9: Autonomous Research Division
    "feature_discovery",
    "failure_scientist",
    "model_scientist",
    "data_quality",
    "macro_intelligence",
    "sector_intelligence",
    "alert",
]


def create_task(
    db:          Session,
    agent_id:    str,
    title:       str,
    task_type:   str   = "daily_run",
    assigned_by: str   = "scheduler",
    priority:    int   = 5,
    description: str   = "",
    input_data:  dict  = None,
) -> AgentTask:
    import json
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
        due_date    = date.today(),
    )
    db.add(task)
    db.flush()
    return task


def _get_agent_instance(agent_id: str):
    from agents.agent_registry import _import_all_agents, _AGENT_CLASSES
    _import_all_agents()
    cls = _AGENT_CLASSES.get(agent_id)
    if not cls:
        raise ValueError(f"Unknown agent: {agent_id}")
    return cls()


def run_agent(db: Session, agent_id: str, task_id: Optional[str] = None) -> dict:
    """Run a single agent by ID. Returns findings dict."""
    agent = _get_agent_instance(agent_id)
    log.info("Running agent: %s", agent_id)
    return agent.execute(db, task_id=task_id)


def run_daily_pipeline(db: Session) -> dict:
    """
    Execute the full daily agent pipeline in order.
    Each agent runs sequentially; failures don't abort subsequent agents.
    """
    log.info("=== DAILY AGENT PIPELINE START ===")
    results = {}
    tasks   = {}

    for agent_id in PIPELINE_ORDER:
        try:
            # Ensure the agent row exists in DB before creating a task that FKs to it
            agent_instance = _get_agent_instance(agent_id)
            agent_instance.ensure_registered(db)
            db.flush()

            task = create_task(
                db,
                agent_id    = agent_id,
                title       = f"Daily run — {agent_id} — {date.today()}",
                task_type   = "daily_run",
                assigned_by = "scheduler",
                priority    = 3,
            )
            task.started_at = datetime.utcnow()
            db.commit()
            tasks[agent_id] = task.task_id

            findings = agent_instance.execute(db, task_id=task.task_id)
            results[agent_id] = {
                "status":   "ok" if "_error" not in findings else "error",
                "task_id":  task.task_id,
                "findings": len(findings.get("findings", [])),
                "summary":  findings.get("summary", ""),
                "error":    findings.get("_error"),
            }
            _complete_task(db, task.task_id, findings)
            log.info("Agent %s: %d findings", agent_id, len(findings.get("findings", [])))
        except Exception as exc:
            log.error("Agent %s pipeline error: %s", agent_id, exc)
            results[agent_id] = {"status": "error", "error": str(exc)}

    # Process follow-up tasks queued by CRO (e.g. "Follow-up: Strategy Decay: ...")
    followup_result = run_followup_tasks(db)
    log.info("=== DAILY AGENT PIPELINE COMPLETE === follow_ups_run=%d", followup_result["follow_ups_run"])
    return {"date": str(date.today()), "agents": results, "follow_ups_run": followup_result["follow_ups_run"]}


def run_followup_tasks(db: Session) -> dict:
    """
    Execute any pending follow_up tasks created by CRO (or other agents).
    Called at end of daily pipeline so they don't accumulate as zombies.
    """
    pending = (
        db.query(AgentTask)
        .filter(AgentTask.task_type == "follow_up", AgentTask.status == "pending")
        .order_by(AgentTask.priority.asc(), AgentTask.created_at.asc())
        .limit(10)  # cap per cycle to avoid runaway
        .all()
    )
    if not pending:
        return {"follow_ups_run": 0}

    log.info("Running %d pending follow-up tasks", len(pending))
    ran = 0
    for task in pending:
        try:
            agent_instance = _get_agent_instance(task.agent_id)
            task.status     = "running"
            task.started_at = datetime.utcnow()
            db.commit()
            findings = agent_instance.execute(db, task_id=task.task_id)
            _complete_task(db, task.task_id, findings)
            ran += 1
            log.info("Follow-up task %s (%s) completed", task.task_id, task.agent_id)
        except Exception as exc:
            log.error("Follow-up task %s failed: %s", task.task_id, exc)
            task.status        = "failed"
            task.error_message = str(exc)
            task.completed_at  = datetime.utcnow()
            db.commit()
    return {"follow_ups_run": ran}


def _complete_task(db: Session, task_id: str, output: dict) -> None:
    import json
    task = db.query(AgentTask).filter(AgentTask.task_id == task_id).first()
    if task:
        task.status       = "completed" if "_error" not in output else "failed"
        task.output_json  = json.dumps(output)
        task.completed_at = datetime.utcnow()
        if "_error" in output:
            task.error_message = output["_error"]
