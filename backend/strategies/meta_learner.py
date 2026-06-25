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
    short_hold_deaths:    int = 0
    total = len(dead)

    for g in dead:
        fam = g.family or "hybrid"
        family_deaths[fam] += 1
        if g.final_fitness is not None:
            family_fitness_avg[fam].append(g.final_fitness)
        reg = g.regime_at_death or "UNKNOWN"
        regime_deaths[reg] += 1

        # Extract features from DSL of dead strategy
        try:
            dsl = json.loads(g.dsl_json or "{}")
            entry = dsl.get("entry_conditions") or {}
            for cond in (entry.get("conditions") or []):
                feat = cond.get("feature") if isinstance(cond, dict) else None
                if feat:
                    bad_feature_counts[feat] += 1
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

    return {
        "total_dead":         total,
        "family_mortality":   family_mortality_rate,
        "regime_deaths":      dict(regime_deaths),
        "bad_feature_counts": dict(bad_feature_counts),
        "short_hold_deaths":  short_hold_deaths,
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
    for reg, outcomes in regime_acc.items():
        if outcomes:
            regime_win_rate[reg] = round(sum(outcomes) / len(outcomes) * 100, 1)

    conf_win_rate = {}
    for band, outcomes in conf_band_acc.items():
        if outcomes:
            conf_win_rate[band] = round(sum(outcomes) / len(outcomes) * 100, 1)

    return {
        "regime_win_rate":    regime_win_rate,
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
            StrategyV2.trade_count >= 8,
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
    good_features:  defaultdict[str, int]         = defaultdict(int)

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
            entry = dsl.get("entry_conditions") or {}
            for cond in (entry.get("conditions") or []):
                feat = cond.get("feature") if isinstance(cond, dict) else None
                if feat:
                    good_features[feat] += 1
        except Exception:
            pass

    param_priors = {}
    for fam in family_fitness:
        scores = family_fitness[fam]
        holds  = family_hold[fam]
        sls    = family_sl[fam]
        tps    = family_tp[fam]
        param_priors[fam] = {
            "avg_fitness":  round(sum(scores) / len(scores), 2),
            "count":        len(scores),
            "avg_hold":     round(sum(holds) / len(holds), 1)  if holds  else None,
            "avg_sl_abs":   round(sum(sls) / len(sls), 2)      if sls    else None,
            "avg_tp":       round(sum(tps) / len(tps), 2)      if tps    else None,
        }

    return {
        "param_priors":  param_priors,
        "good_features": dict(good_features),
        "top_count":     len(top),
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
        # High death share + low dead fitness = reduce weight
        if death_share > 0.20 and avg_dead < 20:
            weights[fam] = max(weights[fam] * 0.5, MIN_FAMILY_WEIGHT)
            log.info("Meta: downweighting %s (death_share=%.1f%% avg_dead_fit=%.1f)", fam, death_share * 100, avg_dead)
        elif death_share > 0.30:
            weights[fam] = max(weights[fam] * 0.7, MIN_FAMILY_WEIGHT)

    # Boost families with strong live performance
    live_perf = live.get("family_live_performance", {})
    for fam, lp in live_perf.items():
        if fam not in weights:
            continue
        if lp["win_rate"] >= 60 and lp["trades"] >= 5:
            weights[fam] = min(weights[fam] * 1.3, MAX_FAMILY_WEIGHT)
            log.info("Meta: boosting %s (live win_rate=%.1f%%)", fam, lp["win_rate"])
        elif lp["win_rate"] < 40 and lp["trades"] >= 5:
            weights[fam] = max(weights[fam] * 0.6, MIN_FAMILY_WEIGHT)

    # Boost families where alive top-performers are concentrated
    for fam, priors in alive["param_priors"].items():
        if fam not in weights:
            continue
        if priors["avg_fitness"] >= 50 and priors["count"] >= 5:
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

    # ── 3. Rank mutation operations ──────────────────────────────
    ranked_ops = evo.get("ranked_ops", [])

    # ── 4. Dynamic confidence floor per regime ───────────────────
    regime_win = preds.get("regime_win_rate", {})
    conf_floor_by_regime = {}
    for reg, wr in regime_win.items():
        if wr < 50:
            # Model underperforms in this regime — require higher confidence
            conf_floor_by_regime[reg] = 68.0
        elif wr >= 65:
            # Model is reliable — allow lower confidence entry
            conf_floor_by_regime[reg] = 52.0
        else:
            conf_floor_by_regime[reg] = 58.0
    current_conf_floor = conf_floor_by_regime.get(regime, 55.0)

    # ── 5. Regime-family avoidance ────────────────────────────────
    regime_deaths = grave["regime_deaths"]
    most_deadly_regime = max(regime_deaths, key=regime_deaths.get) if regime_deaths else None

    # ── 6. Param priors ─────────────────────────────────────────
    param_priors = alive["param_priors"]

    meta_state = {
        "computed_at":           str(date.today()),
        "current_regime":        regime,
        "family_weights":        weights,
        "bad_features":          bad_features,
        "ranked_mutation_ops":   ranked_ops,
        "mutation_op_stats":     evo.get("op_stats", {}),
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
    Return the most recent MetaState.
    If no recent state exists (first run), compute one on the fly.
    """
    # Check if we have a recent record from today
    today_record = (
        db.query(MetaLearningRecord)
        .filter(MetaLearningRecord.insight_type == "family_weight_shift")
        .order_by(MetaLearningRecord.created_at.desc())
        .first()
    )

    if today_record:
        # Re-compute lightweight state from cached signals
        return compute_meta_state(db)

    # First time — compute fresh
    return run_meta_learning(db)
