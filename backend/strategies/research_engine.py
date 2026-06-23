"""
Meta Research Engine
Generates automatic research reports answering key strategic questions:

  Q1: Which feature categories produce the best strategies?
  Q2: Which regimes generate the highest returns?
  Q3: Which strategy families survive the longest?
  Q4: What evolution operations produce the biggest fitness gains?
  Q5: Are there resurrection candidates in the graveyard?
  Q6: What is the current population health?

Reports are written to StrategyResearchReport and stored as KnowledgeEvents.
No changes are deployed automatically — reports are for analyst review.
"""

from __future__ import annotations

import sys, os, json
from datetime import date

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from sqlalchemy.orm import Session

from aqrti.database.models import StrategyResearchReport, KnowledgeEvent
from aqrti.utils.logger import get_logger
from strategies.strategy_memory import (
    family_survival_memory,
    feature_category_memory,
    regime_family_affinity,
    evolution_tree_summary,
)
from strategies.graveyard_manager import (
    failure_pattern_analysis,
    get_resurrection_candidates,
)
from strategies.strategy_registry import (
    get_leaderboard,
    get_population_stats,
    get_graveyard_summary,
)

log = get_logger("research_engine")


def _write_report(
    db:              Session,
    category:        str,
    title:           str,
    summary:         str,
    findings:        dict,
    recommendations: str = "",
) -> StrategyResearchReport:
    row = StrategyResearchReport(
        report_date     = date.today(),
        category        = category,
        title           = title,
        summary         = summary,
        findings_json   = json.dumps(findings),
        recommendations = recommendations,
    )
    db.add(row)

    event = KnowledgeEvent(
        event_date  = date.today(),
        category    = "strategy",
        event_type  = f"research_report:{category}",
        description = f"{title} — {summary[:200]}",
        outcome     = "neutral",
    )
    db.add(event)
    return row


def report_feature_analysis(db: Session) -> StrategyResearchReport:
    """Q1: Which feature categories produce the best strategies?"""
    mem     = feature_category_memory(db)
    ranked  = mem.get("ranked", [])

    if ranked:
        best_cat = ranked[0]["category"]
        summary  = (
            f"Top feature category: '{best_cat}' with avg fitness {ranked[0]['avg_fitness']:.1f}. "
            f"{len(ranked)} categories analysed."
        )
        rec = (
            f"Prioritise '{best_cat}' features in next generation. "
            f"Reduce emphasis on '{ranked[-1]['category']}' (avg fitness {ranked[-1]['avg_fitness']:.1f})."
            if len(ranked) > 1 else
            f"Prioritise '{best_cat}' features."
        )
    else:
        summary = "Insufficient strategy data for feature analysis."
        rec     = "Run backtest cycles to accumulate data."

    return _write_report(
        db,
        category        = "feature_analysis",
        title           = "Feature Category Performance Analysis",
        summary         = summary,
        findings        = mem,
        recommendations = rec,
    )


def report_regime_analysis(db: Session) -> StrategyResearchReport:
    """Q2: Which regimes generate the highest returns?"""
    affinity = regime_family_affinity(db)

    regime_sharpes: dict[str, list[float]] = {}
    for f, d in affinity.items():
        for reg, s in d.get("regime_sharpe", {}).items():
            regime_sharpes.setdefault(reg, []).append(s)

    regime_avgs = {
        r: round(sum(v) / len(v), 4)
        for r, v in regime_sharpes.items() if v
    }
    best_regime = max(regime_avgs, key=regime_avgs.get) if regime_avgs else "BULL"
    summary = (
        f"Best performing regime: {best_regime} "
        f"(avg Sharpe {regime_avgs.get(best_regime, 0):.3f} across all families)."
    )
    rec = (
        f"Focus evolution in {best_regime} regime. "
        "Consider generating more regime-adaptive strategies for underperforming regimes."
    )
    return _write_report(
        db,
        category        = "regime_analysis",
        title           = "Regime Performance Analysis",
        summary         = summary,
        findings        = {"affinity": affinity, "regime_averages": regime_avgs},
        recommendations = rec,
    )


def report_family_survival(db: Session) -> StrategyResearchReport:
    """Q3: Which strategy families survive the longest?"""
    survival  = family_survival_memory(db)
    graveyard = get_graveyard_summary(db)
    sorted_sv = sorted(survival.values(), key=lambda x: x["survival_rate"], reverse=True)

    if sorted_sv:
        best_fam  = sorted_sv[0]["family"]
        worst_fam = sorted_sv[-1]["family"] if len(sorted_sv) > 1 else best_fam
        summary   = (
            f"Most resilient family: '{best_fam}' "
            f"({sorted_sv[0]['survival_rate']:.1f}% survival rate). "
            f"Most fragile: '{worst_fam}' ({sorted_sv[-1]['survival_rate']:.1f}%)."
        )
        rec = (
            f"Increase cross-breeding with '{best_fam}' strategies. "
            f"Investigate why '{worst_fam}' strategies fail and extract lessons."
        )
    else:
        summary = "Insufficient family data."
        rec     = "Run full generation cycle."

    return _write_report(
        db,
        category        = "family_survival",
        title           = "Strategy Family Survival Analysis",
        summary         = summary,
        findings        = {"survival": survival, "graveyard": graveyard},
        recommendations = rec,
    )


def report_evolution_summary(db: Session) -> StrategyResearchReport:
    """Q4: What evolution operations produce the biggest fitness gains?"""
    tree    = evolution_tree_summary(db, days=90)
    by_op   = tree.get("by_operation", {})

    best_op = max(by_op, key=lambda k: by_op[k]["avg_fitness_delta"]) if by_op else "mutation"
    worst_op = min(by_op, key=lambda k: by_op[k]["avg_fitness_delta"]) if by_op else "crossover"
    best_data = by_op.get(best_op, {})

    summary = (
        f"Best operation: '{best_op}' "
        f"(avg fitness delta {best_data.get('avg_fitness_delta', 0):+.2f}, "
        f"{best_data.get('positive_pct', 0):.0f}% positive outcomes). "
        f"{tree['total_events']} evolution events in last 90 days."
    )
    rec = (
        f"Increase proportion of '{best_op}' operations in next cycle. "
        f"Reduce reliance on '{worst_op}' which shows lower average improvement."
    )
    return _write_report(
        db,
        category        = "evolution_summary",
        title           = "Evolution Operations Performance",
        summary         = summary,
        findings        = tree,
        recommendations = rec,
    )


def report_resurrection_candidates(db: Session) -> StrategyResearchReport:
    """Q5: Are there graveyard strategies worth retesting?"""
    candidates = get_resurrection_candidates(db)
    failure_patterns = failure_pattern_analysis(db)

    if candidates:
        best = candidates[0]
        summary = (
            f"{len(candidates)} resurrection candidate(s) found. "
            f"Top: {best['name']} (fitness {best['final_fitness']:.1f}, "
            f"died in {best['died_in_regime']}, current: {best['current_regime']})."
        )
        rec = (
            f"Consider retesting '{best['strategy_id']}' — it died in "
            f"{best['died_in_regime']} regime but current regime is {best['current_regime']}."
        )
    else:
        summary = "No viable resurrection candidates found."
        rec     = "Continue current generation cycle."

    return _write_report(
        db,
        category        = "resurrection",
        title           = "Graveyard Resurrection Analysis",
        summary         = summary,
        findings        = {"candidates": candidates, "failure_patterns": failure_patterns},
        recommendations = rec,
    )


def report_population_health(db: Session) -> StrategyResearchReport:
    """Q6: What is the current population health?"""
    stats    = get_population_stats(db)
    leaders  = get_leaderboard(db, top_n=5)

    summary = (
        f"Population: {stats['total']} strategies, "
        f"{stats['active_count']} active, "
        f"avg fitness {stats['avg_fitness']:.1f}, "
        f"max fitness {stats['max_fitness']:.1f}."
    )
    rec_parts = []
    if stats["total"] < 50:
        rec_parts.append("Run generation cycle to expand population.")
    if stats["avg_fitness"] < 40:
        rec_parts.append("Average fitness is low — consider broader mutation range.")
    if not rec_parts:
        rec_parts.append("Population is healthy. Continue evolution cycle.")

    return _write_report(
        db,
        category        = "population_health",
        title           = "Strategy Population Health Report",
        summary         = summary,
        findings        = {"stats": stats, "top5": leaders},
        recommendations = " ".join(rec_parts),
    )


def run_full_research(db: Session) -> dict:
    """
    Generate all research reports for today.
    Commits to DB.
    """
    reports = []
    for fn in [
        report_feature_analysis,
        report_regime_analysis,
        report_family_survival,
        report_evolution_summary,
        report_resurrection_candidates,
        report_population_health,
    ]:
        try:
            r = fn(db)
            reports.append({"category": r.category, "title": r.title})
        except Exception as exc:
            log.error("Research report failed (%s): %s", fn.__name__, exc)

    db.commit()
    log.info("Full research completed: %d reports generated", len(reports))
    return {"reports": reports, "date": str(date.today())}
