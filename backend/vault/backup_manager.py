"""
AQRTI Vault — Backup Manager
Creates timestamped SQLite backup copies and manifest files.
"""

from __future__ import annotations

import sys, os

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import json
import shutil
from datetime import datetime, date

from sqlalchemy.orm import Session

from aqrti.database.models import (
    MarketSnapshot, PredictionArchive, PortfolioArchive,
    StrategyArchive, KnowledgeArchive, ResearchArchive,
)


def run_backup(db: Session, backup_dir: str | None = None) -> dict:
    if backup_dir is None:
        backup_dir = os.path.join(backend_dir, "data", "backups")
    os.makedirs(backup_dir, exist_ok=True)

    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")

    # Copy the SQLite database file
    db_path = _find_db_path()
    backup_path = None
    if db_path and os.path.exists(db_path):
        backup_filename = f"aqrti_vault_{timestamp}.db"
        backup_path = os.path.join(backup_dir, backup_filename)
        shutil.copy2(db_path, backup_path)
        backup_size = os.path.getsize(backup_path)
    else:
        backup_size = 0

    # Write manifest
    manifest = {
        "backup_timestamp": timestamp,
        "backup_path":      backup_path,
        "backup_size_bytes":backup_size,
        "vault_counts": {
            "market_snapshots":   db.query(MarketSnapshot).count(),
            "prediction_archive": db.query(PredictionArchive).count(),
            "portfolio_archive":  db.query(PortfolioArchive).count(),
            "strategy_archive":   db.query(StrategyArchive).count(),
            "knowledge_archive":  db.query(KnowledgeArchive).count(),
            "research_archive":   db.query(ResearchArchive).count(),
        },
    }
    manifest_path = os.path.join(backup_dir, f"manifest_{timestamp}.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    return {
        "status":        "ok",
        "timestamp":     timestamp,
        "backup_path":   backup_path,
        "manifest_path": manifest_path,
        "size_bytes":    backup_size,
        "vault_counts":  manifest["vault_counts"],
    }


def list_backups(backup_dir: str | None = None) -> list[dict]:
    if backup_dir is None:
        backup_dir = os.path.join(backend_dir, "data", "backups")
    if not os.path.exists(backup_dir):
        return []

    manifests = sorted(
        [f for f in os.listdir(backup_dir) if f.startswith("manifest_") and f.endswith(".json")],
        reverse=True,
    )
    results = []
    for m in manifests[:30]:
        path = os.path.join(backup_dir, m)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            results.append(data)
        except Exception:
            pass
    return results


def _find_db_path() -> str | None:
    candidates = [
        os.path.join(backend_dir, "data", "aqrti.db"),
        os.path.join(backend_dir, "aqrti.db"),
        os.path.join(backend_dir, "data", "db", "aqrti.db"),
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return None
