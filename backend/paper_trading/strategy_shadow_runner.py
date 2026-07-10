"""
Strategy Shadow Runner — genuine forward paper-testing per strategy.

Problem this solves: the "default" paper portfolio enters on ML predictions
and merely stamps the best strategy's ID on its trades. That is NOT evidence
the strategy works — its own entry/exit rules were never exercised forward.

This runner gives every promoted/active strategy its own virtual book
(PaperTrade rows, portfolio_name = "strat_<id>") and each day:
  1. EXITS: checks each open shadow position against the latest close —
     stop-loss / take-profit / max-hold / DSL exit rule (fail-closed).
  2. ENTRIES: evaluates the strategy's OWN DSL entry conditions against
     today's feature vectors (fail-closed: no features → no entry), gated by
     the same regime/confidence logic the backtester uses.
Costs mirror the backtester (NSE delivery 0.28% round-trip).

The quarantine gate on /strategies/{id}/activate counts ONLY these shadow
trades — forward performance on data that did not exist when the strategy
was created, which is the one test that cannot be overfit.

Runs daily from the scheduler after ingestion + feature generation.
"""

from __future__ import annotations

import sys, os, json
from datetime import date, timedelta

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from sqlalchemy.orm import Session

from aqrti.database.engine import get_db
from aqrti.database.models import (
    StrategyV2, PaperTrade, DailyPrice, FeatureValue, MarketRegime,
)
from aqrti.utils.logger import get_logger

log = get_logger("strategy_shadow")

NOTIONAL_PER_TRADE = 100_000.0   # ₹1L notional per shadow trade (bookkeeping only)
MAX_OPEN_PER_STRATEGY = 8
NSE_BUY_COST  = 0.0028 * 0.55    # matches backtester split
NSE_SELL_COST = 0.0028 * 0.45


def _portfolio_name(strategy_id: str) -> str:
    return f"strat_{strategy_id}"


def _latest_trading_date(db: Session) -> date | None:
    row = db.query(DailyPrice.date).order_by(DailyPrice.date.desc()).first()
    return row[0] if row else None


def _closes_on(db: Session, on_date: date) -> dict[str, float]:
    rows = (
        db.query(DailyPrice.symbol, DailyPrice.close)
        .filter(DailyPrice.date == on_date, DailyPrice.close.isnot(None))
        .all()
    )
    return {r[0]: r[1] for r in rows}


def _features_on(db: Session, on_date: date) -> dict[str, dict]:
    rows = (
        db.query(FeatureValue.symbol, FeatureValue.feature_name, FeatureValue.value)
        .filter(FeatureValue.date == on_date, FeatureValue.version == 1)
        .all()
    )
    out: dict[str, dict] = {}
    for sym, fname, val in rows:
        out.setdefault(sym, {})[fname] = val
    return out


def _current_regime(db: Session) -> str:
    row = (
        db.query(MarketRegime.regime)
        .order_by(MarketRegime.date.desc())
        .first()
    )
    return row[0] if row else "BULL"


def run_shadow_paper_cycle() -> dict:
    """
    One daily shadow cycle for all promoted/active strategies.
    Idempotent per (strategy, date): entries are skipped for symbols already
    held; a second run on the same day is a no-op.
    """
    from strategies.strategy_dsl import StrategyDSL
    from strategies.strategy_backtester import (
        get_backtest_universe, _technical_signal, _should_enter,
    )

    report = {"date": None, "strategies": 0, "opened": 0, "closed": 0, "errors": []}

    with get_db() as db:
        today = _latest_trading_date(db)
        if today is None:
            report["errors"].append("no price data")
            return report
        report["date"] = str(today)

        closes   = _closes_on(db, today)
        features = _features_on(db, today)
        regime   = _current_regime(db)
        universe = set(get_backtest_universe(db))

        strategies = (
            db.query(StrategyV2)
            .filter(StrategyV2.status.in_(["promoted", "active"]),
                    StrategyV2.dsl_json.isnot(None))
            .all()
        )
        report["strategies"] = len(strategies)

        for strat in strategies:
            try:
                dsl = StrategyDSL.from_json(strat.dsl_json)
                pname = _portfolio_name(strat.strategy_id)

                sl   = getattr(dsl, "stop_loss_pct",    -7.0)
                tp   = getattr(dsl, "take_profit_pct",  12.0)
                hold = getattr(dsl, "max_holding_days", 20)
                conf = getattr(dsl, "min_confidence",   50.0)
                regs = getattr(dsl, "allowed_regimes",  ["BULL", "SIDEWAYS", "BEAR", "VOLATILE"])
                entry_conds = getattr(dsl, "entry_conditions", None)
                exit_conds  = getattr(dsl, "exit_conditions",  None)

                open_trades = (
                    db.query(PaperTrade)
                    .filter(PaperTrade.portfolio_name == pname,
                            PaperTrade.is_open == True)
                    .all()
                )

                # ── EXITS ─────────────────────────────────────
                for t in open_trades:
                    cur = closes.get(t.symbol)
                    if cur is None or t.entry_price <= 0:
                        continue
                    if t.entry_date == today:
                        continue   # entered today — nothing to mark yet
                    pnl_pct = (cur - t.entry_price) / t.entry_price * 100
                    held_days = (today - t.entry_date).days
                    reason = None
                    if pnl_pct <= sl:
                        reason = "stop_loss"
                    elif pnl_pct >= tp:
                        reason = "take_profit"
                    elif held_days >= hold:
                        reason = "max_holding_days"
                    elif exit_conds is not None:
                        fv = features.get(t.symbol)
                        if fv and exit_conds.evaluate(fv):
                            reason = "exit_rule"
                    if reason:
                        exit_price = cur * (1 - NSE_SELL_COST)
                        net_pnl_pct = (exit_price - t.entry_price) / t.entry_price * 100
                        t.exit_date     = today
                        t.exit_price    = round(exit_price, 4)
                        t.gross_pnl_pct = round(net_pnl_pct, 4)
                        t.gross_pnl     = round(t.capital_deployed * net_pnl_pct / 100, 2)
                        t.actual_return = round(net_pnl_pct, 4)
                        t.exit_reason   = reason
                        t.is_open       = False
                        t.holding_days  = held_days
                        report["closed"] += 1

                # ── ENTRIES ───────────────────────────────────
                still_open = [t for t in open_trades if t.is_open]
                slots = MAX_OPEN_PER_STRATEGY - len(still_open)
                if slots <= 0 or regime not in regs:
                    continue
                held_syms = {t.symbol for t in still_open}

                # Candidate symbols: liquid universe with features today
                for sym in universe:
                    if slots <= 0:
                        break
                    if sym in held_syms or sym not in closes:
                        continue
                    fv = features.get(sym)
                    if not fv:
                        continue   # fail-closed, same as backtester
                    if entry_conds is not None and not entry_conds.evaluate(fv):
                        continue

                    # Same signal/confidence gate as the backtester
                    hist = (
                        db.query(DailyPrice.close)
                        .filter(DailyPrice.symbol == sym,
                                DailyPrice.date <= today,
                                DailyPrice.close.isnot(None))
                        .order_by(DailyPrice.date.desc())
                        .limit(120)
                        .all()
                    )
                    closes_hist = [r[0] for r in reversed(hist)]
                    if len(closes_hist) < 22:
                        continue
                    sig = _technical_signal(closes_hist)
                    if not _should_enter(sig, regime, "FLAT", conf, regs):
                        continue

                    entry_px = closes[sym] * (1 + NSE_BUY_COST)
                    db.add(PaperTrade(
                        portfolio_name   = pname,
                        symbol           = sym,
                        entry_date       = today,
                        entry_price      = round(entry_px, 4),
                        shares           = round(NOTIONAL_PER_TRADE / entry_px, 4),
                        capital_deployed = NOTIONAL_PER_TRADE,
                        direction        = "Bullish",
                        confidence       = sig.get("confidence", 0.0),
                        is_open          = True,
                        strategy_id      = strat.strategy_id,
                        strategy_name    = strat.name,
                    ))
                    slots -= 1
                    report["opened"] += 1

                db.commit()
            except Exception as exc:
                db.rollback()
                report["errors"].append(f"{strat.strategy_id}: {exc}")

    log.info("Shadow paper cycle %s: strategies=%d opened=%d closed=%d errors=%d",
             report["date"], report["strategies"], report["opened"],
             report["closed"], len(report["errors"]))
    return report
