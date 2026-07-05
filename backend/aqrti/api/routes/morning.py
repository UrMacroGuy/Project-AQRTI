"""
GO-7: Morning Decision Screen API

Answers "what should I do today and why?" — returns today's actionable
signals from promoted algos, current market regime, circuit-breaker state,
and an explicit NO ACTION state when there is nothing to act on.

Also provides POST /morning/act to log when the user acts on or skips a
signal (compliance log for paper vs real reconciliation).

MorningActionLog is stored via raw SQLite (CREATE TABLE IF NOT EXISTS) to
avoid touching models.py while it is being refactored concurrently (ARCH-5).
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from aqrti.database.engine import get_db_dependency, get_engine
from aqrti.database.models import (
    MarketRegime,
    PaperTrade,
    StrategyV2,
    SystemHealthCheck,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# ── Constants ──────────────────────────────────────────────────────────────────

PAPER_CAPITAL = 100_000.0          # INR paper trading capital base
POSITION_CAP_INR = 1_000.0         # GO-10: hard cap per trade
QUARANTINE_DAYS = 60
QUARANTINE_TRADES = 20
QUARANTINE_WR = 0.50

# Regimes that prevent trading (conservative posture)
NO_TRADE_REGIMES = {"BEAR", "SIDEWAYS_VOLATILE"}

_LOG_TABLE_CREATED = False


# ── Table bootstrap ────────────────────────────────────────────────────────────

def _ensure_log_table() -> None:
    """
    Create MorningActionLog if it does not exist.
    Uses raw SQLite so we don't touch models.py during concurrent ARCH-5 refactor.
    Idempotent — safe to call on every request startup.
    """
    global _LOG_TABLE_CREATED
    if _LOG_TABLE_CREATED:
        return
    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS morning_action_log (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                logged_at     TEXT    NOT NULL,
                trade_date    TEXT    NOT NULL,
                strategy_id   TEXT    NOT NULL,
                symbol        TEXT    NOT NULL,
                action        TEXT    NOT NULL CHECK(action IN ('acted', 'skipped')),
                note          TEXT,
                regime        TEXT,
                risk_posture  TEXT
            )
        """))
        conn.commit()
    _LOG_TABLE_CREATED = True


# ── Helpers ────────────────────────────────────────────────────────────────────

def _latest_regime(db: Session) -> Optional[MarketRegime]:
    return (
        db.query(MarketRegime)
        .order_by(MarketRegime.date.desc())
        .first()
    )


def _latest_health(db: Session) -> Optional[SystemHealthCheck]:
    return (
        db.query(SystemHealthCheck)
        .order_by(SystemHealthCheck.checked_at.desc())
        .first()
    )


def _risk_posture(health: Optional[SystemHealthCheck]) -> str:
    """
    Derive risk posture from the circuit-breaker (SystemHealthCheck).
    Returns "high" if circuit breaker is red, else "normal".
    "elevated" is a future extension (e.g. partial failures).
    """
    if health is None:
        return "normal"          # No data yet — assume normal, don't block
    if not health.overall_ok:
        return "high"
    return "normal"


def _position_size_inr(dsl_json_str: Optional[str]) -> float:
    """
    Parse the algo's DSL to find its intended position size.
    Returns the INR value capped at POSITION_CAP_INR (GO-10).
    Falls back to POSITION_CAP_INR if the DSL has no sizing field.
    """
    if not dsl_json_str:
        return POSITION_CAP_INR

    try:
        dsl = json.loads(dsl_json_str)
    except (json.JSONDecodeError, TypeError):
        return POSITION_CAP_INR

    # DSL may be a dict directly or wrapped under a key
    if isinstance(dsl, dict):
        # Try position_size_pct (fractional, e.g. 0.02 = 2% of capital)
        pct = dsl.get("position_size_pct")
        if pct is not None:
            try:
                computed = float(pct) * PAPER_CAPITAL
                return min(computed, POSITION_CAP_INR)
            except (TypeError, ValueError):
                pass

        # Try position_size (absolute INR)
        absolute = dsl.get("position_size")
        if absolute is not None:
            try:
                return min(float(absolute), POSITION_CAP_INR)
            except (TypeError, ValueError):
                pass

    return POSITION_CAP_INR


def _quarantine_stats(db: Session, strategy_id: str) -> dict[str, Any]:
    """Return quarantine progress stats for a promoted algo."""
    now = datetime.utcnow()

    algo = (
        db.query(StrategyV2)
        .filter(StrategyV2.strategy_id == strategy_id)
        .first()
    )
    if algo is None:
        return {"quarantine_days": 0, "shadow_trades": 0, "shadow_wr": None}

    days_in_q = (now - algo.promoted_at).days if algo.promoted_at else 0

    closed_trades = (
        db.query(PaperTrade)
        .filter(
            PaperTrade.strategy_id == strategy_id,
            PaperTrade.is_open == False,  # noqa: E712
        )
        .all()
    )
    shadow_count = len(closed_trades)
    if shadow_count > 0:
        wins = sum(
            1 for t in closed_trades
            if (t.gross_pnl_pct is not None and t.gross_pnl_pct > 0)
        )
        shadow_wr = round(wins / shadow_count * 100, 1)
    else:
        shadow_wr = None

    return {
        "quarantine_days": days_in_q,
        "shadow_trades": shadow_count,
        "shadow_wr": shadow_wr,
    }


# ── GET /morning/decision ──────────────────────────────────────────────────────

@router.get("/morning/decision", tags=["Morning Decision"])
def get_morning_decision(db: Session = Depends(get_db_dependency)) -> dict[str, Any]:
    """
    GO-7: Morning Decision Screen.

    Returns today's actionable signals from promoted/active algos, the current
    market regime, circuit-breaker state, and an explicit NO ACTION state when
    there is nothing to act on.

    no_action=True when:
    - Zero promoted/active algos exist, OR
    - Regime is in NO_TRADE_REGIMES (BEAR, SIDEWAYS_VOLATILE), OR
    - Circuit breaker is red (overall_ok=False)
    """
    _ensure_log_table()

    today = date.today()

    # ── Regime ────────────────────────────────────────────────────────────────
    regime_row = _latest_regime(db)
    regime = regime_row.regime if regime_row else None

    # ── Circuit breaker / risk posture ────────────────────────────────────────
    health = _latest_health(db)
    posture = _risk_posture(health)

    # ── Promoted algos ────────────────────────────────────────────────────────
    promoted_algos = (
        db.query(StrategyV2)
        .filter(StrategyV2.status.in_(["promoted", "active"]))
        .all()
    )
    promoted_ids = [a.strategy_id for a in promoted_algos]
    algo_lookup = {a.strategy_id: a for a in promoted_algos}

    # ── Determine no_action ───────────────────────────────────────────────────
    no_action = False
    no_action_reason: Optional[str] = None

    if len(promoted_algos) == 0:
        no_action = True
        no_action_reason = (
            "No promoted algos — all algos are still in candidate/shadow/testing phase. "
            "The population must produce at least one algo that passes all honest gates."
        )
    elif posture == "high":
        no_action = True
        failures = getattr(health, "failures", "") or ""
        no_action_reason = (
            f"Circuit breaker RED — system health check failed. "
            f"Failures: {failures or 'see system health page'}. "
            "Do not act on signals until pipeline is green again."
        )
    elif regime and regime.upper() in NO_TRADE_REGIMES:
        no_action = True
        no_action_reason = (
            f"Regime is {regime} — conservative posture, no new entries today. "
            "Promoted algos are not designed for this regime; wait for BULL or SIDEWAYS."
        )

    # ── Build signals from open paper trades ──────────────────────────────────
    signals: list[dict[str, Any]] = []

    if promoted_ids and not no_action:
        open_trades = (
            db.query(PaperTrade)
            .filter(
                PaperTrade.strategy_id.in_(promoted_ids),
                PaperTrade.is_open == True,  # noqa: E712
            )
            .order_by(PaperTrade.entry_date.desc())
            .all()
        )

        for trade in open_trades:
            algo = algo_lookup.get(trade.strategy_id)
            algo_name = (algo.name if algo else None) or trade.strategy_name or trade.strategy_id

            # DSL-derived position size, capped at Rs 1,000
            dsl_str = algo.dsl_json if algo else None
            position_size_inr = _position_size_inr(dsl_str)

            # Derive SL/TP from DSL if available
            stop_loss_pct: Optional[float] = None
            take_profit_pct: Optional[float] = None
            if dsl_str:
                try:
                    dsl = json.loads(dsl_str)
                    if isinstance(dsl, dict):
                        sl_raw = dsl.get("stop_loss_pct") or dsl.get("stop_loss")
                        tp_raw = dsl.get("take_profit_pct") or dsl.get("take_profit")
                        if sl_raw is not None:
                            stop_loss_pct = float(sl_raw)
                        if tp_raw is not None:
                            take_profit_pct = float(tp_raw)
                except (json.JSONDecodeError, TypeError, ValueError):
                    pass

            q_stats = _quarantine_stats(db, trade.strategy_id)

            signals.append({
                "strategy_id": trade.strategy_id,
                "algo_name": algo_name,
                "symbol": trade.symbol,
                "direction": trade.direction,
                "entry_price": trade.entry_price,
                "entry_date": str(trade.entry_date) if trade.entry_date else None,
                "stop_loss_pct": stop_loss_pct,
                "take_profit_pct": take_profit_pct,
                "position_size_inr": position_size_inr,
                "confidence": trade.confidence,
                "quarantine_days": q_stats["quarantine_days"],
                "shadow_trades": q_stats["shadow_trades"],
                "shadow_wr": q_stats["shadow_wr"],
                "current_pnl_pct": round(trade.gross_pnl_pct or 0.0, 3),
            })

    return {
        "date": today.isoformat(),
        "regime": regime,
        "regime_date": str(regime_row.date) if regime_row else None,
        "risk_posture": posture,
        "circuit_breaker_ok": health.overall_ok if health else None,
        "no_action": no_action,
        "no_action_reason": no_action_reason,
        "promoted_algo_count": len(promoted_algos),
        "signals": signals,
        "signal_count": len(signals),
        "position_cap_inr": POSITION_CAP_INR,
        "note": (
            "Signals are open paper trades on promoted/active algos only. "
            "Position size is hard-capped at Rs 1,000 per GO-10. "
            "User reviews and trades manually — AQRTI never executes real trades."
        ),
    }


# ── POST /morning/act ──────────────────────────────────────────────────────────

class MorningActRequest(BaseModel):
    strategy_id: str
    symbol: str
    action: str          # "acted" | "skipped"
    note: Optional[str] = None


@router.post("/morning/act", tags=["Morning Decision"])
def post_morning_act(
    body: MorningActRequest,
    db: Session = Depends(get_db_dependency),
) -> dict[str, Any]:
    """
    GO-7: Log a user action (acted / skipped) on a morning signal.

    Builds a compliance audit trail for paper vs real reconciliation.
    Stored in morning_action_log (raw SQLite table, not an ORM model —
    models.py is being refactored concurrently under ARCH-5).
    """
    _ensure_log_table()

    if body.action not in ("acted", "skipped"):
        return {"logged": False, "error": "action must be 'acted' or 'skipped'"}

    # Capture current regime and risk posture at log time
    regime_row = _latest_regime(db)
    regime = regime_row.regime if regime_row else None
    health = _latest_health(db)
    posture = _risk_posture(health)

    now = datetime.utcnow()
    today = date.today()

    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(
            text("""
                INSERT INTO morning_action_log
                    (logged_at, trade_date, strategy_id, symbol, action, note,
                     regime, risk_posture)
                VALUES
                    (:logged_at, :trade_date, :strategy_id, :symbol, :action,
                     :note, :regime, :risk_posture)
            """),
            {
                "logged_at":    now.isoformat(),
                "trade_date":   today.isoformat(),
                "strategy_id":  body.strategy_id,
                "symbol":       body.symbol,
                "action":       body.action,
                "note":         body.note,
                "regime":       regime,
                "risk_posture": posture,
            },
        )
        conn.commit()

    logger.info(
        "MorningActionLog: %s | %s | %s | %s",
        today.isoformat(), body.strategy_id, body.symbol, body.action,
    )

    return {
        "logged": True,
        "trade_date": today.isoformat(),
        "strategy_id": body.strategy_id,
        "symbol": body.symbol,
        "action": body.action,
        "regime_at_log_time": regime,
        "risk_posture_at_log_time": posture,
    }


# ── GET /morning/act-log ───────────────────────────────────────────────────────

@router.get("/morning/act-log", tags=["Morning Decision"])
def get_morning_act_log(limit: int = 50) -> list[dict[str, Any]]:
    """
    Return the most recent morning action log entries.
    Useful for compliance review and paper vs real reconciliation.
    """
    _ensure_log_table()

    engine = get_engine()
    with engine.connect() as conn:
        rows = conn.execute(
            text("""
                SELECT id, logged_at, trade_date, strategy_id, symbol,
                       action, note, regime, risk_posture
                FROM morning_action_log
                ORDER BY id DESC
                LIMIT :limit
            """),
            {"limit": max(1, min(limit, 500))},
        ).fetchall()

    return [
        {
            "id":           row[0],
            "logged_at":    row[1],
            "trade_date":   row[2],
            "strategy_id":  row[3],
            "symbol":       row[4],
            "action":       row[5],
            "note":         row[6],
            "regime":       row[7],
            "risk_posture": row[8],
        }
        for row in rows
    ]
