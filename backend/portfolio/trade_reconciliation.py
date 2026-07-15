"""
Trade Reconciliation — algo-suggested vs human-executed

Tracks two things CLAUDE.md's Personal Portfolio section asks for:

1. Market slippage: the algo's suggested entry price (PaperPosition, a live
   "algo suggested this" record — simulated, not real money) vs the actual
   fill price the user recorded in PortfolioTransaction (real money,
   append-only tax audit trail) when/if they acted on it.
2. Human override drag: suggestions the user never acted on within a
   reasonable window ("skipped"), and — for matched trades — how many days
   passed between suggestion and fill ("hesitation").

This module writes to TradeReconciliation, a bridge/reporting table that
references both PaperPosition and PortfolioTransaction by ID only. It never
joins or merges the two source tables' semantics, and never mutates
PortfolioTransaction (append-only) or PaperPosition (owned by the paper
engine). Every suggestion this produces is reporting, not advice — the user
decides what to trade.

No fabrication: a row is only created/linked when a real PaperPosition and/or
PortfolioTransaction genuinely exist and align within the match window. If
PortfolioTransaction is empty (no real trades recorded yet), nothing is
matched and existing 'suggested_only' rows simply age into 'skipped'.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from aqrti.database.models import (
    PaperPosition,
    PortfolioTransaction,
    TradeReconciliation,
    DailyPrice,
)
from aqrti.utils.logger import get_logger

log = get_logger("trade_reconciliation")

# Real executions lag the algo's signal — the user checks the app, decides,
# places the order days later. ±10 trading days is roughly 2 calendar weeks,
# generous enough to catch genuine delayed action without matching an
# unrelated later suggestion on the same symbol.
MATCH_WINDOW_DAYS = 14

# If this many days pass with no matching real transaction, the suggestion
# is presumed skipped rather than left open indefinitely.
SKIP_AFTER_DAYS = 21


def _get_latest_close(db: Session, symbol: str, on_or_before: date) -> Optional[float]:
    row = (
        db.query(DailyPrice.close)
        .filter(DailyPrice.symbol == symbol, DailyPrice.date <= on_or_before)
        .order_by(DailyPrice.date.desc())
        .first()
    )
    return row[0] if row else None


def ensure_suggestion_rows(db: Session) -> int:
    """
    Create a 'suggested_only' TradeReconciliation row for every PaperPosition
    that doesn't already have one. Idempotent — safe to call repeatedly
    (e.g. from a scheduled job) as new suggestions appear.

    Returns the number of rows created.
    """
    existing_suggestion_ids = {
        r[0] for r in db.query(TradeReconciliation.algo_suggestion_id)
        .filter(TradeReconciliation.algo_suggestion_id.isnot(None))
        .all()
    }

    positions = db.query(PaperPosition).all()
    created = 0
    for pos in positions:
        if pos.id in existing_suggestion_ids:
            continue
        db.add(TradeReconciliation(
            symbol=pos.symbol,
            algo_suggestion_id=pos.id,
            algo_suggested_price=pos.entry_price,
            algo_suggested_date=pos.entry_date,
            strategy_id=pos.strategy_id,
            strategy_name=pos.strategy_name,
            status="suggested_only",
        ))
        created += 1

    if created:
        db.commit()
    return created


def _find_unmatched_suggestion(
    db: Session, symbol: str, transaction_date: date,
) -> Optional[TradeReconciliation]:
    """
    Find the closest unmatched suggestion for this symbol within
    MATCH_WINDOW_DAYS of the real transaction date. Only 'suggested_only' or
    'skipped' rows are eligible — a 'matched' row stays matched to its
    original transaction (PortfolioTransaction is append-only; corrections
    are new reversal rows, not edits to this link).
    """
    window_start = transaction_date - timedelta(days=MATCH_WINDOW_DAYS)
    window_end = transaction_date + timedelta(days=MATCH_WINDOW_DAYS)

    candidates = (
        db.query(TradeReconciliation)
        .filter(
            TradeReconciliation.symbol == symbol,
            TradeReconciliation.status.in_(["suggested_only", "skipped"]),
            TradeReconciliation.algo_suggested_date >= window_start,
            TradeReconciliation.algo_suggested_date <= window_end,
        )
        .all()
    )
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda r: abs((r.algo_suggested_date - transaction_date).days),
    )


def match_transaction(db: Session, transaction: PortfolioTransaction) -> Optional[TradeReconciliation]:
    """
    Given a real PortfolioTransaction (buy), search for an unmatched
    PaperPosition suggestion on the same symbol within the match window and
    link them — computing slippage_pct, days_to_fill, and outcome_if_taken.

    Returns the updated TradeReconciliation row, or None if no plausible
    suggestion exists to link (never fabricates a match).
    """
    if transaction.transaction_type != "buy":
        return None

    match = _find_unmatched_suggestion(db, transaction.ticker, transaction.transaction_date)
    if match is None:
        return None

    match.human_transaction_id = transaction.id
    match.human_fill_price = transaction.price
    match.human_fill_date = transaction.transaction_date
    match.days_to_fill = (transaction.transaction_date - match.algo_suggested_date).days

    if match.algo_suggested_price:
        match.slippage_pct = round(
            (transaction.price - match.algo_suggested_price) / match.algo_suggested_price * 100.0, 4,
        )

    latest_close = _get_latest_close(db, transaction.ticker, date.today())
    if latest_close and match.algo_suggested_price:
        match.outcome_if_taken = round(
            (latest_close - match.algo_suggested_price) / match.algo_suggested_price * 100.0, 4,
        )

    match.status = "matched"
    db.commit()
    log.info(
        "Reconciled %s: algo suggested %.2f on %s, human filled %.2f on %s (slippage %.3f%%)",
        transaction.ticker, match.algo_suggested_price, match.algo_suggested_date,
        transaction.price, transaction.transaction_date, match.slippage_pct or 0.0,
    )
    return match


def mark_stale_as_skipped(db: Session) -> int:
    """
    Age 'suggested_only' rows older than SKIP_AFTER_DAYS with no matching
    transaction into 'skipped' — a presumed-not-taken suggestion, the raw
    input for "human override drag" reporting.
    """
    cutoff = date.today() - timedelta(days=SKIP_AFTER_DAYS)
    stale = (
        db.query(TradeReconciliation)
        .filter(
            TradeReconciliation.status == "suggested_only",
            TradeReconciliation.algo_suggested_date < cutoff,
        )
        .all()
    )
    for row in stale:
        row.status = "skipped"
        if row.outcome_if_taken is None:
            latest_close = _get_latest_close(db, row.symbol, date.today())
            if latest_close and row.algo_suggested_price:
                row.outcome_if_taken = round(
                    (latest_close - row.algo_suggested_price) / row.algo_suggested_price * 100.0, 4,
                )
    if stale:
        db.commit()
    return len(stale)


def backfill_from_existing_transactions(db: Session) -> int:
    """
    One-time best-effort pass: for every existing PortfolioTransaction not
    already linked, try to match it against an unmatched suggestion. Only
    creates a link when a genuine symbol+date-window match exists — does
    not fabricate matches for transactions with no plausible suggestion.
    """
    already_linked_txn_ids = {
        r[0] for r in db.query(TradeReconciliation.human_transaction_id)
        .filter(TradeReconciliation.human_transaction_id.isnot(None))
        .all()
    }
    txns = (
        db.query(PortfolioTransaction)
        .filter(PortfolioTransaction.transaction_type == "buy")
        .order_by(PortfolioTransaction.transaction_date.asc())
        .all()
    )
    matched = 0
    for txn in txns:
        if txn.id in already_linked_txn_ids:
            continue
        if match_transaction(db, txn) is not None:
            matched += 1
    return matched


def get_reconciliation_report(db: Session) -> dict:
    """
    Run the housekeeping passes (new suggestions, staleness, backfill) then
    return the full reconciliation list plus summary stats. Read-only from
    the caller's perspective in the sense that it never touches
    PortfolioTransaction or PaperPosition — only TradeReconciliation rows.
    """
    ensure_suggestion_rows(db)
    backfill_from_existing_transactions(db)
    mark_stale_as_skipped(db)

    rows = db.query(TradeReconciliation).order_by(TradeReconciliation.algo_suggested_date.desc()).all()

    items = [{
        "id": r.id,
        "symbol": r.symbol,
        "algoSuggestedPrice": r.algo_suggested_price,
        "algoSuggestedDate": str(r.algo_suggested_date),
        "strategyId": r.strategy_id,
        "strategyName": r.strategy_name,
        "humanTransactionId": r.human_transaction_id,
        "humanFillPrice": r.human_fill_price,
        "humanFillDate": str(r.human_fill_date) if r.human_fill_date else None,
        "slippagePct": r.slippage_pct,
        "daysToFill": r.days_to_fill,
        "outcomeIfTaken": r.outcome_if_taken,
        "status": r.status,
    } for r in rows]

    matched_rows = [r for r in rows if r.status == "matched"]
    skipped_rows = [r for r in rows if r.status == "skipped"]

    slippages = [r.slippage_pct for r in matched_rows if r.slippage_pct is not None]
    days_to_fill = [r.days_to_fill for r in matched_rows if r.days_to_fill is not None]
    skipped_outcomes = [r.outcome_if_taken for r in skipped_rows if r.outcome_if_taken is not None]

    summary = {
        "totalSuggestions": len(rows),
        "matchedCount": len(matched_rows),
        "skippedCount": len(skipped_rows),
        "suggestedOnlyCount": len(rows) - len(matched_rows) - len(skipped_rows),
        "avgSlippagePct": round(sum(slippages) / len(slippages), 4) if slippages else None,
        "avgDaysToFill": round(sum(days_to_fill) / len(days_to_fill), 2) if days_to_fill else None,
        "avgSkippedOutcomePct": round(sum(skipped_outcomes) / len(skipped_outcomes), 4) if skipped_outcomes else None,
        "note": (
            "No reconciliation data yet — no real transactions recorded in PortfolioTransaction "
            "to match against algo suggestions."
            if len(rows) == 0 or (len(matched_rows) == 0 and len(skipped_rows) == 0)
            else None
        ),
    }

    return {"items": items, "summary": summary}
