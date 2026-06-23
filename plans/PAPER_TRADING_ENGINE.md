# PAPER_TRADING_ENGINE.md

# PROJECT AQRTI
## Virtual Capital Validation Environment

Version: 1.0

---

## PURPOSE

Before AQRTI is allowed to manage real capital, it must prove itself using simulated capital.

Paper trading is the bridge between backtesting and live deployment.

---

## PHILOSOPHY

- Backtests can lie.
- Markets do not.
- **Paper trading exposes:**
  - Signal latency
  - Regime shifts
  - News shocks
  - Strategy decay
  - Model weaknesses
- Without risking money.

---

## INITIAL CAPITAL

- **Default:** ₹100,000
- **Configurable:** ₹10,000 - ₹10,000,000

---

## DAILY PROCESS

```
    Market Close
         ↓
Generate Predictions
         ↓
 Generate Portfolio
         ↓
  Simulate Entries
         ↓
  Track Positions
         ↓
     Track PnL
         ↓
  Generate Reports
         ↓
 Evaluate Decisions
```

---

## TRADE SIMULATION

Each simulated trade stores:
- Trade ID
- Symbol
- Entry Date
- Entry Price
- Exit Date
- Exit Price
- Position Size
- Strategy Used
- Confidence
- Predicted Return
- Actual Return
- Profit/Loss

---

## PERFORMANCE TRACKING

### Metrics
- Total Return
- CAGR
- Sharpe Ratio
- Sortino Ratio
- Profit Factor
- Max Drawdown
- Win Rate
- Expectancy
- Average Hold Time

---

## DAILY REPORT

- Top Opportunities
- Open Positions
- Closed Positions
- Portfolio Value
- Risk Exposure
- Strategy Performance

---

## LEADERBOARDS

### STRATEGY LEADERBOARD
Every strategy ranked by:
- Profitability
- Consistency
- Risk
- Drawdown
- Longevity

### MODEL LEADERBOARD
Every model ranked by:
- Accuracy
- Calibration
- Confidence Quality
- Return Contribution

---

## PROMOTION REQUIREMENTS

- **Minimum Paper Trading Duration:** 60 Days
- **Recommended Duration:** 120 Days
- **Requirements:**
  - Positive Return
  - Acceptable Drawdown
  - Positive Expectancy
  - Consistent Performance

---

## FAILURE DETECTION

### Detect:
- Overconfidence
- Signal Drift
- Strategy Decay
- Regime Mismatch
- Data Quality Issues

---

## OUTPUT

- **Production Readiness Score:** 0-100

---

## OBJECTIVE

Prove AQRTI deserves real capital before risking real money.
