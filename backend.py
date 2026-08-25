import datetime
import pandas as pd
import numpy as np
import urllib.request
import json
import time
import random
from concurrent.futures import ThreadPoolExecutor, as_completed

def get_sp500_tickers():
    try:
        url = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response:
            tables = pd.read_html(response.read())
            return [t.replace('.', '-') for t in tables[0]['Symbol'].tolist()]
    except Exception:
        return ['AAPL', 'MSFT', 'NVDA', 'AMZN', 'META', 'GOOGL']

def fetch_single_ticker(symbol, period="2y", retries=3):
    url = f'https://query2.finance.yahoo.com/v8/finance/chart/{symbol}?range={period}&interval=1d'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    time.sleep(random.uniform(0.1, 0.4))
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
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
                return symbol, df
        except Exception:
            time.sleep(0.5)
    return symbol, None

def fetch_bulk_parallel(tickers, max_workers=3):
    results = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(fetch_single_ticker, sym): sym for sym in tickers}
        for future in as_completed(futures):
            sym, df = future.result()
            if df is not None:
                results[sym] = df
    return results

def calc_indicators(df_dict, roc_period=130):
    if not df_dict: return None
    
    closes = pd.DataFrame({k: v['Close'] for k, v in df_dict.items()}).ffill()
    highs = pd.DataFrame({k: v['High'] for k, v in df_dict.items()}).ffill()
    lows = pd.DataFrame({k: v['Low'] for k, v in df_dict.items()}).ffill()
    pc = closes.shift(1)
    
    ma200 = closes.rolling(window=200, min_periods=100).mean()
    ma150 = closes.rolling(window=150, min_periods=75).mean()
    
    tr = pd.DataFrame(index=closes.index)
    for col in closes.columns:
        if col in highs.columns and col in lows.columns:
            tr[col] = np.maximum(highs[col] - lows[col], np.maximum((highs[col] - pc[col]).abs(), (lows[col] - pc[col]).abs()))
            
    atr = tr.ewm(alpha=1/60, adjust=False).mean()
    score = (closes.pct_change(periods=roc_period) * 100) / ((atr / closes) * 100 + 1e-6)
    highest_high_60 = highs.rolling(window=60, min_periods=30).max()
    
    gaps = ((closes - pc) / pc) * 100
    gap_max = gaps.rolling(window=90, min_periods=1).max()
    gap_min = gaps.rolling(window=90, min_periods=1).min()
    
    return {
        'c': closes, 'm200': ma200, 'm150': ma150, 'atr': atr, 
        'score': score, 'hh60': highest_high_60, 'g_max': gap_max, 'g_min': gap_min
    }

def process_engine(df_dict, roc_period, atr_multiplier, gap_limit, is_crypto=False):
    inds = calc_indicators(df_dict, roc_period=roc_period)
    if not inds: return []
    
    results = []
    for sym in inds['c'].columns:
        c = float(inds['c'][sym].iloc[-1])
        m150 = float(inds['m150'][sym].iloc[-1]) if pd.notna(inds['m150'][sym].iloc[-1]) else 0
        sc = float(inds['score'][sym].iloc[-1]) if pd.notna(inds['score'][sym].iloc[-1]) else -99
        a = float(inds['atr'][sym].iloc[-1]) if pd.notna(inds['atr'][sym].iloc[-1]) else 0
        hh = float(inds['hh60'][sym].iloc[-1]) if pd.notna(inds['hh60'][sym].iloc[-1]) else c
        g_max = float(inds['g_max'][sym].iloc[-1]) if pd.notna(inds['g_max'][sym].iloc[-1]) else 0
        g_min = float(inds['g_min'][sym].iloc[-1]) if pd.notna(inds['g_min'][sym].iloc[-1]) else 0
        
        if sym == 'BTC-USD': sc *= 1.25 # Tax bonus
        
        trail_stop = hh - (atr_multiplier * a)
        
        # FILTRO DI FERRO ANTI-GHOST E ANTI-API VUOTE: c > 0.000001
        if c > 0.000001 and c > m150 and sc > 0 and g_max < gap_limit and g_min > -gap_limit and c > trail_stop:
            res_sym = sym.replace('-USD', '') if is_crypto else sym
            results.append({
                "Ticker": res_sym,
                "Prezzo ($)": round(c, 8 if is_crypto else 2),
                "Momentum Score": round(sc, 2),
                "Stop Loss ($)": round(trail_stop, 8 if is_crypto else 2)
            })
            
    df_res = pd.DataFrame(results).sort_values(by="Momentum Score", ascending=False)
    return df_res.to_dict(orient="records")

print("Avvio Motore Apex (Architettura Multithread Definitiva)...")
output = {"macro": {}, "top20": [], "crypto_top": [], "timestamp": datetime.datetime.now().strftime("%d %b %Y, %H:%M (UTC)")}

print("Elaborazione Macro...")
b_ticks = ['RSP', 'GC=F', 'IEF', 'BTC-USD']
b_data = fetch_bulk_parallel(b_ticks, max_workers=2)
b_inds = calc_indicators(b_data)
if b_inds:
    for sym in b_ticks:
        if sym in b_inds['c'].columns:
            output["macro"][sym] = {
                "price": float(b_inds['c'][sym].iloc[-1]),
                "ma200": float(b_inds['m200'][sym].iloc[-1]) if pd.notna(b_inds['m200'][sym].iloc[-1]) else 0,
                "atr": float(b_inds['atr'][sym].iloc[-1]) if pd.notna(b_inds['atr'][sym].iloc[-1]) else 0,
                "highest_high_60": float(b_inds['hh60'][sym].iloc[-1]) if pd.notna(b_inds['hh60'][sym].iloc[-1]) else float(b_inds['c'][sym].iloc[-1])
            }

print("Elaborazione Azioni (S&P 500)...")
eq_ticks = get_sp500_tickers()
eq_data = fetch_bulk_parallel(eq_ticks, max_workers=3)
output["top20"] = process_engine(eq_data, roc_period=130, atr_multiplier=3.5, gap_limit=15.0)[:20]

print("Elaborazione Crypto...")
try:
    req_k = urllib.request.Request('https://futures.kraken.com/derivatives/api/v3/instruments', headers={'User-Agent': 'Mozilla/5.0'})
    kr_data = json.loads(urllib.request.urlopen(req_k).read().decode())['instruments']
    kr_syms = [i['symbol'][3:-3].upper() for i in kr_data if i.get('tradeable') and i['symbol'].startswith('PF_') and i['symbol'].endswith('USD')]
    if "XBT" in kr_syms: kr_syms.append("BTC")
    if "XDG" in kr_syms: kr_syms.append("DOGE")
    
    req_cg = urllib.request.Request('https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=market_cap_desc&per_page=100&page=1', headers={'User-Agent': 'Mozilla/5.0'})
    cg_data = json.loads(urllib.request.urlopen(req_cg).read().decode())
    
    BLACKLIST = ['USDT', 'USDC', 'DAI', 'FDUSD', 'USDE', 'WBTC', 'WETH', 'STETH', 'WSTETH', 'USDS', 'USD1', 'USDG', 'CC', 'RAIN', 'HYPE']
    c_ticks = [d['symbol'].upper() + '-USD' for d in cg_data if d['symbol'].upper() in kr_syms and d['symbol'].upper() not in BLACKLIST][:30]
except Exception:
    c_ticks = ['BTC-USD', 'ETH-USD', 'SOL-USD', 'XRP-USD', 'ADA-USD', 'DOGE-USD']

cr_data = fetch_bulk_parallel(c_ticks, max_workers=2)
output["crypto_top"] = process_engine(cr_data, roc_period=90, atr_multiplier=2.0, gap_limit=40.0, is_crypto=True)[:3]

with open('apex_data.json', 'w') as f:
    json.dump(output, f, indent=4)
print("Apex Backend elaborato con successo!")

# ==============================
# NOTIFICHE TELEGRAM
# ==============================
def send_telegram_alert(data_dict):
    import os
    import urllib.parse
    
    token = os.environ.get("TELEGRAM_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    
    if not token or not chat_id:
        print("Credenziali Telegram non trovate (o non configurate). Skip alert.")
        return
        
    try:
        macro = data_dict.get("macro", {})
        is_eq = macro.get("RSP", {}).get("price", 0) > macro.get("RSP", {}).get("ma200", 0)
        is_cr = macro.get("BTC-USD", {}).get("price", 0) > macro.get("BTC-USD", {}).get("ma200", 0)
        is_g = macro.get("GC=F", {}).get("price", 0) > macro.get("GC=F", {}).get("ma200", 0)
        is_b = macro.get("IEF", {}).get("price", 0) > macro.get("IEF", {}).get("ma200", 0)
        
        msg = f"🦅 *APEX ENGINE UPDATE* 🦅\n"
        msg += f"🕒 _{data_dict.get('timestamp', '')}_\n\n"
        
        msg += "🎛️ *COCKPIT MACRO*\n"
        msg += f"📈 Azionario: {'🟢 INVESTITO' if is_eq else '🔴 LIQUIDO'}\n"
        msg += f"🪙 Crypto: {'🟢 INVESTITO' if is_cr else '🔴 LIQUIDO'}\n"
        msg += f"🥇 Oro: {'🟢 INVESTITO' if is_g else '🔴 LIQUIDO'}\n"
        msg += f"🛡️ Bond: {'🟢 INVESTITO' if is_b else '🔴 LIQUIDO'}\n\n"
        
        msg += "📋 *TOP 5 AZIONI (S&P 500)*\n"
        if is_eq and "top20" in data_dict and data_dict["top20"]:
            for i, row in enumerate(data_dict["top20"][:5]):
                msg += f"{i+1}. {row['Ticker']} (Mom: {row['Momentum Score']} | Stop: ${row['Stop Loss ($)']})\n"
        else:
            msg += "Semaforo Rosso - Azionario disattivato.\n"
            
        msg += "\n🪙 *TOP 3 CRYPTO*\n"
        if is_cr and "crypto_top" in data_dict and data_dict["crypto_top"]:
            for i, row in enumerate(data_dict["crypto_top"][:3]):
                msg += f"{i+1}. {row['Ticker']} (Mom: {row['Momentum Score']} | Stop: ${row['Stop Loss ($)']})\n"
        else:
            msg += "Semaforo Rosso - Crypto disattivate.\n"
            
        msg += "\n💡 _Vai sulla Dashboard per la lista completa._"
        
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        data = urllib.parse.urlencode({
            "chat_id": chat_id,
            "text": msg,
            "parse_mode": "Markdown"
        }).encode('utf-8')
        
        req = urllib.request.Request(url, data=data)
        urllib.request.urlopen(req)
        print("Alert Telegram inviato con successo nel Canale!")
    except Exception as e:
        print(f"Errore nell'invio Telegram: {e}")

# Invia la notifica alla fine dello script
send_telegram_alert(output)

