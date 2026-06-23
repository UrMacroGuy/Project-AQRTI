"""
Feature Validator — Phase 8.5G
Backtests proposed features to measure their predictive value before deployment.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from aqrti.database.engine import get_session_factory
from aqrti.utils.logger import get_logger

logger = get_logger("feature_validator")


def compute_information_coefficient(
    feature_values: pd.Series,
    forward_returns: pd.Series,
) -> float:
    """Compute Spearman rank IC between feature and forward returns."""
    try:
        from scipy.stats import spearmanr
        aligned = pd.DataFrame({"feat": feature_values, "ret": forward_returns}).dropna()
        if len(aligned) < 20:
            return 0.0
        ic, _ = spearmanr(aligned["feat"], aligned["ret"])
        return float(ic) if not np.isnan(ic) else 0.0
    except Exception:
        return 0.0


def validate_feature_proposal(
    proposal_id: str,
    feature_values_func,
    horizon_days: int = 5,
    db: Optional[Session] = None,
) -> Dict[str, Any]:
    """
    Validate a feature proposal by computing its IC over historical data.
    feature_values_func: callable(symbol, date) → float
    """
    own_session = db is None
    if own_session:
        db = get_session_factory()()
    try:
        cutoff = date.today() - timedelta(days=365)
        price_rows = db.execute(
            "SELECT symbol, date, close FROM daily_prices WHERE date >= :cutoff ORDER BY symbol, date",
            {"cutoff": cutoff},
        ).fetchall()

        if not price_rows:
            return {"status": "no_data", "ic": 0.0}

        df = pd.DataFrame([dict(r._mapping) for r in price_rows])
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values(["symbol", "date"])

        # Compute forward return for each row
        df["fwd_return"] = df.groupby("symbol")["close"].pct_change(horizon_days).shift(-horizon_days) * 100

        # Compute feature values
        feature_list = []
        for _, row in df.iterrows():
            try:
                fv = feature_values_func(row["symbol"], row["date"].date())
                feature_list.append(fv)
            except Exception:
                feature_list.append(np.nan)
        df["feature_value"] = feature_list

        # Compute IC
        ic = compute_information_coefficient(df["feature_value"].dropna(), df["fwd_return"])
        ic_by_regime = {}

        # IC by regime if available
        regime_rows = db.execute(
            "SELECT date, regime FROM market_regimes ORDER BY date"
        ).fetchall()
        if regime_rows:
            rdf = pd.DataFrame([dict(r._mapping) for r in regime_rows])
            rdf["date"] = pd.to_datetime(rdf["date"])
            merged = df.merge(rdf, on="date", how="left")
            for regime in merged["regime"].dropna().unique():
                rslice = merged[merged["regime"] == regime]
                r_ic = compute_information_coefficient(rslice["feature_value"], rslice["fwd_return"])
                ic_by_regime[regime] = round(r_ic, 4)

        # Save validation result
        try:
            db.execute(
                """
                INSERT INTO feature_validations
                    (proposal_id, ic_overall, ic_by_regime_json, horizon_days,
                     sample_count, validation_date, status, created_at)
                VALUES
                    (:pid, :ic, :ic_regime, :horizon, :cnt, :vdate, :status, :now)
                """,
                {
                    "pid": proposal_id, "ic": ic,
                    "ic_regime": json.dumps(ic_by_regime),
                    "horizon": horizon_days, "cnt": len(df.dropna(subset=["feature_value"])),
                    "vdate": date.today().isoformat(),
                    "status": "useful" if abs(ic) >= 0.03 else "weak",
                    "now": datetime.utcnow().isoformat(),
                },
            )
            db.commit()
        except Exception as exc:
            logger.warning("Could not save validation for %s: %s", proposal_id, exc)

        result = {
            "proposal_id": proposal_id,
            "ic_overall": round(ic, 4),
            "ic_by_regime": ic_by_regime,
            "horizon_days": horizon_days,
            "is_useful": abs(ic) >= 0.03,
            "ic_strength": "strong" if abs(ic) >= 0.05 else ("moderate" if abs(ic) >= 0.03 else "weak"),
        }
        logger.info("Feature validation %s: IC=%.4f", proposal_id, ic)
        return result
    finally:
        if own_session:
            db.close()


def get_all_validations(db=None) -> List[Dict[str, Any]]:
    """Retrieve all stored feature validations."""
    own_session = db is None
    if own_session:
        db = get_session_factory()()
    try:
        rows = db.execute("SELECT * FROM feature_validations ORDER BY created_at DESC").fetchall()
        result = []
        for r in rows:
            d = dict(r._mapping)
            if "ic_by_regime_json" in d:
                try:
                    d["ic_by_regime"] = json.loads(d["ic_by_regime_json"] or "{}")
                except Exception:
                    d["ic_by_regime"] = {}
            result.append(d)
        return result
    finally:
        if own_session:
            db.close()
