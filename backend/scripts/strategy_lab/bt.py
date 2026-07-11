"""Honest standalone backtester for candidate strategy rules.

- Data: real daily_prices from aqrti.db (read-only).
- Costs: 0.28% NSE round-trip (0.154% buy / 0.126% sell, matching backend split).
- No look-ahead: signal computed on day d close -> entry at day d+1 OPEN.
- Exits also execute at next open after the exit signal (or stop intraday).
- Train/OOS split: tune only on train; OOS is touched once per final variant.
"""
import sqlite3, sys
import numpy as np
import pandas as pd

DB = r"c:\Users\praty\OneDrive\Desktop\Project AQRTI\backend\aqrti.db"
SYMS = ["BEL","HDFCBANK","NTPC","ICICIBANK","INFY","CDSL","DRREDDY","LT","HAL"]
BUY_COST, SELL_COST = 0.00154, 0.00126   # 0.28% round trip

def load():
    con = sqlite3.connect(DB)
    px = pd.read_sql("SELECT symbol,date,open,high,low,close,volume FROM daily_prices WHERE symbol IN (%s) ORDER BY date" % ",".join("?"*len(SYMS)), con, params=SYMS, parse_dates=["date"])
    nifty = pd.read_sql("SELECT date, close FROM index_data WHERE index_name LIKE '%NIFTY 50%' OR index_name='NIFTY50' OR index_name='NIFTY' ORDER BY date", con, parse_dates=["date"])
    con.close()
    return px, nifty

def rsi(series, n):
    d = series.diff()
    up = d.clip(lower=0).ewm(alpha=1/n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1/n, adjust=False).mean()
    rs = up / dn.replace(0, np.nan)
    return 100 - 100/(1+rs)

def prep(df):
    df = df.sort_values("date").reset_index(drop=True)
    c = df["close"]
    df["sma200"] = c.rolling(200).mean()
    df["sma5"]   = c.rolling(5).mean()
    df["rsi2"]   = rsi(c, 2)
    df["rsi3"]   = rsi(c, 3)
    df["atr14"]  = (pd.concat([(df.high-df.low), (df.high-c.shift()).abs(), (df.low-c.shift()).abs()],axis=1).max(axis=1)).ewm(alpha=1/14, adjust=False).mean()
    df["ret63"]  = c.pct_change(63)
    df["ret126"] = c.pct_change(126)
    df["hi252"]  = c.rolling(252).max()
    df["lo7"]    = c.rolling(7).min()
    return df

def run(df, entry_fn, exit_fn, stop_atr=None, max_hold=None, time_stop=None):
    """Day-by-day sim. Entry signal on d close -> fill at d+1 open."""
    trades = []
    in_pos = False; entry_px = 0; entry_i = 0
    for i in range(210, len(df)-1):
        row = df.iloc[i]
        nxt = df.iloc[i+1]
        if not in_pos:
            if entry_fn(df, i):
                entry_px = nxt["open"] * (1 + BUY_COST)
                entry_i = i+1
                in_pos = True
        else:
            # intraday hard stop first (gap-aware: fill at min(stop, open))
            exit_px = None; reason = None
            if stop_atr is not None:
                stop = df.iloc[entry_i]["open"] - stop_atr * df.iloc[entry_i-1]["atr14"]
                if nxt["open"] <= stop:
                    exit_px = nxt["open"]; reason = "gap_stop"
                elif nxt["low"] <= stop:
                    exit_px = stop; reason = "stop"
            if exit_px is None and exit_fn(df, i):
                exit_px = nxt["open"]; reason = "signal"
            if exit_px is None and max_hold and (i+1 - entry_i) >= max_hold:
                exit_px = nxt["open"]; reason = "time"
            if exit_px is not None:
                net = exit_px * (1 - SELL_COST) / entry_px - 1
                trades.append({"entry_date": df.iloc[entry_i]["date"], "exit_date": nxt["date"],
                               "days": i+1-entry_i, "ret": net, "reason": reason})
                in_pos = False
    return trades

def report(all_trades, label):
    t = pd.DataFrame(all_trades)
    if t.empty:
        print(f"{label}: 0 trades"); return None
    wr = (t.ret > 0).mean()*100
    print(f"{label}: n={len(t)} WR={wr:.1f}% avg={t.ret.mean()*100:.3f}% med={t.ret.median()*100:.3f}% "
          f"avgW={t[t.ret>0].ret.mean()*100:.2f}% avgL={t[t.ret<=0].ret.mean()*100:.2f}% "
          f"tot={(1+t.ret).prod()-1:+.1%} hold={t.days.mean():.1f}d")
    return t

if __name__ == "__main__":
    px, nifty = load()
    print("rows:", len(px), "| nifty rows:", len(nifty), "| range:", px.date.min().date(), "->", px.date.max().date())
