"""
Automatic Feature Discovery Engine
Generates candidate features via interactions and lags, validates with IC, persists results.
"""

from __future__ import annotations

import json, uuid
from datetime import date, timedelta
from typing import Optional
import sys, os

import numpy as np

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from sqlalchemy.orm import Session
from aqrti.database.models import FeatureValue, DailyPrice, MarketRegime, FeatureCandidate
from aqrti.utils.logger import get_logger

log = get_logger("feature_discovery")

IC_ACCEPT_THRESHOLD  = 0.05
IC_REJECT_FLOOR      = 0.01
IC_REGIME_MIN        = 2
MIN_SAMPLES          = 50
MAX_CANDIDATES       = 30

INTERACTION_PAIRS = [
    ("return_5d", "volume_ratio_20d"), ("rsi_14", "breadth_pct"),
    ("momentum_10d", "realized_vol_20d"), ("return_5d", "sentiment_score"),
    ("volume_ratio_20d", "sentiment_score"), ("rsi_14", "volume_ratio_20d"),
]
LAG_FEATURES = ["rsi_14", "momentum_10d", "return_5d"]
LAG_DAYS     = [3, 5, 10]


def _feat_series(db, name, days=365):
    cutoff = date.today() - timedelta(days=days)
    rows = db.query(FeatureValue.symbol, FeatureValue.date, FeatureValue.value).filter(
        FeatureValue.feature_name == name, FeatureValue.date >= cutoff).all()
    return {(r[0], r[1]): r[2] for r in rows}


def _fwd_returns(db, horizon=5, days=365):
    cutoff = date.today() - timedelta(days=days + horizon * 2)
    rows = db.query(DailyPrice.symbol, DailyPrice.date, DailyPrice.close).filter(
        DailyPrice.date >= cutoff).order_by(DailyPrice.symbol, DailyPrice.date).all()
    sym_prices: dict = {}
    for sym, dt, cl in rows:
        sym_prices.setdefault(sym, []).append((dt, cl))
    fwd = {}
    for sym, pl in sym_prices.items():
        pl.sort(key=lambda x: x[0])
        closes = [c for _, c in pl]
        dates  = [d for d, _ in pl]
        n = len(dates)
        for i in range(n - horizon):
            p0 = closes[i]
            p1 = closes[i + horizon]
            if p0 and p0 > 0:
                fwd[(sym, dates[i])] = (p1 - p0) / p0 * 100
    return fwd


def _ic(feature_vals, fwd):
    common = set(feature_vals) & set(fwd)
    if len(common) < MIN_SAMPLES: return 0.0
    x = [feature_vals[k] for k in common]
    y = [fwd[k] for k in common]
    if np.std(x) < 1e-8 or np.std(y) < 1e-8: return 0.0
    try:
        from scipy.stats import spearmanr
        corr, _ = spearmanr(x, y)
        return float(corr) if not np.isnan(corr) else 0.0
    except Exception:
        return 0.0


def _ic_by_regime(db, feature_vals, fwd):
    regime_map = {r.date: r.regime for r in db.query(MarketRegime).all()}
    rfv: dict = {}; rfr: dict = {}
    for (sym, dt), val in feature_vals.items():
        reg = regime_map.get(dt, "UNKNOWN")
        rfv.setdefault(reg, {})[(sym, dt)] = val
    for (sym, dt), ret in fwd.items():
        reg = regime_map.get(dt, "UNKNOWN")
        rfr.setdefault(reg, {})[(sym, dt)] = ret
    return {reg: round(_ic(rfv[reg], rfr.get(reg, {})), 4) for reg in rfv if reg in rfr}


def run_feature_discovery(db: Session) -> dict:
    log.info("Starting feature discovery")
    fwd = _fwd_returns(db)
    if len(fwd) < MIN_SAMPLES:
        return {"status": "insufficient_data", "fwd_samples": len(fwd)}

    candidates = []
    # Interaction candidates
    for fa, fb in INTERACTION_PAIRS:
        sa, sb = _feat_series(db, fa), _feat_series(db, fb)
        if not sa or not sb: continue
        for op, op_name in [("product", "×"), ("ratio", "÷"), ("diff", "−")]:
            combined = {}
            for k in set(sa) & set(sb):
                a, b = sa[k], sb[k]
                if a is None or b is None: continue
                if op == "product": combined[k] = a * b
                elif op == "ratio": combined[k] = a / b if abs(b) > 1e-8 else None
                else: combined[k] = a - b
            combined = {k: v for k, v in combined.items() if v is not None}
            if len(combined) < MIN_SAMPLES: continue
            candidates.append({"name": f"{fa}_{op}_{fb}", "formula": f"{fa} {op_name} {fb}",
                               "category": "interaction", "source": "combination",
                               "parent_features_json": json.dumps([fa, fb]),
                               "hypothesis": f"Interaction of {fa} and {fb} via {op}",
                               "ic_score": _ic(combined, fwd), "sample_count": len(combined),
                               "_fv": combined})

    # Lag candidates
    for feat_name in LAG_FEATURES:
        series = _feat_series(db, feat_name)
        if not series: continue
        sym_dates: dict = {}
        for sym, dt in series:
            sym_dates.setdefault(sym, []).append(dt)
        for sym in sym_dates: sym_dates[sym].sort()
        for lag in LAG_DAYS:
            lagged = {}
            for sym, dts in sym_dates.items():
                for i, dt in enumerate(dts):
                    if i < lag: continue
                    pd_ = dts[i - lag]
                    if (sym, pd_) in series: lagged[(sym, dt)] = series[(sym, pd_)]
            if len(lagged) < MIN_SAMPLES: continue
            candidates.append({"name": f"{feat_name}_lag{lag}d", "formula": f"{feat_name}[t-{lag}d]",
                               "category": "temporal", "source": "temporal",
                               "parent_features_json": json.dumps([feat_name]),
                               "hypothesis": f"{lag}-day lagged {feat_name}",
                               "ic_score": _ic(lagged, fwd), "sample_count": len(lagged),
                               "_fv": lagged})

    created = approved = rejected = 0
    for c in candidates[:MAX_CANDIDATES]:
        fv = c.pop("_fv", {})
        if db.query(FeatureCandidate).filter(FeatureCandidate.name == c["name"]).first():
            continue
        ic_regime = _ic_by_regime(db, fv, fwd)
        c["ic_by_regime_json"] = json.dumps(ic_regime)
        c["candidate_id"] = str(uuid.uuid4())[:12]
        passing = sum(1 for ic in ic_regime.values() if abs(ic) >= IC_ACCEPT_THRESHOLD)
        if abs(c["ic_score"]) >= IC_ACCEPT_THRESHOLD and passing >= IC_REGIME_MIN:
            c["validation_status"] = "approved"
            c["validation_details_json"] = json.dumps({"ic": c["ic_score"], "regimes_passing": passing})
            approved += 1
            log.info("APPROVED: %s (IC=%.3f)", c["name"], c["ic_score"])
        elif abs(c["ic_score"]) < IC_REJECT_FLOOR:
            c["validation_status"] = "rejected"
            c["rejection_reason"] = f"IC={c['ic_score']:.4f} below floor"
            rejected += 1
        else:
            c["validation_status"] = "pending"
        db.add(FeatureCandidate(**{k: v for k, v in c.items() if not k.startswith("_")}))
        created += 1
    db.commit()
    log.info("Feature discovery: created=%d approved=%d rejected=%d", created, approved, rejected)
    return {"status": "ok", "candidates_created": created, "approved": approved, "rejected": rejected}


def get_approved_features(db: Session) -> list:
    rows = db.query(FeatureCandidate).filter(FeatureCandidate.validation_status == "approved").order_by(FeatureCandidate.ic_score.desc()).all()
    return [{"candidate_id": r.candidate_id, "name": r.name, "formula": r.formula,
             "ic_score": r.ic_score, "sample_count": r.sample_count} for r in rows]


def get_candidate_pipeline(db: Session) -> dict:
    total = db.query(FeatureCandidate).count()
    by_status = {s: db.query(FeatureCandidate).filter(FeatureCandidate.validation_status == s).count()
                 for s in ["pending", "approved", "rejected", "archived"]}
    top = db.query(FeatureCandidate).filter(FeatureCandidate.validation_status == "approved").order_by(FeatureCandidate.ic_score.desc()).limit(5).all()
    return {"total": total, "by_status": by_status,
            "top_features": [{"name": r.name, "ic_score": r.ic_score} for r in top]}
