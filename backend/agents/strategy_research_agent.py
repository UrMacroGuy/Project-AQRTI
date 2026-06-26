"""
Strategy Research Agent
Deep analysis of the strategy ecosystem: population health, family breakdown,
decay detection, evolution efficiency, regime alignment, trade-level insights,
and resurrection candidates.

MAY NOT: activate strategies, modify DSL, deploy changes.
"""

from __future__ import annotations

import sys, os, json
from datetime import date, datetime, timedelta
from collections import Counter, defaultdict
from statistics import median, stdev

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from sqlalchemy import func
from sqlalchemy.orm import Session
from aqrti.database.models import (
    StrategyV2, StrategyGraveyard, MarketRegime, Prediction,
    StrategyEvolutionHistory, StrategyBacktestTrade, StrategyPerformance,
)
from aqrti.utils.logger import get_logger
from agents.agent_base import AgentBase
from agents.agent_registry import register_agent_class

log = get_logger("agent.strategy_research")


def _safe(val, default=0.0):
    return val if val is not None else default


class StrategyResearchAgent(AgentBase):
    agent_id    = "strategy_research"
    agent_type  = "strategy"
    name        = "Strategy Research Agent"
    description = (
        "Deep strategy ecosystem analysis: population health, family rankings, "
        "decay detection, evolution efficiency, regime alignment, trade patterns, "
        "and resurrection candidates."
    )

    def run(self, db: Session) -> dict:
        findings        = []
        recommendations = []
        today           = date.today()
        cutoff_7d       = today - timedelta(days=7)
        cutoff_30d      = today - timedelta(days=30)
        cutoff_60d      = today - timedelta(days=60)

        # ── Current Regime ──────────────────────────────────────────
        try:
            regime_row     = db.query(MarketRegime).order_by(MarketRegime.date.desc()).first()
            current_regime = regime_row.regime if regime_row else "UNKNOWN"
        except Exception:
            current_regime = "UNKNOWN"

        # ── Load all live strategies once ───────────────────────────
        try:
            all_live = db.query(StrategyV2).filter(
                StrategyV2.status.in_(["active", "promoted", "shadow", "candidate"])
            ).all()
        except Exception:
            all_live = []

        active   = [s for s in all_live if s.status in ("active", "promoted", "shadow")]
        scored   = [s for s in active   if s.fitness_score is not None]
        unscored = [s for s in all_live if s.fitness_score is None]

        # ═══════════════════════════════════════════════════════════
        # 1. POPULATION HEALTH SUMMARY
        # ═══════════════════════════════════════════════════════════
        try:
            candidates_count = db.query(StrategyV2).filter(StrategyV2.status == "candidate").count()
            graveyard_count  = db.query(StrategyGraveyard).count()
            promoted_count   = len([s for s in active if s.status in ("active", "promoted")])
            shadow_count     = len([s for s in active if s.status == "shadow"])

            if not active:
                findings.append({
                    "title":       "Strategy Population: Empty Active Tier",
                    "description": (
                        f"No active/shadow strategies found. {candidates_count} candidates "
                        f"and {graveyard_count} in graveyard. Population needs seeding."
                    ),
                    "evidence":    f"active=0, candidates={candidates_count}, graveyard={graveyard_count}",
                    "implication": "Run strategy generation cycle immediately.",
                    "urgency":     "high",
                    "subcategory": "population",
                    "category":    "strategy",
                })
                recommendations.append("Run strategy generation cycle to seed the population.")
            else:
                fitnesses   = [s.fitness_score for s in scored]
                avg_fitness = sum(fitnesses) / len(fitnesses) if fitnesses else 0.0
                top_fitness = max(fitnesses) if fitnesses else 0.0
                bot_fitness = min(fitnesses) if fitnesses else 0.0
                fit_median  = median(fitnesses) if fitnesses else 0.0
                fit_std     = stdev(fitnesses) if len(fitnesses) > 1 else 0.0

                health = (
                    "EXCELLENT" if avg_fitness >= 60 else
                    "GOOD"      if avg_fitness >= 50 else
                    "FAIR"      if avg_fitness >= 40 else
                    "POOR"
                )

                findings.append({
                    "title": (
                        f"Population Health: {health} — {len(active)} active "
                        f"(avg={avg_fitness:.1f}, top={top_fitness:.1f}, unscored={len(unscored)})"
                    ),
                    "description": (
                        f"Active tier: {promoted_count} promoted, {shadow_count} shadow. "
                        f"Fitness: avg={avg_fitness:.1f}, median={fit_median:.1f}, "
                        f"top={top_fitness:.1f}, bottom={bot_fitness:.1f}, σ={fit_std:.1f}. "
                        f"Backlog: {len(unscored)} unscored candidates. "
                        f"Graveyard: {graveyard_count} retired."
                    ),
                    "evidence": (
                        f"active={len(active)}, promoted={promoted_count}, shadow={shadow_count}, "
                        f"avg_fitness={avg_fitness:.1f}, unscored={len(unscored)}, graveyard={graveyard_count}"
                    ),
                    "implication": (
                        "Population is thriving — continue evolution." if health == "EXCELLENT" else
                        "Population is healthy — monitor top performers." if health == "GOOD" else
                        "Population fitness is slipping — schedule evolution cycle." if health == "FAIR" else
                        "Population is in poor health — urgent evolution cycle needed."
                    ),
                    "urgency":     "high" if health == "POOR" else "normal" if health == "FAIR" else "low",
                    "subcategory": "population",
                    "category":    "strategy",
                })
                if health in ("POOR", "FAIR"):
                    recommendations.append(f"Population avg fitness {avg_fitness:.1f} is below target 50 — run evolution cycle.")
                if len(unscored) > 500:
                    recommendations.append(f"{len(unscored)} unscored candidates — backtest backlog is high; strategy generation paused by scheduler.")
        except Exception as exc:
            log.debug("Population health query failed: %s", exc)

        # ═══════════════════════════════════════════════════════════
        # 2. FAMILY BREAKDOWN — strength ranking
        # ═══════════════════════════════════════════════════════════
        try:
            family_data: dict[str, dict] = defaultdict(lambda: {
                "count": 0, "fitnesses": [], "sharpes": [], "win_rates": [],
                "top_strategy": None, "top_fitness": 0.0,
            })
            for s in scored:
                fam = s.family or "hybrid"
                d   = family_data[fam]
                d["count"]     += 1
                d["fitnesses"].append(s.fitness_score)
                if s.sharpe    is not None: d["sharpes"].append(s.sharpe)
                if s.win_rate  is not None: d["win_rates"].append(s.win_rate)
                if s.fitness_score > d["top_fitness"]:
                    d["top_fitness"]  = s.fitness_score
                    d["top_strategy"] = s.name

            if family_data:
                ranked = sorted(
                    family_data.items(),
                    key=lambda kv: sum(kv[1]["fitnesses"]) / len(kv[1]["fitnesses"]) if kv[1]["fitnesses"] else 0,
                    reverse=True,
                )
                family_lines = []
                for fam, d in ranked:
                    avg_f  = sum(d["fitnesses"]) / len(d["fitnesses"]) if d["fitnesses"] else 0
                    avg_sh = sum(d["sharpes"])   / len(d["sharpes"])   if d["sharpes"]   else None
                    avg_wr = sum(d["win_rates"]) / len(d["win_rates"]) if d["win_rates"] else None
                    line   = (
                        f"{fam}: n={d['count']} avg_fit={avg_f:.1f} "
                        f"{'sharpe='+f'{avg_sh:.2f} ' if avg_sh else ''}"
                        f"{'wr='+f'{avg_wr:.1f}%' if avg_wr else ''}"
                        f" best={d['top_fitness']:.1f}({d['top_strategy'] or 'n/a'})"
                    )
                    family_lines.append(line)

                best_fam, best_d = ranked[0]
                weak_fam, weak_d = ranked[-1]
                best_avg = sum(best_d["fitnesses"]) / len(best_d["fitnesses"])
                weak_avg = sum(weak_d["fitnesses"]) / len(weak_d["fitnesses"]) if weak_d["fitnesses"] else 0

                findings.append({
                    "title": (
                        f"Family Rankings: {best_fam} leads (avg={best_avg:.1f}), "
                        f"{weak_fam} weakest (avg={weak_avg:.1f})"
                    ),
                    "description": "\n".join(family_lines),
                    "evidence":    f"families={len(ranked)}, best={best_fam}@{best_avg:.1f}, weak={weak_fam}@{weak_avg:.1f}",
                    "implication": (
                        f"Bias evolution toward '{best_fam}'. "
                        f"Investigate '{weak_fam}' — low avg fitness may signal concept failure."
                    ),
                    "urgency":     "normal",
                    "subcategory": "family_analysis",
                    "category":    "strategy",
                })
                if weak_avg < 30 and weak_d["count"] >= 3:
                    recommendations.append(
                        f"Family '{weak_fam}' avg fitness={weak_avg:.1f} (<30) with {weak_d['count']} strategies — "
                        "consider pausing generation for this family."
                    )
        except Exception as exc:
            log.debug("Family breakdown failed: %s", exc)

        # ═══════════════════════════════════════════════════════════
        # 3. DECAY DETECTION — strategies deteriorating
        # ═══════════════════════════════════════════════════════════
        try:
            decaying_critical = [s for s in scored if s.fitness_score < 20]
            decaying_high     = [s for s in scored if 20 <= s.fitness_score < 35]
            decaying_watch    = [s for s in scored if 35 <= s.fitness_score < 45]

            for s in sorted(decaying_critical, key=lambda x: x.fitness_score)[:3]:
                findings.append({
                    "title":       f"Critical Decay: {s.name} fitness={s.fitness_score:.1f} [{s.family}]",
                    "description": (
                        f"{s.name} ({s.family}) fitness={s.fitness_score:.1f}, "
                        f"sharpe={_safe(s.sharpe):.2f}, win_rate={_safe(s.win_rate):.1f}%, "
                        f"trades={s.trade_count or 0}, drawdown={_safe(s.max_drawdown):.1f}%."
                    ),
                    "evidence": (
                        f"fitness={s.fitness_score:.1f}, sharpe={s.sharpe}, "
                        f"win_rate={s.win_rate}, trades={s.trade_count}"
                    ),
                    "implication": "Retire immediately — this strategy is destroying value.",
                    "urgency":     "critical",
                    "subcategory": "decay",
                    "category":    "strategy",
                })

            if decaying_high:
                names = [f"{s.name}({s.fitness_score:.0f})" for s in sorted(decaying_high, key=lambda x: x.fitness_score)[:4]]
                findings.append({
                    "title":       f"Decay Alert: {len(decaying_high)} strategies fitness 20–35: {', '.join(names[:3])}",
                    "description": (
                        f"{len(decaying_high)} strategies in the danger zone (fitness 20–35). "
                        f"Top culprits: {', '.join(names)}."
                    ),
                    "evidence":    f"count={len(decaying_high)}, examples={names}",
                    "implication": "Schedule lifecycle sweep — these will likely retire on next scoring cycle.",
                    "urgency":     "high",
                    "subcategory": "decay",
                    "category":    "strategy",
                })
                recommendations.append(f"{len(decaying_high)} strategies in decay zone (20–35) — run lifecycle sweep.")

            if decaying_watch and not decaying_critical and not decaying_high:
                names = [s.name for s in decaying_watch[:3]]
                findings.append({
                    "title":       f"Watch List: {len(decaying_watch)} strategies in 35–45 range",
                    "description": f"{', '.join(names)} are below fitness target. Monitor closely.",
                    "evidence":    f"count={len(decaying_watch)}",
                    "implication": "These strategies need improvement or will decay further.",
                    "urgency":     "normal",
                    "subcategory": "decay",
                    "category":    "strategy",
                })
        except Exception as exc:
            log.debug("Decay detection failed: %s", exc)

        # ═══════════════════════════════════════════════════════════
        # 4. TOP PERFORMERS + TRADE QUALITY
        # ═══════════════════════════════════════════════════════════
        try:
            top5 = sorted(scored, key=lambda s: s.fitness_score, reverse=True)[:5]
            if top5:
                top_lines = []
                for s in top5:
                    top_lines.append(
                        f"  {s.name} [{s.family}] fit={s.fitness_score:.1f} "
                        f"sharpe={_safe(s.sharpe):.2f} wr={_safe(s.win_rate):.1f}% "
                        f"trades={s.trade_count or 0} dd={_safe(s.max_drawdown):.1f}%"
                    )
                best = top5[0]
                findings.append({
                    "title":       f"Top Performer: {best.name} [{best.family}] fitness={best.fitness_score:.1f}",
                    "description": "Top 5 strategies by fitness:\n" + "\n".join(top_lines),
                    "evidence":    (
                        f"best={best.name}, fitness={best.fitness_score:.1f}, "
                        f"sharpe={best.sharpe}, win_rate={best.win_rate}, trades={best.trade_count}"
                    ),
                    "implication": (
                        f"Prioritise '{best.family}' family in evolution. "
                        f"{'Excellent Sharpe — strong risk-adjusted returns.' if _safe(best.sharpe) >= 1.5 else ''}"
                    ),
                    "urgency":     "low",
                    "subcategory": "top_performers",
                    "category":    "strategy",
                })

                # Sharpe quality check
                high_sharpe = [s for s in scored if _safe(s.sharpe) >= 2.0]
                if high_sharpe:
                    findings.append({
                        "title":       f"Elite Sharpe Club: {len(high_sharpe)} strategies with Sharpe ≥2.0",
                        "description": ", ".join(f"{s.name}({s.sharpe:.2f})" for s in sorted(high_sharpe, key=lambda x: _safe(x.sharpe), reverse=True)[:5]),
                        "evidence":    f"count={len(high_sharpe)}, best_sharpe={max(_safe(s.sharpe) for s in high_sharpe):.2f}",
                        "implication": "These strategies have institutional-grade risk-adjusted returns. Protect them.",
                        "urgency":     "low",
                        "subcategory": "top_performers",
                        "category":    "strategy",
                    })
        except Exception as exc:
            log.debug("Top performers analysis failed: %s", exc)

        # ═══════════════════════════════════════════════════════════
        # 5. REGIME ALIGNMENT
        # ═══════════════════════════════════════════════════════════
        try:
            if current_regime != "UNKNOWN" and active:
                regime_sharpe_attr = {
                    "BULL":     "bull_sharpe",
                    "BEAR":     "bear_sharpe",
                    "SIDEWAYS": "sideways_sharpe",
                    "VOLATILE": "volatile_sharpe",
                }.get(current_regime)

                mismatched    = []
                regime_suited = []
                for s in active:
                    try:
                        allowed = json.loads(s.allowed_regimes) if s.allowed_regimes else []
                        if allowed and current_regime not in allowed:
                            mismatched.append(s)
                        elif allowed and current_regime in allowed:
                            regime_suited.append(s)
                    except Exception:
                        pass

                if mismatched:
                    findings.append({
                        "title":       f"Regime Misalignment: {len(mismatched)} strategies unsuited for {current_regime}",
                        "description": (
                            f"Current regime is {current_regime}. "
                            f"{len(mismatched)} active strategies not configured for it: "
                            f"{', '.join(s.name for s in mismatched[:4])}."
                        ),
                        "evidence":    f"regime={current_regime}, mismatched={len(mismatched)}, suited={len(regime_suited)}",
                        "implication": "These strategies may generate unreliable signals. Consider regime-gating in DSL.",
                        "urgency":     "high" if len(mismatched) > len(regime_suited) else "normal",
                        "subcategory": "regime_mismatch",
                        "category":    "strategy",
                    })
                    if len(mismatched) > len(regime_suited):
                        recommendations.append(
                            f"Majority of strategies ({len(mismatched)}) not suited for {current_regime} — "
                            "generate regime-specific strategies."
                        )

                # Best strategy for current regime by regime-specific Sharpe
                if regime_sharpe_attr:
                    regime_perf = [
                        (s, getattr(s, regime_sharpe_attr))
                        for s in scored
                        if getattr(s, regime_sharpe_attr) is not None
                    ]
                    if regime_perf:
                        best_regime_strat, best_regime_sharpe = max(regime_perf, key=lambda x: x[1])
                        findings.append({
                            "title":       f"Best for {current_regime}: {best_regime_strat.name} (regime Sharpe={best_regime_sharpe:.2f})",
                            "description": (
                                f"In {current_regime} regimes, {best_regime_strat.name} [{best_regime_strat.family}] "
                                f"achieves Sharpe={best_regime_sharpe:.2f} specifically. "
                                f"Overall fitness={best_regime_strat.fitness_score:.1f}."
                            ),
                            "evidence":    f"regime_sharpe={best_regime_sharpe:.2f}, strategy={best_regime_strat.name}",
                            "implication": f"Weight {best_regime_strat.name} higher in paper trading signal selection.",
                            "urgency":     "low",
                            "subcategory": "regime_alignment",
                            "category":    "strategy",
                        })
        except Exception as exc:
            log.debug("Regime alignment analysis failed: %s", exc)

        # ═══════════════════════════════════════════════════════════
        # 6. EVOLUTION EFFICIENCY (last 30 days)
        # ═══════════════════════════════════════════════════════════
        try:
            evo_rows = (
                db.query(StrategyEvolutionHistory)
                .filter(StrategyEvolutionHistory.evolved_date >= cutoff_30d)
                .all()
            )
            if evo_rows:
                mutations   = [r for r in evo_rows if r.operation == "mutation"]
                crossovers  = [r for r in evo_rows if r.operation == "crossover"]
                retirements = [r for r in evo_rows if r.operation == "retire"]
                improving   = [r for r in evo_rows if r.fitness_delta is not None and r.fitness_delta > 0]
                worsening   = [r for r in evo_rows if r.fitness_delta is not None and r.fitness_delta < 0]

                total_ops = len(evo_rows)
                improve_rate = len(improving) / total_ops * 100 if total_ops else 0
                avg_delta    = (
                    sum(r.fitness_delta for r in evo_rows if r.fitness_delta is not None) /
                    max(1, sum(1 for r in evo_rows if r.fitness_delta is not None))
                )

                # Best mutation op by avg delta
                op_deltas: dict[str, list[float]] = defaultdict(list)
                for r in evo_rows:
                    if r.fitness_delta is not None:
                        op_deltas[r.operation].append(r.fitness_delta)
                best_op = max(op_deltas, key=lambda k: sum(op_deltas[k]) / len(op_deltas[k])) if op_deltas else None
                best_op_avg = sum(op_deltas[best_op]) / len(op_deltas[best_op]) if best_op else 0

                findings.append({
                    "title": (
                        f"Evolution (30d): {total_ops} ops, {improve_rate:.0f}% positive, "
                        f"avg delta={avg_delta:+.1f}"
                    ),
                    "description": (
                        f"30-day evolution stats: {len(mutations)} mutations, {len(crossovers)} crossovers, "
                        f"{len(retirements)} retirements. "
                        f"{len(improving)} improved ({improve_rate:.0f}%), {len(worsening)} worsened. "
                        f"Best operation: '{best_op}' avg Δfitness={best_op_avg:+.1f}."
                    ),
                    "evidence": (
                        f"ops={total_ops}, improve_rate={improve_rate:.1f}%, "
                        f"avg_delta={avg_delta:.2f}, best_op={best_op}"
                    ),
                    "implication": (
                        f"Evolution is {'effective' if improve_rate >= 55 else 'inefficient' if improve_rate < 40 else 'marginal'}. "
                        f"Bias toward '{best_op}' operations." if best_op else ""
                    ),
                    "urgency":     "high" if improve_rate < 35 else "normal" if improve_rate < 50 else "low",
                    "subcategory": "evolution",
                    "category":    "strategy",
                })
                if improve_rate < 35:
                    recommendations.append(
                        f"Evolution improvement rate is only {improve_rate:.0f}% — "
                        "review mutation parameters and parent selection quality."
                    )
        except Exception as exc:
            log.debug("Evolution efficiency analysis failed: %s", exc)

        # ═══════════════════════════════════════════════════════════
        # 7. BACKTEST TRADE PATTERNS (last 30 days of trades)
        # ═══════════════════════════════════════════════════════════
        try:
            recent_trades = (
                db.query(StrategyBacktestTrade)
                .filter(StrategyBacktestTrade.entry_date >= cutoff_30d)
                .all()
            )
            if len(recent_trades) >= 20:
                wins       = [t for t in recent_trades if t.pnl_pct is not None and t.pnl_pct > 0]
                losses     = [t for t in recent_trades if t.pnl_pct is not None and t.pnl_pct <= 0]
                win_rate   = len(wins) / len(recent_trades) * 100 if recent_trades else 0
                avg_win    = sum(t.pnl_pct for t in wins)   / len(wins)   if wins   else 0
                avg_loss   = sum(t.pnl_pct for t in losses) / len(losses) if losses else 0
                expectancy = (win_rate / 100 * avg_win) + ((1 - win_rate / 100) * avg_loss)

                # Best symbols
                sym_wins: dict[str, int] = Counter(t.symbol for t in wins)
                sym_loss: dict[str, int] = Counter(t.symbol for t in losses)
                best_sym = sym_wins.most_common(1)[0] if sym_wins else None
                worst_sym = sym_loss.most_common(1)[0] if sym_loss else None

                # Stop-loss vs target vs time exit breakdown
                exit_counts = Counter(t.exit_reason for t in recent_trades if t.exit_reason)

                findings.append({
                    "title": (
                        f"Backtest Trades (30d): {len(recent_trades)} trades, "
                        f"win_rate={win_rate:.1f}%, expectancy={expectancy:+.2f}%"
                    ),
                    "description": (
                        f"Trade quality: {len(recent_trades)} trades, win_rate={win_rate:.1f}%, "
                        f"avg_win={avg_win:+.2f}%, avg_loss={avg_loss:.2f}%, expectancy={expectancy:+.3f}%. "
                        f"Best symbol: {best_sym[0]} ({best_sym[1]} wins). "
                        f"Worst symbol: {worst_sym[0]} ({worst_sym[1]} losses). "
                        f"Exits: {dict(exit_counts.most_common(3))}."
                    ),
                    "evidence": (
                        f"trades={len(recent_trades)}, win_rate={win_rate:.1f}%, "
                        f"expectancy={expectancy:.4f}, best_sym={best_sym}"
                    ),
                    "implication": (
                        "Positive expectancy — strategies are generating edge." if expectancy > 0 else
                        "Negative expectancy — strategies are net losers on average. Review entry rules."
                    ),
                    "urgency":     "high" if expectancy < -0.5 else "normal" if expectancy < 0 else "low",
                    "subcategory": "trade_quality",
                    "category":    "strategy",
                })
                if expectancy < 0:
                    recommendations.append(
                        f"Negative expectancy ({expectancy:.3f}%) across 30d backtest trades — "
                        "tighten entry conditions or raise confidence floor."
                    )

                # Stop loss dominance check
                stop_exits = exit_counts.get("stop_loss", 0) + exit_counts.get("stop", 0)
                target_exits = exit_counts.get("target", 0) + exit_counts.get("target_hit", 0)
                if stop_exits > 0 and target_exits > 0:
                    sl_ratio = stop_exits / (stop_exits + target_exits)
                    if sl_ratio > 0.6:
                        findings.append({
                            "title":       f"Stop-Loss Dominance: {sl_ratio*100:.0f}% of exits are stops",
                            "description": (
                                f"Stop-losses account for {stop_exits}/{stop_exits+target_exits} exits. "
                                "Strategies are being cut too often — targets may be set too far out."
                            ),
                            "evidence":    f"stop_exits={stop_exits}, target_exits={target_exits}",
                            "implication": "Tighten targets or widen stops. Risk/reward ratio likely degraded.",
                            "urgency":     "normal",
                            "subcategory": "trade_quality",
                            "category":    "strategy",
                        })
        except Exception as exc:
            log.debug("Backtest trade pattern analysis failed: %s", exc)

        # ═══════════════════════════════════════════════════════════
        # 8. RESURRECTION CANDIDATES
        # ═══════════════════════════════════════════════════════════
        try:
            if current_regime != "UNKNOWN":
                graves = (
                    db.query(StrategyGraveyard)
                    .filter(
                        StrategyGraveyard.regime_at_death != current_regime,
                        StrategyGraveyard.final_fitness   >= 45,
                        StrategyGraveyard.failure_reason  != "manual",
                    )
                    .order_by(StrategyGraveyard.final_fitness.desc())
                    .limit(5)
                    .all()
                )
                if graves:
                    lines = [
                        f"  {g.name} [{g.family}] fit={g.final_fitness:.1f} "
                        f"died_in={g.regime_at_death} trades={g.trade_count or '?'}"
                        for g in graves
                    ]
                    best = graves[0]
                    findings.append({
                        "title": (
                            f"Resurrection Candidates: {len(graves)} strategies died in "
                            f"different regime, best: {best.name} (fit={best.final_fitness:.1f})"
                        ),
                        "description": (
                            f"Current regime is {current_regime}. "
                            f"{len(graves)} graveyard strategies died under {best.regime_at_death} "
                            "conditions with fitness ≥45 — worth retesting now.\n" +
                            "\n".join(lines)
                        ),
                        "evidence": (
                            f"candidates={len(graves)}, best={best.name}, "
                            f"final_fitness={best.final_fitness:.1f}, died_regime={best.regime_at_death}"
                        ),
                        "implication": (
                            f"Reintroduce {best.name} as a shadow strategy — "
                            "it failed in {best.regime_at_death}, not {current_regime}."
                        ),
                        "urgency":     "normal",
                        "subcategory": "resurrection",
                        "category":    "strategy",
                    })
                    recommendations.append(
                        f"Retest {best.name} (fitness={best.final_fitness:.1f}) — "
                        f"died in {best.regime_at_death} regime, not current {current_regime}."
                    )
        except Exception as exc:
            log.debug("Resurrection analysis failed: %s", exc)

        # ═══════════════════════════════════════════════════════════
        # 9. SIGNAL PERSISTENCE (prediction model alignment)
        # ═══════════════════════════════════════════════════════════
        try:
            recent_preds = (
                db.query(Prediction)
                .filter(Prediction.date >= cutoff_30d)
                .all()
            )
            if recent_preds:
                # Directional consistency per symbol
                sym_dirs: dict[str, Counter] = defaultdict(Counter)
                for p in recent_preds:
                    if p.symbol and p.direction:
                        sym_dirs[p.symbol][p.direction] += 1

                persistent = [
                    (sym, dirs.most_common(1)[0][0], dirs.most_common(1)[0][1], sum(dirs.values()))
                    for sym, dirs in sym_dirs.items()
                    if sum(dirs.values()) >= 8 and dirs.most_common(1)[0][1] / sum(dirs.values()) >= 0.75
                ]
                if persistent:
                    persistent.sort(key=lambda x: x[2], reverse=True)
                    sym, direction, count, total = persistent[0]
                    findings.append({
                        "title":       f"Persistent Signal: {sym} {direction} {count}/{total} signals (30d)",
                        "description": (
                            f"{sym} has been {direction.lower()} {count} out of {total} times in 30 days "
                            f"({count/total*100:.0f}% directional consistency). "
                            f"{len(persistent)} total persistent-signal stocks."
                        ),
                        "evidence":    f"symbol={sym}, direction={direction}, count={count}, total={total}",
                        "implication": (
                            f"Build or evolve a dedicated strategy for {sym} "
                            f"{direction.lower()} patterns — strong model conviction."
                        ),
                        "urgency":     "low",
                        "subcategory": "signal_persistence",
                        "category":    "strategy",
                    })

                # Live prediction accuracy
                evaluated = [p for p in recent_preds if p.success is not None]
                if len(evaluated) >= 10:
                    correct  = sum(1 for p in evaluated if p.success)
                    live_wr  = correct / len(evaluated) * 100
                    bull_ev  = [p for p in evaluated if p.direction == "Bullish"]
                    bear_ev  = [p for p in evaluated if p.direction == "Bearish"]
                    bull_wr  = sum(1 for p in bull_ev if p.success) / len(bull_ev) * 100 if bull_ev else None
                    bear_wr  = sum(1 for p in bear_ev if p.success) / len(bear_ev) * 100 if bear_ev else None

                    findings.append({
                        "title": (
                            f"Live Prediction Accuracy: {live_wr:.1f}% ({correct}/{len(evaluated)}) — "
                            f"Bull {bull_wr:.1f}% Bear {bear_wr:.1f}%"
                            if bull_wr is not None and bear_wr is not None else
                            f"Live Prediction Accuracy: {live_wr:.1f}% ({correct}/{len(evaluated)})"
                        ),
                        "description": (
                            f"Evaluated {len(evaluated)} predictions in 30d: {correct} correct ({live_wr:.1f}%). "
                            + (f"Bullish: {bull_wr:.1f}% ({len(bull_ev)} signals). " if bull_wr is not None else "")
                            + (f"Bearish: {bear_wr:.1f}% ({len(bear_ev)} signals)." if bear_wr is not None else "")
                        ),
                        "evidence":    f"live_wr={live_wr:.1f}%, bull_wr={bull_wr}, bear_wr={bear_wr}, n={len(evaluated)}",
                        "implication": (
                            "Model accuracy is strong — strategy signals are well-grounded." if live_wr >= 60 else
                            "Model accuracy is borderline — strategies relying on ML signals need caution." if live_wr >= 50 else
                            "Model accuracy below 50% — model needs retraining before strategies can be trusted."
                        ),
                        "urgency":     "high" if live_wr < 50 else "normal" if live_wr < 58 else "low",
                        "subcategory": "prediction_accuracy",
                        "category":    "strategy",
                    })
                    if live_wr < 50:
                        recommendations.append(
                            f"Live prediction accuracy only {live_wr:.1f}% (<50%) — trigger model retraining."
                        )
        except Exception as exc:
            log.debug("Signal persistence analysis failed: %s", exc)

        # ── Fallback if nothing fired ────────────────────────────────
        if not findings:
            findings.append({
                "title":       "Strategy System Baseline",
                "description": "Strategy tables accessible. No anomalies detected.",
                "evidence":    f"active={len(active)}, scored={len(scored)}",
                "implication": "System operating normally.",
                "urgency":     "low",
                "subcategory": "baseline",
                "category":    "strategy",
            })

        urgency = (
            "critical" if any(f.get("urgency") == "critical" for f in findings) else
            "high"     if any(f.get("urgency") == "high"     for f in findings) else
            "normal"
        )
        summary = (
            f"Strategy research: {len(findings)} findings. "
            f"Regime: {current_regime}. "
            f"Active: {len(active)} ({len(scored)} scored). "
            f"Urgency: {urgency}."
        )

        return {
            "title":           f"Strategy Research — {today}",
            "summary":         summary,
            "findings":        findings,
            "recommendations": recommendations,
            "urgency":         urgency,
            "metadata": {
                "current_regime":   current_regime,
                "active_count":     len(active),
                "scored_count":     len(scored),
                "unscored_count":   len(unscored),
            },
        }


register_agent_class(StrategyResearchAgent)
