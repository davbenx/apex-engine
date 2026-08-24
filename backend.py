import pandas as pd
import numpy as np
import urllib.request
import json
import time
import os

def get_sp500_tickers():
    try:
        url = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response:
            tables = pd.read_html(response.read())
            return [t.replace('.', '-') for t in tables[0]['Symbol'].tolist()]
    except Exception:
        return ['AAPL', 'MSFT', 'NVDA', 'AMZN', 'META', 'GOOGL', 'TSLA']

def fetch_single_ticker(symbol, period="2y"):
    try:
        url = f'https://query2.finance.yahoo.com/v8/finance/chart/{symbol}?range={period}&interval=1d'
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode())['chart']['result'][0]
            timestamps = pd.to_datetime(data['timestamp'], unit='s')
            quote = data['indicators']['quote'][0]
            df = pd.DataFrame({
                'Open': quote['open'],
                'High': quote['high'],
                'Low': quote['low'],
                'Close': quote['close']
            }, index=timestamps).ffill().dropna()
            df = df[~df.index.duplicated(keep='first')]
            return df
    except Exception:
        return None

def calc_indicators(opens, closes, highs, lows, roc_period=130):
    ma200 = closes.rolling(window=200, min_periods=100).mean()
    ma150 = closes.rolling(window=150, min_periods=75).mean()
    pc = closes.shift(1)
    
    tr = pd.DataFrame(index=closes.index)
    for col in closes.columns:
        if col in highs.columns and col in lows.columns:
            h = highs[col]; l = lows[col]; p = pc[col]
            tr[col] = np.maximum(h - l, np.maximum((h - p).abs(), (l - p).abs()))
            
    # Wilder's Smoothing per ATR (alpha = 1/60)
    atr = tr.ewm(alpha=1/60, adjust=False).mean()
    
    # Momentum Score
    roc130 = closes.pct_change(periods=roc_period) * 100
    natr = (atr / closes) * 100
    score = roc130 / (natr + 1e-6)
    
    # Chandelier Exit (Highest High in last 60 days)
    highest_high_60 = highs.rolling(window=60, min_periods=30).max()
    
    # Gap Up e Gap Down su 90 giorni
    gaps = ((closes - pc) / pc) * 100
    gap_max = gaps.rolling(window=90, min_periods=1).max()
    gap_min = gaps.rolling(window=90, min_periods=1).min()
    
    return ma200, ma150, atr, score, highest_high_60, gap_max, gap_min

print("Inizio calcolo backend Apex (Aggiornato con Wilder e Chandelier)...")
output_data = {"macro": {}, "top20": []}

# MACRO ASSETS (Sostituito SPY con RSP)
benchmarks = ['RSP', 'GC=F', 'IEF', 'BTC-USD']
b_opens, b_closes, b_highs, b_lows = {}, {}, {}, {}
for sym in benchmarks:
    df = fetch_single_ticker(sym)
    if df is not None:
        b_opens[sym] = df['Open']; b_closes[sym] = df['Close']; b_highs[sym] = df['High']; b_lows[sym] = df['Low']
    time.sleep(1)

if b_closes:
    df_o = pd.DataFrame(b_opens).ffill()
    df_c = pd.DataFrame(b_closes).ffill()
    df_h = pd.DataFrame(b_highs).ffill()
    df_l = pd.DataFrame(b_lows).ffill()
    ma200, _, atr, _, _, _, _ = calc_indicators(df_o, df_c, df_h, df_l)
    
    highest_high_60 = df_h.rolling(window=60, min_periods=30).max()
    for sym in benchmarks:
        if sym in df_c.columns:
            c = float(df_c[sym].iloc[-1])
            m = float(ma200[sym].iloc[-1])
            a = float(atr[sym].iloc[-1]) if pd.notna(atr[sym].iloc[-1]) else 0.0
            hh = float(highest_high_60[sym].iloc[-1]) if pd.notna(highest_high_60[sym].iloc[-1]) else c
            output_data["macro"][sym] = {"price": c, "ma200": m, "atr": a, "highest_high_60": hh}

# AZIONI TOP 20
tickers = get_sp500_tickers()
opens, closes, highs, lows = {}, {}, {}, {}
for i, sym in enumerate(tickers):
    df = fetch_single_ticker(sym)
    if df is not None:
        opens[sym] = df['Open']; closes[sym] = df['Close']; highs[sym] = df['High']; lows[sym] = df['Low']
    time.sleep(0.1)

if closes:
    df_o = pd.DataFrame(opens).ffill()
    df_c = pd.DataFrame(closes).ffill()
    df_h = pd.DataFrame(highs).ffill()
    df_l = pd.DataFrame(lows).ffill()
    
    ma200, ma150, atr, score, hh60, gap_max, gap_min = calc_indicators(df_o, df_c, df_h, df_l)
    
    results = []
    for sym in df_c.columns:
        c = float(df_c[sym].iloc[-1])
        m150 = float(ma150[sym].iloc[-1]) if pd.notna(ma150[sym].iloc[-1]) else 0
        sc = float(score[sym].iloc[-1]) if pd.notna(score[sym].iloc[-1]) else -99
        a = float(atr[sym].iloc[-1]) if pd.notna(atr[sym].iloc[-1]) else 0
        max_h60 = float(hh60[sym].iloc[-1]) if pd.notna(hh60[sym].iloc[-1]) else c
        g_max = float(gap_max[sym].iloc[-1]) if pd.notna(gap_max[sym].iloc[-1]) else 0
        g_min = float(gap_min[sym].iloc[-1]) if pd.notna(gap_min[sym].iloc[-1]) else 0
        
        # Filtro: Prezzo > MA150, Score > 0, Niente GapUp > 15%, Niente GapDn < -15%
        trail_stop_eq = max_h60 - (3.5 * a)
        if c > m150 and sc > 0 and g_max < 15.0 and g_min > -15.0 and c > trail_stop_eq:
            results.append({
                "Ticker": sym, 
                "Prezzo ($)": round(c, 2), 
                "Momentum Score": round(sc, 2), 
                "Stop Loss ($)": round(max_h60 - (3.5 * a), 2)
            })
            
    df_res = pd.DataFrame(results).sort_values(by="Momentum Score", ascending=False).head(20)
    output_data["top20"] = df_res.to_dict(orient="records")




# ==============================
# MOTORE CRIPTOVALUTE (DINAMICO KRAKEN)
# ==============================
print("Ricerca Universo Cripto (Kraken API + CoinGecko)...")

try:
    # 1. Asset Kraken
    req_k = urllib.request.Request('https://api.kraken.com/0/public/Assets', headers={'User-Agent': 'Mozilla/5.0'})
    kraken_data = json.loads(urllib.request.urlopen(req_k).read().decode())['result']
    kraken_symbols = [info['altname'].upper() for key, info in kraken_data.items()]
    
    # 2. Mappature storiche
    if "XBT" in kraken_symbols: kraken_symbols.append("BTC")
    if "XDG" in kraken_symbols: kraken_symbols.append("DOGE")
    
    # 3. Top 100 CoinGecko
    req_cg = urllib.request.Request('https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=market_cap_desc&per_page=100&page=1', headers={'User-Agent': 'Mozilla/5.0'})
    cg_data = json.loads(urllib.request.urlopen(req_cg).read().decode())
    
    # 4. Blacklist (Solo Stablecoin, Wrapped e Falsi Positivi evidenti. WBT è permesso)
    BLACKLIST = ['USDT', 'USDC', 'DAI', 'FDUSD', 'USDE', 'WBTC', 'WETH', 'STETH', 'WSTETH', 'USDS', 'USD1', 'USDG', 'CC', 'RAIN', 'HYPE']
                 
    crypto_tickers = []
    for d in cg_data:
        sym = d['symbol'].upper()
        if sym in kraken_symbols and sym not in BLACKLIST:
            crypto_tickers.append(sym + '-USD')
            
    print(f"Trovate {len(crypto_tickers)} coin globali tradabili su Kraken.")
except Exception as e:
    print("Errore API, uso fallback...")
    crypto_tickers = ['BTC-USD', 'ETH-USD', 'SOL-USD', 'XRP-USD', 'ADA-USD', 'DOGE-USD', 'TRX-USD', 'DOT-USD', 'LINK-USD', 'AVAX-USD', 'SHIB-USD', 'LTC-USD', 'BCH-USD', 'NEAR-USD', 'UNI-USD']

crypto_tickers = crypto_tickers[:30]
c_opens, c_closes, c_highs, c_lows = {}, {}, {}, {}
for i, sym in enumerate(crypto_tickers):
    df = fetch_single_ticker(sym)
    if df is not None:
        c_opens[sym] = df['Open']; c_closes[sym] = df['Close']; c_highs[sym] = df['High']; c_lows[sym] = df['Low']
    time.sleep(0.1)

if c_closes:
    df_o = pd.DataFrame(c_opens).ffill()
    df_c = pd.DataFrame(c_closes).ffill()
    df_h = pd.DataFrame(c_highs).ffill()
    df_l = pd.DataFrame(c_lows).ffill()
    
    # ROC a 90 giorni per le Crypto
    ma200_c, ma150_c, atr_c, score_c, hh60_c, gap_max_c, gap_min_c = calc_indicators(df_o, df_c, df_h, df_l, roc_period=90)
    
    # BONUS FISCALE: +25% al Momentum Score del Bitcoin per compensare l'efficienza dell'ETP
    if 'BTC-USD' in score_c.columns:
        score_c['BTC-USD'] = score_c['BTC-USD'] * 1.25
        
    results_c = []
    for sym in df_c.columns:
        c = float(df_c[sym].iloc[-1])
        m150 = float(ma150_c[sym].iloc[-1]) if pd.notna(ma150_c[sym].iloc[-1]) else 0
        sc = float(score_c[sym].iloc[-1]) if pd.notna(score_c[sym].iloc[-1]) else -99
        a = float(atr_c[sym].iloc[-1]) if pd.notna(atr_c[sym].iloc[-1]) else 0
        max_h60 = float(hh60_c[sym].iloc[-1]) if pd.notna(hh60_c[sym].iloc[-1]) else c
        g_max = float(gap_max_c[sym].iloc[-1]) if pd.notna(gap_max_c[sym].iloc[-1]) else 0
        g_min = float(gap_min_c[sym].iloc[-1]) if pd.notna(gap_min_c[sym].iloc[-1]) else 0
        
        # Filtro Crypto: Prezzo > MA150, Score > 0, Limite Gap a 40%
        trail_stop_cr = max_h60 - (2.0 * a)
        if c > m150 and sc > 0 and g_max < 40.0 and g_min > -40.0 and c > trail_stop_cr:
            results_c.append({
                "Ticker": sym.replace("-USD", ""), 
                "Prezzo ($)": round(c, 4), 
                "Momentum Score": round(sc, 2),
                "Stop Loss ($)": round(max_h60 - (2.0 * a), 4)
            })
            
    df_res_c = pd.DataFrame(results_c).sort_values(by="Momentum Score", ascending=False).head(3) # Top 3 altcoin
    output_data["crypto_top"] = df_res_c.to_dict(orient="records")

with open('apex_data.json', 'w') as f:

    json.dump(output_data, f, indent=4)
print("Dati salvati in apex_data.json con successo!")
