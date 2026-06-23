"""
AQRTI Meta Learning Engine — Phase 8.5F
Learns about AQRTI's own learning process:
  - When is AQRTI likely wrong?
  - When is AQRTI overconfident?
  - Which predictions deserve less trust?
  - Which conditions create failures?
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from aqrti.database.engine import get_session_factory
from aqrti.utils.logger import get_logger

logger = get_logger("meta_learning_engine")


@dataclass
class MetaInsight:
    """A single meta-learning insight about AQRTI's prediction behavior."""
    insight_type: str
    title: str
    description: str
    condition: str
    evidence: Dict[str, Any]
    failure_rate: float
    sample_count: int
    severity: str  # low|medium|high|critical
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "insight_type": self.insight_type,
            "title": self.title,
            "description": self.description,
            "condition": self.condition,
            "evidence": self.evidence,
            "failure_rate": self.failure_rate,
            "sample_count": self.sample_count,
            "severity": self.severity,
            "created_at": self.created_at,
        }


def _load_prediction_outcomes(days_back: int, db: Session) -> pd.DataFrame:
    """Load predictions with actual outcomes for meta-analysis."""
    cutoff = date.today() - timedelta(days=days_back)
    rows = db.execute(
        """
        SELECT p.date, p.symbol, p.direction, p.confidence, p.expected_return,
               p.actual_return, p.success, p.regime,
               ch.model_agreement, ch.historical_accuracy, ch.regime_confidence,
               ch.signal_strength, ch.feature_completeness, ch.confidence_category
        FROM predictions p
        LEFT JOIN confidence_history ch ON ch.symbol = p.symbol AND ch.prediction_date = p.date
        WHERE p.date >= :cutoff AND p.actual_return IS NOT NULL
        """,
        {"cutoff": cutoff},
    ).fetchall()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame([dict(r._mapping) for r in rows])
    df["was_correct"] = df["success"].fillna(False).astype(bool)
    return df


def analyze_overconfidence(df: pd.DataFrame) -> List[MetaInsight]:
    """Detect conditions where AQRTI is systematically overconfident."""
    insights = []
    if df.empty or "confidence" not in df.columns:
        return insights

    # High confidence + wrong
    high_conf = df[df["confidence"] >= 75]
    if len(high_conf) >= 10:
        failure_rate = float(1 - high_conf["was_correct"].mean())
        if failure_rate > 0.40:
            insights.append(MetaInsight(
                insight_type="overconfidence",
                title="High Confidence Failure Pattern",
                description=f"When confidence >= 75, AQRTI fails {failure_rate*100:.1f}% of the time",
                condition="confidence >= 75",
                evidence={
                    "threshold": 75,
                    "failure_rate": failure_rate,
                    "sample_count": len(high_conf),
                    "success_rate": float(high_conf["was_correct"].mean()),
                },
                failure_rate=failure_rate,
                sample_count=len(high_conf),
                severity="high" if failure_rate > 0.50 else "medium",
            ))

    # By regime
    for regime in df["regime"].dropna().unique():
        regime_df = df[df["regime"] == regime]
        if len(regime_df) < 10:
            continue
        avg_conf = float(regime_df["confidence"].mean())
        success = float(regime_df["was_correct"].mean())
        if avg_conf > 70 and success < 0.50:
            insights.append(MetaInsight(
                insight_type="regime_overconfidence",
                title=f"Overconfident in {regime} Regime",
                description=f"Avg confidence {avg_conf:.1f} but only {success*100:.1f}% accurate in {regime}",
                condition=f"regime == '{regime}'",
                evidence={"regime": regime, "avg_confidence": avg_conf, "accuracy": success},
                failure_rate=1 - success,
                sample_count=len(regime_df),
                severity="high" if success < 0.40 else "medium",
            ))

    return insights


def analyze_systematic_failures(df: pd.DataFrame) -> List[MetaInsight]:
    """Identify conditions that systematically produce failures."""
    insights = []
    if df.empty:
        return insights

    # Low model agreement + wrong
    if "model_agreement" in df.columns:
        low_agree = df[df["model_agreement"].notna() & (df["model_agreement"] < 0.5)]
        if len(low_agree) >= 10:
            failure_rate = float(1 - low_agree["was_correct"].mean())
            if failure_rate > 0.55:
                insights.append(MetaInsight(
                    insight_type="model_disagreement",
                    title="Model Disagreement → High Failure Rate",
                    description=f"When models disagree (agreement < 0.5), {failure_rate*100:.1f}% fail",
                    condition="model_agreement < 0.5",
                    evidence={"threshold": 0.5, "failure_rate": failure_rate},
                    failure_rate=failure_rate,
                    sample_count=len(low_agree),
                    severity="high",
                ))

    # Low feature completeness
    if "feature_completeness" in df.columns:
        low_feat = df[df["feature_completeness"].notna() & (df["feature_completeness"] < 0.7)]
        if len(low_feat) >= 10:
            failure_rate = float(1 - low_feat["was_correct"].mean())
            if failure_rate > 0.50:
                insights.append(MetaInsight(
                    insight_type="incomplete_features",
                    title="Incomplete Feature Data → Unreliable Predictions",
                    description=f"Feature completeness < 70% → {failure_rate*100:.1f}% failure rate",
                    condition="feature_completeness < 0.7",
                    evidence={"failure_rate": failure_rate},
                    failure_rate=failure_rate,
                    sample_count=len(low_feat),
                    severity="medium",
                ))

    # By direction bias
    for direction in ["Bullish", "Bearish"]:
        dir_df = df[df["direction"] == direction]
        if len(dir_df) >= 15:
            failure_rate = float(1 - dir_df["was_correct"].mean())
            if failure_rate > 0.55:
                insights.append(MetaInsight(
                    insight_type="directional_bias",
                    title=f"Systematic Failure in {direction} Predictions",
                    description=f"{direction} predictions fail {failure_rate*100:.1f}% of the time",
                    condition=f"direction == '{direction}'",
                    evidence={"direction": direction, "failure_rate": failure_rate},
                    failure_rate=failure_rate,
                    sample_count=len(dir_df),
                    severity="high" if failure_rate > 0.60 else "medium",
                ))

    return insights


def analyze_trust_conditions(df: pd.DataFrame) -> List[MetaInsight]:
    """Identify which conditions produce the most reliable predictions."""
    insights = []
    if df.empty:
        return insights

    # High-trust: high model_agreement + high historical_accuracy
    if "model_agreement" in df.columns and "historical_accuracy" in df.columns:
        high_trust = df[
            (df["model_agreement"].notna()) &
            (df["model_agreement"] >= 0.8) &
            (df["historical_accuracy"].notna()) &
            (df["historical_accuracy"] >= 0.65)
        ]
        if len(high_trust) >= 10:
            success_rate = float(high_trust["was_correct"].mean())
            insights.append(MetaInsight(
                insight_type="high_trust_condition",
                title="Optimal Prediction Conditions Identified",
                description=f"model_agreement >= 0.8 AND hist_accuracy >= 0.65 → {success_rate*100:.1f}% accuracy",
                condition="model_agreement >= 0.8 AND historical_accuracy >= 0.65",
                evidence={"success_rate": success_rate, "samples": len(high_trust)},
                failure_rate=1 - success_rate,
                sample_count=len(high_trust),
                severity="low",
            ))

    return insights


def run_meta_learning_analysis(days_back: int = 365, db=None) -> Dict[str, Any]:
    """Full meta-learning analysis pipeline."""
    own_session = db is None
    if own_session:
        db = get_session_factory()()
    try:
        df = _load_prediction_outcomes(days_back, db)

        if df.empty:
            return {
                "status": "no_data",
                "insights": [],
                "summary": {"total_predictions": 0},
            }

        all_insights: List[MetaInsight] = []
        all_insights.extend(analyze_overconfidence(df))
        all_insights.extend(analyze_systematic_failures(df))
        all_insights.extend(analyze_trust_conditions(df))

        # Save insights to DB
        for ins in all_insights:
            try:
                db.execute(
                    """
                    INSERT INTO meta_learning_records
                        (insight_type, title, description, condition_text,
                         evidence_json, failure_rate, sample_count, severity, created_at)
                    VALUES
                        (:type, :title, :desc, :cond, :ev, :fr, :cnt, :sev, :now)
                    """,
                    {
                        "type": ins.insight_type, "title": ins.title,
                        "desc": ins.description, "cond": ins.condition,
                        "ev": json.dumps(ins.evidence), "fr": ins.failure_rate,
                        "cnt": ins.sample_count, "sev": ins.severity,
                        "now": datetime.utcnow().isoformat(),
                    },
                )
            except Exception as exc:
                logger.warning("Could not save meta-learning insight: %s", exc)

        try:
            db.commit()
        except Exception:
            pass

        logger.info("Meta-learning analysis: %d insights from %d predictions",
                    len(all_insights), len(df))

        return {
            "status": "complete",
            "insights": [i.to_dict() for i in all_insights],
            "summary": {
                "total_predictions": len(df),
                "overall_accuracy": float(df["was_correct"].mean()),
                "insights_generated": len(all_insights),
                "high_severity": sum(1 for i in all_insights if i.severity in ("high", "critical")),
            },
        }
    finally:
        if own_session:
            db.close()
