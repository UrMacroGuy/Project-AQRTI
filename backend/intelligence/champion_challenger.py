"""
Champion-Challenger Model Arena
Evaluates candidate models against the current champion.
Promotes challenger if acc_delta >= 0.02 AND auc_delta >= 0.01 AND eval_sample_count >= 30.
Supports rollback to previous champion.
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
from aqrti.database.models import P9Arena as ModelArena, P9ArenaEval as ArenaEvaluation, ModelRecord, Prediction, DailyPrice
from aqrti.utils.logger import get_logger

log = get_logger("champion_challenger")

ACC_DELTA_THRESHOLD  = 0.02
AUC_DELTA_THRESHOLD  = 0.01
MIN_EVAL_SAMPLES     = 30
EVAL_HORIZON_DAYS    = 30


def _gen_id():
    return str(uuid.uuid4())[:16]


def _roc_auc(y_true, y_score):
    from scipy.stats import mannwhitneyu
    pos = [s for s, t in zip(y_score, y_true) if t == 1]
    neg = [s for s, t in zip(y_score, y_true) if t == 0]
    if not pos or not neg:
        return 0.5
    stat, _ = mannwhitneyu(pos, neg, alternative="greater")
    return float(stat) / (len(pos) * len(neg))


def _eval_model(db: Session, model_id: str, cutoff: date) -> Optional[dict]:
    model = db.query(ModelRecord).filter(ModelRecord.model_id == model_id).first()
    if not model:
        return None
    preds = db.query(Prediction).filter(
        Prediction.model_version == model_id,
        Prediction.date >= cutoff,
    ).order_by(Prediction.date.asc()).all()
    if len(preds) < MIN_EVAL_SAMPLES:
        return None

    # Bulk-load all price data needed for evaluation — avoids N+1 queries
    symbols = list({p.symbol for p in preds})
    min_date = min(p.date for p in preds)
    price_rows = db.query(DailyPrice.symbol, DailyPrice.date, DailyPrice.close).filter(
        DailyPrice.symbol.in_(symbols), DailyPrice.date >= min_date
    ).order_by(DailyPrice.symbol, DailyPrice.date).all()
    # Build lookup: sym → sorted [(date, close), ...]
    sym_prices: dict = {}
    for sym, dt, cl in price_rows:
        sym_prices.setdefault(sym, []).append((dt, cl))

    def _get_close_on_or_after(sym, target_date):
        pl = sym_prices.get(sym, [])
        for dt, cl in pl:
            if dt >= target_date:
                return cl
        return None

    HORIZON = 5
    y_true, y_score = [], []
    for p in preds:
        sym, pred_date = p.symbol, p.date
        future = pred_date + timedelta(days=HORIZON)
        p0 = _get_close_on_or_after(sym, pred_date)
        p1 = _get_close_on_or_after(sym, future)
        if not p0 or not p1:
            continue
        actual = 1 if p1 > p0 else 0
        y_true.append(actual)
        conf = float(p.confidence or 50.0) / 100.0
        y_score.append(conf if p.direction == "Bullish" else 1.0 - conf)

    if len(y_true) < MIN_EVAL_SAMPLES:
        return None

    acc = float(np.mean([1 if (s >= 0.5) == t else 0 for s, t in zip(y_score, y_true)]))
    auc = _roc_auc(y_true, y_score)
    return {"acc": acc, "auc": auc, "n": len(y_true), "model_id": model_id}


def run_arena_evaluation(db: Session, arena_id: Optional[str] = None) -> dict:
    if arena_id:
        arenas = db.query(ModelArena).filter(ModelArena.arena_id == arena_id).all()
    else:
        arenas = db.query(ModelArena).filter(ModelArena.status == "active").all()
    if not arenas:
        return {"status": "no_active_arenas"}

    results = []
    cutoff = date.today() - timedelta(days=EVAL_HORIZON_DAYS)

    for arena in arenas:
        champ_stats = _eval_model(db, arena.champion_model_id, cutoff)
        if not champ_stats:
            results.append({"arena": arena.arena_id, "status": "champion_no_data"})
            continue

        challengers = json.loads(arena.challenger_model_ids_json or "[]")
        winner_id = arena.champion_model_id

        for chal_id in challengers:
            chal_stats = _eval_model(db, chal_id, cutoff)
            if not chal_stats:
                continue
            acc_delta = chal_stats["acc"] - champ_stats["acc"]
            auc_delta = chal_stats["auc"] - champ_stats["auc"]
            verdict = "challenger_wins" if (
                acc_delta >= ACC_DELTA_THRESHOLD and
                auc_delta >= AUC_DELTA_THRESHOLD and
                chal_stats["n"] >= MIN_EVAL_SAMPLES
            ) else "champion_holds"

            ev = ArenaEvaluation(
                eval_id=_gen_id(),
                arena_id=arena.arena_id,
                champion_model_id=arena.champion_model_id,
                challenger_model_id=chal_id,
                eval_date=date.today(),
                champion_accuracy=champ_stats["acc"],
                challenger_accuracy=chal_stats["acc"],
                acc_delta=acc_delta,
                champion_auc=champ_stats["auc"],
                challenger_auc=chal_stats["auc"],
                auc_delta=auc_delta,
                eval_sample_count=chal_stats["n"],
                verdict=verdict,
                promotion_reason=f"acc+{acc_delta:.4f} auc+{auc_delta:.4f} n={chal_stats['n']}" if verdict == "challenger_wins" else None,
                thresholds_json=json.dumps({
                    "acc_delta_threshold": ACC_DELTA_THRESHOLD,
                    "auc_delta_threshold": AUC_DELTA_THRESHOLD,
                    "min_samples": MIN_EVAL_SAMPLES,
                }),
            )
            db.add(ev)

            if verdict == "challenger_wins":
                log.info("PROMOTION: %s replaces %s (acc+%.4f, auc+%.4f)",
                         chal_id, arena.champion_model_id, acc_delta, auc_delta)
                arena.previous_champion_id = arena.champion_model_id
                arena.champion_model_id = chal_id
                winner_id = chal_id
                champ_stats = chal_stats  # New champion for next comparisons
                results.append({
                    "arena": arena.arena_id, "verdict": "promoted",
                    "new_champion": chal_id, "acc_delta": acc_delta, "auc_delta": auc_delta,
                })
            else:
                results.append({
                    "arena": arena.arena_id, "verdict": "no_change",
                    "champion": arena.champion_model_id, "acc_delta": acc_delta,
                })

        arena.last_evaluated = date.today()
    db.commit()
    return {"status": "ok", "arenas_evaluated": len(arenas), "results": results}


def rollback_champion(db: Session, arena_id: str) -> dict:
    arena = db.query(ModelArena).filter(ModelArena.arena_id == arena_id).first()
    if not arena:
        return {"status": "error", "reason": "arena not found"}
    if not arena.previous_champion_id:
        return {"status": "error", "reason": "no previous champion to roll back to"}
    prev = arena.previous_champion_id
    arena.previous_champion_id = arena.champion_model_id
    arena.champion_model_id = prev
    db.commit()
    log.info("ROLLBACK: arena %s reverted to %s", arena_id, prev)
    return {"status": "ok", "arena_id": arena_id, "restored_champion": prev}


def register_arena(db: Session, name: str, champion_id: str, challenger_ids: list) -> dict:
    arena_id = _gen_id()
    db.add(ModelArena(
        arena_id=arena_id, name=name,
        champion_model_id=champion_id,
        challenger_model_ids_json=json.dumps(challenger_ids),
        status="active",
    ))
    db.commit()
    return {"status": "ok", "arena_id": arena_id}


def get_arena_status(db: Session) -> list:
    arenas = db.query(ModelArena).all()
    out = []
    for a in arenas:
        latest = db.query(ArenaEvaluation).filter(
            ArenaEvaluation.arena_id == a.arena_id
        ).order_by(ArenaEvaluation.eval_date.desc()).first()
        out.append({
            "arena_id": a.arena_id, "name": a.name,
            "champion": a.champion_model_id,
            "challengers": json.loads(a.challenger_model_ids_json or "[]"),
            "status": a.status,
            "last_evaluated": str(a.last_evaluated) if a.last_evaluated else None,
            "last_verdict": latest.verdict if latest else None,
            "last_acc_delta": latest.acc_delta if latest else None,
        })
    return out
