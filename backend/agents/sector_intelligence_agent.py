"""
Sector Intelligence Agent
Monitors sector rotation phases, identifies leadership and weakness.

MAY NOT: modify strategies, execute trades, retrain models.
"""

from __future__ import annotations

import sys, os, json
from datetime import date, timedelta
from collections import defaultdict

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from sqlalchemy.orm import Session
from aqrti.database.models import SectorRotation, DailyPrice, Stock
from aqrti.utils.logger import get_logger
from agents.agent_base import AgentBase
from agents.agent_registry import register_agent_class

log = get_logger("agent.sector_intelligence")


class SectorIntelligenceAgent(AgentBase):
    agent_id    = "sector_intelligence"
    agent_type  = "sector_intelligence"
    name        = "Sector Intelligence Agent"
    description = "Monitors sector rotation phases, identifies leading/lagging sectors and rotation switches."

    def run(self, db: Session) -> dict:
        findings        = []
        recommendations = []
        today           = date.today()
        last_week       = today - timedelta(days=7)
        cutoff_30d      = today - timedelta(days=30)

        # ── 1. Read SectorRotation table ─────────────────────────
        try:
            latest_rotations = (
                db.query(SectorRotation)
                .filter(SectorRotation.rotation_date >= last_week)
                .order_by(SectorRotation.rotation_date.desc())
                .all()
            )

            prior_rotations = (
                db.query(SectorRotation)
                .filter(
                    SectorRotation.rotation_date >= cutoff_30d,
                    SectorRotation.rotation_date < last_week,
                )
                .order_by(SectorRotation.rotation_date.desc())
                .all()
            )

            if latest_rotations:
                # Group latest by sector (take most recent per sector)
                latest_by_sector: dict[str, SectorRotation] = {}
                for row in latest_rotations:
                    if row.sector not in latest_by_sector:
                        latest_by_sector[row.sector] = row

                prior_by_sector: dict[str, SectorRotation] = {}
                for row in prior_rotations:
                    if row.sector not in prior_by_sector:
                        prior_by_sector[row.sector] = row

                # ── LEADING sectors ────────────────────────────────
                leading = [
                    r for r in latest_by_sector.values()
                    if r.rotation_phase == "LEADING" and (r.momentum_score or 0) > 60
                ]
                if leading:
                    leading_names = [r.sector for r in sorted(leading, key=lambda x: x.momentum_score or 0, reverse=True)]
                    findings.append({
                        "title":       f"Leading Sectors: {', '.join(leading_names[:3])}",
                        "description": (
                            f"{len(leading)} sectors in LEADING phase with momentum > 60: "
                            f"{', '.join(leading_names)}."
                        ),
                        "evidence":    f"leading_sectors={leading_names}, phase=LEADING, momentum>60",
                        "implication": "Overweight these sectors in next portfolio rebalance.",
                        "urgency":     "normal",
                        "subcategory": "leading_sectors",
                    })
                    recommendations.append(f"Overweight LEADING sectors: {', '.join(leading_names[:3])}.")

                # ── LAGGING sectors ────────────────────────────────
                lagging = [
                    r for r in latest_by_sector.values()
                    if r.rotation_phase == "LAGGING"
                ]
                if lagging:
                    lagging_names = [r.sector for r in lagging]
                    findings.append({
                        "title":       f"Lagging Sectors: {', '.join(lagging_names[:3])}",
                        "description": f"{len(lagging)} sectors in LAGGING phase: {', '.join(lagging_names)}.",
                        "evidence":    f"lagging_sectors={lagging_names}, phase=LAGGING",
                        "implication": "Reduce exposure to lagging sectors; look for exits.",
                        "urgency":     "normal",
                        "subcategory": "lagging_sectors",
                    })
                    recommendations.append(f"Underweight LAGGING sectors: {', '.join(lagging_names[:3])}.")

                # ── Rotation switches: compare current vs prior week ──
                switches = []
                for sector, current in latest_by_sector.items():
                    prior = prior_by_sector.get(sector)
                    if prior and current.rotation_phase != prior.rotation_phase:
                        switches.append({
                            "sector": sector,
                            "from":   prior.rotation_phase,
                            "to":     current.rotation_phase,
                            "momentum": current.momentum_score or 0,
                        })

                for sw in switches[:5]:
                    urgency = "high" if (
                        sw["to"] in ("LEADING", "LAGGING") or
                        sw["from"] in ("LEADING",) and sw["to"] == "WEAKENING"
                    ) else "normal"
                    findings.append({
                        "title":       f"Rotation Switch: {sw['sector']} {sw['from']} → {sw['to']}",
                        "description": (
                            f"Sector '{sw['sector']}' shifted from {sw['from']} to {sw['to']} "
                            f"this week (momentum={sw['momentum']:.1f})."
                        ),
                        "evidence":    f"sector={sw['sector']}, from={sw['from']}, to={sw['to']}, momentum={sw['momentum']:.1f}",
                        "implication": (
                            f"{'Emerging leadership — consider adding exposure.' if sw['to'] == 'LEADING' else ''}"
                            f"{'Weakening leader — reduce overweight.' if sw['to'] == 'WEAKENING' else ''}"
                            f"{'Sector losing momentum — exit or underweight.' if sw['to'] == 'LAGGING' else ''}"
                            f"{'Recovery signal — watch for confirmation.' if sw['to'] == 'IMPROVING' else ''}"
                        ),
                        "urgency":     urgency,
                        "subcategory": "rotation_switch",
                    })
            else:
                log.debug("No SectorRotation data found — falling back to DailyPrice calculation")
        except Exception as exc:
            log.debug("SectorRotation read skipped: %s", exc)

        # ── 2. Fallback: compute sector returns from DailyPrice ───
        try:
            if not findings or all(f.get("subcategory") == "data_coverage" for f in findings):
                stocks = db.query(Stock.symbol, Stock.sector).filter(Stock.active == True).all()
                sector_symbols: dict[str, list[str]] = defaultdict(list)
                for sym, sector in stocks:
                    if sector:
                        sector_symbols[sector].append(sym)

                sector_rets: dict[str, float] = {}
                for sector, symbols in sector_symbols.items():
                    rets = []
                    for sym in symbols[:10]:  # sample up to 10 per sector
                        rows = (
                            db.query(DailyPrice.close, DailyPrice.date)
                            .filter(DailyPrice.symbol == sym, DailyPrice.date >= cutoff_30d)
                            .order_by(DailyPrice.date.desc())
                            .limit(6)
                            .all()
                        )
                        if len(rows) >= 2:
                            old_close = rows[min(4, len(rows)-1)].close
                            if old_close and old_close > 0:
                                rets.append((rows[0].close - old_close) / old_close * 100)
                    if rets:
                        sector_rets[sector] = sum(rets) / len(rets)

                if sector_rets:
                    top_s = max(sector_rets, key=sector_rets.get)
                    bot_s = min(sector_rets, key=sector_rets.get)
                    findings.append({
                        "title":       f"Top Sector (5d): {top_s} ({sector_rets[top_s]:+.1f}%)",
                        "description": f"{top_s} leads with {sector_rets[top_s]:+.1f}% avg 5d return across {len(sector_symbols.get(top_s,[]))} stocks.",
                        "evidence":    f"sector={top_s}, ret_5d={sector_rets[top_s]:.2f}%",
                        "implication": "Consider overweighting this sector.",
                        "urgency":     "normal",
                        "subcategory": "sector_performance",
                    })
                    findings.append({
                        "title":       f"Weak Sector (5d): {bot_s} ({sector_rets[bot_s]:+.1f}%)",
                        "description": f"{bot_s} lags with {sector_rets[bot_s]:+.1f}% avg 5d return.",
                        "evidence":    f"sector={bot_s}, ret_5d={sector_rets[bot_s]:.2f}%",
                        "implication": "Consider underweighting or avoiding this sector.",
                        "urgency":     "normal" if sector_rets[bot_s] > -3 else "high",
                        "subcategory": "sector_performance",
                    })
        except Exception as exc:
            log.debug("Sector fallback calculation skipped: %s", exc)

        if not findings:
            findings.append({
                "title":       "Sector Data Unavailable",
                "description": "No SectorRotation records found and DailyPrice too sparse for sector analysis.",
                "evidence":    "sector_rotation_rows=0",
                "implication": "Run data_supremacy sector pipeline to populate sector rotation table.",
                "urgency":     "low",
                "subcategory": "data_coverage",
            })

        summary = (
            f"Sector intelligence: {len(findings)} findings, "
            f"leading={len([f for f in findings if f.get('subcategory')=='leading_sectors'])}, "
            f"switches={len([f for f in findings if f.get('subcategory')=='rotation_switch'])}."
        )
        return {
            "title":           f"Sector Intelligence — {today}",
            "summary":         summary,
            "findings":        findings,
            "recommendations": recommendations,
            "urgency":         "high" if any(f.get("urgency") == "high" for f in findings) else "normal",
        }


register_agent_class(SectorIntelligenceAgent)
