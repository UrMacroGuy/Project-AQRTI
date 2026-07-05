# PORTFOLIO_OPTIMIZATION_ENGINE.md

> ⚠️ **Historical design document (June 2026, v1.0).** Kept for reference. Numbers, thresholds, and architecture here are aspirational or superseded. Current truth: `PROJECT_DIARY.md` (system), `docs/STRATEGY_ARENA.md` (arena), `backend/strategies/promotion_config.py` (gates), `DATABASE_AND_TRAINING.md` (DB/ML).


# PROJECT AQRTI

## PURPOSE

Decide how capital should be allocated.

Finding opportunities is not enough.

Capital allocation determines performance.

---

## INPUTS

- Predictions
- Confidence
- Risk Score
- Sector Score
- Strategy Score
- Volatility

---

## OBJECTIVE

### Maximize:
- Expected Return

### While Minimizing:
- Risk
- Drawdown
- Concentration

---

## ALLOCATION RULES

- **Higher Confidence**  
  ↓  
  Larger Allocation
- **Higher Risk**  
  ↓  
  Smaller Allocation

---

## DIVERSIFICATION

- Maximum Sector Exposure
- Maximum Single Position
- Maximum Correlation

---

## PORTFOLIO TYPES

- Conservative
- Balanced
- Aggressive

---

## REBALANCING

- Daily Review
- Weekly Rebalance
- Monthly Deep Review

---

## OUTPUT

- Position Size
- Portfolio Weight
- Expected Portfolio Return
- Expected Portfolio Risk

---

## OBJECTIVE

Build portfolios, not isolated trades.
