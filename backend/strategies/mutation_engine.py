"""
Mutation Engine
Produces a mutated child from a parent StrategyDSL.

Mutation operations:
  1. threshold_shift    — nudge a condition threshold ±10-30%
  2. operator_flip      — flip > to >= or vice versa, occasionally > to <
  3. feature_swap       — replace one feature with another from the same category
  4. rule_add           — append a new condition from a related category
  5. rule_remove        — remove the least important condition (must keep ≥ 2)
  6. regime_expand      — add one more allowed regime
  7. regime_restrict    — remove one allowed regime (must keep ≥ 1)
  8. param_adjust       — modify stop_loss / take_profit / max_holding_days ±20%
"""

from __future__ import annotations

import sys, os, copy, random, json
from typing import Optional

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from aqrti.utils.logger import get_logger
from strategies.strategy_dsl import StrategyDSL, Condition, ConditionGroup
from strategies.strategy_generator import (
    PRICE_FEATURES, VOLUME_FEATURES, VOLATILITY_FEATURES,
    TREND_FEATURES, SENTIMENT_FEATURES, REGIME_SETS,
)

log = get_logger("mutation_engine")

FLIP_MAP = {">": ">=", ">=": ">", "<": "<=", "<=": "<"}
ALL_REGIMES = ["BULL", "BEAR", "SIDEWAYS", "VOLATILE"]
FEATURE_POOL_BY_CATEGORY = {
    "price":      PRICE_FEATURES,
    "trend":      TREND_FEATURES,
    "volume":     VOLUME_FEATURES,
    "volatility": VOLATILITY_FEATURES,
    "sentiment":  SENTIMENT_FEATURES,
}


def _guess_category(feature: str) -> str:
    for cat, pool in FEATURE_POOL_BY_CATEGORY.items():
        if feature in pool:
            return cat
    return "price"


def _collect_conditions(group: ConditionGroup) -> list[Condition]:
    result = []
    for c in group.conditions:
        if isinstance(c, Condition):
            result.append(c)
        elif isinstance(c, ConditionGroup):
            result.extend(_collect_conditions(c))
    return result


def _replace_condition_in_group(
    group:   ConditionGroup,
    old:     Condition,
    new:     Condition,
) -> ConditionGroup:
    new_conds = []
    for c in group.conditions:
        if isinstance(c, Condition) and c is old:
            new_conds.append(new)
        elif isinstance(c, ConditionGroup):
            new_conds.append(_replace_condition_in_group(c, old, new))
        else:
            new_conds.append(c)
    return ConditionGroup(conditions=new_conds, logic=group.logic)


def mutate(
    parent:       StrategyDSL,
    rng:          Optional[random.Random] = None,
    operation:    Optional[str] = None,
) -> tuple[StrategyDSL, str, str]:
    """
    Produce a mutated copy of parent.

    Returns:
        (child_strategy, operation_used, description)
    """
    rng  = rng or random.Random()
    dsl  = copy.deepcopy(parent)
    ops  = [
        "threshold_shift", "operator_flip", "feature_swap",
        "rule_add", "rule_remove", "regime_expand", "regime_restrict", "param_adjust",
    ]
    op   = operation or rng.choice(ops)
    desc = ""

    all_conds = _collect_conditions(dsl.entry_conditions)

    if op == "threshold_shift" and all_conds:
        target = rng.choice(all_conds)
        if isinstance(target.threshold, (int, float)):
            delta = target.threshold * rng.uniform(-0.25, 0.25)
            new_thresh = round(target.threshold + delta, 4)
            new_cond   = Condition(target.feature, target.operator, new_thresh, target.weight)
            dsl.entry_conditions = _replace_condition_in_group(dsl.entry_conditions, target, new_cond)
            desc = f"threshold_shift: {target.feature} {target.operator} {target.threshold} → {new_thresh}"

    elif op == "operator_flip" and all_conds:
        target  = rng.choice([c for c in all_conds if c.operator in FLIP_MAP] or all_conds)
        new_op  = FLIP_MAP.get(target.operator, target.operator)
        new_cond = Condition(target.feature, new_op, target.threshold, target.weight)
        dsl.entry_conditions = _replace_condition_in_group(dsl.entry_conditions, target, new_cond)
        desc = f"operator_flip: {target.feature} {target.operator} → {new_op}"

    elif op == "feature_swap" and all_conds:
        target   = rng.choice(all_conds)
        cat      = _guess_category(target.feature)
        pool     = FEATURE_POOL_BY_CATEGORY.get(cat, PRICE_FEATURES)
        alts     = [f for f in pool if f != target.feature]
        if alts:
            new_feat  = rng.choice(alts)
            new_cond  = Condition(new_feat, target.operator, target.threshold, target.weight)
            dsl.entry_conditions = _replace_condition_in_group(dsl.entry_conditions, target, new_cond)
            desc = f"feature_swap: {target.feature} → {new_feat}"

    elif op == "rule_add":
        cat    = rng.choice(list(FEATURE_POOL_BY_CATEGORY.keys()))
        feat   = rng.choice(FEATURE_POOL_BY_CATEGORY[cat])
        thresh = round(rng.uniform(40, 75), 2)
        new_c  = Condition(feat, ">", thresh)
        dsl.entry_conditions.conditions.append(new_c)
        desc = f"rule_add: {feat} > {thresh}"

    elif op == "rule_remove" and len(all_conds) > 2:
        # Remove the condition with the lowest weight (or random)
        target = min(all_conds, key=lambda c: c.weight)
        dsl.entry_conditions.conditions = [
            c for c in dsl.entry_conditions.conditions if c is not target
        ]
        desc = f"rule_remove: {target}"

    elif op == "regime_expand":
        missing = [r for r in ALL_REGIMES if r not in dsl.allowed_regimes]
        if missing:
            new_regime = rng.choice(missing)
            dsl.allowed_regimes.append(new_regime)
            desc = f"regime_expand: added {new_regime}"

    elif op == "regime_restrict" and len(dsl.allowed_regimes) > 1:
        rm = rng.choice(dsl.allowed_regimes)
        dsl.allowed_regimes.remove(rm)
        desc = f"regime_restrict: removed {rm}"

    elif op == "param_adjust":
        attr = rng.choice(["stop_loss_pct", "take_profit_pct", "max_holding_days"])
        val  = getattr(dsl, attr)
        if attr == "max_holding_days":
            new_val = max(3, int(val * rng.uniform(0.8, 1.3)))
        elif attr == "stop_loss_pct":
            new_val = round(val * rng.uniform(0.8, 1.2), 1)
            new_val = min(new_val, -2.0)   # floor at -2%
        else:
            new_val = round(val * rng.uniform(0.8, 1.25), 1)
        setattr(dsl, attr, new_val)
        desc = f"param_adjust: {attr} {val} → {new_val}"

    if not desc:
        desc = f"{op}: no change applied"

    # Update name and recompute ID
    dsl.name = f"{parent.name}_mut"
    log.debug("Mutation applied: %s", desc)
    return dsl, op, desc
