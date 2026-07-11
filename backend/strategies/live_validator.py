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

import sys, os, math, json
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

# ── Post-promotion lifecycle triggers (additive — stack on top of the
# divergence check above, never replace it; per CLAUDE.md, gates only
# tighten, never loosen) ─────────────────────────────────────────
ROLLING_WR_WINDOW      = 20    # trades — rolling window for the live WR floor
ROLLING_WR_FLOOR        = 50.0  # % — matches MIN_OOS_WIN_RATE (promotion_config.py);
                                 # a champion's live edge must never fall below what
                                 # it had to prove to get promoted in the first place
DRAWDOWN_BREACH_FACTOR  = 1.5   # live drawdown > 1.5x validated backtest max_drawdown → demote


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
            PaperTrade.portfolio_name == f"strat_{strategy_id}",
            PaperTrade.is_open       == False,
            PaperTrade.exit_date     == on_date,
        )
        .all()
    )
    opened_today = db.query(PaperTrade).filter(
        PaperTrade.portfolio_name == f"strat_{strategy_id}",
        PaperTrade.entry_date    == on_date,
    ).count()

    # Cumulative across all time
    all_closed = (
        db.query(PaperTrade)
        .filter(
            PaperTrade.portfolio_name == f"strat_{strategy_id}",
            PaperTrade.is_open        == False,
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
            continue
        elif result["flag"]:
            flagged.append(strategy_id)

        # Additive post-promotion triggers — each independently sufficient
        # to demote; checked even if the divergence check above passed.
        for check in (_check_rolling_win_rate_floor, _check_drawdown_breach, _check_regime_shift):
            trigger = check(db, strategy_id)
            if trigger["demote"]:
                demoted.append(strategy_id)
                _demote_to_shadow(db, strategy_id, trigger["reason"])
                break

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
            PaperTrade.portfolio_name == f"strat_{strategy_id}",
            PaperTrade.is_open        == False,
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


def _closed_trades_chronological(db: Session, strategy_id: str) -> list[PaperTrade]:
    return (
        db.query(PaperTrade)
        .filter(
            PaperTrade.portfolio_name == f"strat_{strategy_id}",
            PaperTrade.is_open        == False,
        )
        .order_by(PaperTrade.exit_date.asc())
        .all()
    )


def _check_rolling_win_rate_floor(db: Session, strategy_id: str) -> dict:
    """
    Trigger: live win rate over the most recent ROLLING_WR_WINDOW closed
    trades falls below ROLLING_WR_FLOOR. Uses a trailing window rather than
    all-time win rate so a champion that curdles recently gets caught even
    if its early live trades were strong enough to keep the cumulative
    average above the floor.
    """
    closed = _closed_trades_chronological(db, strategy_id)
    if len(closed) < ROLLING_WR_WINDOW:
        return {"demote": False, "reason": ""}

    window = closed[-ROLLING_WR_WINDOW:]
    wins = sum(1 for t in window if (t.gross_pnl or 0) > 0)
    win_rate = wins / len(window) * 100.0

    demote = win_rate < ROLLING_WR_FLOOR
    reason = (
        f"rolling_win_rate: {win_rate:.1f}% over last {len(window)} trades "
        f"< floor {ROLLING_WR_FLOOR}%"
    )
    if demote:
        log.warning("Strategy %s rolling WR breach: %s", strategy_id, reason)
    return {"demote": demote, "reason": reason}


def _check_drawdown_breach(db: Session, strategy_id: str) -> dict:
    """
    Trigger: live drawdown (peak-to-trough on the cumulative live P&L curve)
    exceeds DRAWDOWN_BREACH_FACTOR x the strategy's validated backtest
    max_drawdown. A strategy losing far more live than its backtest ever
    showed is exactly the "picking up pennies in front of a steamroller"
    failure mode promotion_config.py's MAX_DRAWDOWN_LIMIT exists to catch
    in backtest — this is its live-trading counterpart.
    """
    strat = db.query(StrategyV2).filter_by(strategy_id=strategy_id).first()
    if not strat or not strat.max_drawdown:
        return {"demote": False, "reason": ""}

    closed = _closed_trades_chronological(db, strategy_id)
    if len(closed) < DEMOTION_MIN_TRADES:
        return {"demote": False, "reason": ""}

    equity = 0.0
    peak = 0.0
    max_dd_pct = 0.0
    for t in closed:
        equity += (t.gross_pnl or 0.0)
        peak = max(peak, equity)
        if peak > 0:
            dd_pct = (equity - peak) / peak * 100.0
            max_dd_pct = min(max_dd_pct, dd_pct)

    bt_dd = strat.max_drawdown  # negative, percent
    breach_threshold = bt_dd * DRAWDOWN_BREACH_FACTOR  # more negative than bt_dd

    demote = max_dd_pct < breach_threshold
    reason = (
        f"drawdown_breach: live_dd={max_dd_pct:.1f}% exceeds "
        f"{DRAWDOWN_BREACH_FACTOR}x backtest_dd={bt_dd:.1f}% (threshold={breach_threshold:.1f}%)"
    )
    if demote:
        log.warning("Strategy %s drawdown breach: %s", strategy_id, reason)
    return {"demote": demote, "reason": reason}


def _check_regime_shift(db: Session, strategy_id: str) -> dict:
    """
    Trigger: the market has shifted into a regime this strategy was never
    validated in (not in its allowed_regimes / no bull_sharpe|bear_sharpe|
    sideways_sharpe|volatile_sharpe recorded for it). A strategy trading on
    while the regime moves outside its proven envelope is running blind —
    cut the signal stream rather than let it fire on an unvalidated premise.
    """
    strat = db.query(StrategyV2).filter_by(strategy_id=strategy_id).first()
    if not strat:
        return {"demote": False, "reason": ""}

    current_regime = _current_regime(db)

    allowed = []
    if strat.allowed_regimes:
        try:
            allowed = json.loads(strat.allowed_regimes)
        except (ValueError, TypeError):
            allowed = []
    if allowed and current_regime not in allowed:
        reason = f"regime_shift: current={current_regime} not in allowed_regimes={allowed}"
        log.warning("Strategy %s regime shift: %s", strategy_id, reason)
        return {"demote": True, "reason": reason}

    # Even if nominally "allowed", a regime the strategy has literally never
    # traded in (no per-regime Sharpe recorded) is unvalidated in practice.
    regime_sharpe = {
        "BULL":     strat.bull_sharpe,
        "BEAR":     strat.bear_sharpe,
        "SIDEWAYS": strat.sideways_sharpe,
        "VOLATILE": strat.volatile_sharpe,
    }.get(current_regime)
    if regime_sharpe is None:
        reason = f"regime_shift: no validated Sharpe for current regime {current_regime}"
        log.warning("Strategy %s regime shift: %s", strategy_id, reason)
        return {"demote": True, "reason": reason}

    return {"demote": False, "reason": ""}


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
        .filter(PaperTrade.portfolio_name == f"strat_{strategy_id}", PaperTrade.is_open == False)
        .all()
    )
    open_cnt = db.query(PaperTrade).filter(
        PaperTrade.portfolio_name == f"strat_{strategy_id}", PaperTrade.is_open == True
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
