"""
Index Futures Strategy Generator
Generates candidate strategies for the index-futures segment — separate
from strategy_generator.py's stock families, scoped to ONLY the features
actually computed by features/index_features.py (price/trend/volatility;
no volume/sentiment/pattern/regime features, since those don't exist for a
modeled index series).

Each candidate is assigned asset_class="index_futures" and a specific
index_name — one strategy trades exactly one instrument (see the
StrategyV2.index_name column comment in aqrti/database/models.py for why
this differs from the stock DSL's multi-symbol-universe design).

Families here are intentionally simpler than the stock generator's 11
families — index futures are a single, less noisy instrument (vs picking
among hundreds of stocks), so momentum/mean-reversion/breakout/volatility
already covers the natural strategy space without needing sentiment or
institutional-flow proxies that don't exist for this segment.
"""

from __future__ import annotations

import sys, os, json, random
from typing import Optional

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from sqlalchemy.orm import Session

from aqrti.database.models import StrategyV2
from aqrti.utils.logger import get_logger
from strategies.strategy_dsl import StrategyDSL, Condition, ConditionGroup
from strategies.strategy_store import upsert_strategy, save_version
from strategies.index_futures_config import INDEX_FUTURES_UNIVERSE

log = get_logger("index_futures_generator")

# ── Feature pools — ONLY features index_features.py actually computes ──
INDEX_PRICE_FEATURES = [
    "return_5d", "return_21d", "momentum_10d", "momentum_20d",
    "breakout_distance_52w", "price_position_52w",
    "support_distance_20d", "resistance_distance_20d", "gap_open_pct",
]
INDEX_TREND_FEATURES = [
    "rsi_14", "adx_14", "macd_histogram", "macd_crossover",
    "price_vs_ema21_pct", "price_vs_ema50_pct", "ma_20_slope", "ma_50_slope",
    "ma_spread", "di_plus_minus",
]
INDEX_VOLATILITY_FEATURES = [
    "atr_pct_14", "rolling_vol_10d", "rolling_vol_21d", "vol_compression",
    "vol_expansion", "historical_vol_63d",
]

# Futures-specific features (computed by index_features.py compute_futures_features)
INDEX_FUTURES_FEATURES = [
    "basis_pct",
]

FAMILIES = ["momentum", "mean_reversion", "breakout", "volatility_play",
            "carry_trade", "roll_yield_momentum"]


def _cond(feature: str, op: str, threshold: float, weight: float = 1.0) -> Condition:
    return Condition(feature=feature, operator=op, threshold=threshold, weight=weight)


def _rr_take_profit(rng: random.Random, stop_loss_pct: float, min_rr: float = 1.5) -> float:
    min_tp = abs(stop_loss_pct) * min_rr
    max_tp = abs(stop_loss_pct) * 3.0
    return round(rng.uniform(min_tp, max_tp), 1)


def _generate_momentum(rng: random.Random, index_name: str) -> StrategyDSL:
    feat   = rng.choice(["return_5d", "return_21d", "momentum_10d", "momentum_20d"])
    thresh = round(rng.uniform(0.8, 3.5), 2)   # index moves are smaller % than single stocks
    rsi_th = round(rng.uniform(50, 62), 1)
    conds  = [_cond(feat, ">", thresh), _cond("rsi_14", ">", rsi_th)]
    if rng.random() < 0.5:
        conds.append(_cond("adx_14", ">", round(rng.uniform(18, 28), 1)))

    sl = round(rng.uniform(-4.0, -1.5), 1)
    tp = _rr_take_profit(rng, sl)
    return StrategyDSL(
        name=f"IdxMom_{index_name}_{feat}_gt{thresh}",
        family="momentum",
        entry_conditions=ConditionGroup(conditions=conds, logic="AND"),
        exit_conditions=ConditionGroup(
            conditions=[_cond("rsi_14", "<", round(rng.uniform(38, 48), 1))], logic="OR"),
        stop_loss_pct=sl, take_profit_pct=tp,
        min_confidence=round(rng.uniform(50, 62), 1),
        max_holding_days=rng.randint(5, 20),
        allowed_regimes=["BULL", "SIDEWAYS"],
    )


def _generate_mean_reversion(rng: random.Random, index_name: str) -> StrategyDSL:
    rsi_th = round(rng.uniform(25, 35), 1)
    conds  = [_cond("rsi_14", "<", rsi_th)]
    if rng.random() < 0.5:
        conds.append(_cond("support_distance_20d", "<", round(rng.uniform(1.0, 3.0), 1)))

    sl = round(rng.uniform(-3.5, -1.5), 1)
    tp = _rr_take_profit(rng, sl, min_rr=1.2)
    return StrategyDSL(
        name=f"IdxMR_{index_name}_rsi_lt{rsi_th}",
        family="mean_reversion",
        entry_conditions=ConditionGroup(conditions=conds, logic="AND"),
        exit_conditions=ConditionGroup(
            conditions=[_cond("rsi_14", ">", round(rng.uniform(52, 62), 1))], logic="OR"),
        stop_loss_pct=sl, take_profit_pct=tp,
        min_confidence=round(rng.uniform(50, 60), 1),
        max_holding_days=rng.randint(3, 12),
        allowed_regimes=["SIDEWAYS", "BEAR"],
    )


def _generate_breakout(rng: random.Random, index_name: str) -> StrategyDSL:
    dist_th = round(rng.uniform(-3.0, -0.5), 2)   # close to/above 52w high
    conds   = [_cond("breakout_distance_52w", ">", dist_th),
               _cond("adx_14", ">", round(rng.uniform(20, 30), 1))]

    sl = round(rng.uniform(-4.5, -2.0), 1)
    tp = _rr_take_profit(rng, sl, min_rr=1.8)
    return StrategyDSL(
        name=f"IdxBrk_{index_name}_dist{dist_th}",
        family="breakout",
        entry_conditions=ConditionGroup(conditions=conds, logic="AND"),
        exit_conditions=ConditionGroup(
            conditions=[_cond("adx_14", "<", round(rng.uniform(14, 20), 1))], logic="OR"),
        stop_loss_pct=sl, take_profit_pct=tp,
        min_confidence=round(rng.uniform(52, 65), 1),
        max_holding_days=rng.randint(8, 20),
        allowed_regimes=["BULL", "VOLATILE"],
    )


def _generate_volatility_play(rng: random.Random, index_name: str) -> StrategyDSL:
    conds = [_cond("vol_compression", ">", round(rng.uniform(0.3, 0.7), 2)),
             _cond("return_5d", ">", round(rng.uniform(0.5, 2.0), 2))]

    sl = round(rng.uniform(-3.0, -1.2), 1)
    tp = _rr_take_profit(rng, sl, min_rr=1.5)
    return StrategyDSL(
        name=f"IdxVol_{index_name}_compress",
        family="volatility_play",
        entry_conditions=ConditionGroup(conditions=conds, logic="AND"),
        exit_conditions=ConditionGroup(
            conditions=[_cond("vol_expansion", ">", round(rng.uniform(1.5, 2.5), 1))], logic="OR"),
        stop_loss_pct=sl, take_profit_pct=tp,
        min_confidence=round(rng.uniform(50, 60), 1),
        max_holding_days=rng.randint(5, 15),
        allowed_regimes=["BULL", "SIDEWAYS", "VOLATILE"],
    )


def _generate_carry_trade(rng: random.Random, index_name: str) -> StrategyDSL:
    """
    P-PF-7: Trade the cost-of-carry basis. Enter long when futures trade at
    a discount to spot (negative basis = backwardation = positive carry for
    longs), confirmed by trending conditions. The thesis: in backwardation,
    the futures price converges toward spot at expiry, adding a structural
    tailwind to long positions that pure equity strategies cannot access.
    Index futures have far lower round-trip cost (0.10% vs 0.28%), so this
    structural advantage is not eaten by transaction friction.
    """
    basis_th = round(rng.uniform(-0.15, -0.03), 3)   # basis < -0.03% = discount
    rsi_th   = round(rng.uniform(45, 58), 1)
    conds    = [_cond("basis_pct", "<", basis_th, weight=1.3),
                _cond("rsi_14", ">", rsi_th)]
    if rng.random() < 0.5:
        conds.append(_cond("adx_14", ">", round(rng.uniform(18, 26), 1)))

    sl = round(rng.uniform(-3.5, -1.5), 1)
    tp = _rr_take_profit(rng, sl, min_rr=1.6)
    return StrategyDSL(
        name=f"Carry_{index_name}_basis{basis_th}",
        family="carry_trade",
        entry_conditions=ConditionGroup(conditions=conds, logic="AND"),
        exit_conditions=ConditionGroup(
            conditions=[_cond("basis_pct", ">", round(rng.uniform(0.0, 0.10), 3)),
                        _cond("rsi_14", ">", round(rng.uniform(65, 78), 1))],
            logic="OR"),
        stop_loss_pct=sl, take_profit_pct=tp,
        min_confidence=round(rng.uniform(52, 65), 1),
        max_holding_days=rng.randint(10, 25),
        allowed_regimes=["BULL", "SIDEWAYS"],
    )


def _generate_roll_yield_momentum(rng: random.Random, index_name: str) -> StrategyDSL:
    """
    P-PF-7: Momentum on the futures series, filtered by basis environment.
    Only enter when (a) futures themselves are trending and (b) the basis
    is not in extreme contango (which would impose excessive negative carry
    cost on a long position). This avoids the worst case for a long futures
    strategy: catching a trend right when it is most expensive to hold.
    """
    thresh = round(rng.uniform(0.8, 2.5), 2)     # modest momentum
    rsi_th = round(rng.uniform(50, 62), 1)
    basis_cap = round(rng.uniform(0.05, 0.15), 3) # basis must be below this (not extreme contango)
    conds  = [_cond("return_5d", ">", thresh),
              _cond("rsi_14", ">", rsi_th),
              _cond("basis_pct", "<", basis_cap)]
    if rng.random() < 0.5:
        conds.append(_cond("adx_14", ">", round(rng.uniform(20, 28), 1)))

    sl = round(rng.uniform(-3.0, -1.5), 1)
    tp = _rr_take_profit(rng, sl, min_rr=1.5)
    return StrategyDSL(
        name=f"RollMom_{index_name}_ret{thresh}",
        family="roll_yield_momentum",
        entry_conditions=ConditionGroup(conditions=conds, logic="AND"),
        exit_conditions=ConditionGroup(
            conditions=[_cond("rsi_14", "<", round(rng.uniform(38, 48), 1)),
                        _cond("return_5d", "<", round(-rng.uniform(1.0, 2.0), 2))],
            logic="OR"),
        stop_loss_pct=sl, take_profit_pct=tp,
        min_confidence=round(rng.uniform(50, 62), 1),
        max_holding_days=rng.randint(7, 18),
        allowed_regimes=["BULL", "SIDEWAYS", "VOLATILE"],
    )


_GENERATORS = {
    "momentum":            _generate_momentum,
    "mean_reversion":      _generate_mean_reversion,
    "breakout":             _generate_breakout,
    "volatility_play":      _generate_volatility_play,
    "carry_trade":          _generate_carry_trade,
    "roll_yield_momentum":  _generate_roll_yield_momentum,
}


def generate_index_candidates(
    n: int = 20,
    index_names: Optional[list[str]] = None,
    seed: Optional[int] = None,
) -> list[tuple[StrategyDSL, str]]:
    """Returns list of (StrategyDSL, index_name) tuples."""
    rng = random.Random(seed)
    targets = index_names or list(INDEX_FUTURES_UNIVERSE.keys())

    candidates = []
    attempts = 0
    seen_ids = set()
    while len(candidates) < n and attempts < n * 10:
        attempts += 1
        index_name = rng.choice(targets)
        family = rng.choice(FAMILIES)
        dsl = _GENERATORS[family](rng, index_name)
        sid = dsl.strategy_id()
        if sid in seen_ids:
            continue
        seen_ids.add(sid)
        candidates.append((dsl, index_name))

    log.info("Generated %d/%d index-futures candidates in %d attempts",
              len(candidates), n, attempts)
    return candidates


def persist_index_candidates(
    db: Session,
    candidates: list[tuple[StrategyDSL, str]],
    generation: int = 0,
) -> int:
    """Same contract as strategy_generator.persist_candidates, index-scoped."""
    written = 0
    for dsl, index_name in candidates:
        sid = dsl.strategy_id()
        existing = db.query(StrategyV2.id).filter(StrategyV2.strategy_id == sid).first()
        if existing:
            continue

        feature_cats = list({
            "price" if f in INDEX_PRICE_FEATURES else
            "trend" if f in INDEX_TREND_FEATURES else
            "volatility" if f in INDEX_VOLATILITY_FEATURES else "other"
            for f in dsl.feature_names()
        })
        upsert_strategy(db, {
            "strategy_id":        sid,
            "name":               dsl.name,
            "family":             dsl.family,
            "generation":         generation,
            "dsl_json":           dsl.to_json(),
            "feature_categories": json.dumps(feature_cats),
            "allowed_regimes":    json.dumps(dsl.allowed_regimes),
            "status":             "candidate",
            "asset_class":        "index_futures",
            "index_name":         index_name,
        })
        save_version(db, sid, dsl.to_json(), version=1, change_type="seed")
        written += 1

    db.commit()
    log.info("Persisted %d new index-futures candidate strategies (generation=%d)",
              written, generation)
    return written


def run_index_generation_cycle(db: Session, n: int = 20, generation: int = 0,
                                index_names: Optional[list[str]] = None,
                                seed: Optional[int] = None) -> dict:
    candidates = generate_index_candidates(n=n, index_names=index_names, seed=seed)
    written = persist_index_candidates(db, candidates, generation=generation)
    return {
        "generated": len(candidates),
        "persisted": written,
        "skipped":   len(candidates) - written,
        "generation": generation,
    }
