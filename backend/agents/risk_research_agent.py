"""
Risk Research Agent
Analyzes portfolio risk, sector concentration, exposure, tail risk, and drawdown trends.
Falls back to market-level risk metrics from price data when paper trading is empty.

MAY NOT: modify portfolio allocations, adjust position sizes, execute any trades.
"""

from __future__ import annotations

import sys, os, math
from datetime import date, timedelta

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from sqlalchemy.orm import Session
from aqrti.database.models import (
    PaperTrade, PaperPosition, PaperPortfolio, PerformanceSnapshot,
    EquityCurvePoint, DailyPrice, IndexData,
)
from aqrti.utils.logger import get_logger
from agents.agent_base import AgentBase
from agents.agent_registry import register_agent_class

log = get_logger("agent.risk_research")

MAX_DRAWDOWN_ALERT = -15.0
SECTOR_CONC_ALERT  = 40.0
EXPOSURE_ALERT     = 80.0

SECTOR_MAP = {
    "RELIANCE": "Energy",   "ONGC": "Energy",
    "TCS": "IT",            "INFY": "IT",      "WIPRO": "IT",      "LTIM": "IT",
    "HDFCBANK": "Banking",  "ICICIBANK": "Banking", "AXISBANK": "Banking",
    "KOTAKBANK": "Banking", "SBIN": "Banking",
    "BAJFINANCE": "NBFC",
    "MARUTI": "Auto",       "TATAMOTORS": "Auto",
    "SUNPHARMA": "Pharma",
    "TATASTEEL": "Metal",   "HINDALCO": "Metal",
    "NESTLEIND": "FMCG",
    "TITAN": "Consumer",
    "BHARTIARTL": "Telecom",
}

STOCK_UNIVERSE = list(SECTOR_MAP.keys())


class RiskResearchAgent(AgentBase):
    agent_id    = "risk_research"
    agent_type  = "risk"
    name        = "Risk Research Agent"
    description = "Analyzes portfolio risk, sector concentration, exposure, tail risk, and drawdown trends."

    def run(self, db: Session) -> dict:
        findings        = []
        recommendations = []
        today           = date.today()
        cutoff_30d      = today - timedelta(days=30)

        portfolio_data_found = False

        # ── 1. Portfolio Drawdown ────────────────────────────────
        try:
            perf = (
                db.query(PerformanceSnapshot)
                .order_by(PerformanceSnapshot.date.desc())
                .first()
            )
            if perf:
                portfolio_data_found = True
                dd     = perf.current_drawdown_pct or 0.0
                max_dd = perf.max_drawdown_pct     or 0.0

                if dd < MAX_DRAWDOWN_ALERT:
                    findings.append({
                        "title":       f"Active Drawdown Alert: {dd:.1f}%",
                        "description": f"Portfolio is in {dd:.1f}% drawdown (max historical: {max_dd:.1f}%).",
                        "evidence":    f"current_dd={dd:.1f}%, max_dd={max_dd:.1f}%",
                        "implication": "Portfolio under stress. Review open positions for exit candidates.",
                        "urgency":     "critical" if dd < -20 else "high",
                        "subcategory": "drawdown",
                    })
                    recommendations.append("Review and potentially close losing positions to limit drawdown.")

                if perf.sharpe_ratio is not None and perf.sharpe_ratio < 0.5:
                    findings.append({
                        "title":       f"Low Sharpe Ratio: {perf.sharpe_ratio:.2f} (target ≥1.0)",
                        "description": f"30-day rolling Sharpe ratio is {perf.sharpe_ratio:.2f}.",
                        "evidence":    f"sharpe={perf.sharpe_ratio:.2f}, date={perf.date}",
                        "implication": "Risk-adjusted returns are poor. Strategy selection may be sub-optimal.",
                        "urgency":     "normal",
                        "subcategory": "risk_adjusted_return",
                    })

                if perf.win_rate_pct is not None:
                    findings.append({
                        "title":       f"Portfolio Win Rate: {perf.win_rate_pct:.1f}% (30d)",
                        "description": (
                            f"Win rate={perf.win_rate_pct:.1f}%, "
                            f"total_trades={perf.total_trades or 0}, "
                            f"winning={perf.winning_trades or 0}, "
                            f"losing={perf.losing_trades or 0}."
                        ),
                        "evidence":    f"win_rate={perf.win_rate_pct:.1f}%, total_trades={perf.total_trades}",
                        "implication": f"{'Healthy trade quality.' if perf.win_rate_pct >= 55 else 'Below-target win rate — strategy or model issue.'}",
                        "urgency":     "high" if (perf.win_rate_pct or 100) < 40 else "normal",
                        "subcategory": "win_rate",
                    })
        except Exception as exc:
            log.debug("Performance snapshot query skipped: %s", exc)

        # ── 2. Open Positions & Sector Concentration ─────────────
        try:
            open_positions = db.query(PaperPosition).all()
            if open_positions:
                portfolio_data_found = True
                sector_counts: dict[str, int] = {}
                total = len(open_positions)
                for pos in open_positions:
                    sector = pos.sector or SECTOR_MAP.get(pos.symbol, "Unknown")
                    sector_counts[sector] = sector_counts.get(sector, 0) + 1

                for sector, count in sector_counts.items():
                    pct = count / total * 100
                    if pct > SECTOR_CONC_ALERT:
                        findings.append({
                            "title":       f"Sector Concentration: {sector} = {pct:.0f}% of open positions",
                            "description": f"{count}/{total} open positions are in {sector} ({pct:.0f}%).",
                            "evidence":    f"sector={sector}, count={count}, pct={pct:.1f}%",
                            "implication": f"High concentration in {sector}. Correlated sector event could cause large losses.",
                            "urgency":     "high" if pct > 60 else "normal",
                            "subcategory": "sector_concentration",
                        })
                        recommendations.append(f"Diversify away from {sector} concentration ({pct:.0f}%).")

                # Capital exposure
                portfolio = db.query(PaperPortfolio).first()
                if portfolio and portfolio.total_value > 0:
                    invested = portfolio.total_value - portfolio.current_cash
                    exposure_pct = invested / portfolio.total_value * 100
                    if exposure_pct > EXPOSURE_ALERT:
                        findings.append({
                            "title":       f"High Portfolio Exposure: {exposure_pct:.0f}% capital deployed",
                            "description": (
                                f"Portfolio has {exposure_pct:.0f}% of capital deployed "
                                f"(₹{invested:,.0f} invested of ₹{portfolio.total_value:,.0f} total)."
                            ),
                            "evidence":    f"invested={invested:.0f}, total={portfolio.total_value:.0f}, exposure={exposure_pct:.1f}%",
                            "implication": "Limited cash buffer. Reduce exposure to allow room for new opportunities.",
                            "urgency":     "normal",
                            "subcategory": "exposure",
                        })
        except Exception as exc:
            log.debug("Open positions query skipped: %s", exc)

        # ── 3. Tail Risk — recent large losses ───────────────────
        try:
            large_losses = (
                db.query(PaperTrade)
                .filter(
                    PaperTrade.is_open   == False,
                    PaperTrade.exit_date >= cutoff_30d,
                    PaperTrade.actual_return < -8.0,
                )
                .count()
            )
            if large_losses >= 3:
                portfolio_data_found = True
                findings.append({
                    "title":       f"Tail Risk Event: {large_losses} trades with >8% loss in 30 days",
                    "description": f"{large_losses} closed trades had losses greater than 8% in the last 30 days.",
                    "evidence":    f"large_loss_count={large_losses}",
                    "implication": "Stop-loss levels may be too wide, or entry signals are poor-quality.",
                    "urgency":     "high",
                    "subcategory": "tail_risk",
                })
                recommendations.append("Review stop-loss calibration — large loss frequency is elevated.")
        except Exception as exc:
            log.debug("Tail risk query skipped: %s", exc)

        # ── 4. Market Risk from Price Data (fallback + supplement) ─
        try:
            stock_returns: list[float] = []
            for symbol in STOCK_UNIVERSE:
                rows = (
                    db.query(DailyPrice.daily_return)
                    .filter(DailyPrice.symbol == symbol, DailyPrice.date >= cutoff_30d)
                    .order_by(DailyPrice.date.desc())
                    .limit(20)
                    .all()
                )
                # daily_return stored as percent (e.g. -1.5), convert to decimal
                rets = [r[0] / 100.0 for r in rows if r[0] is not None]
                stock_returns.extend(rets)

            if len(stock_returns) >= 30:
                mean_r = sum(stock_returns) / len(stock_returns)
                variance = sum((r - mean_r) ** 2 for r in stock_returns) / len(stock_returns)
                vol_daily = math.sqrt(variance)
                var_95    = mean_r - 1.645 * vol_daily      # parametric 95% 1-day VaR
                vol_ann   = vol_daily * math.sqrt(252) * 100

                findings.append({
                    "title":       f"Market Risk: Universe Volatility {vol_ann:.1f}% ann., 1-day VaR {var_95:.2f}%",
                    "description": (
                        f"NSE universe (20 stocks, 30d) annualised vol={vol_ann:.1f}%. "
                        f"Parametric 95% 1-day VaR={var_95:.2f}% per unit invested."
                    ),
                    "evidence":    f"vol_ann={vol_ann:.1f}%, var_95={var_95:.2f}%, n_returns={len(stock_returns)}",
                    "implication": f"{'Elevated market risk — reduce position sizes.' if vol_ann > 25 else 'Market risk within normal parameters.'}",
                    "urgency":     "high" if vol_ann > 30 else "normal",
                    "subcategory": "market_var",
                })

                # Worst single-day drop across universe
                worst = min(stock_returns)
                worst_sym = None
                for symbol in STOCK_UNIVERSE:
                    rows = (
                        db.query(DailyPrice.daily_return, DailyPrice.date)
                        .filter(DailyPrice.symbol == symbol, DailyPrice.date >= cutoff_30d)
                        .order_by(DailyPrice.daily_return.asc())
                        .limit(1)
                        .all()
                    )
                    if rows and rows[0][0] is not None and rows[0][0] <= worst + 0.01:
                        worst_sym = symbol
                        break

                if worst < -5.0:
                    findings.append({
                        "title":       f"Max Single-Day Loss: {worst:.1f}%{f' ({worst_sym})' if worst_sym else ''} in 30d",
                        "description": (
                            f"Worst single-day return across the stock universe in the last 30 days: {worst:.1f}%"
                            f"{f' by {worst_sym}' if worst_sym else ''}."
                        ),
                        "evidence":    f"worst_return={worst:.2f}%, symbol={worst_sym}",
                        "implication": "Tail events are occurring. Review stop-loss calibration.",
                        "urgency":     "high" if worst < -8 else "normal",
                        "subcategory": "tail_loss",
                    })
        except Exception as exc:
            log.debug("Market risk calculation skipped: %s", exc)

        # ── 5. NIFTY Benchmark Risk ──────────────────────────────
        try:
            nifty_rows = (
                db.query(IndexData.returns)
                .filter(IndexData.index_name == "NIFTY50", IndexData.date >= cutoff_30d)
                .order_by(IndexData.date.desc())
                .limit(20)
                .all()
            )
            nifty_rets = [r[0] for r in nifty_rows if r[0] is not None]
            if len(nifty_rets) >= 10:
                neg_days  = sum(1 for r in nifty_rets if r < 0)
                neg_pct   = neg_days / len(nifty_rets) * 100
                if neg_pct > 55:
                    findings.append({
                        "title":       f"NIFTY Negative Bias: {neg_pct:.0f}% of last {len(nifty_rets)} sessions negative",
                        "description": f"NIFTY50 has closed negative in {neg_days} of {len(nifty_rets)} recent sessions.",
                        "evidence":    f"negative_days={neg_days}, total={len(nifty_rets)}, neg_pct={neg_pct:.1f}%",
                        "implication": "Bearish market environment increases risk for long-biased positions.",
                        "urgency":     "normal",
                        "subcategory": "benchmark_bias",
                    })
        except Exception as exc:
            log.debug("NIFTY benchmark risk skipped: %s", exc)

        if not findings:
            findings.append({
                "title":       "No Risk Alerts — Market Within Normal Parameters",
                "description": "No significant risk events detected. Portfolio and market data within expected ranges.",
                "evidence":    "all_checks_passed",
                "implication": "Continue monitoring daily. Risk parameters are nominal.",
                "urgency":     "low",
                "subcategory": "all_clear",
            })

        summary = (
            f"Risk assessment: {len([f for f in findings if f['urgency'] in ('critical','high')])} high/critical risks. "
            f"{len(findings)} total findings. "
            f"{'Critical risks detected.' if any(f['urgency'] == 'critical' for f in findings) else 'No critical issues.'}"
        )
        urgency = (
            "critical" if any(f["urgency"] == "critical" for f in findings) else
            "high"     if any(f["urgency"] == "high"     for f in findings) else
            "normal"
        )

        return {
            "title":           f"Risk Research — {today}",
            "summary":         summary,
            "findings":        findings,
            "recommendations": recommendations,
            "urgency":         urgency,
        }


register_agent_class(RiskResearchAgent)
