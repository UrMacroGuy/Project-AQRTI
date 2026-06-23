"""
Pattern Research Agent (7G)
Discovers new patterns, tracks pattern drift, failures, and opportunities.

MAY NOT: modify models, activate strategies, change pattern thresholds.
"""

from __future__ import annotations

import sys, os
from datetime import date, timedelta
from collections import Counter

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from sqlalchemy.orm import Session
from aqrti.database.models import PatternOutcome, PatternMatch, KnowledgeScore
from aqrti.utils.logger import get_logger
from agents.agent_base import AgentBase
from agents.agent_registry import register_agent_class

log = get_logger("agent.pattern_research")


class PatternResearchAgent(AgentBase):
    agent_id    = "pattern_research"
    agent_type  = "pattern"
    name        = "Pattern Research Agent"
    description = "Discovers new patterns, tracks pattern drift, failures, and opportunities."

    def run(self, db: Session) -> dict:
        findings        = []
        recommendations = []
        cutoff_30d      = date.today() - timedelta(days=30)
        cutoff_7d       = date.today() - timedelta(days=7)

        # ── 1. Pattern Hit Rate ───────────────────────────────────
        try:
            recent_outcomes = (
                db.query(PatternOutcome)
                .filter(PatternOutcome.prediction_date >= cutoff_30d)
                .all()
            )
            if recent_outcomes:
                evaluated = [o for o in recent_outcomes if o.was_correct is not None]
                if evaluated:
                    hit_rate = sum(1 for o in evaluated if o.was_correct) / len(evaluated) * 100
                    if hit_rate < 50:
                        findings.append({
                            "title":       f"Pattern Hit Rate Below 50%: {hit_rate:.1f}%",
                            "description": f"Patterns are correct only {hit_rate:.1f}% of the time (last 30d, n={len(evaluated)}).",
                            "evidence":    f"hit_rate={hit_rate:.1f}%, n={len(evaluated)}",
                            "implication": "Pattern matching quality has degraded. Consider similarity threshold review.",
                            "urgency":     "high",
                            "subcategory": "hit_rate",
                        })
                        recommendations.append("Review pattern similarity thresholds — hit rate has declined.")
                    elif hit_rate >= 65:
                        findings.append({
                            "title":       f"Strong Pattern Hit Rate: {hit_rate:.1f}%",
                            "description": f"Patterns achieving {hit_rate:.1f}% hit rate in last 30d (n={len(evaluated)}).",
                            "evidence":    f"hit_rate={hit_rate:.1f}%, n={len(evaluated)}",
                            "implication": "Pattern engine performing well. Consider increasing confidence scores.",
                            "urgency":     "low",
                            "subcategory": "hit_rate",
                        })
        except Exception as exc:
            log.debug("Pattern hit rate query skipped: %s", exc)

        # ── 2. Nifty Outperformance Rate ─────────────────────────
        try:
            outperformed = (
                db.query(PatternOutcome)
                .filter(
                    PatternOutcome.prediction_date >= cutoff_30d,
                    PatternOutcome.outperformed_nifty == True,
                )
                .count()
            )
            total_eval = (
                db.query(PatternOutcome)
                .filter(
                    PatternOutcome.prediction_date >= cutoff_30d,
                    PatternOutcome.outperformed_nifty.isnot(None),
                )
                .count()
            )
            if total_eval > 0:
                beat_rate = outperformed / total_eval * 100
                if beat_rate < 50:
                    findings.append({
                        "title":       f"Pattern Alpha Negative: Only {beat_rate:.1f}% beat Nifty",
                        "description": f"Patterns generated {beat_rate:.1f}% Nifty-beating signals (last 30d).",
                        "evidence":    f"beat_rate={beat_rate:.1f}%, outperformed={outperformed}/{total_eval}",
                        "implication": "Pattern-based signals are not generating alpha vs the index.",
                        "urgency":     "high",
                        "subcategory": "alpha",
                    })
        except Exception as exc:
            log.debug("Nifty outperformance query skipped: %s", exc)

        # ── 3. Pattern Volume / Coverage ─────────────────────────
        try:
            recent_matches = (
                db.query(PatternMatch)
                .filter(PatternMatch.match_date >= cutoff_7d)
                .count()
            )
            if recent_matches < 5:
                findings.append({
                    "title":       f"Low Pattern Activity: {recent_matches} matches in 7 days",
                    "description": f"Only {recent_matches} pattern matches recorded in the last 7 days.",
                    "evidence":    f"recent_matches={recent_matches}",
                    "implication": "Pattern matching may not be running or market is structurally different.",
                    "urgency":     "normal",
                    "subcategory": "coverage",
                })
        except Exception as exc:
            log.debug("Pattern coverage query skipped: %s", exc)

        # ── 4. Pattern Drift by Regime ────────────────────────────
        try:
            regime_outcomes: dict[str, list[bool]] = {}
            outcomes = (
                db.query(PatternOutcome)
                .filter(PatternOutcome.prediction_date >= cutoff_30d)
                .all()
            )
            for o in outcomes:
                reg = o.regime_at or "UNKNOWN"
                if o.was_correct is not None:
                    regime_outcomes.setdefault(reg, []).append(o.was_correct)

            for reg, results in regime_outcomes.items():
                if len(results) >= 5:
                    rate = sum(results) / len(results) * 100
                    if rate < 45:
                        findings.append({
                            "title":       f"Pattern Drift in {reg} Regime: {rate:.1f}% hit rate",
                            "description": f"Patterns perform poorly in {reg} regime ({rate:.1f}%, n={len(results)}).",
                            "evidence":    f"regime={reg}, hit_rate={rate:.1f}%, n={len(results)}",
                            "implication": f"Pattern-based signals in {reg} regime are unreliable.",
                            "urgency":     "normal",
                            "subcategory": "regime_drift",
                            "regime":      reg,
                        })
        except Exception as exc:
            log.debug("Pattern drift analysis skipped: %s", exc)

        summary = (
            f"Pattern research: {len(findings)} findings. "
            f"{'[!] Quality issues detected.' if any(f['urgency'] in ('high','critical') for f in findings) else 'Patterns operating normally.'}"
        )
        urgency = "high" if any(f["urgency"] == "high" for f in findings) else "normal"

        return {
            "title":           f"Pattern Research — {date.today()}",
            "summary":         summary,
            "findings":        findings,
            "recommendations": recommendations,
            "urgency":         urgency,
        }


register_agent_class(PatternResearchAgent)
