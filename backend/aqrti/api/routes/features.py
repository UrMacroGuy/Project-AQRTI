"""
AQRTI API — /api/v1/features
Feature Engineering endpoints.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session

from aqrti.database.engine import get_db_dependency
from aqrti.database.models import FeatureMetadata

router = APIRouter()


@router.get("/catalog")
def feature_catalog(db: Session = Depends(get_db_dependency)):
    """Return all feature definitions from the registry."""
    rows = db.query(FeatureMetadata).order_by(FeatureMetadata.category, FeatureMetadata.name).all()
    return [
        {
            "name":        r.name,
            "category":    r.category,
            "version":     r.version,
            "description": r.description,
            "formula":     r.formula,
            "min_periods": r.min_periods,
            "output_type": r.output_type,
        }
        for r in rows
    ]


@router.get("/latest")
def latest_features(
    symbol: str = Query(..., description="NSE symbol e.g. RELIANCE"),
    db: Session = Depends(get_db_dependency),
):
    """Return the most recent feature vector for a symbol."""
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
    from features.feature_store import get_latest_features
    features = get_latest_features(db, symbol.upper())
    if not features:
        raise HTTPException(404, detail=f"No features found for {symbol}")
    return {"symbol": symbol.upper(), "features": features}


@router.get("")
def get_features(
    symbol: str = Query(..., description="NSE symbol"),
    feature_date: Optional[date] = Query(None, description="YYYY-MM-DD, defaults to latest"),
    db: Session = Depends(get_db_dependency),
):
    """Return feature vector for a symbol on a specific date (or latest)."""
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
    from features.feature_store import get_features_on_date, get_latest_features

    sym = symbol.upper()
    if feature_date:
        features = get_features_on_date(db, sym, feature_date)
    else:
        features = get_latest_features(db, sym)

    if not features:
        raise HTTPException(404, detail=f"No features found for {sym}")

    return {
        "symbol":  sym,
        "date":    str(feature_date or "latest"),
        "features": features,
        "count":   len(features),
    }


@router.get("/history/{feature_name}")
def feature_history(
    feature_name: str,
    symbol: str = Query(...),
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db_dependency),
):
    """Return time-series for a single feature for a symbol."""
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
    from features.feature_store import get_feature_history

    series = get_feature_history(db, symbol.upper(), feature_name, days)
    return {
        "symbol":       symbol.upper(),
        "feature_name": feature_name,
        "days":         days,
        "data":         series,
    }
