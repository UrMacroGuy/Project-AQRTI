import sys, os, time
sys.path.insert(0, os.getcwd())
from features.feature_generator import run_full_feature_generation

t0 = time.time()
print("Starting full feature generation with widened window (days=2000)...", flush=True)
result = run_full_feature_generation()
print(f"RESULT: {result}", flush=True)
print(f"Elapsed: {(time.time()-t0)/60:.1f} min", flush=True)
