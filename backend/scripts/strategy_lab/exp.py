"""Experiment driver — variants evaluated on TRAIN only (<=2024-12-31).
OOS (2025-01-01..2026-07-10) is run ONCE for the chosen finalist, separately."""
import pandas as pd
from bt import load, prep, run, report, SYMS

SPLIT = pd.Timestamp("2024-12-31")

def eval_variant(name, entry, exit_, period="train", **kw):
    px, _ = load()
    all_tr = []
    for s in SYMS:
        df = prep(px[px.symbol == s])
        tr = run(df, entry, exit_, **kw)
        all_tr += tr
    t = pd.DataFrame(all_tr)
    if t.empty: print(f"{name} [{period}]: 0 trades"); return
    mask = t.entry_date <= SPLIT if period == "train" else t.entry_date > SPLIT
    report(t[mask].to_dict("records"), f"{name} [{period}]")

# A: Connors-style RSI2 pullback in uptrend
eA_entry = lambda d,i: d.iloc[i].close > d.iloc[i].sma200 and d.iloc[i].rsi2 < 10
eA_exit  = lambda d,i: d.iloc[i].close > d.iloc[i].sma5 or d.iloc[i].rsi2 > 65

# B: RSI3 variant (fewer, stronger signals)
eB_entry = lambda d,i: d.iloc[i].close > d.iloc[i].sma200 and d.iloc[i].rsi3 < 15
eB_exit  = lambda d,i: d.iloc[i].rsi3 > 70

# C: 7-day-low pullback in uptrend, exit above 5dma
eC_entry = lambda d,i: d.iloc[i].close > d.iloc[i].sma200 and d.iloc[i].close <= d.iloc[i].lo7
eC_exit  = lambda d,i: d.iloc[i].close > d.iloc[i].sma5

# D: 52wk-high momentum
eD_entry = lambda d,i: d.iloc[i].close >= 0.95*d.iloc[i].hi252 and d.iloc[i].ret126 > 0.10
eD_exit  = lambda d,i: d.iloc[i].ret63 < 0

if __name__ == "__main__":
    eval_variant("A rsi2<10 x sma5", eA_entry, eA_exit, max_hold=10)
    eval_variant("A+stop3atr",       eA_entry, eA_exit, max_hold=10, stop_atr=3.0)
    eval_variant("B rsi3<15 x rsi3>70", eB_entry, eB_exit, max_hold=12)
    eval_variant("C lo7 x sma5",     eC_entry, eC_exit, max_hold=10)
    eval_variant("D 52wk-high mom",  eD_entry, eD_exit, max_hold=60)
