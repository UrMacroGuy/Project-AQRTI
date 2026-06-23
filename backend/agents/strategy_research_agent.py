"""
Strategy Research Agent (7D)
Analyzes strategy performance, decay, resurrection candidates, and emerging families.

MAY NOT: activate strategies, modify DSL, deploy changes.
"""

from __future__ import annotations

import sys, os, json
from datetime import date, timedelta

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from sqlalchemy.orm import Session
from aqrti.database.models import StrategyV2, StrategyGraveyard, MarketRegime
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
        regime_row = db.query(MarketRegime).order_by(MarketRegime.date.desc()).first()
        current_regime = regime_row.regime if regime_row else "BULL"

        # ── 1. Population Health ──────────────────────────────────
        active_strats = db.query(StrategyV2).filter(
            StrategyV2.status.in_(["active", "promoted", "shadow"])
        ).all()
        candidates = db.query(StrategyV2).filter(StrategyV2.status == "candidate").count()
        graveyard  = db.query(StrategyGraveyard).count()

        if not active_strats:
            findings.append({
                "title":       "No Active Strategies — Population Empty",
                "description": "No strategies are in active/promoted/shadow status.",
                "evidence":    "active_count=0",
                "implication": "Run generation cycle to populate strategy universe.",
                "urgency":     "critical",
                "subcategory": "population",
            })
            recommendations.append("Trigger strategy generation cycle immediately.")
        else:
            avg_fitness = sum(s.fitness_score or 0 for s in active_strats) / len(active_strats)
            if avg_fitness < 45:
                findings.append({
                    "title":       f"Low Average Strategy Fitness: {avg_fitness:.1f}",
                    "description": f"Active population avg fitness={avg_fitness:.1f}. Target ≥55.",
                    "evidence":    f"n={len(active_strats)}, avg_fitness={avg_fitness:.1f}",
                    "implication": "Current strategy population underperforms. Evolution cycle recommended.",
                    "urgency":     "high",
                    "subcategory": "population",
                })
                recommendations.append("Run evolution cycle to improve population fitness.")

        # ── 2. Strategy Decay ────────────────────────────────────
        cutoff = date.today() - timedelta(days=30)
        decaying = [
            s for s in active_strats
            if s.fitness_score is not None and s.fitness_score < 40
        ]
        if decaying:
            for s in decaying[:5]:
                findings.append({
                    "title":       f"Strategy Decay: {s.name} fitness={s.fitness_score:.1f}",
                    "description": (
                        f"{s.family.title()} strategy {s.name} has fitness {s.fitness_score:.1f} "
                        f"(Sharpe={s.sharpe}, win_rate={s.win_rate}%). Decay detected."
                    ),
                    "evidence":    f"fitness={s.fitness_score:.1f}, sharpe={s.sharpe}, trades={s.trade_count}",
                    "implication": f"Strategy {s.name} should be retired. Recommend lifecycle sweep.",
                    "urgency":     "high" if s.fitness_score < 30 else "normal",
                    "subcategory": "decay",
                })
            recommendations.append(f"{len(decaying)} strategies show decay — run lifecycle sweep.")

        # ── 3. Regime Misalignment ───────────────────────────────
        regime_mismatched = []
        for s in active_strats:
            try:
                allowed = json.loads(s.allowed_regimes) if s.allowed_regimes else []
                if allowed and current_regime not in allowed:
                    regime_mismatched.append(s)
            except Exception:
                pass

        if regime_mismatched:
            names = [s.name for s in regime_mismatched[:3]]
            findings.append({
                "title":       f"Regime Mismatch: {len(regime_mismatched)} strategies not designed for {current_regime}",
                "description": f"Strategies {names} are running in {current_regime} but not configured for it.",
                "evidence":    f"current_regime={current_regime}, mismatched={len(regime_mismatched)}",
                "implication": "These strategies may generate false signals in the current regime.",
                "urgency":     "normal",
                "subcategory": "regime_mismatch",
            })

        # ── 4. Resurrection Candidates ───────────────────────────
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
                "title":       f"Resurrection Candidate: {best.name} (fitness={best.final_fitness:.1f})",
                "description": (
                    f"{best.name} died in {best.regime_at_death} regime but current is {current_regime}. "
                    f"May be worth retesting."
                ),
                "evidence":    f"final_fitness={best.final_fitness:.1f}, died_in={best.regime_at_death}",
                "implication": "Retest this strategy in current regime conditions.",
                "urgency":     "normal",
                "subcategory": "resurrection",
            })
            recommendations.append(f"Retest {best.name} — died in different regime.")

        # ── 5. Emerging Family ───────────────────────────────────
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

        summary = (
            f"Strategy population: {len(active_strats)} active, {candidates} candidates, {graveyard} in graveyard. "
            f"{len(decaying)} decaying. {len(resurrection)} resurrection candidates. "
            f"{len(findings)} findings."
        )
        urgency = "critical" if any(f["urgency"] == "critical" for f in findings) else \
                  "high"     if any(f["urgency"] == "high"     for f in findings) else "normal"

        return {
            "title":           f"Strategy Research — {date.today()}",
            "summary":         summary,
            "findings":        findings,
            "recommendations": recommendations,
            "urgency":         urgency,
            "metadata": {
                "active_count":      len(active_strats),
                "candidate_count":   candidates,
                "graveyard_count":   graveyard,
                "decaying_count":    len(decaying),
                "current_regime":    current_regime,
            },
        }


register_agent_class(StrategyResearchAgent)
