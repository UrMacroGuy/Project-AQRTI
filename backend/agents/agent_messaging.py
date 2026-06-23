"""
Agent Messaging
Inter-agent message bus — read, write, broadcast, and query messages.
"""

from __future__ import annotations

import sys, os, json
from datetime import datetime, timedelta, date

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from sqlalchemy.orm import Session
from aqrti.database.models import AgentMessage
from aqrti.utils.logger import get_logger

log = get_logger("agent_messaging")


def send_message(
    db:           Session,
    from_agent:   str,
    to_agent:     str,
    subject:      str,
    body:         str,
    message_type: str  = "finding",
    payload:      dict = None,
    priority:     int  = 5,
) -> AgentMessage:
    msg = AgentMessage(
        from_agent   = from_agent,
        to_agent     = to_agent,
        message_type = message_type,
        subject      = subject,
        body         = body,
        payload_json = json.dumps(payload or {}),
        priority     = priority,
    )
    db.add(msg)
    return msg


def get_inbox(
    db:       Session,
    agent_id: str,
    unread_only: bool = False,
    limit:    int = 50,
) -> list[dict]:
    q = db.query(AgentMessage).filter(
        (AgentMessage.to_agent == agent_id) | (AgentMessage.to_agent == "all")
    )
    if unread_only:
        q = q.filter(AgentMessage.read == False)
    rows = q.order_by(AgentMessage.priority, AgentMessage.created_at.desc()).limit(limit).all()
    return [_msg_to_dict(r) for r in rows]


def get_all_messages(
    db:           Session,
    days:         int        = 7,
    from_agent:   str | None = None,
    to_agent:     str | None = None,
    message_type: str | None = None,
    limit:        int        = 200,
) -> list[dict]:
    cutoff = datetime.utcnow() - timedelta(days=days)
    q = db.query(AgentMessage).filter(AgentMessage.created_at >= cutoff)
    if from_agent:
        q = q.filter(AgentMessage.from_agent == from_agent)
    if to_agent:
        q = q.filter(AgentMessage.to_agent == to_agent)
    if message_type:
        q = q.filter(AgentMessage.message_type == message_type)
    rows = q.order_by(AgentMessage.created_at.desc()).limit(limit).all()
    return [_msg_to_dict(r) for r in rows]


def mark_read(db: Session, message_id: int) -> None:
    msg = db.query(AgentMessage).filter(AgentMessage.id == message_id).first()
    if msg:
        msg.read = True


def mark_all_read(db: Session, agent_id: str) -> int:
    rows = db.query(AgentMessage).filter(
        (AgentMessage.to_agent == agent_id) | (AgentMessage.to_agent == "all"),
        AgentMessage.read == False,
    ).all()
    for r in rows:
        r.read = True
    return len(rows)


def get_unread_count(db: Session, agent_id: str) -> int:
    return db.query(AgentMessage).filter(
        (AgentMessage.to_agent == agent_id) | (AgentMessage.to_agent == "all"),
        AgentMessage.read == False,
    ).count()


def get_message_summary(db: Session, days: int = 7) -> dict:
    cutoff = datetime.utcnow() - timedelta(days=days)
    rows = db.query(AgentMessage).filter(AgentMessage.created_at >= cutoff).all()
    by_type: dict[str, int]      = {}
    by_from: dict[str, int]      = {}
    alerts: list[dict]           = []
    for r in rows:
        by_type[r.message_type] = by_type.get(r.message_type, 0) + 1
        by_from[r.from_agent]   = by_from.get(r.from_agent, 0) + 1
        if r.priority <= 2:
            alerts.append(_msg_to_dict(r))
    return {
        "total":    len(rows),
        "by_type":  by_type,
        "by_agent": by_from,
        "alerts":   alerts[:10],
    }


def _msg_to_dict(r: AgentMessage) -> dict:
    try:
        payload = json.loads(r.payload_json) if r.payload_json else {}
    except Exception:
        payload = {}
    return {
        "id":           r.id,
        "from_agent":   r.from_agent,
        "to_agent":     r.to_agent,
        "message_type": r.message_type,
        "subject":      r.subject,
        "body":         r.body,
        "payload":      payload,
        "priority":     r.priority,
        "read":         r.read,
        "created_at":   r.created_at.isoformat() if r.created_at else None,
    }
