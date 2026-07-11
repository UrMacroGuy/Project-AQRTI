"""
Paper-vs-Real Reconciliation
Compares real portfolio fills (PortfolioTransaction, manually recorded by
the user per CLAUDE.md's "tracker only, never execute" rule) against what
the paper-trading engine assumed for the same symbol/date — slippage,
timing, and the 0.28% NSE cost model.

A persistent paper-beats-real gap is a red flag on the underlying strategy:
it means the honest backtest/paper numbers don't survive contact with real
execution, and should be surfaced, never hidden (CLAUDE.md rule 1).

This module does nothing until real trades exist — PortfolioTransaction is
empty until the user records their first manual trade. Every function here
degrades to an explicit "no real trades yet" result rather than fabricating
a comparison.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from aqrti.database.models import PortfolioTransaction, PaperTrade
from aqrti.utils.logger import get_logger

log = get_logger("paper_real_reconciliation")

# A real fill is matched to a paper trade on the same symbol if the paper
# trade's entry/exit date falls within this many days of the real
# transaction date — real executions don't happen at the exact instant a
# paper signal fires (the user checks the app, decides, places the order).
MATCH_WINDOW_DAYS = 3

# A gap this large (percentage points of P&L) between what the paper engine
# assumed and what the real fill actually achieved is flagged as a
# persistent red flag once it recurs across REPEATED_GAP_MIN_OCCURRENCES.
SIGNIFICANT_GAP_PCT = 1.0
REPEATED_GAP_MIN_OCCURRENCES = 3


def has_real_trades(db: Session) -> bool:
    return db.query(PortfolioTransaction.id).first() is not None


def _find_matching_paper_trade(
    db: Session, ticker: str, transaction_date: date, transaction_type: str,
) -> Optional[PaperTrade]:
    """
    Find the paper trade closest in date to a real transaction, on the same
    symbol and matching side (buy -> entry, sell -> exit). Returns None if
    nothing falls within MATCH_WINDOW_DAYS — an unmatched real trade is not
    an error, just outside what the paper engine could have anticipated.
    """
    window_start = transaction_date - timedelta(days=MATCH_WINDOW_DAYS)
    window_end = transaction_date + timedelta(days=MATCH_WINDOW_DAYS)

    q = db.query(PaperTrade).filter(PaperTrade.symbol == ticker)
    if transaction_type == "buy":
        q = q.filter(PaperTrade.entry_date >= window_start, PaperTrade.entry_date <= window_end)
    elif transaction_type == "sell":
        q = q.filter(
            PaperTrade.exit_date.isnot(None),
            PaperTrade.exit_date >= window_start,
            PaperTrade.exit_date <= window_end,
        )
    else:
        return None

    candidates = q.all()
    if not candidates:
        return None

    ref_date = transaction_date
    def _dist(t: PaperTrade) -> int:
        d = t.entry_date if transaction_type == "buy" else t.exit_date
        return abs((d - ref_date).days) if d else 999
    return min(candidates, key=_dist)


def reconcile(db: Session, lookback_days: int = 365) -> dict:
    """
    Compare every real transaction in the lookback window against its
    matched paper trade (if any). Returns a summary with per-transaction
    detail and any persistent gaps flagged.

    Returns:
        {
          "has_real_trades": bool,
          "transactions_checked": int,
          "matched": int,
          "unmatched": int,
          "comparisons": [ {ticker, transaction_date, real_price,
                             paper_price, gap_pct, matched} ... ],
          "persistent_gap_flags": [ {ticker, occurrences, avg_gap_pct} ... ],
        }
    """
    cutoff = date.today() - timedelta(days=lookback_days)
    real_txns = (
        db.query(PortfolioTransaction)
        .filter(
            PortfolioTransaction.transaction_type.in_(["buy", "sell"]),
            PortfolioTransaction.transaction_date >= cutoff,
        )
        .order_by(PortfolioTransaction.transaction_date.asc())
        .all()
    )

    if not real_txns:
        return {
            "has_real_trades": False,
            "transactions_checked": 0,
            "matched": 0,
            "unmatched": 0,
            "comparisons": [],
            "persistent_gap_flags": [],
            "note": "No real transactions recorded yet — reconciliation has nothing to compare. "
                    "This is expected until the user records their first manual trade in the "
                    "Personal Portfolio tracker.",
        }

    comparisons: list[dict] = []
    gaps_by_ticker: dict[str, list[float]] = {}

    for txn in real_txns:
        matched_trade = _find_matching_paper_trade(
            db, txn.ticker, txn.transaction_date, txn.transaction_type,
        )
        if matched_trade is None:
            comparisons.append({
                "ticker": txn.ticker,
                "transaction_date": txn.transaction_date.isoformat(),
                "transaction_type": txn.transaction_type,
                "real_price": txn.price,
                "paper_price": None,
                "gap_pct": None,
                "matched": False,
            })
            continue

        paper_price = (
            matched_trade.entry_price if txn.transaction_type == "buy"
            else matched_trade.exit_price
        )
        gap_pct = None
        if paper_price and txn.price:
            gap_pct = round((txn.price - paper_price) / paper_price * 100.0, 3)
            gaps_by_ticker.setdefault(txn.ticker, []).append(gap_pct)

        comparisons.append({
            "ticker": txn.ticker,
            "transaction_date": txn.transaction_date.isoformat(),
            "transaction_type": txn.transaction_type,
            "real_price": txn.price,
            "paper_price": paper_price,
            "gap_pct": gap_pct,
            "matched": True,
            "paper_strategy_id": matched_trade.strategy_id,
        })

    persistent_gap_flags = []
    for ticker, gaps in gaps_by_ticker.items():
        significant = [g for g in gaps if abs(g) >= SIGNIFICANT_GAP_PCT]
        if len(significant) >= REPEATED_GAP_MIN_OCCURRENCES:
            avg_gap = round(sum(significant) / len(significant), 3)
            persistent_gap_flags.append({
                "ticker": ticker,
                "occurrences": len(significant),
                "avg_gap_pct": avg_gap,
                "direction": "real_worse_than_paper" if avg_gap > 0 else "real_better_than_paper",
            })
            log.warning(
                "Persistent paper-vs-real gap for %s: %d occurrences, avg %.2f%% (%s)",
                ticker, len(significant), avg_gap,
                "real fills worse than paper assumed" if avg_gap > 0 else "real fills better than paper assumed",
            )

    matched_count = sum(1 for c in comparisons if c["matched"])
    return {
        "has_real_trades": True,
        "transactions_checked": len(real_txns),
        "matched": matched_count,
        "unmatched": len(real_txns) - matched_count,
        "comparisons": comparisons,
        "persistent_gap_flags": persistent_gap_flags,
    }
