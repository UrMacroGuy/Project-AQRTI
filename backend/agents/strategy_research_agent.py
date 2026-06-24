"""
Strategy Research Agent (7D)
Analyzes strategy performance, decay, resurrection candidates, and emerging families.

When strategies_v2 / strategy_graveyard are empty (fresh install), produces
prediction-based proto-strategy proxies and reports status at low urgency.

MAY NOT: activate strategies, modify DSL, deploy changes.
"""

from __future__ import annotations

import sys, os, json
from datetime import date, timedelta
from collections import Counter

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from sqlalchemy.orm import Session
from sqlalchemy import func
from aqrti.database.models import StrategyV2, StrategyGraveyard, MarketRegime, Prediction, PaperTrade
from aqrti.utils.logger import get_logger
from agents.agent_base import AgentBase
from agents.agent_registry import register_agent_class

log = get_logger("agent.strategy_research")


class StrategyResearchAgent(AgentBase):
    agent_id    = "strategy_research"
    agent_type  = "strategy"
    name        = "Strategy Research Agent"
    description = "Analyzes strategy performance, decay, resurrection candidates, and emerging families."

    def run(self, db: Session) -> dict:
        findings        = []
        recommendations = []

        # ── Current regime ─────────────────────────────────────────
        current_regime = "UNKNOWN"
        try:
            regime_row = db.query(MarketRegime).order_by(MarketRegime.date.desc()).first()
            current_regime = regime_row.regime if regime_row else "UNKNOWN"
        except Exception as exc:
            log.debug("Regime query failed: %s", exc)

        active_strats = []
        candidates    = 0
        graveyard     = 0
        decaying      = []

        # ── 1. Population Health ──────────────────────────────────
        try:
            active_strats = db.query(StrategyV2).filter(
                StrategyV2.status.in_(["active", "promoted", "shadow"])
            ).all()
            candidates = db.query(StrategyV2).filter(StrategyV2.status == "candidate").count()
            graveyard  = db.query(StrategyGraveyard).count()

            if not active_strats and candidates == 0:
                findings.append({
                    "title":       "Strategy Population Empty — System Initialising",
                    "description": (
                        "No strategies exist in active, promoted, shadow, or candidate status. "
                        f"Graveyard has {graveyard} retired entries."
                    ),
                    "evidence":    f"active=0, candidates=0, graveyard={graveyard}",
                    "implication": "Run strategy generation cycle to populate the universe. This is expected for a fresh install.",
                    "urgency":     "normal",
                    "subcategory": "population",
                })
                recommendations.append("Trigger strategy generation cycle to populate strategy universe.")
            else:
                total_pop = len(active_strats) + candidates
                if total_pop > 0:
                    avg_fitness = (
                        sum(s.fitness_score or 0 for s in active_strats) / len(active_strats)
                        if active_strats else 0.0
                    )
                    findings.append({
                        "title":       f"Strategy Population: {len(active_strats)} active, {candidates} candidates",
                        "description": (
                            f"Active/shadow/promoted: {len(active_strats)}. "
                            f"Candidates: {candidates}. "
                            f"Graveyard: {graveyard}. "
                            + (f"Avg fitness (active): {avg_fitness:.1f}." if active_strats else "")
                        ),
                        "evidence":    f"active={len(active_strats)}, candidates={candidates}, graveyard={graveyard}",
                        "implication": "Population is in operation. Monitor fitness trends.",
                        "urgency":     "low",
                        "subcategory": "population",
                    })

                    if active_strats and avg_fitness < 45:
                        findings.append({
                            "title":       f"Low Average Strategy Fitness: {avg_fitness:.1f}",
                            "description": f"Active population avg fitness={avg_fitness:.1f}. Target ≥55.",
                            "evidence":    f"n={len(active_strats)}, avg_fitness={avg_fitness:.1f}",
                            "implication": "Current strategy population underperforms. Evolution cycle recommended.",
                            "urgency":     "high",
                            "subcategory": "population",
                        })
                        recommendations.append("Run evolution cycle to improve population fitness.")
        except Exception as exc:
            log.debug("Population query failed: %s", exc)

        # ── 2. Strategy Decay ────────────────────────────────────
        try:
            decaying = [
                s for s in active_strats
                if s.fitness_score is not None and s.fitness_score < 40
            ]
            if decaying:
                for s in decaying[:5]:
                    findings.append({
                        "title":       f"Strategy Decay: {s.name or s.strategy_id} fitness={s.fitness_score:.1f}",
                        "description": (
                            f"{s.family.title()} strategy '{s.name or s.strategy_id}' has fitness "
                            f"{s.fitness_score:.1f} "
                            f"(Sharpe={s.sharpe}, win_rate={s.win_rate}%). Decay detected."
                        ),
                        "evidence":    f"fitness={s.fitness_score:.1f}, sharpe={s.sharpe}, trades={s.trade_count}",
                        "implication": f"Strategy should be retired. Recommend lifecycle sweep.",
                        "urgency":     "high" if s.fitness_score < 30 else "normal",
                        "subcategory": "decay",
                    })
                recommendations.append(f"{len(decaying)} strategies show decay — run lifecycle sweep.")
        except Exception as exc:
            log.debug("Decay analysis failed: %s", exc)

        # ── 3. Regime Misalignment ───────────────────────────────
        try:
            regime_mismatched = []
            for s in active_strats:
                try:
                    allowed = json.loads(s.allowed_regimes) if s.allowed_regimes else []
                    if allowed and current_regime not in allowed:
                        regime_mismatched.append(s)
                except Exception:
                    pass

            if regime_mismatched:
                names = [s.name or s.strategy_id for s in regime_mismatched[:3]]
                findings.append({
                    "title":       f"Regime Mismatch: {len(regime_mismatched)} strategies not designed for {current_regime}",
                    "description": f"Strategies {names} are running in {current_regime} but not configured for it.",
                    "evidence":    f"current_regime={current_regime}, mismatched={len(regime_mismatched)}",
                    "implication": "These strategies may generate false signals in the current regime.",
                    "urgency":     "normal",
                    "subcategory": "regime_mismatch",
                })
        except Exception as exc:
            log.debug("Regime mismatch check failed: %s", exc)

        # ── 4. Resurrection Candidates ───────────────────────────
        try:
            resurrection = (
                db.query(StrategyGraveyard)
                .filter(
                    StrategyGraveyard.regime_at_death != current_regime,
                    StrategyGraveyard.final_fitness >= 45,
                )
                .order_by(StrategyGraveyard.final_fitness.desc())
                .limit(3)
                .all()
            )
            if resurrection:
                best = resurrection[0]
                findings.append({
                    "title":       f"Resurrection Candidate: {best.name or best.strategy_id} (fitness={best.final_fitness:.1f})",
                    "description": (
                        f"Strategy died in {best.regime_at_death} regime but current is {current_regime}. "
                        f"May be worth retesting."
                    ),
                    "evidence":    f"final_fitness={best.final_fitness:.1f}, died_in={best.regime_at_death}",
                    "implication": "Retest this strategy in current regime conditions.",
                    "urgency":     "normal",
                    "subcategory": "resurrection",
                })
                recommendations.append(f"Retest {best.name or best.strategy_id} — died in different regime.")
        except Exception as exc:
            log.debug("Resurrection query failed: %s", exc)

        # ── 5. Emerging Family ───────────────────────────────────
        try:
            family_scores: dict[str, list[float]] = {}
            for s in active_strats:
                if s.fitness_score:
                    family_scores.setdefault(s.family, []).append(s.fitness_score)

            if family_scores:
                best_family = max(family_scores, key=lambda f: sum(family_scores[f]) / len(family_scores[f]))
                best_avg    = sum(family_scores[best_family]) / len(family_scores[best_family])
                findings.append({
                    "title":       f"Leading Family: {best_family} (avg fitness={best_avg:.1f})",
                    "description": f"Family '{best_family}' leads with avg fitness {best_avg:.1f} across {len(family_scores[best_family])} strategies.",
                    "evidence":    f"family={best_family}, avg_fitness={best_avg:.1f}, n={len(family_scores[best_family])}",
                    "implication": f"Prioritize '{best_family}' in next evolution cycle.",
                    "urgency":     "low",
                    "subcategory": "family_analysis",
                })
        except Exception as exc:
            log.debug("Family analysis failed: %s", exc)

        # ── 6. Prediction-based proto-strategy proxy ─────────────
        # Only when no strategies exist — show recurring direction patterns as seeds
        try:
            if not active_strats and candidates == 0:
                pred_rows = (
                    db.query(Prediction.symbol, Prediction.direction, func.count().label("cnt"))
                    .filter(Prediction.direction.isnot(None))
                    .group_by(Prediction.symbol, Prediction.direction)
                    .order_by(func.count().label("cnt").desc())
                    .limit(5)
                    .all()
                )
                if pred_rows:
                    top = pred_rows[0]
                    findings.append({
                        "title":       f"Proto-Strategy Signal: {top.symbol} consistently {top.direction} ({top.cnt} predictions)",
                        "description": (
                            f"Without a formal strategy population, prediction history shows "
                            f"{top.symbol} has {top.cnt} {top.direction} predictions — "
                            f"a candidate seed for a {top.direction.lower()} momentum strategy."
                        ),
                        "evidence":    f"symbol={top.symbol}, direction={top.direction}, pred_count={top.cnt}",
                        "implication": "Use this pattern as a seed for the first strategy generation cycle.",
                        "urgency":     "low",
                        "subcategory": "proto_strategy",
                    })
        except Exception as exc:
            log.debug("Proto-strategy query failed: %s", exc)

        # ── 7. Paper trade win rate by regime ────────────────────
        try:
            closed_trades = (
                db.query(PaperTrade)
                .filter(
                    PaperTrade.is_open == False,
                    PaperTrade.actual_return.isnot(None),
                )
                .all()
            )
            if closed_trades and len(closed_trades) >= 5:
                wins     = sum(1 for t in closed_trades if (t.actual_return or 0) > 0)
                win_rate = wins / len(closed_trades) * 100

                # Group by strategy name
                strat_perf: dict[str, list[float]] = {}
                for t in closed_trades:
                    key = t.strategy or "unknown"
                    strat_perf.setdefault(key, []).append(t.actual_return or 0)

                if len(strat_perf) > 1:
                    best_strat_key  = max(strat_perf, key=lambda k: sum(strat_perf[k]) / len(strat_perf[k]))
                    best_strat_avg  = sum(strat_perf[best_strat_key]) / len(strat_perf[best_strat_key])
                    worst_strat_key = min(strat_perf, key=lambda k: sum(strat_perf[k]) / len(strat_perf[k]))
                    worst_strat_avg = sum(strat_perf[worst_strat_key]) / len(strat_perf[worst_strat_key])

                    findings.append({
                        "title":       f"Live Trade Win Rate: {win_rate:.1f}% ({len(closed_trades)} trades)",
                        "description": (
                            f"Paper trading win rate: {win_rate:.1f}%. "
                            f"Best strategy: '{best_strat_key}' (avg ret={best_strat_avg:+.2f}%). "
                            f"Worst: '{worst_strat_key}' (avg ret={worst_strat_avg:+.2f}%)."
                        ),
                        "evidence":    f"win_rate={win_rate:.1f}%, trades={len(closed_trades)}, best_strat={best_strat_key}",
                        "implication": (
                            "Strategy signals are generating positive returns in paper trading."
                            if win_rate >= 55 else
                            "Win rate below 55% — review strategy selection criteria."
                        ),
                        "urgency":     "high" if win_rate < 40 else "normal",
                        "subcategory": "live_performance",
                    })
        except Exception as exc:
            log.debug("Trade win-rate by strategy failed: %s", exc)

        # ── Fallback ──────────────────────────────────────────────
        if not findings:
            findings.append({
                "title":       "Strategy System Initialising",
                "description": "No strategies, trades, or predictions found. System is in early operation.",
                "evidence":    "active_strats=0, candidates=0, trades=0",
                "implication": "Complete data ingestion and prediction generation before strategy analysis can begin.",
                "urgency":     "low",
                "subcategory": "data_coverage",
            })

        summary = (
            f"Strategy population: {len(active_strats)} active, {candidates} candidates, {graveyard} in graveyard. "
            f"{len(decaying)} decaying. "
            f"{len(findings)} findings."
        )
        urgency = (
            "critical" if any(f["urgency"] == "critical" for f in findings) else
            "high"     if any(f["urgency"] == "high"     for f in findings) else
            "normal"
        )

        return {
            "title":           f"Strategy Research — {date.today()}",
            "summary":         summary,
            "findings":        findings,
            "recommendations": recommendations,
            "urgency":         urgency,
            "metadata": {
                "active_count":    len(active_strats),
                "candidate_count": candidates,
                "graveyard_count": graveyard,
                "decaying_count":  len(decaying),
                "current_regime":  current_regime,
            },
        }


register_agent_class(StrategyResearchAgent)
