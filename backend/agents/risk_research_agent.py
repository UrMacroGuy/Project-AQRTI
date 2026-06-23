"""
Risk Research Agent (7F)
Analyzes portfolio risk, sector concentration, exposure, tail risk, drawdown trends.

MAY NOT: modify portfolio allocations, adjust position sizes, execute any trades.
"""

from __future__ import annotations

import sys, os
from datetime import date, timedelta

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from sqlalchemy.orm import Session
from sqlalchemy import func
from aqrti.database.models import (
    PaperTrade, PerformanceSnapshot, EquityCurvePoint,
    FailureRecord, Stock,
)
from aqrti.utils.logger import get_logger
from agents.agent_base import AgentBase
from agents.agent_registry import register_agent_class

log = get_logger("agent.risk_research")

MAX_DRAWDOWN_ALERT   = -15.0   # % — alert if max drawdown exceeds this
SECTOR_CONC_ALERT    = 40.0    # % — alert if any sector exceeds this % of open positions
EXPOSURE_ALERT       = 80.0    # % — alert if capital deployed exceeds this


class RiskResearchAgent(AgentBase):
    agent_id    = "risk_research"
    agent_type  = "risk"
    name        = "Risk Research Agent"
    description = "Analyzes portfolio risk, sector concentration, exposure, tail risk, and drawdown trends."

    def run(self, db: Session) -> dict:
        findings        = []
        recommendations = []

        # ── 1. Current Drawdown ──────────────────────────────────
        perf = (
            db.query(PerformanceSnapshot)
            .order_by(PerformanceSnapshot.date.desc())
            .first()
        )
        if perf:
            dd = perf.current_drawdown_pct or 0.0
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

        # ── 2. Sector Concentration ──────────────────────────────
        open_trades = (
            db.query(PaperTrade)
            .filter(PaperTrade.is_open == True)
            .all()
        )
        if open_trades:
            sector_counts: dict[str, int] = {}
            total = len(open_trades)
            for t in open_trades:
                stock = db.query(Stock).filter(Stock.symbol == t.symbol).first()
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

        # ── 3. Portfolio Exposure ────────────────────────────────
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

        # ── 4. Tail Risk — recent large losses ───────────────────
        cutoff_30d = date.today() - timedelta(days=30)
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
            findings.append({
                "title":       f"Tail Risk Event: {large_losses} trades lost >8% in 30 days",
                "description": f"{large_losses} closed trades had losses greater than 8% in the last 30 days.",
                "evidence":    f"large_loss_count={large_losses}",
                "implication": "Stop-loss levels may be too wide, or entry signals are poor-quality.",
                "urgency":     "high",
                "subcategory": "tail_risk",
            })
            recommendations.append("Review stop-loss calibration — large loss frequency is elevated.")

        # ── 5. Sharpe Trend ──────────────────────────────────────
        if perf and perf.sharpe_ratio is not None:
            sharpe = perf.sharpe_ratio
            if sharpe < 0.5:
                findings.append({
                    "title":       f"Low Sharpe Ratio: {sharpe:.2f}",
                    "description": f"30-day rolling Sharpe ratio is {sharpe:.2f}. Target ≥1.0.",
                    "evidence":    f"sharpe={sharpe:.2f}",
                    "implication": "Risk-adjusted returns are poor. Strategy selection may be sub-optimal.",
                    "urgency":     "normal",
                    "subcategory": "risk_adjusted_return",
                })

        summary = (
            f"Risk assessment: "
            f"drawdown={perf.current_drawdown_pct:.1f}% " if perf else "no perf data. "
        ) + f"{len(findings)} findings. " + (
            "Critical risks detected." if any(f["urgency"] == "critical" for f in findings)
            else "No critical issues."
        )

        urgency = "critical" if any(f["urgency"] == "critical" for f in findings) else \
                  "high"     if any(f["urgency"] == "high"     for f in findings) else "normal"

        return {
            "title":           f"Risk Research — {date.today()}",
            "summary":         summary,
            "findings":        findings,
            "recommendations": recommendations,
            "urgency":         urgency,
        }


register_agent_class(RiskResearchAgent)
