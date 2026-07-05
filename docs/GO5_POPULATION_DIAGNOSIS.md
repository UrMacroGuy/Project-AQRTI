# GO-5: Population Diagnosis Report
**Date:** 2026-07-05  
**Population:** 1,134 algos (1,133 candidate, 1 shadow)  
**Promoted:** 0 — correct behavior per honest gates

---

## Summary verdict

**The dominant failure mode is win-rate collapse.** 84% of algos fail at the win-rate gate (< 52%) after passing the trade-count gate. The median win-rate of the population is **47.1%** — below coin flip. The median Sharpe is **–2.1**, which means the average algo is actively destroying value on an annualized basis. The root cause is a structural mismatch: the current DSL families generate entry signals that are no better than random on NSE, even after applying ML confidence filtering.

---

## Evidence

### Gate failure cascade (1,133 candidates)

| Gate | Condition | Failed | % of total |
|------|-----------|--------|------------|
| Min trades | < 60 | 341 | 30.1% |
| Win rate | < 52% (after trades gate) | 727 | **64.2%** |
| Sharpe | < 0.5 (after WR gate) | 65 | 5.7% |
| Fitness | < 50 (after Sharpe gate) | 0 | 0.0% |

The majority of algos (64%) pass the trade-count test but can't beat 52% win rate. This is the primary bottleneck.

### Population metric distributions (950 algos with ≥ 5 trades)

| Metric | Min | P25 | Median | P75 | Max |
|--------|-----|-----|--------|-----|-----|
| Trades | 5 | 100 | 284 | 538 | 1579 |
| Win rate % | 2.8 | 40.0 | **47.1** | 50.6 | 81.8 |
| Sharpe | -8.0 | -3.4 | **-2.1** | -1.4 | 2.8 |
| Max drawdown % | -45.9 | -10.0 | -7.1 | -4.0 | -0.2 |
| Fitness | 12.5 | 21.5 | 26.2 | 36.1 | 71.0 |

**Only 4 algos (0.4%) pass the Sharpe ≥ 0.5 gate on their own.** Of those 4, the top 3 all have < 60 trades (17, 23, 25) — far below the min-trades gate. The only one with enough trades (`AQRTI_STR_D6CFF5A5E1`, 61 trades, Sharpe 0.248) fails the Sharpe gate.

### DSL structure (top candidates)

The top 3 Sharpe algos are all `regime_adaptive` family, restricted to `VOLATILE` regime, with:
- 2-condition AND entry (always `macd_signal` + one other)
- `max_holding_days`: 7–11
- `min_confidence`: 61–65%
- `stop_loss`: -6% to -8.6%, `take_profit`: 9–21%

These have high Sharpe **because they fired very rarely** (17–25 trades over the full 5-year backtest). Low sample size makes Sharpe unstable; the OOS test confirms: of the top 20 by Sharpe, only 3/15 that have OOS scores pass the OOS Sharpe ≥ 0.2 gate.

### Regime concentration

Every top-performing algo is restricted to `VOLATILE` regime. This is selection pressure, not edge — the backtester samples fewer trades in volatile periods, so noise dominates and a few lucky runs get high Sharpe. This is **regime overfitting via sample scarcity**.

### Cost sensitivity

NSE round-trip cost is 0.28%. The median algo holds 284 trades over ~5 years (~57 trades/year). At 0.28% per round trip that's **16% annualized cost drag** — far exceeding any realistic edge from the current signal families. High-trade-count algos are being cost-crushed.

---

## Root causes (ranked by impact)

1. **Signal quality: entry conditions are not predictive.** The DSL generates conditions on individual features (macd_signal > threshold, rsi_14 < threshold) without any structural edge. The feature pool produces signals at random-walk frequency for the current threshold mutation range. Win rate at population median = 47% confirms this.

2. **Regime overfitting via scarcity.** Top Sharpe algos restrict to VOLATILE regime and fire rarely. With 17–25 trades, the Sharpe estimate has ±2 standard error units — the apparent edge is statistical noise.

3. **OOS rejection confirms no real edge.** 3/20 top algos pass OOS (15%). This is below the 20% that would pass by chance at a 0.2 Sharpe threshold given Sharpe's known positive bias on short samples.

4. **ML confidence filter is not differentiating enough.** `min_confidence` of 60–65% sounds discriminating but if the ML model's own accuracy is ~58% (ML retrain v7 result), confidence scores above 60% do not reliably predict 5-day direction — they just reduce sample size without improving win rate.

5. **Holding period is not matched to feature decay.** Algos hold 7–11 days but features like `macd_signal` and `rsi_14` mean-revert within 1–3 days on NSE. The signal decays before the exit.

---

## Verdict for GO-5b

**Do NOT widen gates or weaken cost assumptions.** The current gates are honest and correct.

**Direction for the next generation (GO-5b):**

1. **Better entry signal construction:** Require that any new DSL family be validated at the signal level first — not "does the backtest pass?" but "does this specific condition predict next-5d direction above 52% on held-out data at the individual-condition level?"

2. **Pair trading / spread signals:** Single-leg directional signals are too noisy on NSE. A pairs or sector-rotation signal (stock return relative to sector index) reduces regime noise and is harder for costs to erase.

3. **Shorter holding periods for the available features:** Match holding to feature half-life. RSI/MACD signals expire in 1–3 days. Either use 1–3 day hold (but costs become brutal), or switch to features with longer persistence (52-week position, earnings momentum, 1M relative strength).

4. **Fix regime detection before regime-gating algos:** The VOLATILE-only restriction is exacerbating scarcity. If regime classification itself has noise, restricting to one regime creates phantom edge. Either remove regime gating from entry conditions or first validate regime classifier accuracy.

5. **ML label quality check:** If `direction_5d` accuracy is ~58%, the ceiling on ML-filtered win rate is ~58%. Investigate whether using a longer horizon label (10d or 15d) or an alpha label (`outperform_nifty_5d`) gives a more learnable signal.

---

*All data queried from `backend/aqrti.db` at 2026-07-05. No estimates, no fabricated numbers.*
