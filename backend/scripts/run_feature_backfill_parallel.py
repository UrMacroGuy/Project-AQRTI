"""
Parallel feature backfill — splits the 352-symbol universe across a small,
fixed number of worker processes (default 4, conservative for a 16GB
machine with other apps open) so the backfill finishes in a fraction of the
single-process time without saturating the CPU/RAM.

Each worker calls the SAME verified-correct run_full_feature_generation()
used by the single-process path (only_symbols=<its chunk>) — no new feature
math, just parallel execution of already-correct, already-diffed-against-
golden code. SQLite WAL mode + busy_timeout=30000 (see aqrti/database/engine.py)
lets concurrent writers queue safely instead of erroring.

Usage: python scripts/run_feature_backfill_parallel.py [--workers N]
"""
import sys, os, time, argparse
from multiprocessing import Process, Queue

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)
os.chdir(BACKEND)


def _worker(symbols: list[str], worker_id: int, result_q: Queue):
    # Re-import inside the child process (required on Windows spawn)
    sys.path.insert(0, BACKEND)
    os.chdir(BACKEND)
    # Lower process priority so the backfill doesn't starve the rest of the
    # machine (foreground apps, etc.) — best-effort, no hard dependency.
    try:
        import ctypes
        BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
        handle = ctypes.windll.kernel32.GetCurrentProcess()
        ctypes.windll.kernel32.SetPriorityClass(handle, BELOW_NORMAL_PRIORITY_CLASS)
    except Exception:
        pass
    from features.feature_generator import run_full_feature_generation
    t0 = time.time()
    try:
        result = run_full_feature_generation(only_symbols=set(symbols))
        result_q.put((worker_id, "ok", result, time.time() - t0))
    except Exception as exc:
        result_q.put((worker_id, "error", str(exc), time.time() - t0))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=4,
                     help="Number of parallel worker processes (default 4 — conservative for a 16GB machine)")
    args = ap.parse_args()
    n_workers = max(1, args.workers)

    from aqrti.database.engine import get_db
    from aqrti.database.models import Stock, DailyPrice
    from sqlalchemy import func

    with get_db() as db:
        symbols = [r[0] for r in db.query(func.distinct(DailyPrice.symbol))
                   .filter(DailyPrice.symbol.in_(
                       db.query(Stock.symbol).filter(Stock.active == True).scalar_subquery()
                   )).all()]
    symbols.sort()
    print(f"Total symbols: {len(symbols)}, workers: {n_workers}", flush=True)

    chunks = [symbols[i::n_workers] for i in range(n_workers)]
    for i, c in enumerate(chunks):
        print(f"  worker {i}: {len(c)} symbols", flush=True)

    result_q = Queue()
    procs = []
    t_start = time.time()
    for i, chunk in enumerate(chunks):
        p = Process(target=_worker, args=(chunk, i, result_q))
        p.start()
        procs.append(p)

    results = []
    for _ in procs:
        results.append(result_q.get())

    for p in procs:
        p.join()

    elapsed = time.time() - t_start
    print(f"\n=== ALL WORKERS COMPLETE in {elapsed:.1f}s ({elapsed/60:.1f} min) ===", flush=True)
    total_rows = 0
    total_errors = []
    for worker_id, status, result, w_elapsed in sorted(results):
        if status == "ok":
            print(f"  worker {worker_id}: {result} in {w_elapsed:.1f}s", flush=True)
            total_rows += result.get("total_rows_written", 0)
            total_errors.extend(result.get("errors", []))
        else:
            print(f"  worker {worker_id}: ERROR: {result}", flush=True)
            total_errors.append(f"worker{worker_id}")

    print(f"\nRESULT: total_rows={total_rows} errors={total_errors} status={'COMPLETED' if not total_errors else 'COMPLETED_WITH_ERRORS'}", flush=True)


if __name__ == "__main__":
    main()
