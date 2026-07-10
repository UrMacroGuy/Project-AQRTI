"""
Feature Proposals Store — Phase 8.5G
Query, approve, and manage proposed features.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from aqrti.database.engine import get_session_factory
from aqrti.utils.logger import get_logger

logger = get_logger("feature_proposals")


def get_all_proposals(status: Optional[str] = None, db=None) -> List[Dict[str, Any]]:
    """Retrieve all feature proposals, optionally filtered by status."""
    own_session = db is None
    if own_session:
        db = get_session_factory()()
    try:
        query = "SELECT * FROM feature_proposals"
        params = {}
        if status:
            query += " WHERE status = :status"
            params["status"] = status
        query += " ORDER BY created_at DESC"
        rows = db.execute(text(query), params).fetchall()
        results = []
        for r in rows:
            d = dict(r._mapping)
            if "source_failures_json" in d:
                try:
                    d["source_failures"] = json.loads(d["source_failures_json"] or "[]")
                except Exception:
                    d["source_failures"] = []
            results.append(d)
        return results
    finally:
        if own_session:
            db.close()


def approve_proposal(proposal_id: str, db=None) -> bool:
    """Mark a feature proposal as approved (still needs implementation)."""
    own_session = db is None
    if own_session:
        db = get_session_factory()()
    try:
        result = db.execute(
            text("UPDATE feature_proposals SET status = 'approved', approved_at = :now WHERE proposal_id = :pid"),
            {"pid": proposal_id, "now": datetime.utcnow().isoformat()},
        )
        db.commit()
        if result.rowcount == 0:
            logger.warning("Feature proposal %s not found", proposal_id)
            return False
        logger.info("Feature proposal %s approved", proposal_id)
        return True
    except Exception as exc:
        logger.error("Failed to approve proposal %s: %s", proposal_id, exc)
        db.rollback()
        return False
    finally:
        if own_session:
            db.close()


def reject_proposal(proposal_id: str, reason: str = "", db=None) -> bool:
    """Mark a feature proposal as rejected."""
    own_session = db is None
    if own_session:
        db = get_session_factory()()
    try:
        result = db.execute(
            text("UPDATE feature_proposals SET status = 'rejected', rejection_reason = :reason WHERE proposal_id = :pid"),
            {"pid": proposal_id, "reason": reason},
        )
        db.commit()
        return result.rowcount > 0
    except Exception as exc:
        logger.error("Failed to reject proposal %s: %s", proposal_id, exc)
        db.rollback()
        return False
    finally:
        if own_session:
            db.close()


def get_proposal_summary(db=None) -> Dict[str, Any]:
    """Summary of all proposals by status."""
    own_session = db is None
    if own_session:
        db = get_session_factory()()
    try:
        rows = db.execute(
            text("SELECT status, COUNT(*) as cnt FROM feature_proposals GROUP BY status")
        ).fetchall()
        return {r.status: r.cnt for r in rows}
    finally:
        if own_session:
            db.close()
