"""Backups API — /api/v1/backups"""

from __future__ import annotations

import sys, os

backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from aqrti.database.engine import get_db_dependency

router = APIRouter()


@router.get("")
def list_backups():
    from vault.backup_manager import list_backups as _list
    return {"backups": _list()}


@router.post("/run")
def run_backup(db: Session = Depends(get_db_dependency)):
    from vault.backup_manager import run_backup as _backup
    return _backup(db)
