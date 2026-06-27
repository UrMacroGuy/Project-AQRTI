"""
Research Hypothesis Engine
Auto-generates hypotheses from feature decay, failures, and interaction data.
Runs experiments and promotes accepted findings to LessonLearned.
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
from aqrti.database.models import (
    ResearchHypothesis, ResearchExperiment, FeatureDecayHistory,
    FailureRecord, FeatureValue, DailyPrice, MarketRegime, LessonLearned,
)
from aqrti.utils.logger import get_logger

log = get_logger("hypothesis_engine")

MIN_IC_SIG = 0.05
MIN_PVALUE = 0.05
MIN_SAMPLE = 30


def _gen_id():
    return str(uuid.uuid4())[:16]


def _spearman_ic(x, y):
    from scipy.stats import spearmanr
    if len(x) < MIN_SAMPLE:
        return 0.0, 1.0
    corr, pval = spearmanr(x, y)
    return (float(corr) if not np.isnan(corr) else 0.0,
            float(pval) if not np.isnan(pval) else 1.0)


def generate_hypotheses_from_decay(db: Session) -> int:
    decaying = db.query(FeatureDecayHistory).filter(FeatureDecayHistory.decay_flag == True).limit(20).all()
    count = 0
    for fd in decaying:
        title = f"Does {fd.feature_name} still predict returns in current regime?"
        ex = db.query(ResearchHypothesis).filter(ResearchHypothesis.title == title).first()
        if ex:
            continue
        db.add(ResearchHypothesis(
            hypothesis_id=_gen_id(),
            title=title,
            description=f"Feature {fd.feature_name} shows IC={fd.ic_30d:.4f} (30d) vs IC={fd.ic_90d:.4f} (90d). "
                        f"Decay severity={fd.decay_severity}. Is the predictive signal still valid?",
            category="feature_decay",
            generated_by="auto:decay_detector",
            evidence_for_json=json.dumps({"feature": fd.feature_name, "ic_90d": fd.ic_90d}),
            status="pending",
            priority=2 if fd.decay_severity == "high" else 1,
        ))
        count += 1
    db.commit()
    log.info("Hypothesis: generated %d from decay", count)
    return count


def generate_hypotheses_from_failures(db: Session, days: int = 30) -> int:
    cutoff = date.today() - timedelta(days=days)
    failures = db.query(FailureRecord).filter(FailureRecord.failure_date >= cutoff).all()
    cat_regime: dict = {}
    for f in failures:
        key = (f.failure_category, f.regime_at)
        cat_regime[key] = cat_regime.get(key, 0) + 1
    count = 0
    for (cat, regime), freq in cat_regime.items():
        if freq < 3:
            continue
        title = f"Why does '{cat}' fail in {regime}?"
        ex = db.query(ResearchHypothesis).filter(ResearchHypothesis.title == title).first()
        if ex:
            continue
        db.add(ResearchHypothesis(
            hypothesis_id=_gen_id(),
            title=title,
            description=f"Failure category '{cat}' appeared {freq} times in regime {regime} in last {days} days. "
                        "Investigate whether regime-specific adjustments reduce failure rate.",
            category="failure_pattern",
            generated_by="auto:failure_analyzer",
            evidence_for_json=json.dumps({"regime": regime, "freq": freq}),
            status="pending",
            priority=1 + int(freq >= 5),
        ))
        count += 1
    db.commit()
    log.info("Hypothesis: generated %d from failures", count)
    return count


def _get_feature_name(hypothesis: ResearchHypothesis) -> Optional[str]:
    try:
        ev = json.loads(hypothesis.evidence_for_json or "{}")
        return ev.get("feature")
    except Exception:
        return None


def run_experiment(db: Session, hypothesis: ResearchHypothesis) -> dict:
    exp_id = _gen_id()
    log.info("Running experiment for hypothesis: %s", hypothesis.title)

    feature_name = _get_feature_name(hypothesis)
    if not feature_name:
        return {"status": "skipped", "reason": "no feature to test"}

    cutoff = date.today() - timedelta(days=365)
    fv_rows = db.query(FeatureValue.symbol, FeatureValue.date, FeatureValue.value).filter(
        FeatureValue.feature_name == feature_name, FeatureValue.date >= cutoff).all()
    if len(fv_rows) < MIN_SAMPLE:
        return {"status": "skipped", "reason": "insufficient feature data"}

    fv_map = {(r[0], r[1]): r[2] for r in fv_rows}
    price_rows = db.query(DailyPrice.symbol, DailyPrice.date, DailyPrice.close).filter(
        DailyPrice.date >= cutoff).order_by(DailyPrice.symbol, DailyPrice.date).all()
    sym_prices: dict = {}
    for sym, dt, cl in price_rows:
        sym_prices.setdefault(sym, []).append((dt, cl))
    fwd: dict = {}
    HORIZON = 5
    for sym, pl in sym_prices.items():
        pl.sort(key=lambda x: x[0])
        closes = [c for _, c in pl]
        dates  = [d for d, _ in pl]
        for i in range(len(dates) - HORIZON):
            p0, p1 = closes[i], closes[i + HORIZON]
            if p0 and p0 > 0:
                fwd[(sym, dates[i])] = (p1 - p0) / p0 * 100

    common = set(fv_map) & set(fwd)
    if len(common) < MIN_SAMPLE:
        return {"status": "skipped", "reason": "no fwd return alignment"}

    x = [fv_map[k] for k in common]
    y = [fwd[k] for k in common]
    ic, pval = _spearman_ic(x, y)

    regime_map = {r.date: r.regime for r in db.query(MarketRegime).all()}
    regime_ics: dict = {}
    rfv: dict = {}; rfr: dict = {}
    for k in common:
        reg = regime_map.get(k[1], "UNKNOWN")
        rfv.setdefault(reg, []).append(fv_map[k])
        rfr.setdefault(reg, []).append(fwd[k])
    for reg in rfv:
        if len(rfv[reg]) < MIN_SAMPLE: continue
        rc, rp = _spearman_ic(rfv[reg], rfr[reg])
        regime_ics[reg] = {"ic": rc, "pval": rp, "n": len(rfv[reg])}

    regimes_pass = sum(1 for ri in regime_ics.values() if abs(ri["ic"]) >= MIN_IC_SIG and ri["pval"] <= MIN_PVALUE)
    accepted = abs(ic) >= MIN_IC_SIG and pval <= MIN_PVALUE and regimes_pass >= 1

    verdict = "accepted" if accepted else "rejected"
    exp = ResearchExperiment(
        experiment_id=exp_id,
        hypothesis_id=hypothesis.hypothesis_id,
        name=f"IC validation: {feature_name}",
        design_json=json.dumps({"type": "ic_regime_split", "feature": feature_name}),
        result_json=json.dumps({"ic": ic, "ic_by_regime": regime_ics, "regimes_passing": regimes_pass}),
        p_value=pval,
        effect_size=ic,
        sample_size=len(common),
        status=verdict,
        conclusion=f"IC={ic:.4f} pval={pval:.4f} regimes_passing={regimes_pass}",
    )
    db.add(exp)

    if accepted:
        hypothesis.status = "accepted"
        hypothesis.result_summary = f"Feature {feature_name} IC={ic:.4f} is significant across {regimes_pass} regimes."
        title = f"Feature {feature_name} remains predictive (IC={ic:.4f})"
        if not db.query(LessonLearned).filter(LessonLearned.title == title).first():
            db.add(LessonLearned(
                lesson_date=date.today(), category="hypothesis",
                title=title,
                description=f"Experiment confirmed {feature_name} with IC={ic:.4f} (p={pval:.4f}) on {len(common)} samples.",
                what_happened=f"Ran IC validation on {feature_name}",
                why_it_happened="Hypothesis experiment auto-run by engine",
                what_worked=feature_name,
                what_failed="null hypothesis (no predictive power)",
                recommendation=f"Keep using {feature_name} in models",
                severity="low",
            ))
    else:
        hypothesis.status = "rejected"
        hypothesis.result_summary = f"Feature {feature_name} IC={ic:.4f} not significant (p={pval:.4f})."

    db.commit()
    return {"status": "ok", "accepted": accepted, "ic": ic, "pval": pval,
            "regimes_passing": regimes_pass, "n": len(common)}


def run_hypothesis_cycle(db: Session) -> dict:
    log.info("Hypothesis cycle starting")
    gen_d = generate_hypotheses_from_decay(db)
    gen_f = generate_hypotheses_from_failures(db)

    pending = db.query(ResearchHypothesis).filter(
        ResearchHypothesis.status == "pending",
        ResearchHypothesis.category == "feature_decay",
    ).order_by(ResearchHypothesis.priority.desc()).limit(5).all()

    results = []
    for h in pending:
        try:
            r = run_experiment(db, h)
            results.append({"hypothesis": h.title, **r})
        except Exception as exc:
            log.warning("Experiment failed for %s: %s", h.title, exc)
            results.append({"hypothesis": h.title, "status": "error", "error": str(exc)})

    return {"status": "ok", "hypotheses_generated": gen_d + gen_f,
            "experiments_run": len(results), "results": results}


def get_hypothesis_summary(db: Session) -> dict:
    total = db.query(ResearchHypothesis).count()
    by_status = {s: db.query(ResearchHypothesis).filter(ResearchHypothesis.status == s).count()
                 for s in ["pending", "accepted", "rejected", "archived"]}
    recent = db.query(ResearchHypothesis).order_by(ResearchHypothesis.id.desc()).limit(5).all()
    return {"total": total, "by_status": by_status,
            "recent": [{"title": h.title, "status": h.status, "category": h.category} for h in recent]}
