import yfinance as yf
import pandas as pd
import numpy as np

print("Download dati per Analisi Waterfall...")
macro_ticks = ["SPY", "BTC-USD", "GLD", "TLT", "SHV"]
eq_ticks = ["AAPL", "MSFT", "NVDA", "JPM", "V", "JNJ", "UNH", "XOM", "PG", "MA", "HD", "CVX", "ABBV", "MRK", "META"]
cr_ticks = ["BTC-USD", "ETH-USD", "XRP-USD"]

all_ticks = list(set(macro_ticks + eq_ticks + cr_ticks))
df = yf.download(all_ticks, start="2016-01-01", end="2024-01-01", progress=False)['Close'].ffill()

# Invece di fillna(0) che sballa il pct_change, riempiamo in avanti, poi calcoliamo, poi fillna(0)
df_m = df.resample('M').last()
ret_m = df_m.pct_change().fillna(0)
mom130 = df_m.pct_change(6).fillna(0)
ma200 = df.rolling(200).mean().resample('M').last().fillna(0)

idx = ret_m.index.intersection(mom130.index).intersection(ma200.index)
port_ret = []
yearly_ret = {}

for i in range(1, len(idx)):
    date = idx[i]
    prev = idx[i-1]
    
    # 1. Filtro MA200
    valid_macro = []
    for m in ["SPY", "BTC-USD", "GLD", "TLT"]:
        if df_m.loc[prev, m] > ma200.loc[prev, m]:
            valid_macro.append((m, mom130.loc[prev, m]))
            
    # 2. Ranking Momentum
    valid_macro.sort(key=lambda x: x[1], reverse=True)
    ranked = [x[0] for x in valid_macro]
    
    # 3. Waterfall
    capital = 1.0
    alloc = {"SPY": 0, "BTC-USD": 0, "GLD": 0, "TLT": 0, "SHV": 0}
    
    for m in ranked:
        if capital <= 0: break
        
        if m == "BTC-USD":
            take = min(0.15, capital)
            alloc["BTC-USD"] = take
            capital -= take
        elif m == "GLD":
            take = min(0.10, capital)
            alloc["GLD"] = take
            capital -= take
        elif m == "SPY":
            take = min(0.70, capital)
            alloc["SPY"] = take
            capital -= take
        elif m == "TLT":
            alloc["TLT"] = capital
            capital = 0
            
    # Spillover
    if capital > 0:
        if df_m.loc[prev, "TLT"] > ma200.loc[prev, "TLT"] and mom130.loc[prev, "TLT"] > mom130.loc[prev, "SHV"]:
            alloc["TLT"] += capital
        else:
            alloc["SHV"] += capital
            
    # Ritorni
    r_eq = sum([ret_m.loc[date, t] for t in eq_ticks]) / len(eq_ticks) if alloc["SPY"] > 0 else 0
    r_cr = sum([ret_m.loc[date, t] for t in cr_ticks]) / len(cr_ticks) if alloc["BTC-USD"] > 0 else 0
    
    period_ret = (alloc["SPY"] * r_eq) + (alloc["BTC-USD"] * r_cr) + (alloc["GLD"] * ret_m.loc[date, "GLD"]) + (alloc["TLT"] * ret_m.loc[date, "TLT"]) + (alloc["SHV"] * ret_m.loc[date, "SHV"])
    port_ret.append(period_ret)
    
    year = date.year
    if year not in yearly_ret: yearly_ret[year] = []
    yearly_ret[year].append(period_ret)

final_series = pd.Series(port_ret, index=idx[1:])
eq = (1 + final_series).cumprod()
cagr = (eq.iloc[-1] ** (12/len(eq))) - 1
max_dd = ((eq - eq.cummax()) / eq.cummax()).min()

out = f"CAGR: {cagr*100:.2f}%\nMax DD: {max_dd*100:.2f}%\n\nYearly:\n"
for y in sorted(yearly_ret.keys()):
    if len(yearly_ret[y]) == 12 or y == 2023 or y == 2016:
        y_eq = (1 + pd.Series(yearly_ret[y])).cumprod()
        y_ret = (y_eq.iloc[-1] - 1) * 100
        out += f"{y}: {y_ret:.2f}%\n"

with open("waterfall_report.txt", "w") as f:
    f.write(out)
