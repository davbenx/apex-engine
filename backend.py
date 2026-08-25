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

print("Elaborazione Macro (Waterfall Allocation)...")
b_ticks = ['SPY', 'BTC-USD', 'GC=F', 'TLT', 'SHV']
b_data = fetch_bulk_parallel(b_ticks, max_workers=2)

macro = {}
for t in b_ticks:
    if b_data[t].empty: continue
    df = b_data[t].resample('D').last().ffill()
    df_m = df.resample('M').last()
    
    price = df['Close'].iloc[-1]
    try: ma200 = df['Close'].rolling(200).mean().iloc[-1]
    except: ma200 = price
    try: mom = df_m['Close'].pct_change(6).iloc[-1]
    except: mom = 0.0
    
    macro[t] = {'price': price, 'ma200': ma200, 'mom': mom}

# Waterfall Allocation
allocations = {"Equities": 0, "Crypto": 0, "Gold": 0, "Bonds": 0, "Cash": 0}

valid_macro = []
for m in ["SPY", "BTC-USD", "GC=F", "TLT"]:
    if m in macro and macro[m]['price'] > macro[m]['ma200']:
        valid_macro.append((m, macro[m]['mom']))

valid_macro.sort(key=lambda x: x[1], reverse=True)
ranked = [x[0] for x in valid_macro]

capital = 100
for m in ranked:
    if capital <= 0: break
    
    if m == "BTC-USD":
        take = min(15, capital)
        allocations["Crypto"] = take
        capital -= take
    elif m == "GC=F":
        take = min(10, capital)
        allocations["Gold"] = take
        capital -= take
    elif m == "SPY":
        take = min(70, capital)
        allocations["Equities"] = take
        capital -= take
    elif m == "TLT":
        # Se TLT è in classifica prima del Cash Spillover, si prende tutto lo spazio rimasto
        allocations["Bonds"] = capital
        capital = 0

# Spillover di sicurezza (se avanza capitale non assorbito dai Tetti)
if capital > 0:
    tlt = macro.get("TLT", {})
    shv = macro.get("SHV", {})
    if tlt.get('price', 0) > tlt.get('ma200', 0) and tlt.get('mom', 0) > shv.get('mom', 0):
        allocations["Bonds"] += capital
    else:
        allocations["Cash"] += capital

output["allocations"] = allocations

bull_eq = allocations["Equities"] > 0
bull_cr = allocations["Crypto"] > 0 json
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

print("Elaborazione Macro (Dynamic Dual Momentum)...")
b_ticks = ['SPY', 'BTC-USD', 'GC=F', 'TLT', 'SHV']
b_data = fetch_bulk_parallel(b_ticks, max_workers=2)

macro = {}
for t in b_ticks:
    if b_data[t].empty: continue
    df = b_data[t].resample('D').last().ffill()
    df_m = df.resample('M').last()
    
    price = df['Close'].iloc[-1]
    try: ma200 = df['Close'].rolling(200).mean().iloc[-1]
    except: ma200 = price
    try: mom = df_m['Close'].pct_change(6).iloc[-1]
    except: mom = 0.0
    
    macro[t] = {'price': price, 'ma200': ma200, 'mom': mom}

# Calcolo Pesi Macro
allocations = {"Equities": 0, "Crypto": 0, "Gold": 0, "Bonds": 0, "Cash": 0}
risk_on_map = {"SPY": "Equities", "BTC-USD": "Crypto", "GC=F": "Gold"}

valid_risk_on = []
for t in risk_on_map.keys():
    if t in macro and macro[t]['price'] > macro[t]['ma200']:
        valid_risk_on.append((t, macro[t]['mom']))

valid_risk_on.sort(key=lambda x: x[1], reverse=True)
top_2 = [x[0] for x in valid_risk_on[:2]]

for t in top_2:
    allocations[risk_on_map[t]] += 50

# Slot vuoti vanno nel Safe Haven
empty_slots = 2 - len(top_2)
if empty_slots > 0:
    tlt = macro.get("TLT", {})
    shv = macro.get("SHV", {})
    
    if tlt.get('price', 0) > tlt.get('ma200', 0) and tlt.get('mom', 0) > shv.get('mom', 0):
        allocations["Bonds"] += (50 * empty_slots)
    else:
        allocations["Cash"] += (50 * empty_slots)

output["allocations"] = allocations

bull_eq = allocations["Equities"] > 0
bull_cr = allocations["Crypto"] > 0

    ret_eq = 0.0
    if bull_eq and "top20" in data_dict and data_dict["top20"]:
        rets = [get_ret(eq_inds, row["Ticker"]) for row in data_dict["top20"]]
        ret_eq = sum(rets) / len(rets) if rets else 0.0
        
    ret_cr = 0.0
    if bull_cr and "crypto_top" in data_dict and data_dict["crypto_top"]:
        rets = [get_ret(cr_inds, row["Ticker"] + "-USD") for row in data_dict["crypto_top"]]
        ret_cr = sum(rets) / len(rets) if rets else 0.0
        
    ret_g = get_ret(b_inds, "GC=F") if bull_g else 0.0
    ret_b = get_ret(b_inds, "IEF") if bull_b else 0.0
    
    # Ritorno Totale Portafoglio
    tot_ret = (0.70 * ret_eq) + (0.10 * ret_cr) + (0.10 * ret_g) + (0.10 * ret_b)
    
    new_value = last_value * (1.0 + tot_ret)
    eq_data["history"].append({"date": today_str, "value": round(new_value, 2)})
    
    with open(eq_file, 'w') as f:
        json.dump(eq_data, f, indent=4)
    print(f"Equity Curve aggiornata: {new_value}")

# Chiamata al tracker

# Aggiorna l'Equity Curve SOLO il Venerdì
if datetime.datetime.now().weekday() == 4:
    update_equity_curve(output, b_inds, calc_indicators(eq_data), calc_indicators(cr_data))


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
        
        
        def fmt(val):
            try:
                v = float(val)
                return f"{v:.2f}" if v > 1 else f"{v:.6f}"
            except:
                return str(val)

        msg = f"🦅 *APEX ENGINE UPDATE* 🦅\n"
        msg += f"🕒 _{data_dict.get('timestamp', '')}_\n\n"
        
        msg += "🎛️ *COCKPIT MACRO*\n"
        msg += f"📈 Azionario: {data_dict['allocations']['Equities']}%
"
        msg += f"🪙 Crypto: {data_dict['allocations']['Crypto']}%
"
        msg += f"🥇 Oro: {data_dict['allocations']['Gold']}%
"
        msg += f"🛡️ Bond (TLT): {data_dict['allocations']['Bonds']}%
"
        msg += f"💵 Cash: {data_dict['allocations']['Cash']}%

"

        
        msg += "📋 *TOP 20 AZIONI (S&P 500)*\n"
        if bull_eq and "top20" in data_dict and data_dict["top20"]:
            for i, row in enumerate(data_dict["top20"]):
                msg += f"{i+1}. {row['Ticker']} (Stop: ${fmt(row['Stop Loss ($)'])})\n"
        else:
            msg += "Semaforo Rosso - Azionario disattivato.\n"
            
        msg += "\n🪙 *TOP 3 CRYPTO*\n"
        if bull_cr and "crypto_top" in data_dict and data_dict["crypto_top"]:
            for i, row in enumerate(data_dict["crypto_top"]):
                msg += f"{i+1}. {row['Ticker']} (Stop: ${fmt(row['Stop Loss ($)'])})\n"
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

import os
import datetime
# Invia Telegram solo il Venerdì (weekday == 4) o se lanciato a mano (workflow_dispatch)
is_friday = datetime.datetime.now().weekday() == 4
is_manual = os.environ.get('GITHUB_EVENT_NAME') == 'workflow_dispatch'
if is_friday or is_manual:
    send_telegram_alert(output)
else:
    print("Nessun alert Telegram oggi (non è Venerdì).")


