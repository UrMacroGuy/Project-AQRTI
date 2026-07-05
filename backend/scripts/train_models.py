"""
Standalone model training entrypoint — runs completely independently of
the live backend process.

Why this exists: model training (esp. AQRTINet's 7-fold stacking + 4
regime experts) is memory/CPU-heavy and was previously triggered as a
daemon thread INSIDE the live backend process (scheduler.py's drift-check
step), meaning training and live serving fought over the same RAM/CPU with
no way to run one without the other, and no way to choose when training
happens. This script separates them: run this whenever you want to train,
independent of whether the backend is running.

Usage:
    # Full training pipeline (walk-forward validation + final models for
    # all 3 tasks: direction_5d, expected_return, outperform_binary)
    python scripts/train_models.py

    # Just the drift-triggered check-and-retrain path (direction_5d only,
    # matches what the scheduler used to do automatically)
    python scripts/train_models.py --quick

Safe to run alongside the backend (reads live DB data, only writes new
ModelVersion rows + .pkl artifacts), but for best performance/least RAM
contention, stop the backend first if training feels slow.
"""
import sys, os, argparse, time

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)
os.chdir(BACKEND)


def run_full():
    from ml.validation.backtest_validator import run_full_training
    print("=== Full training pipeline (all 3 tasks, all 3 models) ===", flush=True)
    t0 = time.time()
    results = run_full_training(version=1)
    print(f"\nDone in {time.time()-t0:.1f}s")
    for task, r in results.items():
        print(f"  {task}: {r.get('status')} — models_trained={r.get('models_trained')}")
    return results


def run_quick():
    from aqrti.database.engine import get_session_factory
    from ml.model_retrainer import check_and_retrain
    print("=== Quick retrain (direction_5d only, drift-check path) ===", flush=True)
    t0 = time.time()
    db = get_session_factory()()
    result = check_and_retrain(db, force=True)
    db.close()
    print(f"\nDone in {time.time()-t0:.1f}s: {result}")
    return result


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true",
                     help="Run only the quick drift-retrain path (direction_5d, single fold comparison) instead of the full pipeline")
    args = ap.parse_args()

    if args.quick:
        run_quick()
    else:
        run_full()
