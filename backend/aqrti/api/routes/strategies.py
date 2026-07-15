"""Strategy API — /api/v1/strategies (Phase 6 — StrategyV2)"""

from __future__ import annotations

import sys, os, json

backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from fastapi import APIRouter, BackgroundTasks, Depends, Query, HTTPException
from sqlalchemy.orm import Session

from aqrti.database.engine import get_db_dependency
from aqrti.database.models import (
    StrategyV2, StrategyVersion, StrategyEvolutionHistory, StrategyBacktestTrade,
)
from strategies.strategy_store import (
    get_strategy, list_strategies, get_population_stats,
)
from strategies.strategy_registry import (
    get_leaderboard, get_family_summary, count_by_generation,
)
from strategies.strategy_lifecycle import (
    promote_strategy, retire_strategy, run_lifecycle_sweep,
)
from strategies.strategy_generator import run_generation_cycle
from strategies.evolution_engine import evolve_population

router = APIRouter()


def _safe_json(s):
    try:
        return json.loads(s) if s else None
    except Exception:
        return s


def _quarantine_status(db: Session, row: StrategyV2) -> dict | None:
    """
    Progress toward the paper-trading quarantine gate that /activate enforces
    (see promotion_config.QUARANTINE_*). Only meaningful for 'promoted'
    strategies — 'active' ones already cleared it (or were force-approved).
    """
    if row.status != "promoted":
        return None
    from datetime import datetime as _dt
    from aqrti.database.models import PaperTrade
    from strategies.promotion_config import (
        QUARANTINE_MIN_DAYS, QUARANTINE_MIN_TRADES, QUARANTINE_MIN_WIN_RATE,
        is_expectancy_gated,
    )
    days_promoted = (_dt.utcnow() - row.promoted_at).days if row.promoted_at else 0
    closed = (
        db.query(PaperTrade)
        .filter(PaperTrade.portfolio_name == f"strat_{row.strategy_id}",
                PaperTrade.is_open == False)
        .all()
    )
    n = len(closed)
    wins = sum(1 for t in closed if (t.gross_pnl_pct or 0) > 0)
    wr = wins / n * 100 if n else 0.0
    net_pnl = sum(t.gross_pnl or 0 for t in closed)
    # Expectancy-gated families (promotion_config, user decision 2026-07-14)
    # are held to live profitability instead of the WR floor in quarantine —
    # a 43% WR family would otherwise be structurally unable to ever clear
    # quarantine despite being promoted under the expectancy standard. The
    # net_pnl > 0 requirement below still applies to them unchanged.
    wr_gate_ok = True if is_expectancy_gated(row.family) else (n == 0 or wr >= QUARANTINE_MIN_WIN_RATE)
    ready = (
        days_promoted >= QUARANTINE_MIN_DAYS
        and n >= QUARANTINE_MIN_TRADES
        and wr_gate_ok
        and (n == 0 or net_pnl > 0)
    )
    return {
        "days_promoted":   days_promoted,
        "days_required":   QUARANTINE_MIN_DAYS,
        "shadow_trades":   n,
        "trades_required": QUARANTINE_MIN_TRADES,
        "shadow_win_rate": round(wr, 1),
        "win_rate_required": QUARANTINE_MIN_WIN_RATE,
        "shadow_net_pnl":  round(net_pnl, 2),
        "ready_for_activation": ready,
    }


@router.get("")
def get_strategies(
    status:   str | None = Query(default=None),
    family:   str | None = Query(default=None),
    limit:    int        = Query(default=50, ge=1, le=200),
    order_by: str        = Query(default="fitness"),
    db: Session = Depends(get_db_dependency),
):
    rows = list_strategies(db, status=status, family=family, limit=limit, order_by=order_by)
    return {
        "strategies": [
            {
                "strategy_id":    r.strategy_id,
                "name":           r.name,
                "family":         r.family,
                "generation":     r.generation,
                "status":         r.status,
                "fitness_score":  r.fitness_score,
                "sharpe":         r.sharpe,
                "win_rate":       r.win_rate,
                "profit_factor":  r.profit_factor,
                "max_drawdown":   r.max_drawdown,
                "trade_count":    r.trade_count,
                "oos_sharpe":     r.oos_sharpe,
                "oos_win_rate":   r.oos_win_rate,
                "oos_trades":     r.oos_trades,
                "oos_passed":     r.oos_passed,
                "allowed_regimes": _safe_json(r.allowed_regimes),
                "created_at":     r.created_at.isoformat() if r.created_at else None,
                "promoted_at":    r.promoted_at.isoformat() if r.promoted_at else None,
                "quarantine":     _quarantine_status(db, r),
            }
            for r in rows
        ],
        "total": len(rows),
    }


@router.get("/population")
def get_population(db: Session = Depends(get_db_dependency)):
    return {
        "stats":         get_population_stats(db),
        "by_family":     get_family_summary(db),
        "by_generation": count_by_generation(db),
        "leaderboard":   get_leaderboard(db, top_n=10),
    }


@router.get("/leaderboard")
def get_leaderboard_endpoint(
    top_n:  int        = Query(default=20, ge=5, le=100),
    status: str | None = Query(default=None),
    db: Session = Depends(get_db_dependency),
):
    return {"leaderboard": get_leaderboard(db, top_n=top_n, status=status)}


@router.get("/stats")
def get_strategy_stats(db: Session = Depends(get_db_dependency)):
    """Aggregate stats used by frontend dashboard cards."""
    total    = db.query(StrategyV2).count()
    promoted = db.query(StrategyV2).filter(StrategyV2.status == "promoted").count()
    active   = db.query(StrategyV2).filter(StrategyV2.status == "active").count()
    shadow   = db.query(StrategyV2).filter(StrategyV2.status == "shadow").count()
    retired  = db.query(StrategyV2).filter(StrategyV2.status == "retired").count()
    families = db.query(StrategyV2.family).distinct().count()

    top = (
        db.query(StrategyV2)
        .filter(StrategyV2.fitness_score != None)
        .order_by(StrategyV2.fitness_score.desc())
        .first()
    )
    from sqlalchemy import func as _func
    avg_fitness_row = db.query(_func.avg(StrategyV2.fitness_score)).filter(
        StrategyV2.fitness_score != None
    ).scalar()
    avg_fitness = round(float(avg_fitness_row), 2) if avg_fitness_row else 0.0

    return {
        "total":       total,
        "promoted":    promoted,
        "active":      active,
        "shadow":      shadow,
        "retired":     retired,
        "families":    families,
        "avgFitness":  avg_fitness,
        "topStrategy": {
            "id":      top.strategy_id,
            "name":    top.name,
            "fitness": top.fitness_score,
            "sharpe":  top.sharpe,
            "winRate": top.win_rate,
        } if top else None,
    }


@router.get("/recommendations")
def get_trade_recommendations(db: Session = Depends(get_db_dependency)):
    """
    Real-world actionable trade recommendations.
    Combines: top promoted strategy, current regime, today's ML predictions.
    Returns up to 5 specific trades with entry price, stop-loss, target, and position size.
    """
    from aqrti.database.models import (
        MarketRegime, Prediction, DailyPrice, Stock,
    )
    from sqlalchemy import func as _func

    # Current market regime
    regime_row = (
        db.query(MarketRegime.regime, MarketRegime.date)
        .order_by(MarketRegime.date.desc())
        .first()
    )
    current_regime = regime_row[0] if regime_row else "BULL"
    regime_date    = str(regime_row[1]) if regime_row else None

    # Best promoted strategy (allowed in current regime)
    top_strategy = (
        db.query(StrategyV2)
        .filter(
            StrategyV2.status == "promoted",
            StrategyV2.fitness_score != None,
        )
        .order_by(StrategyV2.fitness_score.desc())
        .first()
    )

    # Latest ML predictions — Bullish, high confidence
    from datetime import date as _date, timedelta as _td
    cutoff = _date.today() - _td(days=3)
    predictions = (
        db.query(Prediction)
        .filter(
            Prediction.direction == "Bullish",
            Prediction.confidence >= 55.0,
            Prediction.date >= cutoff,
        )
        .order_by(Prediction.confidence.desc(), Prediction.expected_return.desc())
        .limit(20)
        .all()
    )

    # Build symbol → latest price map
    symbols = list({p.symbol for p in predictions})
    price_rows = (
        db.query(DailyPrice.symbol, DailyPrice.close, DailyPrice.date)
        .filter(DailyPrice.symbol.in_(symbols))
        .order_by(DailyPrice.symbol, DailyPrice.date.desc())
        .all()
    )
    price_map: dict = {}
    for pr in price_rows:
        if pr.symbol not in price_map:
            price_map[pr.symbol] = {"close": pr.close, "date": str(pr.date)}

    # Stock sector map
    sector_rows = db.query(Stock.symbol, Stock.sector).filter(Stock.symbol.in_(symbols)).all()
    sector_map = {r.symbol: r.sector for r in sector_rows}

    # Regime-specific stop/target from top strategy DSL
    strategy_dsl = {}
    stop_pct   = 5.0   # default 5% stop
    target_pct = 10.0  # default 10% target
    if top_strategy:
        strategy_dsl = _safe_json(top_strategy.dsl_json) or {}
        if isinstance(strategy_dsl, dict):
            stop_pct   = abs(strategy_dsl.get("stop_loss_pct",   -stop_pct))
            target_pct = strategy_dsl.get("take_profit_pct", target_pct)

    # Position sizing: use 5% of portfolio per trade, max 8 open positions
    POSITION_SIZE_PCT = 5.0

    recs = []
    for p in predictions:
        price_info = price_map.get(p.symbol)
        if not price_info or not price_info["close"]:
            continue
        price      = float(price_info["close"])
        stop_price = round(price * (1 - stop_pct / 100), 2)
        target_price = round(price * (1 + target_pct / 100), 2)
        # Use expected_return if larger than default target
        if p.expected_return and p.expected_return > target_pct:
            target_price = round(price * (1 + p.expected_return / 100), 2)

        rr_ratio = round((target_price - price) / (price - stop_price), 2) if price > stop_price else 0.0

        recs.append({
            "symbol":         p.symbol,
            "sector":         sector_map.get(p.symbol, "—"),
            "currentPrice":   price,
            "priceDate":      price_info["date"],
            "direction":      p.direction,
            "confidence":     round(p.confidence or 0, 1),
            "expectedReturn": round(p.expected_return or 0, 2),
            "entryPrice":     price,
            "stopLoss":       stop_price,
            "target":         target_price,
            "stopPct":        round(stop_pct, 1),
            "targetPct":      round((target_price - price) / price * 100, 1),
            "rrRatio":        rr_ratio,
            "positionSizePct": POSITION_SIZE_PCT,
            "regime":         current_regime,
            "strategyId":     top_strategy.strategy_id if top_strategy else None,
            "strategyName":   top_strategy.name if top_strategy else None,
            "predictionDate": str(p.date) if p.date else None,
        })
        if len(recs) >= 5:
            break

    return {
        "recommendations":  recs,
        "currentRegime":    current_regime,
        "regimeDate":       regime_date,
        "topStrategy": {
            "id":      top_strategy.strategy_id,
            "name":    top_strategy.name,
            "fitness": top_strategy.fitness_score,
            "winRate": top_strategy.win_rate,
            "sharpe":  top_strategy.sharpe,
        } if top_strategy else None,
        "positionSizePct": POSITION_SIZE_PCT,
        "maxPositions":    8,
        "totalRecommendations": len(recs),
    }


RESERVED_IDS = {"all", "ALL", "All"}


@router.get("/{strategy_id}")
def get_strategy_detail(strategy_id: str, db: Session = Depends(get_db_dependency)):
    if strategy_id in RESERVED_IDS:
        raise HTTPException(status_code=400, detail="'All' is reserved — use GET /strategies without an ID to list all")
    row = get_strategy(db, strategy_id)
    if not row:
        raise HTTPException(status_code=404, detail="Strategy not found")
    return {
        "strategy_id":      row.strategy_id,
        "name":             row.name,
        "family":           row.family,
        "generation":       row.generation,
        "status":           row.status,
        "status_reason":    row.status_reason,
        "fitness_score":    row.fitness_score,
        "sharpe":           row.sharpe,
        "sortino":          row.sortino,
        "win_rate":         row.win_rate,
        "profit_factor":    row.profit_factor,
        "max_drawdown":     row.max_drawdown,
        "expectancy":       row.expectancy,
        "trade_count":      row.trade_count,
        "avg_holding_days": row.avg_holding_days,
        "exposure_pct":     row.exposure_pct,
        "bull_sharpe":      row.bull_sharpe,
        "bear_sharpe":      row.bear_sharpe,
        "sideways_sharpe":  row.sideways_sharpe,
        "volatile_sharpe":  row.volatile_sharpe,
        "oos_sharpe":       row.oos_sharpe,
        "oos_win_rate":     row.oos_win_rate,
        "oos_trades":       row.oos_trades,
        "oos_passed":       row.oos_passed,
        "backtest_start":   str(row.backtest_start) if row.backtest_start else None,
        "backtest_end":     str(row.backtest_end) if row.backtest_end else None,
        "allowed_regimes":  _safe_json(row.allowed_regimes),
        "feature_categories": _safe_json(row.feature_categories),
        "parent_ids":       _safe_json(row.parent_ids),
        "dsl":              _safe_json(row.dsl_json),
        "promoted_at":      row.promoted_at.isoformat() if row.promoted_at else None,
        "retired_at":       row.retired_at.isoformat() if row.retired_at else None,
        "created_at":       row.created_at.isoformat() if row.created_at else None,
        "quarantine":       _quarantine_status(db, row),
    }


@router.get("/{strategy_id}/dna")
def get_strategy_dna(strategy_id: str, db: Session = Depends(get_db_dependency)):
    """
    Full Strategy DNA: decoded rules, parent lineage, mutation history,
    live validation vs backtest, and trade-by-trade breakdown.
    Used by the Strategy DNA Viewer panel in the UI.
    """
    if strategy_id in RESERVED_IDS:
        raise HTTPException(status_code=400, detail="'All' is reserved — provide a concrete strategy ID")
    row = get_strategy(db, strategy_id)
    if not row:
        raise HTTPException(status_code=404, detail="Strategy not found")

    # ── DSL decoded ──────────────────────────────────────────────
    dsl = _safe_json(row.dsl_json) or {}

    # Human-readable rule explanation
    entry_rules = []
    exit_rules  = []
    if isinstance(dsl, dict):
        for c in (dsl.get("entry_conditions") or {}).get("conditions", []):
            op = c.get("operator", ">")
            entry_rules.append(
                f"{c.get('feature','?')} {op} {c.get('threshold','?')}"
            )
        for c in (dsl.get("exit_conditions") or {}).get("conditions", []):
            op = c.get("operator", ">")
            exit_rules.append(
                f"{c.get('feature','?')} {op} {c.get('threshold','?')}"
            )

    # ── Version / mutation history ───────────────────────────────
    versions = (
        db.query(StrategyVersion)
        .filter(StrategyVersion.strategy_id == strategy_id)
        .order_by(StrategyVersion.version.asc())
        .all()
    )
    version_history = [
        {
            "version":      v.version,
            "change_type":  v.change_type,
            "change_desc":  v.change_desc,
            "fitness_score": v.fitness_score,
            "created_at":   v.created_at.isoformat() if v.created_at else None,
        }
        for v in versions
    ]

    # ── Evolution lineage ────────────────────────────────────────
    evo = (
        db.query(StrategyEvolutionHistory)
        .filter(StrategyEvolutionHistory.child_strategy_id == strategy_id)
        .order_by(StrategyEvolutionHistory.created_at.asc())
        .all()
    )
    evolution_events = [
        {
            "operation":    e.operation,
            "detail":       _safe_json(e.operation_detail),
            "parent_ids":   _safe_json(e.parent_strategy_ids),
            "parent_fitness": e.parent_fitness,
            "child_fitness":  e.child_fitness,
            "fitness_delta":  e.fitness_delta,
            "regime_at":    e.regime_at,
            "date":         str(e.evolved_date) if e.evolved_date else None,
        }
        for e in evo
    ]

    # ── Parent strategies ────────────────────────────────────────
    parent_ids = _safe_json(row.parent_ids) or []
    parents = []
    for pid in parent_ids[:5]:
        p = db.query(StrategyV2).filter(StrategyV2.strategy_id == pid).first()
        if p:
            parents.append({
                "strategy_id": p.strategy_id,
                "name":        p.name,
                "family":      p.family,
                "fitness":     p.fitness_score,
                "status":      p.status,
            })

    # ── Children this strategy produced ─────────────────────────
    children_evo = (
        db.query(StrategyEvolutionHistory)
        .filter(StrategyEvolutionHistory.parent_strategy_ids.contains(strategy_id))
        .order_by(StrategyEvolutionHistory.created_at.desc())
        .limit(10)
        .all()
    )
    children = []
    for ce in children_evo:
        c = db.query(StrategyV2).filter(
            StrategyV2.strategy_id == ce.child_strategy_id
        ).first()
        if c:
            children.append({
                "strategy_id": c.strategy_id,
                "name":        c.name,
                "fitness":     c.fitness_score,
                "status":      c.status,
                "operation":   ce.operation,
            })

    # ── Recent backtest trades ───────────────────────────────────
    recent_trades = (
        db.query(StrategyBacktestTrade)
        .filter(StrategyBacktestTrade.strategy_id == strategy_id)
        .order_by(StrategyBacktestTrade.exit_date.desc())
        .limit(20)
        .all()
    )
    trade_rows = [
        {
            "symbol":       t.symbol,
            "entry_date":   str(t.entry_date) if t.entry_date else None,
            "exit_date":    str(t.exit_date)  if t.exit_date  else None,
            "entry_price":  t.entry_price,
            "exit_price":   t.exit_price,
            "pnl_pct":      round(t.pnl_pct or 0, 4),
            "exit_reason":  t.exit_reason,
            "holding_days": t.holding_days,
            "regime":       getattr(t, "regime_at", None),
            "signal_source": getattr(t, "signal_source", "backtest"),
        }
        for t in recent_trades
    ]

    # ── Live validation summary ──────────────────────────────────
    try:
        from strategies.live_validator import get_live_validation_summary
        live_validation = get_live_validation_summary(db, strategy_id)
    except Exception:
        live_validation = {"available": False}

    # ── Net expectancy (cost-adjusted) ───────────────────────────
    ROUND_TRIP_COST = 0.28
    net_expectancy = round((row.expectancy or 0) - ROUND_TRIP_COST, 4)

    return {
        "strategy_id":      strategy_id,
        "name":             row.name,
        "family":           row.family,
        "generation":       row.generation,
        "status":           row.status,
        "status_reason":    row.status_reason,
        # Fitness breakdown
        "fitness_score":    row.fitness_score,
        "sharpe":           row.sharpe,
        "sortino":          row.sortino,
        "win_rate":         row.win_rate,
        "profit_factor":    row.profit_factor,
        "max_drawdown":     row.max_drawdown,
        "expectancy":       row.expectancy,
        "net_expectancy":   net_expectancy,
        "trade_count":      row.trade_count,
        "avg_holding_days": row.avg_holding_days,
        "bull_sharpe":      row.bull_sharpe,
        "bear_sharpe":      row.bear_sharpe,
        "sideways_sharpe":  row.sideways_sharpe,
        "volatile_sharpe":  row.volatile_sharpe,
        "allowed_regimes":  _safe_json(row.allowed_regimes),
        "backtest_start":   str(row.backtest_start) if row.backtest_start else None,
        "backtest_end":     str(row.backtest_end) if row.backtest_end else None,
        # DNA
        "entry_rules":      entry_rules,
        "exit_rules":       exit_rules,
        "dsl":              dsl,
        # Params
        "min_confidence":   dsl.get("min_confidence") if isinstance(dsl, dict) else None,
        "stop_loss_pct":    dsl.get("stop_loss_pct")  if isinstance(dsl, dict) else None,
        "take_profit_pct":  dsl.get("take_profit_pct") if isinstance(dsl, dict) else None,
        "max_holding_days": dsl.get("max_holding_days") if isinstance(dsl, dict) else None,
        # Lineage
        "parents":          parents,
        "children":         children,
        "version_history":  version_history,
        "evolution_events": evolution_events,
        "created_at":       row.created_at.isoformat() if row.created_at else None,
        "promoted_at":      row.promoted_at.isoformat() if row.promoted_at else None,
        # Live validation
        "live_validation":  live_validation,
        # Sample trades
        "recent_trades":    trade_rows,
    }


@router.post("/{strategy_id}/promote")
def promote(
    strategy_id: str,
    reason: str = Query(default="manual_approval"),
    db: Session = Depends(get_db_dependency),
):
    if strategy_id in RESERVED_IDS:
        raise HTTPException(status_code=400, detail="'All' is reserved — provide a concrete strategy ID")
    result = promote_strategy(db, strategy_id, reason=reason)
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/{strategy_id}/activate")
def activate(strategy_id: str, force: bool = False, db: Session = Depends(get_db_dependency)):
    """
    Human approval — moves 'promoted' → 'active'. No automatic path exists.

    Paper-trading QUARANTINE gate: the strategy must have spent
    QUARANTINE_MIN_DAYS in 'promoted' AND produced QUARANTINE_MIN_TRADES
    closed live paper trades with win rate >= QUARANTINE_MIN_WIN_RATE and
    positive net P&L. Forward performance on data that didn't exist when the
    strategy was created is the only test that can't be overfit.
    Pass force=true to override (logged in status_reason).
    """
    if strategy_id in RESERVED_IDS:
        raise HTTPException(status_code=400, detail="'All' is reserved — provide a concrete strategy ID")
    from strategies.strategy_lifecycle import check_quarantine_gate

    row = get_strategy(db, strategy_id)
    if not row:
        raise HTTPException(status_code=404, detail="Strategy not found")
    if row.status != "promoted":
        raise HTTPException(
            status_code=400,
            detail=f"Strategy must be in 'promoted' state to activate. Current: {row.status}",
        )

    if not force:
        failures = check_quarantine_gate(db, row)
        if failures:
            raise HTTPException(
                status_code=400,
                detail="Quarantine gate not met: " + "; ".join(failures) +
                       ". Pass force=true to override.",
            )

    row.status        = "active"
    row.status_reason = "human_approved_forced" if force else "human_approved_after_quarantine"
    db.commit()
    return {"strategy_id": strategy_id, "status": "active",
            "message": "Strategy activated by human approval" + (" (FORCED past quarantine)" if force else "")}


@router.post("/{strategy_id}/retire")
def retire(
    strategy_id: str,
    reason: str = Query(default="manual_retirement"),
    db: Session = Depends(get_db_dependency),
):
    if strategy_id in RESERVED_IDS:
        raise HTTPException(status_code=400, detail="'All' is reserved — provide a concrete strategy ID")
    result = retire_strategy(db, strategy_id, failure_reason=reason)
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])

    # 2-for-1 breeding: spawn 2 offspring to replace the retired strategy
    try:
        breed_result = evolve_population(db, n_offspring=2)
        result["bred_offspring"] = breed_result.get("evolved", 0)
        result["breed_message"] = f"Spawned {breed_result.get('evolved', 0)} new strategies to replace retired one"
    except Exception as exc:
        result["breed_error"] = str(exc)

    return result


@router.post("/admin/lifecycle-sweep")
def lifecycle_sweep(db: Session = Depends(get_db_dependency)):
    return run_lifecycle_sweep(db)


@router.post("/admin/generate")
def generate_candidates(
    n: int = Query(default=100, ge=10, le=500),
    db: Session = Depends(get_db_dependency),
):
    return run_generation_cycle(db, n=n, generation=0)


@router.post("/admin/evolve")
def evolve(
    n_offspring: int = Query(default=40, ge=5, le=200),
    db: Session = Depends(get_db_dependency),
):
    return evolve_population(db, n_offspring=n_offspring)


@router.post("/admin/bulk-backtest")
def bulk_backtest(
    background_tasks: BackgroundTasks,
    batch_size: int = Query(default=200, ge=10, le=500),
    db: Session = Depends(get_db_dependency),
):
    """Backtest up to batch_size unscored candidate strategies (runs in background)."""
    from strategies.strategy_research_loop import _backtest_unscored
    from aqrti.database.session import get_db_session

    def _run():
        with get_db_session() as bg_db:
            _backtest_unscored(bg_db, max_stocks=batch_size)

    background_tasks.add_task(_run)
    return {"status": "started", "batch_size": batch_size, "message": f"Backtesting up to {batch_size} strategies in background"}


@router.post("/admin/rescore")
def rescore(db: Session = Depends(get_db_dependency)):
    """Recompute fitness scores for all strategies with backtest data."""
    from strategies.fitness_engine import rescore_all
    from strategies.strategy_lifecycle import run_lifecycle_sweep
    rescore_result = rescore_all(db)
    lifecycle = run_lifecycle_sweep(db)
    return {**rescore_result, "promoted": len(lifecycle["promoted"]), "retired": len(lifecycle["retired"])}


@router.post("/admin/full-research-cycle")
def full_research_cycle(
    background_tasks: BackgroundTasks,
    generate_n:  int = Query(default=100, ge=10, le=500),
    evolve_n:    int = Query(default=40,  ge=5,  le=200),
    batch_size:  int = Query(default=200, ge=10, le=500),
):
    """Run a full strategy research cycle in background: generate → backtest → score → lifecycle → evolve."""
    from strategies.strategy_research_loop import _backtest_unscored
    from strategies.fitness_engine import rescore_all
    from strategies.strategy_lifecycle import run_lifecycle_sweep
    from aqrti.database.session import get_db_session

    def _run():
        with get_db_session() as bg_db:
            run_generation_cycle(bg_db, n=generate_n, generation=0)
            _backtest_unscored(bg_db, max_stocks=batch_size)
            rescore_all(bg_db)
            run_lifecycle_sweep(bg_db)
            evolve_population(bg_db, n_offspring=evolve_n)

    background_tasks.add_task(_run)
    return {
        "status":  "started",
        "message": f"Full research cycle running in background (generate={generate_n}, backtest={batch_size}, evolve={evolve_n})",
    }


@router.get("/{strategy_id}/trades")
def get_strategy_trades(
    strategy_id: str,
    limit: int = Query(default=200, ge=1, le=500),
    db: Session = Depends(get_db_dependency),
):
    """Return individual backtest trades for a strategy."""
    from aqrti.database.models import StrategyBacktestTrade
    row = get_strategy(db, strategy_id)
    if not row:
        raise HTTPException(status_code=404, detail="Strategy not found")

    trades = (
        db.query(StrategyBacktestTrade)
        .filter_by(strategy_id=strategy_id)
        .order_by(StrategyBacktestTrade.entry_date)
        .limit(limit)
        .all()
    )
    # Build cumulative equity curve from trades
    equity = 100.0
    equity_curve = []
    for t in trades:
        pnl = t.pnl_pct or 0.0
        equity *= (1 + pnl / 100)
        equity_curve.append(round(equity, 4))

    return {
        "strategy_id": strategy_id,
        "name":        row.name,
        "family":      row.family,
        "status":      row.status,
        "fitness":     row.fitness_score,
        "sharpe":      row.sharpe,
        "win_rate":    row.win_rate,
        "trade_count": len(trades),
        "trades": [
            {
                "symbol":      t.symbol,
                "entryDate":   str(t.entry_date),
                "exitDate":    str(t.exit_date) if t.exit_date else None,
                "entryPrice":  t.entry_price,
                "exitPrice":   t.exit_price,
                "pnlPct":      round(t.pnl_pct, 4) if t.pnl_pct else None,
                "exitReason":  t.exit_reason,
                "holdingDays": t.holding_days,
                "result":      "win" if (t.pnl_pct or 0) > 0 else "loss" if (t.pnl_pct or 0) < 0 else "flat",
            }
            for t in trades
        ],
        "equityCurve": equity_curve,
    }


@router.post("/{strategy_id}/replay")
def replay_strategy(
    strategy_id: str,
    db: Session = Depends(get_db_dependency),
):
    """Re-run backtest for a strategy and return full trade sequence for replay."""
    if strategy_id in RESERVED_IDS:
        raise HTTPException(status_code=400, detail="'All' is reserved — provide a concrete strategy ID")
    import json as _json
    row = get_strategy(db, strategy_id)
    if not row:
        raise HTTPException(status_code=404, detail="Strategy not found")
    if not row.dsl_json:
        raise HTTPException(status_code=400, detail="Strategy has no DSL definition")

    from strategies.strategy_backtester import backtest_and_update
    from strategies.strategy_dsl import StrategyDSL

    try:
        dsl = StrategyDSL.from_dict(_json.loads(row.dsl_json))
        # Stored-row re-backtest: keep the row's stored ID (strategy_id() is
        # now a full-genome hash; recomputing would fork a duplicate row).
        result = backtest_and_update(db, dsl, strategy_id_override=row.strategy_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    # Build equity curve for replay animation
    equity = 100.0
    replay_frames = []
    for t in result.trades:
        pnl = t.pnl_pct or 0.0
        equity *= (1 + pnl / 100)
        replay_frames.append({
            "symbol":      t.symbol,
            "entryDate":   str(t.entry_date),
            "exitDate":    str(t.exit_date) if t.exit_date else None,
            "entryPrice":  t.entry_price,
            "exitPrice":   t.exit_price,
            "pnlPct":      round(t.pnl_pct, 4) if t.pnl_pct else None,
            "equityAfter": round(equity, 2),
            "result":      "win" if pnl > 0 else "loss" if pnl < 0 else "flat",
            "holdingDays": t.holding_days,
            "exitReason":  t.exit_reason,
        })

    return {
        "strategy_id":  strategy_id,
        "name":         row.name,
        "family":       row.family,
        "sharpe":       result.sharpe,
        "win_rate":     result.win_rate,
        "total_return": result.total_return,
        "trade_count":  result.trade_count,
        "max_drawdown": result.max_drawdown,
        "frames":       replay_frames,
        "finalEquity":  round(equity, 2),
    }
