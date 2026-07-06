"""
Obsidian Vault Exporter — Phase 1 core.
Spec: docs/OBSIDIAN_INTEGRATION_PLAN.md

One-way, read-DB / write-markdown. The DB is the source of truth; every
note here is fully regenerable. Renders nothing for missing data (no
filler content, per the project's no-placeholder rule).

Public entry point: export_vault(full=False) -> dict of counts.
Scheduler/API wiring (OBS-2) calls this; it is not wired in here.
"""
from __future__ import annotations

import sys, os
from datetime import date, timedelta
from pathlib import Path

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import json

from aqrti.config.settings import get_settings
from aqrti.database.session import get_db_session
from aqrti.database.models import (
    ResearchBrief, KnowledgeScore, MarketRegime, Prediction,
    PaperTrade, LessonLearned, Stock, StrategyV2, StrategyPerformance,
    ResearchFinding,
)
from aqrti.data.global_universe import GLOBAL_UNIVERSE
from aqrti.utils.logger import get_logger
from obsidian.vault_writer import upsert_note
from obsidian.renderers import (
    render_daily_note, render_stock_note, render_lesson_note, render_home_note,
    render_algo_note, render_report_note,
    render_algos_index, render_lessons_index, render_stocks_index, render_daily_index,
    _slug,
)

log = get_logger("obsidian_exporter")


def _vault_root() -> Path | None:
    raw = (get_settings().obsidian_vault_path or "").strip()
    if not raw:
        return None
    return Path(raw)


def _lesson_note_name(lesson: LessonLearned) -> str:
    return f"L-{lesson.id:04d} {_slug(lesson.title)}"


_ALGO_STATUSES = ("promoted", "active", "retired")


def _export_daily(db, root: Path, brief_date: date, counts: dict) -> str | None:
    brief = (
        db.query(ResearchBrief)
        .filter(ResearchBrief.brief_date == brief_date)
        .first()
    )
    ks = (
        db.query(KnowledgeScore)
        .filter(KnowledgeScore.date == brief_date)
        .first()
    )
    regime_row = (
        db.query(MarketRegime)
        .filter(MarketRegime.date == brief_date)
        .first()
    )

    top_predictions = [
        {
            "symbol": p.symbol,
            "direction": p.direction,
            "confidence": p.confidence,
            "expected_return": p.expected_return,
        }
        for p in (
            db.query(Prediction)
            .filter(Prediction.date == brief_date)
            .order_by(Prediction.confidence.desc())
            .limit(5)
            .all()
        )
    ]

    opened = (
        db.query(PaperTrade)
        .filter(PaperTrade.entry_date == brief_date)
        .all()
    )
    closed = (
        db.query(PaperTrade)
        .filter(PaperTrade.exit_date == brief_date)
        .all()
    )
    lessons_today = (
        db.query(LessonLearned)
        .filter(LessonLearned.lesson_date == brief_date)
        .all()
    )

    if not (brief or ks or top_predictions or opened or closed or lessons_today):
        return None  # nothing happened this day — no stub note

    content = render_daily_note(
        brief_date=brief_date,
        brief=brief,
        knowledge_score=ks.overall_score if ks else None,
        regime=regime_row.regime if regime_row else (brief.regime_at if brief else None),
        top_predictions=top_predictions,
        trades_opened=[
            {"symbol": t.symbol, "shares": t.shares, "entry_price": t.entry_price, "strategy_id": t.strategy_id}
            for t in opened
        ],
        trades_closed=[
            {"symbol": t.symbol, "actual_return": t.actual_return, "exit_reason": t.exit_reason}
            for t in closed
        ],
        lessons_today=[f"Lessons/{_lesson_note_name(l)}" for l in lessons_today],
    )

    path = root / "Daily" / f"{brief_date.isoformat()}.md"
    result = upsert_note(path, content)
    counts[result] = counts.get(result, 0) + 1
    return f"Daily/{brief_date.isoformat()}"


def _touched_symbols(db, since: date) -> set[str]:
    symbols = set()
    for row in db.query(Prediction.symbol).filter(Prediction.date >= since).distinct():
        symbols.add(row[0])
    for row in db.query(PaperTrade.symbol).filter(PaperTrade.entry_date >= since).distinct():
        symbols.add(row[0])
    for row in db.query(LessonLearned.symbol).filter(LessonLearned.lesson_date >= since, LessonLearned.symbol.isnot(None)).distinct():
        symbols.add(row[0])
    return symbols


def _lookup_exchange_meta(symbol: str) -> dict | None:
    """
    Prediction/PaperTrade store bare tickers (e.g. "TCS"), but
    GLOBAL_UNIVERSE keys Indian names with their exchange suffix
    ("TCS.NS"/"TCS.BO") and only leaves US/ADR tickers bare. Try the
    bare symbol first (correct for US names and ADRs — e.g. "INFY" is
    genuinely a distinct NYSE-listed ADR entry, not the same row as
    "INFY.NS"), then fall back to the NSE/BSE suffixed variants.
    """
    for candidate in (symbol, f"{symbol}.NS", f"{symbol}.BO"):
        if candidate in GLOBAL_UNIVERSE:
            return GLOBAL_UNIVERSE[candidate]
    return None


def _export_stock(db, root: Path, symbol: str, counts: dict) -> None:
    stock = db.query(Stock).filter(Stock.symbol == symbol).first()
    exchange_meta = _lookup_exchange_meta(symbol)

    last_prediction = (
        db.query(Prediction)
        .filter(Prediction.symbol == symbol)
        .order_by(Prediction.date.desc())
        .first()
    )

    open_trade = (
        db.query(PaperTrade)
        .filter(PaperTrade.symbol == symbol, PaperTrade.is_open == True)  # noqa: E712
        .order_by(PaperTrade.entry_date.desc())
        .first()
    )
    open_position = (
        {"shares": open_trade.shares, "entry_price": open_trade.entry_price, "entry_date": open_trade.entry_date.isoformat()}
        if open_trade else None
    )

    all_closed = (
        db.query(PaperTrade)
        .filter(PaperTrade.symbol == symbol, PaperTrade.is_open == False)  # noqa: E712
        .order_by(PaperTrade.entry_date.desc())
        .all()
    )
    wins = [t for t in all_closed if (t.gross_pnl_pct or 0) > 0]
    losses = [t for t in all_closed if (t.gross_pnl_pct or 0) <= 0]
    trade_stats = {
        "closed": len(all_closed),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": (len(wins) / len(all_closed) * 100) if all_closed else 0.0,
        "avg_return_pct": (
            sum(t.gross_pnl_pct for t in all_closed if t.gross_pnl_pct is not None) / len(all_closed)
        ) if all_closed else 0.0,
        "total_pnl": sum(t.gross_pnl for t in all_closed if t.gross_pnl is not None),
    }

    recent_trades = [
        {
            "entry_date": t.entry_date.isoformat() if t.entry_date else None,
            "exit_date": t.exit_date.isoformat() if t.exit_date else None,
            "return_pct": t.gross_pnl_pct,
            "exit_reason": t.exit_reason,
        }
        for t in all_closed[:10]
    ]

    content = render_stock_note(
        symbol=symbol,
        stock=stock,
        exchange_meta=exchange_meta,
        last_prediction=last_prediction,
        sentiment_score=last_prediction.sentiment_score if last_prediction else None,
        open_position=open_position,
        recent_trades=recent_trades,
        trade_stats=trade_stats,
    )

    path = root / "Stocks" / f"{symbol}.md"
    result = upsert_note(path, content)
    counts[result] = counts.get(result, 0) + 1


def _export_lessons(db, root: Path, since: date, counts: dict) -> None:
    lessons = (
        db.query(LessonLearned)
        .filter(LessonLearned.lesson_date >= since)
        .all()
    )
    for lesson in lessons:
        content = render_lesson_note(lesson)
        path = root / "Lessons" / f"{_lesson_note_name(lesson)}.md"
        result = upsert_note(path, content)
        counts[result] = counts.get(result, 0) + 1


def _export_algos(db, root: Path, counts: dict) -> list[str]:
    """Promoted/active/retired algos only — a note per all candidates would be graph noise."""
    algos = (
        db.query(StrategyV2)
        .filter(StrategyV2.status.in_(_ALGO_STATUSES))
        .all()
    )
    promoted_links = []
    for strategy in algos:
        try:
            dsl = json.loads(strategy.dsl_json) if strategy.dsl_json else None
        except Exception:
            dsl = None

        shadow_trades = [
            {
                "date": row.date.isoformat(),
                "trades_opened": row.trades_opened,
                "trades_closed": row.trades_closed,
                "daily_pnl": row.daily_pnl,
            }
            for row in (
                db.query(StrategyPerformance)
                .filter(StrategyPerformance.strategy_id == strategy.strategy_id)
                .order_by(StrategyPerformance.date.desc())
                .limit(20)
                .all()
            )
        ]

        content = render_algo_note(strategy, dsl, shadow_trades)
        path = root / "Algos" / f"{strategy.strategy_id}.md"
        result = upsert_note(path, content)
        counts[result] = counts.get(result, 0) + 1

        if strategy.status in ("promoted", "active"):
            promoted_links.append(f"Algos/{strategy.strategy_id}")

    return promoted_links


def _export_reports(db, root: Path, since: date, counts: dict) -> None:
    """One note per (agent_id, finding_date) — groups that agent's findings for the day."""
    findings = (
        db.query(ResearchFinding)
        .filter(ResearchFinding.finding_date >= since)
        .order_by(ResearchFinding.finding_date, ResearchFinding.agent_id)
        .all()
    )
    grouped: dict[tuple, list] = {}
    for f in findings:
        grouped.setdefault((f.agent_id, f.finding_date), []).append(f)

    for (agent_id, finding_date), items in grouped.items():
        content = render_report_note(agent_id, finding_date, items)
        path = root / "Reports" / f"{finding_date.isoformat()} {_slug(agent_id)}.md"
        result = upsert_note(path, content)
        counts[result] = counts.get(result, 0) + 1


def _export_indexes(root: Path, counts: dict) -> None:
    """
    One Dataview-powered index note per folder — pure organization, no new
    DB reads. Filename underscore-prefixed so it sorts to the top of its
    folder in the file explorer, ahead of the dated/symbol-named notes.
    """
    for folder, content in (
        ("Daily",   render_daily_index()),
        ("Stocks",  render_stocks_index()),
        ("Lessons", render_lessons_index()),
        ("Algos",   render_algos_index()),
    ):
        path = root / folder / "_index.md"
        result = upsert_note(path, content)
        counts[result] = counts.get(result, 0) + 1


def _export_home(db, root: Path, counts: dict, promoted_algos: list) -> None:
    latest_brief = (
        db.query(ResearchBrief)
        .order_by(ResearchBrief.brief_date.desc())
        .first()
    )
    latest_daily_date = latest_brief.brief_date if latest_brief else None

    trend = [
        (ks.date, ks.overall_score)
        for ks in (
            db.query(KnowledgeScore)
            .order_by(KnowledgeScore.date.desc())
            .limit(7)
            .all()
        )
    ][::-1]

    recent_lessons = [
        f"Lessons/{_lesson_note_name(l)}"
        for l in (
            db.query(LessonLearned)
            .order_by(LessonLearned.lesson_date.desc())
            .limit(5)
            .all()
        )
    ]

    content = render_home_note(
        latest_daily_date=latest_daily_date,
        knowledge_score_trend=trend,
        recent_lessons=recent_lessons,
        promoted_algos=promoted_algos,
    )
    path = root / "Home.md"
    result = upsert_note(path, content)
    counts[result] = counts.get(result, 0) + 1


def export_vault(full: bool = False) -> dict:
    """
    Render the Obsidian vault from current DB state.
    full=False (default): today + anything touched in the last 7 days.
    full=True: backfill from all history (first-run / manual full export).
    Returns a counts dict: {"written": n, "unchanged": n, "skipped_collision": n, "days_exported": n}.
    """
    root = _vault_root()
    if root is None:
        log.info("obsidian_vault_path unset — export skipped")
        return {"skipped": "vault_path_unset"}

    counts: dict = {}
    since = date(2000, 1, 1) if full else (date.today() - timedelta(days=7))

    try:
        with get_db_session() as db:
            brief_dates = sorted({
                d for (d,) in db.query(ResearchBrief.brief_date).filter(ResearchBrief.brief_date >= since).all()
            })
            days_exported = 0
            for d in brief_dates:
                if _export_daily(db, root, d, counts):
                    days_exported += 1

            for symbol in _touched_symbols(db, since):
                _export_stock(db, root, symbol, counts)

            _export_lessons(db, root, since, counts)
            promoted_algos = _export_algos(db, root, counts)
            _export_reports(db, root, since, counts)
            _export_indexes(root, counts)
            _export_home(db, root, counts, promoted_algos)

            counts["days_exported"] = days_exported
    except Exception:
        log.exception("Obsidian export failed — pipeline continues unaffected")
        return {"error": "export_failed"}

    log.info("Obsidian export complete: %s", counts)
    return counts


if __name__ == "__main__":
    import json as _json
    print(_json.dumps(export_vault(full="--full" in sys.argv), indent=2, default=str))
