"""
Failure Scientist Agent
Clusters failures by regime/category, generates prevention rules.

MAY NOT: modify strategies, retrain models, execute trades.
"""

from __future__ import annotations

import sys, os
from datetime import date, timedelta
from collections import defaultdict

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from sqlalchemy.orm import Session
from aqrti.database.models import FailureRecord
from aqrti.utils.logger import get_logger
from agents.agent_base import AgentBase
from agents.agent_registry import register_agent_class

log = get_logger("agent.failure_scientist")


class FailureScientistAgent(AgentBase):
    agent_id    = "failure_scientist"
    agent_type  = "failure_scientist"
    name        = "Failure Scientist Agent"
    description = "Clusters failures by regime/category and generates actionable prevention rules."

    def run(self, db: Session) -> dict:
        findings        = []
        recommendations = []
        today           = date.today()
        cutoff_7d       = today - timedelta(days=7)

        # ── 1. Wrap root_cause_engine ─────────────────────────────
        try:
            from learning.root_cause_engine import run_failure_analysis
            analysis = run_failure_analysis(db, days=7)
            failures_processed = analysis.get("failures_processed", 0)
            log.debug("Root cause engine: processed=%d", failures_processed)
        except Exception as exc:
            log.debug("Root cause engine skipped: %s", exc)

        # ── 2. Cluster last 7d failures by regime + category ──────
        try:
            recent = (
                db.query(FailureRecord)
                .filter(FailureRecord.failure_date >= cutoff_7d)
                .all()
            )
            if not recent:
                findings.append({
                    "title":       "No Failures Detected (7d)",
                    "description": "No failure records found in the last 7 days.",
                    "evidence":    "failure_records_7d=0",
                    "implication": "System is performing within expected parameters.",
                    "urgency":     "low",
                    "subcategory": "failure_summary",
                })
            else:
                # Cluster by regime + category
                clusters: dict[tuple, list] = defaultdict(list)
                for f in recent:
                    key = (f.regime_at or "UNKNOWN", f.failure_category or "unknown")
                    clusters[key].append(f)

                total_failures = len(recent)
                for (regime, category), cluster in clusters.items():
                    cluster_count   = len(cluster)
                    failure_rate    = cluster_count / total_failures * 100
                    severity_counts = defaultdict(int)
                    for f in cluster:
                        severity_counts[f.severity or "low"] += 1

                    dominant_sev = max(severity_counts, key=severity_counts.get)
                    urgency = "CRITICAL" if failure_rate > 40 else ("HIGH" if failure_rate > 20 else "MEDIUM")

                    # Prevention rule text
                    if category == "false_positive":
                        rule = f"In {regime} regime: tighten signal confirmation threshold by 10%."
                    elif category == "overconfidence":
                        rule = f"In {regime} regime: cap confidence scores at 0.75 until resolved."
                    elif category == "regime":
                        rule = "Regime misclassification cluster — trigger regime re-calibration."
                    elif category == "feature":
                        rule = f"Feature-driven failures in {regime}: run feature decay detection."
                    else:
                        rule = f"Cluster [{regime}/{category}]: investigate signal quality in this regime."

                    findings.append({
                        "title":       f"Failure Cluster: {regime}/{category} — {cluster_count} failures ({failure_rate:.0f}%)",
                        "description": (
                            f"{cluster_count} failures in {regime} regime, category='{category}' "
                            f"over last 7 days. Dominant severity: {dominant_sev}."
                        ),
                        "evidence":    (
                            f"regime={regime}, category={category}, count={cluster_count}, "
                            f"rate={failure_rate:.1f}%, severity={dominant_sev}"
                        ),
                        "implication": rule,
                        "urgency":     urgency.lower(),
                        "subcategory": "failure_cluster",
                        "regime":      regime,
                    })
                    recommendations.append(rule)

                    # Alert CRO for high-severity clusters
                    if failure_rate > 40:
                        try:
                            self.send_message(
                                db,
                                to_agent   = "cro",
                                subject    = f"URGENT: Failure cluster {regime}/{category} ({failure_rate:.0f}% of failures)",
                                body       = rule,
                                message_type = "alert",
                                priority   = 1,
                            )
                        except Exception as exc:
                            log.debug("CRO alert skipped: %s", exc)
        except Exception as exc:
            log.debug("Failure clustering skipped: %s", exc)

        summary = (
            f"Failure scientist: {len(findings)} cluster findings, "
            f"critical_clusters={len([f for f in findings if f.get('urgency') in ('critical', 'high')])}."
        )
        return {
            "title":           f"Failure Science Report — {today}",
            "summary":         summary,
            "findings":        findings,
            "recommendations": recommendations,
            "urgency":         "high" if any(f.get("urgency") in ("critical", "high") for f in findings) else "normal",
        }


register_agent_class(FailureScientistAgent)
