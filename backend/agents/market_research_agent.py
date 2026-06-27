"""
Market Research Agent
Monitors market breadth, sector rotation, volatility, regime changes, and anomalies.
Derives intelligence from live price data in daily_prices + index_data tables.

MAY NOT: execute trades, modify strategies, retrain models.
"""

from __future__ import annotations

import sys, os, math
from datetime import date, timedelta

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from sqlalchemy.orm import Session
from aqrti.database.models import (
    MarketRegime, DailyPrice, IndexData, SentimentRecord, MarketBreadth,
)
from aqrti.utils.logger import get_logger
from agents.agent_base import AgentBase
from agents.agent_registry import register_agent_class

log = get_logger("agent.market_research")

STOCK_UNIVERSE = [
    # Original 20
    "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "WIPRO", "AXISBANK",
    "NESTLEIND", "BAJFINANCE", "MARUTI", "SUNPHARMA", "TATASTEEL",
    "KOTAKBANK", "TITAN", "ONGC", "HINDALCO", "SBIN", "BHARTIARTL",
    # Expanded 30
    "HCLTECH", "ITC", "LT", "HINDUNILVR", "ULTRACEMCO",
    "BAJAJFINSV", "NTPC", "ADANIENT", "ADANIPORTS", "JSWSTEEL",
    "TECHM", "COALINDIA", "BPCL", "HDFCLIFE", "SBILIFE",
    "INDUSINDBK", "M&M", "DIVISLAB", "DRREDDY", "EICHERMOT",
    "HEROMOTOCO", "CIPLA", "BRITANNIA", "APOLLOHOSP", "TRENT",
    "GRASIM", "SHREECEM", "BEL", "POWERGRID", "ASIANPAINT",
]

SECTOR_MAP = {
    "RELIANCE": "Energy",    "ONGC": "Energy",       "COALINDIA": "Energy",  "BPCL": "Energy",
    "TCS": "IT",             "INFY": "IT",           "WIPRO": "IT",
    "HCLTECH": "IT",         "TECHM": "IT",
    "HDFCBANK": "Banking",   "ICICIBANK": "Banking", "AXISBANK": "Banking",
    "KOTAKBANK": "Banking",  "SBIN": "Banking",      "INDUSINDBK": "Banking",
    "BAJFINANCE": "NBFC",    "BAJAJFINSV": "NBFC",   "HDFCLIFE": "Insurance", "SBILIFE": "Insurance",
    "MARUTI": "Auto",        "M&M": "Auto",
    "EICHERMOT": "Auto",     "HEROMOTOCO": "Auto",
    "SUNPHARMA": "Pharma",   "DRREDDY": "Pharma",    "CIPLA": "Pharma",      "DIVISLAB": "Pharma",
    "TATASTEEL": "Metal",    "HINDALCO": "Metal",    "JSWSTEEL": "Metal",
    "NESTLEIND": "FMCG",     "ITC": "FMCG",          "HINDUNILVR": "FMCG",   "BRITANNIA": "FMCG",
    "TITAN": "Consumer",     "TRENT": "Consumer",    "ASIANPAINT": "Consumer", "APOLLOHOSP": "Healthcare",
    "BHARTIARTL": "Telecom",
    "LT": "Infra",           "ADANIPORTS": "Infra",  "POWERGRID": "Power",   "NTPC": "Power",
    "ULTRACEMCO": "Cement",  "GRASIM": "Cement",     "SHREECEM": "Cement",
    "ADANIENT": "Conglomerate", "BEL": "Defence",
}


def _pct_change(new_val, old_val):
    if old_val and old_val != 0:
        return (new_val - old_val) / old_val * 100
    return None


class MarketResearchAgent(AgentBase):
    agent_id    = "market_research"
    agent_type  = "market"
    name        = "Market Research Agent"
    description = "Monitors market breadth, sector rotation, volatility, and regime changes using live price data."

    def run(self, db: Session) -> dict:
        findings        = []
        recommendations = []
        today           = date.today()
        cutoff_30d      = today - timedelta(days=30)

        current_regime = "UNKNOWN"
        current_conf   = 0.0

        # ── 1. Regime from DB (if populated) ─────────────────────
        try:
            regimes = (
                db.query(MarketRegime)
                .order_by(MarketRegime.date.desc())
                .limit(10)
                .all()
            )
            if regimes:
                current_regime = regimes[0].regime
                current_conf   = regimes[0].confidence or 0.0
                prior = regimes[1] if len(regimes) > 1 else None
                if prior and current_regime != prior.regime:
                    findings.append({
                        "title":       f"Regime Change: {prior.regime} → {current_regime}",
                        "description": (
                            f"Market regime shifted from {prior.regime} to {current_regime} "
                            f"on {regimes[0].date}. Confidence: {current_conf:.0f}%."
                        ),
                        "evidence":    f"prior={prior.regime} ({prior.date}), current={current_regime} ({regimes[0].date})",
                        "implication": "Strategy allocations and signal thresholds may need review.",
                        "urgency":     "high",
                        "subcategory": "regime_change",
                        "regime":      current_regime,
                    })
                    recommendations.append(f"Review active strategies for {current_regime} regime.")

                volatile_days = sum(1 for r in regimes if r.date >= cutoff_30d and r.regime == "VOLATILE")
                if volatile_days > 10:
                    findings.append({
                        "title":       f"Elevated Volatility: {volatile_days} VOLATILE days (30d)",
                        "description": f"Market has been VOLATILE for {volatile_days} of the last 30 days.",
                        "evidence":    f"volatile_days={volatile_days}/30",
                        "implication": "Reduce position sizes; prefer defensive strategies.",
                        "urgency":     "high",
                        "subcategory": "volatility",
                    })

                if 0 < current_conf < 60:
                    findings.append({
                        "title":       f"Low Regime Confidence: {current_conf:.0f}%",
                        "description": f"Current {current_regime} regime has only {current_conf:.0f}% confidence.",
                        "evidence":    f"regime={current_regime}, confidence={current_conf:.1f}%",
                        "implication": "Regime transition may be imminent. Monitor closely.",
                        "urgency":     "normal",
                        "subcategory": "regime_confidence",
                    })
        except Exception as exc:
            log.debug("Regime query skipped: %s", exc)

        # ── 2. NIFTY Index Analysis ───────────────────────────────
        try:
            nifty_rows = (
                db.query(IndexData)
                .filter(IndexData.index_name == "NIFTY50", IndexData.date >= cutoff_30d)
                .order_by(IndexData.date.desc())
                .limit(22)
                .all()
            )
            if len(nifty_rows) >= 2:
                latest = nifty_rows[0]
                prev   = nifty_rows[1]
                ret_1d = _pct_change(latest.close, prev.close)
                if ret_1d is not None and abs(ret_1d) >= 1.5:
                    direction = "surged" if ret_1d > 0 else "fell"
                    findings.append({
                        "title":       f"NIFTY {direction} {ret_1d:+.2f}% on {latest.date}",
                        "description": (
                            f"NIFTY50 closed at {latest.close:,.0f} ({ret_1d:+.2f}% vs prior close {prev.close:,.0f}). "
                            f"{'Sharp move — check for macro trigger.' if abs(ret_1d) >= 2.5 else 'Significant single-day move.'}"
                        ),
                        "evidence":    f"close={latest.close:.0f}, prev={prev.close:.0f}, ret_1d={ret_1d:.2f}%",
                        "implication": "Large index moves affect all open positions and signal quality.",
                        "urgency":     "high" if abs(ret_1d) >= 2.5 else "normal",
                        "subcategory": "index_move",
                    })

                if len(nifty_rows) >= 20:
                    base_20d = nifty_rows[19]
                    ret_20d  = _pct_change(latest.close, base_20d.close)
                    if ret_20d is not None:
                        trend = "UPTREND" if ret_20d > 3 else ("DOWNTREND" if ret_20d < -3 else "SIDEWAYS")
                        if current_regime == "UNKNOWN":
                            current_regime = "BULL" if ret_20d > 5 else ("BEAR" if ret_20d < -5 else "SIDEWAYS")
                        findings.append({
                            "title":       f"NIFTY 20-Day Trend: {trend} ({ret_20d:+.1f}%)",
                            "description": (
                                f"NIFTY50 has moved {ret_20d:+.1f}% over the last 20 trading days "
                                f"({base_20d.date} → {latest.date}, {latest.close:,.0f})."
                            ),
                            "evidence":    f"nifty_20d_return={ret_20d:.2f}%, from={base_20d.close:.0f} to={latest.close:.0f}",
                            "implication": f"{'Broad rally — maintain or increase long exposure.' if ret_20d > 5 else 'Downtrend in force — defensive posture recommended.' if ret_20d < -5 else 'Sideways market — mean-reversion strategies may outperform.'}",
                            "urgency":     "normal",
                            "subcategory": "index_trend",
                        })

                # Annualised volatility
                rets = [r.returns for r in nifty_rows if r.returns is not None]
                if len(rets) >= 10:
                    mean_r = sum(rets) / len(rets)
                    variance = sum((r - mean_r) ** 2 for r in rets) / len(rets)
                    vol_ann  = math.sqrt(variance) * math.sqrt(252) * 100
                    if vol_ann > 20:
                        findings.append({
                            "title":       f"Elevated Market Volatility: {vol_ann:.1f}% annualised",
                            "description": (
                                f"NIFTY50 20-day realised volatility is {vol_ann:.1f}% (annualised). "
                                f"Threshold is 20%."
                            ),
                            "evidence":    f"vol_ann={vol_ann:.1f}%, n_days={len(rets)}",
                            "implication": "Higher volatility widens stop-loss triggers. Reduce position sizes or widen stops.",
                            "urgency":     "high" if vol_ann > 28 else "normal",
                            "subcategory": "volatility",
                        })
        except Exception as exc:
            log.debug("NIFTY analysis skipped: %s", exc)

        # ── 3. Stock Universe Breadth ─────────────────────────────
        try:
            advancing     = 0
            declining     = 0
            sector_rets: dict[str, list[float]] = {}

            for symbol in STOCK_UNIVERSE:
                rows = (
                    db.query(DailyPrice.close, DailyPrice.date)
                    .filter(DailyPrice.symbol == symbol, DailyPrice.date >= cutoff_30d)
                    .order_by(DailyPrice.date.desc())
                    .limit(6)
                    .all()
                )
                if len(rows) < 2:
                    continue
                ret_5d = _pct_change(rows[0].close, rows[min(4, len(rows) - 1)].close)
                if ret_5d is None:
                    continue
                if ret_5d > 0:
                    advancing += 1
                else:
                    declining += 1
                sector = SECTOR_MAP.get(symbol, "Other")
                sector_rets.setdefault(sector, []).append(ret_5d)

            total = advancing + declining
            if total >= 8:
                breadth_pct = advancing / total * 100
                label = "Bullish Breadth" if breadth_pct >= 65 else ("Bearish Breadth" if breadth_pct <= 35 else "Mixed Breadth")
                findings.append({
                    "title":       f"{label}: {advancing}/{total} NSE stocks advancing (5d)",
                    "description": (
                        f"{advancing} of {total} tracked NSE stocks are positive over 5 trading days "
                        f"({breadth_pct:.0f}% advancing, {declining} declining)."
                    ),
                    "evidence":    f"advancing={advancing}, declining={declining}, breadth_pct={breadth_pct:.1f}%",
                    "implication": (
                        "Broad rally — healthy market structure. Long bias supported." if breadth_pct >= 65 else
                        "Narrow breadth — index move may not be sustainable." if breadth_pct <= 35 else
                        "No strong directional edge from breadth alone."
                    ),
                    "urgency":     "high" if breadth_pct < 25 or breadth_pct > 90 else "normal",
                    "subcategory": "market_breadth",
                })

            # ── 4. Sector Rotation ────────────────────────────────
            if len(sector_rets) >= 2:
                sector_avgs = {s: sum(v) / len(v) for s, v in sector_rets.items() if len(v) >= 2}
                if len(sector_avgs) >= 2:
                    top_s = max(sector_avgs, key=sector_avgs.get)
                    bot_s = min(sector_avgs, key=sector_avgs.get)
                    top_r = sector_avgs[top_s]
                    bot_r = sector_avgs[bot_s]
                    spread = top_r - bot_r
                    if spread >= 2.5:
                        findings.append({
                            "title":       f"Sector Rotation: {top_s} leading (+{top_r:.1f}%), {bot_s} lagging ({bot_r:.1f}%)",
                            "description": (
                                f"{top_s} sector avg 5d return={top_r:+.1f}% vs "
                                f"{bot_s} avg={bot_r:+.1f}%. Spread={spread:.1f} percentage points."
                            ),
                            "evidence":    f"top={top_s}:{top_r:+.1f}%, bottom={bot_s}:{bot_r:+.1f}%, spread={spread:.1f}pp",
                            "implication": f"Rotate allocation towards {top_s}; reduce {bot_s} exposure.",
                            "urgency":     "normal",
                            "subcategory": "sector_rotation",
                        })
                        recommendations.append(f"Overweight {top_s}; underweight {bot_s} in next rebalance.")
        except Exception as exc:
            log.debug("Breadth/sector analysis skipped: %s", exc)

        # ── 5. Market Breadth Evolution ───────────────────────────
        try:
            breadth_rows = (
                db.query(MarketBreadth)
                .filter(MarketBreadth.breadth_date >= cutoff_30d)
                .order_by(MarketBreadth.breadth_date.desc())
                .limit(10)
                .all()
            )
            if len(breadth_rows) >= 4:
                # Check advance_decline_ratio declining for 3+ consecutive days
                ratios = [r.advance_decline_ratio for r in breadth_rows if r.advance_decline_ratio is not None]
                if len(ratios) >= 3:
                    consecutive_declines = 0
                    for i in range(len(ratios) - 1):
                        if ratios[i] < ratios[i + 1]:
                            consecutive_declines += 1
                        else:
                            break
                    if consecutive_declines >= 3:
                        findings.append({
                            "title":       f"Breadth Deterioration: A/D Ratio declining for {consecutive_declines}+ days",
                            "description": (
                                f"Advance/Decline ratio has been falling for {consecutive_declines} consecutive days: "
                                f"{' → '.join(f'{r:.2f}' for r in ratios[:consecutive_declines+1][::-1])}."
                            ),
                            "evidence":    f"consecutive_ad_declines={consecutive_declines}, latest_ad={ratios[0]:.2f}",
                            "implication": "Deteriorating breadth often precedes broader market weakness.",
                            "urgency":     "high" if consecutive_declines >= 5 else "normal",
                            "subcategory": "breadth_deterioration",
                        })
        except Exception as exc:
            log.debug("Breadth evolution check skipped: %s", exc)

        # ── 6. Volatility Clustering ──────────────────────────────
        try:
            nifty_90d = (
                db.query(IndexData.returns, IndexData.date)
                .filter(IndexData.index_name == "NIFTY50", IndexData.date >= today - timedelta(days=95))
                .order_by(IndexData.date.desc())
                .limit(90)
                .all()
            )
            if len(nifty_90d) >= 20:
                all_rets   = [r.returns for r in nifty_90d if r.returns is not None]
                last_10    = all_rets[:10]
                prior_80   = all_rets[10:]

                if len(last_10) >= 5 and len(prior_80) >= 20:
                    def _std(vals):
                        if not vals:
                            return 0.0
                        m = sum(vals) / len(vals)
                        return (sum((v - m) ** 2 for v in vals) / len(vals)) ** 0.5

                    std_10d  = _std(last_10)
                    std_90d  = _std(prior_80)
                    if std_90d > 0 and std_10d > 2 * std_90d:
                        findings.append({
                            "title":       f"Volatility Cluster: 10d std ({std_10d:.4f}) is {std_10d/std_90d:.1f}x 90d avg ({std_90d:.4f})",
                            "description": (
                                f"NIFTY50 daily return std over last 10 days ({std_10d:.4f}) is "
                                f"{std_10d/std_90d:.1f}x higher than the 90-day baseline ({std_90d:.4f}). "
                                f"Volatility clustering indicates risk-off or news-driven regime."
                            ),
                            "evidence":    f"std_10d={std_10d:.5f}, std_90d={std_90d:.5f}, ratio={std_10d/std_90d:.2f}x",
                            "implication": "High volatility cluster: reduce position sizes, widen stops, avoid momentum entries.",
                            "urgency":     "high",
                            "subcategory": "volatility_cluster",
                        })
        except Exception as exc:
            log.debug("Volatility clustering check skipped: %s", exc)

        # ── 7. Volume Anomaly Detection ───────────────────────────
        try:
            volume_anomalies = []
            for symbol in STOCK_UNIVERSE:
                vol_rows = (
                    db.query(DailyPrice.volume, DailyPrice.date, DailyPrice.close)
                    .filter(DailyPrice.symbol == symbol, DailyPrice.date >= cutoff_30d)
                    .order_by(DailyPrice.date.desc())
                    .limit(22)
                    .all()
                )
                if len(vol_rows) < 5:
                    continue
                today_vol = vol_rows[0].volume
                if today_vol is None or today_vol == 0:
                    continue
                avg_20d = sum(r.volume for r in vol_rows[1:21] if r.volume) / max(len([r for r in vol_rows[1:21] if r.volume]), 1)
                if avg_20d > 0 and today_vol > 5 * avg_20d:
                    volume_anomalies.append({
                        "symbol":    symbol,
                        "ratio":     today_vol / avg_20d,
                        "volume":    today_vol,
                        "avg_20d":   avg_20d,
                        "close":     vol_rows[0].close,
                        "date":      vol_rows[0].date,
                    })

            for anomaly in sorted(volume_anomalies, key=lambda x: x["ratio"], reverse=True)[:3]:
                findings.append({
                    "title":       f"Volume Anomaly: {anomaly['symbol']} at {anomaly['ratio']:.1f}x avg",
                    "description": (
                        f"{anomaly['symbol']} traded {anomaly['volume']:,.0f} shares on {anomaly['date']} "
                        f"({anomaly['ratio']:.1f}x its 20d avg of {anomaly['avg_20d']:,.0f}). "
                        f"Close: {anomaly['close']:.2f}."
                    ),
                    "evidence":    f"symbol={anomaly['symbol']}, vol={anomaly['volume']:.0f}, avg_20d={anomaly['avg_20d']:.0f}, ratio={anomaly['ratio']:.2f}x",
                    "implication": "Unusual volume may signal institutional activity, news event, or breakout.",
                    "urgency":     "high" if anomaly["ratio"] > 10 else "normal",
                    "subcategory": "volume_anomaly",
                    "symbol":      anomaly["symbol"],
                })
        except Exception as exc:
            log.debug("Volume anomaly detection skipped: %s", exc)

        # ── Fallback ──────────────────────────────────────────────
        if not findings:
            findings.append({
                "title":       "Awaiting Market Data",
                "description": "No price data found in index_data or daily_prices tables. Run the daily market data pipeline to populate.",
                "evidence":    "index_data_rows=0, daily_prices_rows=0",
                "implication": "Market intelligence is unavailable until data pipeline runs.",
                "urgency":     "low",
                "subcategory": "data_coverage",
            })

        summary = (
            f"Market: {current_regime} (conf={current_conf:.0f}%). "
            f"{len(findings)} findings."
        ).strip()
        urgency = "high" if any(f["urgency"] == "high" for f in findings) else "normal"

        return {
            "title":           f"Market Research — {today}",
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
