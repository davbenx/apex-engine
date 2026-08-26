import datetime
import json
import os
import random
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd


def get_sp500_tickers():
    try:
        url = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
        req = urllib.request.Request(
            url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response:
            tables = pd.read_html(response.read())
            return [t.replace('.', '-') for t in tables[0]['Symbol'].tolist()]
    except Exception as e:
        print(f'Errore SP500: {e}')
        return ['AAPL', 'MSFT', 'NVDA', 'AMZN', 'META', 'GOOGL']


def fetch_single_ticker(symbol, period="2y", retries=3):
    url = f'https://query2.finance.yahoo.com/v8/finance/chart/{symbol}?range={period}&interval=1d'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    time.sleep(random.uniform(0.1, 0.4))
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode())[
                    'chart']['result'][0]
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
        futures = {executor.submit(
            fetch_single_ticker, sym): sym for sym in tickers}
        for future in as_completed(futures):
            sym, df = future.result()
            if df is not None:
                results[sym] = df
    return results


def calc_indicators(df_dict, roc_period=130):
    if not df_dict:
        return None

    closes = pd.DataFrame({k: v['Close'] for k, v in df_dict.items()}).ffill()
    highs = pd.DataFrame({k: v['High'] for k, v in df_dict.items()}).ffill()
    lows = pd.DataFrame({k: v['Low'] for k, v in df_dict.items()}).ffill()
    opens = pd.DataFrame({k: v['Open'] for k, v in df_dict.items()}).ffill()
    pc = closes.shift(1)

    ma200 = closes.rolling(window=200, min_periods=100).mean()
    ma150 = closes.rolling(window=150, min_periods=75).mean()

    hl = highs - lows
    hp = (highs - pc).abs()
    lp = (lows - pc).abs()
    tr = pd.DataFrame(np.maximum(hl.values, np.maximum(
        hp.values, lp.values)), index=closes.index, columns=closes.columns)

    atr = tr.ewm(alpha=1/60, adjust=False).mean()
    score = (closes.pct_change(periods=roc_period) * 100) / \
        ((atr / closes) * 100 + 1e-6)
    highest_high_60 = highs.rolling(window=60, min_periods=30).max()

    gaps = ((closes - pc) / pc) * 100
    gap_max = gaps.rolling(window=90, min_periods=1).max()
    gap_min = gaps.rolling(window=90, min_periods=1).min()

    return {
        'c': closes, 'low': lows, 'm200': ma200, 'm150': ma150, 'atr': atr,
        'score': score, 'hh60': highest_high_60, 'g_max': gap_max, 'g_min': gap_min
    }


def process_engine(inds, atr_multiplier, gap_limit, is_crypto=False):
    if not inds:
        return []

    results = []
    for sym in inds['c'].columns:
        # REGOLA: Se non ci sono almeno 150 giorni di storico per la media mobile, scarta e prendi la successiva
        if inds['m150'][sym].empty or pd.isna(inds['m150'][sym].iloc[-1]):
            continue

        c = float(inds['c'].iloc[-1][sym])
        m150 = float(inds['m150'].iloc[-1][sym])
        sc = float(inds['score'].iloc[-1][sym]
                   ) if pd.notna(inds['score'].iloc[-1][sym]) else -99
        a = float(inds['atr'].iloc[-1][sym]
                  ) if pd.notna(inds['atr'].iloc[-1][sym]) else 0
        hh = float(inds['hh60'].iloc[-1][sym]
                   ) if pd.notna(inds['hh60'].iloc[-1][sym]) else c
        g_max = float(inds['g_max'].iloc[-1][sym]
                      ) if pd.notna(inds['g_max'].iloc[-1][sym]) else 0
        g_min = float(inds['g_min'].iloc[-1][sym]
                      ) if pd.notna(inds['g_min'].iloc[-1][sym]) else 0

        if sym == 'BTC-USD':
            sc *= 1.25  # Tax bonus

        trail_stop = hh - (atr_multiplier * a)

        # Filtro di ammissione
        if c > 0.000001 and c > m150 and sc > 0 and g_max < gap_limit and g_min > -gap_limit and c > trail_stop:
            res_sym = sym.replace('-USD', '') if is_crypto else sym
            results.append({
                "Ticker": res_sym,
                "Prezzo ($)": round(c, 8 if is_crypto else 2),
                "Momentum Score": round(sc, 2),
                "Stop Loss ($)": round(trail_stop, 8 if is_crypto else 2)
            })

    df_res = pd.DataFrame(results).sort_values(
        by="Momentum Score", ascending=False)
    return df_res.to_dict(orient="records")


print("Avvio Motore Apex (Architettura Multithread Definitiva)...")
output = {"macro": {}, "top20": [], "crypto_top": [],
          "timestamp": datetime.datetime.now().strftime("%d %b %Y, %H:%M (UTC)")}

print("Elaborazione Macro (Waterfall Allocation)...")
b_ticks = ['SPY', 'BTC-USD', 'GC=F', 'TLT', 'SHV']
b_data = fetch_bulk_parallel(b_ticks, max_workers=2)

macro = {}
for t in b_ticks:
    if b_data[t].empty:
        continue
    df = b_data[t].resample('D').last().ffill()
    df_m = df.resample('ME').last()

    price = df['Close'].iloc[-1]
    try:
        ma200 = df['Close'].rolling(200).mean().iloc[-1]
    except:
        ma200 = price
    try:
        mom = df_m['Close'].pct_change(6).iloc[-1]
    except:
        mom = 0.0

    macro[t] = {'price': price, 'ma200': ma200, 'mom': mom}

output["macro"] = macro

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
    if capital <= 0:
        break

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
        allocations["Bonds"] = capital
        capital = 0

if capital > 0:
    tlt = macro.get("TLT", {})
    shv = macro.get("SHV", {})
    if tlt.get('price', 0) > tlt.get('ma200', 0) and tlt.get('mom', 0) > shv.get('mom', 0):
        allocations["Bonds"] += capital
    else:
        allocations["Cash"] += capital

output["allocations"] = allocations


today_str = datetime.datetime.now().strftime("%Y-%m-%d")
macro_dates = {}
macro_events = []

old_data = None
try:
    if os.path.exists("apex_data.json"):
        with open("apex_data.json", "r") as f:
            old_data = json.load(f)
except:
    pass

old_alloc = old_data.get("allocations", {}) if old_data else {}
old_dates = old_data.get("macro_dates", {}) if old_data else {}

for engine in ["Equities", "Crypto", "Gold", "Bonds"]:
    was_active = old_alloc.get(engine, 0) > 0
    is_active = allocations.get(engine, 0) > 0

    if was_active == is_active and engine in old_dates:
        macro_dates[engine] = old_dates[engine]
    else:
        macro_dates[engine] = today_str
        if old_data is not None:  # Not the first run
            stato_nuovo = "🟢 ATTIVATO" if is_active else "🔴 DISATTIVATO"
            macro_events.append(
                f"⚠️ MACRO REGIME: Il motore {engine} è passato a {stato_nuovo}")

output["macro_dates"] = macro_dates
output["macro_events"] = macro_events

if allocations["Equities"] > 0:
    print("Elaborazione Azioni (S&P 500)...")
    eq_ticks = get_sp500_tickers()
    eq_data = fetch_bulk_parallel(eq_ticks, max_workers=3)
    eq_inds = calc_indicators(eq_data, roc_period=130)
    output["top20"] = process_engine(eq_inds, atr_multiplier=3.5, gap_limit=15.0)[:20]
else:
    output["top20"] = []
    eq_data = {}
    eq_inds = None

if allocations["Crypto"] > 0:
    print("Elaborazione Crypto...")
    try:
        # Recupera i ticker tradabili su Kraken Futures (Perp)
        req_k = urllib.request.Request(
            'https://futures.kraken.com/derivatives/api/v3/instruments', headers={'User-Agent': 'Mozilla/5.0'})
        kr_data = json.loads(urllib.request.urlopen(
            req_k).read().decode())['instruments']
        kr_syms = [d['symbol'].upper() for d in kr_data if d['tradeable']
                   and 'PI_XBT' not in d['symbol']]

        kr_bases = set()
        for s in kr_syms:
            s = s.replace('PI_', '').replace('PF_', '').replace('USD', '')
            if s == 'XBT':
                s = 'BTC'
            kr_bases.add(s)

        url = "https://query2.finance.yahoo.com/v1/finance/screener/predefined/saved?formatted=false&lang=en-US&region=US&scrIds=all_cryptocurrencies_us&start=0&count=100"
        req_y = urllib.request.Request(
            url, headers={'User-Agent': 'Mozilla/5.0'})
        res_y = urllib.request.urlopen(req_y).read().decode()
        quotes = json.loads(res_y)['finance']['result'][0]['quotes']

        BLACKLIST = ['USDT', 'USDC', 'FDUSD', 'TUSD', 'DAI', 'STETH', 'WSTETH', 'WBTC',
                     'WBETH', 'WETH', 'AETHWETH', 'BTCB', 'WEETH', 'USDE', 'USDG', 'USDS', 'CBBTC',
                     'XAUT', 'PAXG', 'KAG', 'KAU', 'EURT', 'EURC', 'PYUSD', 'BUSD', 'USDD', 'FRAX']

        c_ticks = []
        for q in quotes:
            sym = q['symbol']
            base = sym.replace('-USD', '')
            if base not in BLACKLIST and not any(char.isdigit() for char in base) and base in kr_bases:
                c_ticks.append(sym)

        c_ticks = c_ticks[:30]

    except Exception as e:
        print("Errore nel recupero lista crypto:", e)
        c_ticks = []

    if not c_ticks:
        c_ticks = ['BTC-USD', 'ETH-USD', 'SOL-USD',
                   'XRP-USD', 'ADA-USD', 'DOGE-USD']

    cr_data = fetch_bulk_parallel(c_ticks, max_workers=2)
    cr_inds = calc_indicators(cr_data, roc_period=90)
    output["crypto_top"] = process_engine(cr_inds, atr_multiplier=2.0, gap_limit=40.0, is_crypto=True)[:3]

else:
    output["crypto_top"] = []
    cr_data = {}
    cr_inds = None

# ==============================
# EQUITY CURVE TRACKER
# ==============================


def update_equity_curve(data_dict, b_inds, eq_inds, cr_inds):

    eq_file = 'equity.json'
    if os.path.exists(eq_file):
        with open(eq_file, 'r') as f:
            eq_data = json.load(f)
    else:
        eq_data = {"history": [{"date": (datetime.datetime.now(
        ) - datetime.timedelta(days=1)).strftime("%Y-%m-%d"), "value": 100000.0}]}

    last_value = eq_data["history"][-1]["value"]
    last_date = eq_data["history"][-1]["date"]
    today_str = datetime.datetime.now().strftime("%Y-%m-%d")

    if last_date == today_str:
        return  # Già aggiornato oggi

    # Calcolo ritorni giornalieri
    def get_ret(inds, sym):
        if inds and sym in inds['c'].columns and len(inds['c'][sym]) > 5:
            # Ritorno a 5 giorni di borsa (esattamente 1 settimana: da Venerdì scorso a questo Venerdì)
            return float(inds['c'][sym].iloc[-1] / inds['c'][sym].iloc[-6]) - 1.0
        return 0.0

    alloc = data_dict.get(
        "allocations", {"Equities": 0, "Crypto": 0, "Gold": 0, "Bonds": 0, "Cash": 100})

    ret_eq = 0.0
    if alloc["Equities"] > 0 and "top20" in data_dict and data_dict["top20"]:
        rets = [get_ret(eq_inds, row["Ticker"]) for row in data_dict["top20"]]
        ret_eq = sum(rets) / len(rets) if rets else 0.0

    ret_cr = 0.0
    if alloc["Crypto"] > 0 and "crypto_top" in data_dict and data_dict["crypto_top"]:
        rets = [get_ret(cr_inds, row["Ticker"] + "-USD")
                for row in data_dict["crypto_top"]]
        ret_cr = sum(rets) / len(rets) if rets else 0.0

    ret_g = get_ret(b_inds, "GC=F") if alloc["Gold"] > 0 else 0.0
    ret_b = get_ret(b_inds, "TLT") if alloc["Bonds"] > 0 else 0.0

    # Ritorno Totale Portafoglio dinamico pesato per le allocations
    tot_ret = ((alloc["Equities"]/100.0) * ret_eq) + ((alloc["Crypto"]/100.0) *
                                                      ret_cr) + ((alloc["Gold"]/100.0) * ret_g) + ((alloc["Bonds"]/100.0) * ret_b)

    new_value = last_value * (1.0 + tot_ret)
    open_val = round(last_value, 2)
    close_val = round(new_value, 2)
    high_val = round(max(open_val, close_val) * 1.002, 2)
    low_val = round(min(open_val, close_val) * 0.998, 2)
    eq_data["history"].append({
        "date": today_str,
        "open": open_val,
        "high": high_val,
        "low": low_val,
        "close": close_val,
        "value": close_val
    })

    with open(eq_file, 'w') as f:
        json.dump(eq_data, f, indent=4)
    print(f"Equity Curve aggiornata: {new_value}")

# Chiamata al tracker


with open('apex_data.json', 'w') as f:
    json.dump(output, f, indent=4)
print("Apex Backend elaborato con successo!")


# ==============================
# TRADE LOGGER & PORTFOLIO STATE
# ==============================
def update_portfolio(output, b_inds, eq_inds, cr_inds):

    pf_file = 'portfolio.json'
    if os.path.exists(pf_file):
        with open(pf_file, 'r') as f:
            pf = json.load(f)
    else:
        pf = {"open_positions": {}, "macro_positions": {}, "trade_history": [], "pending_alerts": []}

    if "pending_alerts" not in pf:
        pf["pending_alerts"] = []
    if "macro_positions" not in pf:
        pf["macro_positions"] = {}

    today = datetime.datetime.now()
    is_rotation = today.weekday() == 4 and (
        today + datetime.timedelta(days=7)).month != today.month
    today_str = today.strftime("%Y-%m-%d")

    action_log = []

    # 1. Check Stop Losses & Update Trailing Stops (Daily/Weekly)
    sold_keys = []
    for ticker, pos in pf["open_positions"].items():
        is_crypto = pos.get("is_crypto", False)
        inds = cr_inds if is_crypto else eq_inds
        sym = ticker + "-USD" if is_crypto else ticker

        if inds and sym in inds['c'].columns:
            low_price = float(
                inds['low'][sym].iloc[-1]) if 'low' in inds else float(inds['c'][sym].iloc[-1])
            close_price = float(inds['c'][sym].iloc[-1])
            # Salva il prezzo attuale per la dashboard
            pos["current_price"] = close_price

            # Aggiornamento Trailing Stop (solo a salire, SOLO IL VENERDI)
            if today.weekday() == 4:
                try:
                    atr = float(inds['atr'][sym].iloc[-1])
                    new_stop = close_price - (atr * 2.0)
                    if new_stop > pos["stop_loss"]:
                        pos["stop_loss"] = new_stop
                except:
                    pass

            # Stop loss hit
            if low_price < pos["stop_loss"]:
                open_price = float(
                    inds['open'][sym].iloc[-1]) if 'open' in inds else float(inds['c'][sym].iloc[-1])

                if open_price < pos["stop_loss"]:
                    exit_price = open_price
                else:
                    exit_price = pos["stop_loss"]

                profit_pct = (exit_price / pos["entry_price"]) - 1.0
                pf["trade_history"].append({
                    "ticker": ticker,
                    "entry_date": pos["entry_date"],
                    "exit_date": today_str,
                    "entry_price": pos["entry_price"],
                    "exit_price": exit_price,
                    "profit_pct": round(profit_pct * 100, 2),
                    "reason": "Stop Loss"
                })
                action_log.append(
                    f"🔴 STOP LOSS: {ticker} venduto a {exit_price:.2f} ({round(profit_pct*100, 2)}%)")
                sold_keys.append(ticker)

    for k in sold_keys:
        del pf["open_positions"][k]

    # Create missing macro positions if currently allocated
    for asset, sym in [("Gold", "GC=F"), ("Bonds", "TLT")]:
        if output["allocations"].get(asset, 0) > 0:
            if asset not in pf.setdefault("macro_positions", {}):
                try:
                    price = float(b_inds['c'][sym].iloc[-1])
                except:
                    price = 0.0
                pf["macro_positions"][asset] = {"entry_date": today_str, "entry_price": price}

    # Update current prices for macro positions
    for asset, pos in pf.get("macro_positions", {}).items():
        sym = "GC=F" if asset == "Gold" else "TLT"
        try:
            pos["current_price"] = float(b_inds['c'][sym].iloc[-1])
        except:
            pos["current_price"] = pos["entry_price"]


    # 2. Weekly Actions (Macro Shifts & Deploying Cash)
    if today.weekday() == 4:
        alloc = output["allocations"]

        # Sell assets if their macro engine is OFF
        forced_sells = []
        for ticker, pos in list(pf["open_positions"].items()):
            is_crypto = pos.get("is_crypto", False)
            if is_crypto and alloc["Crypto"] == 0:
                forced_sells.append(ticker)
            elif not is_crypto and alloc["Equities"] == 0:
                forced_sells.append(ticker)

        for ticker in forced_sells:
            pos = pf["open_positions"][ticker]
            is_crypto = pos.get("is_crypto", False)
            inds = cr_inds if is_crypto else eq_inds
            sym = ticker + "-USD" if is_crypto else ticker
            close_price = float(
                inds['c'][sym].iloc[-1]) if inds and sym in inds['c'].columns else pos["entry_price"]

            profit_pct = (close_price / pos["entry_price"]) - 1.0
            pf["trade_history"].append({
                "ticker": ticker,
                "entry_date": pos["entry_date"],
                "exit_date": today_str,
                "entry_price": pos["entry_price"],
                "exit_price": close_price,
                "profit_pct": round(profit_pct * 100, 2),
                "reason": "Macro Bear"
            })
            action_log.append(
                f"🔴 MACRO BEAR: {ticker} liquidato a {close_price:.2f} ({round(profit_pct*100, 2)}%)")
            del pf["open_positions"][ticker]

        # Buy missing assets to deploy cash (if Macro is ON)
        if alloc["Equities"] > 0:
            current_eq = len(
                [k for k, v in pf["open_positions"].items() if not v.get("is_crypto", False)])
            to_buy = 20 - current_eq
            if to_buy > 0:
                for row in output.get("top20", []):
                    ticker = row["Ticker"]
                    if ticker not in pf["open_positions"]:
                        pf["open_positions"][ticker] = {
                            "entry_date": today_str,
                            "entry_price": row["Prezzo ($)"],
                            "stop_loss": row["Stop Loss ($)"],
                            "is_crypto": False
                        }
                        action_log.append(
                            f"🟢 ACQUISTO SETTIMANALE (Reinvestimento Cash): {ticker} a {row['Prezzo ($)']}")
                        to_buy -= 1
                        if to_buy == 0:
                            break

        if alloc["Crypto"] > 0:
            # We don't dynamically add crypto based on count, we just buy the top 3 if missing
            for row in output.get("crypto_top", []):
                ticker = row["Ticker"]
                if ticker not in pf["open_positions"]:
                    pf["open_positions"][ticker] = {
                        "entry_date": today_str,
                        "entry_price": row["Prezzo ($)"],
                        "stop_loss": row["Stop Loss ($)"],
                        "is_crypto": True
                    }
                    action_log.append(
                        f"🟢 ACQUISTO SETTIMANALE CRYPTO: {ticker} a {row['Prezzo ($)']}")

        # --- MACRO POSITIONS (GOLD & BONDS) TRACKING ---
        for asset, sym in [("Gold", "GC=F"), ("Bonds", "TLT")]:
            if alloc[asset] > 0:
                if asset not in pf["macro_positions"]:
                    try:
                        price = float(b_inds['c'][sym].iloc[-1])
                    except:
                        price = 0.0
                    pf["macro_positions"][asset] = {"entry_date": today_str, "entry_price": price}
                    action_log.append(f"🛡️ HEDGE ATTIVATO: {asset} a {price:.2f}")
            else:
                if asset in pf["macro_positions"]:
                    pos = pf["macro_positions"][asset]
                    try:
                        exit_price = float(b_inds['c'][sym].iloc[-1])
                    except:
                        exit_price = pos["entry_price"]
                    profit_pct = (exit_price / pos["entry_price"]) - 1.0 if pos["entry_price"] > 0 else 0
                    pf["trade_history"].append({
                        "ticker": asset + " (Hedge)",
                        "entry_date": pos["entry_date"],
                        "exit_date": today_str,
                        "entry_price": pos["entry_price"],
                        "exit_price": exit_price,
                        "profit_pct": round(profit_pct * 100, 2),
                        "reason": "Hedge Chiuso"
                    })
                    action_log.append(f"🛑 HEDGE CHIUSO: {asset} a {exit_price:.2f} ({round(profit_pct*100, 2)}%)")
                    del pf["macro_positions"][asset]


    # 3. Monthly Rotation (Sell underperformers that dropped out of rankings)
    if is_rotation:
        desired = {}
        for row in output.get("top20", []):
            desired[row["Ticker"]] = True
        for row in output.get("crypto_top", []):
            desired[row["Ticker"]] = True

        sold_rot = []
        for ticker, pos in list(pf["open_positions"].items()):
            if ticker not in desired:
                is_crypto = pos.get("is_crypto", False)
                inds = cr_inds if is_crypto else eq_inds
                sym = ticker + "-USD" if is_crypto else ticker
                close_price = float(
                    inds['c'][sym].iloc[-1]) if inds and sym in inds['c'].columns else pos["entry_price"]

                profit_pct = (close_price / pos["entry_price"]) - 1.0
                pf["trade_history"].append({
                    "ticker": ticker,
                    "entry_date": pos["entry_date"],
                    "exit_date": today_str,
                    "entry_price": pos["entry_price"],
                    "exit_price": close_price,
                    "profit_pct": round(profit_pct * 100, 2),
                    "reason": "Rotazione"
                })
                action_log.append(
                    f"🔄 ROTAZIONE (VENDITA): {ticker} chiuso a {close_price:.2f} ({round(profit_pct*100, 2)}%)")
                sold_rot.append(ticker)

        for k in sold_rot:
            del pf["open_positions"][k]

    with open(pf_file, 'w') as f:
        json.dump(pf, f, indent=4)

    return action_log


# ==============================
# Calcolo unico indicatori Macro (gli altri sono calcolati sopra)
b_inds = calc_indicators(b_data)

# Aggiorna l'Equity Curve OGNI GIORNO
update_equity_curve(output, b_inds, eq_inds, cr_inds)

# Aggiorna il Portfolio Logger
action_log = update_portfolio(output, b_inds, eq_inds, cr_inds)

# ==============================
# NOTIFICHE TELEGRAM
# ==============================


def send_telegram_alert(data_dict, action_log):
    token = os.environ.get("TELEGRAM_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        print("Credenziali Telegram non trovate (o non configurate). Skip alert.")
        return

    try:
        def fmt(val):
            try:
                v = float(val)
                return f"{v:.2f}" if v > 1 else f"{v:.6f}"
            except:
                return str(val)

        msg = f"🦅 *APEX ENGINE UPDATE* 🦅\n"
        msg += f"🕒 _{data_dict.get('timestamp', '')}_\n\n"

        # 1. Action Log (if any weekly actions or macro actions triggered)
        macro_evs = data_dict.get('macro_events', [])
        if macro_evs:
            msg += "🚨 *ALLERTA MACRO REGIME* 🚨\n"
            for ev in macro_evs:
                msg += f"• {ev}\n"
            msg += "\n"

        if action_log:
            msg += "🚀 *AZIONI DA ESEGUIRE OGGI*\n"
            for log in action_log:
                if "ACQUISTO" in log or "VENDITA" in log or "BEAR" in log:
                    msg += f"• {log}\n"
            msg += "\n"

        # 2. Macro Cockpit
        msg += "🎛️ *COCKPIT MACRO*\n"
        eq_icon = "🟢" if data_dict['allocations']['Equities'] > 0 else "🔴"
        cr_icon = "🟢" if data_dict['allocations']['Crypto'] > 0 else "🔴"
        g_icon = "🟢" if data_dict['allocations']['Gold'] > 0 else "🔴"
        b_icon = "🟢" if data_dict['allocations']['Bonds'] > 0 else "🔴"

        msg += f"{eq_icon} Azionario: {data_dict['allocations']['Equities']}%\n"
        msg += f"{cr_icon} Crypto: {data_dict['allocations']['Crypto']}%\n"
        msg += f"{g_icon} Oro: {data_dict['allocations']['Gold']}%\n"
        msg += f"{b_icon} Bond: {data_dict['allocations']['Bonds']}%\n"
        msg += f"⚪ Cash: {data_dict['allocations']['Cash']}%\n\n"

        # 3. Portfolio Stops
        pf_file = 'portfolio.json'
        if os.path.exists(pf_file):
            with open(pf_file, 'r') as f:
                pf = json.load(f)

            msg += "💼 *IL TUO PORTAFOGLIO (AGGIORNA STOP)*\n"
            open_pos = pf.get("open_positions", {})
            if open_pos:
                for ticker, info in open_pos.items():
                    msg += f"• {ticker} (Nuovo Stop: {fmt(info['stop_loss'])})\n"
            else:
                msg += "Nessuna posizione aperta.\n"

        # 4. Rotation Radar (Only on last Friday)
        today = datetime.datetime.now()
        is_rotation = today.weekday() == 4 and (
            today + datetime.timedelta(days=7)).month != today.month

        if is_rotation:
            msg += "\n🔄 *RADAR ROTAZIONE MENSILE*\n"
            msg += "Controlla la Dashboard per rimpiazzare le vendite.\n"

        msg += "\n💡 _Vai sulla Dashboard per operare._"

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


# Invia Telegram solo il Venerdì, OPPURE se c'è stato un cambio di Regime Macro
if datetime.datetime.now().weekday() == 4 or output.get("macro_events", []):
    send_telegram_alert(output, action_log)
else:
    print("Nessun alert Telegram oggi (non è Venerdì e nessun cambio macro).")
