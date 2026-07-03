"""
AQRTI Feature Store
Reads and writes computed feature values to/from the feature_values table.
All writes are upserts (merge on symbol+date+feature_name+version).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

import pandas as pd
from sqlalchemy.orm import Session
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from aqrti.database.models import FeatureValue
from aqrti.utils.logger import get_logger

log = get_logger("feature_store")


# ══════════════════════════════════════════════════════════════
# WRITE
# ══════════════════════════════════════════════════════════════
def save_feature_vector(
    db: Session,
    symbol: str,
    feature_date: date,
    features: dict[str, Optional[float]],
    version: int = 1,
    commit: bool = True,
) -> int:
    """
    Upsert a full feature vector for one (symbol, date).
    Single bulk INSERT ... ON CONFLICT DO UPDATE — was previously one SELECT
    + one INSERT/UPDATE per feature (~30 round-trips per call); over a full
    backfill (352 symbols x ~1236 dates x ~30 features) that was ~13M
    individual SELECTs and was the dominant cost, far exceeding the actual
    feature computation. Same upsert semantics (skip None values, update
    value + computed_at on conflict), same return contract (count written).

    commit=False lets the caller batch many calls into one transaction
    (e.g. one commit per date across all symbols) instead of one commit per
    (symbol, date) pair — cuts commit count by ~30-350x in the full backfill.
    """
    now = datetime.utcnow()
    rows = [
        {
            "symbol":       symbol,
            "date":         feature_date,
            "feature_name": name,
            "value":        value,
            "version":      version,
            "computed_at":  now,
        }
        for name, value in features.items()
        if value is not None
    ]
    if not rows:
        return 0

    stmt = sqlite_insert(FeatureValue).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["symbol", "date", "feature_name", "version"],
        set_={"value": stmt.excluded.value, "computed_at": stmt.excluded.computed_at},
    )
    db.execute(stmt)
    if commit:
        db.commit()
    return len(rows)


# ══════════════════════════════════════════════════════════════
# READ — latest vector for a symbol
# ══════════════════════════════════════════════════════════════
def get_latest_features(
    db: Session,
    symbol: str,
    version: int = 1,
) -> dict[str, float]:
    """Return the most recent feature vector for a symbol as {name: value}."""
    latest_date = (
        db.query(FeatureValue.date)
        .filter_by(symbol=symbol, version=version)
        .order_by(FeatureValue.date.desc())
        .first()
    )
    if not latest_date:
        return {}

    rows = (
        db.query(FeatureValue)
        .filter_by(symbol=symbol, date=latest_date[0], version=version)
        .all()
    )
    return {r.feature_name: r.value for r in rows}


# ══════════════════════════════════════════════════════════════
# READ — feature vector for a specific date
# ══════════════════════════════════════════════════════════════
def get_features_on_date(
    db: Session,
    symbol: str,
    feature_date: date,
    version: int = 1,
) -> dict[str, float]:
    rows = (
        db.query(FeatureValue)
        .filter_by(symbol=symbol, date=feature_date, version=version)
        .all()
    )
    return {r.feature_name: r.value for r in rows}


# ══════════════════════════════════════════════════════════════
# READ — time-series for a single feature
# ══════════════════════════════════════════════════════════════
def get_feature_history(
    db: Session,
    symbol: str,
    feature_name: str,
    days: int = 30,
    version: int = 1,
) -> list[dict]:
    from datetime import timedelta
    cutoff = date.today() - timedelta(days=days)
    rows = (
        db.query(FeatureValue)
        .filter(
            FeatureValue.symbol       == symbol,
            FeatureValue.feature_name == feature_name,
            FeatureValue.version      == version,
            FeatureValue.date         >= cutoff,
        )
        .order_by(FeatureValue.date.asc())
        .all()
    )
    return [{"date": str(r.date), "value": r.value} for r in rows]


# ══════════════════════════════════════════════════════════════
# READ — feature matrix (all symbols × all features for one date)
# ══════════════════════════════════════════════════════════════
def get_feature_matrix(
    db: Session,
    symbols: list[str],
    feature_date: date,
    version: int = 1,
) -> pd.DataFrame:
    """
    Returns a DataFrame: rows=symbols, columns=feature_names.
    Used by model training pipeline.
    """
    rows = (
        db.query(FeatureValue)
        .filter(
            FeatureValue.symbol.in_(symbols),
            FeatureValue.date    == feature_date,
            FeatureValue.version == version,
        )
        .all()
    )
    if not rows:
        return pd.DataFrame()

    records = [
        {"symbol": r.symbol, "feature": r.feature_name, "value": r.value}
        for r in rows
    ]
    df = pd.DataFrame(records).pivot(index="symbol", columns="feature", values="value")
    df.columns.name = None
    return df


# ══════════════════════════════════════════════════════════════
# READ — last computed date per symbol (for incremental updates)
# ══════════════════════════════════════════════════════════════
def get_last_computed_date(
    db: Session,
    symbol: str,
    version: int = 1,
) -> Optional[date]:
    row = (
        db.query(FeatureValue.date)
        .filter_by(symbol=symbol, version=version)
        .order_by(FeatureValue.date.desc())
        .first()
    )
    return row[0] if row else None
