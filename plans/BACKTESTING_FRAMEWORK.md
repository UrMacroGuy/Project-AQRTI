# BACKTESTING_FRAMEWORK.md

# PROJECT AQRTI

## PURPOSE

Backtesting determines whether a strategy deserves capital.

A strategy that cannot survive historical validation is rejected.

---

## TEST TYPES

### Historical Backtest
Evaluate strategy on historical data.

### Walk Forward Validation
```
     Train
       ↓
     Test
       ↓
Advance Window
       ↓
    Repeat
```

### Monte Carlo Simulation
- Randomize trades.
- Measure robustness.

### Stress Testing
Evaluate during:
- COVID Crash
- Banking Crises
- Elections
- High Volatility

---

## REQUIRED METRICS

- CAGR
- Sharpe Ratio
- Sortino Ratio
- Profit Factor
- Win Rate
- Max Drawdown
- Average Trade
- Exposure
- Recovery Factor
- Expectancy

---

## MINIMUM REQUIREMENTS

- **Profit Factor:** > 1.3
- **Sharpe Ratio:** > 1
- **Expectancy:** Positive Expectancy
- **Drawdown:** Controlled Drawdown

---

## STRATEGY STATUS

- Rejected
- Candidate
- Validated
- Production
- Institutional Tier

---

## OUTPUT

- Full strategy performance report.
- Historical equity curve.
- Risk profile.
- Regime performance.
