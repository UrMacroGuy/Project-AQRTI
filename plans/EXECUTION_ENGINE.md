# EXECUTION_ENGINE.md

# PROJECT AQRTI
## Signal Delivery & Trade Execution

Version: 1.0

---

## PHASES

### PHASE 1: Research Only
- No Real Trades
- **Outputs:**
  - Daily Rankings
  - Opportunity Reports
  - Risk Reports

### PHASE 2: Paper Trading
- Simulated Capital
- **Track:**
  - Returns
  - Drawdowns
  - Accuracy
  - Strategy Performance

### PHASE 3: Semi-Automated Trading
- AQRTI Generates Signals
- Human Approves Trades

### PHASE 4: Autonomous Trading
- Broker Integration
- Automated Orders
- Automated Risk Controls

---

## SIGNAL FORMAT

- Ticker
- Direction
- Confidence
- Expected Return
- Risk
- Position Size
- Strategy
- Reasoning

### EXAMPLE
- **Ticker:** RELIANCE
- **Direction:** Bullish
- **Confidence:** 84
- **Expected Return:** 3.1%
- **Risk:** Low
- **Position:** 4%
- **Strategy:** Momentum + Event

---

## ORDER FLOW

```
     Signal Generated
            ↓
        Risk Check
            ↓
     Portfolio Check
            ↓
   Execution Approval
            ↓
     Order Placement
            ↓
        Monitoring
            ↓
      Exit Management
```

---

## POSITION MONITORING

### Track:
- Live PnL
- Risk Drift
- Volatility
- News Changes
- Sentiment Changes

---

## EXIT RULES

- Target Reached
- Stop Hit
- Signal Reversal
- Risk Trigger
- Regime Change

---

## BROKER PHASE

### Future Support:
- Zerodha
- Angel One
- Upstox

---

## OBJECTIVE

Transform AQRTI from an intelligence platform into a disciplined execution system without compromising risk controls.
