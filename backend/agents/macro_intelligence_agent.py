"""
Macro Intelligence Agent
Tracks global macro indicators: crude, gold, USD/INR, US yields, S&P.
All data via yfinance — completely free.

MAY NOT: modify strategies, retrain models, execute trades.
"""

from __future__ import annotations

import sys, os
from datetime import date, timedelta

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from sqlalchemy.orm import Session
from aqrti.database.models import MarketRegime
from aqrti.utils.logger import get_logger
from agents.agent_base import AgentBase
from agents.agent_registry import register_agent_class

log = get_logger("agent.macro_intelligence")

# Macro tickers — all free via yfinance
MACRO_TICKERS = {
    "S&P 500":       "^GSPC",
    "Gold":          "GC=F",
    "Crude Oil":     "CL=F",
    "USD/INR":       "USDINR=X",
    "US 10Y Yield":  "^TNX",
}


def _safe_pct(new_val, old_val):
    if old_val and old_val != 0 and new_val:
        return (new_val - old_val) / old_val * 100
    return None


class MacroIntelligenceAgent(AgentBase):
    agent_id    = "macro_intelligence"
    agent_type  = "macro_intelligence"
    name        = "Macro Intelligence Agent"
    description = "Tracks crude/gold/USD-INR/US yields/S&P to generate macro risk findings for NSE."

    def run(self, db: Session) -> dict:
        findings        = []
        recommendations = []
        today           = date.today()
        macro_context   = []

        # ── 1. Fetch macro data from yfinance ─────────────────────
        try:
            import yfinance as yf
            end_date   = today.strftime("%Y-%m-%d")
            start_date = (today - timedelta(days=35)).strftime("%Y-%m-%d")

            for label, ticker in MACRO_TICKERS.items():
                try:
                    hist = yf.download(ticker, start=start_date, end=end_date,
                                       progress=False, auto_adjust=True)
                    if hist is None or len(hist) < 2:
                        continue

                    close_col = "Close"
                    if close_col not in hist.columns:
                        continue

                    closes = hist[close_col].dropna()
                    if len(closes) < 2:
                        continue

                    latest    = float(closes.iat[-1])
                    prev_1d   = float(closes.iat[-2])
                    prev_5d   = float(closes.iat[max(-6, -len(closes))])
                    prev_20d  = float(closes.iat[max(-21, -len(closes))])

                    ret_5d  = _safe_pct(latest, prev_5d)
                    ret_20d = _safe_pct(latest, prev_20d)

                    # ── Risk signal detection ──────────────────────
                    if ticker == "CL=F" and ret_5d is not None and ret_5d > 5:
                        findings.append({
                            "title":       f"Crude Spike: +{ret_5d:.1f}% in 5 days (${latest:.1f})",
                            "description": (
                                f"Crude oil (WTI) rose {ret_5d:+.1f}% over 5 days to ${latest:.1f}. "
                                f"Sustained crude above +5% indicates inflation risk for India."
                            ),
                            "evidence":    f"CL=F: latest={latest:.2f}, 5d_ret={ret_5d:.2f}%",
                            "implication": "Inflation risk rising. FMCG, paint, aviation stocks may face margin pressure.",
                            "urgency":     "high",
                            "subcategory": "crude_spike",
                        })
                        macro_context.append(f"crude_spike={ret_5d:.1f}%")
                        recommendations.append("Review BPCL/HPCL exposure — crude spike compresses OMC margins.")

                    elif ticker == "USDINR=X" and ret_5d is not None and ret_5d > 1:
                        findings.append({
                            "title":       f"Rupee Weakening: USD/INR at {latest:.2f} (+{ret_5d:.1f}% in 5d)",
                            "description": (
                                f"USD/INR weakened {ret_5d:+.1f}% over 5 days to {latest:.2f}. "
                                f">1% depreciation signals potential FII outflows."
                            ),
                            "evidence":    f"USDINR=X: latest={latest:.2f}, 5d_ret={ret_5d:.2f}%",
                            "implication": "FII outflow risk elevated. Exporters (IT, Pharma) may benefit; importers at risk.",
                            "urgency":     "high",
                            "subcategory": "usdinr_weakness",
                        })
                        macro_context.append(f"rupee_weak={ret_5d:.1f}%")
                        recommendations.append("Watch FII flow data — rupee weakness often precedes equity selloff.")

                    elif ticker == "^TNX" and ret_20d is not None and ret_20d > 5:
                        findings.append({
                            "title":       f"US Yields Rising: ^TNX at {latest:.2f}% (+{ret_20d:.1f}% in 20d)",
                            "description": (
                                f"US 10Y yield rose {ret_20d:+.1f}% over 20 days to {latest:.2f}%. "
                                f"Rising yields increase risk-off pressure on EMs."
                            ),
                            "evidence":    f"^TNX: latest={latest:.2f}, 20d_ret={ret_20d:.2f}%",
                            "implication": "Risk-off signal: EM capital outflow risk. Defensive sectors may outperform.",
                            "urgency":     "high",
                            "subcategory": "us_yield_rise",
                        })
                        macro_context.append(f"us_yield_rise={ret_20d:.1f}%")

                    # ── General summary finding ────────────────────
                    if ret_5d is not None:
                        findings.append({
                            "title":       f"Macro: {label} = {latest:.2f} ({ret_5d:+.1f}% 5d)",
                            "description": f"{label} at {latest:.2f}, 5d change={ret_5d:+.1f}%, 20d change={ret_20d:+.1f}% (if available).",
                            "evidence":    f"ticker={ticker}, latest={latest:.4f}, ret_5d={ret_5d:.2f}%",
                            "implication": "Informational — monitor for further divergence.",
                            "urgency":     "low",
                            "subcategory": "macro_summary",
                        })

                except Exception as exc:
                    log.debug("Macro ticker %s failed: %s", ticker, exc)
        except ImportError:
            findings.append({
                "title":       "yfinance Unavailable",
                "description": "yfinance package not installed — macro data unavailable.",
                "evidence":    "import_error=True",
                "implication": "Install yfinance to enable macro intelligence.",
                "urgency":     "normal",
                "subcategory": "dependency_missing",
            })
        except Exception as exc:
            log.debug("Macro data fetch skipped: %s", exc)

        # ── 2. Annotate current MarketRegime with macro context ───
        try:
            if macro_context:
                latest_regime = (
                    db.query(MarketRegime)
                    .order_by(MarketRegime.date.desc())
                    .first()
                )
                if latest_regime:
                    import json
                    existing = json.loads(latest_regime.metadata_json or "{}")
                    existing["macro_context"] = macro_context
                    existing["macro_date"]    = str(today)
                    latest_regime.metadata_json = json.dumps(existing)
        except Exception as exc:
            log.debug("Regime annotation skipped: %s", exc)

        if not findings:
            findings.append({
                "title":       "Macro Data Unavailable",
                "description": "No macro data fetched — yfinance timeout or no internet access.",
                "evidence":    "fetched_tickers=0",
                "implication": "Macro intelligence disabled until connectivity is restored.",
                "urgency":     "low",
                "subcategory": "data_coverage",
            })

        # Filter out low-urgency summary findings if we have real signals
        signal_findings = [f for f in findings if f.get("subcategory") != "macro_summary"]
        summary_findings = [f for f in findings if f.get("subcategory") == "macro_summary"]
        all_findings = signal_findings + summary_findings[:3]  # cap summaries at 3

        summary = (
            f"Macro intelligence: {len(all_findings)} findings, "
            f"signals={len(signal_findings)}, "
            f"context=[{', '.join(macro_context)}]."
        )
        return {
            "title":           f"Macro Intelligence — {today}",
            "summary":         summary,
            "findings":        all_findings,
            "recommendations": recommendations,
            "urgency":         "high" if any(f.get("urgency") == "high" for f in all_findings) else "normal",
        }


register_agent_class(MacroIntelligenceAgent)
