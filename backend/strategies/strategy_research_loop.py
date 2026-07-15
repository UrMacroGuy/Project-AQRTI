"""
Phase 6M — Daily Strategy Research Loop

Orchestrates the complete daily strategy research process in sequence:

  Step 1: Generate new candidates (strategy_generator)
  Step 2: Backtest all unscored strategies (strategy_backtester)
  Step 3: Score all strategies (fitness_engine)
  Step 4: Lifecycle sweep — promote winners, retire losers (strategy_lifecycle)
  Step 5: Evolve population — mutation + crossover (evolution_engine)
  Step 6: Store graveyard knowledge (graveyard_manager)
  Step 7: Run full research reports (research_engine)
  Step 8: Record population snapshot (strategy_memory)

This is called by APScheduler Step 8 in the daily pipeline.
No trades executed. No automatic model updates. Human approval required for 'active'.
"""

from __future__ import annotations

import sys, os
from datetime import date, timedelta
from typing import Optional

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from aqrti.database.session import get_db_session
from aqrti.utils.logger import get_logger
from strategies.strategy_generator import run_generation_cycle
from strategies.strategy_backtester import backtest_and_update, _preload_prices, get_backtest_universe
from strategies.fitness_engine import score_all_strategies
from strategies.strategy_lifecycle import run_lifecycle_sweep
from strategies.evolution_engine import evolve_population
from strategies.graveyard_manager import failure_pattern_analysis
from strategies.research_engine import run_full_research
from strategies.strategy_memory import record_knowledge_snapshot
from aqrti.database.models import StrategyV2

log = get_logger("strategy_research_loop")


def _backtest_unscored(db, max_stocks: int = 300) -> dict:
    """Backtest all candidates that have no fitness score yet.
    Selects proportionally across families so no family is starved."""
    import random as _random
    from sqlalchemy import func as _func

    # Count unscored per family
    family_counts = dict(
        db.query(StrategyV2.family, _func.count())
        .filter(
            StrategyV2.fitness_score.is_(None),
            StrategyV2.status.in_(["candidate", "shadow"]),
            StrategyV2.dsl_json.isnot(None),
            StrategyV2.family.isnot(None),
        )
        .group_by(StrategyV2.family)
        .all()
    )

    if not family_counts:
        return {"backtested": 0, "errors": 0, "total_queued": 0}

    # Allocate slots proportionally but give each family at least 1 slot
    total_unscored = sum(family_counts.values())
    per_family_alloc: dict[str, int] = {}
    remaining = max_stocks
    for fam, cnt in sorted(family_counts.items()):
        alloc = max(1, round(max_stocks * cnt / total_unscored))
        alloc = min(alloc, cnt, remaining)
        per_family_alloc[fam] = alloc
        remaining -= alloc
        if remaining <= 0:
            break

    # Fetch per family and shuffle within each
    rows: list = []
    for fam, alloc in per_family_alloc.items():
        fam_rows = (
            db.query(StrategyV2)
            .filter(
                StrategyV2.fitness_score.is_(None),
                StrategyV2.status.in_(["candidate", "shadow"]),
                StrategyV2.dsl_json.isnot(None),
                StrategyV2.family == fam,
            )
            .limit(alloc)
            .all()
        )
        rows.extend(fam_rows)

    _random.shuffle(rows)
    tested = 0
    errors = 0
    end_date   = date.today()
    # 5 years — MUST match the population/evolution window so every strategy is
    # scored on the same data (mixed windows corrupt fitness comparison).
    start_date = end_date - timedelta(days=1825)

    # Pre-load prices + feature vectors ONCE for the whole batch instead of once
    # per strategy (up to 100/cycle) — backtest_strategy() already supports
    # these shared caches, this loop just wasn't threading them through.
    universe = get_backtest_universe(db)
    shared_price_data = _preload_prices(db, universe, start_date, end_date)

    from aqrti.database.models import FeatureValue
    shared_feature_cache: dict = {}
    feat_rows = (
        db.query(FeatureValue.symbol, FeatureValue.date, FeatureValue.feature_name, FeatureValue.value)
        .filter(
            FeatureValue.symbol.in_(universe),
            FeatureValue.date >= start_date,
            FeatureValue.date <= end_date,
            FeatureValue.version == 1,
        )
        .all()
    )
    for sym, dt, fname, fval in feat_rows:
        shared_feature_cache.setdefault((sym, dt), {})[fname] = fval

    shared_signal_cache: dict = {}

    for row in rows:
        try:
            from strategies.strategy_dsl import StrategyDSL
            from strategies.strategy_generator import _passes_prescreen
            dsl = StrategyDSL.from_json(row.dsl_json)

            # Fast structural pre-screen before expensive backtest
            ok, reason = _passes_prescreen(dsl, bad_features=set())
            if not ok:
                log.debug("Pre-screen skip %s: %s", row.strategy_id, reason)
                # Mark it retired immediately — no point backtesting
                row.status        = "retired"
                row.status_reason = f"prescreen:{reason}"
                db.commit()
                errors += 1
                continue

            # Stored-row re-backtest: pass the row's stored ID — dsl was
            # rebuilt from dsl_json, and recomputing strategy_id() (now a
            # full-genome hash) would mint a different ID -> duplicate row.
            backtest_and_update(db, dsl, start_date=start_date, end_date=end_date,
                                universe=universe,
                                strategy_id_override=row.strategy_id,
                                shared_price_data=shared_price_data,
                                shared_feature_cache=shared_feature_cache,
                                shared_signal_cache=shared_signal_cache)
            tested += 1
        except Exception as exc:
            log.warning("Backtest failed for %s: %s", row.strategy_id, exc)
            errors += 1

    return {"backtested": tested, "errors": errors, "total_queued": len(rows)}


def _apply_live_performance_adjustment(db) -> dict:
    """
    Read StrategyPerformance (live paper trading results) and adjust fitness scores.

    Logic:
    - Strategy with ≥5 live closed trades AND live win_rate > backtest win_rate + 5pp
      → fitness boosted by up to +5 points (strong live evidence)
    - Strategy with ≥5 live closed trades AND live win_rate < backtest win_rate - 15pp
      → fitness penalised by up to -10 points (live divergence)

    This feeds real paper trading results back into the genetic algorithm so
    evolution gravitates toward strategies that actually work, not just backtest well.
    """
    from aqrti.database.models import StrategyPerformance
    from sqlalchemy import func

    boosted = 0
    penalised = 0

    # Aggregate live trades per strategy
    perf_rows = (
        db.query(
            StrategyPerformance.strategy_id,
            func.sum(StrategyPerformance.trades_closed).label("total_trades"),
            func.sum(StrategyPerformance.win_count).label("total_wins"),
            func.sum(StrategyPerformance.loss_count).label("total_losses"),
        )
        .group_by(StrategyPerformance.strategy_id)
        .all()
    )

    for row in perf_rows:
        total = (row.total_trades or 0)
        if total < 5:
            continue

        wins = row.total_wins or 0
        live_wr = wins / total * 100 if total > 0 else 0.0

        strat = db.query(StrategyV2).filter_by(strategy_id=row.strategy_id).first()
        if not strat or strat.fitness_score is None:
            continue

        bt_wr = strat.win_rate or 50.0
        gap   = live_wr - bt_wr

        old_fitness = strat.fitness_score
        if gap > 5.0:
            # Live outperforming — boost up to +5 pts proportional to gap
            boost = min(gap * 0.5, 5.0)
            strat.fitness_score = min(100.0, old_fitness + boost)
            boosted += 1
        elif gap < -15.0:
            # Live significantly underperforming — penalise up to -10 pts
            penalty = min(abs(gap) * 0.4, 10.0)
            strat.fitness_score = max(0.0, old_fitness - penalty)
            penalised += 1

    db.commit()
    return {"boosted": boosted, "penalised": penalised, "strategies_evaluated": len(perf_rows)}


def _apply_arena_champion_boost(db) -> dict:
    """
    Strategies that became arena champions get a fitness boost (+8 pts) so the
    genetic algorithm preferentially evolves their parameter family.

    Also boosts all strategies that share the same `family` as any champion
    (sibling boost: +3 pts) — helps the evolution engine rediscover what made
    the champion DSL work without duplicating it exactly.

    Runs after lifecycle and live-performance sweeps so it can compound with them.
    """
    from aqrti.database.models import ArenaRun

    champion_ids = {
        r.strategy_id
        for r in db.query(ArenaRun.strategy_id).filter_by(is_champion=True).all()
    }
    if not champion_ids:
        return {"champion_boost": 0, "sibling_boost": 0}

    champion_families = set()
    direct_boost = 0
    for sid in champion_ids:
        strat = db.query(StrategyV2).filter_by(strategy_id=sid).first()
        if not strat or strat.fitness_score is None:
            continue
        strat.fitness_score = min(100.0, strat.fitness_score + 8.0)
        if strat.family:
            champion_families.add(strat.family)
        direct_boost += 1

    # Sibling boost: same family, not a champion itself
    sibling_boost = 0
    if champion_families:
        siblings = db.query(StrategyV2).filter(
            StrategyV2.family.in_(champion_families),
            StrategyV2.strategy_id.notin_(champion_ids),
            StrategyV2.fitness_score.isnot(None),
        ).all()
        for s in siblings:
            s.fitness_score = min(100.0, s.fitness_score + 3.0)
            sibling_boost += 1

    db.commit()
    return {
        "champion_boost":   direct_boost,
        "sibling_boost":    sibling_boost,
        "champion_families": list(champion_families),
    }


def run_daily_strategy_research(
    generate_n:    int = 50,    # raised 30→50: 50-stock universe → more signal combinations to explore
    evolve_n:      int = 30,    # raised 20→30: more offspring from top parents
    skip_generate: bool = False,
    skip_evolve:   bool = False,
) -> dict:
    """
    Full daily strategy research loop.

    Args:
        generate_n:    how many new candidates to generate
        evolve_n:      how many offspring to create in evolution cycle
        skip_generate: skip generation step (for testing or conservative days)
        skip_evolve:   skip evolution step

    Returns:
        Summary dict of all steps.
    """
    log.info("Daily strategy research loop starting — %s", date.today())
    report = {"date": str(date.today()), "steps": {}}

    # Step 1: Generate new candidates
    if not skip_generate:
        try:
            with get_db_session() as db:
                gen_result = run_generation_cycle(db, n=generate_n, generation=0, use_llm_hints=True)
            report["steps"]["generate"] = gen_result
            log.info("Step 1 — Generated: %d new candidates", gen_result.get("persisted", 0))
        except Exception as exc:
            log.error("Step 1 — Generation failed: %s", exc)
            report["steps"]["generate"] = {"error": str(exc)}
    else:
        report["steps"]["generate"] = {"skipped": True}

    # Step 2: Backtest unscored strategies
    try:
        with get_db_session() as db:
            bt_result = _backtest_unscored(db)
        report["steps"]["backtest"] = bt_result
        log.info("Step 2 — Backtested: %d strategies", bt_result["backtested"])
    except Exception as exc:
        log.error("Step 2 — Backtest sweep failed: %s", exc)
        report["steps"]["backtest"] = {"error": str(exc)}

    # Step 3: Score all strategies
    try:
        with get_db_session() as db:
            score_result = score_all_strategies(db)
        report["steps"]["scoring"] = score_result
        log.info("Step 3 — Scored: %d strategies", score_result.get("scored", 0))
    except Exception as exc:
        log.error("Step 3 — Scoring failed: %s", exc)
        report["steps"]["scoring"] = {"error": str(exc)}

    # Step 4: Lifecycle sweep
    try:
        with get_db_session() as db:
            lifecycle = run_lifecycle_sweep(db)
        report["steps"]["lifecycle"] = lifecycle
        log.info(
            "Step 4 — Lifecycle: promoted=%d retired=%d",
            len(lifecycle.get("promoted", [])),
            len(lifecycle.get("retired", [])),
        )
    except Exception as exc:
        log.error("Step 4 — Lifecycle sweep failed: %s", exc)
        report["steps"]["lifecycle"] = {"error": str(exc)}

    # Step 4B: Apply live performance adjustment to fitness scores
    # Boosts fitness of strategies performing well live, penalises underperformers
    try:
        with get_db_session() as db:
            lp_result = _apply_live_performance_adjustment(db)
        report["steps"]["live_perf_adjust"] = lp_result
        log.info(
            "Step 4B — Live perf adjust: boosted=%d penalised=%d",
            lp_result.get("boosted", 0), lp_result.get("penalised", 0),
        )
    except Exception as exc:
        log.error("Step 4B — Live performance adjustment failed: %s", exc)
        report["steps"]["live_perf_adjust"] = {"error": str(exc)}

    # Step 4C: Arena champion fitness boost
    # Champions get +8 pts; their family siblings get +3 pts so evolution gravitates
    # toward parameter families that actually cleared the champion gates.
    try:
        with get_db_session() as db:
            arena_result = _apply_arena_champion_boost(db)
        report["steps"]["arena_champion_boost"] = arena_result
        log.info(
            "Step 4C — Arena champion boost: direct=%d siblings=%d families=%s",
            arena_result.get("champion_boost", 0),
            arena_result.get("sibling_boost", 0),
            arena_result.get("champion_families", []),
        )
    except Exception as exc:
        log.error("Step 4C — Arena champion boost failed: %s", exc)
        report["steps"]["arena_champion_boost"] = {"error": str(exc)}

    # Step 5: Evolve population
    if not skip_evolve:
        try:
            with get_db_session() as db:
                evo_result = evolve_population(db, n_offspring=evolve_n)
            report["steps"]["evolution"] = evo_result
            log.info(
                "Step 5 — Evolution gen=%s: created=%d",
                evo_result.get("generation", "?"),
                evo_result.get("created", 0),
            )
        except Exception as exc:
            log.error("Step 5 — Evolution failed: %s", exc)
            report["steps"]["evolution"] = {"error": str(exc)}
    else:
        report["steps"]["evolution"] = {"skipped": True}

    # Step 6: Graveyard knowledge
    try:
        with get_db_session() as db:
            patterns = failure_pattern_analysis(db)
        report["steps"]["graveyard"] = patterns
        log.info("Step 6 — Graveyard: total=%d", patterns.get("total", 0))
    except Exception as exc:
        log.error("Step 6 — Graveyard analysis failed: %s", exc)
        report["steps"]["graveyard"] = {"error": str(exc)}

    # Step 7: Research reports
    try:
        with get_db_session() as db:
            research = run_full_research(db)
        report["steps"]["research"] = research
        log.info("Step 7 — Research: %d reports generated", len(research.get("reports", [])))
    except Exception as exc:
        log.error("Step 7 — Research reports failed: %s", exc)
        report["steps"]["research"] = {"error": str(exc)}

    # Step 8: Population snapshot
    try:
        with get_db_session() as db:
            snapshot = record_knowledge_snapshot(db)
        report["steps"]["snapshot"] = snapshot
        log.info(
            "Step 8 — Snapshot: total=%d active=%d avg_fitness=%.1f",
            snapshot.get("total", 0),
            snapshot.get("active_count", 0),
            snapshot.get("avg_fitness", 0),
        )
    except Exception as exc:
        log.error("Step 8 — Snapshot failed: %s", exc)
        report["steps"]["snapshot"] = {"error": str(exc)}

    log.info("Daily strategy research loop complete")
    return report
