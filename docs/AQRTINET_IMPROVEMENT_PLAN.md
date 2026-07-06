# AQRTINet Improvement Plan

Source: fast head-to-head test (`backend/scripts/compare_models.py --sample 5000`)
on `direction_5d`, 2026-07-06. Full results in the (now-deleted) `model_comparison_TEMP.md`.
Kept here as the durable follow-up list — this file stays.

## Test result summary

| Model | Accuracy | AUC-ROC | F1 | Precision | Recall |
|---|---|---|---|---|---|
| AQRTINet (in-house) | 45.2% | 0.645 | 0.210 | 63.5% | 12.6% |
| CatBoost | 61.0% | 0.634 | 0.660 | 66.6% | 65.5% |
| NGBoost | 54.0% | 0.522 | 0.613 | 59.8% | 62.9% |

CatBoost currently wins on accuracy/F1. But AQRTINet's AUC-ROC was actually
*higher* than CatBoost's despite much worse accuracy — meaning its confidence
ranking is informative, but its decision threshold is badly miscalibrated
(12.6% recall = it almost never calls "positive"). That's the core clue for
where to start.

**Critical caveat:** the test sample (5,000 rows) was 100% BULL regime — 0
rows for BEAR/SIDEWAYS/VOLATILE. AQRTINet's entire regime-specialization
design (4 experts) was untested; only the BULL expert ran. This result is
not a fair verdict on the full architecture.

**Update from deeper audit (see "Deep audit findings" section below):** it's
worse than a data-scarcity gap. Two structural bugs (A, B) mean the
regime-expert design doesn't actually get exercised even where multi-regime
data *does* exist — `walk_forward.py` and `backtest_validator.py` both
collapse training to one regime and route every inference call through
"today's" regime rather than the historical row's regime. A bigger test
sample alone will not produce a fair test until A and B are fixed first.

## Deep audit findings (2026-07-06) — structural bugs, higher severity than tuning

A follow-up code audit (reading `training_dataset.py`, `model_retrainer.py`,
`walk_forward.py`, `backtest_validator.py`, `aqrtinet_percentile.py`,
`confidence_engine.py` end-to-end, not just `aqrtinet_model.py` in isolation)
found that the regime-expert architecture — AQRTINet's core design — is
**structurally broken outside one code path**, not just "untested due to
sparse data" as the earlier findings assumed. These supersede the
"re-run at scale" framing in #4 below: a bigger sample alone will not fix
this, because the bug is in how dates/regimes are wired, not in data volume.

### A. [HIGH] Regime routing at inference uses "today's regime," not the row's actual regime
`aqrtinet_model.py:806-816` (`_get_current_regime` → `_route_to_expert`) —
`_predict_impl`/`_predict_proba_impl` call `_get_current_regime()` **once
per call**, which queries `MarketRegime.date.desc()` for whatever regime is
most recent *in the DB right now*, then routes **every row** in the input
batch to that single expert. In `walk_forward.py::run_fold` and
`backtest_validator.py::train_final_model`, this function evaluates
historical test windows (e.g. a 2022 Q1 fold) — but the regime used to pick
the expert is today's (2026) regime, not 2022 Q1's. Every walk-forward fold,
across the whole validation loop, silently gets routed to the same one
expert regardless of what actually prevailed historically, and a test
window that itself spans a regime transition gets no per-row differentiation
either. **Concrete effect: every AQRTINet walk-forward/backtest metric
produced so far has evaluated exactly one expert, dressed up as if it
tested all four.**

### B. [HIGH] Training-time regime assignment also collapses to one regime in 2 of 3 code paths
`aqrtinet_model.py:582-589` — regime assignment for training rows depends on
`self._training_dates` (set externally) or a `"date"` column in `X_train`.
But `get_feature_columns()` (`dataset_builder.py:201-206`) strips `date`
(and all `LABEL_COLUMNS`) out of `feature_cols`, so `X_train` built via
`training_dataset.py` never contains a usable date column. Only
`model_retrainer.py:262-269` manually reconstructs `train_dates` from
`dataset.df` and sets `model._training_dates` before calling `.fit()`.
**`walk_forward.py::run_fold` and `backtest_validator.py::train_final_model`
both construct `AQRTINet(...)` and call `.fit()` directly, without ever
setting `_training_dates`.** In those two paths, `dates` inside `_fit_impl`
stays an empty string for every row, `_regime_map.get("", FALLBACK_REGIME)`
returns `FALLBACK_REGIME` for 100% of training rows, and **all 4 regime
experts collapse into training on one regime's data** — not because BEAR/
VOLATILE data is scarce, but because the date plumbing needed to look them
up is simply missing from those call sites. Combined with finding A: neither
training nor evaluation exercises the regime-expert design in
`walk_forward.py`/`backtest_validator.py` — **only `model_retrainer.py`'s
retrain path wires training correctly, and even that path's *evaluation* of
the freshly-trained model still goes through the broken lookup in
finding A**, so the accuracy number used to decide whether to activate
AQRTINet (`model_retrainer.py`'s `to_activate` selection) is itself computed
through the wrong regime expert.

**Fix, in order:**
1. Fix `_predict_impl`/`_predict_proba_impl` to route per-row based on the
   regime that applied on *that row's date*, not "today." This needs a
   regime lookup keyed by the row's own date (available at inference via
   whatever date context the caller has — `prediction_pipeline.py` calls
   per-symbol for "today," which is the one case where "current regime" is
   actually correct; `walk_forward.py`/`backtest_validator.py` need a
   different code path or an explicit `dates` argument threaded through).
2. Fix `walk_forward.py::run_fold` and `backtest_validator.py::train_final_model`
   to set `model._training_dates` before calling `.fit()`, mirroring what
   `model_retrainer.py` already does correctly.
3. Only after 1+2 are fixed does re-running at a larger sample (#4 below)
   actually test what it's supposed to test. Right now it wouldn't.

### C. [MEDIUM] Inner stacking CV leaks future data into past OOF meta-features
`aqrtinet_model.py:552-571` — `StratifiedKFold(n_splits=7, shuffle=False)`
splits `X_clean`/`y_train` in row order, which is chronological (per
`training_dataset.py`'s date sort). With `shuffle=False`, each of the 7
folds is effectively a contiguous time slice, so early folds' OOF
meta-features (`meta_catboost`, `meta_ngboost`) are generated by a model
trained on **later** dates predicting **earlier** rows — look-ahead bias,
in the opposite direction from what the outer walk-forward purge/embargo
(`training_dataset.py:160-172`) is built to prevent. The outer fold boundary
guarantee ("no test date ever appears in training set,"
`training_dataset.py:5-7`) holds at the outer level but is silently violated
by AQRTINet's own inner stacking CV, since `StratifiedKFold` has no concept
of time order.
- **Fix:** replace with `sklearn.model_selection.TimeSeriesSplit` (or a
  manual expanding-window split) for the stacking OOF loop, so meta-features
  are never generated using future rows.

### D. [LOW/MEDIUM] Same non-shuffled-KFold-on-time-ordered-data issue in Platt calibration
`aqrtinet_model.py:734-735` — `n_splits = 5 if n >= 500 else 3`,
`StratifiedKFold(shuffle=False)`, again on date-ordered, regime-filtered
rows. Regimes aren't contiguous in time (BULL/BEAR can flip repeatedly
across 5 years), so for a regime just over the 500-row threshold, 5
non-shuffled folds of ~120 rows risk being drawn from narrow, adjacent time
windows rather than independent ones — undermining the calibration-quality
rationale for going 3→5 folds (innovation #11). Same class of bug as C, one
layer down.
- **Fix:** same as C — swap for a time-aware split.

### E. Related items already covered below, cross-referenced here
Findings A/B make the "re-run at scale" item (#4 below) necessary but not
sufficient — fix A+B first, or a bigger sample will still silently test only
one expert. Item #7 (per-regime metrics) is also blocked by B: there's
nothing meaningful to log per-regime until training actually produces
distinct regimes to log.

## What to fix, in order

### 1. Recalibrate the decision threshold (cheap, do first)
`backend/ml/models/aqrtinet_model.py` — inference currently assumes a raw
0.5 cutoff for "positive" (implicit in how `predict()` / `predict_proba()`
are consumed downstream). Since AUC-ROC beat CatBoost's, the ranking is
fine; the cutoff isn't.
- Add a per-regime threshold selection step during training (pick the
  threshold on validation/OOF data that maximizes F1, or matches a target
  precision/recall tradeoff — decide which matters more for real trading:
  probably precision, since false positives cost money).
  Store it in the saved artifact (`payload["thresholds"]` in `save()`/`load()`)
  and apply it in `_predict_impl`/`_predict_proba_impl` instead of leaving
  threshold choice to the caller.

### 2. Re-examine `ASYMMETRIC_CLASS_WEIGHT`
`aqrtinet_model.py:98` — `{0: 2.0, 1: 1.0}` penalizes false positives 2×
harder than false negatives, which is a deliberate "only call UP when
confident" design. This is exactly why recall was 12.6% in the small test.
- Try `{0: 1.5, 1: 1.0}` and `{0: 1.0, 1: 1.0}` on a full-size, multi-regime
  test (see #4) and compare — 2.0 may be too conservative for how the model
  is actually being evaluated/used downstream.
- Don't change this based on the small-sample test alone — it's not a fair
  read given the regime collapse (#4).

### 3. Sanity-check `MIN_REGIME_ROWS`
`aqrtinet_model.py:96` — currently 200. Confirm on the real ~15M-row / 5yr
dataset (not the toy sample) that all 4 regimes clear this bar comfortably.
If BEAR/VOLATILE regimes are rare in the real data too, that's a genuine
data-scarcity problem, not a bug — flag it honestly rather than lowering the
threshold just to force an expert to exist on too little data.

### 4. Re-run the comparison at real scale (the test that actually matters)
The 5,000-row sample structurally couldn't test AQRTINet's design — all 4
regimes need real representation to know if regime-specialization pays off.
- Re-run `compare_models.py` with a much larger `--sample` (50,000–100,000+)
  or no cap, so BEAR/SIDEWAYS/VOLATILE regimes actually get trained and
  evaluated.
- Better: compare via `backend/ml/validation/walk_forward.py` (multi-fold,
  time-ordered) rather than a single train/test split — AQRTINet's temporal-
  decay weighting (`TEMPORAL_HALFLIFE_DAYS=252`) is specifically designed to
  matter more across multiple time-ordered folds, which a single split can't
  show.
- This is a longer run (AQRTINet alone took 82s on 5,000 rows; expect
  significantly longer at full scale — budget accordingly, run as a
  background/separate process per the existing training-separation setup,
  not inside the live backend).

### 5. Only after 1–4: decide if AQRTINet should be primary
Don't promote or activate AQRTINet as the primary model based on the small
test — it wasn't a fair evaluation. Decide based on the full-scale walk-
forward comparison. If it still underperforms CatBoost even with threshold
calibration and all 4 regimes populated, that's a real, honest result to
act on (keep CatBoost as primary) — not a reason to keep tuning until
AQRTINet wins (would violate the no-loosening-gates rule in `CLAUDE.md`).

### 6. Ensemble weighting already favors AUC-ROC, not accuracy (verified, no action needed)
`backend/ml/ensemble/model_weighting.py:load_dynamic_weights()` computes each
model's ensemble weight from `auc_roc` (classification tasks) or `ic`
(regression), pulled from the `model_metrics` table — not accuracy or F1.
This matters because on the small test, AQRTINet's AUC-ROC (0.645) actually
beat CatBoost's (0.634), even though its accuracy was far worse (45.2% vs
61.0%). So the live ensemble is already weighting on the metric where
AQRTINet looked competitive, not the one where it looked weak — the
`compute_weights_from_metrics()` softmax (temperature=2.0, min floor=0.10)
would not zero it out for a gap this size. No code change needed here; just
don't be misled by the accuracy gap into thinking the ensemble is
mis-weighting AQRTINet today — confirm this against `model_metrics` rows
once the full-scale test (#4) produces new AUC-ROC numbers for all 3 models.

### 7. Add per-regime AQRTINet metrics to `model_metrics`, not just an overall score
Currently unclear whether `ModelMetric` rows for `aqrtinet` are logged
per-regime or as one blended number. If it's blended, a strong BULL expert
can mask a weak/nonexistent BEAR expert in the ensemble weight calculation.
Check `ml/model_retrainer.py` / wherever `ModelMetric` rows get written for
aqrtinet, and if regime breakdown isn't captured, add it — this is the kind
of gap that would only surface once regime data is actually populated
(tied to #4).

### 8. `_compute_confident_label_weights` silently no-ops outside `model_retrainer.py`
`aqrtinet_model.py:320-321` — requires `return_5d` in `X_train` to compute
confident-label weights (innovation #9, the "down-weight ambiguous ±0.5%
return rows" feature). `return_5d` is in `LABEL_COLUMNS`
(`label_generator.py:31`) and is explicitly stripped by
`get_feature_columns()` (`dataset_builder.py:201-206`), so it never reaches
`X_train` via `walk_forward.py` or `backtest_validator.py` — only
`model_retrainer.py` happens to pass a frame that could include it (not
verified that it does). Net effect: the confident-label-filtering innovation
is a silent no-op (falls back to uniform weights) in 2 of 3 training entry
points, with no log line distinguishing "column missing" from "no ambiguous
rows found."
- **Fix:** either thread `return_5d` through explicitly wherever AQRTINet is
  trained (as a weighting input only, never a feature — already handled by
  the `_LABEL_PASSTHROUGH` strip in `_fit_impl`), or compute confidence
  weights from the label itself (`y_train`) if it's already the direction
  label thresholded from `return_5d`, so the weighting doesn't depend on a
  column that structurally can't survive `training_dataset.py`'s pipeline.

### 9. PercentileRanker passes unseen features through raw and unranked, silently
`ml/models/aqrtinet_percentile.py:77-80` — a column present at inference but
absent at fit-time "passes through raw" on whatever scale it naturally has
(e.g. RSI 0-100, momentum ±X%), sitting next to ~55 other percentile-ranked
[0,1] features feeding the same `HistGradientBoostingClassifier`. Since
interaction/meta features are added before the ranker's `fit_transform`/
`transform` call, a future feature-set change that adds a new `ix_*` column
after the ranker was already fit would sail through unranked and could
dominate splits purely by scale — defeating the ranker's whole stated
purpose (`aqrtinet_percentile.py:9-12`). No warning is logged when
`transform()` hits an unknown column, so this would be invisible in
production logs until someone diffs feature-name sets by hand.
- **Fix:** log a warning (with the specific column names) whenever
  `transform()` encounters a column not seen at `fit()` time, so a silent
  quality regression becomes a visible one.

### 10. Confidence engine's "historical accuracy" component is blended across all 3 models, not per-model
`ml/confidence/confidence_engine.py:120-133` (`get_historical_accuracy`) —
queries `ModelMetric` filtered by `task`/`metric_name`/`split`/`version`
only, no `model_name` filter; the docstring itself says "last 4 folds × 3
models" (line 131), confirming CatBoost/NGBoost/AQRTINet rows are
deliberately averaged together. So the confidence score's
`historical_accuracy` component (25% weight) is identical regardless of
which model actually produced a given prediction — a prediction from
AQRTINet's regime-routed, Platt-calibrated probability gets the same
historical-accuracy credit as one from CatBoost, even where their real
calibration quality differs. This is a distinct gap from item #7 (which is
about `ModelMetric` write-side granularity) — this one is about the
read-side query never using `model_name` even where it's available. No
double-calibration bug was found: Platt/conformal calibration only produces
`direction_prob`, which feeds the separate `signal_strength` component
(`confidence_engine.py:87`) — the two calibration layers don't fight each
other, they're just measuring different things.
- **Fix:** add `model_name` to the `get_historical_accuracy` query (or a
  parallel per-model component) once per-model/per-regime `ModelMetric` rows
  exist (tied to #7).

### 11. Hardcoded feature names in interaction/regime-hint logic will silently degrade, not error, on a feature-registry rename
`_build_interaction_features()` (`aqrtinet_model.py:278-302`) and
`REGIME_FEATURE_HINTS` (`:132-145`) reference feature names like
`momentum_10d`, `adx_14`, `beta_21d` by hardcoded string, with no shared
constant or lookup tying them to `features/feature_registry.py` (verified
these names currently match, e.g. `momentum_10d` and `beta_21d` both exist
there today). `g(col)`'s `.get()`-with-NaN-fallback pattern means a future
rename in the registry wouldn't crash — it would silently zero out that
interaction feature and drop it from the regime-hint IC boost, with only a
debug-level difference in the IC ranking and no explicit "missing feature"
warning.
- **Fix:** at model load/fit time, assert that every name referenced in
  `_build_interaction_features` and `REGIME_FEATURE_HINTS` actually exists
  in the incoming feature set, and log a clear warning (or hard-fail, given
  this project's "no silent degradation" rule) listing exactly which names
  are missing.

### 12. Confirmed fine — no action needed
Cross-checked and ruled out as real issues: (a) the meta-feature `.pkl` glob
pattern in `_build_inference_features` correctly matches `base_model.py`'s
save-path naming, no filename mismatch; (b) `save()`/`load()` correctly
round-trips `regime_map`, `stacking_feature_cols`, `regime_feature_cols` —
persistence itself is not the problem, only the live DB lookup in finding A
is; (c) the *outer* walk-forward purge/embargo logic in
`training_dataset.py:160-172` is sound and correctly reasoned — the leakage
risk is entirely confined to AQRTINet's own *inner* stacking/calibration CV
(findings C/D), not the outer fold construction `training_dataset.py` owns;
(d) `model_retrainer.py` has no per-model timeout/starvation risk — AQRTINet
training slowly is not penalized unfairly relative to CatBoost/NGBoost, it
just runs sequentially to completion.

## Non-goals for this pass

- Don't touch `promotion_config.py` gates to make AQRTINet "pass" more
  easily — model architecture quality and promotion-gate honesty are
  separate concerns.
- Don't drop the regime-expert design just because the small test looked
  weak — it was never actually tested.
