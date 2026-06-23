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
from strategies.strategy_backtester import backtest_and_update
from strategies.fitness_engine import score_all_strategies
from strategies.strategy_lifecycle import run_lifecycle_sweep
from strategies.evolution_engine import evolve_population
from strategies.graveyard_manager import failure_pattern_analysis
from strategies.research_engine import run_full_research
from strategies.strategy_memory import record_knowledge_snapshot
from aqrti.database.models import StrategyV2

log = get_logger("strategy_research_loop")


def _backtest_unscored(db, max_stocks: int = 50) -> dict:
    """Backtest all candidates that have no fitness score yet."""
    rows = (
        db.query(StrategyV2)
        .filter(
            StrategyV2.fitness_score.is_(None),
            StrategyV2.status.in_(["candidate", "shadow"]),
        )
        .limit(50)
        .all()
    )
    tested = 0
    errors = 0
    end_date   = date.today()
    start_date = end_date - timedelta(days=365)

    for row in rows:
        try:
            from strategies.strategy_dsl import StrategyDSL
            dsl = StrategyDSL.from_json(row.dsl_json)
            backtest_and_update(db, dsl, start_date=start_date, end_date=end_date)
            tested += 1
        except Exception as exc:
            log.warning("Backtest failed for %s: %s", row.strategy_id, exc)
            errors += 1

    return {"backtested": tested, "errors": errors, "total_queued": len(rows)}


def run_daily_strategy_research(
    generate_n:    int = 50,
    evolve_n:      int = 20,
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

    with get_db_session() as db:
        # Step 1: Generate new candidates
        if not skip_generate:
            try:
                gen_result = run_generation_cycle(db, n=generate_n, generation=0)
                report["steps"]["generate"] = gen_result
                log.info("Step 1 — Generated: %d new candidates", gen_result.get("persisted", 0))
            except Exception as exc:
                log.error("Step 1 — Generation failed: %s", exc)
                report["steps"]["generate"] = {"error": str(exc)}
        else:
            report["steps"]["generate"] = {"skipped": True}

        # Step 2: Backtest unscored strategies
        try:
            bt_result = _backtest_unscored(db)
            report["steps"]["backtest"] = bt_result
            log.info("Step 2 — Backtested: %d strategies", bt_result["backtested"])
        except Exception as exc:
            log.error("Step 2 — Backtest sweep failed: %s", exc)
            report["steps"]["backtest"] = {"error": str(exc)}

        # Step 3: Score all strategies
        try:
            score_result = score_all_strategies(db)
            report["steps"]["scoring"] = score_result
            log.info("Step 3 — Scored: %d strategies", score_result.get("scored", 0))
        except Exception as exc:
            log.error("Step 3 — Scoring failed: %s", exc)
            report["steps"]["scoring"] = {"error": str(exc)}

        # Step 4: Lifecycle sweep
        try:
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

        # Step 5: Evolve population
        if not skip_evolve:
            try:
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
            patterns = failure_pattern_analysis(db)
            report["steps"]["graveyard"] = patterns
            log.info("Step 6 — Graveyard: total=%d", patterns.get("total", 0))
        except Exception as exc:
            log.error("Step 6 — Graveyard analysis failed: %s", exc)
            report["steps"]["graveyard"] = {"error": str(exc)}

        # Step 7: Research reports
        try:
            research = run_full_research(db)
            report["steps"]["research"] = research
            log.info("Step 7 — Research: %d reports generated", len(research.get("reports", [])))
        except Exception as exc:
            log.error("Step 7 — Research reports failed: %s", exc)
            report["steps"]["research"] = {"error": str(exc)}

        # Step 8: Population snapshot
        try:
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
