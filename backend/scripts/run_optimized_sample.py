import sys, os, time
sys.path.insert(0, os.getcwd())
from features.feature_generator import run_full_feature_generation

SYMS = {"RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK"}
t0 = time.time()
result = run_full_feature_generation(only_symbols=SYMS)
elapsed = time.time() - t0
print(f"RESULT: {result}")
print(f"Elapsed: {elapsed:.1f}s ({elapsed/60:.2f} min)")
