"""
Paper Execution Engine
Converts target portfolio weights into open/close actions.
No live market access — uses daily_prices close as fill price.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from sqlalchemy.orm import Session

from aqrti.database.models import DailyPrice
from aqrti.utils.logger import get_logger
from paper_trading.paper_portfolio import get_or_create_portfolio, update_portfolio_value
from paper_trading.paper_trade import (
    open_position, close_position, get_open_positions,
)

log = get_logger("paper_execution")


def _get_fill_price(db: Session, symbol: str) -> Optional[float]:
    """Use latest close as fill price — simulates market-on-close execution."""
    row = (
        db.query(DailyPrice.close)
        .filter(DailyPrice.symbol == symbol)
        .order_by(DailyPrice.date.desc())
        .first()
    )
    return row[0] if row else None


def execute_rebalance(
    db:              Session,
    target_weights:  dict[str, float],   # {symbol: weight_pct}
    reason:          str = "rebalance",
    candidates:      list[dict] = None,  # optional candidate metadata from portfolio_builder
) -> dict:
    """
    Compare current positions against target_weights and execute trades.

    Rules:
    - Symbols in target_weights but not in portfolio → open new position
    - Symbols in portfolio but not in target_weights → close position
    - Portfolio value is recalculated after each close before new opens

    Returns execution report dict.
    """
    DRIFT_REBALANCE_THRESHOLD = 5.0   # close+reopen if weight drifts > 5 pct points
    MIN_HOLD_DAYS = 3                 # never close a position held fewer than 3 days on rebalance

    portfolio  = get_or_create_portfolio(db)
    current_positions = get_open_positions(db)
    current    = {p["symbol"] for p in current_positions}
    target_set = set(target_weights.keys())

    # Only close positions that are at least MIN_HOLD_DAYS old, to reduce churn
    from aqrti.database.models import PaperPosition
    pos_entry_dates = {
        p["symbol"]: p.get("entryDate") for p in current_positions
    }

    def _held_long_enough(symbol: str) -> bool:
        ed = pos_entry_dates.get(symbol)
        if not ed:
            return True
        if isinstance(ed, str):
            from datetime import datetime as _dt
            try:
                ed = _dt.strptime(ed, "%Y-%m-%d").date()
            except Exception:
                return True
        return (date.today() - ed).days >= MIN_HOLD_DAYS

    to_close = {s for s in (current - target_set) if _held_long_enough(s)}
    to_open  = target_set - current

    # Also close positions whose weight has drifted far from target (force resize)
    for pos in current_positions:
        sym = pos["symbol"]
        if sym not in target_set:
            continue
        current_weight = pos["weightPct"] or 0.0
        target_weight  = target_weights[sym]
        drift = abs(current_weight - target_weight)
        if drift > DRIFT_REBALANCE_THRESHOLD:
            log.info(
                "Drift rebalance: %s  current=%.1f%%  target=%.1f%%  drift=%.1f%%",
                sym, current_weight, target_weight, drift,
            )
            to_close.add(sym)
            to_open.add(sym)

    closed_pnl  = 0.0
    closed_list = []
    opened_list = []
    errors      = []

    # Build candidate lookup for metadata pass-through
    cand_map = {c["symbol"]: c for c in (candidates or [])}

    # ── Close exits first to free up cash ────────────────────────
    # Look up capital_deployed before closing (position gets deleted by close_position)
    pos_capital = {p["symbol"]: p["capitalDeployed"] for p in current_positions}

    for symbol in sorted(to_close):
        deployed = pos_capital.get(symbol, 0.0)
        result = close_position(db, symbol, exit_reason=reason)
        if result:
            freed_cash = deployed + (result["grossPnl"] or 0.0)
            portfolio.current_cash += freed_cash
            db.commit()
            closed_pnl += result["grossPnl"]
            closed_list.append(result["symbol"])

    # ── Refresh portfolio after closes ────────────────────────────
    db.refresh(portfolio)

    # ── Open new positions ────────────────────────────────────────
    for symbol in sorted(to_open):
        weight    = target_weights[symbol]
        fill      = _get_fill_price(db, symbol)
        if not fill:
            errors.append({"symbol": symbol, "error": "no_price"})
            log.warning("No price for %s — skipping open", symbol)
            continue

        capital = portfolio.current_cash * (weight / 100)

        # Check we have enough cash (with 1% buffer)
        if capital > portfolio.current_cash * 0.99:
            capital = portfolio.current_cash * 0.95

        if capital < 100:
            errors.append({"symbol": symbol, "error": "insufficient_cash"})
            continue

        cand = cand_map.get(symbol, {})
        pos = open_position(
            db              = db,
            symbol          = symbol,
            capital         = capital,
            portfolio_value = portfolio.total_value,
            entry_price     = fill,
            direction       = cand.get("direction", "Bullish"),
            confidence      = cand.get("confidence", 0.0),
            expected_return = cand.get("expectedReturn", 0.0),
            sector          = cand.get("sector"),
            prediction_id   = cand.get("predictionId"),
            strategy_id     = cand.get("strategyId"),
            strategy_name   = cand.get("strategyName"),
        )
        if pos:
            portfolio.current_cash -= capital
            opened_list.append(symbol)

    # ── Recalculate total portfolio value ─────────────────────────
    open_pos   = get_open_positions(db)
    invested   = sum(p["currentValue"] for p in open_pos)
    total_val  = portfolio.current_cash + invested
    update_portfolio_value(db, total_val, portfolio.current_cash)

    log.info(
        "Rebalance: closed=%d opened=%d errors=%d  new_value=%.2f",
        len(closed_list), len(opened_list), len(errors), total_val,
    )
    return {
        "date":         str(date.today()),
        "closed":       closed_list,
        "opened":       opened_list,
        "closedPnl":    round(closed_pnl, 2),
        "errors":       errors,
        "portfolioValue": round(total_val, 2),
    }


MAX_HOLDING_DAYS = 20   # force-close any position held longer than this


def mark_to_market(db: Session) -> dict:
    """
    Recalculate current portfolio value using latest prices.
    Enforces stop-loss, take-profit, and max-holding-day rules on open positions.
    Feeds closed losing trades back to the strategy refinement pipeline.
    """
    from aqrti.database.models import PaperPosition

    portfolio   = get_or_create_portfolio(db)
    sl_closed   = []
    tp_closed   = []
    expired     = []
    loss_trades = []

    positions = db.query(PaperPosition).filter_by(portfolio_name=portfolio.portfolio_name).all()
    for pos in positions:
        current_price = _get_fill_price(db, pos.symbol)
        if not current_price:
            continue

        holding_days = (date.today() - pos.entry_date).days
        unrealized_pct = (current_price - pos.entry_price) / pos.entry_price * 100

        hit_sl      = pos.stop_loss_price and current_price <= pos.stop_loss_price
        hit_tp      = pos.target_price    and current_price >= pos.target_price
        hit_expiry  = holding_days >= MAX_HOLDING_DAYS
        # Trailing time-stop: close if loss > 3% after holding ≥ 5 days with no recovery
        hit_time_stop = holding_days >= 5 and unrealized_pct < -3.0

        if hit_sl or hit_tp or hit_expiry or hit_time_stop:
            if hit_sl:
                reason = "stop_loss"
            elif hit_tp:
                reason = "take_profit"
            elif hit_expiry:
                reason = "max_holding_days"
            else:
                reason = "time_stop"

            capital_before = pos.capital_deployed
            result = close_position(db, pos.symbol, exit_reason=reason)
            if result:
                freed_cash = capital_before + (result["grossPnl"] or 0)
                portfolio.current_cash += freed_cash
                db.commit()

                if reason == "stop_loss":
                    sl_closed.append(pos.symbol)
                    log.info("Stop-loss: %s  price=%.2f  sl=%.2f", pos.symbol, current_price, pos.stop_loss_price)
                elif reason == "take_profit":
                    tp_closed.append(pos.symbol)
                    log.info("Take-profit: %s  price=%.2f  tp=%.2f", pos.symbol, current_price, pos.target_price)
                else:
                    expired.append(pos.symbol)
                    log.info("%s: %s  held=%dd  pnl=%.2f%%", reason, pos.symbol, holding_days, unrealized_pct)

                # Track losing trades for strategy feedback
                if (result["grossPnl"] or 0) < 0 and pos.strategy_id:
                    loss_trades.append({
                        "symbol":      pos.symbol,
                        "strategy_id": pos.strategy_id,
                        "pnl_pct":     result["grossPnlPct"],
                        "reason":      reason,
                        "holding_days": holding_days,
                    })

    # Feed losses to strategy refinement
    if loss_trades:
        _refine_strategies_from_losses(db, loss_trades)

    open_pos  = get_open_positions(db)
    invested  = sum(p["currentValue"] for p in open_pos)
    total_val = portfolio.current_cash + invested
    update_portfolio_value(db, total_val, portfolio.current_cash)

    return {
        "date":             str(date.today()),
        "totalValue":       round(total_val, 2),
        "cash":             round(portfolio.current_cash, 2),
        "invested":         round(invested, 2),
        "openPositions":    len(open_pos),
        "stopLossClosed":   sl_closed,
        "takeProfitClosed": tp_closed,
        "expired":          expired,
        "lossesRefined":    len(loss_trades),
    }


def _refine_strategies_from_losses(db: Session, loss_trades: list[dict]) -> None:
    """
    When a trade closes with a loss, feed the result back to the strategy engine:
    1. Record a FailureRecord so the learning system sees it
    2. Run live divergence check — if strategy is underperforming, demote it
    3. Queue it for re-evolution with updated fitness data
    """
    from collections import defaultdict
    try:
        from strategies.live_validator import on_trade_closed, _check_live_divergence, _demote_to_shadow
        from aqrti.database.models import PaperTrade, StrategyV2
    except ImportError as e:
        log.warning("Strategy refinement import error: %s", e)
        return

    strategy_losses: dict[str, list] = defaultdict(list)
    for lt in loss_trades:
        strategy_losses[lt["strategy_id"]].append(lt)

    for strategy_id, losses in strategy_losses.items():
        strat = db.query(StrategyV2).filter_by(strategy_id=strategy_id).first()
        if not strat:
            continue

        avg_loss_pct = sum(l["pnl_pct"] for l in losses) / len(losses)
        log.info(
            "Strategy %s had %d losing trade(s) avg_loss=%.2f%% — checking divergence",
            strategy_id, len(losses), avg_loss_pct,
        )

        # Check if this strategy is now diverging from its backtest metrics
        divergence = _check_live_divergence(db, strategy_id)
        if divergence["demote"]:
            _demote_to_shadow(db, strategy_id, divergence["reason"])
            log.warning("Strategy %s demoted to shadow after losses", strategy_id)

        # Record failure events for the learning system
        try:
            from aqrti.database.models import FailureRecord
            for lt in losses:
                db.add(FailureRecord(
                    failure_date      = date.today(),
                    symbol            = lt["symbol"],
                    failure_category  = "paper_trade_loss",
                    severity          = "high" if lt["pnl_pct"] < -5 else "medium",
                    root_cause        = (
                        f"Strategy {strategy_id} trade closed as {lt['reason']} "
                        f"after {lt['holding_days']}d: {lt['pnl_pct']:.2f}% loss"
                    ),
                    lesson            = f"Review strategy {strategy_id} parameters — live underperformance",
                    resolved          = False,
                ))
            db.commit()
        except Exception as e:
            log.debug("FailureRecord insert error: %s", e)

        # Queue strategy for re-evolution if it has enough losses
        try:
            closed_losses = (
                db.query(PaperTrade)
                .filter(
                    PaperTrade.strategy_id == strategy_id,
                    PaperTrade.is_open == False,
                    PaperTrade.gross_pnl_pct.isnot(None),
                    PaperTrade.gross_pnl_pct < 0,
                )
                .count()
            )
            total_closed = (
                db.query(PaperTrade)
                .filter(PaperTrade.strategy_id == strategy_id, PaperTrade.is_open == False)
                .count()
            )
            loss_rate = closed_losses / total_closed if total_closed > 0 else 0
            # If >60% loss rate on ≥5 trades, mark strategy for re-evolution
            if total_closed >= 5 and loss_rate > 0.60 and strat.status not in ("retired", "archived"):
                strat.status_reason = (
                    f"flagged_for_reevolution: loss_rate={loss_rate:.0%} "
                    f"over {total_closed} live trades"
                )
                if strat.fitness_score and avg_loss_pct < -3:
                    strat.fitness_score = max(0.0, (strat.fitness_score or 0.5) * 0.7)
                db.commit()
                log.info(
                    "Strategy %s flagged for re-evolution: loss_rate=%.0f%% trades=%d",
                    strategy_id, loss_rate * 100, total_closed,
                )
        except Exception as e:
            log.debug("Re-evolution flagging error: %s", e)

    db.commit()
