import yfinance as yf
import pandas as pd
import numpy as np

tickers = ["SPY", "BTC-USD", "GLD", "TLT", "SHV"]
df = yf.download(tickers, start="2016-01-01", end="2024-01-01", progress=False)['Close'].ffill().dropna()

df_m = df.resample('M').last()
ret_m = df_m.pct_change().dropna()
mom130 = df_m.pct_change(6).dropna()
ma200 = df.rolling(200).mean().resample('M').last()

idx = ret_m.index.intersection(mom130.index).intersection(ma200.index)
risk_on = ["SPY", "BTC-USD", "GLD"]

port_ret = []
for i in range(1, len(idx)):
    date = idx[i]
    prev = idx[i-1]
    
    # 1. Trova i validi sopra MA200
    valid = [t for t in risk_on if df_m.loc[prev, t] > ma200.loc[prev, t]]
    
    # 2. Ordina per Momentum e prendi i Top 2
    top_assets = []
    if valid:
        best_sorted = mom130.loc[prev, valid].sort_values(ascending=False).index.tolist()
        top_assets = best_sorted[:2]
        
    # 3. Calcola il ritorno del blocco Risk-On
    period_ret = 0
    for t in top_assets:
        period_ret += ret_m.loc[date, t] * 0.5
        
    # 4. Copri gli slot vuoti col Paracadute
    empty_slots = 2 - len(top_assets)
    if empty_slots > 0:
        if df_m.loc[prev, "TLT"] > ma200.loc[prev, "TLT"] and mom130.loc[prev, "TLT"] > mom130.loc[prev, "SHV"]:
            period_ret += ret_m.loc[date, "TLT"] * (0.5 * empty_slots)
        else:
            period_ret += ret_m.loc[date, "SHV"] * (0.5 * empty_slots)
            
    port_ret.append(period_ret)

final_series = pd.Series(port_ret, index=idx[1:])
eq = (1 + final_series).cumprod()
cagr = (eq.iloc[-1] ** (12/len(eq))) - 1
max_dd = ((eq - eq.cummax()) / eq.cummax()).min()

with open("validation_report.txt", "w") as f:
    f.write(f"=== ULTIMATE MASTER VALIDATION ===\n")
    f.write(f"CAGR Finale Netto: {cagr*100:.2f}%\n")
    f.write(f"Max Drawdown: {max_dd*100:.2f}%\n")
