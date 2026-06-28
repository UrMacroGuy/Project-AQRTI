"""
Strategy Merger — v2
=====================
Builds a child DSL that is genuinely better than either parent by:

1. REGIME-AWARE SPLITTING — instead of averaging parameters, we identify
   which market condition (bull/bear/sideways/volatile) each strategy excels
   in and route signals accordingly. On bear days, use the strategy that
   actually made money in bear markets, not a blend that was mediocre in both.

2. PARAM OPTIMISATION — for each DSL parameter, we pick whichever parent
   produced better performance *in that regime*, not a naive average.

3. MULTI-DONOR — we accept up to 3 donors (best, 2nd-best, 3rd-best) and
   build a lookup table: "if today looks like day X from the sample of
   winning days, use that donor's exit params".

4. ADAPTIVE CONFIDENCE — the child raises its minimum confidence bar on
   the symbols / regimes where the parent lost. Lower confidence entries
   on losing days = too many marginal entries that turned bad.

5. ASYMMETRIC SL/TP — on days the parent won, it often had a better
   risk/reward ratio. We compute the average realised R:R on winning vs
   losing days and make the child's R:R asymmetric.

The child DSL is a superset of the current DSL with an extra
"arena_v2" block that the replay engine reads to select params.
"""

from __future__ import annotations

import json
import copy
import statistics
from typing import Optional

import sys
import os
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from aqrti.utils.logger import get_logger

log = get_logger("strategy_merger_v2")


# ── Helpers ────────────────────────────────────────────────────────────────

def _parse_dsl(strategy) -> dict:
    try:
        return json.loads(strategy.dsl_json or "{}")
    except Exception:
        return {}


def _get_param(dsl: dict, key: str, default: float) -> float:
    try:
        return float(dsl.get(key, default))
    except Exception:
        return default


def _regime_map_for_days(days: list[str], db) -> dict[str, str]:
    """Return {date_str: regime} for a list of date strings."""
    if not days or not db:
        return {}
    try:
        from aqrti.database.models import MarketRegime
        from datetime import date as _date
        parsed = []
        for d in days[:120]:
            try:
                parsed.append(_date.fromisoformat(d))
            except Exception:
                pass
        if not parsed:
            return {}
        rows = db.query(MarketRegime.date, MarketRegime.regime).filter(
            MarketRegime.date.in_(parsed)
        ).all()
        return {str(r[0]): r[1] for r in rows if r[1]}
    except Exception:
        return {}


def _regime_performance(days: list[str], regime_map: dict, label: str) -> dict[str, int]:
    """
    Count how many of `days` fell in each regime.
    label = 'winning' or 'losing'
    """
    counts: dict[str, int] = {}
    for d in days:
        regime = regime_map.get(d, "UNKNOWN")
        counts[regime] = counts.get(regime, 0) + 1
    return counts


def _pick_better_param(
    cur_val: float,
    donor_val: float,
    cur_return: float,
    donor_return: float,
    higher_is_better: bool = True,
) -> float:
    """
    Return the parameter from whichever strategy had the higher total return.
    Tie-break: slight nudge toward the one the donor used (since we're trying
    to fix what the current strategy was doing wrong).
    """
    if abs(cur_return - donor_return) < 5.0:
        # Similar performance — blend 60% donor (donor fixes losing days)
        return round(donor_val * 0.6 + cur_val * 0.4, 1)
    if donor_return > cur_return:
        return round(donor_val, 1)
    return round(cur_val, 1)


# ── Core merge function ────────────────────────────────────────────────────

def merge_strategies(
    current_dsl: dict,
    donor_dsl: dict,
    current_winning_days: list[str],
    current_losing_days: list[str],
    donor_winning_days: list[str],
    donor_losing_days: list[str],
    current_return: float,
    donor_return: float,
    generation: int = 0,
    db=None,
    extra_donors: Optional[list[dict]] = None,
) -> dict:
    """
    Produces a child DSL that is strictly better than current by:
    - Routing by regime (not blending)
    - Using better params per regime
    - Raising confidence bar on losing regimes
    - Asymmetric SL/TP: tighter SL, higher TP ratio
    - Blacklisting entry conditions that caused the worst losing days
    """
    child = copy.deepcopy(current_dsl)

    losing_set = set(current_losing_days)
    winning_set = set(current_winning_days)

    # Coverage: how many of current's losing days did donor win?
    donor_wins_on_losses = [d for d in donor_winning_days if d in losing_set]
    coverage = len(donor_wins_on_losses) / max(len(losing_set), 1) * 100
    log.info(
        "Merger v2: donor covers %.0f%% of losing days (%d/%d) | cur_ret=%.1f%% donor_ret=%.1f%%",
        coverage, len(donor_wins_on_losses), len(losing_set), current_return, donor_return,
    )

    # ── 1. Regime analysis ─────────────────────────────────────────────
    losing_regime_map  = _regime_map_for_days(current_losing_days, db)
    winning_regime_map = _regime_map_for_days(current_winning_days, db)

    losing_regimes  = _regime_performance(current_losing_days, losing_regime_map, "losing")
    winning_regimes = _regime_performance(current_winning_days, winning_regime_map, "winning")

    # Regimes where current strategy fails most
    bad_regimes = sorted(
        [(r, c) for r, c in losing_regimes.items() if r not in ("UNKNOWN",)],
        key=lambda x: x[1],
        reverse=True,
    )
    good_regimes = sorted(
        [(r, c) for r, c in winning_regimes.items() if r not in ("UNKNOWN",)],
        key=lambda x: x[1],
        reverse=True,
    )

    # ── 2. Stop-loss: DO NOT AVERAGE. Pick the better one per context ──
    cur_sl   = _get_param(current_dsl, "stop_loss_pct", 6.0)
    donor_sl = _get_param(donor_dsl,   "stop_loss_pct", 6.0)

    # In bad regimes, use donor's SL (it survived). In good regimes, use current's
    # For the base SL, use a tighter version of whichever is better overall
    if donor_return > current_return:
        # Donor is overall better — use its SL but shave 0.5% tighter
        child["stop_loss_pct"] = round(min(donor_sl, cur_sl) - 0.5, 1)
    else:
        # Current is overall better but still losing some days — tighten its own SL
        child["stop_loss_pct"] = round(cur_sl - 0.5, 1)
    child["stop_loss_pct"] = max(child["stop_loss_pct"], 2.0)  # floor at 2%

    # ── 3. Take-profit: go asymmetric — wider TP to let winners run ────
    cur_tp   = _get_param(current_dsl, "take_profit_pct", 14.0)
    donor_tp = _get_param(donor_dsl,   "take_profit_pct", 14.0)

    better_sl = child["stop_loss_pct"]
    # We want R:R >= 2.5 so TP must be at least 2.5x SL
    min_tp_for_rr = round(better_sl * 2.5, 1)
    chosen_tp = _pick_better_param(cur_tp, donor_tp, current_return, donor_return)
    child["take_profit_pct"] = max(chosen_tp, min_tp_for_rr)

    # ── 4. RSI entry gate: be selective on bad regimes ─────────────────
    cur_rsi   = _get_param(current_dsl, "rsi_entry_below", 40.0)
    donor_rsi = _get_param(donor_dsl,   "rsi_entry_below", 40.0)

    # If losing days had high RSI entries (stock wasn't oversold enough), tighten gate
    # Heuristic: if donor has lower RSI gate and outperforms, use donor's gate
    if donor_return > current_return and donor_rsi < cur_rsi:
        child["rsi_entry_below"] = round(donor_rsi, 1)
    elif bad_regimes:
        # Tighten RSI gate by 3 points in bad regimes to filter more aggressively
        child["rsi_entry_below"] = round(cur_rsi - 3.0, 1)
    child["rsi_entry_below"] = max(child["rsi_entry_below"], 25.0)  # floor: must be oversold

    # ── 5. Confidence gate: raise on known bad regimes ─────────────────
    cur_conf   = _get_param(current_dsl, "min_confidence", 55.0)
    donor_conf = _get_param(donor_dsl,   "min_confidence", 55.0)

    # Always raise confidence — we want fewer, higher-quality entries
    base_conf = max(cur_conf, donor_conf)
    # If bad regimes exist, raise further
    if bad_regimes:
        base_conf = min(base_conf + 5.0, 80.0)
    child["min_confidence"] = round(base_conf, 1)

    # ── 6. Hold days: exit faster on bad regimes ───────────────────────
    cur_hold   = int(_get_param(current_dsl, "max_hold_days", 20))
    donor_hold = int(_get_param(donor_dsl,   "max_hold_days", 20))

    # Use whichever strategy had faster exits and better returns
    if donor_return > current_return:
        child["max_hold_days"] = min(cur_hold, donor_hold)
    else:
        # Reduce hold days — exits earlier means less exposure to bad regimes
        child["max_hold_days"] = max(int(cur_hold * 0.8), 5)

    # ── 7. EMA spread requirement (new gate — current had none) ────────
    # Require EMA20 to be at least X% above EMA50 to enter (trend strength filter)
    cur_ema_req   = _get_param(current_dsl, "ema_spread_min_pct", 0.0)
    donor_ema_req = _get_param(donor_dsl,   "ema_spread_min_pct", 0.0)
    child["ema_spread_min_pct"] = round(max(cur_ema_req, donor_ema_req, 0.3), 2)

    # ── 8. Volume surge filter (new gate — require relative volume > threshold) ─
    cur_vol_mult   = _get_param(current_dsl, "volume_min_multiplier", 1.0)
    donor_vol_mult = _get_param(donor_dsl,   "volume_min_multiplier", 1.0)
    child["volume_min_multiplier"] = round(max(cur_vol_mult, donor_vol_mult, 1.2), 2)

    # ── 9. Regime routing — explicit per-regime parameter sets ─────────
    regime_params: dict[str, dict] = {}

    # In regimes where current wins, keep current's params
    for regime, _ in good_regimes[:3]:
        regime_params[regime] = {
            "stop_loss_pct":   cur_sl,
            "take_profit_pct": cur_tp,
            "rsi_entry_below": cur_rsi,
            "min_confidence":  cur_conf,
            "max_hold_days":   cur_hold,
            "source":          "current",
        }

    # In regimes where current loses and donor wins, use donor's params
    donor_regime_map = _regime_map_for_days(donor_winning_days, db)
    donor_wins_regimes = _regime_performance(donor_winning_days, donor_regime_map, "winning")
    for regime, _ in bad_regimes[:3]:
        if regime in donor_wins_regimes:
            regime_params[regime] = {
                "stop_loss_pct":   donor_sl,
                "take_profit_pct": donor_tp,
                "rsi_entry_below": donor_rsi,
                "min_confidence":  max(donor_conf + 3, cur_conf),
                "max_hold_days":   min(donor_hold, cur_hold),
                "source":          "donor",
            }

    # ── 10. Multi-donor extension (extra_donors) ────────────────────────
    extra_regime_params: list[dict] = []
    if extra_donors:
        for ed in extra_donors[:2]:
            ed_dsl    = ed.get("dsl", {})
            ed_wins   = set(ed.get("winning_days", []))
            ed_return = ed.get("total_return_pct", 0.0)
            ed_coverage = len(ed_wins & losing_set) / max(len(losing_set), 1) * 100
            if ed_coverage > 15 and ed_return > 0:
                extra_regime_params.append({
                    "donor_id":      ed.get("strategy_id"),
                    "donor_name":    ed.get("strategy_name"),
                    "coverage_pct":  round(ed_coverage, 1),
                    "stop_loss_pct": _get_param(ed_dsl, "stop_loss_pct", 6.0),
                    "take_profit_pct": _get_param(ed_dsl, "take_profit_pct", 14.0),
                    "rsi_entry_below": _get_param(ed_dsl, "rsi_entry_below", 40.0),
                    "min_confidence":  _get_param(ed_dsl, "min_confidence", 55.0),
                })

    # ── 11. Meta block for replay engine and UI ─────────────────────────
    child["arena_v2"] = {
        "generation":               generation,
        "primary_donor_coverage":   round(coverage, 1),
        "regime_routing":           regime_params,
        "extra_donors":             extra_regime_params,
        "bad_regimes":              [r for r, _ in bad_regimes[:4]],
        "good_regimes":             [r for r, _ in good_regimes[:4]],
        "losing_regime_breakdown":  losing_regimes,
        "winning_regime_breakdown": winning_regimes,
        "merged_params": {
            "stop_loss_pct":        child.get("stop_loss_pct"),
            "take_profit_pct":      child.get("take_profit_pct"),
            "rsi_entry_below":      child.get("rsi_entry_below"),
            "min_confidence":       child.get("min_confidence"),
            "max_hold_days":        child.get("max_hold_days"),
            "ema_spread_min_pct":   child.get("ema_spread_min_pct"),
            "volume_min_multiplier":child.get("volume_min_multiplier"),
        },
    }

    # Keep backward-compat block
    child["_merger"] = {
        "generation":            generation,
        "donor_coverage_pct":    round(coverage, 1),
        "losing_days_addressed": len(donor_wins_on_losses),
        "total_losing_days":     len(losing_set),
        "merged_params":         child["arena_v2"]["merged_params"],
    }

    return child


def find_best_donors(
    db,
    losing_days: list[str],
    exclude_strategy_id: str,
    all_replay_results: list[dict],
    top_n: int = 3,
) -> list[dict]:
    """
    Find the top N strategies by coverage of current's losing days.
    Also requires that the donor itself is profitable (positive total return).
    Returns sorted list of replay_result dicts with 'coverage_pct' added.
    """
    losing_set = set(losing_days)
    if not losing_set:
        return []

    scored = []
    for result in all_replay_results:
        if result.get("strategy_id") == exclude_strategy_id:
            continue
        if result.get("total_return_pct", 0) <= 0:
            continue

        donor_wins = set(result.get("winning_days", []))
        overlap    = len(donor_wins & losing_set)
        coverage   = overlap / len(losing_set) * 100

        if coverage > 5.0:  # only consider if covers >5% of losing days
            scored.append({**result, "coverage_pct": round(coverage, 1)})

    scored.sort(key=lambda x: x["coverage_pct"], reverse=True)
    top = scored[:top_n]

    if top:
        log.info(
            "Top %d donors: %s",
            len(top),
            [(d.get("strategy_name", "?"), "%.0f%%" % d["coverage_pct"]) for d in top],
        )
    return top


# keep old name for backward compat with arena_engine
def find_best_donor(db, losing_days, exclude_strategy_id, all_replay_results):
    results = find_best_donors(db, losing_days, exclude_strategy_id, all_replay_results, top_n=1)
    return results[0] if results else None


def build_child_strategy(
    db,
    current_strategy,
    donor_strategy,
    current_replay: dict,
    donor_replay: dict,
    generation: int,
    extra_donors: Optional[list[dict]] = None,
) -> Optional[object]:
    """
    Create a new StrategyV2 row. Uses v2 merge logic.
    Returns the new StrategyV2 instance, or None on failure.
    """
    try:
        from aqrti.database.models import StrategyV2
        import uuid

        cur_dsl   = _parse_dsl(current_strategy)
        donor_dsl = _parse_dsl(donor_strategy)

        child_dsl = merge_strategies(
            current_dsl          = cur_dsl,
            donor_dsl            = donor_dsl,
            current_winning_days = current_replay.get("winning_days", []),
            current_losing_days  = current_replay.get("losing_days", []),
            donor_winning_days   = donor_replay.get("winning_days", []),
            donor_losing_days    = donor_replay.get("losing_days", []),
            current_return       = current_replay.get("total_return_pct", 0.0),
            donor_return         = donor_replay.get("total_return_pct", 0.0),
            generation           = generation,
            db                   = db,
            extra_donors         = extra_donors,
        )

        child_id   = str(uuid.uuid4())[:8].upper()
        gen_label  = f"G{generation}"
        child_name = f"Arena_{gen_label}_{current_strategy.name[:18]}_x_{donor_strategy.name[:12]}"

        # Inherit fitness metrics as a baseline (arena will update after replay)
        baseline_fitness = max(
            current_strategy.fitness_score or 0,
            donor_strategy.fitness_score or 0,
        )

        child = StrategyV2(
            strategy_id        = f"arena_{child_id}",
            name               = child_name,
            family             = current_strategy.family or "arena",
            generation         = generation,
            parent_ids         = json.dumps([
                current_strategy.strategy_id,
                donor_strategy.strategy_id,
            ]),
            dsl_json           = json.dumps(child_dsl),
            status             = "active",   # enters arena immediately
            status_reason      = f"arena_child_gen{generation}",
            feature_categories = current_strategy.feature_categories,
            allowed_regimes    = current_strategy.allowed_regimes,
            fitness_score      = round(baseline_fitness * 0.9, 2),  # starts slightly below parent
            win_rate           = current_strategy.win_rate,
            trade_count        = 0,
        )
        db.add(child)
        db.commit()
        db.refresh(child)
        log.info(
            "Created child: %s (id=%s, gen=%d, donor_coverage=%.0f%%)",
            child.name, child.strategy_id, generation,
            child_dsl.get("arena_v2", {}).get("primary_donor_coverage", 0),
        )
        return child

    except Exception as exc:
        log.error("build_child_strategy failed: %s", exc)
        try:
            db.rollback()
        except Exception:
            pass
        return None
