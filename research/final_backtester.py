import yfinance as yf
import pandas as pd
import numpy as np

tickers = ["SPY", "BTC-USD", "GLD", "TLT", "SHV"]
try:
    df = yf.download(tickers, start="2016-01-01", end="2024-01-01", progress=False)['Close'].ffill().dropna()
except Exception as e:
    exit(1)

df_m = df.resample('M').last()
ret_m = df_m.pct_change().dropna()
mom130 = df_m.pct_change(6).dropna()

results = []

def get_metrics(name, port_returns):
    eq = (1 + port_returns).cumprod()
    if len(eq) == 0: return
    cagr = (eq.iloc[-1] ** (12/len(eq))) - 1
    max_dd = ((eq - eq.cummax()) / eq.cummax()).min()
    results.append({'Test': name, 'CAGR_%': round(cagr*100, 2), 'Max_DD_%': round(max_dd*100, 2)})

common_idx = ret_m.index.intersection(mom130.index)
risk_on = ["SPY", "BTC-USD", "GLD"]

for ma_period in [50, 100, 150, 200]:
    ma = df.rolling(ma_period).mean().resample('M').last()
    idx = common_idx.intersection(ma.index)
    port_ret = []
    for i in range(1, len(idx)):
        date = idx[i]
        prev = idx[i-1]
        valid = [t for t in risk_on if df_m.loc[prev, t] > ma.loc[prev, t]]
        if not valid:
            port_ret.append(0)
        else:
            best = mom130.loc[prev, valid].idxmax()
            port_ret.append(ret_m.loc[date, best])
    get_metrics(f'MA {ma_period} (No Paracadute)', pd.Series(port_ret, index=idx[1:]))

for ma_period in [100, 200]:
    ma = df.rolling(ma_period).mean().resample('M').last()
    idx = common_idx.intersection(ma.index)
    port_ret = []
    for i in range(1, len(idx)):
        date = idx[i]
        prev = idx[i-1]
        valid = [t for t in risk_on if df_m.loc[prev, t] > ma.loc[prev, t]]
        if not valid:
            if df_m.loc[prev, "TLT"] > ma.loc[prev, "TLT"] and mom130.loc[prev, "TLT"] > mom130.loc[prev, "SHV"]:
                port_ret.append(ret_m.loc[date, "TLT"])
            else:
                port_ret.append(ret_m.loc[date, "SHV"])
        else:
            best = mom130.loc[prev, valid].idxmax()
            port_ret.append(ret_m.loc[date, best])
    get_metrics(f'MA {ma_period} (Paracadute Bond/Cash)', pd.Series(port_ret, index=idx[1:]))

import pandas as pd
res_df = pd.DataFrame(results).sort_values(by="CAGR_%", ascending=False)
with open("final_report.txt", "w") as f:
    f.write(res_df.to_string(index=False))
