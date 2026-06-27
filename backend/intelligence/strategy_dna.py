"""
Strategy DNA & Genealogy Engine
Computes genetic fingerprint for every strategy. DNA similarity drives breeding.
"""

from __future__ import annotations

import json, hashlib
from collections import defaultdict
from datetime import date
from typing import Optional
import sys, os

import numpy as np

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from sqlalchemy.orm import Session
from aqrti.database.models import (
    StrategyV2, StrategyEvolutionHistory, StrategyBacktestTrade, StrategyDNA, Stock, MarketRegime,
)
from aqrti.utils.logger import get_logger

log = get_logger("strategy_dna")

SIMILARITY_THRESHOLD = 0.70


def _extract_indicators(dsl: dict) -> list:
    indicators = []
    for cond in (dsl.get("entry_conditions") or {}).get("conditions") or []:
        if isinstance(cond, dict) and cond.get("feature"):
            indicators.append(cond["feature"])
    return sorted(set(indicators))


def _holding_range(days):
    if not days: return "medium"
    return "short" if days <= 5 else ("long" if days > 15 else "medium")


def _stop_band(pct):
    if not pct: return "normal"
    a = abs(pct)
    return "tight" if a < 4 else ("wide" if a > 8 else "normal")


def _dna_hash(indicators, holding, regimes, stop, family):
    parts = sorted(indicators) + [holding, stop, family] + sorted(regimes)
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


def _jaccard(a: set, b: set) -> float:
    if not a and not b: return 1.0
    inter = len(a & b); union = len(a | b)
    return inter / union if union > 0 else 0.0


def compute_dna(strategy: StrategyV2, db: Session) -> dict:
    try:
        dsl = json.loads(strategy.dsl_json or "{}")
    except Exception:
        dsl = {}
    indicators = _extract_indicators(dsl)
    holding    = _holding_range(dsl.get("max_holding_days"))
    regimes    = sorted(dsl.get("allowed_regimes") or ["BULL", "BEAR", "SIDEWAYS"])
    stop       = _stop_band(dsl.get("stop_loss_pct"))
    family     = strategy.family or "hybrid"
    dna_hash   = _dna_hash(indicators, holding, regimes, stop, family)

    mutations  = db.query(StrategyEvolutionHistory.operation, StrategyEvolutionHistory.fitness_delta).filter(
        StrategyEvolutionHistory.child_strategy_id == strategy.strategy_id).all()
    mutation_list = [{"op": m[0], "delta": m[1]} for m in mutations]
    parent_ids    = json.loads(strategy.parent_ids or "[]") if strategy.parent_ids else []

    sector_wins: dict = defaultdict(list)
    trades = db.query(StrategyBacktestTrade).filter(StrategyBacktestTrade.strategy_id == strategy.strategy_id).all()
    sym_sector = {s.symbol: s.sector for s in db.query(Stock).all()}

    # Build regime map for trade dates
    regime_map = {r.date: r.regime for r in db.query(MarketRegime).all()}

    regime_pnl: dict = defaultdict(list)
    for t in trades:
        sec = sym_sector.get(t.symbol, "Unknown")
        sector_wins[sec].append(1 if (t.pnl_pct or 0) > 0 else 0)
        reg = regime_map.get(t.entry_date, "UNKNOWN")
        if t.pnl_pct is not None:
            regime_pnl[reg].append(t.pnl_pct)

    sector_pref = {s: round(sum(w) / len(w), 3) for s, w in sector_wins.items() if len(w) >= 3}

    # preferred_regime = best avg pnl; worst_regime = worst avg pnl
    regime_avg = {r: float(np.mean(v)) for r, v in regime_pnl.items() if len(v) >= 3}
    preferred_regime = max(regime_avg, key=regime_avg.get) if regime_avg else (regimes[0] if regimes else None)
    worst_regime = min(regime_avg, key=regime_avg.get) if regime_avg else None

    returns  = [t.pnl_pct for t in trades if t.pnl_pct is not None]
    avg_vol  = float(np.std(returns)) if len(returns) > 1 else None
    neg_rets = [r for r in returns if r < 0]
    avg_dd   = float(np.mean(neg_rets)) if neg_rets else None

    return {
        "strategy_id": strategy.strategy_id, "family": family,
        "dominant_features_json": json.dumps(indicators[:10]),
        "indicator_set_json": json.dumps(indicators),
        "avg_holding_days": dsl.get("max_holding_days"),
        "avg_volatility_at_entry": avg_vol, "avg_drawdown": avg_dd,
        "preferred_regime": preferred_regime,
        "worst_regime": worst_regime,
        "avg_confidence": dsl.get("min_confidence"),
        "sector_preference_json": json.dumps(sector_pref),
        "generation": strategy.generation or 0,
        "mutation_history_json": json.dumps(mutation_list),
        "parent_ids_json": json.dumps(parent_ids),
        "dna_hash": dna_hash,
    }


def sync_strategy_dna(db: Session, limit: int = 200) -> dict:
    strategies = (
        db.query(StrategyV2)
        .filter(StrategyV2.status.in_(["promoted", "active", "shadow"]))
        .order_by(StrategyV2.fitness_score.desc())
        .limit(limit).all()
    )
    created = updated = 0
    for s in strategies:
        try:
            data = compute_dna(s, db)
        except Exception as exc:
            log.warning("DNA failed for %s: %s", s.strategy_id, exc)
            continue
        ex = db.query(StrategyDNA).filter(StrategyDNA.strategy_id == s.strategy_id).first()
        if ex:
            if ex.dna_hash != data["dna_hash"]:
                for k, v in data.items():
                    if k == "strategy_id":
                        continue
                    if v is None and getattr(ex, k, None) is not None:
                        continue  # never overwrite an existing value with None
                    setattr(ex, k, v)
                updated += 1
        else:
            db.add(StrategyDNA(**data))
            created += 1
    db.commit()
    log.info("DNA sync: created=%d updated=%d", created, updated)
    return {"status": "ok", "created": created, "updated": updated}


def find_similar_strategies(db: Session, strategy_id: str, top_n: int = 10) -> list:
    target = db.query(StrategyDNA).filter(StrategyDNA.strategy_id == strategy_id).first()
    if not target:
        return []
    ti = set(json.loads(target.indicator_set_json or "[]"))
    all_dna = db.query(StrategyDNA).filter(StrategyDNA.strategy_id != strategy_id).all()
    scored = []
    for d in all_dna:
        oi  = set(json.loads(d.indicator_set_json or "[]"))
        sim = _jaccard(ti, oi)
        if d.family == target.family: sim = min(1.0, sim + 0.1)
        scored.append({"strategy_id": d.strategy_id, "similarity": round(sim, 3), "family": d.family})
    return sorted(scored, key=lambda x: x["similarity"], reverse=True)[:top_n]


def get_dna_profile(db: Session, strategy_id: str) -> Optional[dict]:
    d = db.query(StrategyDNA).filter(StrategyDNA.strategy_id == strategy_id).first()
    if not d: return None
    return {
        "strategy_id": d.strategy_id, "family": d.family,
        "dominant_features": json.loads(d.dominant_features_json or "[]"),
        "indicator_set": json.loads(d.indicator_set_json or "[]"),
        "avg_holding_days": d.avg_holding_days, "avg_drawdown": d.avg_drawdown,
        "preferred_regime": d.preferred_regime, "avg_confidence": d.avg_confidence,
        "sector_preference": json.loads(d.sector_preference_json or "{}"),
        "generation": d.generation,
        "mutation_history": json.loads(d.mutation_history_json or "[]"),
        "parent_ids": json.loads(d.parent_ids_json or "[]"),
        "dna_hash": d.dna_hash,
    }
