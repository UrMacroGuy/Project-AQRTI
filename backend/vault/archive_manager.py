"""
AQRTI Vault — Archive Manager
Archives predictions, portfolio, strategies, knowledge, and research records daily.
All records are immutable — never overwritten.
"""

from __future__ import annotations

import sys, os

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import json
from datetime import date

from sqlalchemy.orm import Session

from aqrti.database.models import (
    PredictionArchive, PortfolioArchive, StrategyArchive,
    KnowledgeArchive, ResearchArchive,
    Prediction, PaperPortfolio, PaperTrade, StrategyV2,
    KnowledgeScore, ModelDriftHistory, FeatureImportanceHistory,
    LessonLearned, FailureRecord,
    ResearchBrief, ResearchFinding, StrategyResearchReport,
)


# ── Predictions ───────────────────────────────────────────────
def archive_predictions(db: Session, target_date: date) -> dict:
    already = db.query(PredictionArchive).filter(
        PredictionArchive.prediction_date == target_date
    ).count()
    if already:
        return {"status": "already_exists", "date": str(target_date), "count": already}

    preds = db.query(Prediction).filter(Prediction.date == target_date).all()
    for p in preds:
        row = PredictionArchive(
            prediction_date  = target_date,
            symbol           = p.symbol,
            model_name       = p.model_version,
            direction        = p.direction,
            direction_conf   = p.confidence,
            magnitude_pct    = p.expected_return,
            horizon_days     = None,
            regime_at        = p.regime,
            archive_run_id   = str(target_date),
        )
        db.add(row)

    return {"status": "archived", "date": str(target_date), "count": len(preds)}


# ── Portfolio ─────────────────────────────────────────────────
def archive_portfolio(db: Session, target_date: date) -> dict:
    existing = db.query(PortfolioArchive).filter(
        PortfolioArchive.archive_date == target_date
    ).first()
    if existing:
        return {"status": "already_exists", "date": str(target_date)}

    port = db.query(PaperPortfolio).order_by(PaperPortfolio.created_at.desc()).first()
    trades_today = db.query(PaperTrade).filter(
        PaperTrade.entry_date == target_date
    ).all()

    if not port:
        return {"status": "no_portfolio", "date": str(target_date)}

    invested = port.total_value - port.current_cash if port.total_value and port.current_cash else None
    total_pnl = port.total_value - port.initial_capital if port.total_value and port.initial_capital else None

    row = PortfolioArchive(
        archive_date     = target_date,
        total_value      = port.total_value,
        cash             = port.current_cash,
        invested         = invested,
        total_pnl        = total_pnl,
        total_return_pct = port.total_return_pct,
        sharpe           = None,
        max_drawdown     = port.max_drawdown_pct,
        win_rate         = None,
        positions_json   = None,
        trades_json      = json.dumps([_trade_to_dict(t) for t in trades_today]),
        regime_at        = None,
    )
    db.add(row)
    return {"status": "archived", "date": str(target_date), "trades": len(trades_today)}


# ── Strategies ────────────────────────────────────────────────
def archive_strategies(db: Session, target_date: date) -> dict:
    already = db.query(StrategyArchive).filter(
        StrategyArchive.archive_date == target_date
    ).count()
    if already:
        return {"status": "already_exists", "date": str(target_date), "count": already}

    strategies = db.query(StrategyV2).filter(
        StrategyV2.status.in_(["active", "promoted", "testing"])
    ).all()

    for s in strategies:
        row = StrategyArchive(
            strategy_id       = s.strategy_id,
            archive_date      = target_date,
            name              = s.name,
            family            = s.family,
            generation        = s.generation,
            fitness_score     = s.fitness_score,
            status_at_archive = s.status,
            parent_ids        = s.parent_ids,
            dsl_json          = s.dsl_json,
            backtest_json     = s.backtest_json,
            regime_fit_json   = s.regime_fit_json,
        )
        db.add(row)

    return {"status": "archived", "date": str(target_date), "count": len(strategies)}


# ── Knowledge ─────────────────────────────────────────────────
def archive_knowledge(db: Session, target_date: date) -> dict:
    existing = db.query(KnowledgeArchive).filter(
        KnowledgeArchive.archive_date == target_date
    ).first()
    if existing:
        return {"status": "already_exists", "date": str(target_date)}

    ks = db.query(KnowledgeScore).filter(
        KnowledgeScore.date == target_date
    ).first()

    lessons = db.query(LessonLearned).filter(LessonLearned.lesson_date == target_date).all()
    failures = db.query(FailureRecord).filter(
        FailureRecord.failure_date == target_date
    ).all()

    drift_rows = db.query(ModelDriftHistory).filter(
        ModelDriftHistory.measured_date == target_date
    ).all()
    drift_summary = {r.model_name: r.drift_pct for r in drift_rows if r.model_name}

    fi_rows = (
        db.query(FeatureImportanceHistory)
        .filter(FeatureImportanceHistory.measured_date <= target_date)
        .order_by(FeatureImportanceHistory.measured_date.desc(), FeatureImportanceHistory.rank.asc())
        .limit(20)
        .all()
    )
    feature_rankings = [{"feature": r.feature_name, "importance": r.importance, "rank": r.rank} for r in fi_rows]

    row = KnowledgeArchive(
        archive_date     = target_date,
        knowledge_score  = float(ks.overall_score) if ks and ks.overall_score else None,
        lessons_count    = len(lessons),
        failures_count   = len(failures),
        lessons_json     = json.dumps([_lesson_to_dict(l) for l in lessons[:20]]),
        drift_summary    = json.dumps(drift_summary),
        feature_rankings = json.dumps(feature_rankings),
    )
    db.add(row)
    return {
        "status":    "archived",
        "date":      str(target_date),
        "lessons":   len(lessons),
        "failures":  len(failures),
        "score":     float(ks.overall_score) if ks and ks.overall_score else None,
    }


# ── Research ──────────────────────────────────────────────────
def archive_research(db: Session, target_date: date) -> dict:
    already = db.query(ResearchArchive).filter(
        ResearchArchive.archive_date == target_date
    ).count()
    if already:
        return {"status": "already_exists", "date": str(target_date), "count": already}

    count = 0

    # Daily brief
    brief = db.query(ResearchBrief).filter(ResearchBrief.brief_date == target_date).first()
    if brief:
        db.add(ResearchArchive(
            archive_date  = target_date,
            archive_type  = "brief",
            title         = brief.title,
            summary       = brief.market_summary,
            full_content  = json.dumps(_brief_to_dict(brief)),
            regime_at     = brief.regime_at,
            source_id     = brief.id,
        ))
        count += 1

    # Research findings
    findings = db.query(ResearchFinding).filter(
        ResearchFinding.finding_date == target_date
    ).all()
    for f in findings:
        db.add(ResearchArchive(
            archive_date  = target_date,
            archive_type  = "finding",
            agent_id      = f.agent_id,
            title         = f.title,
            summary       = f.implication,
            full_content  = json.dumps({
                "description": f.description,
                "evidence": f.evidence,
                "category": f.category,
                "urgency": f.urgency,
            }),
            urgency       = f.urgency,
            regime_at     = f.regime,
            source_id     = f.id,
        ))
        count += 1

    # Strategy research reports
    from aqrti.database.models import StrategyResearchReport
    srr = db.query(StrategyResearchReport).filter(
        StrategyResearchReport.report_date == target_date
    ).all()
    for r in srr:
        db.add(ResearchArchive(
            archive_date  = target_date,
            archive_type  = "strategy_report",
            title         = r.title,
            summary       = r.summary,
            full_content  = r.findings_json,
            source_id     = r.id,
        ))
        count += 1

    return {"status": "archived", "date": str(target_date), "count": count}


# ── Helpers ───────────────────────────────────────────────────
def _trade_to_dict(t) -> dict:
    return {
        "symbol":      t.symbol,
        "entry_date":  str(t.entry_date) if t.entry_date else None,
        "exit_date":   str(t.exit_date)  if t.exit_date  else None,
        "shares":      t.shares,
        "entry_price": t.entry_price,
        "exit_price":  t.exit_price,
        "gross_pnl":   t.gross_pnl,
        "direction":   t.direction,
        "exit_reason": t.exit_reason,
    }


def _lesson_to_dict(l) -> dict:
    return {
        "title":          l.title,
        "description":    l.description,
        "category":       l.category,
        "severity":       l.severity,
        "recommendation": l.recommendation,
    }


def _brief_to_dict(b) -> dict:
    def _load(v):
        if not v:
            return []
        try:
            import json
            return json.loads(v)
        except Exception:
            return [v]

    return {
        "brief_date":        str(b.brief_date),
        "regime_at":         b.regime_at,
        "knowledge_score":   b.knowledge_score,
        "market_summary":    b.market_summary,
        "top_opportunities": _load(b.top_opportunities),
        "major_risks":       _load(b.major_risks),
        "action_items":      _load(b.action_items),
    }
