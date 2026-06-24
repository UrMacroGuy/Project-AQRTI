"""
Strategy Generator
Generates candidate strategies systematically across 7 feature categories.

Generation approach:
  - For each family template, define a parameter grid (thresholds, feature combinations)
  - Randomly sample N points from the grid to produce candidates
  - Each candidate is a valid StrategyDSL object immediately ready for backtesting
  - Deduplication via strategy_id hash — duplicates are silently skipped

Supported families:
  momentum, mean_reversion, breakout, sentiment_driven,
  regime_adaptive, volume_surge, volatility_play, hybrid
"""

from __future__ import annotations

import sys, os, json, random
from datetime import date
from typing import Optional

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from sqlalchemy.orm import Session

from aqrti.database.models import StrategyV2
from aqrti.utils.logger import get_logger
from strategies.strategy_dsl import StrategyDSL, Condition, ConditionGroup
from strategies.strategy_store import upsert_strategy, save_version

log = get_logger("strategy_generator")

# ── Feature pools by category ─────────────────────────────────

PRICE_FEATURES = [
    "return_1d", "return_5d", "return_21d", "momentum_10d", "momentum_20d",
    "breakout_distance_52w", "price_position_52w", "relative_strength_nifty_21d",
    "support_distance_20d", "resistance_distance_20d",
]
VOLUME_FEATURES = [
    "volume_ratio_20d", "delivery_pct", "volume_surge_flag",
    "vwap_distance", "institutional_flow_proxy",
]
VOLATILITY_FEATURES = [
    "atr_14", "bb_width_20", "realized_vol_20d", "vol_ratio_short_long",
    "hv_percentile_252d",
]
TREND_FEATURES = [
    "ema_20", "ema_50", "macd_signal", "adx_14", "rsi_14", "stoch_k",
    "price_above_ema50", "ema20_above_ema50",
]
SENTIMENT_FEATURES = [
    "sentiment_score", "sentiment_velocity", "news_impact_score",
    "sector_sentiment_score",
]
PATTERN_FEATURES = [
    "pattern_confidence", "similarity_score",
]
REGIME_FEATURES = [
    "regime_confidence", "breadth_pct", "nifty_trend_score",
]

# ── Regime groupings ──────────────────────────────────────────
REGIME_SETS = {
    "bull_only":       ["BULL"],
    "bull_sideways":   ["BULL", "SIDEWAYS"],
    "all_weather":     ["BULL", "BEAR", "SIDEWAYS", "VOLATILE"],
    "defensive":       ["SIDEWAYS", "BEAR"],
    "high_vol":        ["VOLATILE"],
    "trending":        ["BULL", "BEAR"],
}

# ── Family templates ──────────────────────────────────────────

def _make_condition(feature: str, op: str, threshold: float, weight: float = 1.0) -> Condition:
    return Condition(feature=feature, operator=op, threshold=threshold, weight=weight)


def _rand_confidence(rng: random.Random, lo: float = 50.0, hi: float = 68.0) -> float:
    """Generate a realistic min_confidence — biased toward lower values that fire more signals."""
    return round(rng.uniform(lo, hi), 1)


def _generate_momentum(rng: random.Random) -> StrategyDSL:
    feat   = rng.choice(["return_5d", "return_21d", "momentum_10d", "momentum_20d"])
    # Wider threshold ranges so some strategies fire on smaller moves
    thresh = rng.uniform(1.0, 6.0)
    rsi_th = rng.uniform(45, 60)       # was 50-65, lowered to catch more entries
    regime = rng.choice(["bull_only", "bull_sideways", "all_weather"])
    n_conds = rng.randint(2, 3)        # allow 2-condition strategies (less restrictive)
    conds = [_make_condition(feat, ">", round(thresh, 2))]
    if n_conds >= 2:
        conds.append(_make_condition("rsi_14", ">", round(rsi_th, 1)))
    if n_conds >= 3:
        trend = rng.choice(["macd_signal", "adx_14", "ema20_above_ema50"])
        t_val = rng.uniform(45, 65)
        conds.append(_make_condition(trend, ">", round(t_val, 1)))
    entry  = ConditionGroup(conditions=conds)
    exit_  = ConditionGroup(conditions=[
        _make_condition("rsi_14", ">", round(rng.uniform(68, 80), 1)),
    ], logic="OR")
    return StrategyDSL(
        entry_conditions = entry,
        exit_conditions  = exit_,
        allowed_regimes  = REGIME_SETS[regime],
        family           = "momentum",
        name             = f"Momentum_{feat}_{round(thresh,1)}",
        min_confidence   = _rand_confidence(rng, 50.0, 68.0),
        max_holding_days = rng.randint(5, 20),
        stop_loss_pct    = round(-rng.uniform(5, 10), 1),
        take_profit_pct  = round(rng.uniform(8, 18), 1),
    )


def _generate_mean_reversion(rng: random.Random) -> StrategyDSL:
    rsi_lo = round(rng.uniform(28, 42), 1)
    n_conds = rng.randint(2, 3)
    conds = [_make_condition("rsi_14", "<", rsi_lo)]
    if n_conds >= 2:
        conds.append(_make_condition("return_5d", "<", round(-rng.uniform(1.0, 3.5), 2)))
    if n_conds >= 3:
        conds.append(_make_condition("bb_width_20", ">", round(rng.uniform(0.02, 0.07), 3)))
    entry  = ConditionGroup(conditions=conds)
    exit_  = ConditionGroup(conditions=[
        _make_condition("rsi_14", ">", round(rng.uniform(48, 58), 1)),
    ])
    return StrategyDSL(
        entry_conditions = entry,
        exit_conditions  = exit_,
        allowed_regimes  = REGIME_SETS[rng.choice(["bull_sideways", "all_weather"])],
        family           = "mean_reversion",
        name             = f"MeanRev_RSI{rsi_lo}",
        min_confidence   = _rand_confidence(rng, 48.0, 65.0),
        max_holding_days = rng.randint(3, 12),
        stop_loss_pct    = round(-rng.uniform(4, 9), 1),
        take_profit_pct  = round(rng.uniform(5, 13), 1),
    )


def _generate_breakout(rng: random.Random) -> StrategyDSL:
    brk_th = round(rng.uniform(-5, 2), 2)   # wider range — can enter at -5% from 52w high
    vol_th = round(rng.uniform(1.2, 2.2), 2)
    n_conds = rng.randint(2, 4)
    conds = [_make_condition("breakout_distance_52w", ">", brk_th)]
    if n_conds >= 2:
        conds.append(_make_condition("volume_ratio_20d", ">", vol_th))
    if n_conds >= 3:
        adx_th = round(rng.uniform(18, 32), 1)
        conds.append(_make_condition("adx_14", ">", adx_th))
    if n_conds >= 4:
        conds.append(_make_condition("price_above_ema50", "==", 1.0))
    regime = rng.choice(["bull_only", "bull_sideways"])
    return StrategyDSL(
        entry_conditions = ConditionGroup(conditions=conds),
        allowed_regimes  = REGIME_SETS[regime],
        family           = "breakout",
        name             = f"Breakout_52w_{round(brk_th,1)}",
        min_confidence   = _rand_confidence(rng, 52.0, 68.0),
        max_holding_days = rng.randint(8, 22),
        stop_loss_pct    = round(-rng.uniform(6, 12), 1),
        take_profit_pct  = round(rng.uniform(12, 28), 1),
    )


def _generate_sentiment_driven(rng: random.Random) -> StrategyDSL:
    sent_th = round(rng.uniform(55, 75), 1)
    n_conds = rng.randint(2, 3)
    conds = [_make_condition("sentiment_score", ">", sent_th)]
    if n_conds >= 2:
        tech_f  = rng.choice(["rsi_14", "momentum_10d", "return_5d", "adx_14"])
        tech_v  = round(rng.uniform(40, 58), 1)
        conds.append(_make_condition(tech_f, ">", tech_v))
    if n_conds >= 3:
        vel_th = round(rng.uniform(3, 15), 1)
        conds.append(_make_condition("sentiment_velocity", ">", vel_th))
    entry   = ConditionGroup(conditions=conds)
    return StrategyDSL(
        entry_conditions = entry,
        allowed_regimes  = REGIME_SETS[rng.choice(["bull_sideways", "all_weather"])],
        family           = "sentiment_driven",
        name             = f"Sentiment_GT{sent_th}",
        min_confidence   = _rand_confidence(rng, 50.0, 65.0),
        max_holding_days = rng.randint(4, 14),
        stop_loss_pct    = round(-rng.uniform(5, 9), 1),
        take_profit_pct  = round(rng.uniform(7, 16), 1),
    )


def _generate_regime_adaptive(rng: random.Random) -> StrategyDSL:
    regime_set = rng.choice(list(REGIME_SETS.keys()))
    feat1 = rng.choice(PRICE_FEATURES + TREND_FEATURES[:4])
    v1    = round(rng.uniform(-3, 5), 2)
    n_conds = rng.randint(2, 3)
    conds = [_make_condition(feat1, ">", v1)]
    if n_conds >= 2:
        feat2 = rng.choice(TREND_FEATURES)
        v2    = round(rng.uniform(38, 62), 1)
        conds.append(_make_condition(feat2, ">", v2))
    if n_conds >= 3:
        conds.append(_make_condition("regime_confidence", ">", round(rng.uniform(55, 75), 1)))
    entry  = ConditionGroup(conditions=conds)
    return StrategyDSL(
        entry_conditions = entry,
        allowed_regimes  = REGIME_SETS[regime_set],
        family           = "regime_adaptive",
        name             = f"Regime_{regime_set}_{feat1[:6]}",
        min_confidence   = _rand_confidence(rng, 50.0, 66.0),
        max_holding_days = rng.randint(6, 20),
        stop_loss_pct    = round(-rng.uniform(6, 11), 1),
        take_profit_pct  = round(rng.uniform(9, 22), 1),
    )


def _generate_volume_surge(rng: random.Random) -> StrategyDSL:
    vol_th  = round(rng.uniform(1.3, 2.8), 2)
    n_conds = rng.randint(2, 4)
    conds   = [_make_condition("volume_ratio_20d", ">", vol_th)]
    if n_conds >= 2:
        rsi_th  = round(rng.uniform(42, 62), 1)
        conds.append(_make_condition("rsi_14", ">", rsi_th))
    if n_conds >= 3:
        conds.append(_make_condition("return_1d", ">", round(rng.uniform(0.3, 1.8), 2)))
    if n_conds >= 4:
        del_th = round(rng.uniform(50, 72), 1)
        conds.append(_make_condition("delivery_pct", ">", del_th))
    return StrategyDSL(
        entry_conditions = ConditionGroup(conditions=conds),
        allowed_regimes  = REGIME_SETS[rng.choice(["bull_sideways", "bull_only", "all_weather"])],
        family           = "volume_surge",
        name             = f"VolSurge_{vol_th}x",
        min_confidence   = _rand_confidence(rng, 52.0, 67.0),
        max_holding_days = rng.randint(3, 10),
        stop_loss_pct    = round(-rng.uniform(4, 8), 1),
        take_profit_pct  = round(rng.uniform(6, 14), 1),
    )


def _generate_volatility_play(rng: random.Random) -> StrategyDSL:
    atr_th  = round(rng.uniform(1.2, 3.5), 2)
    n_conds = rng.randint(2, 3)
    conds   = [_make_condition("atr_14", ">", atr_th)]
    if n_conds >= 2:
        rsi_th  = round(rng.uniform(32, 52), 1)
        conds.append(_make_condition("rsi_14", "<", rsi_th))
    if n_conds >= 3:
        hv_th = round(rng.uniform(35, 65), 1)
        conds.append(_make_condition("hv_percentile_252d", "<", hv_th))
    # Volatility plays work in all markets including volatile regimes
    return StrategyDSL(
        entry_conditions = ConditionGroup(conditions=conds),
        allowed_regimes  = REGIME_SETS[rng.choice(["high_vol", "all_weather", "bull_sideways"])],
        family           = "volatility_play",
        name             = f"VolPlay_ATR{atr_th}",
        min_confidence   = _rand_confidence(rng, 48.0, 64.0),
        max_holding_days = rng.randint(3, 8),
        stop_loss_pct    = round(-rng.uniform(3, 7), 1),
        take_profit_pct  = round(rng.uniform(5, 13), 1),
    )


def _generate_hybrid(rng: random.Random) -> StrategyDSL:
    # Pick 2-3 features from different categories — wider feature space
    all_cats = [PRICE_FEATURES, TREND_FEATURES, VOLUME_FEATURES, VOLATILITY_FEATURES]
    rng.shuffle(all_cats)
    n_conds = rng.randint(2, 3)
    conds = []
    for pool in all_cats[:n_conds]:
        feat   = rng.choice(pool)
        # Use feature-appropriate threshold ranges
        if feat in VOLATILITY_FEATURES:
            thresh = round(rng.uniform(0.02, 3.0), 3)
        elif feat in VOLUME_FEATURES:
            thresh = round(rng.uniform(1.0, 2.5), 2)
        else:
            thresh = round(rng.uniform(40, 70), 2)
        op = rng.choice([">", ">", ">="])   # bias toward greater-than
        conds.append(_make_condition(feat, op, thresh))
    entry = ConditionGroup(conditions=conds)
    return StrategyDSL(
        entry_conditions = entry,
        allowed_regimes  = REGIME_SETS[rng.choice(["bull_sideways", "all_weather", "bull_only"])],
        family           = "hybrid",
        name             = f"Hybrid_{conds[0].feature[:6]}_{conds[1].feature[:6]}",
        min_confidence   = _rand_confidence(rng, 50.0, 66.0),
        max_holding_days = rng.randint(6, 18),
        stop_loss_pct    = round(-rng.uniform(5, 10), 1),
        take_profit_pct  = round(rng.uniform(8, 18), 1),
    )


_GENERATORS = {
    "momentum":         _generate_momentum,
    "mean_reversion":   _generate_mean_reversion,
    "breakout":         _generate_breakout,
    "sentiment_driven": _generate_sentiment_driven,
    "regime_adaptive":  _generate_regime_adaptive,
    "volume_surge":     _generate_volume_surge,
    "volatility_play":  _generate_volatility_play,
    "hybrid":           _generate_hybrid,
}


def generate_candidates(
    n:            int = 100,
    seed:         int | None = None,
    families:     list[str] | None = None,
) -> list[StrategyDSL]:
    """
    Generate N candidate strategies.

    Args:
        n:        number of candidates to generate
        seed:     random seed for reproducibility
        families: restrict generation to specific families

    Returns:
        list of unique StrategyDSL objects (deduplicated by strategy_id)
    """
    rng      = random.Random(seed)
    pool     = families or list(_GENERATORS.keys())
    seen_ids = set()
    result   = []

    attempts = 0
    while len(result) < n and attempts < n * 5:
        family = rng.choice(pool)
        gen_fn = _GENERATORS[family]
        try:
            strategy = gen_fn(rng)
            sid      = strategy.strategy_id()
            if sid not in seen_ids:
                seen_ids.add(sid)
                result.append(strategy)
        except Exception as exc:
            log.warning("Generator error in family %s: %s", family, exc)
        attempts += 1

    log.info("Generated %d candidates (%d families) in %d attempts", len(result), len(pool), attempts)
    return result


def persist_candidates(
    db:         Session,
    candidates: list[StrategyDSL],
    generation: int = 0,
) -> int:
    """
    Write new candidates to the DB. Skips those already present.
    Returns count of new rows written.
    """
    written = 0
    for s in candidates:
        sid = s.strategy_id()
        existing = db.query(StrategyV2.id).filter(StrategyV2.strategy_id == sid).first()
        if existing:
            continue
        feature_cats = list({
            part for f in s.feature_names()
            for part in (["price"] if f in PRICE_FEATURES else
                         ["volume"] if f in VOLUME_FEATURES else
                         ["volatility"] if f in VOLATILITY_FEATURES else
                         ["trend"] if f in TREND_FEATURES else
                         ["sentiment"] if f in SENTIMENT_FEATURES else
                         ["pattern"] if f in PATTERN_FEATURES else
                         ["regime"] if f in REGIME_FEATURES else [])
        })
        row = upsert_strategy(db, {
            "strategy_id":       sid,
            "name":              s.name,
            "family":            s.family,
            "generation":        generation,
            "dsl_json":          s.to_json(),
            "feature_categories": json.dumps(feature_cats),
            "allowed_regimes":   json.dumps(s.allowed_regimes),
            "status":            "candidate",
        })
        save_version(db, sid, s.to_json(), version=1, change_type="seed")
        written += 1

    db.commit()
    log.info("Persisted %d new candidate strategies (generation=%d)", written, generation)
    return written


def run_generation_cycle(
    db:       Session,
    n:        int = 200,
    seed:     int | None = None,
    families: list[str] | None = None,
    generation: int = 0,
) -> dict:
    candidates = generate_candidates(n=n, seed=seed, families=families)
    written    = persist_candidates(db, candidates, generation=generation)
    return {
        "generated":   len(candidates),
        "persisted":   written,
        "skipped":     len(candidates) - written,
        "generation":  generation,
    }
