import yfinance as yf
import pandas as pd
import numpy as np

print("Scaricamento dati Macro...")
tickers = ["SPY", "BTC-USD", "GLD", "TLT"]
try:
    df = yf.download(tickers, start="2016-01-01", end="2024-01-01", progress=False)['Close'].ffill().dropna()
except Exception as e:
    print(f"Error downloading: {e}")
    exit(1)

df_m = df.resample('M').last()
ret_m = df_m.pct_change().dropna()
ma200 = df.rolling(200).mean().resample('M').last()
mom130 = df_m.pct_change(6).dropna() # 6 mesi ~ 130 giorni

results = []

def calc_metrics(name, port_returns):
    eq = (1 + port_returns).cumprod()
    cagr = (eq.iloc[-1] ** (12/len(eq))) - 1
    max_dd = ((eq - eq.cummax()) / eq.cummax()).min()
    results.append({'Strategia': name, 'CAGR_%': round(cagr*100, 2), 'Max_DD_%': round(max_dd*100, 2)})

# Allineiamo gli indici
common_idx = ret_m.index.intersection(mom130.index).intersection(ma200.index)

# 1. Baseline Attuale: 70 Eq / 10 Cr / 10 Go / 10 Bo (Se sotto MA200 -> Cash a rendimento 0)
base_ret = []
for i in range(1, len(common_idx)):
    date = common_idx[i]
    prev = common_idx[i-1]
    
    r_spy = ret_m.loc[date, "SPY"] if df_m.loc[prev, "SPY"] > ma200.loc[prev, "SPY"] else 0
    r_btc = ret_m.loc[date, "BTC-USD"] if df_m.loc[prev, "BTC-USD"] > ma200.loc[prev, "BTC-USD"] else 0
    r_gld = ret_m.loc[date, "GLD"] if df_m.loc[prev, "GLD"] > ma200.loc[prev, "GLD"] else 0
    r_tlt = ret_m.loc[date, "TLT"] if df_m.loc[prev, "TLT"] > ma200.loc[prev, "TLT"] else 0
    
    port_r = (0.7 * r_spy) + (0.1 * r_btc) + (0.1 * r_gld) + (0.1 * r_tlt)
    base_ret.append(port_r)
calc_metrics('1. Attuale (70-10-10-10 con Filtro)', pd.Series(base_ret, index=common_idx[1:]))

# 2. Aggressiva: 80% SPY / 20% BTC (Niente Oro o Bond)
agg_ret = []
for i in range(1, len(common_idx)):
    date = common_idx[i]
    prev = common_idx[i-1]
    r_spy = ret_m.loc[date, "SPY"] if df_m.loc[prev, "SPY"] > ma200.loc[prev, "SPY"] else 0
    r_btc = ret_m.loc[date, "BTC-USD"] if df_m.loc[prev, "BTC-USD"] > ma200.loc[prev, "BTC-USD"] else 0
    agg_ret.append((0.8 * r_spy) + (0.2 * r_btc))
calc_metrics('2. Aggressiva (80 Eq - 20 BTC)', pd.Series(agg_ret, index=common_idx[1:]))

# 3. Dual Momentum "All-In" (100% nel singolo Asset con Momentum più alto)
dm1_ret = []
for i in range(1, len(common_idx)):
    date = common_idx[i]
    prev = common_idx[i-1]
    
    # Prendi gli asset sopra MA200
    valid = []
    for t in tickers:
        if df_m.loc[prev, t] > ma200.loc[prev, t]:
            valid.append(t)
            
    if not valid:
        dm1_ret.append(0) # Cash
    else:
        # Ordina i validi per Momentum
        best = mom130.loc[prev, valid].idxmax()
        dm1_ret.append(ret_m.loc[date, best])
calc_metrics('3. Dual Momentum Estremo (100% nel Top 1)', pd.Series(dm1_ret, index=common_idx[1:]))

# 4. Dual Momentum "Bilanciato" (50% e 50% nei Top 2 Asset con Momentum più alto)
dm2_ret = []
for i in range(1, len(common_idx)):
    date = common_idx[i]
    prev = common_idx[i-1]
    
    valid = []
    for t in tickers:
        if df_m.loc[prev, t] > ma200.loc[prev, t]:
            valid.append(t)
            
    if not valid:
        dm2_ret.append(0)
    else:
        top2 = mom130.loc[prev, valid].nlargest(2).index.tolist()
        r = sum([ret_m.loc[date, x] for x in top2]) / len(top2)
        dm2_ret.append(r)
calc_metrics('4. Dual Momentum Bilanciato (50% nei Top 2)', pd.Series(dm2_ret, index=common_idx[1:]))

import pandas as pd
res_df = pd.DataFrame(results)
with open("macro_report.txt", "w") as f:
    f.write(res_df.to_string(index=False))
