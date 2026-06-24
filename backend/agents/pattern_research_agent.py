"""
Pattern Research Agent (7G)
Discovers new patterns, tracks pattern drift, failures, and opportunities.

When pattern_outcomes / pattern_matches are empty (fresh install), pivots to
price-based pattern detection from daily_prices:
  - 52-week highs and lows
  - RSI-like overbought / oversold signals (computed from close prices)
  - Volume spikes vs 20-day average

MAY NOT: modify models, activate strategies, change pattern thresholds.
"""

from __future__ import annotations

import sys, os, math
from datetime import date, timedelta
from collections import defaultdict, Counter

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from sqlalchemy.orm import Session
from aqrti.database.models import PatternOutcome, PatternMatch, KnowledgeScore, DailyPrice
from aqrti.utils.logger import get_logger
from agents.agent_base import AgentBase
from agents.agent_registry import register_agent_class

log = get_logger("agent.pattern_research")

RSI_PERIOD       = 14
RSI_OVERBOUGHT   = 70.0
RSI_OVERSOLD     = 30.0
VOLUME_SPIKE_X   = 2.0   # multiplier vs 20d avg
HIGH_52W_LOOKBACK = 252  # trading days to define a 52-week high/low


def _compute_rsi(closes: list[float], period: int = RSI_PERIOD) -> float | None:
    """Compute RSI from a list of closing prices (oldest first).
    Returns the most recent RSI value, or None if insufficient data."""
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gains.append(max(delta, 0))
        losses.append(max(-delta, 0))
    # Wilder smoothing
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs  = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)


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
        ml_patterns_available = False

        # ── 1. Pattern Hit Rate (ML patterns) ────────────────────
        try:
            recent_outcomes = (
                db.query(PatternOutcome)
                .filter(PatternOutcome.prediction_date >= cutoff_30d)
                .all()
            )
            if recent_outcomes:
                ml_patterns_available = True
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

        # ── 2. Nifty Outperformance Rate (ML patterns) ───────────
        try:
            if ml_patterns_available:
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

        # ── 3. Pattern Volume / Coverage (ML patterns) ───────────
        try:
            recent_matches = (
                db.query(PatternMatch)
                .filter(PatternMatch.search_date >= cutoff_7d)
                .count()
            )
            if recent_matches < 5:
                findings.append({
                    "title":       f"Low ML Pattern Activity: {recent_matches} matches in 7 days",
                    "description": f"Only {recent_matches} ML pattern matches recorded in the last 7 days.",
                    "evidence":    f"recent_matches={recent_matches}",
                    "implication": "Pattern matching may not be running or market is structurally different.",
                    "urgency":     "normal" if ml_patterns_available else "low",
                    "subcategory": "coverage",
                })
        except Exception as exc:
            log.debug("Pattern coverage query skipped: %s", exc)

        # ── 4. Pattern Drift by Regime (ML patterns) ─────────────
        try:
            if ml_patterns_available:
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

        # ── 5. Price-based pattern detection (always runs) ───────
        try:
            lookback_days = HIGH_52W_LOOKBACK + 5  # buffer
            cutoff_1y     = date.today() - timedelta(days=lookback_days)

            price_rows = (
                db.query(DailyPrice.symbol, DailyPrice.date, DailyPrice.close, DailyPrice.volume)
                .filter(DailyPrice.date >= cutoff_1y)
                .order_by(DailyPrice.symbol, DailyPrice.date.asc())
                .all()
            )

            if price_rows:
                sym_data: dict[str, list] = defaultdict(list)
                for row in price_rows:
                    sym_data[row.symbol].append({
                        "date": row.date,
                        "close": row.close,
                        "volume": row.volume,
                    })

                highs_52w   = []
                lows_52w    = []
                overbought  = []
                oversold    = []
                vol_spikes  = []

                for sym, history in sym_data.items():
                    if len(history) < 20:
                        continue

                    closes  = [h["close"] for h in history if h["close"]]
                    volumes = [h["volume"] for h in history if h["volume"] and h["volume"] > 0]
                    if not closes:
                        continue

                    latest_close  = closes[-1]
                    latest_date   = history[-1]["date"]

                    # 52-week high / low detection
                    period_closes = closes[-HIGH_52W_LOOKBACK:] if len(closes) >= HIGH_52W_LOOKBACK else closes
                    high_52w      = max(period_closes)
                    low_52w       = min(period_closes)

                    # Within 1% of 52-week high
                    if high_52w > 0 and latest_close >= high_52w * 0.99:
                        highs_52w.append((sym, latest_close, high_52w, latest_date))
                    # Within 1% of 52-week low
                    elif low_52w > 0 and latest_close <= low_52w * 1.01:
                        lows_52w.append((sym, latest_close, low_52w, latest_date))

                    # RSI
                    rsi_window = closes[-(RSI_PERIOD + 10):]  # use recent 24 closes for RSI
                    rsi = _compute_rsi(rsi_window)
                    if rsi is not None:
                        if rsi >= RSI_OVERBOUGHT:
                            overbought.append((sym, rsi, latest_close, latest_date))
                        elif rsi <= RSI_OVERSOLD:
                            oversold.append((sym, rsi, latest_close, latest_date))

                    # Volume spike vs 20d average
                    if len(volumes) >= 5:
                        latest_vol = volumes[-1]
                        avg_vol    = sum(volumes[:-1]) / len(volumes[:-1])
                        if avg_vol > 0 and latest_vol / avg_vol >= VOLUME_SPIKE_X:
                            vol_spikes.append((sym, latest_vol / avg_vol, latest_date))

                # Report 52-week highs
                if highs_52w:
                    syms = ", ".join(s for s, *_ in highs_52w[:5])
                    findings.append({
                        "title":       f"52-Week Highs: {len(highs_52w)} stocks at or near peak",
                        "description": (
                            f"{len(highs_52w)} stocks are trading at or within 1% of their 52-week high: {syms}. "
                            "These are breakout candidates."
                        ),
                        "evidence":    f"highs_52w_count={len(highs_52w)}, top_symbols={syms}",
                        "implication": "Breakout momentum pattern — consider trend-following entries with confirmation.",
                        "urgency":     "normal",
                        "subcategory": "price_pattern",
                    })
                    recommendations.append(f"{len(highs_52w)} stocks near 52-week highs — monitor for breakout confirmation.")

                # Report 52-week lows
                if lows_52w:
                    syms = ", ".join(s for s, *_ in lows_52w[:5])
                    findings.append({
                        "title":       f"52-Week Lows: {len(lows_52w)} stocks near annual floor",
                        "description": (
                            f"{len(lows_52w)} stocks are at or within 1% of their 52-week low: {syms}. "
                            "Possible capitulation or value trap."
                        ),
                        "evidence":    f"lows_52w_count={len(lows_52w)}, symbols={syms}",
                        "implication": "High-risk zone — require strong fundamental support before entry.",
                        "urgency":     "normal",
                        "subcategory": "price_pattern",
                    })

                # Report RSI overbought
                if overbought:
                    ob_sorted = sorted(overbought, key=lambda x: x[1], reverse=True)
                    ob_desc   = ", ".join(f"{s} (RSI={r:.0f})" for s, r, *_ in ob_sorted[:5])
                    findings.append({
                        "title":       f"RSI Overbought: {len(overbought)} stocks ≥{RSI_OVERBOUGHT:.0f}",
                        "description": f"Stocks with RSI ≥{RSI_OVERBOUGHT:.0f}: {ob_desc}. Mean-reversion risk elevated.",
                        "evidence":    f"overbought_count={len(overbought)}, top={ob_desc}",
                        "implication": "Exercise caution on long entries; pullback probability is elevated.",
                        "urgency":     "normal",
                        "subcategory": "rsi_signal",
                    })

                # Report RSI oversold
                if oversold:
                    os_sorted = sorted(oversold, key=lambda x: x[1])
                    os_desc   = ", ".join(f"{s} (RSI={r:.0f})" for s, r, *_ in os_sorted[:5])
                    findings.append({
                        "title":       f"RSI Oversold: {len(oversold)} stocks ≤{RSI_OVERSOLD:.0f}",
                        "description": f"Stocks with RSI ≤{RSI_OVERSOLD:.0f}: {os_desc}. Potential mean-reversion bounce.",
                        "evidence":    f"oversold_count={len(oversold)}, symbols={os_desc}",
                        "implication": "Oversold stocks may offer mean-reversion entries with tight stops.",
                        "urgency":     "low",
                        "subcategory": "rsi_signal",
                    })
                    recommendations.append(f"{len(oversold)} oversold stocks — screen for mean-reversion setups.")

                # Report volume spikes
                if vol_spikes:
                    vs_sorted = sorted(vol_spikes, key=lambda x: x[1], reverse=True)
                    vs_desc   = ", ".join(f"{s} ({ratio:.1f}x)" for s, ratio, _ in vs_sorted[:5])
                    findings.append({
                        "title":       f"Volume Spikes: {len(vol_spikes)} stocks with >{VOLUME_SPIKE_X:.0f}× avg volume",
                        "description": f"Unusual trading volume: {vs_desc}. High volume often precedes directional moves.",
                        "evidence":    f"spike_count={len(vol_spikes)}, top_spikes={vs_desc}",
                        "implication": "Monitor these stocks for breakout or breakdown confirmation.",
                        "urgency":     "normal",
                        "subcategory": "volume_pattern",
                    })

        except Exception as exc:
            log.debug("Price-based pattern detection failed: %s", exc)

        # ── Fallback ──────────────────────────────────────────────
        if not findings:
            findings.append({
                "title":       "Pattern System Initialising — No Data Available",
                "description": "pattern_outcomes, pattern_matches, and daily_prices are all empty or insufficient.",
                "evidence":    "pattern_rows=0, price_rows=0",
                "implication": "Complete data ingestion and ML pattern matching to enable pattern analysis.",
                "urgency":     "low",
                "subcategory": "data_coverage",
            })

        summary = (
            f"Pattern research: {len(findings)} findings. "
            f"{'[!] Quality issues detected.' if any(f['urgency'] in ('high', 'critical') for f in findings) else 'Patterns operating normally.'}"
        )
        urgency = (
            "high"   if any(f["urgency"] == "high"   for f in findings) else
            "normal"
        )

        return {
            "title":           f"Pattern Research — {date.today()}",
            "summary":         summary,
            "findings":        findings,
            "recommendations": recommendations,
            "urgency":         urgency,
        }


register_agent_class(PatternResearchAgent)
