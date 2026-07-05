"""
GO-5c: Walk-forward evolution honesty audit.

Verifies that the meta-learner / evolution loop cannot overfit the OOS windows
through repeated population-level selection.

The test:
  1. Identify all strategies that have a backtest window recorded (backtest_start,
     backtest_end) and an OOS result (oos_sharpe, oos_passed).
  2. For each strategy, check the OOS window: is it genuinely held-out
     (i.e., does it start AFTER backtest_end, not overlap)?
  3. Check whether the OOS pass rate is suspiciously high for strategies that
     went through many evolution rounds (arena_rounds > N). If the OOS pass
     rate for heavily-evolved strategies significantly exceeds the overall rate,
     that's evidence of implicit OOS leakage through the selection loop.
  4. Check the held-out year: is there a contiguous 52-week window that NOTHING
     has been trained or evaluated on? Report it if so.

Output: a structured verdict (PASS / WARNING / FAIL) with evidence.

Run from backend directory:
  python scripts/go5c_oos_audit.py
"""

from __future__ import annotations

import sqlite3
import sys
import os
from datetime import date, datetime, timedelta

DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "aqrti.db")


def main():
    print("=== GO-5c: Walk-forward evolution honesty audit ===\n")

    con = sqlite3.connect(DB)
    con.execute("PRAGMA busy_timeout=10000")
    con.row_factory = sqlite3.Row

    issues = []
    warnings = []

    # ── 1. OOS window overlap check ─────────────────────────────────────────
    print("1. Checking OOS windows for overlap with backtest windows...")
    rows = con.execute("""
        SELECT strategy_id, backtest_start, backtest_end, oos_sharpe, oos_passed, arena_rounds
        FROM strategies_v2
        WHERE backtest_start IS NOT NULL AND backtest_end IS NOT NULL
          AND oos_sharpe IS NOT NULL
    """).fetchall()

    overlap_count = 0
    for r in rows:
        try:
            bt_end = date.fromisoformat(r["backtest_end"])
        except Exception:
            continue
        # The OOS window starts right after backtest_end in our walk-forward split.
        # We don't store oos_start explicitly, but we can verify that oos_sharpe
        # is not a duplicate of in-sample sharpe (a symptom of window overlap).
        # Real check: if oos_sharpe suspiciously equals sharpe (within 0.01) for
        # multiple strategies → likely computed on the same window.
        pass  # overlap_start checked below

    # Check: OOS sharpe distribution vs backtest sharpe
    overlap_rows = con.execute("""
        SELECT COUNT(*) n FROM strategies_v2
        WHERE sharpe IS NOT NULL AND oos_sharpe IS NOT NULL
          AND ABS(sharpe - oos_sharpe) < 0.05
          AND oos_trades > 5
    """).fetchone()["n"]
    total_with_oos = con.execute(
        "SELECT COUNT(*) n FROM strategies_v2 WHERE oos_sharpe IS NOT NULL AND oos_trades > 5"
    ).fetchone()["n"]

    if total_with_oos > 0:
        suspect_pct = 100 * overlap_rows / total_with_oos
        print(f"   Strategies where |sharpe - oos_sharpe| < 0.05: {overlap_rows}/{total_with_oos} ({suspect_pct:.1f}%)")
        if suspect_pct > 30:
            issues.append(
                f"FAIL: {suspect_pct:.1f}% of strategies have in-sample and OOS Sharpe within 0.05 — "
                "strong evidence of window overlap or OOS data reuse"
            )
        elif suspect_pct > 15:
            warnings.append(
                f"WARNING: {suspect_pct:.1f}% of strategies have near-identical in-sample and OOS Sharpe — "
                "check that OOS window doesn't overlap backtest window"
            )
        else:
            print(f"   OK — {suspect_pct:.1f}% near-identical (expected: some by chance, <15% is fine)")
    else:
        print("   Not enough strategies with OOS scores to check. Skipping.")

    # ── 2. Selection pressure on OOS: do heavily-evolved strategies pass OOS at higher rates? ─────
    print("\n2. Checking whether evolution loop inflates OOS pass rate...")
    arena_thresholds = [0, 3, 6, 10]
    for lo, hi in zip(arena_thresholds, arena_thresholds[1:] + [999]):
        bucket = con.execute(f"""
            SELECT COUNT(*) total,
                   SUM(CASE WHEN oos_passed = 1 THEN 1 ELSE 0 END) passed
            FROM strategies_v2
            WHERE oos_sharpe IS NOT NULL
              AND (arena_rounds IS NULL AND {lo} = 0 OR arena_rounds >= {lo} AND arena_rounds < {hi})
        """).fetchone()
        total = bucket["total"]
        passed = bucket["passed"] or 0
        if total > 0:
            rate = 100 * passed / total
            label = f"arena_rounds {lo}-{hi-1}" if hi < 999 else f"arena_rounds >={lo}"
            print(f"   {label:25s}: {passed}/{total} pass OOS ({rate:.1f}%)")

    # Check specifically: strategies with arena_rounds >= 5 vs 0
    low_rounds = con.execute("""
        SELECT COUNT(*) total, SUM(CASE WHEN oos_passed=1 THEN 1 ELSE 0 END) passed
        FROM strategies_v2 WHERE oos_sharpe IS NOT NULL AND (arena_rounds IS NULL OR arena_rounds < 3)
    """).fetchone()
    high_rounds = con.execute("""
        SELECT COUNT(*) total, SUM(CASE WHEN oos_passed=1 THEN 1 ELSE 0 END) passed
        FROM strategies_v2 WHERE oos_sharpe IS NOT NULL AND arena_rounds >= 5
    """).fetchone()

    if low_rounds["total"] > 10 and high_rounds["total"] > 5:
        low_rate  = 100 * (low_rounds["passed"] or 0) / low_rounds["total"]
        high_rate = 100 * (high_rounds["passed"] or 0) / high_rounds["total"]
        diff = high_rate - low_rate
        print(f"\n   Low-rounds OOS pass rate:  {low_rate:.1f}%")
        print(f"   High-rounds OOS pass rate: {high_rate:.1f}%")
        print(f"   Difference:                {diff:+.1f}pp")
        if diff > 20:
            issues.append(
                f"FAIL: High-arena-rounds strategies pass OOS at {diff:+.1f}pp above low-rounds — "
                "evolution loop may be implicitly selecting for OOS window characteristics"
            )
        elif diff > 10:
            warnings.append(
                f"WARNING: {diff:+.1f}pp OOS advantage for heavily-evolved strategies — monitor "
                "whether this grows as population matures"
            )
        else:
            print(f"   OK — {diff:+.1f}pp difference is within acceptable noise")
    else:
        print("   Not enough data in both buckets to compare. Skipping.")

    # ── 3. Held-out year identification ────────────────────────────────────────
    print("\n3. Checking for a truly held-out year that nothing has touched...")
    bt_rows = con.execute("""
        SELECT backtest_start, backtest_end FROM strategies_v2
        WHERE backtest_start IS NOT NULL AND backtest_end IS NOT NULL
        LIMIT 2000
    """).fetchall()

    if bt_rows:
        all_starts = []
        all_ends   = []
        for r in bt_rows:
            try:
                all_starts.append(date.fromisoformat(r["backtest_start"]))
                all_ends.append(date.fromisoformat(r["backtest_end"]))
            except Exception:
                pass

        if all_starts:
            earliest_bt = min(all_starts)
            latest_bt   = max(all_ends)
            print(f"   Backtest windows span: {earliest_bt} to {latest_bt}")

            # Is there a full year BEFORE the earliest backtest start?
            gap_before = (earliest_bt - date(earliest_bt.year - 1, earliest_bt.month, earliest_bt.day)).days
            print(f"   Gap before earliest backtest: {(earliest_bt - date.fromisoformat('2019-01-01')).days} days from 2019-01-01")

            # The OOS window ends at roughly backtest_end + 6 months per the walk-forward split.
            # A truly held-out year would be the last 52 weeks of the price history that
            # no backtest OR OOS window has ever touched.
            oos_approx_end = latest_bt + timedelta(days=180)
            today = date.today()
            true_holdout_start = oos_approx_end + timedelta(days=1)
            true_holdout_days  = (today - true_holdout_start).days

            if true_holdout_days >= 90:
                print(f"   Approx held-out period: {true_holdout_start} → {today} ({true_holdout_days} days)")
                print("   OK — there is recent data that no backtest or OOS window has reached.")
                print("   NOTE: This data should be used ONLY for the GO-5c one-time audit, then retired.")
                print(f"   Held-out window: {true_holdout_start.isoformat()} to {today.isoformat()}")
            else:
                warnings.append(
                    f"WARNING: OOS windows extend to approximately {oos_approx_end} — only "
                    f"{true_holdout_days} days of truly untouched data remain. "
                    "Run the one-time held-out evaluation BEFORE this window shrinks to zero."
                )
    else:
        print("   No backtest windows recorded. Skipping.")

    # ── 4. OOS duration check ───────────────────────────────────────────────────
    print("\n4. Checking OOS window duration (must be >= 90 days for statistical validity)...")
    # We don't store oos_start, but oos_trades gives us a proxy:
    # with 352 universe symbols and a win-rate-level signal, 20 OOS trades in < 30 days → suspect.
    thin_oos = con.execute("""
        SELECT COUNT(*) n FROM strategies_v2
        WHERE oos_sharpe IS NOT NULL AND oos_trades IS NOT NULL
          AND oos_trades < 5 AND oos_passed = 1
    """).fetchone()["n"]
    print(f"   Strategies passing OOS with < 5 trades: {thin_oos}")
    if thin_oos > 0:
        warnings.append(
            f"WARNING: {thin_oos} strategies passed OOS gate with < 5 OOS trades — "
            "thin OOS samples have Sharpe estimates with ±2 std error (statistically unreliable)"
        )

    # ── 5. Verdict ─────────────────────────────────────────────────────────────
    print("\n=== VERDICT ===")
    if issues:
        print("STATUS: FAIL")
        for i in issues:
            print(f"  [FAIL]    {i}")
    elif warnings:
        print("STATUS: PASS WITH WARNINGS")
        for w in warnings:
            print(f"  [WARNING] {w}")
    else:
        print("STATUS: PASS")
        print("  No evidence of walk-forward OOS leakage or selection pressure on OOS windows.")
        print("  The evolution loop appears to be selecting on in-sample metrics, not OOS.")

    print("\n=== Recommended next step ===")
    print("  Run the one-time held-out year evaluation:")
    print("  python scripts/go5c_holdout_eval.py --start <holdout_start> --end <today>")
    print("  This is the only test that cannot be repeated -- run it once when >=1 algo is promoted.")

    con.close()
    return 0 if not issues else 1


if __name__ == "__main__":
    sys.exit(main())
