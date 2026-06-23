# Graph Report - .  (2026-06-22)

## Corpus Check
- Corpus is ~6,550 words - fits in a single context window. You may not need a graph.

## Summary
- 87 nodes · 130 edges · 10 communities (8 shown, 2 thin omitted)
- Extraction: 78% EXTRACTED · 22% INFERRED · 0% AMBIGUOUS · INFERRED: 29 edges (avg confidence: 0.89)
- Token cost: 18,500 input · 5,200 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Dashboard UI & Visualization|Dashboard UI & Visualization]]
- [[_COMMUNITY_Strategy Discovery & Backtesting|Strategy Discovery & Backtesting]]
- [[_COMMUNITY_Multi-Agent Coordination|Multi-Agent Coordination]]
- [[_COMMUNITY_ML Model Architecture|ML Model Architecture]]
- [[_COMMUNITY_Learning Engine & Pattern Matching|Learning Engine & Pattern Matching]]
- [[_COMMUNITY_News & Sentiment Intelligence|News & Sentiment Intelligence]]
- [[_COMMUNITY_Execution & Trading Engine|Execution & Trading Engine]]
- [[_COMMUNITY_Data Pipeline & Feature Store|Data Pipeline & Feature Store]]
- [[_COMMUNITY_VSCode Launch Config|VSCode Launch Config]]
- [[_COMMUNITY_VSCode Settings|VSCode Settings]]

## God Nodes (most connected - your core abstractions)
1. `Model Architecture — Ensemble Intelligence Core` - 19 edges
2. `Autonomous Agent System — Multi-Agent Architecture` - 11 edges
3. `Strategy Discovery Engine — Autonomous Alpha Generation` - 11 edges
4. `Ensemble Engine` - 9 edges
5. `Data Architecture — Foundation Layer` - 8 edges
6. `Learning Engine — Self-Improvement & Knowledge Evolution` - 8 edges
7. `Master Implementation Roadmap` - 8 edges
8. `Backtesting Framework` - 7 edges
9. `init()` - 6 edges
10. `Risk Engine — Capital Preservation Framework` - 6 edges

## Surprising Connections (you probably didn't know these)
- `Model D — Sentiment Model` --semantically_similar_to--> `Sentiment Engine — Market Psychology Measurement`  [INFERRED] [semantically similar]
  MODEL_ARCHITECTURE.md → SENTIMENT_ENGINE.md
- `Confidence Calibration` --semantically_similar_to--> `Confidence Engine`  [INFERRED] [semantically similar]
  LEARNING_ENGINE.md → MODEL_ARCHITECTURE.md
- `Strategy Graveyard (Permanently stored failed strategies)` --semantically_similar_to--> `Learning Database (knowledge_predictions, knowledge_strategies, knowledge_regimes, knowledge_failures, knowledge_patterns)`  [INFERRED] [semantically similar]
  STRATEGY_DISCOVERY_ENGINE.md → LEARNING_ENGINE.md
- `Impact Scoring (0-100)` --semantically_similar_to--> `Model H — Event Impact Model`  [INFERRED] [semantically similar]
  NEWS_INTELLIGENCE_ENGINE.md → MODEL_ARCHITECTURE.md
- `Position Sizing (Confidence-based: 1%-5% allocation)` --semantically_similar_to--> `Capital Allocation Rules (Confidence-Risk Based)`  [INFERRED] [semantically similar]
  RISK_ENGINE.md → PORTFOLIO_OPTIMIZATION_ENGINE.md

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **AQRTI Core Intelligence Pipeline (Data→Features→Models→Ensemble→Risk→Execution)** — data_architecture, feature_store, ensemble_engine, risk_engine, execution_engine, learning_engine [EXTRACTED 0.95]
- **Strategy Lifecycle Pipeline (Discovery→Backtest→Validate→Paper→Production→Retire)** — strategy_discovery_engine, backtesting_framework, walk_forward_validation, paper_trading_engine, strategy_status_lifecycle, strategy_graveyard [EXTRACTED 0.95]
- **Multi-Agent Coordination (Commander orchestrates specialized agents via knowledge layer)** — commander_agent, data_agent, prediction_agent, risk_agent, learning_agent, portfolio_agent [EXTRACTED 0.95]

## Communities (10 total, 2 thin omitted)

### Community 0 - "Dashboard UI & Visualization"
Cohesion: 0.18
Nodes (15): Chart.js Library (v4.4.0), init(), marketData, mockOverview, news, opportunities, renderMarketChart(), renderNews() (+7 more)

### Community 1 - "Strategy Discovery & Backtesting"
Cohesion: 0.18
Nodes (13): Alpha Score (0-100 per strategy), Backtesting Framework, Dashboard Architecture — Intelligence Terminal Design, Institutional Tier Strategies (5-15 highest quality, multi-regime stable), Master Implementation Roadmap, Monte Carlo Simulation, Strategy Agent, Strategy Decay Detection (+5 more)

### Community 2 - "Multi-Agent Coordination"
Cohesion: 0.24
Nodes (12): Autonomous Agent System — Multi-Agent Architecture, Capital Allocation Rules (Confidence-Risk Based), Circuit Breakers (Auto-disable on abnormal loss/volatility/model failure), Commander Agent, Data Agent, Portfolio Agent, Portfolio Optimization Engine, Position Sizing (Confidence-based: 1%-5% allocation) (+4 more)

### Community 3 - "ML Model Architecture"
Cohesion: 0.29
Nodes (12): Model A — Direction Model (LightGBM/XGBoost/CatBoost), Ensemble Engine, Model B — Expected Return Model, Model E — Market Regime Model, Meta Intelligence Layer (Judge the Judges), Model Architecture — Ensemble Intelligence Core, Model I — Pattern Matching Engine, Model G — Relative Strength Model (+4 more)

### Community 4 - "Learning Engine & Pattern Matching"
Cohesion: 0.20
Nodes (10): Confidence Calibration, Confidence Engine, Database Schema (SQLite→PostgreSQL), Knowledge Score (0-100), Learning Agent, Learning Database (knowledge_predictions, knowledge_strategies, knowledge_regimes, knowledge_failures, knowledge_patterns), Learning Engine — Self-Improvement & Knowledge Evolution, Pattern Matching Engine (+2 more)

### Community 5 - "News & Sentiment Intelligence"
Cohesion: 0.25
Nodes (8): Entity Extraction (Company/Sector/People/Events), Model H — Event Impact Model, Impact Scoring (0-100), News Agent, News Intelligence Engine, Sentiment Agent, Sentiment Engine — Market Psychology Measurement, Sentiment Velocity & Acceleration

### Community 6 - "Execution & Trading Engine"
Cohesion: 0.29
Nodes (7): Broker Integration (Zerodha / Angel One / Upstox), Execution Engine — Signal Delivery & Trade Execution, Execution Phases (Research→Paper→Semi-Auto→Autonomous), Model Promotion Pipeline (Dev→Test→Validation→Shadow→Paper→Production), Order Flow (Signal→Risk Check→Portfolio Check→Execution→Monitoring→Exit), Paper Trading Engine — Virtual Capital Validation, Production Readiness Score (0-100)

### Community 7 - "Data Pipeline & Feature Store"
Cohesion: 0.29
Nodes (7): Daily Ingestion Pipeline, Data Architecture — Foundation Layer, Data Immutability Principle, Feature Agent, Feature Store (300+ Features), Model Training Pipeline, Walk-Forward Validation

## Knowledge Gaps
- **25 isolated node(s):** `tabs`, `sections`, `mockOverview`, `marketData`, `opportunities` (+20 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **2 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Master Implementation Roadmap` connect `Strategy Discovery & Backtesting` to `ML Model Architecture`, `Learning Engine & Pattern Matching`, `News & Sentiment Intelligence`, `Execution & Trading Engine`, `Data Pipeline & Feature Store`?**
  _High betweenness centrality (0.444) - this node is a cross-community bridge._
- **Why does `Model Architecture — Ensemble Intelligence Core` connect `ML Model Architecture` to `Strategy Discovery & Backtesting`, `Multi-Agent Coordination`, `Learning Engine & Pattern Matching`, `News & Sentiment Intelligence`, `Execution & Trading Engine`, `Data Pipeline & Feature Store`?**
  _High betweenness centrality (0.338) - this node is a cross-community bridge._
- **Why does `Dashboard Architecture — Intelligence Terminal Design` connect `Strategy Discovery & Backtesting` to `Dashboard UI & Visualization`?**
  _High betweenness centrality (0.298) - this node is a cross-community bridge._
- **Are the 3 inferred relationships involving `Model Architecture — Ensemble Intelligence Core` (e.g. with `Learning Engine — Self-Improvement & Knowledge Evolution` and `Model Training Pipeline`) actually correct?**
  _`Model Architecture — Ensemble Intelligence Core` has 3 INFERRED edges - model-reasoned connections that need verification._
- **Are the 3 inferred relationships involving `Strategy Discovery Engine — Autonomous Alpha Generation` (e.g. with `Learning Engine — Self-Improvement & Knowledge Evolution` and `Strategy Agent`) actually correct?**
  _`Strategy Discovery Engine — Autonomous Alpha Generation` has 3 INFERRED edges - model-reasoned connections that need verification._
- **What connects `tabs`, `sections`, `mockOverview` to the rest of the system?**
  _26 weakly-connected nodes found - possible documentation gaps or missing edges._