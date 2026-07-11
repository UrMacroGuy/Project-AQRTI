"""
Monthly Capital Allocator API — /api/v1/monthly-allocation (read-only)

Thin GET-only surface over portfolio/monthly_allocator.py. Suggests how the
month's ₹700 satellite budget could tilt across BEL/HDFCBANK/NTPC based on
live win-rate history, regime fit, and research synthesis strength.
Suggestion only — never a trade instruction (CLAUDE.md Personal Portfolio
rules).
"""

from __future__ import annotations

import sys
import os

backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from aqrti.database.engine import get_db_dependency
from portfolio.monthly_allocator import compute_monthly_allocation

router = APIRouter()


@router.get("")
def get_monthly_allocation(db: Session = Depends(get_db_dependency)):
    return compute_monthly_allocation(db)
