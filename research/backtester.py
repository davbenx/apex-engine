import yfinance as yf
import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings('ignore')

print("=== LABORATORIO R&D: BACKTEST PROFONDO ===")

def get_metrics(returns, periods=252):
    eq = (1 + returns).cumprod()
    if len(eq) == 0: return 0, 0
    cagr = (eq.iloc[-1] ** (periods/len(eq))) - 1
    peak = eq.cummax()
    dd = (eq - peak) / peak
    return cagr * 100, dd.min() * 100

print("\n1. TEST LIMITE SETTORIALE (Massimo 1 per Settore)")
tickers = {
    'Tech': ['AAPL', 'MSFT', 'NVDA', 'AVGO', 'CSCO'],
    'Fin': ['JPM', 'BAC', 'WFC', 'GS', 'MS'],
    'Health': ['JNJ', 'UNH', 'PFE', 'ABBV', 'MRK']
}
flat = [t for sub in tickers.values() for t in sub]
try:
    df = yf.download(flat, start="2010-01-01", end="2024-01-01", progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df = df['Close']
    df = df.ffill().dropna()
    df_m = df.resample('M').last()
    
    mom = df_m.pct_change(6).dropna()
    ret = df.pct_change()
    
    base_r, cap_r = [], []
    for i in range(1, len(mom)):
        d = mom.index[i]
        pd_d = mom.index[i-1]
        
        curr_mom = mom.loc[pd_d].dropna()
        if curr_mom.empty: continue
        
        top_base = curr_mom.nlargest(3).index.tolist()
        
        top_cap = []
        counts = {'Tech': 0, 'Fin': 0, 'Health': 0}
        for t in curr_mom.sort_values(ascending=False).index:
            sec = 'Tech' if t in tickers['Tech'] else ('Fin' if t in tickers['Fin'] else 'Health')
            if counts[sec] < 1:
                top_cap.append(t)
                counts[sec] += 1
            if len(top_cap) == 3: break
            
        m_data = ret.loc[(ret.index > pd_d) & (ret.index <= d)]
        
        base_r.extend(m_data[top_base].mean(axis=1).values if top_base else [0.0]*len(m_data))
        cap_r.extend(m_data[top_cap].mean(axis=1).values if top_cap else [0.0]*len(m_data))
        
    s_b = pd.Series(base_r).fillna(0)
    s_c = pd.Series(cap_r).fillna(0)
    
    cb, db = get_metrics(s_b)
    cc, dc = get_metrics(s_c)
    print(f"Top 3 (Senza Limiti) -> CAGR: {cb:.2f}% | Max Drawdown: {db:.2f}%")
    print(f"Top 3 (Max 1 per Settore) -> CAGR: {cc:.2f}% | Max Drawdown: {dc:.2f}%")
except Exception as e:
    print("Errore nel test settoriale:", e)

print("\n2. TEST RIBILANCIAMENTO INTELLIGENTE (Annuale vs Mensile su 60/40)")
try:
    df_m = yf.download(["SPY", "TLT"], start="2005-01-01", end="2024-01-01", progress=False)['Close'].ffill().dropna()
    
    def run_rebal(df, freq='M'):
        if freq == 'M': d = df.resample('M').last()
        else: d = df.resample('Y').last()
        
        rets = d.pct_change().dropna()
        port = (rets['SPY']*0.6) + (rets['TLT']*0.4)
        return get_metrics(port, 12 if freq=='M' else 1)
        
    cm, dm = run_rebal(df_m, 'M')
    ca, da = run_rebal(df_m, 'Y')
    
    print(f"Ribilanciamento Mensile -> CAGR: {cm:.2f}% | Max Drawdown: {dm:.2f}%")
    print(f"Ribilanciamento Annuale -> CAGR: {ca:.2f}% | Max Drawdown: {da:.2f}%")
except Exception as e:
    print("Errore nel test ribilanciamento:", e)
