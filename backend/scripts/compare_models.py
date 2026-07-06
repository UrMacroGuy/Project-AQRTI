"""
Head-to-head model comparison — trains each model on the SAME data/split for
one task and prints held-out metrics side by side. Does NOT register
anything in model_versions (is_active untouched) and does NOT save
artifacts under the production ml_models/ path, so it's safe to run
without affecting what the live backend serves.

Use this before deciding whether AQRTINet (our in-house model) alone is
good enough to train instead of the full 3-model ensemble.

Usage:
    python scripts/compare_models.py                        # direction_5d, all 3 models
    python scripts/compare_models.py --task expected_return
    python scripts/compare_models.py --models aqrtinet catboost
"""
import sys, os, argparse, time

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)
os.chdir(BACKEND)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", default="direction_5d",
                    choices=["direction_5d", "expected_return", "outperform_binary"])
    ap.add_argument("--models", nargs="+", default=["catboost", "ngboost", "aqrtinet"],
                    choices=["catboost", "ngboost", "aqrtinet"])
    ap.add_argument("--version", type=int, default=1)
    ap.add_argument("--sample", type=int, default=5000,
                    help="Cap total rows (most recent N, chronological) for a fast, fair comparison instead of training on the full history. Use 0 for no cap.")
    args = ap.parse_args()

    import pandas as pd
    from ml.datasets.training_dataset import prepare_training_dataset, get_final_train_test
    from ml.models.catboost_model import CatBoostModel
    from ml.models.ngboost_model import NGBoostModel
    from ml.models.aqrtinet_model import AQRTINet
    from ml.validation.metrics import compute_metrics

    MODEL_CLASSES = {"catboost": CatBoostModel, "ngboost": NGBoostModel, "aqrtinet": AQRTINet}

    is_classif = args.task in ("direction_5d", "outperform_binary")
    ml_task = "direction" if is_classif else "expected_return"

    print(f"=== Comparing {args.models} on task={args.task} ===", flush=True)
    dataset = prepare_training_dataset(label_col=args.task, version=args.version)
    if dataset.df.empty:
        print("No data for this task — aborting.")
        return

    if args.sample and len(dataset.df) > args.sample:
        # Keep the most recent N rows (chronological order preserved) so the
        # comparison stays fair — same recent regime for every model, just
        # less of it, instead of skewing toward whichever model handles
        # more history better.
        dataset.df = dataset.df.iloc[-args.sample:].reset_index(drop=True)
        print(f"Sampled to most recent {args.sample} rows (from full dataset) for a fast comparison", flush=True)

    X_train, y_train, X_test, y_test, scaler, train_weights, train_dates, test_dates, train_return_5d, _ = get_final_train_test(dataset, scale=True)
    print(f"train rows={len(X_train)}  test rows={len(X_test)}", flush=True)

    val_split = int(len(X_train) * 0.85)
    X_tr, y_tr = X_train.iloc[:val_split], y_train.iloc[:val_split]
    X_vl, y_vl = X_train.iloc[val_split:], y_train.iloc[val_split:]
    w_tr = train_weights.iloc[:val_split] if train_weights is not None else None
    train_dates_tr = train_dates.iloc[:val_split] if train_dates is not None else None
    train_return_5d_tr = train_return_5d.iloc[:val_split] if not train_return_5d.empty else pd.Series([], dtype=float)

    results = {}
    for name in args.models:
        ModelClass = MODEL_CLASSES[name]
        print(f"\n--- Training {name} ---", flush=True)
        t0 = time.time()
        model = ModelClass(task=ml_task, label_col=args.task, version=args.version)
        try:
            # Inject training dates + return_5d for AQRTINet (ignored by other models)
            if name == "aqrtinet":
                if train_dates_tr is not None:
                    model._training_dates = train_dates_tr
                if not train_return_5d_tr.empty:
                    model._return_5d = train_return_5d_tr
            model.fit(X_tr, y_tr, X_vl, y_vl, sample_weight=w_tr)
        except Exception as exc:
            print(f"{name} FAILED: {exc}")
            results[name] = {"status": "error", "error": str(exc)}
            continue
        elapsed = time.time() - t0

        # Pass historical dates so AQRTINet routes each test row to its own
        # regime expert/threshold instead of "today's" single regime — otherwise
        # a chronological test set gets almost entirely mis-routed (see
        # IMPROVEMENTS.md regime-routing fix, 2026-07-06).
        y_pred = model.predict(X_test, dates=test_dates) if name == "aqrtinet" else model.predict(X_test)
        y_proba = model.predict_proba(X_test, dates=test_dates) if name == "aqrtinet" else model.predict_proba(X_test)
        metrics = compute_metrics(y_test, y_pred, y_proba, ml_task)
        results[name] = {"status": "ok", "elapsed_sec": round(elapsed, 1), **metrics}
        print(f"{name}: {elapsed:.1f}s | {metrics}", flush=True)

    print("\n=== SUMMARY ===")
    for name, r in results.items():
        print(f"  {name}: {r}")


if __name__ == "__main__":
    main()
