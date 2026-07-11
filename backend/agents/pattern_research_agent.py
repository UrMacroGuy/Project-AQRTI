"""
Pattern Research Agent
Discovers price patterns, tracks pattern hit rates, and detects technical setups.
Falls back to direct price-pattern computation when pattern DB tables are empty.

MAY NOT: modify models, activate strategies, change pattern thresholds.
"""

from __future__ import annotations

import sys, os, math
from datetime import date, timedelta
from collections import Counter

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from sqlalchemy.orm import Session
from aqrti.database.models import PatternMatch, DailyPrice, IndexData, Stock
from aqrti.utils.logger import get_logger
from agents.agent_base import AgentBase
from agents.agent_registry import register_agent_class

log = get_logger("agent.pattern_research")


def _stock_universe(db: Session) -> list[str]:
    """DB-driven active universe (curated 12-symbol set, 2026-07 prune)."""
    return [s.symbol for s in db.query(Stock.symbol).filter(Stock.active == True).all()]


def _simple_rsi(closes: list[float], period: int = 14) -> float | None:
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, period + 1):
        delta = closes[-(period + 1 - i)] - closes[-(period + 2 - i)]
        (gains if delta > 0 else losses).append(abs(delta))
    avg_gain = sum(gains) / period if gains else 0
    avg_loss = sum(losses) / period if losses else 1e-9
    rs  = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _ema(closes: list[float], period: int) -> float | None:
    if len(closes) < period:
        return None
    k   = 2 / (period + 1)
    ema = sum(closes[:period]) / period
    for c in closes[period:]:
        ema = c * k + ema * (1 - k)
    return ema


class PatternResearchAgent(AgentBase):
    agent_id    = "pattern_research"
    agent_type  = "pattern"
    name        = "Pattern Research Agent"
    description = "Discovers price patterns, RSI extremes, EMA breakouts, and technical setups from live price data."

    def run(self, db: Session) -> dict:
        findings        = []
        recommendations = []
        today           = date.today()
        cutoff_30d      = today - timedelta(days=30)
        cutoff_7d       = today - timedelta(days=7)
        cutoff_52w      = today - timedelta(weeks=52)

        # ── 1. Pattern DB Hit Rate (if tables populated) ──────────
        pattern_db_populated = False
        try:
            recent_matches = db.query(PatternMatch).filter(PatternMatch.search_date >= cutoff_7d).count()
            if recent_matches > 0:
                pattern_db_populated = True
                if recent_matches < 5:
                    findings.append({
                        "title":       f"Low Pattern Activity: {recent_matches} matches in 7 days",
                        "description": f"Only {recent_matches} pattern matches recorded in the last 7 days.",
                        "evidence":    f"recent_matches={recent_matches}",
                        "implication": "Pattern matching may not be running or market structure has changed.",
                        "urgency":     "normal",
                        "subcategory": "coverage",
                    })
                else:
                    findings.append({
                        "title":       f"Pattern Engine Active: {recent_matches} matches in 7 days",
                        "description": f"Pattern matching engine generated {recent_matches} results in the last 7 days.",
                        "evidence":    f"pattern_matches={recent_matches}, period=7d",
                        "implication": "Pattern engine is running normally.",
                        "urgency":     "low",
                        "subcategory": "coverage",
                    })
        except Exception as exc:
            log.debug("Pattern match count skipped: %s", exc)

        # ── 2. RSI Extremes ───────────────────────────────────────
        try:
            overbought = []
            oversold   = []
            universe   = _stock_universe(db)

            for symbol in universe:
                rows = (
                    db.query(DailyPrice.close, DailyPrice.date)
                    .filter(DailyPrice.symbol == symbol, DailyPrice.date >= cutoff_30d)
                    .order_by(DailyPrice.date.asc())
                    .all()
                )
                if len(rows) < 16:
                    continue
                closes = [r.close for r in rows if r.close]
                rsi = _simple_rsi(closes, period=14)
                if rsi is None:
                    continue
                if rsi >= 75:
                    overbought.append((symbol, rsi, rows[-1].date))
                elif rsi <= 25:
                    oversold.append((symbol, rsi, rows[-1].date))

            if overbought:
                overbought.sort(key=lambda x: x[1], reverse=True)
                top = overbought[:4]
                sym_list = [f"{s[0]} ({s[1]:.0f})" for s in top]
                findings.append({
                    "title":       f"RSI Overbought: {len(overbought)} stocks (RSI≥75) — {', '.join(sym_list[:3])}",
                    "description": (
                        f"{len(overbought)} stocks are in overbought territory (RSI≥75): {sym_list}. "
                        "Mean-reversion or pause likely."
                    ),
                    "evidence":    f"overbought_stocks={[s[0] for s in top]}, rsi_values={[round(s[1]) for s in top]}",
                    "implication": "Overbought stocks are vulnerable to pullbacks. Avoid new longs at these levels.",
                    "urgency":     "normal" if len(overbought) >= 5 else "low",
                    "subcategory": "rsi_overbought",
                })
                recommendations.append(f"Caution on new longs in overbought stocks: {', '.join(s[0] for s in top[:3])}.")

            if oversold:
                oversold.sort(key=lambda x: x[1])
                bot = oversold[:4]
                sym_list = [f"{s[0]} ({s[1]:.0f})" for s in bot]
                findings.append({
                    "title":       f"RSI Oversold: {len(oversold)} stocks (RSI≤25) — {', '.join(sym_list[:3])}",
                    "description": (
                        f"{len(oversold)} stocks are in oversold territory (RSI≤25): {sym_list}. "
                        "Potential bounce candidates."
                    ),
                    "evidence":    f"oversold_stocks={[s[0] for s in bot]}, rsi_values={[round(s[1]) for s in bot]}",
                    "implication": "Oversold stocks may produce mean-reversion long signals soon.",
                    "urgency":     "normal" if len(oversold) >= 3 else "low",
                    "subcategory": "rsi_oversold",
                })
                recommendations.append(f"Watch for reversal signals in oversold stocks: {', '.join(s[0] for s in bot[:3])}.")
        except Exception as exc:
            log.debug("RSI analysis skipped: %s", exc)

        # ── 3. EMA Breakouts ─────────────────────────────────────
        try:
            ema_breakouts_up   = []
            ema_breakouts_down = []
            universe           = _stock_universe(db)

            for symbol in universe:
                rows = (
                    db.query(DailyPrice.close, DailyPrice.date)
                    .filter(DailyPrice.symbol == symbol, DailyPrice.date >= cutoff_52w)
                    .order_by(DailyPrice.date.asc())
                    .all()
                )
                if len(rows) < 22:
                    continue
                closes = [r.close for r in rows if r.close]
                if len(closes) < 22:
                    continue

                ema20 = _ema(closes, 20)
                ema50 = _ema(closes, 50) if len(closes) >= 50 else None
                latest = closes[-1]
                prev   = closes[-2]

                if ema20:
                    # Price crossed above EMA20
                    if prev < ema20 and latest >= ema20:
                        ema_breakouts_up.append((symbol, "EMA20", latest, rows[-1].date))
                    # Price crossed below EMA20
                    elif prev > ema20 and latest <= ema20:
                        ema_breakouts_down.append((symbol, "EMA20", latest, rows[-1].date))

                if ema50:
                    if prev < ema50 and latest >= ema50:
                        ema_breakouts_up.append((symbol, "EMA50", latest, rows[-1].date))
                    elif prev > ema50 and latest <= ema50:
                        ema_breakouts_down.append((symbol, "EMA50", latest, rows[-1].date))

            if ema_breakouts_up:
                top = ema_breakouts_up[:4]
                sym_list = [f"{s[0]} ({s[1]})" for s in top]
                findings.append({
                    "title":       f"EMA Breakout (Bullish): {len(ema_breakouts_up)} stocks crossing above EMA",
                    "description": f"Stocks with recent bullish EMA crossovers: {sym_list}.",
                    "evidence":    f"breakout_up_stocks={[s[0] for s in top]}, ema_level={[s[1] for s in top]}",
                    "implication": "EMA breakouts signal momentum shift. Bullish strategies may generate entry signals.",
                    "urgency":     "normal" if len(ema_breakouts_up) >= 3 else "low",
                    "subcategory": "ema_breakout_up",
                })
                recommendations.append(f"Investigate long signals for EMA breakouts: {', '.join(s[0] for s in top[:3])}.")

            if ema_breakouts_down:
                bot = ema_breakouts_down[:4]
                sym_list = [f"{s[0]} ({s[1]})" for s in bot]
                findings.append({
                    "title":       f"EMA Breakdown (Bearish): {len(ema_breakouts_down)} stocks crossing below EMA",
                    "description": f"Stocks with recent bearish EMA crossovers (price below EMA): {sym_list}.",
                    "evidence":    f"breakout_down_stocks={[s[0] for s in bot]}",
                    "implication": "EMA breakdowns signal momentum deterioration. Avoid new longs in these stocks.",
                    "urgency":     "normal" if len(ema_breakouts_down) >= 4 else "low",
                    "subcategory": "ema_breakout_down",
                })
        except Exception as exc:
            log.debug("EMA breakout analysis skipped: %s", exc)

        # ── 4. Volume Pattern: Accumulation vs Distribution ───────
        try:
            accumulating  = []
            distributing  = []
            universe      = _stock_universe(db)

            for symbol in universe:
                rows = (
                    db.query(DailyPrice.close, DailyPrice.volume, DailyPrice.daily_return, DailyPrice.date)
                    .filter(DailyPrice.symbol == symbol, DailyPrice.date >= cutoff_30d)
                    .order_by(DailyPrice.date.desc())
                    .limit(10)
                    .all()
                )
                if len(rows) < 5:
                    continue

                up_vol   = sum(r.volume or 0 for r in rows if (r.daily_return or 0) > 0)
                down_vol = sum(r.volume or 0 for r in rows if (r.daily_return or 0) < 0)
                total    = up_vol + down_vol
                if total == 0:
                    continue

                up_pct = up_vol / total * 100
                if up_pct >= 70:
                    accumulating.append((symbol, up_pct, rows[0].date))
                elif up_pct <= 30:
                    distributing.append((symbol, up_pct, rows[0].date))

            if accumulating:
                accumulating.sort(key=lambda x: x[1], reverse=True)
                top = accumulating[:4]
                findings.append({
                    "title":       f"Accumulation Pattern: {len(accumulating)} stocks showing volume accumulation",
                    "description": (
                        f"Stocks where ≥70% of 10-day volume occurred on up-days: "
                        f"{[s[0] for s in top]} — institutional buying likely."
                    ),
                    "evidence":    f"accumulating={[s[0] for s in top]}, up_vol_pcts={[round(s[1]) for s in top]}",
                    "implication": "Accumulation signals indicate institutional interest. Potential long candidates.",
                    "urgency":     "low",
                    "subcategory": "volume_accumulation",
                })
                recommendations.append(f"Monitor {', '.join(s[0] for s in top[:3])} for long entry signals — accumulation detected.")

            if distributing:
                distributing.sort(key=lambda x: x[1])
                bot = distributing[:4]
                findings.append({
                    "title":       f"Distribution Pattern: {len(distributing)} stocks showing volume distribution",
                    "description": (
                        f"Stocks where ≤30% of 10-day volume occurred on up-days: "
                        f"{[s[0] for s in bot]} — institutional selling likely."
                    ),
                    "evidence":    f"distributing={[s[0] for s in bot]}, up_vol_pcts={[round(s[1]) for s in bot]}",
                    "implication": "Distribution signals suggest exit or shorting opportunities.",
                    "urgency":     "normal" if len(distributing) >= 4 else "low",
                    "subcategory": "volume_distribution",
                })
        except Exception as exc:
            log.debug("Volume accumulation/distribution analysis skipped: %s", exc)

        # ── 5. NIFTY vs Stock Correlation (breadth divergence) ────
        try:
            nifty_row = (
                db.query(IndexData.returns)
                .filter(IndexData.index_name == "NIFTY50", IndexData.date >= cutoff_30d)
                .order_by(IndexData.date.desc())
                .limit(20)
                .all()
            )
            nifty_rets = [r[0] for r in nifty_row if r[0] is not None]
            if len(nifty_rets) >= 10:
                nifty_direction = sum(1 if r > 0 else -1 for r in nifty_rets)
                if nifty_direction > 5:
                    nifty_trend = "RISING"
                elif nifty_direction < -5:
                    nifty_trend = "FALLING"
                else:
                    nifty_trend = "SIDEWAYS"

                # Count stocks rising vs NIFTY trend
                stock_up_count = 0
                for symbol in _stock_universe(db)[:10]:
                    latest_ret = (
                        db.query(DailyPrice.daily_return)
                        .filter(DailyPrice.symbol == symbol, DailyPrice.date >= cutoff_7d)
                        .order_by(DailyPrice.date.desc())
                        .limit(1)
                        .scalar()
                    )
                    if latest_ret is not None and latest_ret > 0:
                        stock_up_count += 1

                stock_up_pct = stock_up_count / 10 * 100
                divergence   = abs(stock_up_pct - (75 if nifty_trend == "RISING" else 25 if nifty_trend == "FALLING" else 50))

                if divergence >= 30:
                    findings.append({
                        "title":       f"Index-Breadth Divergence: NIFTY {nifty_trend} but only {stock_up_pct:.0f}% of stocks up",
                        "description": (
                            f"NIFTY is {nifty_trend} but only {stock_up_pct:.0f}% of sampled stocks are positive recently. "
                            "Divergence may signal index-level distortion."
                        ),
                        "evidence":    f"nifty_trend={nifty_trend}, stock_up_pct={stock_up_pct:.0f}%",
                        "implication": "Index move may be driven by a few large-cap stocks rather than broad participation.",
                        "urgency":     "normal",
                        "subcategory": "breadth_divergence",
                    })
        except Exception as exc:
            log.debug("NIFTY breadth divergence skipped: %s", exc)

        if not findings:
            findings.append({
                "title":       "Pattern Engine Baseline — No Significant Patterns Detected",
                "description": "No RSI extremes, EMA breakouts, or volume anomalies detected. Market appears stable.",
                "evidence":    "rsi_extremes=0, ema_breakouts=0, volume_spikes=0",
                "implication": "Continue normal monitoring. Market structure is balanced.",
                "urgency":     "low",
                "subcategory": "all_clear",
            })

        summary = (
            f"Pattern research: {len(findings)} findings. "
            f"{'[!] Quality issues detected.' if any(f['urgency'] in ('high', 'critical') for f in findings) else 'Patterns operating normally.'}"
        )
        urgency = "high" if any(f["urgency"] == "high" for f in findings) else "normal"

        return {
            "title":           f"Pattern Research — {today}",
            "summary":         summary,
            "findings":        findings,
            "recommendations": recommendations,
            "urgency":         urgency,
        }


register_agent_class(PatternResearchAgent)
