"""
Feature Discovery Agent
Proposes new predictive features using IC analysis and hypothesis generation.

MAY NOT: deploy features, retrain models, execute trades.
"""

from __future__ import annotations

import sys, os
from datetime import date, timedelta

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from sqlalchemy.orm import Session
from aqrti.database.models import FeatureValue, DailyPrice
from aqrti.utils.logger import get_logger
from agents.agent_base import AgentBase
from agents.agent_registry import register_agent_class

log = get_logger("agent.feature_discovery")


class FeatureDiscoveryAgent(AgentBase):
    agent_id    = "feature_discovery"
    agent_type  = "feature_discovery"
    name        = "Feature Discovery Agent"
    description = "Autonomously proposes new predictive features using IC analysis and hypothesis generation."

    def run(self, db: Session) -> dict:
        findings        = []
        recommendations = []
        today           = date.today()

        # ── 1. Wrap existing feature discovery pipeline ───────────
        pipeline_proposals = 0
        try:
            from intelligence_training.feature_discovery import run_feature_discovery_pipeline
            result = run_feature_discovery_pipeline(days_back=90)
            proposals = result.get("proposals", [])
            pipeline_proposals = len(proposals)
            for p in proposals[:5]:  # surface top 5
                findings.append({
                    "title":       f"Feature Proposal: {p.get('name', 'Unknown')}",
                    "description": p.get("description", "New feature candidate from discovery pipeline."),
                    "evidence":    f"ic={p.get('ic', 0):.3f}, category={p.get('category', 'unknown')}",
                    "implication": "High-IC feature may improve prediction accuracy if validated.",
                    "urgency":     "high" if (p.get("ic") or 0) > 0.05 else "normal",
                    "subcategory": "pipeline_proposal",
                })
        except Exception as exc:
            log.debug("Feature discovery pipeline skipped: %s", exc)

        # ── 2. Simple correlation hypothesis: feature pairs vs 5d forward return ──
        try:
            cutoff = today - timedelta(days=60)
            feature_rows = (
                db.query(FeatureValue.feature_name, FeatureValue.symbol,
                         FeatureValue.date, FeatureValue.value)
                .filter(FeatureValue.date >= cutoff)
                .limit(5000)
                .all()
            )

            # Group feature values by (feature_name, symbol, date)
            feature_map: dict[str, dict[tuple, float]] = {}
            for row in feature_rows:
                feature_map.setdefault(row.feature_name, {})[(row.symbol, row.date)] = row.value

            # Get 5d forward returns from DailyPrice
            price_rows = (
                db.query(DailyPrice.symbol, DailyPrice.date, DailyPrice.close)
                .filter(DailyPrice.date >= cutoff)
                .all()
            )
            prices: dict[tuple, float] = {(r.symbol, r.date): r.close for r in price_rows}

            def _fwd_return(symbol, dt):
                close_now = prices.get((symbol, dt))
                close_5d  = prices.get((symbol, dt + timedelta(days=7)))  # ~5 trading days
                if close_now and close_5d and close_now > 0:
                    return (close_5d - close_now) / close_now
                return None

            # Compute IC per feature
            feature_ics: dict[str, float] = {}
            for feat_name, sym_date_val in feature_map.items():
                pairs = []
                for (sym, dt), val in sym_date_val.items():
                    fwd = _fwd_return(sym, dt)
                    if val is not None and fwd is not None:
                        pairs.append((val, fwd))
                if len(pairs) < 30:
                    continue
                vals  = [p[0] for p in pairs]
                fwds  = [p[1] for p in pairs]
                mean_v = sum(vals) / len(vals)
                mean_f = sum(fwds) / len(fwds)
                cov    = sum((v - mean_v) * (f - mean_f) for v, f in pairs) / len(pairs)
                std_v  = (sum((v - mean_v) ** 2 for v in vals) / len(vals)) ** 0.5
                std_f  = (sum((f - mean_f) ** 2 for f in fwds) / len(fwds)) ** 0.5
                if std_v > 0 and std_f > 0:
                    feature_ics[feat_name] = cov / (std_v * std_f)

            # Surface top uncorrelated-looking features with high IC
            top_features = sorted(feature_ics.items(), key=lambda x: abs(x[1]), reverse=True)[:3]
            for feat_name, ic in top_features:
                if abs(ic) > 0.03:
                    findings.append({
                        "title":       f"High-IC Feature Detected: {feat_name} (IC={ic:.3f})",
                        "description": (
                            f"Feature '{feat_name}' shows IC={ic:.3f} vs 5d forward return "
                            f"over last 60 days. Warrants deeper validation."
                        ),
                        "evidence":    f"feature={feat_name}, ic={ic:.4f}, n_obs={len(feature_map.get(feat_name, {}))}",
                        "implication": "Consider promoting this feature in next model training cycle.",
                        "urgency":     "high" if abs(ic) > 0.06 else "normal",
                        "subcategory": "ic_analysis",
                    })
                    recommendations.append(f"Validate {feat_name} (IC={ic:.3f}) in holdout period before promotion.")
        except Exception as exc:
            log.debug("IC hypothesis generation skipped: %s", exc)

        # ── 3. Broadcast high-IC proposals to CRO ─────────────────
        try:
            high_ic = [f for f in findings if f.get("urgency") == "high"]
            if high_ic:
                self.broadcast(
                    db,
                    subject=f"Feature Discovery: {len(high_ic)} high-IC proposals",
                    body="\n".join(f["title"] for f in high_ic),
                    payload={"proposals": high_ic},
                )
        except Exception as exc:
            log.debug("Broadcast skipped: %s", exc)

        if not findings:
            findings.append({
                "title":       "Feature Discovery: No Data Yet",
                "description": "Feature value table is empty or too sparse for IC analysis.",
                "evidence":    "feature_value_rows=0",
                "implication": "Run feature engineering pipeline to populate feature_values table.",
                "urgency":     "low",
                "subcategory": "data_coverage",
            })

        summary = (
            f"Feature discovery: pipeline_proposals={pipeline_proposals}, "
            f"ic_proposals={len([f for f in findings if f.get('subcategory') == 'ic_analysis'])}, "
            f"total_findings={len(findings)}."
        )
        return {
            "title":           f"Feature Discovery — {today}",
            "summary":         summary,
            "findings":        findings,
            "recommendations": recommendations,
            "urgency":         "high" if any(f["urgency"] == "high" for f in findings) else "normal",
        }


register_agent_class(FeatureDiscoveryAgent)
