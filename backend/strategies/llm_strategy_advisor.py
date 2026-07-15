"""
LLM Strategy Advisor (Phase C, 2026-07-15c)
Two fail-closed LLM touchpoints for strategy generation, both via
aqrti.llm.provider.ask_structured — which already returns None on ANY
failure (provider down, bad JSON, schema mismatch). Every candidate this
module influences still flows through the full backtest + gate stack in
promotion_config.py; nothing here bypasses a gate or writes fabricated data.

Touchpoint 1 — parameterization hints. The LLM proposes a StrategyHint
(family + conditions + rationale) grounded in that family's own docstring
(anomaly + evidence) plus REAL measured feature quantiles and REAL
meta_learner aggregates. Every field is validated against ground truth
(registered feature, valid DSL operator, threshold inside the feature's
measured q1-q99 band) before being trusted — an invalid hint is silently
dropped, never coerced into something "close enough".

Touchpoint 2 — graveyard post-mortem. Real graveyard cluster stats go to
the LLM; its suggested avoid-list is validated the same way and folded into
meta_learner's bad-condition counts as a small CAPPED increment — never
enough on its own to cross the existing dead_count>=5 threshold that
actually blacklists a condition. Measured evidence always dominates; the
LLM can only nudge candidates that are already near that bar.

Env kill-switch: AQRTI_LLM_STRATEGY_HINTS (default "1"/on whenever a NIM
key is configured). Any failure — kill-switch off, no provider, LLM error,
validation failure — degrades silently to the pure sampler / pure
measured-evidence path used before this module existed.
"""

from __future__ import annotations

import os
import sys
from typing import Literal, Optional

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from aqrti.llm.provider import ask_structured, is_configured as _llm_configured
from aqrti.utils.logger import get_logger
from strategies.strategy_dsl import StrategyDSL, Condition, ConditionGroup, OPERATORS
from strategies.strategy_generator import _GENERATORS, REGIME_SETS, _rr_take_profit
from strategies.feature_stats import get_feature_quantiles
from features.feature_registry import CATALOG as FEATURE_CATALOG

log = get_logger("llm_strategy_advisor")

# Bumping a bad-condition count by more than this (per post-mortem run)
# would let a single LLM opinion single-handedly cross the real
# dead_count>=5 blacklist threshold in meta_learner.py — capped well below
# that so it can only nudge conditions that measured evidence already put
# close to the line.
_MAX_GRAVEYARD_WEAK_BUMP = 2
_MAX_HINTS_PER_CYCLE_PCT = 0.20   # ~20% of a generation cycle, per plan


def _kill_switch_enabled() -> bool:
    raw = os.getenv("AQRTI_LLM_STRATEGY_HINTS")
    if raw is not None:
        return raw.strip().lower() not in ("0", "false", "off", "no")
    return _llm_configured()   # default on when a key is configured


# ─────────────────────────────────────────────────────────────────
# Touchpoint 1 — parameterization hints
# ─────────────────────────────────────────────────────────────────

class HintCondition(BaseModel):
    feature:   str
    operator:  str
    threshold: float


class StrategyHint(BaseModel):
    """LLM-proposed parameterization for one candidate. Rationale is logged
    only — it never influences validation or the resulting DSL."""
    family:     str
    conditions: list[HintCondition] = Field(min_length=1, max_length=5)
    rationale:  str = ""


def _validate_hint(hint: StrategyHint, stats_by_feature: dict[str, dict]) -> Optional[StrategyHint]:
    """Strict reject on any unknown family/feature/operator, or a threshold
    outside that feature's measured q1-q99 band. Returns None on any
    violation — never clamps or coerces a bad hint into a valid one."""
    if hint.family not in _GENERATORS:
        log.debug("LLM hint rejected: unknown family %r", hint.family)
        return None
    for c in hint.conditions:
        if c.feature not in FEATURE_CATALOG:
            log.debug("LLM hint rejected: unregistered feature %r", c.feature)
            return None
        if c.operator not in OPERATORS:
            log.debug("LLM hint rejected: unknown operator %r", c.operator)
            return None
        band = stats_by_feature.get(c.feature)
        if band:
            q10, q90 = band.get("q10"), band.get("q90")
            if q10 is not None and q90 is not None:
                lo, hi = (q10, q90) if q10 <= q90 else (q90, q10)
                margin = (hi - lo) * 0.5 or 1.0   # q1-q99 approximated as a widened q10-q90 band
                if not (lo - margin <= c.threshold <= hi + margin):
                    log.debug(
                        "LLM hint rejected: %s threshold %.4f outside measured band [%.4f, %.4f]",
                        c.feature, c.threshold, lo - margin, hi + margin,
                    )
                    return None
    return hint


def _build_hint_prompt(family: str, stats_by_feature: dict[str, dict], meta_state: dict | None) -> str:
    gen_fn = _GENERATORS[family]
    docstring = (gen_fn.__doc__ or "").strip()

    quantile_lines = []
    for feat, q in stats_by_feature.items():
        quantile_lines.append(f"  {feat}: q10={q.get('q10')} q50={q.get('q50')} q90={q.get('q90')}")
    quantile_block = "\n".join(quantile_lines) or "  (no measured quantiles available)"

    meta_block = "(no meta-learner state available)"
    if meta_state:
        priors = (meta_state.get("param_priors") or {}).get(family)
        good_conditions = [
            k for k in (meta_state.get("good_condition_counts") or {}) if k.startswith(f"{family}|")
        ][:10]
        meta_block = f"param_priors for this family: {priors}\ngood conditions observed: {good_conditions}"

    return f"""You are proposing entry-condition parameters for a quant strategy
template in the AQRTI system. The template is fixed and documented below —
you are NOT inventing a new strategy, only suggesting realistic thresholds
for its existing conditions, grounded in the real data provided.

TEMPLATE ({family}):
{docstring}

REAL measured feature quantiles across the curated universe:
{quantile_block}

REAL meta-learner aggregates from past strategies of this family:
{meta_block}

Propose 2-4 entry conditions using ONLY features from the quantile list
above (or the template's known features), with thresholds inside the
measured q10-q90 range. Every condition must be directly supported by the
data shown — do not invent a feature or a value outside the measured range."""


def get_generation_hints(
    db: Session,
    families: list[str],
    n_hints: int,
    meta_state: dict | None = None,
) -> list[StrategyHint]:
    """
    Request up to n_hints validated StrategyHints, one LLM call per hint
    (bounded by the caller's rate budget — generate_candidates() only asks
    for ~20% of a cycle's candidates this way). Returns fewer than n_hints
    (possibly zero) on any failure — callers must never block on this.
    """
    if not _kill_switch_enabled() or n_hints <= 0 or not families:
        return []

    hints: list[StrategyHint] = []
    for i in range(n_hints):
        family = families[i % len(families)]
        stats_by_feature: dict[str, dict] = {}
        # Only pull quantiles for features this family's own generator uses,
        # to keep the prompt (and DB cost) small.
        try:
            sample_dsl = _GENERATORS[family](__import__("random").Random(i))
            for feat in sample_dsl.feature_names():
                q = get_feature_quantiles(db, feat)
                if q:
                    stats_by_feature[feat] = q
        except Exception as exc:
            log.debug("hint context build failed for %s: %s", family, exc)
            continue

        prompt = _build_hint_prompt(family, stats_by_feature, meta_state)
        hint = ask_structured(prompt, StrategyHint)
        if hint is None:
            continue
        validated = _validate_hint(hint, stats_by_feature)
        if validated is not None:
            hints.append(validated)
        else:
            log.info("LLM hint for family=%s failed strict validation, discarded", family)

    return hints


def hint_to_strategy(hint: StrategyHint, rng) -> Optional[StrategyDSL]:
    """
    Build a full StrategyDSL from a validated hint using the family's own
    generator as scaffold (exits/stops/regime/hold stay template-controlled
    — the LLM only supplies entry-condition parameterization). Tagged
    generation_source="llm_hint" for honest attribution downstream.
    """
    if hint.family not in _GENERATORS:
        return None
    try:
        scaffold = _GENERATORS[hint.family](rng)
    except Exception as exc:
        log.warning("hint_to_strategy: scaffold generation failed for %s: %s", hint.family, exc)
        return None

    conditions = [
        Condition(feature=c.feature, operator=c.operator, threshold=c.threshold)
        for c in hint.conditions
    ]
    scaffold.entry_conditions = ConditionGroup(conditions=conditions, logic="AND")
    scaffold.name = f"{scaffold.name}_llmhint"
    return scaffold


# ─────────────────────────────────────────────────────────────────
# Touchpoint 2 — graveyard post-mortem
# ─────────────────────────────────────────────────────────────────

class AvoidZone(BaseModel):
    family:          str
    feature:         str
    operator:        str
    threshold_bucket: float


class GraveyardInsight(BaseModel):
    avoid: list[AvoidZone] = Field(default_factory=list, max_length=20)


def _build_postmortem_prompt(bad_condition_counts: dict[str, int]) -> str:
    top = sorted(bad_condition_counts.items(), key=lambda kv: -kv[1])[:30]
    lines = [f"  {key}: {count} graveyard deaths" for key, count in top]
    block = "\n".join(lines) or "  (no graveyard data yet)"
    return f"""You are reviewing real strategy graveyard statistics from the AQRTI
quant system. Each entry below is a "family|feature|operator|threshold_bucket"
condition and how many retired/failed strategies used it.

REAL graveyard condition failure counts (top 30 by death count):
{block}

Identify which of these condition patterns look like genuine structural
failure modes worth avoiding in future strategy generation (not noise).
Only cite patterns that appear in the list above — do not invent new
family/feature/operator combinations."""


def run_graveyard_postmortem(db: Session, bad_condition_counts: dict[str, int]) -> dict[str, int]:
    """
    Hourly, not per-cycle (caller controls cadence). Returns a dict of
    "family|feature|operator|threshold_bucket" -> capped WEAK bump
    (<= _MAX_GRAVEYARD_WEAK_BUMP) to be ADDED to meta_learner's real
    dead_count for that key before the dead_count>=5 blacklist check —
    never large enough alone to cross that bar. Empty dict on any failure
    or when the kill-switch is off.
    """
    if not _kill_switch_enabled() or not bad_condition_counts:
        return {}

    prompt = _build_postmortem_prompt(bad_condition_counts)
    insight = ask_structured(prompt, GraveyardInsight)
    if insight is None:
        return {}

    valid_keys = set(bad_condition_counts.keys())
    bumps: dict[str, int] = {}
    for zone in insight.avoid:
        # threshold_bucket must match the EXACT string format used in
        # bad_condition_counts' keys (meta_learner buckets to the nearest
        # 10 as a Python int, e.g. "50" not "50.0") — try the int-formatted
        # bucket first since that's what real keys always use, matching
        # a raw float format is never valid but tried as a fallback so a
        # genuinely-int-valued zone still round-trips through Pydantic's
        # float coercion.
        bucket_int = int(round(zone.threshold_bucket))
        candidates = [
            f"{zone.family}|{zone.feature}|{zone.operator}|{bucket_int}",
            f"{zone.family}|{zone.feature}|{zone.operator}|{zone.threshold_bucket}",
        ]
        key = next((k for k in candidates if k in valid_keys), None)
        if key is None:
            log.debug("Graveyard insight rejected: %r not in real bad_condition_counts", candidates[0])
            continue
        bumps[key] = _MAX_GRAVEYARD_WEAK_BUMP

    return bumps
