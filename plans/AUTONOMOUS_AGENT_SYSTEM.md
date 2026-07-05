# AUTONOMOUS_AGENT_SYSTEM.md

> ⚠️ **Historical design document (June 2026, v1.0).** Kept for reference. Numbers, thresholds, and architecture here are aspirational or superseded. Current truth: `PROJECT_DIARY.md` (system), `docs/STRATEGY_ARENA.md` (arena), `backend/strategies/promotion_config.py` (gates), `DATABASE_AND_TRAINING.md` (DB/ML).


# PROJECT AQRTI
## Multi-Agent Intelligence Architecture

Version: 1.0

---

## PURPOSE

AQRTI is not one AI.

AQRTI is a collection of specialized agents.

Each agent has a narrow responsibility.

---

## AGENT HIERARCHY

```
Commander Agent
       ↓
Research Agents
       ↓
Analysis Agents
       ↓
Validation Agents
       ↓
Execution Agents
```

---

## AGENTS

### AGENT 1: DATA AGENT
#### Responsibilities:
- Collect Market Data
- Validate Data
- Store Data
- Monitor Missing Data

### AGENT 2: NEWS AGENT
#### Responsibilities:
- Collect News
- Extract Events
- Identify Companies
- Generate Impact Scores

### AGENT 3: SENTIMENT AGENT
#### Responsibilities:
- Analyze Sentiment
- Measure Narrative Strength
- Track Changes

### AGENT 4: FEATURE AGENT
#### Responsibilities:
- Generate Features
- Validate Features
- Monitor Feature Drift

### AGENT 5: PREDICTION AGENT
#### Responsibilities:
- Run Models
- Generate Scores
- Generate Forecasts

### AGENT 6: STRATEGY AGENT
#### Responsibilities:
- Generate Strategies
- Mutate Strategies
- Retire Strategies

### AGENT 7: VALIDATION AGENT
#### Responsibilities:
- Backtesting
- Walk-Forward Testing
- Stress Testing

### AGENT 8: LEARNING AGENT
#### Responsibilities:
- Analyze Mistakes
- Extract Knowledge
- Improve System

### AGENT 9: RISK AGENT
#### Responsibilities:
- Position Sizing
- Risk Limits
- Portfolio Protection

### AGENT 10: PORTFOLIO AGENT
#### Responsibilities:
- Capital Allocation
- Portfolio Construction
- Rebalancing

---

## AGENT COMMUNICATION

```
     Agent
       ↓
 Message Queue
       ↓
Knowledge Layer
       ↓
  Target Agent
```

---

## COMMANDER AGENT

### Responsibilities:
- System Coordination
- Priority Assignment
- Workflow Scheduling
- Health Monitoring

---

## OBJECTIVE

Create a self-improving research organization composed of software agents.
