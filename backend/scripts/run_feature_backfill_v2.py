import sys, os, time
sys.path.insert(0, os.getcwd())
from features.feature_generator import run_full_feature_generation

t0 = time.time()
print("Starting FULL feature generation (optimized, all symbols, days=2000)...", flush=True)
result = run_full_feature_generation()
elapsed = time.time() - t0
print(f"RESULT: {result}", flush=True)
print(f"Elapsed: {elapsed:.1f}s ({elapsed/60:.1f} min)", flush=True)
