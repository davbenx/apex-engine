import yfinance as yf
import pandas as pd
import numpy as np

macro_ticks = ["SPY", "BTC-USD", "GLD", "TLT", "SHV"]
eq_ticks = ["AAPL", "MSFT", "NVDA", "JPM", "V", "JNJ", "UNH", "XOM", "PG", "MA", "HD", "CVX", "ABBV", "MRK", "META"]
cr_ticks = ["BTC-USD", "ETH-USD", "XRP-USD"]

all_ticks = list(set(macro_ticks + eq_ticks + cr_ticks))
df = yf.download(all_ticks, start="2016-01-01", end="2024-01-01", progress=False)['Close'].ffill().dropna(how='all').fillna(0)

df_m = df.resample('M').last()
ret_m = df_m.pct_change().fillna(0)
mom130 = df_m.pct_change(6).fillna(0)
ma200 = df.rolling(200).mean().resample('M').last().fillna(0)

idx = ret_m.index.intersection(mom130.index).intersection(ma200.index)
results = []

def calc_metrics(name, port_ret):
    eq = (1 + pd.Series(port_ret)).cumprod()
    if len(eq) > 0 and eq.iloc[-1] > 0:
        cagr = (eq.iloc[-1] ** (12/len(eq))) - 1
        max_dd = ((eq - eq.cummax()) / eq.cummax()).min()
        results.append({'Versione': name, 'CAGR_%': round(cagr*100, 2), 'Max_DD_%': round(max_dd*100, 2)})

ret_70 = []
for i in range(1, len(idx)):
    date = idx[i]; prev = idx[i-1]
    r_eq = sum([ret_m.loc[date, t] for t in eq_ticks]) / len(eq_ticks) if df_m.loc[prev, "SPY"] > ma200.loc[prev, "SPY"] else 0
    r_cr = sum([ret_m.loc[date, t] for t in cr_ticks]) / len(cr_ticks) if df_m.loc[prev, "BTC-USD"] > ma200.loc[prev, "BTC-USD"] else 0
    r_gld = ret_m.loc[date, "GLD"] if df_m.loc[prev, "GLD"] > ma200.loc[prev, "GLD"] else 0
    r_tlt = ret_m.loc[date, "TLT"] if df_m.loc[prev, "TLT"] > ma200.loc[prev, "TLT"] else 0
    ret_70.append((0.7 * r_eq) + (0.1 * r_cr) + (0.1 * r_gld) + (0.1 * r_tlt))
calc_metrics('Vecchia 70-10-10-10', ret_70)

ret_cap = []
for i in range(1, len(idx)):
    date = idx[i]; prev = idx[i-1]
    valid = []
    if df_m.loc[prev, "SPY"] > ma200.loc[prev, "SPY"]: valid.append(("SPY", mom130.loc[prev, "SPY"]))
    if df_m.loc[prev, "BTC-USD"] > ma200.loc[prev, "BTC-USD"]: valid.append(("BTC-USD", mom130.loc[prev, "BTC-USD"]))
    if df_m.loc[prev, "GLD"] > ma200.loc[prev, "GLD"]: valid.append(("GLD", mom130.loc[prev, "GLD"]))
    valid.sort(key=lambda x: x[1], reverse=True)
    top_2 = [x[0] for x in valid[:2]]
    
    a_eq = 0.5 if "SPY" in top_2 else 0
    a_cr = 0.15 if "BTC-USD" in top_2 else 0
    a_gld = 0.10 if "GLD" in top_2 else 0
    spillover = 1.0 - (a_eq + a_cr + a_gld)
    
    a_tlt, a_shv = 0, 0
    if df_m.loc[prev, "TLT"] > ma200.loc[prev, "TLT"] and mom130.loc[prev, "TLT"] > mom130.loc[prev, "SHV"]:
        a_tlt = spillover
    else:
        a_shv = spillover
        
    r_eq = sum([ret_m.loc[date, t] for t in eq_ticks]) / len(eq_ticks) if a_eq > 0 else 0
    r_cr = sum([ret_m.loc[date, t] for t in cr_ticks]) / len(cr_ticks) if a_cr > 0 else 0
    ret_cap.append((a_eq * r_eq) + (a_cr * r_cr) + (a_gld * ret_m.loc[date, "GLD"]) + (a_tlt * ret_m.loc[date, "TLT"]) + (a_shv * ret_m.loc[date, "SHV"]))
calc_metrics('Nuova Dual Mom Hard-Cap', ret_cap)

res_df = pd.DataFrame(results)
with open("compare_report.txt", "w") as f:
    f.write(res_df.to_string(index=False))
