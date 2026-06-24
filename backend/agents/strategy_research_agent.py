"""
Strategy Research Agent
Analyzes strategy performance, decay, resurrection candidates, and emerging families.
Falls back to prediction-based analysis when strategy tables are empty.

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
from aqrti.database.models import StrategyV2, StrategyGraveyard, MarketRegime, Prediction
from aqrti.utils.logger import get_logger
from agents.agent_base import AgentBase
from agents.agent_registry import register_agent_class

log = get_logger("agent.strategy_research")


class StrategyResearchAgent(AgentBase):
    agent_id    = "strategy_research"
    agent_type  = "strategy"
    name        = "Strategy Research Agent"
    description = "Analyzes strategy performance, decay, resurrection candidates, and emerging signal families."

    def run(self, db: Session) -> dict:
        findings        = []
        recommendations = []
        today           = date.today()
        cutoff_30d      = today - timedelta(days=30)

        # ── Current Regime ─────────────────────────────────────────
        try:
            regime_row     = db.query(MarketRegime).order_by(MarketRegime.date.desc()).first()
            current_regime = regime_row.regime if regime_row else "UNKNOWN"
        except Exception:
            current_regime = "UNKNOWN"

        # ── 1. Strategy Population Health ────────────────────────
        try:
            active_strats = db.query(StrategyV2).filter(
                StrategyV2.status.in_(["active", "promoted", "shadow"])
            ).all()
            candidates = db.query(StrategyV2).filter(StrategyV2.status == "candidate").count()
            graveyard  = db.query(StrategyGraveyard).count()

            if not active_strats:
                findings.append({
                    "title":       "Strategy Population: Empty",
                    "description": (
                        f"No active/shadow strategies found. {candidates} candidates, "
                        f"{graveyard} in graveyard. Population needs seeding."
                    ),
                    "evidence":    f"active=0, candidates={candidates}, graveyard={graveyard}",
                    "implication": "Run strategy generation cycle to populate the active population.",
                    "urgency":     "normal",
                    "subcategory": "population",
                })
                recommendations.append("Trigger strategy generation cycle to seed the population.")
            else:
                avg_fitness = sum(s.fitness_score or 0 for s in active_strats) / len(active_strats)
                findings.append({
                    "title":       f"Strategy Population: {len(active_strats)} active, avg fitness {avg_fitness:.1f}",
                    "description": (
                        f"Active population: {len(active_strats)} strategies, "
                        f"{candidates} candidates, {graveyard} in graveyard. "
                        f"Average fitness={avg_fitness:.1f} (target ≥55)."
                    ),
                    "evidence":    f"active={len(active_strats)}, avg_fitness={avg_fitness:.1f}",
                    "implication": f"{'Population fitness is healthy.' if avg_fitness >= 55 else 'Below-target fitness — evolution cycle recommended.'}",
                    "urgency":     "high" if avg_fitness < 45 else "normal",
                    "subcategory": "population",
                })
                if avg_fitness < 45:
                    recommendations.append("Run evolution cycle to improve population fitness.")

                # Strategy Decay
                decaying = [s for s in active_strats if s.fitness_score is not None and s.fitness_score < 40]
                if decaying:
                    for s in decaying[:5]:
                        findings.append({
                            "title":       f"Strategy Decay: {s.name} fitness={s.fitness_score:.1f}",
                            "description": (
                                f"Strategy {s.name} has fitness {s.fitness_score:.1f} "
                                f"(sharpe={s.sharpe}, win_rate={s.win_rate}%)."
                            ),
                            "evidence":    f"fitness={s.fitness_score:.1f}, sharpe={s.sharpe}, trades={s.trade_count}",
                            "implication": f"Strategy {s.name} should be retired. Lifecycle sweep recommended.",
                            "urgency":     "high" if s.fitness_score < 30 else "normal",
                            "subcategory": "decay",
                        })
                    recommendations.append(f"{len(decaying)} strategies show decay — run lifecycle sweep.")

                # Regime Misalignment
                if current_regime != "UNKNOWN":
                    mismatched = []
                    for s in active_strats:
                        try:
                            allowed = json.loads(s.allowed_regimes) if s.allowed_regimes else []
                            if allowed and current_regime not in allowed:
                                mismatched.append(s)
                        except Exception:
                            pass
                    if mismatched:
                        names = [s.name for s in mismatched[:3]]
                        findings.append({
                            "title":       f"Regime Mismatch: {len(mismatched)} strategies not suited for {current_regime}",
                            "description": f"Strategies {names} running in {current_regime} but not configured for it.",
                            "evidence":    f"current_regime={current_regime}, mismatched={len(mismatched)}",
                            "implication": "These strategies may generate false signals in the current regime.",
                            "urgency":     "normal",
                            "subcategory": "regime_mismatch",
                        })

                # Leading Family
                family_scores: dict[str, list[float]] = {}
                for s in active_strats:
                    if s.fitness_score and getattr(s, 'family', None):
                        family_scores.setdefault(s.family, []).append(s.fitness_score)
                if family_scores:
                    best_fam = max(family_scores, key=lambda f: sum(family_scores[f]) / len(family_scores[f]))
                    best_avg = sum(family_scores[best_fam]) / len(family_scores[best_fam])
                    findings.append({
                        "title":       f"Leading Family: {best_fam} (avg fitness={best_avg:.1f})",
                        "description": f"Family '{best_fam}' leads with avg fitness {best_avg:.1f} across {len(family_scores[best_fam])} strategies.",
                        "evidence":    f"family={best_fam}, avg_fitness={best_avg:.1f}",
                        "implication": f"Prioritise '{best_fam}' in next evolution cycle.",
                        "urgency":     "low",
                        "subcategory": "family_analysis",
                    })
        except Exception as exc:
            log.debug("Strategy population query skipped: %s", exc)

        # ── 2. Resurrection Candidates ────────────────────────────
        try:
            if current_regime != "UNKNOWN":
                resurrection = (
                    db.query(StrategyGraveyard)
                    .filter(
                        StrategyGraveyard.regime_at_death != current_regime,
                        StrategyGraveyard.final_fitness   >= 45,
                    )
                    .order_by(StrategyGraveyard.final_fitness.desc())
                    .limit(3)
                    .all()
                )
                if resurrection:
                    best = resurrection[0]
                    findings.append({
                        "title":       f"Resurrection Candidate: {best.name} (fitness={best.final_fitness:.1f})",
                        "description": (
                            f"{best.name} died in {best.regime_at_death} regime; current is {current_regime}. "
                            "May be worth retesting."
                        ),
                        "evidence":    f"final_fitness={best.final_fitness:.1f}, died_in={best.regime_at_death}",
                        "implication": "Retest this strategy in current regime conditions.",
                        "urgency":     "normal",
                        "subcategory": "resurrection",
                    })
                    recommendations.append(f"Retest {best.name} — died in different regime.")
        except Exception as exc:
            log.debug("Resurrection query skipped: %s", exc)

        # ── 3. Prediction-Based Signal Analysis ───────────────────
        try:
            recent_preds = db.query(Prediction).filter(Prediction.date >= cutoff_30d).all()
            if recent_preds:
                combo_counts = Counter((p.symbol, p.direction) for p in recent_preds if p.direction)
                top_combos   = [(combo, cnt) for combo, cnt in combo_counts.most_common(5) if cnt >= 5]
                if top_combos:
                    top_sym, top_dir = top_combos[0][0]
                    top_cnt          = top_combos[0][1]
                    findings.append({
                        "title":       f"Persistent Signal: {top_sym} {top_dir} ({top_cnt}x in 30d)",
                        "description": (
                            f"The model generated {top_cnt} {top_dir} signals for {top_sym} "
                            "over the last 30 days — a persistent pattern."
                        ),
                        "evidence":    f"symbol={top_sym}, direction={top_dir}, count={top_cnt}",
                        "implication": f"Consider building a dedicated strategy around {top_sym} {top_dir.lower()} signals.",
                        "urgency":     "low",
                        "subcategory": "signal_persistence",
                    })

                evaluated = [p for p in recent_preds if p.success is not None]
                if len(evaluated) >= 5:
                    bull_wins  = sum(1 for p in evaluated if p.direction == "Bullish" and p.success)
                    bull_total = sum(1 for p in evaluated if p.direction == "Bullish")
                    if bull_total >= 3:
                        bull_wr = bull_wins / bull_total * 100
                        if bull_wr > 65 or bull_wr < 40:
                            findings.append({
                                "title":       f"Bullish Signal Win Rate: {bull_wr:.1f}% ({bull_wins}/{bull_total})",
                                "description": f"Bullish predictions win rate={bull_wr:.1f}% over last 30 days.",
                                "evidence":    f"bull_wins={bull_wins}, bull_total={bull_total}",
                                "implication": f"{'Strong bullish edge.' if bull_wr > 65 else 'Poor bullish win rate — review entry criteria.'}",
                                "urgency":     "high" if bull_wr < 40 else "low",
                                "subcategory": "direction_win_rate",
                            })
        except Exception as exc:
            log.debug("Prediction-based strategy analysis skipped: %s", exc)

        if not findings:
            findings.append({
                "title":       "Strategy System Baseline",
                "description": "Strategy tables accessible. No active strategies yet — generation cycle not run.",
                "evidence":    "active_strategies=0",
                "implication": "Run strategy generation cycle from Research Ops.",
                "urgency":     "low",
                "subcategory": "baseline",
            })

        summary = (
            f"Strategy research: {len(findings)} findings. "
            f"Regime: {current_regime}."
        )
        urgency = (
            "critical" if any(f["urgency"] == "critical" for f in findings) else
            "high"     if any(f["urgency"] == "high"     for f in findings) else
            "normal"
        )

        return {
            "title":           f"Strategy Research — {today}",
            "summary":         summary,
            "findings":        findings,
            "recommendations": recommendations,
            "urgency":         urgency,
            "metadata":        {"current_regime": current_regime},
        }


register_agent_class(StrategyResearchAgent)
