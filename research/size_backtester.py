import yfinance as yf
import pandas as pd
import numpy as np

print("Download dati per Test Position Sizing...")
macro_ticks = ["SPY", "BTC-USD", "TLT", "SHV"]
eq_ticks = ["AAPL", "MSFT", "NVDA", "JPM", "V", "JNJ", "UNH", "XOM", "PG", "MA", "HD", "CVX", "ABBV", "MRK", "META", "AMZN", "GOOGL", "NFLX", "ADBE", "CRM", "AMD", "QCOM", "INTC", "CSCO", "PEP", "KO", "MCD", "WMT", "COST", "TGT"]
cr_ticks = ["BTC-USD", "ETH-USD", "XRP-USD", "LTC-USD", "ADA-USD", "DOGE-USD", "BCH-USD", "LINK-USD", "XLM-USD", "BNB-USD"]

all_ticks = list(set(macro_ticks + eq_ticks + cr_ticks))
df = yf.download(all_ticks, start="2018-01-01", end="2024-01-01", progress=False)['Close'].ffill().dropna(how='all')

# Gestisci NA
df = df.fillna(0)

df_m = df.resample('M').last()
ret_m = df_m.pct_change().fillna(0)
mom130 = df_m.pct_change(6).fillna(0)
ma200 = df.rolling(200).mean().resample('M').last().fillna(0)

results = []

for eq_top in [5, 10, 15, 20]:
    for cr_top in [2, 3, 5, 8]:
        port_ret = []
        for i in range(1, len(df_m)):
            date = df_m.index[i]
            prev = df_m.index[i-1]
            
            # Motore Macro
            # Valutiamo SPY e BTC per il macro
            valid_macro = []
            if df_m.loc[prev, "SPY"] > ma200.loc[prev, "SPY"]:
                valid_macro.append(("SPY", mom130.loc[prev, "SPY"]))
            if df_m.loc[prev, "BTC-USD"] > ma200.loc[prev, "BTC-USD"]:
                valid_macro.append(("BTC-USD", mom130.loc[prev, "BTC-USD"]))
                
            valid_macro.sort(key=lambda x: x[1], reverse=True)
            top_macro = [x[0] for x in valid_macro[:2]]
            
            alloc_eq = 0.5 if "SPY" in top_macro else 0
            alloc_cr = 0.5 if "BTC-USD" in top_macro else 0
            
            empty_slots = 2 - len(top_macro)
            alloc_tlt = 0
            alloc_shv = 0
            if empty_slots > 0:
                if df_m.loc[prev, "TLT"] > ma200.loc[prev, "TLT"] and mom130.loc[prev, "TLT"] > mom130.loc[prev, "SHV"]:
                    alloc_tlt = 0.5 * empty_slots
                else:
                    alloc_shv = 0.5 * empty_slots
                    
            # Motore Micro Azioni
            ret_eq = 0
            if alloc_eq > 0:
                valid_eq = [t for t in eq_ticks if df_m.loc[prev, t] > ma200.loc[prev, t]]
                if valid_eq:
                    best_eq = mom130.loc[prev, valid_eq].nlargest(eq_top).index.tolist()
                    ret_eq = sum([ret_m.loc[date, t] for t in best_eq]) / len(best_eq)
                    
            # Motore Micro Crypto
            ret_cr = 0
            if alloc_cr > 0:
                valid_cr = [t for t in cr_ticks if df_m.loc[prev, t] > ma200.loc[prev, t]]
                if valid_cr:
                    best_cr = mom130.loc[prev, valid_cr].nlargest(cr_top).index.tolist()
                    ret_cr = sum([ret_m.loc[date, t] for t in best_cr]) / len(best_cr)
                    
            period_ret = (alloc_eq * ret_eq) + (alloc_cr * ret_cr) + (alloc_tlt * ret_m.loc[date, "TLT"]) + (alloc_shv * ret_m.loc[date, "SHV"])
            port_ret.append(period_ret)
            
        eq = (1 + pd.Series(port_ret)).cumprod()
        if len(eq) > 0 and eq.iloc[-1] > 0:
            cagr = (eq.iloc[-1] ** (12/len(eq))) - 1
            max_dd = ((eq - eq.cummax()) / eq.cummax()).min()
            results.append({'Azioni_Top_N': eq_top, 'Crypto_Top_N': cr_top, 'CAGR_%': round(cagr*100, 2), 'Max_DD_%': round(max_dd*100, 2)})

res_df = pd.DataFrame(results).sort_values(by="CAGR_%", ascending=False)
with open("size_report.txt", "w") as f:
    f.write(res_df.to_string(index=False))
