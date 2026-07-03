"""
Paper Portfolio API
GET /api/v1/paper-portfolio                         — portfolio summary + open positions
GET /api/v1/paper-portfolio/positions               — open positions with live P&L
GET /api/v1/paper-portfolio/allocation              — current allocation view
GET /api/v1/paper-portfolio/export/tradingview      — Pine Script for TradingView paper trading
GET /api/v1/paper-portfolio/export/csv              — CSV of all open positions with SL/TP
"""

from __future__ import annotations

import sys
import os

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from aqrti.database.engine import get_db_dependency
from aqrti.utils.logger import get_logger

log    = APIRouter()
router = log  # alias — FastAPI uses router


def _ensure_path():
    backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)


@router.get("")
def get_paper_portfolio(db: Session = Depends(get_db_dependency)):
    _ensure_path()
    from paper_trading.paper_portfolio import get_portfolio_summary
    from paper_trading.paper_trade import get_open_positions
    from paper_trading.performance_tracker import get_latest_snapshot

    summary   = get_portfolio_summary(db)
    positions = get_open_positions(db)
    snap      = get_latest_snapshot(db)

    return {
        "portfolio":  summary,
        "positions":  positions,
        "performance": snap or {},
        "available":  True,
    }


@router.get("/positions")
def get_positions(db: Session = Depends(get_db_dependency)):
    _ensure_path()
    from paper_trading.paper_trade import get_open_positions
    return get_open_positions(db)


@router.get("/equity-curve")
def get_equity_curve_endpoint(
    days: int = Query(default=90, ge=7, le=365),
    db:   Session = Depends(get_db_dependency),
):
    """
    Return equity curve.  If EquityCurvePoint has fewer than 3 rows,
    reconstruct a synthetic curve from paper trade history so the
    chart always shows something meaningful.
    """
    _ensure_path()
    from paper_trading.performance_tracker import get_equity_curve_data
    from aqrti.database.models import EquityCurvePoint, PaperTrade, PaperPortfolio
    from aqrti.config.settings import get_settings
    from datetime import date, timedelta
    from collections import defaultdict

    data = get_equity_curve_data(db, days=days)
    if len(data.get("labels", [])) >= 3:
        return data

    # ── Synthetic reconstruction from paper trade history ──────────
    settings  = get_settings()
    paper     = db.query(PaperPortfolio).filter_by(portfolio_name="default").first()
    capital   = paper.initial_capital if paper else settings.paper_capital
    end_val   = paper.total_value if paper else capital

    trades = (
        db.query(PaperTrade)
        .filter(PaperTrade.portfolio_name == "default")
        .all()
    )
    if not trades:
        return data  # nothing to reconstruct from

    # Build daily net PnL from closed trades
    daily_pnl: dict = defaultdict(float)
    for t in trades:
        if not t.is_open and t.gross_pnl and t.exit_date:
            daily_pnl[str(t.exit_date)] += t.gross_pnl

    sorted_dates = sorted(daily_pnl.keys())
    if not sorted_dates:
        return data

    # Walk forward from capital, filling every calendar day
    cutoff    = date.today() - timedelta(days=days)
    running   = capital
    labels, values, drawdown_vals, daily_ret_vals = [], [], [], []
    peak      = capital

    # Start one day before first trade date
    first_trade_d = date.fromisoformat(sorted_dates[0])
    start_d = max(cutoff, first_trade_d - timedelta(days=1))
    cur_d   = start_d

    while cur_d <= date.today():
        pnl   = daily_pnl.get(str(cur_d), 0.0)
        prev  = running
        running += pnl
        daily_r = (running - prev) / prev * 100 if prev else 0.0
        peak    = max(peak, running)
        dd      = (running - peak) / peak * 100 if peak else 0.0

        labels.append(str(cur_d))
        values.append(round(running, 2))
        drawdown_vals.append(round(dd, 4))
        daily_ret_vals.append(round(daily_r, 4))
        cur_d += timedelta(days=1)

    return {
        "labels":       labels,
        "values":       values,
        "drawdown":     drawdown_vals,
        "dailyReturns": daily_ret_vals,
        "cash":         [],
        "source":       "reconstructed",
    }


@router.post("/backtest")
def run_historical_backtest(
    strategy_id: str | None = None,
    years: int = 2,
    db: Session = Depends(get_db_dependency),
):
    """
    Run a 2-year historical backtest for a strategy using the Arena replay engine.
    If strategy_id is omitted, uses the highest-fitness active strategy.
    Runs in a background thread — returns immediately with thread name.
    """
    import threading
    _ensure_path()
    from aqrti.database.models import StrategyV2

    if strategy_id:
        strat = db.query(StrategyV2).filter_by(strategy_id=strategy_id).first()
    else:
        # Prefer an arena champion among human-approved active strategies;
        # "champion" now lives in arena_status, not status (status="champion"
        # was removed 2026-07-03 to stop the arena silently colliding with
        # strategy_lifecycle.py's state machine — see arena/arena_engine.py).
        strat = db.query(StrategyV2).filter(
            StrategyV2.status == "active",
            StrategyV2.arena_status == "champion",
            StrategyV2.fitness_score.isnot(None),
            StrategyV2.dsl_json.isnot(None),
        ).order_by(StrategyV2.fitness_score.desc()).first()
        if not strat:
            strat = db.query(StrategyV2).filter(
                StrategyV2.status == "active",
                StrategyV2.fitness_score.isnot(None),
                StrategyV2.dsl_json.isnot(None),
            ).order_by(StrategyV2.fitness_score.desc()).first()

    if not strat:
        return {"status": "no_strategy", "message": "No active strategy found to backtest"}

    sid   = strat.strategy_id
    sname = strat.name

    def _worker():
        from aqrti.database.engine import get_db as _get_db
        from arena.replay_engine import run_replay
        import sys, os
        backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        if backend_dir not in sys.path:
            sys.path.insert(0, backend_dir)
        try:
            with _get_db() as _db:
                s = _db.query(StrategyV2).filter_by(strategy_id=sid).first()
                if s:
                    result = run_replay(_db, s, years=years, fresh=True)
                    log.info("Backtest done: %s return=%.1f%% trades=%d",
                             sname, result.get("total_return_pct", 0), result.get("total_trades", 0))
        except Exception as exc:
            log.error("Backtest failed for %s: %s", sname, exc)

    t = threading.Thread(target=_worker, daemon=True, name=f"backtest-{sid[:8]}")
    t.start()

    return {
        "status":      "started",
        "strategy_id": sid,
        "strategy_name": sname,
        "years":       years,
        "portfolio":   f"arena_{sid}",
        "message":     f"Backtest running in background — results appear in arena_{sid} portfolio",
        "thread":      t.name,
    }


@router.get("/backtest/status")
def backtest_status(strategy_id: str | None = None, db: Session = Depends(get_db_dependency)):
    """
    Return backtest results for a strategy (from ArenaRun table).
    If strategy_id omitted, returns top champion or latest run.
    """
    try:
        from aqrti.database.models import ArenaRun, StrategyV2, PaperPortfolio, EquityCurvePoint

        if strategy_id:
            run = db.query(ArenaRun).filter_by(strategy_id=strategy_id).order_by(
                ArenaRun.round_number.desc()).first()
        else:
            run = db.query(ArenaRun).filter(
                ArenaRun.total_return_pct.isnot(None)
            ).order_by(ArenaRun.total_return_pct.desc()).first()

        if not run:
            return {"available": False, "message": "No backtest results yet — trigger one first"}

        portfolio_name = f"arena_{run.strategy_id}"
        portfolio = db.query(PaperPortfolio).filter_by(portfolio_name=portfolio_name).first()
        ec_count  = db.query(EquityCurvePoint).filter_by(portfolio_name=portfolio_name).count()

        return {
            "available":        True,
            "strategy_id":      run.strategy_id,
            "strategy_name":    run.strategy_name,
            "total_return_pct": run.total_return_pct,
            "max_drawdown_pct": run.max_drawdown_pct,
            "win_rate":         run.win_rate,
            "total_trades":     run.total_trades,
            "is_champion":      run.is_champion,
            "status":           run.status,
            "round":            run.round_number,
            "equity_days":      ec_count,
            "completed_at":     str(run.completed_at) if run.completed_at else None,
            "portfolio_value":  portfolio.total_value if portfolio else None,
        }
    except Exception as exc:
        return {"available": False, "error": str(exc)}


@router.post("/backfill-equity")
def backfill_equity_curve(db: Session = Depends(get_db_dependency)):
    """
    One-time backfill: create EquityCurvePoint rows from paper trade history
    so performance_tracker has real historical data to compute metrics from.
    """
    _ensure_path()
    from aqrti.database.models import EquityCurvePoint, PaperTrade, PaperPortfolio
    from aqrti.config.settings import get_settings
    from datetime import date, timedelta
    from collections import defaultdict

    settings = get_settings()
    paper    = db.query(PaperPortfolio).filter_by(portfolio_name="default").first()
    capital  = paper.initial_capital if paper else settings.paper_capital

    trades = (
        db.query(PaperTrade)
        .filter(PaperTrade.portfolio_name == "default")
        .all()
    )
    if not trades:
        return {"message": "No paper trades found — nothing to backfill", "inserted": 0}

    daily_pnl: dict = defaultdict(float)
    for t in trades:
        if not t.is_open and t.gross_pnl and t.exit_date:
            daily_pnl[str(t.exit_date)] += t.gross_pnl

    if not daily_pnl:
        return {"message": "No closed trades with P&L — nothing to backfill", "inserted": 0}

    sorted_dates = sorted(daily_pnl.keys())
    first_d = date.fromisoformat(sorted_dates[0])
    start_d = first_d - timedelta(days=1)

    running  = capital
    peak     = capital
    inserted = 0

    cur_d = start_d
    while cur_d <= date.today():
        existing = (
            db.query(EquityCurvePoint)
            .filter_by(portfolio_name="default", date=cur_d)
            .first()
        )
        if not existing:
            pnl     = daily_pnl.get(str(cur_d), 0.0)
            prev    = running
            running += pnl
            daily_r = (running - prev) / prev * 100 if prev else 0.0
            peak    = max(peak, running)
            dd      = (running - peak) / peak * 100 if peak else 0.0
            cum_r   = (running - capital) / capital * 100 if capital else 0.0

            db.add(EquityCurvePoint(
                portfolio_name        = "default",
                date                  = cur_d,
                total_value           = round(running, 2),
                cash                  = round(running, 2),
                invested              = 0.0,
                daily_return_pct      = round(daily_r, 6),
                cumulative_return_pct = round(cum_r, 6),
                drawdown_pct          = round(dd, 6),
                open_positions        = 0,
                nifty_close           = None,
            ))
            inserted += 1
        else:
            pnl     = daily_pnl.get(str(cur_d), 0.0)
            running += pnl
            peak    = max(peak, running)

        cur_d += timedelta(days=1)

    db.commit()
    return {"message": f"Backfilled {inserted} equity curve points", "inserted": inserted}


@router.get("/allocation")
def get_allocation(
    method:  str = Query(default="confidence_weighted"),
    db: Session = Depends(get_db_dependency),
):
    _ensure_path()
    from portfolio.portfolio_builder import get_allocation_view
    return get_allocation_view(db, method=method)


@router.get("/export/tradingview")
def export_tradingview(db: Session = Depends(get_db_dependency)):
    """
    Generate a TradingView Pine Script v5 that replicates all open paper positions.
    Each position becomes a strategy.entry() + strategy.exit() with SL and TP.
    Returns the .pine file as a downloadable attachment.
    """
    from fastapi.responses import Response
    from datetime import date as _date
    _ensure_path()
    from paper_trading.paper_trade import get_open_positions

    positions = get_open_positions(db)

    lines = [
        '//@version=5',
        f'// AQRTI Paper Portfolio Export — {_date.today()}',
        f'// {len(positions)} open position(s)',
        '// Paste this into TradingView Pine Editor → Add to chart → use Paper Trading mode',
        '',
        'strategy("AQRTI Paper Portfolio", overlay=true, default_qty_type=strategy.fixed,',
        '         initial_capital=1000000, commission_type=strategy.commission.percent,',
        '         commission_value=0.05, slippage=2)',
        '',
        '// ── Position entries (date-triggered, one candle window) ──',
    ]

    for i, p in enumerate(positions):
        sym    = p["symbol"]
        entry  = p["entryPrice"]
        sl     = p["stopLoss"]
        tp     = p["target"]
        shares = p["shares"]
        edate  = p["entryDate"]          # "YYYY-MM-DD"
        strat  = (p.get("strategyName") or p.get("strategyId") or f"pos{i+1}").replace('"', '')
        conf   = p.get("confidence", 0)
        dirc   = p.get("direction", "Bullish")

        # Convert entry date to timestamp check
        try:
            y, mo, d = edate.split("-")
            date_check = f'year == {y} and month == {mo} and dayofmonth == {d}'
        except Exception:
            date_check = f'bar_index == {i}'

        sl_pct  = round(abs(entry - sl) / entry * 100, 2) if entry else 8.0
        tp_pct  = round(abs(tp - entry) / entry * 100, 2) if entry else 15.0

        lines += [
            '',
            f'// ── {sym} | {strat} | conf={conf}% | {dirc} ──',
            f'// Entry: ₹{entry}  |  SL: ₹{sl} (-{sl_pct}%)  |  TP: ₹{tp} (+{tp_pct}%)',
            f'if ({date_check})',
            f'    strategy.entry("NSE:{sym}_{i+1}", strategy.long, qty={int(max(shares, 1))},',
            f'                   limit={entry}, comment="{strat[:40]}")',
            f'    strategy.exit("NSE:{sym}_{i+1}_exit", from_entry="NSE:{sym}_{i+1}",',
            f'                  stop={sl}, limit={tp})',
        ]

    pine_script = "\n".join(lines)

    return Response(
        content=pine_script,
        media_type="text/plain",
        headers={
            "Content-Disposition": f'attachment; filename="aqrti_paper_portfolio_{_date.today()}.pine"',
            "Access-Control-Expose-Headers": "Content-Disposition",
        },
    )


@router.get("/export/csv")
def export_csv(
    include_closed: bool = Query(default=True),
    days: int = Query(default=90, ge=1, le=365),
    db: Session = Depends(get_db_dependency),
):
    """
    Export trades in TradingView paper trading import format.
    Columns: Symbol, Side, Qty, Fill Price, Commission, Closing Time
    Open positions  → Buy row only (no Closing Time)
    Closed trades   → Buy row + Sell row
    Symbol format   → NSE:TICKER
    """
    from fastapi.responses import Response
    from datetime import date as _date, timedelta
    import csv, io
    _ensure_path()
    from paper_trading.paper_trade import get_open_positions, get_trade_history
    from aqrti.database.models import PaperPosition, PaperTrade

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Symbol", "Side", "Qty", "Fill Price", "Commission", "Closing Time"])

    # ── Open positions → Buy rows (no closing time = still open) ──
    positions = get_open_positions(db)
    for p in positions:
        sym  = f"NSE:{p['symbol']}"
        qty  = max(1, int(round(p["shares"])))
        writer.writerow([sym, "Buy", qty, p["entryPrice"], "", p["entryDate"] + " 9:15:00"])

    # ── Closed trades → Buy + Sell row pairs ──
    if include_closed:
        cutoff = _date.today() - timedelta(days=days)
        trades = get_trade_history(db, limit=500)
        for t in trades:
            try:
                if t.get("entryDate") and _date.fromisoformat(t["entryDate"]) < cutoff:
                    continue
            except Exception:
                pass
            sym  = f"NSE:{t['symbol']}"
            qty  = max(1, int(round(t["shares"])))
            entry_time = (t.get("entryDate") or str(_date.today())) + " 9:15:00"
            exit_time  = (t.get("exitDate")  or str(_date.today())) + " 15:30:00"
            writer.writerow([sym, "Buy",  qty, t["entryPrice"],            "", entry_time])
            writer.writerow([sym, "Sell", qty, t.get("exitPrice") or t["entryPrice"], "", exit_time])

    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="aqrti_tradingview_{_date.today()}.csv"',
            "Access-Control-Expose-Headers": "Content-Disposition",
        },
    )
