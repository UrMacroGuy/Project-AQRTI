"""
Paper-vs-Real Reconciliation API — /api/v1/reconciliation (read-only)

Thin GET-only surface over portfolio/paper_real_reconciliation.py. No write
endpoints — reconciliation is a comparison, not a mutation of either the
real portfolio (append-only, manually recorded) or paper trades.
"""

from __future__ import annotations

import sys
import os

backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from aqrti.database.engine import get_db_dependency
from portfolio.paper_real_reconciliation import reconcile

router = APIRouter()


@router.get("")
def get_reconciliation(
    lookback_days: int = Query(default=365, ge=1, le=1825),
    db: Session = Depends(get_db_dependency),
):
    """
    Compare real (manually recorded) portfolio transactions against the
    paper-trading engine's assumptions for the same symbol/date. Returns
    has_real_trades=False with an explicit note until the user records
    their first real transaction — never fabricates a comparison.
    """
    return reconcile(db, lookback_days=lookback_days)
