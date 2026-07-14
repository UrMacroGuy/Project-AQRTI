"""
Evolution Engine
Orchestrates the full evolutionary cycle:
  1. Select parents from the current population (tournament selection)
  2. Apply crossover + mutation to produce offspring
  3. Backtest offspring
  4. Score offspring
  5. Promote winners, retire losers
  6. Record evolution history

Does NOT deploy strategies automatically.
Human approval remains mandatory before 'active' status.
"""

from __future__ import annotations

import sys, os, json, random, time
from datetime import date, timedelta
from typing import Optional

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from sqlalchemy.orm import Session

from aqrti.database.models import StrategyV2, MarketRegime
from aqrti.utils.logger import get_logger
from strategies.strategy_dsl import StrategyDSL
from strategies.strategy_store import upsert_strategy, save_version, record_evolution_event
from strategies.mutation_engine import mutate
from strategies.crossover_engine import crossover
from strategies.strategy_backtester import backtest_and_update
from strategies.fitness_engine import score_strategy, compute_fitness
from strategies.strategy_lifecycle import run_lifecycle_sweep
from strategies.meta_learner import run_meta_learning, compute_meta_state
from strategies.strategy_generator import _passes_prescreen

log = get_logger("evolution_engine")

TOURNAMENT_SIZE    = 7      # higher selection pressure toward the best
MUTATION_RATE      = 0.65   # 65% mutation, 35% crossover — slightly more exploitation
CROSSOVER_RATE     = 0.35   # crossover: when two good parents exist
MIN_PARENT_FITNESS = 40.0   # lowered 45→40: allows more diverse parents early on
MIN_PARENT_SHARPE  = 0.20   # slightly relaxed while universe is expanding
BACKTEST_DAYS      = 1825   # 5 years — MUST match the population re-backtest window
                            # (backtest_and_update defaults to 5yr); a shorter
                            # window here would score offspring on different data
                            # than their parents, corrupting selection.


def _tournament_select(
    population: list[StrategyV2],
    rng:        random.Random,
    k:          int = TOURNAMENT_SIZE,
) -> StrategyV2:
    """Pick k random candidates, return the one with highest fitness."""
    pool = rng.sample(population, min(k, len(population)))
    return max(pool, key=lambda s: s.fitness_score or 0.0)


def _current_regime(db: Session) -> str:
    row = (
        db.query(MarketRegime.regime)
        .order_by(MarketRegime.date.desc())
        .first()
    )
    return row[0] if row else "BULL"


def _get_next_generation(db: Session) -> int:
    row = db.query(StrategyV2.generation).order_by(StrategyV2.generation.desc()).first()
    return (row[0] or 0) + 1 if row else 1


def evolve_population(
    db:            Session,
    n_offspring:   int = 20,
    seed:          Optional[int] = None,
    backtest_days: int = BACKTEST_DAYS,
    run_meta:      bool = True,
) -> dict:
    """
    Run one evolution cycle: meta-learn → select → reproduce → evaluate → promote/retire.

    Args:
        db:            DB session
        n_offspring:   number of offspring to generate
        seed:          random seed
        backtest_days: how many days to backtest new offspring
        run_meta:      if True, run meta-learning before this cycle and apply results

    Returns:
        Summary dict of the evolution cycle.
    """
    rng       = random.Random(seed)
    regime    = _current_regime(db)
    next_gen  = _get_next_generation(db)

    # ── Run meta-learning before evolution ────────────────────────
    meta_state = None
    meta_insights = 0
    if run_meta:
        try:
            meta_state    = run_meta_learning(db)
            meta_insights = meta_state.get("insights_written", 0)
            log.info(
                "Meta-learning: family_weights adjusted, bad_features=%d, conf_floor=%.1f",
                len(meta_state.get("bad_features", [])),
                meta_state.get("current_conf_floor", 55.0),
            )
        except Exception as exc:
            log.warning("Meta-learning failed, proceeding without: %s", exc)

    # Select parent pool — top tier only, diversified across families.
    # Under honest metrics the absolute-floor pool can be nearly empty, which
    # stalls evolution. Try the strict floor first; if too few qualify, fall
    # back to the best-available real performers (positive Sharpe + enough
    # trades) so we always breed from the top of what exists, never from junk.
    from strategies.promotion_config import MIN_BACKTEST_TRADES
    parents = (
        db.query(StrategyV2)
        .filter(
            StrategyV2.asset_class == "stock",
            StrategyV2.trade_count    >= MIN_BACKTEST_TRADES,
            StrategyV2.fitness_score  >= MIN_PARENT_FITNESS,
            StrategyV2.sharpe         >= MIN_PARENT_SHARPE,
            StrategyV2.dsl_json.isnot(None),
            StrategyV2.family.isnot(None),
        )
        .order_by(StrategyV2.fitness_score.desc())
        .limit(100)
        .all()
    )
    if len(parents) < 20:
        parents = (
            db.query(StrategyV2)
            .filter(
                StrategyV2.asset_class == "stock",
                StrategyV2.trade_count   >= MIN_BACKTEST_TRADES,
                StrategyV2.sharpe        > 0.0,   # positive honest edge, any size
                StrategyV2.dsl_json.isnot(None),
                StrategyV2.family.isnot(None),
            )
            .order_by(StrategyV2.fitness_score.desc())
            .limit(100)
            .all()
        )
        log.info("Parent pool relaxed to best-available (positive-Sharpe) — %d found", len(parents))

    if not parents:
        # Bootstrap case: right after an honest-metrics reset, it's possible for
        # the ENTIRE population to have negative Sharpe (no strategy has proven
        # a real edge yet). Refusing to breed here would stall evolution
        # indefinitely — mutation/crossover would sit idle every cycle until
        # pure-random generation happens to produce a positive-Sharpe seed,
        # which could take a long time across thousands of candidates. Instead,
        # breed from the least-bad, best-fitness strategies that still clear
        # the real trade-count floor (so we're never breeding from small-sample
        # noise) — mutation can still improve on "least negative" the same way
        # it improves on "positive," and this population is temporary: real
        # positive-Sharpe strategies graduate out of this tier automatically
        # the moment they appear.
        parents = (
            db.query(StrategyV2)
            .filter(
                StrategyV2.asset_class == "stock",
                StrategyV2.trade_count   >= MIN_BACKTEST_TRADES,
                StrategyV2.sharpe.isnot(None),
                StrategyV2.dsl_json.isnot(None),
                StrategyV2.family.isnot(None),
            )
            .order_by(StrategyV2.fitness_score.desc())
            .limit(100)
            .all()
        )
        log.warning(
            "No positive-Sharpe parents exist anywhere in the population — "
            "bootstrapping from best-available (least-negative) fitness, %d found",
            len(parents),
        )
    # De-duplicate by family — cap at 10 per family so genetic diversity is maintained
    family_counts: dict[str, int] = {}
    diverse_parents = []
    for p in parents:
        fam = p.family or "hybrid"
        if family_counts.get(fam, 0) < 10:
            diverse_parents.append(p)
            family_counts[fam] = family_counts.get(fam, 0) + 1
    parents = diverse_parents
    log.info(
        "Evolution parent pool: %d strategies across %d families (fitness >= %.1f, sharpe >= %.2f)",
        len(parents), len(family_counts), MIN_PARENT_FITNESS, MIN_PARENT_SHARPE,
    )

    if not parents:
        log.info("No eligible parents found for evolution")
        return {"status": "no_parents", "n_offspring": 0}

    created   = []
    skipped   = 0
    errors    = []

    end_date   = date.today()
    start_date = end_date - timedelta(days=backtest_days)

    bad_features   = set(meta_state.get("bad_features", []))   if meta_state else set()
    bad_conditions = set(meta_state.get("bad_conditions", [])) if meta_state else set()
    prescreen_rejected = 0

    # Slot queue instead of a plain range so a slot that dies to a TRANSIENT
    # "database is locked" (SQLite deferred-transaction upgrade conflict with
    # the concurrent paper-trading/agent writers — busy_timeout cannot save an
    # already-stale read snapshot) gets ONE re-attempt at the back of the
    # queue. Before this, every 5-min evolution cycle silently lost 2-3 of
    # its offspring to these collisions (observed errors=2/errors=3 on every
    # single cycle in the production log).
    _slots = list(range(n_offspring))
    _lock_retried: set[int] = set()
    while _slots:
        i = _slots.pop(0)
        try:
            parent_a = _tournament_select(parents, rng)
            dsl_a    = StrategyDSL.from_json(parent_a.dsl_json)

            # Mutation/crossover can produce structurally invalid offspring
            # (e.g. crossover_engine.rule_blend deduplicating both parents'
            # conditions down to a single shared feature when they overlap,
            # violating the "≥2 entry conditions" curve-fit guard that fresh
            # generation always enforces via _passes_prescreen). Retry a
            # bounded number of times so a bad roll doesn't waste the
            # offspring slot on a strategy nothing else in the system would
            # have accepted; if every retry fails structurally, skip the
            # slot rather than persist a known-invalid child.
            child_dsl = op = desc = parent_ids = operation = None
            # Crossover partners must share parent_a's family — the
            # re-architecture doctrine is "evolution refines within
            # templates, it doesn't invent" (docs/RESEARCH_DRIVEN_
            # REARCHITECTURE.md §5). Cross-family blends produced children
            # labeled with one family but carrying another family's
            # conditions: random-mutation soup by the back door, and it
            # also poisoned the meta-learner's family-keyed condition
            # statistics (pitfall C16) with conditions no generator of
            # that family ever emits.
            same_family_partners = [
                p for p in parents
                if p.family == parent_a.family and p.strategy_id != parent_a.strategy_id
            ]
            for _attempt in range(4):
                if rng.random() < MUTATION_RATE or not same_family_partners:
                    # Mutation — pass meta_state so op selection is biased toward best ops
                    # (also the fallback when no same-family crossover partner exists)
                    cand_dsl, cand_op, cand_desc = mutate(dsl_a, rng=rng, meta_state=meta_state)
                    cand_parent_ids              = [parent_a.strategy_id]
                    cand_operation               = f"mutation:{cand_op}"
                else:
                    # Crossover — same-family only
                    parent_b = _tournament_select(same_family_partners, rng)
                    dsl_b = StrategyDSL.from_json(parent_b.dsl_json)
                    cand_dsl, cand_op, cand_desc = crossover(
                        dsl_a, dsl_b,
                        fitness_a = parent_a.fitness_score or 0.0,
                        fitness_b = parent_b.fitness_score or 0.0,
                        rng=rng,
                    )
                    cand_parent_ids = [parent_a.strategy_id, parent_b.strategy_id]
                    cand_operation  = f"crossover:{cand_op}"

                ok, reason = _passes_prescreen(cand_dsl, bad_features, bad_conditions)
                if ok:
                    child_dsl, op, desc, parent_ids, operation = (
                        cand_dsl, cand_op, cand_desc, cand_parent_ids, cand_operation
                    )
                    break
                log.debug("Evolution offspring %d attempt %d rejected: %s", i, _attempt, reason)

            if child_dsl is None:
                prescreen_rejected += 1
                skipped += 1
                continue

            child_id = child_dsl.strategy_id()

            # Skip if already exists
            existing = db.query(StrategyV2.id).filter(StrategyV2.strategy_id == child_id).first()
            if existing:
                skipped += 1
                continue

            # Use a savepoint so a failure on this offspring doesn't corrupt the whole session
            sp = db.begin_nested()
            try:
                # Persist child as candidate
                upsert_strategy(db, {
                    "strategy_id":  child_id,
                    "name":         child_dsl.name,
                    "family":       child_dsl.family,
                    "generation":   next_gen,
                    "parent_ids":   json.dumps(parent_ids),
                    "dsl_json":     child_dsl.to_json(),
                    "allowed_regimes": json.dumps(child_dsl.allowed_regimes),
                    "status":       "candidate",
                })
                save_version(db, child_id, child_dsl.to_json(), version=1,
                             change_type=operation, change_desc=desc)
                sp.commit()
                # Commit the child NOW: backtest_and_update persists its
                # metrics through a separate short-lived write session that
                # cannot see this session's uncommitted rows. Without this
                # commit, upsert_strategy in that session hits its
                # missing-family/dsl_json insert guard and silently drops the
                # child's backtest metrics (observed as the recurring
                # "skipping insert" warnings in production logs) — children
                # then get scored on empty metrics until the next rescore
                # sweep heals them.
                db.commit()
            except Exception as sp_exc:
                try:
                    sp.rollback()
                except Exception:
                    # Savepoint already released (failure came from the outer
                    # db.commit(), not the savepoint body) — roll back the
                    # session itself instead.
                    try:
                        db.rollback()
                    except Exception:
                        pass
                log.error("Evolution: failed to persist offspring %d (%s): %s", i, child_id, sp_exc)
                errors.append(str(sp_exc))
                continue

            # Backtest (writes metrics via its own short-lived session)
            bt_result = backtest_and_update(
                db, child_dsl, start_date=start_date, end_date=end_date,
                strategy_id_override=child_id,
            )

            # Score
            child_row = db.query(StrategyV2).filter(StrategyV2.strategy_id == child_id).first()
            child_fitness = score_strategy(db, child_row) if child_row else 0.0

            # Record evolution event
            record_evolution_event(
                db,
                child_strategy_id   = child_id,
                operation           = operation,
                operation_detail    = {"desc": desc, "op": op},
                parent_strategy_ids = parent_ids,
                parent_fitness      = parent_a.fitness_score,
                child_fitness       = child_fitness,
                regime_at           = regime,
            )

            created.append({
                "strategy_id": child_id,
                "operation":   operation,
                "fitness":     child_fitness,
                "parent":      parent_ids[0],
            })

        except Exception as exc:
            try:
                db.rollback()
            except Exception:
                pass
            if "database is locked" in str(exc).lower() and i not in _lock_retried:
                _lock_retried.add(i)
                log.warning("Evolution offspring %d hit transient DB lock — retrying slot once", i)
                time.sleep(1.0 + rng.random())
                _slots.append(i)
                continue
            log.error("Evolution error on offspring %d: %s", i, exc)
            errors.append(str(exc))

    db.commit()

    # Lifecycle sweep: promote winners, retire losers
    lifecycle = run_lifecycle_sweep(db)

    log.info(
        "Evolution cycle gen=%d: created=%d skipped=%d (prescreen_rejected=%d) promoted=%d retired=%d errors=%d meta_insights=%d",
        next_gen, len(created), skipped, prescreen_rejected,
        len(lifecycle.get("promoted", [])),
        len(lifecycle.get("retired", [])),
        len(errors),
        meta_insights,
    )

    return {
        "generation":    next_gen,
        "n_offspring":   n_offspring,
        "created":       len(created),
        "skipped":       skipped,
        "prescreen_rejected": prescreen_rejected,
        "errors":        len(errors),
        "promoted":      lifecycle.get("promoted", []),
        "retired":       lifecycle.get("retired", []),
        "regime_at":     regime,
        "offspring":     created,
        "meta_insights": meta_insights,
        "meta_state_summary": {
            "bad_features":    meta_state.get("bad_features", []) if meta_state else [],
            "conf_floor":      meta_state.get("current_conf_floor") if meta_state else None,
            "top_mutation_op": (meta_state.get("ranked_mutation_ops") or [None])[0] if meta_state else None,
        } if meta_state else None,
    }
