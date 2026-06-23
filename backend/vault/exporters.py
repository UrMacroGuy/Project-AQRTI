"""
AQRTI Vault — File Exporters
Export archived vault records as JSON, CSV, or Markdown.
"""

from __future__ import annotations

import sys, os

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import csv
import json
from datetime import date, timedelta
from io import StringIO

from sqlalchemy.orm import Session

from aqrti.database.models import (
    MarketSnapshot, PredictionArchive, PortfolioArchive,
    ResearchBrief, ResearchArchive,
)


# ── JSON Exporter ─────────────────────────────────────────────
def export_snapshots_json(db: Session, start: date, end: date) -> str:
    rows = db.query(MarketSnapshot).filter(
        MarketSnapshot.snapshot_date.between(start, end)
    ).order_by(MarketSnapshot.snapshot_date.asc()).all()

    data = [
        {
            "date":       str(r.snapshot_date),
            "regime":     r.regime,
            "regime_conf":r.regime_conf,
            "nifty_close":r.nifty_close,
            "ret_1d":     r.nifty_return_1d,
            "sentiment":  r.market_sentiment,
            "ad_ratio":   r.advance_decline,
            "knowledge":  r.knowledge_score,
        }
        for r in rows
    ]
    return json.dumps({"export_range": f"{start}/{end}", "records": data}, indent=2)


def export_predictions_json(db: Session, start: date, end: date) -> str:
    rows = db.query(PredictionArchive).filter(
        PredictionArchive.prediction_date.between(start, end)
    ).order_by(PredictionArchive.prediction_date.asc(), PredictionArchive.symbol).all()

    data = [
        {
            "date":        str(r.prediction_date),
            "symbol":      r.symbol,
            "direction":   r.direction,
            "confidence":  r.direction_conf,
            "model":       r.model_name,
            "was_correct": r.was_correct,
            "actual_return": r.actual_return,
        }
        for r in rows
    ]
    return json.dumps({"export_range": f"{start}/{end}", "records": data}, indent=2)


# ── CSV Exporter ──────────────────────────────────────────────
def export_snapshots_csv(db: Session, start: date, end: date) -> str:
    rows = db.query(MarketSnapshot).filter(
        MarketSnapshot.snapshot_date.between(start, end)
    ).order_by(MarketSnapshot.snapshot_date.asc()).all()

    buf = StringIO()
    writer = csv.writer(buf)
    writer.writerow(["date", "regime", "regime_conf", "nifty_close",
                     "ret_1d", "ret_5d", "volatility", "sentiment",
                     "advance_decline", "knowledge_score"])
    for r in rows:
        writer.writerow([
            r.snapshot_date, r.regime, r.regime_conf, r.nifty_close,
            r.nifty_return_1d, r.nifty_return_5d, r.nifty_volatility,
            r.market_sentiment, r.advance_decline, r.knowledge_score,
        ])
    return buf.getvalue()


def export_predictions_csv(db: Session, start: date, end: date) -> str:
    rows = db.query(PredictionArchive).filter(
        PredictionArchive.prediction_date.between(start, end)
    ).order_by(PredictionArchive.prediction_date.asc(), PredictionArchive.symbol).all()

    buf = StringIO()
    writer = csv.writer(buf)
    writer.writerow(["date", "symbol", "direction", "confidence",
                     "magnitude", "model", "regime", "was_correct", "actual_return"])
    for r in rows:
        writer.writerow([
            r.prediction_date, r.symbol, r.direction, r.direction_conf,
            r.magnitude_pct, r.model_name, r.regime_at, r.was_correct, r.actual_return,
        ])
    return buf.getvalue()


def export_portfolio_csv(db: Session, start: date, end: date) -> str:
    rows = db.query(PortfolioArchive).filter(
        PortfolioArchive.archive_date.between(start, end)
    ).order_by(PortfolioArchive.archive_date.asc()).all()

    buf = StringIO()
    writer = csv.writer(buf)
    writer.writerow(["date", "total_value", "cash", "invested", "total_pnl",
                     "total_return_pct", "sharpe", "max_drawdown", "win_rate"])
    for r in rows:
        writer.writerow([
            r.archive_date, r.total_value, r.cash, r.invested, r.total_pnl,
            r.total_return_pct, r.sharpe, r.max_drawdown, r.win_rate,
        ])
    return buf.getvalue()


# ── Markdown Exporter ─────────────────────────────────────────
def export_brief_markdown(db: Session, brief_date: date) -> str:
    row = db.query(ResearchBrief).filter(ResearchBrief.brief_date == brief_date).first()
    if not row:
        return f"# No brief found for {brief_date}\n"

    def _load_list(v):
        if not v:
            return []
        try:
            parsed = json.loads(v)
            return parsed if isinstance(parsed, list) else [str(parsed)]
        except Exception:
            return [str(v)]

    lines = [
        f"# AQRTI Daily Research Brief — {brief_date}",
        f"**Regime:** {row.regime_at}  |  **Knowledge Score:** {row.knowledge_score:.1f}" if row.knowledge_score else f"**Regime:** {row.regime_at}",
        "",
        "## Market Summary",
        row.market_summary or "_No market summary._",
        "",
    ]

    for section, attr in [
        ("Top Opportunities", "top_opportunities"),
        ("Major Risks",       "major_risks"),
        ("Model Insights",    "model_insights"),
        ("Strategy Insights", "strategy_insights"),
        ("Research Findings", "research_findings"),
        ("Lessons Learned",   "lessons_learned"),
        ("Action Items",      "action_items"),
    ]:
        items = _load_list(getattr(row, attr, None))
        if items:
            lines.append(f"## {section}")
            for item in items:
                lines.append(f"- {item}")
            lines.append("")

    return "\n".join(lines)


def save_brief_markdown(db: Session, brief_date: date, output_dir: str) -> str:
    """Write brief markdown to file and return the path."""
    content = export_brief_markdown(db, brief_date)
    os.makedirs(output_dir, exist_ok=True)
    filepath = os.path.join(output_dir, f"daily_brief_{brief_date}.md")
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
    return filepath
