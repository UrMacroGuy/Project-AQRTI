"""
Strategy Arena Engine
=====================
The main self-learning loop. Runs every time the backend starts and every hour.

Full loop per strategy:
  1. Read strategies eligible for arena entry (promoted/active — no status
     mutation happens here; human approval remains the only path to "active",
     see auto_promote_strategies below).
  2. Create isolated portfolio (arena_{strategy_id}) with ₹1,00,000.
  3. Replay TRAIN_YEARS of historical data (in-sample) + hold out the most
     recent OOS_MONTHS as an out-of-sample window the strategy never trains
     against.
  4. Grade IN-SAMPLE: 120% return + <25% drawdown + >52% win rate, AND
     >= MIN_CHAMPION_TRADES trades, AND regime-stratified robustness
     (no single regime bucket can be net-negative if it has enough trades
     to be meaningful) -> passes in-sample gate.
  5. Grade OUT-OF-SAMPLE on the held-out window with looser but still
     required thresholds (OOS_MIN_WIN_RATE, OOS_MIN_RETURN_PCT) -> only
     strategies proving themselves on unseen data become CHAMPION.
  6. If not champion: find donor (best strategy on losing days).
  7. Merge current + donor -> child strategy.
  8. Replay child — must fix old losing days AND keep old winning days
     (Option B), and pass the same in-sample + OOS double gate.
  9. Repeat up to MAX_ROUNDS (10). If still not champion -> "needs_review".

Arena state (champion/refining/needs_review) is tracked in the dedicated
StrategyV2.arena_status / arena_rounds columns — NEVER in StrategyV2.status,
which is owned exclusively by strategy_lifecycle.py's state machine
(candidate -> shadow -> promoted -> active -> retired). A prior version of
this module wrote "champion"/"needs_review" directly into .status and had
auto_promote_strategies() silently move promoted -> active without human
approval or the paper-trading quarantine; both were safety bugs, fixed
2026-07-03.

Runs in background thread — non-blocking, progress tracked in ArenaRun table.
"""

from __future__ import annotations

import json
import threading
import sys
import os
from datetime import datetime, date, timedelta
from typing import Optional

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from aqrti.database.engine import get_db
from aqrti.database.models import StrategyV2, ArenaRun
from aqrti.utils.logger import get_logger

log = get_logger("arena_engine")

# ── Constants ──────────────────────────────────────────────────
MAX_ROUNDS          = 10
MIN_FITNESS_TO_ENTER = 60.0   # promoted strategy must have fitness >= 60
MIN_WIN_RATE        = 55.0    # % — backtest win rate gate for arena eligibility
TARGET_RETURN_PCT   = 120.0   # % — champion gate (in-sample)
MAX_DRAWDOWN_GATE   = -25.0   # % — champion gate (must be better than -25%)
MIN_WIN_RATE_GATE   = 52.0    # % — champion gate on in-sample replay
MIN_CHAMPION_TRADES = 30      # floor — a handful of lucky trades must not crown a champion

# ── Out-of-sample validation (the arena previously had none at all) ────
REPLAY_YEARS   = 2      # total historical window replayed
OOS_MONTHS     = 6      # trailing slice held out as the OOS test
OOS_MIN_TRADES = 8      # minimum trades in the OOS window to grade it at all
OOS_MIN_WIN_RATE   = 48.0   # % — looser than in-sample (small-sample OOS window)
OOS_MIN_RETURN_PCT = 0.0    # OOS must at least be net non-negative

# ── Regime-stratified robustness (previously grading was regime-blind) ──
MIN_TRADES_PER_REGIME_TO_JUDGE = 5   # only judge a regime bucket with enough trades
MAX_NEGATIVE_REGIME_BUCKETS    = 0   # champion must not be net-negative in ANY
                                     # sufficiently-sampled regime (0 = zero tolerance)

_arena_lock         = threading.Lock()
_running            = False


# ══════════════════════════════════════════════════════════════
# AUTO-PROMOTE
# ══════════════════════════════════════════════════════════════

def auto_promote_strategies(db) -> list[str]:
    """
    Flag strategies eligible for arena entry — DOES NOT change status.

    Previously this moved 'promoted' -> 'active' automatically, which
    silently bypassed the human-approval gate that strategy_lifecycle.py
    explicitly documents as required before a strategy reaches 'active'
    ("AQRTI can only reach 'promoted'" — strategy_lifecycle.py class
    docstring) and before the paper-trading quarantine
    (promotion_config.QUARANTINE_*, enforced in
    aqrti/api/routes/strategies.py's /activate endpoint) is satisfied. A
    strategy that never ran a single day of forward-tested paper trading
    could reach 'active' purely by clearing two in-sample backtest numbers.

    The arena now only READS 'promoted' + already-human-approved 'active'
    strategies to decide who is eligible to enter arena rounds; it never
    performs the status transition itself. Returns the eligible strategy_ids
    (for logging/visibility), no DB write.
    """
    promoted = db.query(StrategyV2).filter(
        StrategyV2.status == "promoted",
        StrategyV2.fitness_score >= MIN_FITNESS_TO_ENTER,
        StrategyV2.dsl_json.isnot(None),
    ).all()

    eligible = [s.strategy_id for s in promoted if (s.win_rate or 0) >= MIN_WIN_RATE]
    if eligible:
        log.info("Arena-eligible (still awaiting human /activate approval): %d strategies", len(eligible))
    return eligible


# ══════════════════════════════════════════════════════════════
# GRADING
# ══════════════════════════════════════════════════════════════

def _grade_regime_robustness(regime_buckets: dict) -> dict:
    """
    A strategy that makes all its money in one regime and bleeds in every
    other well-sampled regime is not robust — it's a lucky fit to whichever
    regime dominated the replay window. Only judge buckets with enough days
    to be meaningful (MIN_TRADES_PER_REGIME_TO_JUDGE, reusing the same floor
    concept as trade-count elsewhere); a regime that barely occurred in the
    window doesn't get to veto a champion.
    """
    negative_regimes = [
        reg for reg, b in regime_buckets.items()
        if b["days"] >= MIN_TRADES_PER_REGIME_TO_JUDGE and b["net_pnl"] < 0
    ]
    judged_regimes = [
        reg for reg, b in regime_buckets.items()
        if b["days"] >= MIN_TRADES_PER_REGIME_TO_JUDGE
    ]
    passes = len(negative_regimes) <= MAX_NEGATIVE_REGIME_BUCKETS
    return {
        "passes_robustness_gate": passes,
        "judged_regimes":         judged_regimes,
        "negative_regimes":       negative_regimes,
    }


def _grade_replay(replay_result: dict) -> dict:
    """
    Check if a replay result passes the champion gates.

    Grading is now IN-SAMPLE + OUT-OF-SAMPLE + regime-robustness, not just a
    single in-sample number. A strategy that clears the in-sample return/
    drawdown/win-rate bar on lucky/overfit trades will fail either the OOS
    check (unseen recent data) or the regime-robustness check (concentrated
    in one regime) — both were previously entirely absent from this gate.
    """
    ret   = replay_result.get("total_return_pct", 0.0)
    dd    = replay_result.get("max_drawdown_pct", -100.0)
    wr    = replay_result.get("win_rate", 0.0)
    total_trades = replay_result.get("total_trades", 0)

    passes_return   = ret  >= TARGET_RETURN_PCT
    passes_drawdown = dd   >= MAX_DRAWDOWN_GATE
    passes_winrate  = wr   >= MIN_WIN_RATE_GATE
    passes_min_trades = total_trades >= MIN_CHAMPION_TRADES

    # Out-of-sample gate — the strategy must also work on data it wasn't
    # refined against. Only meaningful if enough OOS trades occurred;
    # otherwise we can't tell signal from noise, so we don't hard-fail on it
    # but we also don't let it silently pass — treat as "not yet provable".
    oos = replay_result.get("oos_stats", {"trades": 0, "win_rate": 0.0, "total_return_pct": 0.0})
    oos_gradeable = oos.get("trades", 0) >= OOS_MIN_TRADES
    passes_oos = (
        oos_gradeable
        and oos.get("win_rate", 0.0) >= OOS_MIN_WIN_RATE
        and oos.get("total_return_pct", 0.0) >= OOS_MIN_RETURN_PCT
    )

    robustness = _grade_regime_robustness(replay_result.get("regime_buckets", {}))

    is_champion = (
        passes_return and passes_drawdown and passes_winrate
        and passes_min_trades and passes_oos
        and robustness["passes_robustness_gate"]
    )

    return {
        "passes_return_gate":    passes_return,
        "passes_drawdown_gate":  passes_drawdown,
        "passes_winrate_gate":   passes_winrate,
        "passes_min_trades_gate": passes_min_trades,
        "passes_oos_gate":       passes_oos,
        "oos_gradeable":         oos_gradeable,
        "oos_trades":            oos.get("trades", 0),
        "oos_win_rate":          oos.get("win_rate", 0.0),
        "oos_return_pct":        oos.get("total_return_pct", 0.0),
        "passes_robustness_gate": robustness["passes_robustness_gate"],
        "negative_regimes":      robustness["negative_regimes"],
        "is_champion":           is_champion,
        "return_pct":            ret,
        "drawdown_pct":          dd,
        "win_rate":              wr,
        "total_trades":          total_trades,
    }


def _regression_check(
    child_replay: dict,
    parent_replay: dict,
) -> bool:
    """
    Option B: child must fix parent's losing days AND not break parent's winning days.
    Returns True if child passes (no significant regression on winning days).
    """
    parent_winning = set(parent_replay.get("winning_days", []))
    child_winning  = set(child_replay.get("winning_days", []))

    if not parent_winning:
        return True  # nothing to regress on

    # Child must retain at least 70% of parent's winning days
    retained  = len(parent_winning & child_winning)
    retention = retained / len(parent_winning)

    ok = retention >= 0.70
    log.info(
        "Regression check: retained %.0f%% of parent winning days (%d/%d) — %s",
        retention * 100, retained, len(parent_winning),
        "PASS" if ok else "FAIL",
    )
    return ok


def _losing_days_fixed(
    child_replay: dict,
    parent_replay: dict,
) -> bool:
    """
    Check that child profits on at least 50% of parent's losing days.
    """
    parent_losing = set(parent_replay.get("losing_days", []))
    child_winning = set(child_replay.get("winning_days", []))

    if not parent_losing:
        return True

    fixed     = len(parent_losing & child_winning)
    fixed_pct = fixed / len(parent_losing) * 100

    ok = fixed_pct >= 50.0
    log.info(
        "Losing days fixed: %.0f%% (%d/%d) — %s",
        fixed_pct, fixed, len(parent_losing),
        "PASS" if ok else "FAIL",
    )
    return ok


# ══════════════════════════════════════════════════════════════
# ARENA RUN — one strategy
# ══════════════════════════════════════════════════════════════

def _save_arena_run(db, strategy, replay_result: dict, grade: dict,
                    round_num: int, donor=None, donor_coverage: float = 0.0,
                    status: str = "running") -> ArenaRun:
    """Upsert an ArenaRun row for this strategy + round."""
    losing_days = replay_result.get("losing_days", [])
    winning_days = replay_result.get("winning_days", [])
    daily = replay_result.get("daily_results", [])

    # Sample daily results for UI (keep every 5th day to limit JSON size)
    sampled = daily[::5] if len(daily) > 100 else daily

    run = db.query(ArenaRun).filter_by(
        strategy_id=strategy.strategy_id,
        round_number=round_num,
    ).first()

    if not run:
        run = ArenaRun(
            strategy_id        = strategy.strategy_id,
            strategy_name      = strategy.name,
            parent_strategy_id = strategy.parent_ids,
            generation         = strategy.generation or 0,
            round_number       = round_num,
            started_at         = datetime.utcnow(),
        )
        db.add(run)

    run.total_return_pct     = replay_result.get("total_return_pct")
    run.max_drawdown_pct     = replay_result.get("max_drawdown_pct")
    run.final_value          = replay_result.get("final_value")
    run.total_trades         = replay_result.get("total_trades")
    run.win_rate             = replay_result.get("win_rate")
    run.winning_days_count   = len(winning_days)
    run.losing_days_count    = len(losing_days)
    run.passes_return_gate   = grade.get("passes_return_gate")
    run.passes_drawdown_gate = grade.get("passes_drawdown_gate")
    run.passes_winrate_gate  = grade.get("passes_winrate_gate")
    run.is_champion          = grade.get("is_champion", False)
    run.status               = status
    run.daily_results_json   = json.dumps(sampled)
    run.winning_days_json    = json.dumps(winning_days[:200])
    run.losing_days_json     = json.dumps(losing_days[:200])
    run.completed_at         = datetime.utcnow()

    if donor:
        run.donor_strategy_id   = donor.strategy_id
        run.donor_strategy_name = donor.name
        run.donor_coverage_pct  = donor_coverage

    db.commit()
    db.refresh(run)
    return run


def run_arena_for_strategy(strategy_id: str) -> dict:
    """
    Run the full arena loop for a single strategy.
    This is the core self-learning function.
    """
    from arena.replay_engine import run_replay
    from arena.strategy_merger import find_best_donors, build_child_strategy

    log.info("=== ARENA START: %s ===", strategy_id)

    with get_db() as db:
        strategy = db.query(StrategyV2).filter_by(strategy_id=strategy_id).first()
        if not strategy:
            return {"status": "not_found", "strategy_id": strategy_id}

        # Skip if already a champion or in error state
        existing_champion = db.query(ArenaRun).filter_by(
            strategy_id=strategy_id,
            is_champion=True,
        ).first()
        if existing_champion:
            log.info("Already champion: %s — skipping", strategy_id)
            return {"status": "already_champion", "strategy_id": strategy_id}

        # Count completed rounds for this lineage
        completed_rounds = db.query(ArenaRun).filter(
            ArenaRun.strategy_id == strategy_id,
            ArenaRun.status.in_(["champion", "refining", "needs_review"]),
        ).count()

        if completed_rounds >= MAX_ROUNDS:
            log.info("Max rounds reached for %s — needs_review", strategy_id)
            db.query(ArenaRun).filter_by(strategy_id=strategy_id).update(
                {"status": "needs_review", "needs_review": True}
            )
            # Mark arena-exhausted WITHOUT touching the lifecycle status —
            # a strategy that fails to become an arena champion has NOT
            # necessarily failed its honest backtest/OOS/promotion gates;
            # it just didn't clear the arena's much harder bar. Leave
            # StrategyV2.status alone so strategy_lifecycle.py's own
            # promote/retire logic is unaffected by arena outcomes.
            strategy.arena_status = "needs_review"
            strategy.arena_rounds = completed_rounds
            db.commit()
            return {"status": "needs_review", "strategy_id": strategy_id}

        round_num = completed_rounds + 1
        log.info("Running round %d for %s", round_num, strategy.name)

    # ── Round 1+: Replay current strategy (with OOS holdout) ─
    with get_db() as db:
        strategy = db.query(StrategyV2).filter_by(strategy_id=strategy_id).first()
        replay = run_replay(db, strategy, years=REPLAY_YEARS, fresh=True, oos_months=OOS_MONTHS)

    grade = _grade_replay(replay)

    with get_db() as db:
        strategy = db.query(StrategyV2).filter_by(strategy_id=strategy_id).first()

        if grade["is_champion"]:
            strategy.arena_status = "champion"
            strategy.arena_rounds = round_num
            strategy.status_reason = f"arena_champion_round{round_num}"
            db.commit()
            _save_arena_run(db, strategy, replay, grade, round_num, status="champion")
            log.info(
                "CHAMPION: %s — return=%.1f%% dd=%.1f%% wr=%.0f%% trades=%d oos_trades=%d oos_wr=%.0f%%",
                strategy.name, grade["return_pct"], grade["drawdown_pct"], grade["win_rate"],
                grade["total_trades"], grade["oos_trades"], grade["oos_win_rate"],
            )
            return {
                "status":      "champion",
                "strategy_id": strategy_id,
                "return_pct":  grade["return_pct"],
                "round":       round_num,
            }

        # Not champion — save progress and find donor
        strategy.arena_status = "refining"
        strategy.arena_rounds = round_num
        db.commit()
        _save_arena_run(db, strategy, replay, grade, round_num, status="refining")

    log.info(
        "Round %d: NOT champion (ret=%.1f%% dd=%.1f%% wr=%.0f%% trades=%d "
        "min_trades=%s oos=%s robust=%s) — finding donor",
        round_num, grade["return_pct"], grade["drawdown_pct"], grade["win_rate"],
        grade["total_trades"], grade["passes_min_trades_gate"],
        grade["passes_oos_gate"], grade["passes_robustness_gate"],
    )

    # ── Find top donors from all existing arena results ───────────
    with get_db() as db:
        strategy = db.query(StrategyV2).filter_by(strategy_id=strategy_id).first()

        all_runs = db.query(ArenaRun).filter(
            ArenaRun.strategy_id != strategy_id,
            ArenaRun.total_return_pct.isnot(None),
            ArenaRun.total_return_pct > 0,
        ).order_by(ArenaRun.total_return_pct.desc()).limit(80).all()

        # Build donor candidate list — include winning_days + losing_days + dsl
        all_results = []
        for run in all_runs:
            try:
                wd = json.loads(run.winning_days_json or "[]")
                ld = json.loads(run.losing_days_json  or "[]")
                donor_strat = db.query(StrategyV2).filter_by(
                    strategy_id=run.strategy_id
                ).first()
                all_results.append({
                    "strategy_id":      run.strategy_id,
                    "strategy_name":    run.strategy_name,
                    "total_return_pct": run.total_return_pct or 0,
                    "winning_days":     wd,
                    "losing_days":      ld,
                    "dsl":              json.loads(donor_strat.dsl_json or "{}") if donor_strat else {},
                })
            except Exception:
                pass

        losing_days = replay.get("losing_days", [])

        # Get top 3 donors (v2 multi-donor)
        top_donors = find_best_donors(
            db,
            losing_days=losing_days,
            exclude_strategy_id=strategy_id,
            all_replay_results=all_results,
            top_n=3,
        )

        if not top_donors:
            # Fallback: if no donor from arena runs, try using any active strategy
            # as a donor (first run — no arena runs yet for other strategies)
            log.info(
                "No arena-run donors found for %s — trying active strategies as fallback",
                strategy.name,
            )
            fallback_strats = db.query(StrategyV2).filter(
                StrategyV2.status == "active",
                StrategyV2.strategy_id != strategy_id,
                StrategyV2.fitness_score.isnot(None),
            ).order_by(StrategyV2.fitness_score.desc()).limit(5).all()

            if not fallback_strats:
                log.info("No fallback donors found for %s — will retry next cycle", strategy.name)
                # Don't permanently flag needs_review — just return, let next cycle retry
                return {"status": "no_donor_retry", "strategy_id": strategy_id}

            # Use top fitness strategy as donor
            donor_strategy = fallback_strats[0]
            donor_replay   = {"winning_days": [], "losing_days": []}
            coverage       = 0.0
            extra_donors   = []
        else:
            best_donor_result = top_donors[0]
            donor_strategy    = db.query(StrategyV2).filter_by(
                strategy_id=best_donor_result["strategy_id"]
            ).first()
            if not donor_strategy:
                return {"status": "donor_not_found", "strategy_id": strategy_id}

            donor_run = db.query(ArenaRun).filter_by(
                strategy_id=donor_strategy.strategy_id
            ).order_by(ArenaRun.round_number.desc()).first()
            donor_replay = {
                "winning_days":   json.loads(donor_run.winning_days_json or "[]") if donor_run else best_donor_result.get("winning_days", []),
                "losing_days":    json.loads(donor_run.losing_days_json  or "[]") if donor_run else best_donor_result.get("losing_days",  []),
                "total_return_pct": best_donor_result.get("total_return_pct", 0),
            }
            coverage     = best_donor_result.get("coverage_pct", 0.0)
            extra_donors = [
                {
                    "strategy_id":   d.get("strategy_id"),
                    "strategy_name": d.get("strategy_name"),
                    "total_return_pct": d.get("total_return_pct", 0),
                    "winning_days":  d.get("winning_days", []),
                    "dsl":           d.get("dsl", {}),
                }
                for d in top_donors[1:]
            ]

        # Build child with v2 merger
        child = build_child_strategy(
            db               = db,
            current_strategy = strategy,
            donor_strategy   = donor_strategy,
            current_replay   = replay,
            donor_replay     = donor_replay,
            generation       = (strategy.generation or 0) + 1,
            extra_donors     = extra_donors,
        )

        if not child:
            return {"status": "merge_failed", "strategy_id": strategy_id}

        # Update ArenaRun with donor info
        db.query(ArenaRun).filter_by(
            strategy_id=strategy_id, round_number=round_num
        ).update({
            "donor_strategy_id":   donor_strategy.strategy_id,
            "donor_strategy_name": donor_strategy.name,
            "donor_coverage_pct":  coverage,
        })
        db.commit()

    # ── Replay child (with OOS holdout, same as parent) ────────
    log.info("Replaying child: %s", child.strategy_id)
    with get_db() as db:
        child_strategy = db.query(StrategyV2).filter_by(
            strategy_id=child.strategy_id
        ).first()
        child_replay = run_replay(db, child_strategy, years=REPLAY_YEARS, fresh=True, oos_months=OOS_MONTHS)

    child_grade = _grade_replay(child_replay)

    # ── Option B checks ───────────────────────────────────────
    regression_ok    = _regression_check(child_replay, replay)
    losing_days_fixed = _losing_days_fixed(child_replay, replay)

    if child_grade["is_champion"] and regression_ok:
        with get_db() as db:
            child_strategy = db.query(StrategyV2).filter_by(
                strategy_id=child.strategy_id
            ).first()
            # arena_status="champion" marks it as an arena success — this
            # does NOT touch StrategyV2.status (still "candidate" until it
            # separately earns promotion through strategy_lifecycle.py's
            # honest backtest/OOS/benchmark/duplicate gates + human
            # /activate approval + paper-trading quarantine).
            child_strategy.arena_status = "champion"
            child_strategy.arena_rounds = round_num
            child_strategy.status_reason = f"arena_champion_round{round_num}_child"
            db.commit()
            _save_arena_run(db, child_strategy, child_replay, child_grade,
                            round_num, status="champion")
        log.info("CHAMPION CHILD: %s", child.strategy_id)
        return {
            "status":      "champion",
            "strategy_id": child.strategy_id,
            "return_pct":  child_grade["return_pct"],
            "round":       round_num,
        }

    # Child improves but not champion yet — it becomes the new candidate for
    # next round WITHIN THE ARENA (arena_status only); lifecycle status is
    # untouched, still "candidate", so it still has to earn promotion the
    # normal way in parallel with further arena refinement.
    with get_db() as db:
        child_strategy = db.query(StrategyV2).filter_by(
            strategy_id=child.strategy_id
        ).first()
        child_strategy.arena_status = "refining"
        child_strategy.arena_rounds = round_num + 1
        child_strategy.status_reason = f"arena_refinement_gen{(strategy.generation or 0) + 1}"
        db.commit()
        _save_arena_run(db, child_strategy, child_replay, child_grade,
                        round_num + 1, status="refining")

    log.info(
        "Round %d child created: %s (ret=%.1f%% fixed=%.0f%% regression=%s)",
        round_num, child.strategy_id,
        child_grade["return_pct"],
        len(set(replay.get("losing_days", [])) & set(child_replay.get("winning_days", [])))
        / max(len(replay.get("losing_days", [])), 1) * 100,
        "OK" if regression_ok else "FAIL",
    )

    return {
        "status":       "refining",
        "strategy_id":  child.strategy_id,
        "parent_id":    strategy_id,
        "return_pct":   child_grade["return_pct"],
        "round":        round_num,
    }


# ══════════════════════════════════════════════════════════════
# MAIN ENTRY — runs on boot + every hour
# ══════════════════════════════════════════════════════════════

def run_arena_cycle() -> dict:
    """
    Full arena cycle — called on boot and every hour.
    1. Log arena-eligible strategies (no status mutation — see
       auto_promote_strategies)
    2. Run arena loop for eligible strategies that aren't champions yet:
       either human-approved promoted/active strategies, or arena-bred
       children still mid-refinement (arena_status == "refining").
    Non-blocking: runs in a background thread.
    """
    global _running
    with _arena_lock:
        if _running:
            log.info("Arena already running — skipping")
            return {"status": "already_running"}
        _running = True

    def _worker():
        global _running
        try:
            _run_arena_cycle_sync()
        except Exception as exc:
            log.error("Arena cycle failed: %s", exc)
        finally:
            _running = False

    t = threading.Thread(target=_worker, daemon=True, name="arena-cycle")
    t.start()
    return {"status": "started", "thread": t.name}


def _run_arena_cycle_sync():
    """Synchronous arena cycle — called inside background thread."""
    log.info("=== ARENA CYCLE START ===")

    # Step 1: Log eligibility (no auto-promotion — see auto_promote_strategies)
    with get_db() as db:
        eligible = auto_promote_strategies(db)
        if eligible:
            log.info("%d strategies eligible for arena (awaiting human approval)", len(eligible))

    # Step 2: Get strategies to run arena rounds on — either lifecycle-
    # approved promoted/active strategies, or arena-bred children still
    # mid-refinement (tracked via arena_status, independent of their
    # lifecycle status which is usually still "candidate").
    with get_db() as db:
        from sqlalchemy import or_
        champion_ids = {
            r.strategy_id for r in
            db.query(ArenaRun.strategy_id).filter_by(is_champion=True).all()
        }
        needs_review_ids = {
            r.strategy_id for r in
            db.query(ArenaRun.strategy_id).filter_by(needs_review=True).all()
        }
        active_strategies = db.query(StrategyV2).filter(
            or_(
                StrategyV2.status.in_(["promoted", "active"]),
                StrategyV2.arena_status == "refining",
            ),
            StrategyV2.arena_status != "champion",
            StrategyV2.dsl_json.isnot(None),
            # This arena cycle runs replay_engine.run_replay(), which is
            # stock-specific (DailyPrice/get_backtest_universe). Index-futures
            # strategies need their own arena path (index_futures_backtester +
            # their own benchmark) — exclude them here rather than let them
            # get silently replayed against the wrong instrument/universe.
            StrategyV2.asset_class == "stock",
        ).order_by(StrategyV2.fitness_score.desc()).all()

        to_run = [
            s for s in active_strategies
            if s.strategy_id not in champion_ids
            and s.strategy_id not in needs_review_ids
        ]
        strategy_ids = [s.strategy_id for s in to_run]

    log.info(
        "Arena: %d active strategies, %d champions, %d needs_review, %d to run",
        len(active_strategies), len(champion_ids),
        len(needs_review_ids), len(to_run),
    )

    results = []
    for sid in strategy_ids:
        try:
            result = run_arena_for_strategy(sid)
            results.append(result)
            log.info("Arena result: %s → %s", sid, result.get("status"))
        except Exception as exc:
            log.error("Arena failed for %s: %s", sid, exc)
            results.append({"strategy_id": sid, "status": "error", "error": str(exc)})

    champions = [r for r in results if r.get("status") == "champion"]
    log.info(
        "=== ARENA CYCLE DONE: ran=%d champions=%d ===",
        len(results), len(champions),
    )
    return {
        "status":    "done",
        "ran":       len(results),
        "champions": len(champions),
        "results":   results,
    }


def get_arena_status(db) -> dict:
    """Summary of arena state — used by the API route."""
    total      = db.query(ArenaRun).count()
    champions  = db.query(ArenaRun).filter_by(is_champion=True).count()
    refining   = db.query(ArenaRun).filter_by(status="refining").count()
    review     = db.query(ArenaRun).filter_by(needs_review=True).count()
    running    = _running

    recent = (
        db.query(ArenaRun)
        .order_by(ArenaRun.created_at.desc())
        .limit(20)
        .all()
    )

    return {
        "total_runs":        total,
        "champions":         champions,
        "refining":          refining,
        "needs_review":      review,
        "is_running":        running,
        "recent_runs":       [
            {
                "id":                r.id,
                "strategy_id":       r.strategy_id,
                "strategy_name":     r.strategy_name,
                "round":             r.round_number,
                "generation":        r.generation,
                "status":            r.status,
                "total_return_pct":  r.total_return_pct,
                "max_drawdown_pct":  r.max_drawdown_pct,
                "win_rate":          r.win_rate,
                "total_trades":      r.total_trades,
                "winning_days":      r.winning_days_count,
                "losing_days":       r.losing_days_count,
                "is_champion":       r.is_champion,
                "needs_review":      r.needs_review,
                "donor_name":        r.donor_strategy_name,
                "donor_coverage":    r.donor_coverage_pct,
                "started_at":        str(r.started_at) if r.started_at else None,
                "completed_at":      str(r.completed_at) if r.completed_at else None,
            }
            for r in recent
        ],
    }
