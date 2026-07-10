"""
Strategy Lifecycle Manager
Handles state transitions: candidate → shadow → promoted → active → retired.

Rules:
  - Promotion requires fitness >= PROMOTE_THRESHOLD
  - Retirement happens when fitness drops below RETIRE_THRESHOLD for N consecutive days
    OR when max_drawdown exceeds DRAWDOWN_LIMIT
  - Retired strategies are moved to graveyard with lessons extracted
  - Human approval is required before "active" status — AQRTI can only reach "promoted"
"""

from __future__ import annotations

import sys, os, json
from datetime import date, datetime, timedelta
from typing import Optional

import pytz

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from sqlalchemy.orm import Session

from aqrti.database.models import StrategyV2, StrategyGraveyard, KnowledgeEvent
from aqrti.utils.logger import get_logger

log = get_logger("strategy_lifecycle")

from strategies.promotion_config import (
    PROMOTE_THRESHOLD, RETIRE_THRESHOLD, MIN_BACKTEST_TRADES,
    MIN_WIN_RATE, MIN_SHARPE, REQUIRE_OOS_PASS, MIN_OOS_SHARPE,
    PAPER_WIN_RATE_GATE, BENCHMARK_SHARPE_FACTOR, MAX_TRADE_OVERLAP,
    QUARANTINE_MIN_DAYS, QUARANTINE_MIN_TRADES, QUARANTINE_MIN_WIN_RATE,
    MAX_DRAWDOWN_LIMIT,
)

DRAWDOWN_LIMIT = MAX_DRAWDOWN_LIMIT     # backwards-compat alias for external importers
MIN_TRADES     = MIN_BACKTEST_TRADES   # backwards-compat alias for external importers
PAPER_WIN_RATE = PAPER_WIN_RATE_GATE   # backwards-compat alias

IST = pytz.timezone("Asia/Kolkata")


def _get_quarantine_release_date(promoted_at: Optional[datetime]) -> date:
    """Return the quarantine release date, clamped to >= today."""
    if promoted_at is None:
        return date.today()
    computed = (promoted_at + timedelta(days=QUARANTINE_MIN_DAYS)).date()
    return max(computed, date.today())


def _get_next_lottery_schedule() -> dict:
    """Return next lottery run time as IST-aware dict."""
    now_ist = datetime.now(IST)
    # Next lottery: next weekday at 15:30 IST (after NSE close)
    target = now_ist.replace(hour=15, minute=30, second=0, microsecond=0)
    if target <= now_ist:
        target += timedelta(days=1)
    # Skip weekends
    while target.weekday() >= 5:
        target += timedelta(days=1)
    return {
        "next_lottery_ist": target.isoformat(),
        "current_time_ist": now_ist.isoformat(),
        "seconds_until_next": int((target - now_ist).total_seconds()),
    }

_SHARPE_CACHE_MAXSIZE = 256   # bounded — see note below on why this can't be @lru_cache

_nifty_sharpe_cache: dict = {}
_index_futures_sharpe_cache: dict = {}


def _cache_put(cache: dict, key, val, maxsize: int = _SHARPE_CACHE_MAXSIZE) -> None:
    """Bounded insert with FIFO eviction. These caches are keyed by
    (start, end) backtest-window tuples, not by db Session (unhashable and
    irrelevant to the result), so functools.lru_cache can't wrap the
    functions directly — this is the manual equivalent, sized generously
    above the handful of distinct windows seen in practice so it only ever
    evicts under genuinely unbounded key growth (e.g. per-strategy rolling
    walk-forward windows), not normal operation."""
    if len(cache) >= maxsize:
        cache.pop(next(iter(cache)))
    cache[key] = val


def _nifty_benchmark_sharpe(db: Session, start, end) -> float:
    """Honest daily Sharpe of buy-and-hold NIFTY50 over [start, end]."""
    key = (start, end)
    if key in _nifty_sharpe_cache:
        return _nifty_sharpe_cache[key]
    from aqrti.database.models import IndexData
    from strategies.strategy_metrics import compute_sharpe
    rows = (
        db.query(IndexData.returns)
        .filter(IndexData.index_name == "NIFTY50",
                IndexData.date >= start, IndexData.date <= end)
        .order_by(IndexData.date.asc())
        .all()
    )
    rets = [r[0] for r in rows if r[0] is not None]
    val = compute_sharpe(rets) if len(rets) >= 20 else 0.0
    _cache_put(_nifty_sharpe_cache, key, val)
    return val


def _own_instrument_benchmark_sharpe(db: Session, index_name: str, start, end) -> float:
    """
    Honest daily Sharpe of buy-and-hold on the strategy's OWN index future
    over [start, end]. A BANKNIFTY strategy benchmarked against NIFTY50
    buy-and-hold is comparing against the wrong instrument; a NIFTY50
    strategy benchmarked against NIFTY50 itself would be circular either
    way — so index-futures strategies use this instead of
    _nifty_benchmark_sharpe, always benchmarked against their OWN
    underlying's buy-and-hold return (computed from the spot close series,
    since spot-vs-spot buy-and-hold is the right "did nothing" comparison
    regardless of the synthetic futures basis layered on top for trading).
    """
    key = (index_name, start, end)
    if key in _index_futures_sharpe_cache:
        return _index_futures_sharpe_cache[key]
    from aqrti.database.models import IndexFuturesPrice
    from strategies.strategy_metrics import compute_sharpe
    rows = (
        db.query(IndexFuturesPrice.spot_close)
        .filter(IndexFuturesPrice.index_name == index_name,
                IndexFuturesPrice.date >= start, IndexFuturesPrice.date <= end)
        .order_by(IndexFuturesPrice.date.asc())
        .all()
    )
    closes = [r[0] for r in rows if r[0] is not None]
    rets = [
        (closes[i] / closes[i - 1] - 1) * 100
        for i in range(1, len(closes)) if closes[i - 1]
    ]
    val = compute_sharpe(rets) if len(rets) >= 20 else 0.0
    _cache_put(_index_futures_sharpe_cache, key, val)
    return val


def _trade_overlap_with_promoted(db: Session, strategy_id: str) -> tuple[float, Optional[str]]:
    """
    Max Jaccard similarity of (symbol, entry_date) backtest-trade sets between
    this strategy and any currently promoted/active strategy.
    Returns (max_overlap, most_similar_strategy_id).
    """
    from aqrti.database.models import StrategyBacktestTrade
    mine = {
        (r[0], r[1]) for r in
        db.query(StrategyBacktestTrade.symbol, StrategyBacktestTrade.entry_date)
        .filter(StrategyBacktestTrade.strategy_id == strategy_id).all()
    }
    if not mine:
        return 0.0, None
    # Trade-overlap only means anything within the same asset class — an
    # index-futures strategy's trades (index, entry_date) can never overlap
    # a stock strategy's trades (symbol, entry_date) in any meaningful sense.
    this_strat = db.query(StrategyV2.asset_class).filter(
        StrategyV2.strategy_id == strategy_id
    ).scalar()
    peers = [
        r[0] for r in
        db.query(StrategyV2.strategy_id)
        .filter(StrategyV2.status.in_(["promoted", "active"]),
                StrategyV2.strategy_id != strategy_id,
                StrategyV2.asset_class == (this_strat or "stock"))
        .all()
    ]
    worst, worst_id = 0.0, None
    for pid in peers:
        theirs = {
            (r[0], r[1]) for r in
            db.query(StrategyBacktestTrade.symbol, StrategyBacktestTrade.entry_date)
            .filter(StrategyBacktestTrade.strategy_id == pid).all()
        }
        if not theirs:
            continue
        jac = len(mine & theirs) / len(mine | theirs)
        if jac > worst:
            worst, worst_id = jac, pid
    return worst, worst_id


def promote_strategy(
    db:          Session,
    strategy_id: str,
    reason:      str = "fitness_threshold_met",
) -> dict:
    """
    Move a strategy from shadow → promoted.
    Does NOT move to 'active' — that requires human approval.
    """
    row = db.query(StrategyV2).filter(StrategyV2.strategy_id == strategy_id).first()
    if not row:
        return {"success": False, "error": "strategy not found"}
    if row.status not in ("candidate", "shadow"):
        return {"success": False, "error": f"cannot promote from {row.status}"}
    if (row.fitness_score or 0) < PROMOTE_THRESHOLD:
        return {"success": False, "error": f"fitness {row.fitness_score} below threshold {PROMOTE_THRESHOLD}"}
    if (row.trade_count or 0) < MIN_TRADES:
        return {"success": False, "error": f"insufficient trades ({row.trade_count})"}
    if (row.win_rate or 0) < MIN_WIN_RATE:
        return {"success": False, "error": f"win_rate {row.win_rate:.1f}% below {MIN_WIN_RATE}% threshold"}
    if (row.sharpe or 0) < MIN_SHARPE:
        return {"success": False, "error": f"sharpe {row.sharpe:.2f} below {MIN_SHARPE} threshold"}
    # Out-of-sample HARD gate: strategy must have proven itself on the
    # held-out walk-forward window. None = never OOS-tested → not promotable.
    if REQUIRE_OOS_PASS and not row.oos_passed:
        return {"success": False, "error": f"OOS gate failed (oos_passed={row.oos_passed}, oos_wr={row.oos_win_rate})"}
    if REQUIRE_OOS_PASS and (row.oos_sharpe or 0) < MIN_OOS_SHARPE:
        return {"success": False, "error": f"oos_sharpe {row.oos_sharpe or 0:.2f} below {MIN_OOS_SHARPE}"}

    # Benchmark gate: must reach BENCHMARK_SHARPE_FACTOR × buy-and-hold
    # Sharpe over the same backtest window. Worse than doing nothing = not
    # worth capital. Index-futures strategies benchmark against their OWN
    # underlying's buy-and-hold (a BANKNIFTY strategy vs NIFTY50 buy-and-hold
    # is the wrong comparison; vs its own instrument is the right one).
    if row.backtest_start and row.backtest_end:
        if row.asset_class == "index_futures" and row.index_name:
            bench = _own_instrument_benchmark_sharpe(
                db, row.index_name, row.backtest_start, row.backtest_end
            )
            bench_label = row.index_name
        else:
            bench = _nifty_benchmark_sharpe(db, row.backtest_start, row.backtest_end)
            bench_label = "NIFTY"
        if bench > 0 and (row.sharpe or 0) < bench * BENCHMARK_SHARPE_FACTOR:
            return {"success": False,
                    "error": f"sharpe {row.sharpe or 0:.2f} below benchmark gate "
                             f"({BENCHMARK_SHARPE_FACTOR}x {bench_label} {bench:.2f})"}

    # Duplicate gate: near-clone of an already-promoted strategy adds
    # concentration risk, not edge.
    overlap, twin = _trade_overlap_with_promoted(db, strategy_id)
    if overlap > MAX_TRADE_OVERLAP:
        return {"success": False,
                "error": f"trade overlap {overlap:.0%} with {twin} exceeds {MAX_TRADE_OVERLAP:.0%}"}

    old_status   = row.status
    row.status   = "promoted"
    row.promoted_at = datetime.utcnow()
    row.updated_at  = datetime.utcnow()

    _log_event(db, strategy_id, "strategy_promoted",
               f"Promoted from {old_status}. Fitness={row.fitness_score:.1f}. {reason}")
    log.info("Strategy %s promoted to 'promoted' (fitness=%.1f)", strategy_id, row.fitness_score)
    try:
        from aqrti.alerts.telegram_alerts import alert_algo_promoted
        # StrategyV2 has no `sharpe_ratio` column (that's a PerformanceSnapshot
        # field) — the real column is `sharpe`. Using the wrong attribute
        # silently evaluated to `None` (AttributeError would only fire on a
        # class without __getattr__ fallback; SQLAlchemy models raise
        # AttributeError here, which the bare `except Exception` swallowed,
        # so no promotion alert was ever sent). Also `row.win_rate` is
        # already a percent (e.g. 52.3, gated against MIN_WIN_RATE=52.0 in
        # promotion_config.py) — multiplying by 100 again produced a
        # nonsense value like "5230.0%" in the alert text.
        alert_algo_promoted(strategy_id, row.sharpe or 0.0, row.win_rate or 0.0)
    except Exception:
        pass
    return {"success": True, "new_status": "promoted", "fitness": row.fitness_score}


def retire_strategy(
    db:             Session,
    strategy_id:    str,
    failure_reason: str = "low_fitness",
    failure_detail: str = "",
    regime_at:      str | None = None,
) -> dict:
    """
    Retire a strategy: update status → retired, write to graveyard.
    Strategies are NEVER deleted.
    """
    try:
        row = db.query(StrategyV2).filter(StrategyV2.strategy_id == strategy_id).first()
        if not row:
            return {"success": False, "error": "strategy not found"}
        if row.status == "archived":
            return {"success": False, "error": "already archived"}

        lessons = _extract_retirement_lessons(row, failure_reason)

        row.status        = "retired"
        row.retired_at    = datetime.utcnow()
        row.status_reason = failure_reason
        row.updated_at    = datetime.utcnow()

        already = (
            db.query(StrategyGraveyard)
            .filter(StrategyGraveyard.strategy_id == strategy_id)
            .first()
        )
        if not already:
            grave = StrategyGraveyard(
                strategy_id     = strategy_id,
                name            = row.name,
                family          = row.family,
                generation      = row.generation,
                dsl_json        = row.dsl_json,
                final_fitness   = row.fitness_score,
                final_sharpe    = row.sharpe,
                final_win_rate  = row.win_rate,
                failure_reason  = failure_reason,
                failure_detail  = failure_detail,
                regime_at_death = regime_at,
                lessons_json    = json.dumps(lessons),
                lifespan_days   = (date.today() - row.created_at.date()).days if row.created_at else 0,
                trade_count     = row.trade_count,
            )
            db.add(grave)

        _log_event(db, strategy_id, "strategy_retired",
                   f"Retired. Reason: {failure_reason}. Fitness={row.fitness_score or 0}. {failure_detail}")
        db.commit()
        log.info("Strategy %s retired. Reason: %s", strategy_id, failure_reason)
        return {"success": True, "strategy_id": strategy_id, "failure_reason": failure_reason, "lessons": lessons}
    except Exception as exc:
        db.rollback()
        log.error("retire_strategy %s failed: %s", strategy_id, exc)
        return {"success": False, "error": str(exc)}


def run_lifecycle_sweep(db: Session) -> dict:
    """
    Scan all active strategies and auto-promote / auto-retire based on fitness.
    Returns summary.
    """
    promoted = []
    retired  = []

    # Promote candidates / shadow strategies that pass all gates
    candidates = (
        db.query(StrategyV2)
        .filter(StrategyV2.status.in_(["candidate", "shadow"]))
        .all()
    )
    for s in candidates:
        if (
            (s.fitness_score or 0) >= PROMOTE_THRESHOLD
            and (s.trade_count or 0) >= MIN_TRADES
            and (s.win_rate or 0) >= MIN_WIN_RATE
            and (s.sharpe or 0) >= MIN_SHARPE
            and (not REQUIRE_OOS_PASS or (s.oos_passed and (s.oos_sharpe or 0) >= MIN_OOS_SHARPE))
        ):
            r = promote_strategy(db, s.strategy_id)
            if r["success"]:
                promoted.append(s.strategy_id)

    # Retire shadow/promoted strategies that fall below thresholds
    at_risk = (
        db.query(StrategyV2)
        .filter(StrategyV2.status.in_(["shadow", "promoted"]))
        .all()
    )
    for s in at_risk:
        # Don't retire a strategy that hasn't completed a full backtest yet
        if (s.trade_count or 0) < MIN_TRADES:
            continue
        reason = None
        detail = ""
        if (s.fitness_score or 100) < RETIRE_THRESHOLD:
            reason = "low_fitness"
            detail = f"fitness={s.fitness_score:.1f} below {RETIRE_THRESHOLD}"
        elif s.status == "promoted" and (s.win_rate or 0) < MIN_WIN_RATE:
            reason = "low_win_rate"
            detail = f"win_rate={s.win_rate:.1f}% below {MIN_WIN_RATE}% threshold"
        elif (s.max_drawdown or 0) < MAX_DRAWDOWN_LIMIT:
            # max_drawdown is stored as a negative percent, so "worse than
            # the limit" means more negative (< the limit). Was previously
            # unreachable at -100.0; now checked against the honest daily
            # mark-to-market drawdown. A strategy can pass fitness/win-rate
            # while still carrying a catastrophic single blowout — this
            # catches that failure mode independently.
            reason = "drawdown"
            detail = f"max_drawdown={s.max_drawdown:.1f}% breached {MAX_DRAWDOWN_LIMIT}% limit"
        if reason:
            r = retire_strategy(db, s.strategy_id, failure_reason=reason, failure_detail=detail)
            if r["success"]:
                retired.append(s.strategy_id)

    db.commit()
    log.info("Lifecycle sweep: promoted=%d retired=%d", len(promoted), len(retired))
    return {"promoted": promoted, "retired": retired}


def _extract_retirement_lessons(row: StrategyV2, failure_reason: str) -> list[str]:
    lessons = []
    if failure_reason == "low_fitness":
        lessons.append(f"Family '{row.family}' gen {row.generation}: fitness degraded to {row.fitness_score or 0}. "
                       f"Sharpe={row.sharpe or 0}, win_rate={row.win_rate or 0}.")
    if failure_reason == "drawdown":
        lessons.append(f"Max drawdown {row.max_drawdown or 0}% exceeded limits — position sizing or stop-loss insufficient.")
    if row.trade_count and row.trade_count < MIN_TRADES:
        lessons.append("Strategy fired too few signals — rules may be too restrictive.")
    try:
        regimes = json.loads(row.allowed_regimes or "[]")
        if len(regimes) == 1:
            lessons.append(f"Single-regime strategy (only {regimes[0]}) — high regime-change risk.")
    except Exception:
        pass
    return lessons


def _log_event(db: Session, strategy_id: str, event_type: str, desc: str):
    event = KnowledgeEvent(
        event_date  = date.today(),
        category    = "strategy",
        event_type  = event_type,
        description = f"[{strategy_id}] {desc}",
        outcome     = "neutral",
    )
    db.add(event)
