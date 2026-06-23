# STRATEGY_DISCOVERY_ENGINE.md

# PROJECT AQRTI
## Autonomous Quantitative Research & Trading Intelligence

Version: 1.0

---

## PURPOSE

The Strategy Discovery Engine is the alpha generation system of AQRTI.

Its purpose is to continuously discover new profitable strategies.

Most retail systems use static strategies.
- *Example:* RSI Strategy, MACD Strategy, Moving Average Strategy.
- These eventually stop working.

AQRTI continuously creates, evaluates, improves, and retires strategies.

---

## CORE MISSION

Transform AQRTI from:
- **Strategy User**

Into:
- **Strategy Creator**

---

## PHILOSOPHY

- A strategy is a hypothesis.
  - *Example:* "If volume doubles and sentiment is positive, price may rise."
- AQRTI treats every strategy as an experiment.
- No strategy is trusted permanently.
- Every strategy must earn its right to exist.

---

## STRATEGY LIFECYCLE

```
   Idea Generated
         ↓
     Backtested
         ↓
     Validated
         ↓
    Paper Traded
         ↓
     Production
         ↓
     Monitored
         ↓
      Improved
         ↓
      Retired
```

---

## STRATEGY DNA

Every strategy is represented as a DNA structure.

### Example
- **Strategy ID:** `AQRTI_MOM_001`
- Entry Conditions
- Exit Conditions
- Risk Rules
- Position Sizing Rules
- Market Regime Rules
- Sector Filters
- Confidence Filters

---

## STRATEGY COMPONENTS

Every strategy contains:

### ENTRY RULES
- *Example:* Volume > 2x Average **AND** Sentiment > 70 **AND** Sector Rank > 80

### EXIT RULES
- *Example:* Target Hit **OR** Stop Loss Hit **OR** Signal Reversal

### RISK RULES
- Maximum Loss
- Maximum Position Size
- Maximum Exposure

### MARKET RULES
- Allowed Regimes
- Blocked Regimes

---

## STRATEGY CATEGORIES

AQRTI maintains multiple families:

### MOMENTUM
- **Purpose:** Follow strength.
- **Examples:** Breakouts, Relative Strength, Trend Continuation

### MEAN REVERSION
- **Purpose:** Exploit overreaction.
- **Examples:** Oversold Recovery, Gap Fill, Volatility Compression

### BREAKOUT
- **Purpose:** Capture expansion.
- **Examples:** 52 Week Breakout, Range Breakout, Volume Breakout

### SECTOR ROTATION
- **Purpose:** Follow institutional flows.
- **Examples:** Strong Sector, Weak Sector, Relative Sector Strength

### EVENT DRIVEN
- **Purpose:** Exploit information events.
- **Examples:** Earnings, Acquisitions, Buybacks, Management Changes

### SENTIMENT
- **Purpose:** Exploit information flow.
- **Examples:** News Momentum, Sentiment Shift, Narrative Expansion

### HYBRID
- **Purpose:** Combine multiple families.
- **Examples:** Momentum + Sentiment, Breakout + Event, Sector + Momentum

---

## STRATEGY GENERATION ENGINE
*AQRTI automatically generates strategies.*

### Generation Inputs
- Features
- Indicators
- Sentiment Variables
- Sector Variables
- Risk Variables
- Regime Variables

### Example System Combination
- `RS > 80`
- `Volume Ratio > 1.8`
- `Sentiment > 65`
- `Sector Score > 75`
- **Creates Strategy:** `AQRTI_GEN_00231`

---

## RULE GENERATOR
- **Purpose:** Generate candidate rules.
- **Examples:** Volume Spike, Price Acceleration, Sector Leadership, News Expansion, Sentiment Momentum, Institutional Activity.
- *Thousands of combinations produced.*

---

## STRATEGY POPULATION

- **Target Population:** 10,000+ Strategies
- **Active Research Population:** 1,000+ Strategies
- **Production Population:** 10-50 Strategies

---

## BACKTEST ENGINE
*Every generated strategy must be tested.*

### Test Periods
- Bull Markets
- Bear Markets
- Recovery Markets
- Sideways Markets
- High Volatility Markets

*No strategy survives if it only works in one environment.*

---

## VALIDATION LAYER
*Validation is stricter than backtesting.*

### Requirements
- Positive Expectancy
- Acceptable Drawdown
- Reasonable Trade Count
- Multiple Regimes
- Consistent Performance

---

## STRATEGY FITNESS SCORE

Each strategy receives a score (0-100) based on:
- Profit Factor
- Sharpe Ratio
- Sortino Ratio
- Expectancy
- Consistency
- Drawdown
- Robustness

---

## STRATEGY EVOLUTION ENGINE
*Inspired by evolutionary systems.*

```
   Parent Strategies
           ↓
        Mutation
           ↓
      New Variants
           ↓
       Backtesting
           ↓
        Selection
           ↓
        Survival
```

### Example
- **Parent Strategy:** `Volume > 2.0`
- **Mutation 1:** `Volume > 1.8`
- **Mutation 2:** `Volume > 2.3`
- **Mutation 3:** `Volume > 2.0 AND Sentiment > 60`
- *Best performer survives.*

---

## STRATEGY GRAVEYARD
*Failed strategies are never deleted.*

### Stored Information
- Failure Reason
- Performance History
- Weaknesses
- Failure Date
- Market Conditions

### Purpose
Prevent repeating old mistakes.

---

## STRATEGY MEMORY

AQRTI remembers:
- What worked
- What failed
- When it worked
- When it failed
- Why it failed

*This becomes institutional knowledge.*

---

## MARKET REGIME FILTER
*No strategy runs everywhere.*

- **Example (Momentum Strategy):**
  - **Allowed:** Bull Market, Recovery Market
  - **Blocked:** Bear Market
- **Example (Mean Reversion):**
  - **Allowed:** Range Market, High Volatility
  - **Blocked:** Strong Trend

---

## SHADOW TESTING

Before production, strategy enters shadow mode:
```
Generate Signals
       ↓
 Track Results
       ↓
No Real Trades
       ↓
Compare Outcomes
       ↓
   Validate
```
*Only then:* **Production Approval**

---

## STRATEGY DECAY DETECTION
*Markets evolve. Strategies die.*

### AQRTI monitors:
- Win Rate Decline
- Profit Factor Decline
- Sharpe Decline
- Confidence Drift

### If decay detected:
- Flag Strategy
- Reduce Weight
- Retest
- Retire if necessary

---

## STRATEGY PROMOTION PIPELINE

```
  Generated
      ↓
 Backtested
      ↓
  Validated
      ↓
 Shadow Mode
      ↓
Paper Trading
      ↓
 Production
      ↓
Institutional Tier
```

---

## INSTITUTIONAL TIER
*Highest quality strategies.*

### Requirements
- Long-Term Stability
- Multiple Regimes
- Strong Risk Metrics
- Consistent Alpha
- **Expected Count:** 5-15 Strategies

---

## ALPHA SCORE

Every strategy receives an Alpha Score (0-100) based on:
- Profitability
- Stability
- Risk
- Adaptability
- Longevity

---

## DAILY DISCOVERY CYCLE

```
   Market Close
        ↓
  Update Database
        ↓
 Generate Features
        ↓
Create New Strategies
        ↓
Mutate Existing Strategies
        ↓
    Backtest
        ↓
    Validate
        ↓
      Score
        ↓
 Promote Winners
        ↓
  Retire Losers
        ↓
Update Knowledge Base
```

---

## LONG TERM GOAL

AQRTI becomes a self-improving strategy research laboratory.

It should eventually know:
- Which strategies work
- When they work
- Why they work
- When they fail
- Why they fail

*Better than the human operator.*

---

*The objective is not to find one great strategy.*  
*The objective is to build a machine that continuously discovers great strategies.*
