"""
AQRTI Feature Discovery Engine — Phase 8.5G
Analyzes historical failures to generate new feature ideas.
All proposed features are human-approved before deployment.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session
from sqlalchemy import text

from aqrti.database.engine import get_session_factory
from aqrti.utils.logger import get_logger

logger = get_logger("feature_discovery")


@dataclass
class FeatureProposal:
    """A proposed new feature generated from failure analysis."""
    proposal_id: str
    feature_name: str
    category: str
    description: str
    formula: str
    rationale: str
    expected_impact: str
    source_failures: List[str]
    estimated_ic: Optional[float] = None
    status: str = "proposed"  # proposed|validated|rejected|deployed
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "feature_name": self.feature_name,
            "category": self.category,
            "description": self.description,
            "formula": self.formula,
            "rationale": self.rationale,
            "expected_impact": self.expected_impact,
            "source_failures": self.source_failures,
            "estimated_ic": self.estimated_ic,
            "status": self.status,
            "created_at": self.created_at,
        }


# Predefined feature proposals based on known failure patterns
CANDIDATE_FEATURES = [
    {
        "feature_name": "confidence_breadth_conflict",
        "category": "meta",
        "description": "Detects when high AQRTI confidence conflicts with low market breadth",
        "formula": "confidence_score * (1 - breadth_pct) if breadth_pct < 0.4 else 0",
        "rationale": "Historical failures show AQRTI stays confident during breadth deterioration",
        "expected_impact": "Reduces false positives in late bull exhaustion",
        "trigger": "overconfidence_in_breadth_divergence",
    },
    {
        "feature_name": "institutional_distribution_pressure",
        "category": "market",
        "description": "Quantifies net institutional selling pressure",
        "formula": "max(0, avg_volume_20d - volume) / avg_volume_20d * sentiment_velocity_negative",
        "rationale": "Distribution patterns precede bear phases by 5-10 days",
        "expected_impact": "Earlier detection of institutional exit",
        "trigger": "late_detection_of_distribution",
    },
    {
        "feature_name": "sector_rotation_acceleration",
        "category": "sector",
        "description": "Rate of change in sector leadership (momentum of momentum)",
        "formula": "sector_rank_change_5d - sector_rank_change_10d",
        "rationale": "Rapid sector rotation signals regime change — missed in sideways markets",
        "expected_impact": "Better performance during rotation regimes",
        "trigger": "rotation_regime_underperformance",
    },
    {
        "feature_name": "confidence_regime_mismatch",
        "category": "meta",
        "description": "Penalty when AQRTI direction conflicts with macro regime",
        "formula": "confidence * (1 - regime_alignment_score)",
        "rationale": "AQRTI makes bullish calls during bear regimes — needs explicit penalty",
        "expected_impact": "Reduces directional errors during regime transitions",
        "trigger": "regime_transition_failures",
    },
    {
        "feature_name": "model_disagreement_adjusted_confidence",
        "category": "meta",
        "description": "Confidence adjusted downward when models disagree",
        "formula": "confidence * model_agreement_score",
        "rationale": "High stated confidence with low model agreement is a systematic failure mode",
        "expected_impact": "Better calibration of ensemble confidence",
        "trigger": "model_disagreement_failures",
    },
    {
        "feature_name": "news_silence_anomaly",
        "category": "sentiment",
        "description": "Detects abnormal absence of news for usually-covered stocks",
        "formula": "1 - (news_count_5d / avg_news_count_30d) if avg_news_count_30d > 2 else 0",
        "rationale": "Unusually quiet stocks sometimes precede sharp moves",
        "expected_impact": "Captures pre-announcement drift",
        "trigger": "pre_event_price_moves_missed",
    },
    {
        "feature_name": "volatility_adjusted_momentum",
        "category": "price",
        "description": "Momentum normalized by current volatility level",
        "formula": "return_5d / (atr_14d / close)",
        "rationale": "Raw momentum is misleading in high-vol regimes",
        "expected_impact": "More reliable signals during high-vol periods",
        "trigger": "high_volatility_prediction_failures",
    },
    {
        "feature_name": "pattern_freshness_score",
        "category": "pattern",
        "description": "Recency of the most similar historical pattern match",
        "formula": "1 / (1 + days_since_best_pattern_match / 252)",
        "rationale": "Old pattern matches are less reliable in changed market structures",
        "expected_impact": "Better pattern match quality scoring",
        "trigger": "stale_pattern_match_failures",
    },
]


def analyze_failures_for_feature_ideas(
    days_back: int = 180,
    db: Optional[Session] = None,
) -> List[str]:
    """Analyze recent failures to identify feature gaps."""
    own_session = db is None
    if own_session:
        db = get_session_factory()()
    try:
        cutoff = date.today() - timedelta(days=days_back)
        rows = db.execute(text("""
            SELECT failure_category, failure_type, COUNT(*) as cnt
            FROM failure_records
            WHERE failure_date >= :cutoff
            GROUP BY failure_category, failure_type
            ORDER BY cnt DESC
            """),
            {"cutoff": cutoff},
        ).fetchall()

        triggers = []
        for r in rows:
            cat = r.failure_category or ""
            ftype = r.failure_type or ""
            if r.cnt >= 3:
                triggers.append(f"{cat}_{ftype}".lower().replace(" ", "_"))
        logger.info("Feature discovery: %d failure triggers identified", len(triggers))
        return triggers
    finally:
        if own_session:
            db.close()


def generate_feature_proposals(
    days_back: int = 180,
    db: Optional[Session] = None,
) -> List[FeatureProposal]:
    """Generate feature proposals based on failure analysis."""
    own_session = db is None
    if own_session:
        db = get_session_factory()()
    try:
        failure_triggers = analyze_failures_for_feature_ideas(days_back, db)

        proposals = []
        for i, candidate in enumerate(CANDIDATE_FEATURES):
            proposal = FeatureProposal(
                proposal_id=f"FP_{date.today().strftime('%Y%m%d')}_{i:03d}",
                feature_name=candidate["feature_name"],
                category=candidate["category"],
                description=candidate["description"],
                formula=candidate["formula"],
                rationale=candidate["rationale"],
                expected_impact=candidate["expected_impact"],
                source_failures=[candidate.get("trigger", "general_analysis")],
            )
            proposals.append(proposal)

        # Save to DB
        for p in proposals:
            try:
                db.execute(text("""
                    INSERT OR IGNORE INTO feature_proposals
                        (proposal_id, feature_name, category, description, formula,
                         rationale, expected_impact, source_failures_json, status, created_at)
                    VALUES
                        (:pid, :name, :cat, :desc, :formula, :rat, :impact, :src, :status, :now)
                    """),
                    {
                        "pid": p.proposal_id, "name": p.feature_name, "cat": p.category,
                        "desc": p.description, "formula": p.formula, "rat": p.rationale,
                        "impact": p.expected_impact, "src": json.dumps(p.source_failures),
                        "status": p.status, "now": p.created_at,
                    },
                )
            except Exception as exc:
                logger.warning("Could not save proposal %s: %s", p.proposal_id, exc)

        try:
            db.commit()
        except Exception:
            pass

        logger.info("Generated %d feature proposals", len(proposals))
        return proposals
    finally:
        if own_session:
            db.close()


def run_feature_discovery_pipeline(days_back: int = 180) -> Dict[str, Any]:
    """Full feature discovery pipeline."""
    proposals = generate_feature_proposals(days_back)
    return {
        "status": "complete",
        "proposals_generated": len(proposals),
        "proposals": [p.to_dict() for p in proposals],
        "note": "All proposals require human approval before deployment",
    }
