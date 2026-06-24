"""
Risk Research Agent (7F)
Analyzes portfolio risk, sector concentration, exposure, tail risk, drawdown trends.

When paper_trades / performance_snapshots are empty, computes risk proxies directly
from daily_prices and index_data (VaR proxy, max single-day loss, universe volatility).

MAY NOT: modify portfolio allocations, adjust position sizes, execute any trades.
"""

from __future__ import annotations

import sys, os, math
from datetime import date, timedelta
from collections import defaultdict

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from sqlalchemy.orm import Session
from sqlalchemy import func
from aqrti.database.models import (
    PaperTrade, PerformanceSnapshot, EquityCurvePoint,
    FailureRecord, Stock, DailyPrice, IndexData,
)
from aqrti.utils.logger import get_logger
from agents.agent_base import AgentBase
from agents.agent_registry import register_agent_class

log = get_logger("agent.risk_research")

MAX_DRAWDOWN_ALERT = -15.0   # % — alert if max drawdown exceeds this
SECTOR_CONC_ALERT  = 40.0    # % — alert if any sector exceeds this % of open positions
EXPOSURE_ALERT     = 80.0    # % — alert if capital deployed exceeds this
VAR_CONFIDENCE     = 0.95    # 95th percentile VaR


class RiskResearchAgent(AgentBase):
    agent_id    = "risk_research"
    agent_type  = "risk"
    name        = "Risk Research Agent"
    description = "Analyzes portfolio risk, sector concentration, exposure, tail risk, and drawdown trends."

    def run(self, db: Session) -> dict:
        findings        = []
        recommendations = []
        trade_data_available = False
        perf_data_available  = False

        # ── 1. Current Drawdown (paper portfolio) ────────────────
        try:
            perf = (
                db.query(PerformanceSnapshot)
                .order_by(PerformanceSnapshot.date.desc())
                .first()
            )
            if perf:
                perf_data_available = True
                dd     = perf.current_drawdown_pct or 0.0
                max_dd = perf.max_drawdown_pct or 0.0

                if dd < MAX_DRAWDOWN_ALERT:
                    findings.append({
                        "title":       f"Active Drawdown Alert: {dd:.1f}%",
                        "description": f"Portfolio is currently in {dd:.1f}% drawdown (max historical: {max_dd:.1f}%).",
                        "evidence":    f"current_dd={dd:.1f}%, max_dd={max_dd:.1f}%",
                        "implication": "Portfolio is under stress. Review open positions for exits.",
                        "urgency":     "critical" if dd < -20 else "high",
                        "subcategory": "drawdown",
                    })
                    recommendations.append("Review and potentially close losing positions to limit drawdown.")

                if max_dd < -25:
                    findings.append({
                        "title":       f"Historical Max Drawdown: {max_dd:.1f}%",
                        "description": f"Portfolio has seen a maximum drawdown of {max_dd:.1f}%.",
                        "evidence":    f"max_drawdown={max_dd:.1f}%",
                        "implication": "Risk controls may need tightening for future cycles.",
                        "urgency":     "normal",
                        "subcategory": "drawdown",
                    })

                if perf.sharpe_ratio is not None and perf.sharpe_ratio < 0.5:
                    findings.append({
                        "title":       f"Low Sharpe Ratio: {perf.sharpe_ratio:.2f}",
                        "description": f"30-day rolling Sharpe ratio is {perf.sharpe_ratio:.2f}. Target ≥1.0.",
                        "evidence":    f"sharpe={perf.sharpe_ratio:.2f}",
                        "implication": "Risk-adjusted returns are poor. Strategy selection may be sub-optimal.",
                        "urgency":     "normal",
                        "subcategory": "risk_adjusted_return",
                    })
        except Exception as exc:
            log.debug("Performance snapshot query failed: %s", exc)

        # ── 2. Sector Concentration ──────────────────────────────
        try:
            open_trades = (
                db.query(PaperTrade)
                .filter(PaperTrade.is_open == True)
                .all()
            )
            if open_trades:
                trade_data_available = True
                sector_counts: dict[str, int] = {}
                total = len(open_trades)
                for t in open_trades:
                    stock  = db.query(Stock).filter(Stock.symbol == t.symbol).first()
                    sector = stock.sector if stock else "Unknown"
                    sector_counts[sector] = sector_counts.get(sector, 0) + 1

                for sector, count in sector_counts.items():
                    pct = count / total * 100
                    if pct > SECTOR_CONC_ALERT:
                        findings.append({
                            "title":       f"Sector Concentration: {sector} = {pct:.0f}% of positions",
                            "description": f"{count}/{total} open positions are in {sector} sector ({pct:.0f}%).",
                            "evidence":    f"sector={sector}, count={count}, pct={pct:.1f}%",
                            "implication": f"High concentration in {sector}. Sector event could cause correlated losses.",
                            "urgency":     "high" if pct > 60 else "normal",
                            "subcategory": "sector_concentration",
                        })
                        recommendations.append(f"Diversify away from {sector} concentration ({pct:.0f}%).")
        except Exception as exc:
            log.debug("Sector concentration query failed: %s", exc)

        # ── 3. Portfolio Exposure ────────────────────────────────
        try:
            ec = (
                db.query(EquityCurvePoint)
                .order_by(EquityCurvePoint.date.desc())
                .first()
            )
            if ec and ec.total_value:
                exposure_pct = (ec.invested / ec.total_value * 100) if ec.invested else 0
                if exposure_pct > EXPOSURE_ALERT:
                    findings.append({
                        "title":       f"High Portfolio Exposure: {exposure_pct:.0f}% deployed",
                        "description": f"Portfolio has {exposure_pct:.0f}% of capital deployed across positions.",
                        "evidence":    f"invested={ec.invested:.0f}, total={ec.total_value:.0f}, pct={exposure_pct:.1f}%",
                        "implication": "Limited cash buffer. No room for new opportunities or emergency exits.",
                        "urgency":     "normal",
                        "subcategory": "exposure",
                    })
        except Exception as exc:
            log.debug("Equity curve query failed: %s", exc)

        # ── 4. Tail Risk — recent large losses ───────────────────
        try:
            cutoff_30d   = date.today() - timedelta(days=30)
            large_losses = (
                db.query(PaperTrade)
                .filter(
                    PaperTrade.is_open    == False,
                    PaperTrade.exit_date  >= cutoff_30d,
                    PaperTrade.actual_return < -8.0,
                )
                .count()
            )
            if large_losses >= 3:
                findings.append({
                    "title":       f"Tail Risk Event: {large_losses} trades lost >8% in 30 days",
                    "description": f"{large_losses} closed trades had losses greater than 8% in the last 30 days.",
                    "evidence":    f"large_loss_count={large_losses}",
                    "implication": "Stop-loss levels may be too wide, or entry signals are poor-quality.",
                    "urgency":     "high",
                    "subcategory": "tail_risk",
                })
                recommendations.append("Review stop-loss calibration — large loss frequency is elevated.")
        except Exception as exc:
            log.debug("Tail risk query failed: %s", exc)

        # ── 5. Price-based risk proxies (when portfolio is empty) ─
        if not trade_data_available and not perf_data_available:
            try:
                cutoff_20d = date.today() - timedelta(days=28)
                ret_rows   = (
                    db.query(DailyPrice.symbol, DailyPrice.date, DailyPrice.daily_return)
                    .filter(
                        DailyPrice.date >= cutoff_20d,
                        DailyPrice.daily_return.isnot(None),
                    )
                    .order_by(DailyPrice.symbol, DailyPrice.date.asc())
                    .all()
                )

                if ret_rows:
                    # Collect all returns for VaR computation
                    all_returns: list[float] = [r.daily_return for r in ret_rows if r.daily_return is not None]

                    # Per-symbol max single-day loss
                    sym_rets: dict[str, list[float]] = defaultdict(list)
                    for row in ret_rows:
                        if row.daily_return is not None:
                            sym_rets[row.symbol].append(row.daily_return)

                    # VaR proxy: 5th percentile of all universe returns
                    if len(all_returns) >= 10:
                        sorted_rets  = sorted(all_returns)
                        var_index    = max(0, int(len(sorted_rets) * (1 - VAR_CONFIDENCE)) - 1)
                        var_95       = sorted_rets[var_index]
                        avg_ret      = sum(all_returns) / len(all_returns)
                        # Annualised std dev proxy
                        variance     = sum((r - avg_ret) ** 2 for r in all_returns) / len(all_returns)
                        std_dev_daily = math.sqrt(variance)
                        ann_vol      = std_dev_daily * math.sqrt(252)

                        findings.append({
                            "title":       f"Universe VaR Proxy (95%): {var_95:.2f}% daily",
                            "description": (
                                f"Based on {len(all_returns)} daily returns across {len(sym_rets)} stocks "
                                f"(last 20 trading days): "
                                f"95% VaR = {var_95:.2f}% per day. "
                                f"Annualised volatility proxy = {ann_vol:.1f}%."
                            ),
                            "evidence":    f"var_95={var_95:.2f}%, ann_vol={ann_vol:.1f}%, n_returns={len(all_returns)}",
                            "implication": (
                                "Elevated market volatility — use tighter position sizing."
                                if ann_vol > 25 else
                                "Volatility within normal range for NSE universe."
                            ),
                            "urgency":     "high" if ann_vol > 35 else "normal",
                            "subcategory": "var_proxy",
                        })

                    # Worst single-day loss across universe
                    max_loss_sym = min(sym_rets, key=lambda s: min(sym_rets[s]))
                    max_loss_val = min(sym_rets[max_loss_sym])
                    if max_loss_val < -5.0:
                        findings.append({
                            "title":       f"Max Single-Day Loss in Universe: {max_loss_sym} at {max_loss_val:.2f}%",
                            "description": (
                                f"The worst single-day return in the 20-day universe was "
                                f"{max_loss_val:.2f}% ({max_loss_sym}). "
                                f"This sets the floor for tail risk exposure."
                            ),
                            "evidence":    f"symbol={max_loss_sym}, max_loss={max_loss_val:.2f}%",
                            "implication": "Ensure stop-loss levels are wider than this value to avoid premature exits.",
                            "urgency":     "normal",
                            "subcategory": "tail_risk",
                        })

                    # NIFTY correlation with stock universe (simplified: avg return vs NIFTY return)
                    try:
                        nifty_rows = (
                            db.query(IndexData.date, IndexData.returns)
                            .filter(
                                IndexData.index_name == "NIFTY50",
                                IndexData.date >= cutoff_20d,
                                IndexData.returns.isnot(None),
                            )
                            .order_by(IndexData.date.asc())
                            .all()
                        )
                        if nifty_rows and len(nifty_rows) >= 5:
                            nifty_dates = {r.date: r.returns for r in nifty_rows}
                            # Compute daily avg universe return per date
                            date_rets: dict[object, list[float]] = defaultdict(list)
                            for row in ret_rows:
                                if row.daily_return is not None:
                                    date_rets[row.date].append(row.daily_return)

                            common_dates = sorted(set(nifty_dates.keys()) & set(date_rets.keys()))
                            if len(common_dates) >= 5:
                                nifty_rets_list = [nifty_dates[d] for d in common_dates]
                                univ_rets_list  = [sum(date_rets[d]) / len(date_rets[d]) for d in common_dates]

                                n          = len(common_dates)
                                nifty_mean = sum(nifty_rets_list) / n
                                univ_mean  = sum(univ_rets_list) / n
                                cov        = sum((nifty_rets_list[i] - nifty_mean) * (univ_rets_list[i] - univ_mean) for i in range(n)) / n
                                nifty_std  = math.sqrt(sum((r - nifty_mean) ** 2 for r in nifty_rets_list) / n)
                                univ_std   = math.sqrt(sum((r - univ_mean) ** 2 for r in univ_rets_list) / n)
                                corr       = cov / (nifty_std * univ_std) if nifty_std > 0 and univ_std > 0 else 0.0

                                findings.append({
                                    "title":       f"Universe-NIFTY50 Correlation: {corr:.2f} (20d)",
                                    "description": (
                                        f"Average correlation between stock universe and NIFTY50 over last {n} trading days: {corr:.2f}. "
                                        f"High correlation (>0.85) means limited diversification benefit."
                                    ),
                                    "evidence":    f"correlation={corr:.2f}, n_days={n}",
                                    "implication": (
                                        "Universe is highly correlated with the index — little diversification protection."
                                        if corr > 0.85 else
                                        "Universe correlation with index is within acceptable range."
                                    ),
                                    "urgency":     "normal",
                                    "subcategory": "correlation",
                                })
                    except Exception as exc2:
                        log.debug("Correlation calculation failed: %s", exc2)

            except Exception as exc:
                log.debug("Price-based risk proxy analysis failed: %s", exc)

        # ── Fallback ──────────────────────────────────────────────
        if not findings:
            findings.append({
                "title":       "Risk System Initialising — No Portfolio Data Yet",
                "description": "Paper trades, performance snapshots, and price history are all unavailable.",
                "evidence":    "perf_rows=0, trade_rows=0, price_rows=0",
                "implication": "Complete at least one data ingestion and paper trading cycle before risk assessment can begin.",
                "urgency":     "low",
                "subcategory": "data_coverage",
            })

        # Build summary safely
        try:
            perf_latest = db.query(PerformanceSnapshot).order_by(PerformanceSnapshot.date.desc()).first()
            dd_str = f"drawdown={perf_latest.current_drawdown_pct:.1f}% " if perf_latest and perf_latest.current_drawdown_pct else "no portfolio data "
        except Exception:
            dd_str = "no portfolio data "

        summary = (
            f"Risk assessment: {dd_str}"
            f"{len(findings)} findings. "
            + (
                "Critical risks detected."
                if any(f["urgency"] == "critical" for f in findings) else
                "No critical issues."
            )
        )

        urgency = (
            "critical" if any(f["urgency"] == "critical" for f in findings) else
            "high"     if any(f["urgency"] == "high"     for f in findings) else
            "normal"
        )

        return {
            "title":           f"Risk Research — {date.today()}",
            "summary":         summary,
            "findings":        findings,
            "recommendations": recommendations,
            "urgency":         urgency,
        }


register_agent_class(RiskResearchAgent)
