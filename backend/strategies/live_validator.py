"""
Live Paper Trading Validator
════════════════════════════
Bridges the gap between paper trades (PaperTrade table) and strategy validation
(StrategyPerformance table).

Every time a paper trade closes, this module:
  1. Identifies which strategy drove the trade (strategy_id on PaperTrade)
  2. Writes / updates a StrategyPerformance row for that day
  3. Computes live Sharpe, win-rate, profit-factor from closed paper trades
  4. Flags strategies whose live metrics diverge badly from their backtest metrics
     (live validation gap > 15pp Sharpe or >20pp win-rate → demote to shadow)

Called by:
  - paper_trade.close_position() (per-trade, lightweight)
  - /api/v1/strategy-performance/validate (daily sweep, full recompute)
"""

from __future__ import annotations

import sys, os, math
from datetime import date, timedelta
from collections import defaultdict
from typing import Optional

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from sqlalchemy.orm import Session
from aqrti.database.models import (
    PaperTrade, StrategyPerformance, StrategyV2, MarketRegime,
)
from aqrti.utils.logger import get_logger

log = get_logger("live_validator")

# ── Thresholds ─────────────────────────────────────────────────
MIN_LIVE_TRADES      = 3     # need at least 3 closed live trades before judging
SHARPE_DIVERGE_LIMIT = 0.8   # if live Sharpe < backtest Sharpe - 0.8 → flag
WINRATE_DIVERGE_LIMIT = 20.0 # if live win-rate < backtest - 20pp → flag
DEMOTION_MIN_TRADES  = 5     # only demote if ≥ 5 live trades (avoid noise)


# ── Helpers ───────────────────────────────────────────────────

def _sharpe(returns: list[float], risk_free_daily: float = 0.067 / 252) -> float:
    if len(returns) < 3:
        return 0.0
    n   = len(returns)
    avg = sum(returns) / n
    var = sum((r - avg) ** 2 for r in returns) / n
    std = math.sqrt(var)
    if std == 0:
        return 0.0
    excess = avg - risk_free_daily
    return round(excess / std * math.sqrt(252), 3)


def _current_regime(db: Session) -> str:
    row = db.query(MarketRegime.regime).order_by(MarketRegime.date.desc()).first()
    return row[0] if row else "BULL"


# ── Core: record one day's live performance per strategy ───────

def record_strategy_live_day(
    db:          Session,
    strategy_id: str,
    on_date:     date,
) -> Optional[StrategyPerformance]:
    """
    Aggregate all paper trades for strategy_id that closed on on_date
    and upsert a StrategyPerformance row.
    """
    # PaperTrade.strategy_id has no FK (positions may reference a strategy
    # that's since been deleted, e.g. population cleanup). StrategyPerformance
    # DOES have a hard FK to strategies_v2 — skip rather than let the insert
    # violate it and poison the caller's shared session.
    if not db.query(StrategyV2.id).filter_by(strategy_id=strategy_id).first():
        return None

    # All trades for this strategy on this date
    day_trades = (
        db.query(PaperTrade)
        .filter(
            PaperTrade.strategy_id == strategy_id,
            PaperTrade.is_open     == False,
            PaperTrade.exit_date   == on_date,
        )
        .all()
    )
    opened_today = db.query(PaperTrade).filter(
        PaperTrade.strategy_id == strategy_id,
        PaperTrade.entry_date  == on_date,
    ).count()

    # Cumulative across all time
    all_closed = (
        db.query(PaperTrade)
        .filter(
            PaperTrade.strategy_id == strategy_id,
            PaperTrade.is_open     == False,
        )
        .all()
    )

    wins   = [t for t in day_trades if (t.gross_pnl or 0) > 0]
    losses = [t for t in day_trades if (t.gross_pnl or 0) <= 0]
    daily_pnl     = sum(t.gross_pnl or 0 for t in day_trades)
    daily_pnl_pct = sum(t.gross_pnl_pct or 0 for t in day_trades)

    # Cumulative P&L from all closed trades
    cum_pnl = sum(t.gross_pnl or 0 for t in all_closed)

    regime = _current_regime(db)

    existing = (
        db.query(StrategyPerformance)
        .filter_by(strategy_id=strategy_id, date=on_date)
        .first()
    )
    if existing:
        existing.trades_closed   = len(day_trades)
        existing.trades_opened   = opened_today
        existing.daily_pnl       = round(daily_pnl, 4)
        existing.daily_pnl_pct   = round(daily_pnl_pct, 4)
        existing.cumulative_pnl  = round(cum_pnl, 4)
        existing.win_count       = len(wins)
        existing.loss_count      = len(losses)
        existing.regime_at       = regime
        perf = existing
    else:
        perf = StrategyPerformance(
            strategy_id    = strategy_id,
            date           = on_date,
            signals_fired  = 0,
            trades_opened  = opened_today,
            trades_closed  = len(day_trades),
            daily_pnl      = round(daily_pnl, 4),
            daily_pnl_pct  = round(daily_pnl_pct, 4),
            cumulative_pnl = round(cum_pnl, 4),
            win_count      = len(wins),
            loss_count     = len(losses),
            regime_at      = regime,
        )
        db.add(perf)

    log.debug(
        "Live perf %s %s: closed=%d pnl=%.2f cum=%.2f",
        strategy_id, on_date, len(day_trades), daily_pnl, cum_pnl,
    )
    return perf


# ── Full daily validation sweep ────────────────────────────────

def run_daily_validation_sweep(db: Session, days_back: int = 90) -> dict:
    """
    Full recompute: scan all paper trades in last `days_back` days,
    attribute to strategies, write StrategyPerformance rows,
    and check for live vs. backtest divergence.

    Returns summary dict.
    """
    cutoff = date.today() - timedelta(days=days_back)

    # Find all strategies that have live paper trades
    rows = (
        db.query(PaperTrade)
        .filter(
            PaperTrade.strategy_id.isnot(None),
            PaperTrade.is_open == False,
            PaperTrade.exit_date >= cutoff,
        )
        .all()
    )

    # Group by (strategy_id, exit_date)
    by_strat_date: dict[str, set] = defaultdict(set)
    for t in rows:
        if t.strategy_id and t.exit_date:
            by_strat_date[t.strategy_id].add(t.exit_date)

    written = 0
    demoted = []
    flagged = []

    for strategy_id, dates in by_strat_date.items():
        for d in sorted(dates):
            record_strategy_live_day(db, strategy_id, d)
            written += 1

        # Check divergence vs backtest
        result = _check_live_divergence(db, strategy_id)
        if result["demote"]:
            demoted.append(strategy_id)
            _demote_to_shadow(db, strategy_id, result["reason"])
        elif result["flag"]:
            flagged.append(strategy_id)

    db.commit()

    log.info(
        "Validation sweep: %d performance rows written, %d demoted, %d flagged",
        written, len(demoted), len(flagged),
    )
    return {
        "status":        "ok",
        "rows_written":  written,
        "demoted":       demoted,
        "flagged":       flagged,
        "strategies_evaluated": len(by_strat_date),
    }


def _check_live_divergence(db: Session, strategy_id: str) -> dict:
    """
    Compare live paper trading performance vs. backtest metrics.
    Returns {demote: bool, flag: bool, reason: str}.
    """
    strat = db.query(StrategyV2).filter_by(strategy_id=strategy_id).first()
    if not strat:
        return {"demote": False, "flag": False, "reason": ""}

    closed = (
        db.query(PaperTrade)
        .filter(
            PaperTrade.strategy_id == strategy_id,
            PaperTrade.is_open     == False,
        )
        .all()
    )
    if len(closed) < MIN_LIVE_TRADES:
        return {"demote": False, "flag": False, "reason": "insufficient_live_trades"}

    live_returns = [t.gross_pnl_pct or 0.0 for t in closed]
    live_wins    = [r for r in live_returns if r > 0]
    live_sharpe  = _sharpe(live_returns)
    live_winrate = len(live_wins) / len(live_returns) * 100 if live_returns else 0.0

    bt_sharpe    = strat.sharpe or 0.0
    bt_winrate   = strat.win_rate or 0.0

    sharpe_gap   = bt_sharpe  - live_sharpe
    winrate_gap  = bt_winrate - live_winrate

    flag   = (sharpe_gap > SHARPE_DIVERGE_LIMIT * 0.5 or winrate_gap > WINRATE_DIVERGE_LIMIT * 0.5)
    demote = (
        len(closed) >= DEMOTION_MIN_TRADES and (
            sharpe_gap  > SHARPE_DIVERGE_LIMIT or
            winrate_gap > WINRATE_DIVERGE_LIMIT or
            live_winrate < 55.0   # absolute floor — live win_rate must stay ≥ 55%
        )
    )
    reason = (
        f"live_divergence: sharpe_gap={sharpe_gap:.2f} winrate_gap={winrate_gap:.1f}pp "
        f"live_wr={live_winrate:.1f}% live_trades={len(closed)}"
    )
    log.debug("Divergence %s: %s demote=%s", strategy_id, reason, demote)
    return {"demote": demote, "flag": flag, "reason": reason}


def _demote_to_shadow(db: Session, strategy_id: str, reason: str) -> None:
    strat = db.query(StrategyV2).filter_by(strategy_id=strategy_id).first()
    if not strat or strat.status not in ("promoted", "active"):
        return
    strat.status        = "shadow"
    strat.status_reason = f"auto_demoted: {reason}"
    log.warning("Strategy %s demoted to shadow: %s", strategy_id, reason)


# ── Called from paper_trade.close_position() ──────────────────

def on_trade_closed(db: Session, trade: PaperTrade) -> None:
    """
    Lightweight hook — called immediately after a paper trade closes.
    Records the live performance row for that strategy+day.
    """
    if not trade.strategy_id or not trade.exit_date:
        return
    try:
        record_strategy_live_day(db, trade.strategy_id, trade.exit_date)
        db.commit()
    except Exception as exc:
        # Roll back — leaving the session in "pending rollback" state after a
        # failed flush/commit poisons every subsequent operation on this same
        # session (the caller's db.commit(), the next position's db.delete(),
        # etc.), turning one skippable error into a cascading job failure.
        db.rollback()
        log.warning("on_trade_closed failed for %s: %s", trade.strategy_id, exc)


# ── Live metrics summary for one strategy ─────────────────────

def get_live_validation_summary(db: Session, strategy_id: str) -> dict:
    """
    Returns a full live-vs-backtest comparison for one strategy.
    Used by the Strategy DNA viewer API.
    """
    strat = db.query(StrategyV2).filter_by(strategy_id=strategy_id).first()
    if not strat:
        return {"available": False}

    closed = (
        db.query(PaperTrade)
        .filter(PaperTrade.strategy_id == strategy_id, PaperTrade.is_open == False)
        .all()
    )
    open_cnt = db.query(PaperTrade).filter(
        PaperTrade.strategy_id == strategy_id, PaperTrade.is_open == True
    ).count()

    if not closed:
        return {
            "available":       True,
            "live_trades":     0,
            "open_positions":  open_cnt,
            "backtest_sharpe": strat.sharpe,
            "backtest_winrate": strat.win_rate,
            "live_sharpe":     None,
            "live_winrate":    None,
            "divergence":      None,
            "status":          strat.status,
        }

    live_returns = [t.gross_pnl_pct or 0.0 for t in closed]
    live_wins    = [r for r in live_returns if r > 0]
    live_sharpe  = _sharpe(live_returns)
    live_wr      = len(live_wins) / len(live_returns) * 100 if live_returns else 0.0
    live_pnl     = sum(live_returns)
    live_avg_hold= sum(t.holding_days or 0 for t in closed) / len(closed)

    bt_sharpe    = strat.sharpe or 0.0
    bt_wr        = strat.win_rate or 0.0
    sharpe_gap   = round(bt_sharpe - live_sharpe, 3)
    wr_gap       = round(bt_wr - live_wr, 2)

    divergence_status = "ok"
    if sharpe_gap > SHARPE_DIVERGE_LIMIT or wr_gap > WINRATE_DIVERGE_LIMIT:
        divergence_status = "critical"
    elif sharpe_gap > SHARPE_DIVERGE_LIMIT * 0.5 or wr_gap > WINRATE_DIVERGE_LIMIT * 0.5:
        divergence_status = "warning"

    return {
        "available":        True,
        "live_trades":      len(closed),
        "open_positions":   open_cnt,
        "live_total_pnl":   round(live_pnl, 4),
        "live_avg_holding": round(live_avg_hold, 1),
        "live_sharpe":      live_sharpe,
        "live_winrate":     round(live_wr, 2),
        "backtest_sharpe":  bt_sharpe,
        "backtest_winrate": bt_wr,
        "sharpe_gap":       sharpe_gap,
        "winrate_gap":      wr_gap,
        "divergence":       divergence_status,
        "status":           strat.status,
    }
