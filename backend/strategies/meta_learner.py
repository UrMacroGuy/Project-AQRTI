"""
Meta-Learning Engine
Reads all available failure signals and converts them into concrete behavioural
adjustments that the generator, mutation engine, and evolution engine apply on
the next cycle.

Signal sources:
  1. StrategyGraveyard   — retired strategies + their lessons
  2. StrategyEvolutionHistory — which operations actually improved fitness
  3. LessonLearned        — cross-system lessons from prediction/model failures
  4. PaperTrade outcomes  — which strategies translated to live profit
  5. Prediction outcomes  — model accuracy by regime / confidence band

Outputs (written to MetaLearningRecord and returned as MetaState dict):
  - family_weights        — adjusted generation weights per family
  - regime_bias           — which regimes to avoid for each family
  - param_priors          — better threshold / stop / hold defaults per family
  - bad_features          — features that consistently appear in failed strategies
  - preferred_operations  — mutation ops ranked by avg fitness delta
  - min_confidence_floor  — dynamic minimum confidence per regime
"""

from __future__ import annotations

import sys, os, json
from collections import defaultdict
from datetime import date, timedelta
from typing import Optional

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from sqlalchemy.orm import Session

from aqrti.database.models import (
    StrategyV2, StrategyGraveyard, StrategyEvolutionHistory,
    LessonLearned, PaperTrade, Prediction, MetaLearningRecord,
    MarketRegime,
)
from aqrti.utils.logger import get_logger

log = get_logger("meta_learner")

# ── Default family weights (baseline from strategy_generator) ─────────
_DEFAULT_FAMILY_WEIGHTS = {
    "momentum":           0.18,
    "mean_reversion":     0.10,
    "breakout":           0.12,
    "sentiment_driven":   0.06,
    "regime_adaptive":    0.08,
    "volume_surge":       0.10,
    "volatility_play":    0.08,
    "hybrid":             0.08,
    "quality_momentum":   0.12,
    "institutional_flow": 0.08,
}

# Caps on how far meta-learning can shift a family weight
MIN_FAMILY_WEIGHT = 0.02
MAX_FAMILY_WEIGHT = 0.35

# ── Helpers ───────────────────────────────────────────────────────────

def _safe_json(s, default=None):
    if default is None:
        default = []
    try:
        return json.loads(s) if s else default
    except Exception:
        return default


def _current_regime(db: Session) -> str:
    row = db.query(MarketRegime.regime).order_by(MarketRegime.date.desc()).first()
    return row[0] if row else "BULL"


# Sample-size floor below which a signal is considered too thin to act on at
# full strength. Below this floor, adjustment magnitude is shrunk toward
# neutral (multiplier 1.0) rather than either fully applied or hard-gated
# off — a 1-death "family" and a 200-death family both used to get the same
# suppression multiplier off a ratio alone; this dampens the small-sample
# case proportionally instead. Applies to family-mortality suppression,
# mutation-op ranking, and regime confidence-floor shifts — the three
# mechanisms in this file that previously had NO sample-size gate at all.
MIN_CONFIDENT_SAMPLE = 10


def _shrink_toward_neutral(multiplier: float, n: int, neutral: float = 1.0,
                          min_n: int = MIN_CONFIDENT_SAMPLE) -> float:
    """
    Shrinkage estimator: at n=0 the adjustment has no effect (returns
    `neutral`); at n>=min_n the full `multiplier` is applied; in between,
    linearly interpolate. This stops 1-2 early observations (a single dead
    strategy, one lucky mutation) from swinging a weight/floor to its
    fully-adjusted value — the same one bad or good roll gets diluted until
    enough evidence accumulates.
    """
    if n <= 0:
        return neutral
    weight = min(n / min_n, 1.0)
    return neutral + (multiplier - neutral) * weight


# ═════════════════════════════════════════════════════════════════════
# SIGNAL EXTRACTION
# ═════════════════════════════════════════════════════════════════════

def _extract_graveyard_signals(db: Session, days: int = 90) -> dict:
    """
    Analyse the graveyard: which families die most, in which regimes,
    with which features.  Returns per-family failure counts and patterns.
    """
    cutoff = date.today() - timedelta(days=days)
    dead = db.query(StrategyGraveyard).all()

    family_deaths:        defaultdict[str, int]         = defaultdict(int)
    family_fitness_avg:   defaultdict[str, list[float]] = defaultdict(list)
    regime_deaths:        defaultdict[str, int]         = defaultdict(int)
    bad_feature_counts:   defaultdict[str, int]         = defaultdict(int)
    # Condition-level tracking: (feature, operator, threshold-bucket) triples,
    # not just the feature name — "rsi_14 > 70" and "rsi_14 < 30" used to be
    # lumped into the same bad_feature_counts["rsi_14"] bucket even though
    # they mean opposite things. Threshold is bucketed to the nearest 10 so
    # near-identical failed thresholds still aggregate (else every strategy's
    # slightly-different float would be its own singleton bucket).
    bad_condition_counts: defaultdict[tuple, int]        = defaultdict(int)
    # Family x regime cross-tabulation — the plain regime_deaths /
    # family_mortality aggregations above are each collapsed on the other
    # dimension, so "momentum dies specifically in BEAR" was invisible.
    family_regime_deaths: defaultdict[tuple, int]        = defaultdict(int)
    short_hold_deaths:    int = 0
    total = len(dead)

    for g in dead:
        fam = g.family or "hybrid"
        family_deaths[fam] += 1
        if g.final_fitness is not None:
            family_fitness_avg[fam].append(g.final_fitness)
        reg = g.regime_at_death or "UNKNOWN"
        regime_deaths[reg] += 1
        family_regime_deaths[(fam, reg)] += 1

        # Extract features from DSL of dead strategy
        try:
            dsl = json.loads(g.dsl_json or "{}")
            entry = dsl.get("entry_conditions") or {}
            for cond in (entry.get("conditions") or []):
                if not isinstance(cond, dict):
                    continue
                feat = cond.get("feature")
                if not feat:
                    continue
                bad_feature_counts[feat] += 1
                op  = cond.get("operator", "?")
                thr = cond.get("threshold")
                if isinstance(thr, (int, float)):
                    thr_bucket = round(thr / 10) * 10   # bucket to nearest 10
                    bad_condition_counts[(feat, op, thr_bucket)] += 1
            # Short holding penalty signal
            if (dsl.get("max_holding_days") or 10) < 4:
                short_hold_deaths += 1
        except Exception:
            pass

    # Family mortality rate — families with >30% death share get downweighted
    family_mortality_rate = {}
    for fam, count in family_deaths.items():
        avg_fit = (
            sum(family_fitness_avg[fam]) / len(family_fitness_avg[fam])
            if family_fitness_avg[fam] else 0.0
        )
        family_mortality_rate[fam] = {
            "deaths":        count,
            "death_share":   count / total if total else 0.0,
            "avg_dead_fit":  round(avg_fit, 2),
        }

    # Family x regime mortality — which family dies specifically in which
    # regime, as a share of THAT family's total deaths (so a family with few
    # deaths overall doesn't automatically look "regime-concentrated").
    family_regime_mortality = {}
    for (fam, reg), count in family_regime_deaths.items():
        fam_total = family_deaths[fam]
        family_regime_mortality.setdefault(fam, {})[reg] = {
            "deaths": count,
            "share_of_family_deaths": round(count / fam_total, 2) if fam_total else 0.0,
        }

    return {
        "total_dead":              total,
        "family_mortality":        family_mortality_rate,
        "regime_deaths":           dict(regime_deaths),
        "family_regime_mortality": family_regime_mortality,
        "bad_feature_counts":      dict(bad_feature_counts),
        "bad_condition_counts":    {f"{f}|{op}|{thr}": c for (f, op, thr), c in bad_condition_counts.items()},
        "short_hold_deaths":       short_hold_deaths,
    }


def _extract_evolution_signals(db: Session, days: int = 60) -> dict:
    """
    Which mutation/crossover operations improve fitness most reliably?
    Returns ranked operations and per-family best operations.
    """
    cutoff = date.today() - timedelta(days=days)
    rows = (
        db.query(StrategyEvolutionHistory)
        .filter(StrategyEvolutionHistory.evolved_date >= cutoff)
        .all()
    )

    op_deltas:  defaultdict[str, list[float]] = defaultdict(list)
    op_positive: defaultdict[str, int]         = defaultdict(int)
    op_total:    defaultdict[str, int]         = defaultdict(int)

    for r in rows:
        op = (r.operation or "unknown").split(":")[0]
        op_total[op] += 1
        if r.fitness_delta is not None:
            op_deltas[op].append(r.fitness_delta)
            if r.fitness_delta > 0:
                op_positive[op] += 1

    op_stats = {}
    for op in op_total:
        n = op_total[op]
        deltas = op_deltas[op]
        op_stats[op] = {
            "total":         n,
            "positive_pct":  round(op_positive[op] / n * 100, 1) if n else 0,
            "avg_delta":     round(sum(deltas) / len(deltas), 3) if deltas else 0.0,
        }

    # Rank operations by avg_delta descending
    ranked_ops = sorted(
        op_stats.keys(),
        key=lambda op: op_stats[op]["avg_delta"],
        reverse=True,
    )

    return {
        "op_stats":    op_stats,
        "ranked_ops":  ranked_ops,
        "sample_days": days,
        "total_events": len(rows),
    }


def _extract_live_trade_signals(db: Session, days: int = 30) -> dict:
    """
    From closed paper trades: which strategy families generate real profit?
    Returns per-family win rate and avg return.
    """
    cutoff = date.today() - timedelta(days=days)
    closed = (
        db.query(PaperTrade)
        .filter(PaperTrade.is_open == False, PaperTrade.exit_date >= cutoff)
        .all()
    )

    family_trades:  defaultdict[str, list[float]] = defaultdict(list)

    for t in closed:
        # Trace back to strategy — join via strategy_id on the trade
        sid = getattr(t, "strategy_id", None)
        if not sid:
            continue
        strat = db.query(StrategyV2.family).filter(StrategyV2.strategy_id == sid).first()
        fam = strat[0] if strat else "unknown"
        family_trades[fam].append(t.actual_return or 0.0)

    result = {}
    for fam, returns in family_trades.items():
        wins = sum(1 for r in returns if r > 0)
        result[fam] = {
            "trades":   len(returns),
            "win_rate": round(wins / len(returns) * 100, 1),
            "avg_ret":  round(sum(returns) / len(returns), 4),
        }
    return {"family_live_performance": result, "total_closed_trades": len(closed)}


def _extract_prediction_signals(db: Session, days: int = 30) -> dict:
    """
    Model accuracy by regime and confidence band.
    If model accuracy is bad in a regime, lower min_confidence floor for that regime.
    """
    cutoff = date.today() - timedelta(days=days)
    preds = (
        db.query(Prediction)
        .filter(Prediction.date >= cutoff, Prediction.success.isnot(None))
        .all()
    )

    regime_acc:   defaultdict[str, list[int]] = defaultdict(list)
    conf_band_acc: defaultdict[str, list[int]] = defaultdict(list)

    for p in preds:
        regime = getattr(p, "regime", None) or "UNKNOWN"
        regime_acc[regime].append(1 if p.success else 0)
        conf = p.confidence or 0
        band = "high" if conf >= 75 else ("med" if conf >= 60 else "low")
        conf_band_acc[band].append(1 if p.success else 0)

    regime_win_rate = {}
    regime_sample_n = {}
    for reg, outcomes in regime_acc.items():
        if outcomes:
            regime_win_rate[reg] = round(sum(outcomes) / len(outcomes) * 100, 1)
            regime_sample_n[reg] = len(outcomes)

    conf_win_rate = {}
    for band, outcomes in conf_band_acc.items():
        if outcomes:
            conf_win_rate[band] = round(sum(outcomes) / len(outcomes) * 100, 1)

    return {
        "regime_win_rate":    regime_win_rate,
        "regime_sample_n":    regime_sample_n,
        "conf_band_win_rate": conf_win_rate,
        "total_evaluated":    len(preds),
    }


def _extract_alive_signals(db: Session) -> dict:
    """
    Which families and parameter ranges characterise the BEST alive strategies?
    Used to pull generation toward what's working.
    """
    top = (
        db.query(StrategyV2)
        .filter(
            StrategyV2.fitness_score >= 40,
            StrategyV2.trade_count >= 20,   # raised 8→20: avoid noise from minimal-trade strategies
            StrategyV2.status.in_(["promoted", "active", "shadow"]),
        )
        .order_by(StrategyV2.fitness_score.desc())
        .limit(200)
        .all()
    )

    family_fitness: defaultdict[str, list[float]] = defaultdict(list)
    family_hold:    defaultdict[str, list[float]] = defaultdict(list)
    family_sl:      defaultdict[str, list[float]] = defaultdict(list)
    family_tp:      defaultdict[str, list[float]] = defaultdict(list)
    family_conf:    defaultdict[str, list[float]] = defaultdict(list)
    good_features:  defaultdict[str, int]         = defaultdict(int)
    good_condition_counts: defaultdict[tuple, int] = defaultdict(int)

    for s in top:
        fam = s.family or "hybrid"
        if s.fitness_score:
            family_fitness[fam].append(s.fitness_score)
        try:
            dsl = json.loads(s.dsl_json or "{}")
            if dsl.get("max_holding_days"):
                family_hold[fam].append(dsl["max_holding_days"])
            if dsl.get("stop_loss_pct"):
                family_sl[fam].append(abs(dsl["stop_loss_pct"]))
            if dsl.get("take_profit_pct"):
                family_tp[fam].append(dsl["take_profit_pct"])
            if dsl.get("min_confidence"):
                family_conf[fam].append(dsl["min_confidence"])
            entry = dsl.get("entry_conditions") or {}
            for cond in (entry.get("conditions") or []):
                if not isinstance(cond, dict):
                    continue
                feat = cond.get("feature")
                if not feat:
                    continue
                good_features[feat] += 1
                op  = cond.get("operator", "?")
                thr = cond.get("threshold")
                if isinstance(thr, (int, float)):
                    thr_bucket = round(thr / 10) * 10
                    good_condition_counts[(feat, op, thr_bucket)] += 1
        except Exception:
            pass

    param_priors = {}
    for fam in family_fitness:
        scores = family_fitness[fam]
        holds  = family_hold[fam]
        sls    = family_sl[fam]
        tps    = family_tp[fam]
        confs  = family_conf[fam]
        param_priors[fam] = {
            "avg_fitness":  round(sum(scores) / len(scores), 2),
            "count":        len(scores),
            "avg_hold":     round(sum(holds) / len(holds), 1)  if holds  else None,
            "avg_sl_abs":   round(sum(sls) / len(sls), 2)      if sls    else None,
            "avg_tp":       round(sum(tps) / len(tps), 2)      if tps    else None,
            "avg_conf":     round(sum(confs) / len(confs), 1)  if confs  else None,
        }

    return {
        "param_priors":         param_priors,
        "good_features":        dict(good_features),
        "good_condition_counts": {f"{f}|{op}|{thr}": c for (f, op, thr), c in good_condition_counts.items()},
        "top_count":            len(top),
    }


# ═════════════════════════════════════════════════════════════════════
# META-STATE COMPUTATION
# ═════════════════════════════════════════════════════════════════════

def compute_meta_state(db: Session) -> dict:
    """
    Aggregate all signal sources into a single MetaState dict.
    This is the only function the generator / mutation engine calls.
    """
    log.info("Computing meta-learning state from all signal sources...")

    grave    = _extract_graveyard_signals(db)
    evo      = _extract_evolution_signals(db)
    live     = _extract_live_trade_signals(db)
    preds    = _extract_prediction_signals(db)
    alive    = _extract_alive_signals(db)
    regime   = _current_regime(db)

    # ── 1. Adjust family generation weights ──────────────────────
    weights = dict(_DEFAULT_FAMILY_WEIGHTS)

    for fam, stats in grave["family_mortality"].items():
        if fam not in weights:
            continue
        death_share = stats["death_share"]
        avg_dead    = stats["avg_dead_fit"]
        n_deaths    = stats["deaths"]
        # Graduated suppression: the more a family dies, the harder it gets
        # suppressed. Raw multiplier is computed first, then shrunk toward
        # 1.0 (no-op) based on n_deaths — previously a single dead strategy
        # (n=1) with a small total graveyard could hit death_share>0.35 and
        # get the full x0.25 suppression off one data point.
        raw_mult = 1.0
        if death_share > 0.35 and avg_dead < 15:
            raw_mult = 0.25
            log.info("Meta: suppressing %s toward x%.2f (death_share=%.0f%% avg_dead=%.1f, n=%d)",
                     fam, raw_mult, death_share * 100, avg_dead, n_deaths)
        elif death_share > 0.25 and avg_dead < 25:
            raw_mult = 0.45
        elif death_share > 0.15:
            raw_mult = 0.65
        mult = _shrink_toward_neutral(raw_mult, n_deaths)
        weights[fam] = max(weights[fam] * mult, MIN_FAMILY_WEIGHT)

    # Boost families with strong live performance (real-world edge)
    live_perf = live.get("family_live_performance", {})
    for fam, lp in live_perf.items():
        if fam not in weights:
            continue
        if lp["win_rate"] >= 60 and lp["trades"] >= 5:
            weights[fam] = min(weights[fam] * 1.5, MAX_FAMILY_WEIGHT)  # strong live signal → big boost
            log.info("Meta: boosting %s (live win_rate=%.1f%% on %d trades)", fam, lp["win_rate"], lp["trades"])
        elif lp["win_rate"] >= 55 and lp["trades"] >= 5:
            weights[fam] = min(weights[fam] * 1.25, MAX_FAMILY_WEIGHT)
        elif lp["win_rate"] < 40 and lp["trades"] >= 5:
            weights[fam] = max(weights[fam] * 0.4, MIN_FAMILY_WEIGHT)  # live failure → suppress hard

    # Boost families where alive top-performers cluster — they know something
    for fam, priors in alive["param_priors"].items():
        if fam not in weights:
            continue
        if priors["avg_fitness"] >= 60 and priors["count"] >= 5:
            weights[fam] = min(weights[fam] * 1.3, MAX_FAMILY_WEIGHT)
        elif priors["avg_fitness"] >= 50 and priors["count"] >= 5:
            weights[fam] = min(weights[fam] * 1.15, MAX_FAMILY_WEIGHT)

    # Renormalise
    total_w = sum(weights.values())
    weights = {f: round(w / total_w, 4) for f, w in weights.items()}

    # ── 2. Identify bad features (in dead strategies, rarely in top) ─
    bad_feat_raw   = grave["bad_feature_counts"]
    good_feat_raw  = alive["good_features"]
    bad_features   = []
    for feat, dead_count in bad_feat_raw.items():
        good_count = good_feat_raw.get(feat, 0)
        if dead_count >= 10 and good_count < dead_count * 0.3:
            bad_features.append(feat)

    # ── 2a. Condition-level bad list — (feature, operator, threshold-bucket)
    # triples, not just the feature name. "rsi_14 > 70" failing and
    # "rsi_14 < 30" succeeding are now distinguishable instead of both
    # incrementing the same bad_feature_counts["rsi_14"] bucket.
    bad_cond_raw  = grave["bad_condition_counts"]
    good_cond_raw = alive["good_condition_counts"]
    bad_conditions = []
    for key, dead_count in bad_cond_raw.items():
        good_count = good_cond_raw.get(key, 0)
        if dead_count >= 5 and good_count < dead_count * 0.3:
            bad_conditions.append(key)   # "feature|operator|threshold_bucket"

    # ── 2b. Build graveyard zones — dead (family, param) clusters across
    # SL, TP, hold-days AND confidence, not just stop_loss_pct. The old
    # single-dimension check meant two structurally-near-identical failed
    # strategies differing only in TP or hold-days (not SL) were invisible
    # to this avoidance mechanism and kept getting regenerated.
    graveyard_zones = []
    for g in db.query(StrategyGraveyard).all():
        try:
            dsl = json.loads(g.dsl_json or "{}")
            if not g.family:
                continue
            zone = {"family": g.family}
            if dsl.get("stop_loss_pct") is not None:
                zone["stop_loss_pct"] = dsl["stop_loss_pct"]
            if dsl.get("take_profit_pct") is not None:
                zone["take_profit_pct"] = dsl["take_profit_pct"]
            if dsl.get("max_holding_days") is not None:
                zone["max_holding_days"] = dsl["max_holding_days"]
            if dsl.get("min_confidence") is not None:
                zone["min_confidence"] = dsl["min_confidence"]
            if len(zone) > 1:   # more than just "family"
                graveyard_zones.append(zone)
        except Exception:
            pass

    # ── 3. Rank mutation operations — shrunk toward neutral (no reorder
    # bonus) for ops with too few observed events, so one lucky mutation
    # can't dominate the op pool (mutation_engine.py awards extra pool slots
    # to the top-3 ranked ops based on avg_delta alone, previously with no
    # sample-size check whatsoever).
    op_stats = dict(evo.get("op_stats", {}))
    for op, stats in op_stats.items():
        stats["avg_delta_shrunk"] = _shrink_toward_neutral(
            stats["avg_delta"], stats["total"], neutral=0.0
        )
    ranked_ops = sorted(op_stats.keys(), key=lambda op: op_stats[op]["avg_delta_shrunk"], reverse=True)

    # ── 4. Dynamic confidence floor per regime — shrunk toward the neutral
    # 55.0 floor when a regime has few evaluated predictions, so a regime
    # with e.g. 2 predictions and a 0%/100% win rate doesn't swing the floor
    # to its extreme value off pure noise.
    regime_win = preds.get("regime_win_rate", {})
    regime_sample_n = preds.get("regime_sample_n", {})
    conf_floor_by_regime = {}
    for reg, wr in regime_win.items():
        n = regime_sample_n.get(reg, 0)
        if wr < 50:
            raw_floor = 68.0
        elif wr >= 65:
            raw_floor = 52.0
        else:
            raw_floor = 58.0
        conf_floor_by_regime[reg] = round(_shrink_toward_neutral(raw_floor, n, neutral=55.0), 1)
    current_conf_floor = conf_floor_by_regime.get(regime, 55.0)

    # ── 5. Regime-family avoidance — now genuinely family x regime, not two
    # separately-collapsed aggregations. A family whose deaths concentrate
    # (>=50% share) in one regime, with enough deaths to trust the signal,
    # is flagged so the generator can bias that family away from that regime
    # (allowed_regimes) rather than just the whole-population "most deadly
    # regime" scalar that ignored which family was dying there.
    regime_deaths = grave["regime_deaths"]
    most_deadly_regime = max(regime_deaths, key=regime_deaths.get) if regime_deaths else None
    family_regime_avoid = {}
    for fam, regs in grave.get("family_regime_mortality", {}).items():
        for reg, stats in regs.items():
            if stats["deaths"] >= 5 and stats["share_of_family_deaths"] >= 0.5:
                family_regime_avoid.setdefault(fam, []).append(reg)

    # ── 6. Param priors — now genuinely consumed (see generation ranges
    # below), not just returned for display. Families with a confident
    # (count>=5) alive-strategy sample bias new candidates' default SL/TP/
    # hold-days/confidence toward what's actually working, instead of the
    # generator's fixed hardcoded per-family ranges regardless of evidence.
    param_priors = alive["param_priors"]

    meta_state = {
        "computed_at":           str(date.today()),
        "current_regime":        regime,
        "family_weights":        weights,
        "bad_features":          bad_features,
        "bad_conditions":        bad_conditions,
        "graveyard_zones":       graveyard_zones,
        "family_regime_avoid":   family_regime_avoid,
        "ranked_mutation_ops":   ranked_ops,
        "mutation_op_stats":     op_stats,
        "current_conf_floor":    current_conf_floor,
        "conf_floor_by_regime":  conf_floor_by_regime,
        "most_deadly_regime":    most_deadly_regime,
        "param_priors":          param_priors,
        "live_family_perf":      live_perf,
        "graveyard_total":       grave["total_dead"],
        "short_hold_deaths":     grave["short_hold_deaths"],
        "prediction_regime_acc": regime_win,
        "prediction_conf_acc":   preds.get("conf_band_win_rate", {}),
        "top_alive_count":       alive["top_count"],
    }

    log.info(
        "Meta-state: regime=%s conf_floor=%.1f bad_features=%d ranked_ops=%d",
        regime, current_conf_floor, len(bad_features), len(ranked_ops),
    )
    return meta_state


# ═════════════════════════════════════════════════════════════════════
# PERSIST META-LEARNING RECORDS
# ═════════════════════════════════════════════════════════════════════

def persist_meta_insights(db: Session, meta_state: dict) -> int:
    """
    Write key insights from meta_state as MetaLearningRecord rows
    so the UI can display what the system learned.
    Returns count written.
    """
    written = 0
    today = date.today()

    def _write(insight_type: str, title: str, desc: str, evidence: dict,
                failure_rate: float | None, severity: str):
        nonlocal written
        rec = MetaLearningRecord(
            insight_type   = insight_type,
            title          = title,
            description    = desc,
            evidence_json  = json.dumps(evidence),
            failure_rate   = failure_rate,
            severity       = severity,
        )
        db.add(rec)
        written += 1

    # Family weight shifts
    default_w = _DEFAULT_FAMILY_WEIGHTS
    for fam, w in meta_state["family_weights"].items():
        orig = default_w.get(fam, 0.1)
        if abs(w - orig) / orig > 0.15:  # >15% change
            direction = "boosted" if w > orig else "downweighted"
            severity = "high" if abs(w - orig) / orig > 0.4 else "medium"
            _write(
                "family_weight_shift",
                f"Family {fam} {direction}: {orig:.2f} → {w:.2f}",
                (f"Meta-learning {direction} generation weight for '{fam}' family "
                 f"based on live performance and graveyard analysis."),
                {"family": fam, "old_weight": orig, "new_weight": w},
                None, severity,
            )

    # Bad features
    if meta_state["bad_features"]:
        _write(
            "bad_features",
            f"{len(meta_state['bad_features'])} features identified as high-failure indicators",
            (f"Features {meta_state['bad_features'][:5]} appear frequently in retired strategies "
             "but rarely in top performers. Generator will avoid or reduce weight on these."),
            {"bad_features": meta_state["bad_features"]},
            None, "medium",
        )

    # Confidence floor shift
    floor = meta_state["current_conf_floor"]
    if floor != 55.0:
        direction = "raised" if floor > 55 else "lowered"
        _write(
            "confidence_floor",
            f"Min confidence floor {direction} to {floor}% in {meta_state['current_regime']} regime",
            (f"Based on model win rate in {meta_state['current_regime']} regime, "
             f"confidence floor {direction} to {floor}% to filter noise."),
            {"regime": meta_state["current_regime"], "floor": floor,
             "regime_acc": meta_state["prediction_regime_acc"]},
            None, "low",
        )

    # Best mutation operation
    ranked = meta_state["ranked_mutation_ops"]
    if ranked:
        best_op = ranked[0]
        op_stats = meta_state["mutation_op_stats"].get(best_op, {})
        _write(
            "best_mutation_op",
            f"Top mutation operation: '{best_op}' (avg delta={op_stats.get('avg_delta', 0):.3f})",
            (f"Over the last 60 days, '{best_op}' produced the highest average fitness improvement "
             f"({op_stats.get('positive_pct', 0):.1f}% positive outcomes). "
             "Mutation engine will prefer this operation."),
            {"op": best_op, "stats": op_stats},
            None, "low",
        )

    db.commit()
    log.info("Persisted %d meta-learning insights", written)
    return written


# ═════════════════════════════════════════════════════════════════════
# PUBLIC API
# ═════════════════════════════════════════════════════════════════════

def run_meta_learning(db: Session) -> dict:
    """
    Full meta-learning cycle.  Call after each evolution cycle or daily.
    Returns the MetaState dict — pass this to adaptive_generator and
    adaptive_mutation for the next generation.
    """
    meta_state = compute_meta_state(db)
    n_insights = persist_meta_insights(db, meta_state)
    meta_state["insights_written"] = n_insights
    log.info("Meta-learning cycle complete: %d insights written", n_insights)
    return meta_state


def get_latest_meta_state(db: Session) -> dict:
    """
    Compute and return the current MetaState.

    Always recomputes fresh from live signal sources (graveyard, evolution
    history, paper trades, predictions, alive population) — the underlying
    queries are cheap aggregations, not a heavy model fit, so caching adds
    complexity without a real performance win. A previous version of this
    function implied it returned a cached state from a prior
    MetaLearningRecord when one existed "from today", but both branches
    called compute_meta_state() either directly or via run_meta_learning()
    (which also calls it) — the caching described in the docstring never
    actually happened. This version does the same work with an honest
    docstring instead of dead conditional logic.

    Use run_meta_learning() instead of this function when you also want the
    insights persisted to MetaLearningRecord for UI display; use this one
    for a read-only state fetch (e.g. from an API route).
    """
    return compute_meta_state(db)
