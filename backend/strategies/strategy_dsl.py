"""
Strategy DSL (Domain Specific Language)
Represents strategy logic as structured, serializable objects.

Example strategy:
  IF  rsi_14 > 60
  AND sector_rank > 80
  AND sentiment_score > 70
  AND regime IN [BULL, SIDEWAYS]
  THEN BUY
  EXIT_IF  rsi_14 < 40 OR holding_days >= 10

Every strategy is:
  - Fully serializable to/from JSON
  - Evaluatable against a feature row (dict)
  - Composable (rules can be combined via AND/OR)
  - Evolvable (thresholds and rules can be mutated)
"""

from __future__ import annotations

import json
import hashlib
from dataclasses import dataclass, field, asdict
from typing import Any, Optional


# ── Condition ────────────────────────────────────────────────
OPERATORS = {
    ">":   lambda a, b: a > b,
    "<":   lambda a, b: a < b,
    ">=":  lambda a, b: a >= b,
    "<=":  lambda a, b: a <= b,
    "==":  lambda a, b: a == b,
    "!=":  lambda a, b: a != b,
    "in":  lambda a, b: a in b,      # b must be a list
    "not_in": lambda a, b: a not in b,
}


@dataclass
class Condition:
    """Single comparison: feature_name operator threshold."""
    feature:   str
    operator:  str               # one of OPERATORS keys
    threshold: Any               # float, int, or list for "in"
    weight:    float = 1.0       # contribution weight (used in scoring, not filtering)

    def evaluate(self, features: dict) -> bool:
        val = features.get(self.feature)
        if val is None:
            return False
        op = OPERATORS.get(self.operator)
        if op is None:
            return False
        try:
            return bool(op(val, self.threshold))
        except (TypeError, ValueError):
            return False

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Condition":
        return cls(**d)

    def __str__(self) -> str:
        return f"{self.feature} {self.operator} {self.threshold}"


@dataclass
class ConditionGroup:
    """
    A group of Conditions combined with AND or OR logic.
    Nested groups are supported.
    """
    conditions: list   # list of Condition or ConditionGroup
    logic:      str = "AND"   # AND | OR

    def evaluate(self, features: dict) -> bool:
        results = [
            c.evaluate(features) if isinstance(c, (Condition, ConditionGroup)) else False
            for c in self.conditions
        ]
        if self.logic == "AND":
            return all(results)
        return any(results)

    def to_dict(self) -> dict:
        return {
            "logic":      self.logic,
            "conditions": [
                c.to_dict() if hasattr(c, "to_dict") else c
                for c in self.conditions
            ],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ConditionGroup":
        conditions = []
        for c in d.get("conditions", []):
            if "logic" in c:
                conditions.append(ConditionGroup.from_dict(c))
            else:
                conditions.append(Condition.from_dict(c))
        return cls(conditions=conditions, logic=d.get("logic", "AND"))


@dataclass
class StrategyDSL:
    """
    Complete strategy definition.

    entry_conditions : rules that must all pass to generate a BUY signal
    exit_conditions  : rules that trigger EXIT — evaluated daily while position is open
    allowed_regimes  : list of regime strings in which this strategy is allowed to trade
    family           : strategy family label
    name             : human-readable name
    signal_type      : BUY | SELL | BOTH (default BUY)
    min_confidence   : minimum AQRTI confidence required to act on the signal
    generation_source: "sampler" (pure random/quantile sampling) or
                       "llm_hint" (parameterization proposed by
                       llm_strategy_advisor, then scaffolded onto the same
                       family template — honest attribution only, does not
                       affect strategy_id() or gate behavior)
    """
    entry_conditions: ConditionGroup
    exit_conditions:  Optional[ConditionGroup] = None
    allowed_regimes:  list[str] = field(default_factory=lambda: ["BULL", "SIDEWAYS", "BEAR", "VOLATILE"])
    family:           str = "hybrid"
    name:             str = ""
    signal_type:      str = "BUY"
    min_confidence:   float = 60.0
    max_holding_days: int = 15
    stop_loss_pct:    float = -8.0    # percentage loss that triggers exit
    take_profit_pct:  float = 15.0   # percentage gain that triggers exit
    generation_source: str = "sampler"

    # ── Evaluation ──────────────────────────────────────────

    def should_enter(self, features: dict, regime: str | None = None) -> bool:
        """True if entry conditions are met and regime is allowed."""
        if regime and regime not in self.allowed_regimes:
            return False
        return self.entry_conditions.evaluate(features)

    def should_exit(
        self,
        features:     dict,
        holding_days: int  = 0,
        pnl_pct:      float = 0.0,
    ) -> tuple[bool, str]:
        """Returns (should_exit, reason)."""
        if holding_days >= self.max_holding_days:
            return True, "max_holding_days"
        if pnl_pct <= self.stop_loss_pct:
            return True, "stop_loss"
        if pnl_pct >= self.take_profit_pct:
            return True, "take_profit"
        if self.exit_conditions and self.exit_conditions.evaluate(features):
            return True, "exit_rule"
        return False, ""

    # ── Serialisation ───────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "family":          self.family,
            "name":            self.name,
            "signal_type":     self.signal_type,
            "min_confidence":  self.min_confidence,
            "max_holding_days": self.max_holding_days,
            "stop_loss_pct":   self.stop_loss_pct,
            "take_profit_pct": self.take_profit_pct,
            "allowed_regimes": self.allowed_regimes,
            "entry_conditions": self.entry_conditions.to_dict(),
            "exit_conditions":  self.exit_conditions.to_dict() if self.exit_conditions else None,
            "generation_source": self.generation_source,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=None)

    @classmethod
    def from_dict(cls, d: dict) -> "StrategyDSL":
        entry = ConditionGroup.from_dict(d["entry_conditions"])
        exit_ = ConditionGroup.from_dict(d["exit_conditions"]) if d.get("exit_conditions") else None
        return cls(
            entry_conditions  = entry,
            exit_conditions   = exit_,
            allowed_regimes   = d.get("allowed_regimes", ["BULL", "SIDEWAYS", "BEAR", "VOLATILE"]),
            family            = d.get("family", "hybrid"),
            name              = d.get("name", ""),
            signal_type       = d.get("signal_type", "BUY"),
            min_confidence    = d.get("min_confidence", 60.0),
            max_holding_days  = d.get("max_holding_days", 15),
            stop_loss_pct     = d.get("stop_loss_pct", -8.0),
            take_profit_pct   = d.get("take_profit_pct", 15.0),
            generation_source = d.get("generation_source", "sampler"),
        )

    @classmethod
    def from_json(cls, s: str) -> "StrategyDSL":
        return cls.from_dict(json.loads(s))

    def strategy_id(self) -> str:
        """
        Deterministic hash-based ID from the FULL strategy genome: entry
        conditions, exit conditions, allowed regimes, and the risk
        parameters (SL/TP/hold/confidence).

        Previously this hashed entry_conditions ONLY, so two strategies
        differing solely in exits, regimes, or risk params collided on the
        same ID — evolution's param_blend/regime_union offspring were
        silently deduplicated against their own parents, and
        crossover_engine had to mutate an entry threshold +-15% purely to
        mint a unique ID (distorting the crossover's actual semantics).
        Existing DB rows are unaffected: strategy_id is a stored string,
        and every re-backtest path for stored rows passes the stored ID
        explicitly (backtest_and_update's strategy_id_override) instead of
        recomputing it.
        """
        content = json.dumps({
            "entry":   self.entry_conditions.to_dict(),
            "exit":    self.exit_conditions.to_dict() if self.exit_conditions else None,
            "regimes": sorted(self.allowed_regimes or []),
            "sl":      self.stop_loss_pct,
            "tp":      self.take_profit_pct,
            "hold":    self.max_holding_days,
            "conf":    self.min_confidence,
        }, sort_keys=True)
        h = hashlib.md5(content.encode()).hexdigest()[:10].upper()
        return f"AQRTI_STR_{h}"

    def human_readable(self) -> str:
        """Returns a readable summary of the strategy rules."""
        lines = [f"STRATEGY: {self.name or self.strategy_id()}",
                 f"  Family: {self.family}",
                 f"  Signal: {self.signal_type}",
                 f"  Regimes: {', '.join(self.allowed_regimes)}",
                 f"  Min Confidence: {self.min_confidence}%",
                 "  Entry Rules:"]
        for c in self.entry_conditions.conditions:
            lines.append(f"    {c}")
        if self.exit_conditions:
            lines.append("  Exit Rules:")
            for c in self.exit_conditions.conditions:
                lines.append(f"    {c}")
        lines.append(f"  Stop Loss: {self.stop_loss_pct}% | Take Profit: {self.take_profit_pct}% | Max Hold: {self.max_holding_days}d")
        return "\n".join(lines)

    def __str__(self) -> str:
        return self.human_readable()

    def feature_names(self) -> list[str]:
        """Return all feature names referenced in entry and exit conditions."""
        names = set()
        def collect(group):
            for c in group.conditions:
                if isinstance(c, Condition):
                    names.add(c.feature)
                elif isinstance(c, ConditionGroup):
                    collect(c)
        collect(self.entry_conditions)
        if self.exit_conditions:
            collect(self.exit_conditions)
        return sorted(names)

    def feature_categories(self, feature_cat_map: dict[str, str] | None = None) -> list[str]:
        """Return unique feature categories used, if a mapping dict is provided."""
        if not feature_cat_map:
            return []
        cats = {feature_cat_map.get(f) for f in self.feature_names() if feature_cat_map.get(f)}
        return sorted(cats)
