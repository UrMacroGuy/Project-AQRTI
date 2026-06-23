"""Portfolio / Paper Trading API — /api/v1/portfolio"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from aqrti.database.engine import get_db_dependency
from aqrti.data.portfolio import get_portfolio_summary, get_equity_curve, get_open_positions

router = APIRouter()


@router.get("")
def get_portfolio(db: Session = Depends(get_db_dependency)):
    return get_portfolio_summary(db)


@router.get("/equity-curve")
def get_equity_curve_route(
    days: int = Query(default=30, ge=7, le=365),
    db: Session = Depends(get_db_dependency),
):
    return get_equity_curve(db, days)


@router.get("/positions")
def get_positions(db: Session = Depends(get_db_dependency)):
    return get_open_positions(db)
