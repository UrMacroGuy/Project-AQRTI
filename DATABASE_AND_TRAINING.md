# AQRTI — Database & Training Deep Dive

*A ground-truth, code-verified reference for exactly how AQRTI's SQLite database is structured, how data flows into it, and how that stored data is turned into trained ML models and tested algos (trading strategies). Companion to `PROJECT_DIARY.md`.*

**Terminology note:** from this point forward, what earlier docs called "strategies" are called **algos** — same engine (`backend/strategies/`), same DB tables (`strategies_v2`, etc.), just the name used going forward when discussing them.

Source of truth for every claim below: `backend/aqrti/database/models.py` (2,305 lines, 93 tables) plus direct reads of `backend/ml/datasets/`, `backend/features/`, `backend/ml/models/`, `backend/strategies/strategy_backtester.py`, and `backend/paper_trading/paper_engine.py`.

---

## Table of Contents

1. [The Database at a Glance](#1-the-database-at-a-glance)
2. [How Raw Data Gets In](#2-how-raw-data-gets-in)
3. [Feature Engineering — From Prices to `FeatureValue`](#3-feature-engineering)
4. [Building a Training Dataset — Table by Table](#4-building-a-training-dataset)
5. [The Data-Leakage Bug — What Happened, in Full Detail](#5-the-data-leakage-bug)
6. [Training the Models — CatBoost, NGBoost, AQRTINet](#6-training-the-models)
7. [How a Trained Model Becomes "Active"](#7-how-a-trained-model-becomes-active)
8. [How an Algo Gets Backtested — Table by Table](#8-how-an-algo-gets-backtested)
9. [How Paper Trading Reads and Writes](#9-how-paper-trading-reads-and-writes)
10. [The Full Feedback Loop](#10-the-full-feedback-loop)
11. [Every Table, Grouped by Subsystem](#11-every-table-grouped-by-subsystem)

---

## 1. The Database at a Glance

- **Engine**: SQLite, WAL (write-ahead log) mode, accessed through SQLAlchemy ORM.
- **File**: `backend/aqrti.db` (several GB; a pre-Trust-Overhaul backup exists as `aqrti.db.bak-20260702`).
- **93 tables total**, defined in one file: `backend/aqrti/database/models.py`.
- **Largest table by far**: `feature_values` (`FeatureValue`) — one row per `(symbol, date, feature_name, version)`, currently 18.5M+ rows.

Think of the database in four layers, in the order data actually flows through them:

```
RAW DATA            →  DailyPrice, IndexData, NewsEvent, CorporateEvent, OptionsChain, FIIDIIFlow, ...
       ↓
DERIVED SIGNALS      →  FeatureValue, MarketRegime, SentimentRecord
       ↓
MODEL OUTPUT          →  Prediction, ModelVersion, ConfidenceHistory
       ↓
DECISIONS & OUTCOMES  →  StrategyV2 (algos), PaperPosition, PaperTrade, FailureRecord, LessonLearned
```

Nothing upstream is ever overwritten once written (raw data is immutable — see `PROJECT_DIARY.md` §4's five data principles). Downstream tables (features, predictions, algo scores) are recomputed and *upserted*, not appended-forever, except for the explicit archive tables in §11 which exist specifically to keep a permanent, never-touched copy.

---

## 2. How Raw Data Gets In

| Raw table | Source | Written by |
|---|---|---|
| `DailyPrice` (`daily_prices`) | yfinance OHLCV, supplemented with NSE bhavcopy delivery volume | `aqrti/data/scheduler.py` daily job, step 1 |
| `IndexData` (`index_data`) | yfinance, index tickers (`^NSEI` for NIFTY etc.) | same ingestion pass |
| `NewsEvent` (`news_events`) | RSS feeds | `news/news_pipeline.py` |
| `CorporateEvent` (`corporate_events`) / `NSECorporateFiling` | NSE announcements scraper | `data_supremacy/corporate_scraper.py` |
| `FIIDIIFlow` | NSE/exchange FII-DII bulletins | `data_supremacy/fii_dii_scraper.py` |
| `OptionsChain` / `OptionsData` | NSE options chain scrape | `data_supremacy/options_scraper.py` |
| `MarketBreadth` | computed from `DailyPrice` across the universe | `data_supremacy/breadth_engine.py` |
| `SectorRotation` | computed from `DailyPrice` + `Stock.sector` | `data_supremacy/sector_rotation.py` |
| `EarningsEvent` | NSE earnings calendar scrape | `data_supremacy/earnings_scraper.py` |

`DailyPrice` columns actually populated at ingest: `symbol, date, open, high, low, close, adj_close, volume, delivery_volume, vwap, daily_return`. This is the single most important raw table — nearly everything downstream (features, algo backtests, paper trading fills) ultimately traces back to `DailyPrice.close`.

A **data integrity sweep** (`aqrti/data/integrity_check.py`) runs weekly (Saturday 10:00 IST) specifically to catch corruption in this layer: split-adjustment drift, `high < low`, non-positive prices, close outside `[low, high]`, and >25% single-day moves get flagged or healed by full re-download.

---

## 3. Feature Engineering — From Prices to `FeatureValue`

**Orchestrator**: `backend/features/feature_generator.py`. Three modes:
- `run_full_feature_generation()` — backfills every (symbol, date) missing a feature vector.
- `run_incremental_feature_generation()` — the daily-pipeline version: computes only the newest missing date per symbol.
- `run_symbol_features()` — on-demand, single symbol, doesn't write to DB (used for live inference).

### Point-in-time correctness

Full generation loops **date-major**, not symbol-major: for each calendar date, it builds one shared slice of the entire universe using `np.searchsorted` on pre-sorted date arrays, so every feature computed "as of" date `d` only ever sees rows with `date <= d`. This is the mechanism that prevents lookahead bias at the feature layer (a separate concern from the label-merge leakage bug in §5, which happened one step later in the pipeline).

### The 5 feature category modules and what `DailyPrice` columns they read

| Module | Reads | Produces (examples) |
|---|---|---|
| `price_features.py` | `close, open, low, high` | `return_1d/5d/21d/63d`, `momentum_10d/20d`, `gap_open_pct`, `breakout_distance_52w` (needs 252 rows), `support_distance_20d`, `resistance_distance_20d` |
| `volume_features.py` | `volume, delivery_volume` | `volume_ratio_20d`, `delivery_pct`, `volume_surge_flag` |
| `volatility_features.py` | `close, daily_return` + NIFTY close | `atr_14`, `bb_width_20`, `realized_vol_20d`, beta vs NIFTY |
| `trend_features.py` | `close, high, low` | `rsi_14`, `macd_signal`, `adx_14`, `ema_20/50` slopes |
| `market_features.py` | shared universe slice + `Stock.sector` | cross-sectional breadth/sector-relative features |

Minimum 30 rows of price history required before a symbol gets any feature row (`MIN_HISTORY_ROWS = 30`).

### The write itself — `features/feature_store.py`, `save_feature_vector()`

One **bulk upsert** per (symbol, date): builds a row per non-null feature `{symbol, date, feature_name, value, version, computed_at}` and issues:
```sql
INSERT INTO feature_values (...) VALUES (...)
ON CONFLICT (symbol, date, feature_name, version) DO UPDATE SET value=..., computed_at=...
```
The full generation loop commits **once per date** across every symbol (not once per symbol/feature) — this single change cut a full backfill from ~435,000 commits to ~1,236, which is why a full re-backfill is minutes rather than hours.

**Result:** `feature_values` is a long/tall table — one feature per row, not one row per symbol/date with 148 columns. Reading a full feature vector for a (symbol, date) means pivoting many rows into one wide record, which is exactly what the dataset builder does next.

---

## 4. Building a Training Dataset — Table by Table

**File**: `backend/ml/datasets/dataset_builder.py`, function `build_symbol_dataset()` (per symbol) and `build_full_dataset()` (all symbols).

### Step by step

1. **Load prices** — `DailyPrice.date, .close` for the symbol, last 2000 days (`_load_price_data`).
2. **Load NIFTY** — `IndexData.date, .close` where `index_name == "NIFTY50"` (`_load_nifty_data`), used to compute "did this stock outperform the index" labels.
3. **Load features** — `FeatureValue.date, .feature_name, .value` for the symbol at `version` (`_load_feature_vectors`), pivoted into one row per date, one column per feature name.
4. **Generate labels** — `generate_labels(price_df, nifty_df)` in `ml/datasets/label_generator.py`. This step touches **only raw close prices**, never the feature table — a deliberate separation that keeps label computation leakage-free by construction.
5. **Merge** — `feat_df.merge(labels_df, on="date", how="inner")`. Only dates present in *both* the feature table and the label table survive.
6. **Clean** — drop rows with >30% NaN features (`MAX_NAN_RATIO`); drop the whole symbol if fewer than 50 joined rows remain (`MIN_ROWS_PER_SYMBOL`).
7. **Repeat per symbol**, concatenate, sort by `(date, symbol)`.

### The label columns (`LABEL_COLUMNS`, `ml/datasets/label_generator.py`)

```
return_3d, return_5d, return_10d, return_15d         — forward returns, N trading days ahead
outperform_nifty_5d                                    — stock's 5d return minus NIFTY's 5d return
direction_5d                                            — 1 if return_5d > 0 else 0   (the main classification target)
outperform_binary                                       — 1 if outperform_nifty_5d > 0 else 0
expected_return                                         — average of return_5d and return_10d
```

These are computed with pure forward-looking integer offsets (`close[i+h] / close[i] - 1`), and any row where the future price doesn't exist yet is dropped outright — never filled in, never estimated. This is what "never train on future data" (from the original design philosophy) means concretely.

### Building the final training set — `ml/datasets/training_dataset.py`

- `prepare_training_dataset(label_col=..., top_features=40, ...)`:
  1. Builds the full dataset (above).
  2. Fills remaining feature NaNs — forward-fill within a symbol's own history, then cross-sectional median fill for anything still missing.
  3. Drops rows with a null target label.
  4. Excludes features flagged `severe`/`moderate` decay in `FeatureDecayHistory` within the last 30 days — decayed features are removed from training automatically, not just flagged for humans.
  5. Selects the **top 40 features by Information Coefficient** (Spearman rank correlation between feature and label), computed only on the **first 80%** of chronologically sorted data — so even feature *selection* can't peek at the test window.
- **Walk-forward folds** (`build_walk_forward_folds`): expanding-window, minimum 1-year train window, a **14-day embargo gap** between train end and test start (so a label computed from data a few days into the "test" period can't leak backward across the boundary), 3-month test windows sliding forward 3 months at a time. A per-fold `RobustScaler` is fit on train data only. Folds need ≥200 train rows and ≥20 test rows or are skipped.
- **Final split** (`get_final_train_test`): simple chronological 80/20 split — no shuffling anywhere in the pipeline. As the code comment puts it: *"all splits are strictly time-ordered. No test date ever appears in any training set."*
- **Failure-weighted samples** — `build_failure_sample_weights()` queries `FailureRecord` (by symbol + date + severity) and up-weights rows the model previously got wrong by 1.5×–3.0× depending on severity. This is the direct mechanism by which real mistakes get more attention in the next retrain.

---

## 5. The Data-Leakage Bug — What Happened, in Full Detail

Worth documenting fully because it's the clearest illustration of how subtle a leak can be, and it invalidated every model trained before 2026-06-26 (v2 through v5).

**The setup:** `price_features.py` computes a genuinely useful, *backward*-looking feature literally named `return_5d` (the stock's return over the past 5 days) and stores it in `FeatureValue`. Completely independently, `label_generator.py` computes a *forward*-looking label also named `return_5d` (the stock's return over the *next* 5 days) — the very thing the model is supposed to predict.

**The collision:** when `dataset_builder.py` ran `feat_df.merge(labels_df, on="date", how="inner")`, pandas found two columns both named `return_5d` and auto-renamed them to `return_5d_x` (the feature) and `return_5d_y` (the label) rather than raising an error.

**The leak:** the code that selected which columns to actually train on only excluded exact names in `LABEL_COLUMNS` — it had never heard of `return_5d_x` or `return_5d_y`, so `return_5d_x` (a backward return, strongly autocorrelated with the forward return in trending markets) sailed straight into the training feature set, sitting right next to the label it was correlated with.

**The result:** models trained on this data hit AUC = 1.0 and accuracy = 0.999 — numbers that should have been an immediate red flag rather than a celebration, since real single-stock 5-day direction prediction on liquid markets does not look like that.

**The fix**, all in `dataset_builder.py`:
1. `get_feature_columns()` now builds its exclusion set as `{label, f"{label}_x", f"{label}_y"}` for every label in `LABEL_COLUMNS`, not just the exact label name.
2. `build_symbol_dataset()` explicitly drops any leftover `_x`/`_y` merge artifacts before returning the dataset, as a second line of defense.
3. The NaN-ratio filter switched to calling the same `get_feature_columns()` helper instead of its own separate inline filter — previously it had its *own* incomplete exclusion list, a second place the same bug could have re-entered.

**Post-fix sanity check:** the best remaining feature (a breadth-related one) had an honest Information Coefficient of about 0.16, with everything else under 0.10 — described in the changelog as "realistic for direction prediction." Every model trained before the fix was invalidated and retrained from scratch.

---

## 6. Training the Models — CatBoost, NGBoost, AQRTINet

**Orchestrator**: `backend/ml/model_retrainer.py`. **Model implementations**: `backend/ml/models/{catboost_model.py, ngboost_model.py, aqrtinet_model.py}` (plus unused legacy `lightgbm_model.py`/`xgboost_model.py` — kept in the codebase but not called by the active training loop, which only trains `[CatBoostModel, NGBoostModel, AQRTINet]`).

### Feature count going into training
40 features selected by IC (§4). AQRTINet expands this internally to 56 (45 base + 9 engineered interaction features + 2 stacking meta-features — see below), then narrows to the top 30 per market regime.

### CatBoost
`CatBoostClassifier`/`CatBoostRegressor`. Key hyperparameters: `iterations=1000`, `learning_rate=0.05`, `depth=6`, `min_data_in_leaf=20`, `l2_leaf_reg=3.0`, `subsample=0.8`, `colsample_bylevel=0.8`, `early_stopping_rounds=50`, `random_seed=42`. Classification uses `Logloss` + `AUC` eval metric, `auto_class_weights="Balanced"` (added to correct a roughly 54/46 class imbalance).

### NGBoost
`NGBClassifier(Dist=Bernoulli, Score=LogScore)` for classification / `NGBRegressor(Dist=Normal, Score=LogScore)` for regression. `n_estimators=500`, `learning_rate=0.05`, `minibatch_frac=0.8`, `col_sample=0.8`, `natural_gradient=True`. NGBoost's whole reason for being in the ensemble is `predict_confidence_interval()` — it produces genuine probability distributions, not just point estimates, which is what lets the downstream confidence scoring and position sizing distinguish "60% confident" from "60% confident but the distribution is very wide."

### AQRTINet (the custom, in-house model)
Not one model — a **dictionary of 4 regime-specialist models**, one `HistGradientBoostingClassifier` per `{BULL, BEAR, SIDEWAYS, VOLATILE}`, each with its own tuned hyperparameters (e.g. BULL: `max_iter=400, learning_rate=0.04, max_depth=7, min_samples_leaf=15`). Its training pipeline:
1. Strip any label-passthrough columns.
2. Add 9 engineered interaction features (e.g. `momentum_10d × adx_14`, `rsi_14 × rolling_vol_21d`).
3. Run 7-fold stratified cross-validation, training CatBoost and NGBoost *inside* each fold to generate out-of-fold prediction columns (`meta_catboost`, `meta_ngboost`) — this is the "stacking" referenced in the changelog: AQRTINet uses the other two models' own honest, never-seen-this-row predictions as two of its own input features.
4. Cross-sectionally percentile-rank every feature to [0, 1] (`PercentileRanker`) — so a feature value means "how does this stock rank against the rest of the universe today," not just a raw number.
5. Look up each training row's market regime from `MarketRegime.regime` and route it to the matching regime-expert.
6. Weight samples by (a) temporal exponential decay with a 252-trading-day half-life — recent data matters more — and (b) confidence: rows with `|return_5d| < 0.5%` (i.e. the market barely moved, a weak/noisy training signal) are down-weighted to 0.3×.
7. Train each regime expert on its own regime's rows, using the asymmetric loss described in `PROJECT_DIARY.md` §5 (`class_weight={0: 2.0, 1: 1.0}` — a false bullish call costs twice as much as a false bearish one during training).
8. Platt-calibrate each regime expert (logistic regression wrapping the raw output) so its stated probability is honest.

At prediction time, AQRTINet looks up today's `MarketRegime.regime` and routes the query to the matching specialist (falling back to the BULL expert if no regime is found).

### Serialization
All three models save to `backend/ml_models/*.pkl` as `{model_type}_{task}_v{version}.pkl` (e.g. `catboost_direction_v58.pkl`). CatBoost/NGBoost save a plain pickled dict of `{model, feature_cols, artifact, hyperparams, task, label_col, version}`. AQRTINet's save payload is richer — it also stores the full `experts` dict (one calibrated model per regime), the `PercentileRanker`, the regime map, and the separate stacking/regime feature-column lists needed to reconstruct exactly which of the 56 features each regime expert expects.

---

## 7. How a Trained Model Becomes "Active"

`ml/model_retrainer.py`, `_run_training_pipeline()`:

1. Compute `next_version = max(existing ModelVersion.version) + 1`.
2. Train all 3 models on the latest walk-forward fold's train/test split.
3. Pick whichever has the best test-set accuracy as `best_model`.
4. **Save the `.pkl` file first**, before touching the database at all — the code comment explicitly notes this ordering exists "to avoid leaving the system with no active model if the save fails."
5. Flip every currently `is_active=True` row in `model_versions` to `False`.
6. Insert the new `ModelVersion` row: `model_name, task, label_col, version, artifact_path, primary_metric (=accuracy), metrics_json (accuracy/AUC/test-row-count), importance_json (top feature importances), train_rows, trained_at, is_active=True`.

**Retraining is triggered by** (from `check_and_retrain()`):
- Rolling 30-day live win rate falling below the floor.
- Model staleness — more than 45 days since last training.
- A drift flag raised by `learning/model_drift.py` in the last 3 days.
- Directly, from `paper_trading/paper_engine.py`, when live win rate underperforms target (§9).

A new model is only ever promoted if it beats the required win-rate bar on its own held-out test set — a bad retrain simply doesn't get promoted, and the previous `is_active=True` model keeps serving.

---

## 8. How an Algo Gets Backtested — Table by Table

**File**: `backend/strategies/strategy_backtester.py`.

### Reads
| Table | What for |
|---|---|
| `DailyPrice` | The core price series. Bulk-preloaded once per backtest run for the whole universe (`symbol, date, close, open, high, low`, plus 180 days extra lookback for indicators) into in-memory dicts for fast lookups in the hot trading loop — this is why a full population re-backtest is fast rather than one SQL query per bar. |
| `FeatureValue` | Only when the algo's DSL has entry/exit conditions — bulk-loaded and pivoted into a `{(symbol, date): {feature: value}}` cache, `version == 1` only. |
| `Prediction` | **Disabled by default** (`use_ml_predictions=False`). The code comment is explicit: prediction rows are only ever written with today's date by a model trained on full history, so using a historical prediction row in a backtest is look-ahead bias. Backtests are technical-indicator + DSL only unless a caller explicitly opts in. |
| `MarketRegime` | Regime lookup per day; falls back to a price-derived regime classifier (20-day NIFTY return/volatility thresholds) for any date missing a DB row. |
| `IndexData` | NIFTY daily returns, for regime fallback and the "don't enter if NIFTY is falling" entry gate. |

### Writes
`backtest_and_update()`:
- **`StrategyV2`** (the algo's own row) — upserts `sharpe, sortino, win_rate, profit_factor, max_drawdown, expectancy, trade_count, avg_holding_days, exposure_pct`, per-regime Sharpe (`bull_sharpe`, `bear_sharpe`, `sideways_sharpe`, `volatile_sharpe`), and the OOS columns (`oos_sharpe, oos_win_rate, oos_trades, oos_passed`). Reads `status` first and preserves it — a re-backtest never silently demotes an algo that's already promoted; that's a separate lifecycle sweep's job (see `PROJECT_DIARY.md` §6).
- **`StrategyBacktestTrade`** — every existing trade row for that algo's `strategy_id` is deleted, then one fresh row per simulated trade is inserted (`symbol, entry_date, exit_date, entry_price, exit_price, pnl_pct, exit_reason, holding_days`). This table is what powers the per-algo trade log and the animated replay feature in the Strategy Lab.

**The out-of-sample split** isn't a single shared holdout window for every algo — each algo's own 6-month OOS window is shifted 0–59 days based on an MD5 hash of its own `strategy_id`. This staggering is what prevents the whole population from being overfit *by selection*, since no fixed test window exists for evolution to indirectly tune against.

---

## 9. How Paper Trading Reads and Writes

**File**: `backend/paper_trading/paper_engine.py`, `run_paper_trading_cycle()`.

### Reads
- `IndexData` — NIFTY close, purely for benchmarking the equity curve.
- Via `portfolio/risk_allocator.py`:
  - `Prediction` — today's rows with `confidence >= min_conf`, ranked by confidence.
  - `StrategyV2` — either a specific requested algo, or automatically the best one with `status IN ("promoted", "active")`, `win_rate >= 50%`, `trade_count >= 500`, ranked by `fitness_score`.
  - `MarketRegime` — today's regime, for gating.
  - `FeatureValue` — per-candidate values used for extra risk filtering before sizing a position.

### Writes
- `PaperPortfolio` — the single `portfolio_name="default"` row tracking cash/total value.
- `PaperPosition` — opened and closed as positions are entered/exited; a rebalance compares current holdings against the target portfolio, closing anything no longer in the target (minimum 3-day hold) and opening new positions at that day's `DailyPrice.close` (a simulated market-on-close fill — there is no live market access in paper trading).
- `PaperTrade` — the permanent closed-trade record.
- `FailureRecord` — written the moment a closed trade is a loss. This is the direct, real-time link from a real paper-trading loss back into `training_dataset.py`'s failure-weighted sampling (§4) for the *next* retrain.
- `EquityCurvePoint` and `PerformanceSnapshot` — daily portfolio-value and aggregate-stat rows.
- **Auto-retrain trigger**: after each cycle, the live win rate (computed from `PaperTrade`) is checked against the target; if it's below target with enough trades to be meaningful, a background thread calls the same `check_and_retrain()` → `_run_training_pipeline()` path described in §7 — closing the loop from real paper-trading performance straight back into a fresh model.

---

## 10. The Full Feedback Loop

Putting §§3–9 together, one full cycle of "how does AQRTI get smarter" looks like this:

```
DailyPrice (raw prices)
     │
     ▼
FeatureValue (148 features/symbol/day, point-in-time correct)
     │
     ├──────────────────────────────┐
     ▼                              ▼
dataset_builder.py            strategy_backtester.py
(joins features + forward       (uses FeatureValue for
 labels, IC-selects top 40,      DSL conditions, DailyPrice
 walk-forward folds,             for prices, MarketRegime
 failure-weighted samples)       for regime gating)
     │                              │
     ▼                              ▼
CatBoost / NGBoost / AQRTINet   StrategyV2 (algo) scored,
trained → best saved to         backtested trades written
ml_models/*.pkl → ModelVersion  to StrategyBacktestTrade
row (is_active=True)                 │
     │                              ▼
     ▼                         Lifecycle gate: candidate →
Prediction (daily, per symbol)  shadow → promoted → (human
     │                          approval) → active
     ▼
risk_allocator.py picks the
best algo + confident
predictions → paper_engine.py
     │
     ▼
PaperPosition / PaperTrade
     │
     ├─ loss? → FailureRecord ──────► feeds back into the next
     │                                 dataset_builder.py run's
     │                                 sample weights (§4)
     │
     └─ win-rate below target? ─────► triggers check_and_retrain()
                                        (§7), closing the loop
```

Nothing in this loop is allowed to touch its own test data: label generation only sees raw prices, feature selection only sees the first 80% of history, walk-forward folds embargo 14 days at each boundary, and an algo's OOS window is uniquely shifted per algo so the population as a whole can't be overfit by selection. See `PROJECT_DIARY.md` §14's "Trust Overhaul" section for the history of how these guarantees were hardened after they were found to be violated.

---

## 11. Every Table, Grouped by Subsystem

*(Full list — see `PROJECT_DIARY.md` §12 for the same list; reproduced here with the layer framing from §1 above.)*

**Raw data layer**: `Stock`, `DailyPrice`, `IndexData`, `CorporateEvent`, `NewsEvent`, `SentimentRecord`, `OptionsData`, `NSECorporateFiling`, `FIIDIIFlow`, `OptionsChain`, `MarketBreadth`, `SectorRotation`, `EarningsEvent`, `DataSourceHealth`, `DataQualityLog`

**Derived signals layer**: `FeatureValue`, `FeatureMetadata`, `MarketRegime`, `EntityMention`

**Model layer**: `Prediction`, `ModelVersion`, `ModelMetric`, `ModelRecord` (legacy), `WalkForwardFold`, `PatternMatch`, `ConfidenceHistory`, `ModelDriftHistory`, `ModelWeight`, `FeatureImportanceHistory`, `FeatureDecayHistory`, `ModelMemory`

**Algo (strategy) layer**: `StrategyV2` (main population table — the one referred to as "algos"), `Strategy` (legacy v1), `StrategyVersion`, `StrategyPerformance`, `StrategyEvolutionHistory`, `StrategyGraveyard`, `StrategyBacktestTrade`, `StrategyResearchReport`, `StrategyMemory`, `StrategyDNA`

**Paper trading & outcomes layer**: `PaperPortfolio`, `PaperPosition`, `PaperTrade`, `Trade` (legacy), `EquityCurvePoint`, `PerformanceSnapshot`, `PortfolioSnapshot`, `Mistake` (legacy)

**Learning & knowledge layer**: `KnowledgeEvent`, `FailureRecord`, `LessonLearned`, `KnowledgeScore`, `PatternOutcome`, `FailurePattern`, `PredictionPattern`

**Agents layer**: `Agent`, `AgentTask`, `AgentReport`, `AgentMessage`, `ResearchBrief`, `ResearchFinding`

**Vault/archive layer** (permanent, never mutated): `HistoricalReplay`, `RegimeDataset`, `MetaLearningRecord`, `FeatureProposal`, `FeatureValidation`, `ResearchMemory`, `MarketSnapshot`, `PredictionArchive`, `PortfolioArchive`, `StrategyArchive`, `KnowledgeArchive`, `ResearchArchive`

**Phase-9 intelligence layer**: `DiscoveredRegime`, `DailyRegimeAssignment`, `RegimeTransitionMatrix`, `CounterfactualSimulation`, `CounterfactualLesson`, `FeatureCandidate`, `KnowledgeNode`, `KnowledgeEdge`, `ResearchHypothesis`, `ResearchExperiment`, `ModelArena`, `ArenaEvaluation`, `UncertaintyEstimate`, `SpecialistAgentOpinion`, `ModeratorDecision`, `ArenaRun`, plus parallel `P9*`-prefixed tables

**Index futures layer** (added 2026-07-03 — a fully parallel schema, deliberately isolated from every table above): `IndexFuturesContract` (lot size/tick size/margin % per index), `IndexFuturesPrice` (continuous monthly-contract OHLC + `spot_close` + `basis`, `is_synthetic` flag on every row), `IndexFuturesRoll` (contract-month rollover records for cost/slippage attribution), `IndexFuturesFeatureValue` (mirrors `FeatureValue`'s shape exactly but keyed on `index_name`, no FK to `Stock` — `DailyPrice`/`FeatureValue` both have a hard FK there, confirmed unusable for this segment). `StrategyV2` gained `asset_class` (`"stock"` default / `"index_futures"`) and `index_name` columns for isolation — same dedicated-namespace pattern as `arena_status`, so an index-futures algo can never be mixed into stock arena rounds or promotion pools. Important caveat: `IndexFuturesPrice` rows are NOT real traded futures ticks — no free data source carries historical NSE index futures contract prices, so this is a documented cost-of-carry approximation (F = S·e^((r−q)T)) over the real underlying spot index, not fabricated data but an explicit, labeled approximation.

---

*For the broader picture — what each subsystem is for, the full chronological project history, the dashboard, and the risk engine — see `PROJECT_DIARY.md`. This document goes deep on one thing only: the database and the training pipeline.*
