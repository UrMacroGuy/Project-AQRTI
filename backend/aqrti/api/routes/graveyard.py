"""Strategy Graveyard API — /api/v1/graveyard"""

from __future__ import annotations

import sys, os

backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from aqrti.database.engine import get_db_dependency
from strategies.graveyard_manager import (
    get_graveyard, get_resurrection_candidates, failure_pattern_analysis,
)
from strategies.strategy_registry import get_graveyard_summary

router = APIRouter()


@router.get("")
def list_graveyard(
    family:         str | None = Query(default=None),
    failure_reason: str | None = Query(default=None),
    limit:          int        = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db_dependency),
):
    rows = get_graveyard(db, family=family, failure_reason=failure_reason, limit=limit)
    return {"graveyard": rows, "total": len(rows)}


@router.get("/summary")
def graveyard_summary(db: Session = Depends(get_db_dependency)):
    return get_graveyard_summary(db)


@router.get("/failure-patterns")
def failure_patterns(db: Session = Depends(get_db_dependency)):
    return failure_pattern_analysis(db)


@router.get("/resurrection-candidates")
def resurrection_candidates(db: Session = Depends(get_db_dependency)):
    candidates = get_resurrection_candidates(db)
    return {"candidates": candidates, "total": len(candidates)}
