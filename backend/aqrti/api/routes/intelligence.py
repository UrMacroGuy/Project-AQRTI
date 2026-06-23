"""
AQRTI Historical Intelligence Lab API — Phase 8.5L
Routes: /api/v1/replay, /api/v1/meta-learning, /api/v1/model-memory,
        /api/v1/strategy-memory, /api/v1/feature-proposals, /api/v1/research-memory
"""

from __future__ import annotations

import json
import sys
import os
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text

from aqrti.database.engine import get_db_dependency
from aqrti.utils.logger import get_logger

logger = get_logger("intelligence_api")

# Ensure backend directory is on path for sibling package imports
_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

router = APIRouter()


# ── /api/v1/replay ─────────────────────────────────────────────────

class ReplayRequest(BaseModel):
    scope: str  # day|week|month|regime|event
    target_date: Optional[str] = None
    week_start: Optional[str] = None
    year: Optional[int] = None
    month: Optional[int] = None
    regime_name: Optional[str] = None
    event_date: Optional[str] = None
    days_before: int = 5
    days_after: int = 5


@router.post("/replay")
def trigger_replay(req: ReplayRequest):
    """Replay any historical period and return snapshot metadata."""
    try:
        from intelligence_training.historical_replay import (
            replay_day, replay_week, replay_month, replay_regime,
            replay_event_window, snapshot_to_dict,
        )
        scope = req.scope

        if scope == "day":
            d = date.fromisoformat(req.target_date)
            snap = replay_day(d)
            return {
                "scope": "day",
                "date": str(d),
                "symbols": len(snap.market_data),
                "news": len(snap.news_events),
                "predictions": len(snap.predictions_at_date),
                "regime": snap.regime,
                "knowledge_score": snap.knowledge_score_at_date,
            }
        elif scope == "week":
            ws = date.fromisoformat(req.week_start)
            snaps = replay_week(ws)
            return {
                "scope": "week", "week_start": str(ws),
                "days_replayed": len(snaps),
                "dates": [str(s.replay_date) for s in snaps],
            }
        elif scope == "month":
            snaps = replay_month(req.year, req.month)
            return {
                "scope": "month", "year": req.year, "month": req.month,
                "days_replayed": len(snaps),
            }
        elif scope == "regime":
            snaps = replay_regime(req.regime_name)
            return {
                "scope": "regime", "regime": req.regime_name,
                "days_replayed": len(snaps),
                "date_range": {
                    "start": str(snaps[0].replay_date) if snaps else None,
                    "end": str(snaps[-1].replay_date) if snaps else None,
                },
            }
        elif scope == "event":
            ed = date.fromisoformat(req.event_date)
            snaps = replay_event_window(ed, req.days_before, req.days_after)
            return {
                "scope": "event", "event_date": str(ed),
                "days_replayed": len(snaps),
            }
        else:
            raise HTTPException(400, f"Unknown scope: {scope}")
    except Exception as exc:
        raise HTTPException(500, str(exc))


@router.get("/replay/date-range")
def get_replay_date_range():
    """Return earliest and latest available dates for replay."""
    try:
        from intelligence_training.time_machine import get_time_machine
        tm = get_time_machine()
        start, end = tm.get_date_range()
        return {"start": str(start) if start else None, "end": str(end) if end else None}
    except Exception as exc:
        raise HTTPException(500, str(exc))


@router.get("/replay/regimes")
def get_available_regimes():
    """List all regimes with data available for replay."""
    try:
        from intelligence_training.time_machine import get_time_machine
        tm = get_time_machine()
        return {"regimes": tm.get_available_regimes()}
    except Exception as exc:
        raise HTTPException(500, str(exc))


@router.get("/replay/history")
def get_replay_history(db=Depends(get_db_dependency)):
    """List recent replay runs."""
    try:
        rows = db.execute(
            text("SELECT * FROM historical_replays ORDER BY created_at DESC LIMIT 50")
        ).fetchall()
        return [dict(r._mapping) for r in rows]
    except Exception as exc:
        raise HTTPException(500, str(exc))


# ── /api/v1/meta-learning ──────────────────────────────────────────

@router.get("/meta-learning")
def get_meta_learning_insights(
    severity: Optional[str] = Query(None),
    limit: int = Query(50),
    db=Depends(get_db_dependency),
):
    """Return all meta-learning insights about AQRTI's prediction behavior."""
    try:
        query = "SELECT * FROM meta_learning_records"
        params: Dict[str, Any] = {}
        if severity:
            query += " WHERE severity = :sev"
            params["sev"] = severity
        query += " ORDER BY created_at DESC LIMIT :limit"
        params["limit"] = limit
        rows = db.execute(text(query), params).fetchall()
        result = []
        for r in rows:
            d = dict(r._mapping)
            if "evidence_json" in d:
                try:
                    d["evidence"] = json.loads(d["evidence_json"] or "{}")
                except Exception:
                    d["evidence"] = {}
            result.append(d)
        return result
    except Exception as exc:
        raise HTTPException(500, str(exc))


@router.post("/meta-learning/run")
def run_meta_learning():
    """Manually trigger meta-learning analysis."""
    try:
        from intelligence_training.meta_learning_engine import run_meta_learning_analysis
        return run_meta_learning_analysis(days_back=365)
    except Exception as exc:
        raise HTTPException(500, str(exc))


@router.get("/meta-learning/summary")
def get_meta_learning_summary(db=Depends(get_db_dependency)):
    """Summary statistics of meta-learning insights."""
    try:
        rows = db.execute(
            text("SELECT severity, COUNT(*) as cnt FROM meta_learning_records GROUP BY severity")
        ).fetchall()
        return {"by_severity": {r.severity: r.cnt for r in rows}}
    except Exception as exc:
        raise HTTPException(500, str(exc))


# ── /api/v1/model-memory ───────────────────────────────────────────

@router.get("/model-memory")
def get_model_memory(db=Depends(get_db_dependency)):
    """Return model reliability scores and memory records."""
    try:
        from intelligence_training.model_memory import get_model_memory_records
        return get_model_memory_records(db)
    except Exception as exc:
        raise HTTPException(500, str(exc))


@router.post("/model-memory/update")
def update_model_memory():
    """Manually trigger model memory update."""
    try:
        from intelligence_training.model_memory import run_model_memory_pipeline
        return run_model_memory_pipeline()
    except Exception as exc:
        raise HTTPException(500, str(exc))


@router.get("/model-memory/{model_name}")
def get_model_memory_by_name(model_name: str, db=Depends(get_db_dependency)):
    """Return memory records for a specific model."""
    try:
        rows = db.execute(
            text("SELECT * FROM model_memory WHERE model_name = :m ORDER BY computed_at DESC LIMIT 30"),
            {"m": model_name},
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r._mapping)
            try:
                d["regime_scores"] = json.loads(d.get("regime_scores_json") or "{}")
            except Exception:
                d["regime_scores"] = {}
            result.append(d)
        return result
    except Exception as exc:
        raise HTTPException(500, str(exc))


# ── /api/v1/strategy-memory ────────────────────────────────────────

@router.get("/strategy-memory")
def get_strategy_memory(
    status: Optional[str] = Query(None),
    family: Optional[str] = Query(None),
    db=Depends(get_db_dependency),
):
    """Return strategy lifecycle memory records."""
    try:
        query = "SELECT * FROM strategy_memory WHERE 1=1"
        params: Dict[str, Any] = {}
        if status:
            query += " AND status = :status"
            params["status"] = status
        if family:
            query += " AND family = :family"
            params["family"] = family
        query += " ORDER BY computed_at DESC LIMIT 200"
        rows = db.execute(text(query), params).fetchall()
        result = []
        for r in rows:
            d = dict(r._mapping)
            for jcol in ("best_regimes_json", "worst_regimes_json", "lessons_json"):
                key = jcol.replace("_json", "")
                try:
                    d[key] = json.loads(d.get(jcol) or "[]")
                except Exception:
                    d[key] = []
            result.append(d)
        return result
    except Exception as exc:
        raise HTTPException(500, str(exc))


@router.get("/strategy-memory/summary")
def get_strategy_memory_summary(db=Depends(get_db_dependency)):
    """Summary of strategy survival and decay by family."""
    try:
        rows = db.execute(
            text("""
            SELECT family,
                   COUNT(*) as total,
                   SUM(CASE WHEN decay_detected=1 THEN 1 ELSE 0 END) as decayed,
                   AVG(survival_days) as avg_survival,
                   AVG(final_fitness) as avg_fitness
            FROM strategy_memory GROUP BY family ORDER BY avg_fitness DESC
            """)
        ).fetchall()
        return [dict(r._mapping) for r in rows]
    except Exception as exc:
        raise HTTPException(500, str(exc))


@router.post("/strategy-memory/update")
def update_strategy_memory():
    """Manually trigger strategy memory pipeline."""
    try:
        from intelligence_training.strategy_memory_training import run_strategy_memory_pipeline
        return run_strategy_memory_pipeline()
    except Exception as exc:
        raise HTTPException(500, str(exc))


# ── /api/v1/feature-proposals ─────────────────────────────────────

@router.get("/feature-proposals")
def get_feature_proposals(
    status: Optional[str] = Query(None),
    db=Depends(get_db_dependency),
):
    """Return all feature proposals."""
    try:
        from intelligence_training.feature_proposals import get_all_proposals
        return get_all_proposals(status=status, db=db)
    except Exception as exc:
        raise HTTPException(500, str(exc))


@router.get("/feature-proposals/summary")
def get_feature_proposals_summary(db=Depends(get_db_dependency)):
    """Summary of proposals by status."""
    try:
        from intelligence_training.feature_proposals import get_proposal_summary
        return get_proposal_summary(db=db)
    except Exception as exc:
        raise HTTPException(500, str(exc))


@router.post("/feature-proposals/{proposal_id}/approve")
def approve_feature_proposal(proposal_id: str, db=Depends(get_db_dependency)):
    """Human approves a feature proposal. Required before deployment."""
    try:
        from intelligence_training.feature_proposals import approve_proposal
        ok = approve_proposal(proposal_id, db=db)
        if not ok:
            raise HTTPException(404, f"Proposal {proposal_id} not found")
        return {"status": "approved", "proposal_id": proposal_id}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))


@router.post("/feature-proposals/{proposal_id}/reject")
def reject_feature_proposal(proposal_id: str, reason: str = Query(""), db=Depends(get_db_dependency)):
    """Human rejects a feature proposal."""
    try:
        from intelligence_training.feature_proposals import reject_proposal
        ok = reject_proposal(proposal_id, reason=reason, db=db)
        if not ok:
            raise HTTPException(404, f"Proposal {proposal_id} not found")
        return {"status": "rejected", "proposal_id": proposal_id}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))


@router.post("/feature-proposals/discover")
def run_feature_discovery():
    """Manually trigger feature discovery pipeline."""
    try:
        from intelligence_training.feature_discovery import run_feature_discovery_pipeline
        return run_feature_discovery_pipeline(days_back=180)
    except Exception as exc:
        raise HTTPException(500, str(exc))


@router.get("/feature-proposals/validations")
def get_feature_validations(db=Depends(get_db_dependency)):
    """Return all feature validation results."""
    try:
        from intelligence_training.feature_validator import get_all_validations
        return get_all_validations(db=db)
    except Exception as exc:
        raise HTTPException(500, str(exc))


# ── /api/v1/research-memory ────────────────────────────────────────

@router.get("/research-memory")
def get_research_memory(
    limit: int = Query(30),
    db=Depends(get_db_dependency),
):
    """Return research memory snapshots."""
    try:
        rows = db.execute(
            text("SELECT * FROM research_memory ORDER BY memory_date DESC LIMIT :limit"),
            {"limit": limit},
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r._mapping)
            for jcol in ("summary_json", "themes_json"):
                key = jcol.replace("_json", "")
                try:
                    d[key] = json.loads(d.get(jcol) or "{}")
                except Exception:
                    d[key] = {}
            result.append(d)
        return result
    except Exception as exc:
        raise HTTPException(500, str(exc))


@router.get("/research-memory/latest")
def get_latest_research_memory(db=Depends(get_db_dependency)):
    """Return the most recent research memory snapshot."""
    try:
        row = db.execute(
            text("SELECT * FROM research_memory ORDER BY memory_date DESC LIMIT 1")
        ).fetchone()
        if not row:
            return {"status": "no_data"}
        d = dict(row._mapping)
        for jcol in ("summary_json", "themes_json"):
            key = jcol.replace("_json", "")
            try:
                d[key] = json.loads(d.get(jcol) or "{}")
            except Exception:
                d[key] = {}
        return d
    except Exception as exc:
        raise HTTPException(500, str(exc))


@router.post("/research-memory/update")
def update_research_memory():
    """Manually trigger research memory pipeline."""
    try:
        from intelligence_training.research_learning import run_research_learning_pipeline
        return run_research_learning_pipeline()
    except Exception as exc:
        raise HTTPException(500, str(exc))


# ── /api/v1/regime-datasets ────────────────────────────────────────

@router.get("/regime-datasets")
def get_regime_datasets(db=Depends(get_db_dependency)):
    """Return all regime dataset metadata."""
    try:
        rows = db.execute(text("SELECT * FROM regime_datasets ORDER BY regime_label")).fetchall()
        result = []
        for r in rows:
            d = dict(r._mapping)
            try:
                d["definition"] = json.loads(d.get("definition_json") or "{}")
            except Exception:
                d["definition"] = {}
            try:
                d["symbols"] = json.loads(d.get("symbols_json") or "[]")
            except Exception:
                d["symbols"] = []
            result.append(d)
        return result
    except Exception as exc:
        raise HTTPException(500, str(exc))


@router.post("/regime-datasets/build")
def build_regime_datasets(horizon_days: int = Query(5)):
    """Manually trigger regime dataset build pipeline."""
    try:
        from intelligence_training.regime_dataset_builder import run_regime_dataset_pipeline
        return run_regime_dataset_pipeline(horizon_days=horizon_days)
    except Exception as exc:
        raise HTTPException(500, str(exc))


# ── /api/v1/intelligence-pipeline ─────────────────────────────────

@router.post("/intelligence-pipeline/run")
def run_intelligence_pipeline():
    """Manually trigger the full Historical Intelligence pipeline."""
    try:
        from intelligence_training.intelligence_pipeline import run_historical_intelligence_pipeline
        return run_historical_intelligence_pipeline()
    except Exception as exc:
        raise HTTPException(500, str(exc))


# ── /api/v1/failure-patterns ──────────────────────────────────────

@router.get("/failure-patterns")
def get_failure_patterns(db=Depends(get_db_dependency)):
    """Return identified recurring failure patterns."""
    try:
        rows = db.execute(
            text("SELECT * FROM failure_patterns ORDER BY occurrence_count DESC LIMIT 100")
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r._mapping)
            try:
                d["regimes"] = json.loads(d.get("regimes_json") or "[]")
            except Exception:
                d["regimes"] = []
            result.append(d)
        return result
    except Exception as exc:
        raise HTTPException(500, str(exc))


@router.get("/prediction-patterns")
def get_prediction_patterns(db=Depends(get_db_dependency)):
    """Return recurring success patterns."""
    try:
        rows = db.execute(
            text("SELECT * FROM prediction_patterns ORDER BY success_rate DESC LIMIT 100")
        ).fetchall()
        return [dict(r._mapping) for r in rows]
    except Exception as exc:
        raise HTTPException(500, str(exc))
