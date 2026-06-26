# Bug: `float division by zero` in Strategy Backtester

## Status
Partially fixed — root causes identified but the error persists after restart. The exact traceback line has not yet been captured because the `log.warning` call swallows the exception without a full stack trace. A traceback-logging patch is now in place (`strategy_research_loop.py:108`) and will emit the full stack on the next strategy loop cycle (~5 min after backend restart).

---

## Symptom

Every ~10–15 seconds the strategy loop logs:

```
WARNING | aqrti.strategy_research_loop | Backtest failed for AQRTI_STR_XXXXXXXX: float division by zero
```

Affects all strategies being backtested — 100% failure rate on the strategy loop.

---

## Files Involved

| File | Role |
|---|---|
| `backend/strategies/strategy_research_loop.py` | Calls `backtest_and_update`, catches exception at line 107 |
| `backend/strategies/strategy_backtester.py` | Main backtest engine — most likely location of the divide |
| `backend/strategies/strategy_metrics.py` | `compute_sharpe`, `compute_sortino`, `compute_max_drawdown`, `compute_profit_factor`, `compute_expectancy` |
| `backend/strategies/fitness_engine.py` | `score_all_strategies` — called after backtest |

---

## Known Division Sites in `strategy_backtester.py`

These are every `/` in the file — all are candidates:

### Already guarded (fixed in this session)
- **Line ~540** (exit loop): `(cur_price - pos["entry_price"]) / pos["entry_price"] * 100`  
  Fix added: `if pos["entry_price"] <= 0: continue`
- **Line ~631** (force-close): `(cur_price - pos["entry_price"]) / pos["entry_price"] * 100`  
  Fix added: `if cur_price is None or pos["entry_price"] <= 0: continue`
- **Line ~614** (entry): `if entry_price is None or entry_price <= 0: continue`
- **Line ~229** (`_technical_signal` momentum): `/ closes[-6]`  
  Fix added: `if len(closes) >= 6 and closes[-6] != 0:`

### Still potentially unguarded
- **`BacktestResult.compute_metrics()` line 311**:  
  `daily = t.pnl_pct / days` — `days = max(t.holding_days, 1)` so minimum is 1, this is safe.
- **`_rsi()` line ~170–172**: `avg_gain / period`, `avg_loss / period` — guarded with `if gains else 0.0` and `if losses else 1e-9`.
- **`_ema()` line ~180**: `sum(closes[:period]) / period` — `period` is always a positive integer constant, safe.
- **`compute_metrics()` line 293**: `len(wins) / len(closed)` — guarded by `if not closed: return`.

### Most likely remaining culprit
The error still fires after the above fixes were applied, which means one of these untouched paths is the real source:

1. **`strategy_metrics.py` — not yet visible in traceback.** `compute_sharpe` and `compute_sortino` both divide by `std` — guarded with `if std == 0: return 0.0`. Safe.

2. **The `exposure_pct` field** — computed nowhere in `BacktestResult.compute_metrics()`. May be set elsewhere with a divide.

3. **`fitness_engine.py`** — called after `backtest_and_update`. Check all `/` operators there against zero denominators.

4. **`strategy_store.py` `upsert_strategy`** — may compute a ratio on write.

---

## How to Get the Real Traceback

The traceback logging is now active. After the next strategy loop cycle fires (within 5 minutes of backend restart), look for `Traceback (most recent call last)` in:

```
backend/logs/aqrti.log
```

The line immediately following `ZeroDivisionError: float division by zero` in the traceback will identify the exact file and line number.

---

## Task for Codex

1. **Read `backend/logs/aqrti.log`** — find the first `Traceback` block that appears after timestamp `2026-06-26 17:28:27` (when backend restarted with traceback logging). The exact failing line will be in the traceback.

2. **Fix the division** at the identified line — add a `if denominator == 0` guard, replace with `max(denominator, 1e-9)`, or skip the computation and return a safe default.

3. **Search all remaining `/` operators** in these files for unguarded zero denominators:
   - `backend/strategies/strategy_backtester.py`
   - `backend/strategies/strategy_metrics.py`
   - `backend/strategies/fitness_engine.py`
   - `backend/strategies/strategy_store.py`
   - `backend/strategies/evolution_engine.py`

4. **Remove the traceback logging** added to `strategy_research_loop.py` line 107–108 once the fix is confirmed — restore it to:
   ```python
   except Exception as exc:
       log.warning("Backtest failed for %s: %s", row.strategy_id, exc)
       errors += 1
   ```

5. **Verify** by running one backtest manually:
   ```python
   # In backend/ with .venv active:
   python -c "
   import sys; sys.path.insert(0, '.')
   from aqrti.database.engine import get_db
   from strategies.strategy_backtester import backtest_strategy, get_backtest_universe
   from datetime import date, timedelta
   with get_db() as db:
       u = get_backtest_universe(db)[:5]
       r = backtest_strategy(db, 'TEST', date.today()-timedelta(days=365), date.today(), universe=u)
       print('trades:', r.trade_count, 'sharpe:', r.sharpe)
   "
   ```
   Should complete without `ZeroDivisionError`.
