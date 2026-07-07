"""
GO-1 / GO-7 / GO-8: Go/No-Go Scorecard API
Returns the 5 conditions required before real capital deployment,
quarantine progress for promoted algos, today's actionable signals,
and 30-day pipeline uptime.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from aqrti.database.engine import get_db_dependency
from aqrti.database.models import PaperTrade, StrategyPerformance, StrategyV2, SystemHealthCheck

router = APIRouter()


# ── Helpers ────────────────────────────────────────────────────────────────────

def _trading_days_ago(n: int) -> date:
    """Return the date ~n trading days ago (approx: subtract n*7/5 calendar days, floor)."""
    # Simple approximation — accurate enough for 30-day uptime window
    return date.today() - timedelta(days=int(n * 1.4 + 1))


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/go-nogo", tags=["Go/No-Go"])
def get_go_nogo(db: Session = Depends(get_db_dependency)) -> dict[str, Any]:
    """
    GO-1: 5-condition scorecard before real capital deployment.
    All conditions must be green before trading real money.
    """

    conditions = []

    # ── Condition 1: At least 1 algo promoted through all honest gates ─────────
    promoted_count = (
        db.query(func.count(StrategyV2.id))
        .filter(StrategyV2.status.in_(["promoted", "active"]))
        .scalar()
        or 0
    )
    total_count = db.query(func.count(StrategyV2.id)).scalar() or 0
    cond1_status = "green" if promoted_count >= 1 else "red"
    conditions.append({
        "id": 1,
        "label": "Algo promoted",
        "status": cond1_status,
        "detail": (
            f"{promoted_count} of {total_count} algos promoted through all honest gates"
            if total_count > 0
            else "No algos in population yet"
        ),
    })

    # ── Condition 2: Quarantine complete for at least 1 promoted algo ─────────
    promoted_algos = (
        db.query(StrategyV2)
        .filter(StrategyV2.status.in_(["promoted", "active"]))
        .all()
    )

    quarantine_algos: list[dict] = []
    quarantine_green_count = 0
    quarantine_partial_count = 0

    QUARANTINE_DAYS = 60
    QUARANTINE_TRADES = 20
    QUARANTINE_WR = 0.50

    for algo in promoted_algos:
        now = datetime.utcnow()
        promoted_dt = algo.promoted_at

        # Days in quarantine
        if promoted_dt:
            days_in_q = (now - promoted_dt).days
        else:
            days_in_q = 0

        # Shadow trades (closed paper trades for this strategy).
        # Must match ONLY the strategy's own shadow-runner portfolio
        # ("strat_<id>", written by strategy_shadow_runner.py — the
        # strategy's own DSL exercised forward). Filtering by
        # PaperTrade.strategy_id alone also pulls in "default"-portfolio
        # ML-driven trades (paper_trade.py / continuous_monitor.py) that
        # merely borrow this strategy's SL/TP params — not evidence the
        # strategy's own rules work. See strategies.py's /activate endpoint,
        # which already gates on portfolio_name correctly.
        closed_trades = (
            db.query(PaperTrade)
            .filter(
                PaperTrade.portfolio_name == f"strat_{algo.strategy_id}",
                PaperTrade.is_open == False,  # noqa: E712
            )
            .all()
        )
        shadow_count = len(closed_trades)

        # Win rate and net P&L
        if shadow_count > 0:
            wins = sum(
                1
                for t in closed_trades
                if (t.gross_pnl_pct is not None and t.gross_pnl_pct > 0)
            )
            shadow_wr = wins / shadow_count
            net_pnl = sum(
                (t.gross_pnl or 0.0) for t in closed_trades
            )
        else:
            shadow_wr = 0.0
            net_pnl = 0.0

        days_ok = days_in_q >= QUARANTINE_DAYS
        trades_ok = shadow_count >= QUARANTINE_TRADES
        wr_ok = shadow_wr >= QUARANTINE_WR
        pnl_ok = net_pnl > 0
        quarantine_ok = days_ok and trades_ok and wr_ok and pnl_ok

        if quarantine_ok:
            quarantine_green_count += 1
        else:
            quarantine_partial_count += 1

        quarantine_algos.append({
            "strategy_id": algo.strategy_id,
            "name": algo.name or algo.strategy_id,
            "days_in_quarantine": days_in_q,
            "shadow_trades": shadow_count,
            "shadow_wr": round(shadow_wr * 100, 1),
            "net_pnl": round(net_pnl, 2),
            "quarantine_ok": quarantine_ok,
            "gates": {
                "days_60": days_ok,
                "trades_20": trades_ok,
                "wr_50pct": wr_ok,
                "positive_pnl": pnl_ok,
            },
        })

    if len(promoted_algos) == 0:
        cond2_status = "red"
        cond2_detail = "No promoted algos yet — quarantine clock hasn't started"
    elif quarantine_green_count >= 1:
        cond2_status = "green"
        cond2_detail = (
            f"{quarantine_green_count} algo(s) completed quarantine "
            f"(>=60 days, >=20 shadow trades, >=50% WR, positive P&L)"
        )
    else:
        cond2_status = "partial"
        cond2_detail = (
            f"{len(promoted_algos)} algo(s) in quarantine — "
            f"none completed all 4 gates yet"
        )

    conditions.append({
        "id": 2,
        "label": "Quarantine complete",
        "status": cond2_status,
        "detail": cond2_detail,
    })

    # ── Condition 3: 30-day uptime (pipeline self-check green runs) ───────────
    cutoff_dt = datetime.utcnow() - timedelta(days=45)  # 45 calendar days covers ~30 trading
    health_rows = (
        db.query(SystemHealthCheck)
        .filter(SystemHealthCheck.checked_at >= cutoff_dt)
        .order_by(SystemHealthCheck.checked_at.desc())
        .limit(35)
        .all()
    )
    total_checks = len(health_rows)
    green_checks = sum(1 for r in health_rows if r.overall_ok)

    # Find earliest check date to report
    earliest_check: str | None = None
    if health_rows:
        earliest = min(r.checked_at for r in health_rows)
        earliest_check = earliest.strftime("%Y-%m-%d")

    if green_checks >= 20:
        cond3_status = "green"
        cond3_detail = (
            f"{green_checks}/{total_checks} health checks green in the last ~30 trading days"
        )
    elif green_checks >= 10:
        cond3_status = "partial"
        cond3_detail = (
            f"{green_checks}/{total_checks} health checks green — "
            f"need >=20 green for full confidence"
        )
    elif total_checks == 0:
        cond3_status = "red"
        cond3_detail = "No health check runs recorded yet — pipeline watchdog not running"
    else:
        cond3_status = "red"
        cond3_detail = (
            f"Only {green_checks}/{total_checks} health checks green "
            f"(since {earliest_check}) — pipeline reliability too low"
        )

    conditions.append({
        "id": 3,
        "label": "30-day uptime",
        "status": cond3_status,
        "detail": cond3_detail,
    })

    # ── Condition 4: Morning workflow rehearsed >=2 weeks (manual) ────────────
    conditions.append({
        "id": 4,
        "label": "Workflow rehearsed",
        "status": "red",
        "detail": "Mark manually when 2-week morning rehearsal is complete",
    })

    # ── Condition 5: First capital capped at Rs 5,000 ─────────────────────────
    conditions.append({
        "id": 5,
        "label": "Capital cap set",
        "status": "green",
        "detail": "Rs 5,000 cap per ROAD_TO_REAL.md — enforce manually at first real trade",
    })

    # ── Overall status ─────────────────────────────────────────────────────────
    statuses = [c["status"] for c in conditions]
    if all(s == "green" for s in statuses):
        overall = "green"
    elif any(s == "green" for s in statuses):
        overall = "partial"
    else:
        overall = "red"

    # ── Actionable signals: open paper trades on promoted/active algos ────────
    promoted_ids = [a.strategy_id for a in promoted_algos]
    actionable_signals: list[dict] = []

    if promoted_ids:
        open_trades = (
            db.query(PaperTrade)
            .filter(
                PaperTrade.strategy_id.in_(promoted_ids),
                PaperTrade.is_open == True,  # noqa: E712
            )
            .order_by(PaperTrade.entry_date.desc())
            .limit(5)
            .all()
        )
        # Build a lookup of strategy_id -> name
        algo_names = {a.strategy_id: (a.name or a.strategy_id) for a in promoted_algos}
        for t in open_trades:
            actionable_signals.append({
                "strategy_id": t.strategy_id,
                "algo_name": algo_names.get(t.strategy_id, t.strategy_name or t.strategy_id),
                "symbol": t.symbol,
                "entry_date": str(t.entry_date) if t.entry_date else None,
                "entry_price": t.entry_price,
                "current_pnl_pct": round(t.gross_pnl_pct or 0.0, 2),
                "direction": t.direction,
            })

    return {
        "overall": overall,
        "conditions": conditions,
        "actionable_signals": actionable_signals,
        "quarantine_algos": quarantine_algos,
    }


@router.get("/go-nogo/risk-rails", tags=["Go/No-Go"])
def get_risk_rails() -> dict:
    """
    GO-10: Real-capital risk rails — the non-negotiable rules for first real money.
    Rendered on the Go/No-Go page so the rules are visible at decision time.
    These are process rules, not code enforcement.
    """
    return {
        "rules": [
            {
                "id": 1,
                "rule": "Starting capital: Rs 5,000 maximum",
                "detail": "First real position must not exceed Rs 5,000 total. A total loss is tuition, not disaster. Scale only after 3 months of reconciled real fills.",
            },
            {
                "id": 2,
                "rule": "One algo only at first",
                "detail": "Only the single best-scoring promoted algo that passed quarantine gets real capital. No diversification until the first algo's assumptions are proven in real fills.",
            },
            {
                "id": 3,
                "rule": "Position cap: Rs 1,000 per trade",
                "detail": "Size each position per the algo's DSL, but hard-cap at Rs 1,000 regardless. No exceptions.",
            },
            {
                "id": 4,
                "rule": "Hard stop: -10% real drawdown = halt",
                "detail": "If cumulative real P&L hits -10% of starting capital (i.e. -Rs 500), stop immediately. Write a post-mortem. Return to paper-only mode. Do not add capital to recover.",
            },
            {
                "id": 5,
                "rule": "Scaling rule: 2x max per quarter, never on a drawdown month",
                "detail": "After 3 months of real fills reconciling with paper assumptions within tolerance: may double capital once per quarter. Never scale up in a month where real P&L is negative.",
            },
        ],
        "note": "These rules are enforced manually by the user — AQRTI never executes real trades. Review them every session before acting on any signal.",
    }


@router.get("/go-nogo/uptime-log", tags=["Go/No-Go"])
def get_uptime_log(db: Session = Depends(get_db_dependency)) -> list[dict]:
    """
    Return the last 30 SystemHealthCheck rows for the 30-day uptime dot chart.
    """
    cutoff_dt = datetime.utcnow() - timedelta(days=50)  # wider window to get 30 rows
    rows = (
        db.query(SystemHealthCheck)
        .filter(SystemHealthCheck.checked_at >= cutoff_dt)
        .order_by(SystemHealthCheck.checked_at.desc())
        .limit(30)
        .all()
    )
    return [
        {
            "checked_at": r.checked_at.isoformat() if r.checked_at else None,
            "overall_ok": r.overall_ok,
            "failures": r.failures or "",
        }
        for r in rows
    ]


@router.get("/go-nogo/monthly-review", tags=["Go/No-Go"])
def get_monthly_review(db: Session = Depends(get_db_dependency)) -> dict[str, Any]:
    """
    GO-11: Monthly review report data.
    Returns live vs backtest comparison per promoted algo, cost reconciliation placeholder,
    and a summary of the last 30 days of shadow trading activity.
    """
    today = date.today()
    month_ago = today - timedelta(days=30)

    promoted_algos = (
        db.query(StrategyV2)
        .filter(StrategyV2.status.in_(["promoted", "active"]))
        .all()
    )

    algo_reviews: list[dict] = []

    for algo in promoted_algos:
        # Closed shadow trades in the last 30 days. Must match ONLY the
        # strategy's own shadow-runner portfolio ("strat_<id>") — filtering
        # by PaperTrade.strategy_id alone also pulls in "default"-portfolio
        # ML-driven trades that merely borrow this strategy's SL/TP params,
        # which is not "shadow trading activity" as this report claims.
        recent_trades = (
            db.query(PaperTrade)
            .filter(
                PaperTrade.portfolio_name == f"strat_{algo.strategy_id}",
                PaperTrade.is_open == False,  # noqa: E712
                PaperTrade.exit_date >= month_ago,
            )
            .all()
        )

        trade_count = len(recent_trades)
        if trade_count > 0:
            wins = sum(1 for t in recent_trades if (t.gross_pnl_pct or 0) > 0)
            live_wr = wins / trade_count
            live_net_pnl = sum(t.gross_pnl or 0.0 for t in recent_trades)
            avg_return = sum(t.gross_pnl_pct or 0.0 for t in recent_trades) / trade_count
        else:
            live_wr = None
            live_net_pnl = 0.0
            avg_return = None

        algo_reviews.append({
            "strategy_id": algo.strategy_id,
            "name": algo.name or algo.strategy_id,
            "backtest_sharpe": algo.sharpe,
            "backtest_win_rate": algo.win_rate,
            "backtest_trade_count": algo.trade_count,
            "live_30d_trades": trade_count,
            "live_30d_win_rate": round(live_wr * 100, 1) if live_wr is not None else None,
            "live_30d_avg_return_pct": round(avg_return, 3) if avg_return is not None else None,
            "live_30d_net_pnl": round(live_net_pnl, 2),
            "wr_vs_backtest_pp": (
                round((live_wr - (algo.win_rate or 0)) * 100, 1)
                if live_wr is not None and algo.win_rate is not None
                else None
            ),
        })

    # Uptime summary for the month
    month_health = (
        db.query(SystemHealthCheck)
        .filter(SystemHealthCheck.checked_at >= datetime.utcnow() - timedelta(days=32))
        .all()
    )
    health_total = len(month_health)
    health_green = sum(1 for r in month_health if r.overall_ok)

    return {
        "report_date": today.isoformat(),
        "month_start": month_ago.isoformat(),
        "promoted_algo_count": len(promoted_algos),
        "algo_reviews": algo_reviews,
        "uptime": {
            "checks_total": health_total,
            "checks_green": health_green,
            "uptime_pct": round(100 * health_green / health_total, 1) if health_total > 0 else None,
        },
        "cost_reconciliation": {
            "note": "Manual — compare real fill prices against backtester's 0.28% round-trip assumption when first real trade is recorded.",
            "modeled_cost_pct": 0.28,
            "real_cost_pct": None,
        },
        "no_data": len(promoted_algos) == 0,
        "empty_reason": "No promoted algos yet — monthly review will populate once an algo passes all gates and completes quarantine." if len(promoted_algos) == 0 else None,
    }
