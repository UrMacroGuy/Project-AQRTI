"""
Crossover Engine
Combines two parent strategies to produce a child.

Crossover methods:
  1. rule_blend      — take N conditions from parent A, M conditions from parent B
  2. param_blend     — average stop_loss, take_profit, min_confidence between parents
  3. regime_union    — child allowed_regimes = union of both parents
  4. regime_intersect — child allowed_regimes = intersection of both parents
  5. family_dominant — take entry rules from better parent, exits from the other

The child inherits the family of the higher-fitness parent.
"""

from __future__ import annotations

import sys, os, copy, random
from typing import Optional

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from aqrti.utils.logger import get_logger
from strategies.strategy_dsl import StrategyDSL, Condition, ConditionGroup
from strategies.mutation_engine import _collect_conditions

log = get_logger("crossover_engine")


def _nudge_entry_condition(child: StrategyDSL, rng: random.Random) -> None:
    """Nudge one entry condition threshold so child gets a unique strategy_id()."""
    conds = _collect_conditions(child.entry_conditions)
    nudged = False
    for c in conds:
        if isinstance(c.threshold, (int, float)):
            factor = 1.0 + rng.uniform(-0.15, 0.15)
            c.threshold = round(c.threshold * factor, 4) if isinstance(c.threshold, float) else int(c.threshold * factor)
            nudged = True
            break
    if not nudged:
        child.entry_conditions.conditions.append(
            Condition(feature="volume_ratio_20d", operator=">", threshold=0.01)
        )


def crossover(
    parent_a:     StrategyDSL,
    parent_b:     StrategyDSL,
    fitness_a:    float = 50.0,
    fitness_b:    float = 50.0,
    rng:          Optional[random.Random] = None,
    method:       Optional[str] = None,
) -> tuple[StrategyDSL, str, str]:
    """
    Produce a child by combining two parent strategies.

    Returns:
        (child_strategy, method_used, description)
    """
    rng = rng or random.Random()
    methods = ["rule_blend", "param_blend", "regime_union", "regime_intersect", "family_dominant"]
    method  = method or rng.choice(methods)

    child = copy.deepcopy(parent_a if fitness_a >= fitness_b else parent_b)
    desc  = ""

    conds_a = _collect_conditions(parent_a.entry_conditions)
    conds_b = _collect_conditions(parent_b.entry_conditions)

    if method == "rule_blend":
        # Take half from each parent (at least 1 from each)
        n_a    = max(1, len(conds_a) // 2)
        n_b    = max(1, len(conds_b) // 2)
        chosen = (rng.sample(conds_a, min(n_a, len(conds_a))) +
                  rng.sample(conds_b, min(n_b, len(conds_b))))
        # Deduplicate by feature name
        seen  = set()
        dedup = []
        for c in chosen:
            if c.feature not in seen:
                seen.add(c.feature)
                dedup.append(c)
        child.entry_conditions = ConditionGroup(conditions=dedup, logic="AND")
        desc = f"rule_blend: {n_a} from A + {n_b} from B → {len(dedup)} conditions"

    elif method == "param_blend":
        child.stop_loss_pct    = round((parent_a.stop_loss_pct    + parent_b.stop_loss_pct)    / 2, 1)
        child.take_profit_pct  = round((parent_a.take_profit_pct  + parent_b.take_profit_pct)  / 2, 1)
        child.min_confidence   = round((parent_a.min_confidence   + parent_b.min_confidence)   / 2, 1)
        child.max_holding_days = max(1, int((parent_a.max_holding_days + parent_b.max_holding_days) / 2))
        desc = (f"param_blend: sl={child.stop_loss_pct} tp={child.take_profit_pct} "
                f"conf={child.min_confidence} hold={child.max_holding_days}")
        _nudge_entry_condition(child, rng)

    elif method == "regime_union":
        child.allowed_regimes = sorted(set(parent_a.allowed_regimes) | set(parent_b.allowed_regimes))
        desc = f"regime_union: {child.allowed_regimes}"
        _nudge_entry_condition(child, rng)

    elif method == "regime_intersect":
        intersection = sorted(set(parent_a.allowed_regimes) & set(parent_b.allowed_regimes))
        if intersection:
            child.allowed_regimes = intersection
            desc = f"regime_intersect: {intersection}"
        else:
            child.allowed_regimes = parent_a.allowed_regimes if fitness_a >= fitness_b else parent_b.allowed_regimes
            desc = "regime_intersect: empty — used dominant parent regimes"
        _nudge_entry_condition(child, rng)

    elif method == "family_dominant":
        # Better parent contributes entry, worse contributes exit
        dom   = parent_a if fitness_a >= fitness_b else parent_b
        sub   = parent_b if fitness_a >= fitness_b else parent_a
        child.entry_conditions = copy.deepcopy(dom.entry_conditions)
        child.exit_conditions  = copy.deepcopy(sub.exit_conditions) if sub.exit_conditions else None
        child.family           = dom.family
        desc = f"family_dominant: entry from {dom.family}, exit from {sub.family}"
        _nudge_entry_condition(child, rng)

    # Child name and family
    child.name   = f"X_{parent_a.name[:8]}_{parent_b.name[:8]}"
    child.family = parent_a.family if fitness_a >= fitness_b else parent_b.family
    log.debug("Crossover (%s): %s", method, desc)
    return child, method, desc
