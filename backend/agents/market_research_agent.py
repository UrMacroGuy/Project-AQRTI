"""
Market Research Agent (7B)
Monitors market breadth, sector rotation, volatility, regime changes, anomalies.
Produces daily market intelligence findings.

MAY NOT: execute trades, modify strategies, retrain models.
"""

from __future__ import annotations

import sys, os, json, math
from datetime import date, timedelta
from typing import Optional

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from sqlalchemy.orm import Session
from sqlalchemy import func
from aqrti.database.models import (
    MarketRegime, DailyPrice, IndexData, Stock, SentimentRecord,
)
from aqrti.utils.logger import get_logger
from agents.agent_base import AgentBase
from agents.agent_registry import register_agent_class

log = get_logger("agent.market_research")

# Sector map from STOCK_META (symbols without .NS suffix)
SECTOR_MAP: dict[str, str] = {
    "RELIANCE":   "Energy",
    "TCS":        "IT",
    "INFY":       "IT",
    "HDFCBANK":   "Banking",
    "ICICIBANK":  "Banking",
    "WIPRO":      "IT",
    "AXISBANK":   "Banking",
    "LTIM":       "IT",
    "NESTLEIND":  "FMCG",
    "BAJFINANCE": "NBFC",
    "MARUTI":     "Auto",
    "SUNPHARMA":  "Pharma",
    "TATASTEEL":  "Metal",
    "TATAMOTORS": "Auto",
    "KOTAKBANK":  "Banking",
    "TITAN":      "Consumer",
    "ONGC":       "Energy",
    "HINDALCO":   "Metal",
    "SBIN":       "Banking",
    "BHARTIARTL": "Telecom",
}


class MarketResearchAgent(AgentBase):
    agent_id    = "market_research"
    agent_type  = "market"
    name        = "Market Research Agent"
    description = "Monitors market breadth, sector rotation, volatility, regime changes, and anomalies."

    def run(self, db: Session) -> dict:
        findings        = []
        recommendations = []

        current_regime = "UNKNOWN"
        current_conf   = 0.0

        # ── 1. Regime Change Detection ────────────────────────────
        try:
            regimes = (
                db.query(MarketRegime)
                .order_by(MarketRegime.date.desc())
                .limit(10)
                .all()
            )
            if regimes:
                current        = regimes[0]
                prior          = regimes[1] if len(regimes) > 1 else None
                current_regime = current.regime
                current_conf   = current.confidence or 0.0

                if prior and current.regime != prior.regime:
                    findings.append({
                        "title":       f"Regime Change: {prior.regime} → {current.regime}",
                        "description": (
                            f"Market regime shifted from {prior.regime} to {current.regime} "
                            f"on {current.date}. Confidence: {current_conf:.0f}%."
                        ),
                        "evidence":    f"Prior: {prior.regime} ({prior.date}). Current: {current.regime} ({current.date}).",
                        "implication": "Strategy allocations and signal thresholds may need review.",
                        "urgency":     "high",
                        "subcategory": "regime_change",
                        "regime":      current.regime,
                    })
                    recommendations.append(
                        f"Review active strategies for compatibility with {current.regime} regime."
                    )

                cutoff_30d     = date.today() - timedelta(days=30)
                recent_regimes = [r for r in regimes if r.date >= cutoff_30d]
                volatile_days  = sum(1 for r in recent_regimes if r.regime == "VOLATILE")
                if volatile_days > 10:
                    findings.append({
                        "title":       f"Elevated Volatility: {volatile_days} VOLATILE days in 30d",
                        "description": f"Market has been in VOLATILE regime for {volatile_days} of the last 30 days.",
                        "evidence":    f"volatile_days={volatile_days}/30",
                        "implication": "Reduce position sizes; prefer defensive strategies.",
                        "urgency":     "high",
                        "subcategory": "volatility",
                    })
                    recommendations.append("Consider reducing portfolio exposure during elevated volatility.")

                if current_conf < 60:
                    findings.append({
                        "title":       f"Low Regime Confidence: {current_conf:.0f}%",
                        "description": f"Current {current_regime} regime has only {current_conf:.0f}% confidence.",
                        "evidence":    f"regime={current_regime}, confidence={current_conf:.1f}%",
                        "implication": "Regime transition may be imminent. Monitor closely.",
                        "urgency":     "normal",
                        "subcategory": "regime_confidence",
                    })

                if len(regimes) >= 5:
                    same_streak = 1
                    for i in range(1, len(regimes)):
                        if regimes[i].regime == regimes[0].regime:
                            same_streak += 1
                        else:
                            break
                    if same_streak >= 7:
                        findings.append({
                            "title":       f"Extended {current_regime} Streak: {same_streak} consecutive days",
                            "description": f"Market has been in {current_regime} for {same_streak} consecutive days.",
                            "evidence":    f"streak={same_streak} days in {current_regime}",
                            "implication": "Mean-reversion strategies may become more viable soon.",
                            "urgency":     "normal",
                            "subcategory": "anomaly",
                        })
        except Exception as exc:
            log.debug("Regime query failed: %s", exc)

        # ── 2. NIFTY / BANKNIFTY price analysis ──────────────────
        try:
            nifty_rows = (
                db.query(IndexData)
                .filter(IndexData.index_name == "NIFTY50")
                .order_by(IndexData.date.desc())
                .limit(25)
                .all()
            )
            if nifty_rows:
                latest     = nifty_rows[0]
                ret_1d     = latest.returns or 0.0

                # 5-day return
                closes     = [r.close for r in reversed(nifty_rows) if r.close]
                ret_5d     = ((closes[-1] / closes[-6]) - 1) * 100 if len(closes) >= 6 else None
                ret_20d    = ((closes[-1] / closes[0]) - 1) * 100 if len(closes) >= 20 else None

                move_desc  = "up" if ret_1d >= 0 else "down"
                urgency_1d = "high" if abs(ret_1d) >= 1.5 else "normal"

                findings.append({
                    "title":       f"NIFTY50 1-day move: {ret_1d:+.2f}%",
                    "description": (
                        f"NIFTY50 closed at {latest.close:,.0f} on {latest.date}, "
                        f"{move_desc} {abs(ret_1d):.2f}% today."
                        + (f" 5d return: {ret_5d:+.2f}%." if ret_5d is not None else "")
                        + (f" 20d return: {ret_20d:+.2f}%." if ret_20d is not None else "")
                    ),
                    "evidence":    (
                        f"close={latest.close:,.0f}, ret_1d={ret_1d:+.2f}%"
                        + (f", ret_5d={ret_5d:+.2f}%" if ret_5d is not None else "")
                        + (f", ret_20d={ret_20d:+.2f}%" if ret_20d is not None else "")
                    ),
                    "implication": (
                        "Large intraday move — verify regime classification and position sizes."
                        if abs(ret_1d) >= 1.5 else
                        "NIFTY50 within normal range."
                    ),
                    "urgency":     urgency_1d,
                    "subcategory": "index_move",
                })

                if ret_5d is not None and abs(ret_5d) >= 3.0:
                    direction = "bull run" if ret_5d > 0 else "sell-off"
                    findings.append({
                        "title":       f"NIFTY50 5-day {direction}: {ret_5d:+.2f}%",
                        "description": f"NIFTY50 has moved {ret_5d:+.2f}% over the last 5 trading days.",
                        "evidence":    f"ret_5d={ret_5d:+.2f}%, close={latest.close:,.0f}",
                        "implication": "Sustained directional move — trend strategies may have an edge.",
                        "urgency":     "normal",
                        "subcategory": "index_trend",
                    })
        except Exception as exc:
            log.debug("Index analysis failed: %s", exc)

        # ── 3. Stock Universe Breadth ─────────────────────────────
        try:
            cutoff_5d = date.today() - timedelta(days=8)
            price_rows = (
                db.query(DailyPrice.symbol, DailyPrice.date, DailyPrice.close)
                .filter(DailyPrice.date >= cutoff_5d)
                .order_by(DailyPrice.symbol, DailyPrice.date.asc())
                .all()
            )
            if price_rows:
                from collections import defaultdict
                sym_history: dict[str, list] = defaultdict(list)
                for row in price_rows:
                    sym_history[row.symbol].append((row.date, row.close))

                up_count   = 0
                down_count = 0
                total_ret  = []
                for sym, history in sym_history.items():
                    if len(history) >= 2:
                        old_close = history[0][1]
                        new_close = history[-1][1]
                        if old_close and new_close and old_close > 0:
                            ret = (new_close / old_close - 1) * 100
                            total_ret.append(ret)
                            if ret > 0:
                                up_count += 1
                            else:
                                down_count += 1

                total_stocks = up_count + down_count
                if total_stocks > 0:
                    breadth_pct = up_count / total_stocks * 100
                    avg_ret     = sum(total_ret) / len(total_ret) if total_ret else 0.0
                    breadth_urgency = "high" if breadth_pct < 30 or breadth_pct > 85 else "normal"
                    findings.append({
                        "title":       f"Market Breadth: {up_count}/{total_stocks} stocks up (5d)",
                        "description": (
                            f"{up_count} of {total_stocks} tracked stocks gained over 5 days "
                            f"({breadth_pct:.0f}% advance rate). Average return: {avg_ret:+.2f}%."
                        ),
                        "evidence":    f"up={up_count}, down={down_count}, breadth={breadth_pct:.1f}%, avg_ret={avg_ret:+.2f}%",
                        "implication": (
                            "Broad market participation — strong bull signal."
                            if breadth_pct >= 70 else
                            "Narrow advance — potential distribution."
                            if breadth_pct < 40 else
                            "Mixed breadth — selective stock picking recommended."
                        ),
                        "urgency":     breadth_urgency,
                        "subcategory": "breadth",
                    })
        except Exception as exc:
            log.debug("Breadth analysis failed: %s", exc)

        # ── 4. Sector Strength via Price Returns ──────────────────
        try:
            cutoff_5d = date.today() - timedelta(days=8)
            price_rows = (
                db.query(DailyPrice.symbol, DailyPrice.date, DailyPrice.close)
                .filter(DailyPrice.date >= cutoff_5d)
                .order_by(DailyPrice.symbol, DailyPrice.date.asc())
                .all()
            )
            if price_rows:
                from collections import defaultdict
                sym_history2: dict[str, list] = defaultdict(list)
                for row in price_rows:
                    sym_history2[row.symbol].append((row.date, row.close))

                sector_returns: dict[str, list[float]] = defaultdict(list)
                for sym, history in sym_history2.items():
                    if len(history) >= 2 and sym in SECTOR_MAP:
                        old_c = history[0][1]
                        new_c = history[-1][1]
                        if old_c and new_c and old_c > 0:
                            ret = (new_c / old_c - 1) * 100
                            sector_returns[SECTOR_MAP[sym]].append(ret)

                sector_avgs = {
                    sec: sum(rets) / len(rets)
                    for sec, rets in sector_returns.items()
                    if rets
                }
                if len(sector_avgs) >= 2:
                    best_sec  = max(sector_avgs, key=sector_avgs.get)
                    worst_sec = min(sector_avgs, key=sector_avgs.get)
                    best_ret  = sector_avgs[best_sec]
                    worst_ret = sector_avgs[worst_sec]
                    spread    = best_ret - worst_ret
                    if spread >= 2.0:
                        findings.append({
                            "title":       f"Sector Rotation: {best_sec} leading, {worst_sec} lagging",
                            "description": (
                                f"{best_sec} is the top-performing sector (5d avg: {best_ret:+.2f}%). "
                                f"{worst_sec} is the worst (5d avg: {worst_ret:+.2f}%). "
                                f"Spread: {spread:.2f}%."
                            ),
                            "evidence":    f"best={best_sec}:{best_ret:+.2f}%, worst={worst_sec}:{worst_ret:+.2f}%, spread={spread:.2f}%",
                            "implication": f"Overweight {best_sec} exposure; reduce {worst_sec} exposure.",
                            "urgency":     "normal",
                            "subcategory": "sector_rotation",
                        })
                        recommendations.append(f"Sector rotation favors {best_sec} — review stock selection.")
        except Exception as exc:
            log.debug("Sector analysis failed: %s", exc)

        # ── 5. Sentiment-based sector rotation (if available) ────
        try:
            cutoff_sent = date.today() - timedelta(days=7)
            sector_query = (
                db.query(SentimentRecord.entity, func.avg(SentimentRecord.score).label("avg_sent"))
                .filter(
                    SentimentRecord.entity_type == "sector",
                    SentimentRecord.timestamp >= cutoff_sent,
                )
                .group_by(SentimentRecord.entity)
                .order_by(func.avg(SentimentRecord.score).desc())
                .limit(5)
                .all()
            )
            if sector_query:
                top_sector    = sector_query[0][0]
                top_score     = sector_query[0][1]
                bottom_sector = sector_query[-1][0]
                bottom_score  = sector_query[-1][1]
                if top_score and bottom_score and (top_score - bottom_score) > 20:
                    findings.append({
                        "title":       f"Sentiment Sector Signal: {top_sector} leading",
                        "description": (
                            f"{top_sector} sentiment avg={top_score:.1f} vs "
                            f"{bottom_sector} avg={bottom_score:.1f}. Spread={top_score - bottom_score:.1f}."
                        ),
                        "evidence":    f"top={top_sector}:{top_score:.1f}, bottom={bottom_sector}:{bottom_score:.1f}",
                        "implication": f"Sentiment confirms overweight {top_sector}; reduce {bottom_sector} exposure.",
                        "urgency":     "normal",
                        "subcategory": "sector_rotation",
                    })
        except Exception as exc:
            log.debug("Sector sentiment query skipped: %s", exc)

        # ── Fallback: ensure at least 1 finding ───────────────────
        if not findings:
            findings.append({
                "title":       "Market Data Status: Initialising",
                "description": "No regime data or price history is available yet. Run data ingestion first.",
                "evidence":    "regime_rows=0, index_rows=0",
                "implication": "Pipeline must complete at least one ingestion cycle before market analysis can begin.",
                "urgency":     "low",
                "subcategory": "data_coverage",
            })

        summary = (
            f"Market: {current_regime} (conf={current_conf:.0f}%). "
            f"{len(findings)} findings. "
            f"{'Regime change detected.' if any(f.get('subcategory') == 'regime_change' for f in findings) else ''}"
        ).strip()

        urgency = (
            "critical" if any(f["urgency"] == "critical" for f in findings) else
            "high"     if any(f["urgency"] == "high"     for f in findings) else
            "normal"
        )

        return {
            "title":           f"Market Research — {date.today()}",
            "summary":         summary,
            "findings":        findings,
            "recommendations": recommendations,
            "urgency":         urgency,
            "metadata": {
                "current_regime":    current_regime,
                "regime_confidence": current_conf,
            },
        }


register_agent_class(MarketResearchAgent)
