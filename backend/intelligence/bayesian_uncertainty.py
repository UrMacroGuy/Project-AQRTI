"""
Bayesian Uncertainty Estimator
5-component uncertainty: epistemic, aleatoric, regime_familiarity,
feature_stability, historical_calibration.
Output: "82% ± 11%" style confidence with components explained.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Optional
import sys, os

import numpy as np

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from sqlalchemy.orm import Session
from aqrti.database.models import (
    P9Uncertainty as UncertaintyEstimate, Prediction, FeatureDecayHistory,
    DailyRegimeAssignment, DiscoveredRegime, MarketRegime,
)
from aqrti.utils.logger import get_logger

log = get_logger("bayesian_uncertainty")

# Component weights (must sum to 1.0)
W_EPISTEMIC   = 0.25
W_ALEATORIC   = 0.20
W_REGIME_FAM  = 0.20
W_FEAT_STAB   = 0.20
W_HIST_CALIB  = 0.15


def _epistemic_uncertainty(db: Session, model_id: str, days: int = 30) -> float:
    """Uncertainty from model disagreement / ensemble spread."""
    cutoff = date.today() - timedelta(days=days)
    preds = db.query(Prediction.confidence).filter(
        Prediction.model_version == model_id, Prediction.date >= cutoff
    ).all()
    if len(preds) < 10:
        return 0.20  # default high uncertainty when little data
    probs = np.array([(p[0] or 50.0) / 100.0 for p in preds], dtype=float)
    # Epistemic uncertainty = spread of predictions (std dev)
    spread = float(np.std(probs))
    # Normalize: std of 0.5 is maximum uncertainty
    return min(1.0, spread / 0.5)


def _aleatoric_uncertainty(db: Session, symbol: Optional[str] = None, days: int = 60) -> float:
    """Irreducible noise: market volatility of the underlying."""
    from aqrti.database.models import DailyPrice, IndexData
    cutoff = date.today() - timedelta(days=days)
    if symbol:
        rows = db.query(DailyPrice.close).filter(
            DailyPrice.symbol == symbol, DailyPrice.date >= cutoff
        ).order_by(DailyPrice.date.asc()).all()
        closes_raw = [r[0] for r in rows if r[0]]
    else:
        # Use NIFTY index as market proxy — much smaller than full price table
        rows = db.query(IndexData.close).filter(
            IndexData.index_name == "^NSEI", IndexData.date >= cutoff
        ).order_by(IndexData.date.asc()).all()
        closes_raw = [r[0] for r in rows if r[0]]
    if len(closes_raw) < 10:
        return 0.15
    closes = np.array(closes_raw, dtype=float)
    if len(closes) < 2:
        return 0.15
    log_rets = np.diff(np.log(np.where(closes > 0, closes, 1e-8)))
    vol_ann = float(np.std(log_rets) * np.sqrt(252))
    return min(1.0, vol_ann / 0.5)


def _regime_familiarity(db: Session) -> float:
    """How well the current regime matches training history."""
    today_assignment = db.query(DailyRegimeAssignment).order_by(
        DailyRegimeAssignment.date.desc()).first()
    if not today_assignment:
        return 0.5  # unknown → 50% uncertainty

    regime_id = today_assignment.regime_id
    regime = db.query(DiscoveredRegime).filter(DiscoveredRegime.regime_id == regime_id).first()
    if not regime:
        return 0.5

    total_days = db.query(DailyRegimeAssignment).count()
    regime_days = db.query(DailyRegimeAssignment).filter(
        DailyRegimeAssignment.regime_id == regime_id).count()
    if total_days == 0:
        return 0.5

    coverage = regime_days / total_days
    confidence = float(today_assignment.confidence or 0.5)
    familiarity = (coverage * 0.5 + confidence * 0.5)
    # High familiarity → low uncertainty
    return 1.0 - familiarity


def _feature_stability(db: Session) -> float:
    """Fraction of features showing decay."""
    total = db.query(FeatureDecayHistory).count()
    if total == 0:
        return 0.10
    decaying = db.query(FeatureDecayHistory).filter(FeatureDecayHistory.decay_flag == True).count()
    frac = decaying / total
    return min(1.0, frac * 2)  # Scale: 50% decaying → 100% uncertain


def _historical_calibration(db: Session, model_id: str, days: int = 90) -> float:
    """Calibration gap: how far confidence deviates from actual accuracy."""
    cutoff = date.today() - timedelta(days=days)
    preds = db.query(Prediction).filter(
        Prediction.model_version == model_id, Prediction.date >= cutoff
    ).all()
    correct = total = 0
    conf_vals = []
    for p in preds:
        if p.success is None:
            continue
        conf = float(p.confidence or 50.0) / 100.0
        conf_vals.append(conf)
        correct += 1 if p.success else 0
        total += 1
    if total < 10:
        return 0.20
    actual_acc = correct / total
    avg_conf = float(np.mean(conf_vals)) if conf_vals else 0.5
    gap = abs(avg_conf - actual_acc)
    return min(1.0, gap * 2)


def estimate_uncertainty(db: Session, model_id: str,
                         symbol: Optional[str] = None,
                         base_confidence: float = 0.70) -> dict:
    ep  = _epistemic_uncertainty(db, model_id)
    al  = _aleatoric_uncertainty(db, symbol)
    rf  = _regime_familiarity(db)
    fs  = _feature_stability(db)
    hc  = _historical_calibration(db, model_id)

    composite_uncertainty = (
        ep  * W_EPISTEMIC  +
        al  * W_ALEATORIC  +
        rf  * W_REGIME_FAM +
        fs  * W_FEAT_STAB  +
        hc  * W_HIST_CALIB
    )
    confidence_pct = round((1.0 - composite_uncertainty) * base_confidence * 100, 1)
    uncertainty_pct = round(composite_uncertainty * 100 / 2, 1)  # ±uncertainty
    confidence_pct = max(0.0, min(99.9, confidence_pct))
    uncertainty_pct = max(0.1, min(49.9, uncertainty_pct))

    breakdown = {
        "epistemic":            {"value": round(ep, 4),  "weight": W_EPISTEMIC,  "contribution": round(ep * W_EPISTEMIC, 4)},
        "aleatoric":            {"value": round(al, 4),  "weight": W_ALEATORIC,  "contribution": round(al * W_ALEATORIC, 4)},
        "regime_familiarity":   {"value": round(rf, 4),  "weight": W_REGIME_FAM, "contribution": round(rf * W_REGIME_FAM, 4)},
        "feature_stability":    {"value": round(fs, 4),  "weight": W_FEAT_STAB,  "contribution": round(fs * W_FEAT_STAB, 4)},
        "historical_calibration":{"value": round(hc, 4), "weight": W_HIST_CALIB, "contribution": round(hc * W_HIST_CALIB, 4)},
    }

    label = f"{confidence_pct}% ± {uncertainty_pct}%"
    explanation = (
        f"Epistemic ({ep:.2f}) captures model spread. "
        f"Aleatoric ({al:.2f}) captures market noise. "
        f"Regime familiarity ({rf:.2f}) reflects how well-trained we are in this regime. "
        f"Feature stability ({fs:.2f}) reflects decay rate. "
        f"Historical calibration ({hc:.2f}) measures prediction accuracy gap."
    )

    row = UncertaintyEstimate(
        model_id=model_id, symbol=symbol, estimate_date=date.today(),
        base_confidence=base_confidence,
        epistemic_uncertainty=ep, aleatoric_uncertainty=al,
        regime_familiarity=rf, feature_stability=fs, historical_calibration=hc,
        composite_uncertainty=composite_uncertainty,
        final_confidence=confidence_pct / 100,
        confidence_label=label,
        breakdown_json=json.dumps(breakdown),
        explanation=explanation,
    )
    db.add(row)
    db.commit()

    log.info("Uncertainty: %s → %s", model_id, label)
    return {
        "model_id": model_id, "symbol": symbol,
        "confidence": confidence_pct, "uncertainty_range": uncertainty_pct,
        "label": label, "composite_uncertainty": round(composite_uncertainty, 4),
        "breakdown": breakdown, "explanation": explanation,
    }


def uncertainty_quality_score(db: Session, days: int = 30) -> float:
    """Aggregate calibration quality — used by knowledge_score.py"""
    cutoff = date.today() - timedelta(days=days)
    rows = db.query(UncertaintyEstimate).filter(UncertaintyEstimate.estimate_date >= cutoff).all()
    if not rows:
        return 0.0
    avg_uncertainty = float(np.mean([r.composite_uncertainty for r in rows]))
    # Lower composite uncertainty → higher quality score (inverted)
    return round(max(0.0, 1.0 - avg_uncertainty), 4)


def get_latest_estimate(db: Session, model_id: str) -> Optional[dict]:
    row = db.query(UncertaintyEstimate).filter(
        UncertaintyEstimate.model_id == model_id
    ).order_by(UncertaintyEstimate.estimate_date.desc()).first()
    if not row:
        return None
    return {
        "model_id": row.model_id, "symbol": row.symbol,
        "estimate_date": str(row.estimate_date),
        "label": row.confidence_label,
        "confidence": row.final_confidence,
        "composite_uncertainty": row.composite_uncertainty,
        "breakdown": json.loads(row.breakdown_json or "{}"),
        "explanation": row.explanation,
    }
