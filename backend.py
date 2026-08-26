"""
Apex Multi-Asset Quantitative Engine (Genesis Core Release)
Autonomous quantitative engine for Waterfall Macro Allocation, Cross-Sectional Momentum,
Trailing Stops, Dynamic Portfolio Tracking, and Telegram Notifications.
"""

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

# ==============================================================================
# CONFIGURATION & CONSTANTS
# ==============================================================================
INITIAL_CAPITAL = 100_000.0

# Position Sizing Weights
EQUITY_POSITION_WEIGHT = 0.05       # 5% per equity position
BTC_POSITION_WEIGHT = 0.10          # 10% for Bitcoin
ALTCOIN_POSITION_WEIGHT = 0.05      # 5% for other cryptocurrencies
MAX_EQUITY_POSITIONS = 20
MAX_CRYPTO_POSITIONS = 3

# Waterfall Macro Class Caps (%)
MAX_EQUITIES_ALLOCATION = 70
MAX_CRYPTO_ALLOCATION = 15
MAX_GOLD_ALLOCATION = 10

# Quantitative Screening Parameters
EQUITIES_ROC_PERIOD = 130
CRYPTO_ROC_PERIOD = 90
EQUITIES_GAP_LIMIT = 15.0
CRYPTO_GAP_LIMIT = 40.0
ATR_STOP_MULTIPLIER = 3.0
ATR_ALPHA = 1 / 60
MA_LONG_PERIOD = 200
MA_MID_PERIOD = 150
HH_PERIOD = 60
GAP_PERIOD = 90

# Persistence File Names
APEX_DATA_FILE = 'apex_data.json'
PORTFOLIO_FILE = 'portfolio.json'
EQUITY_FILE = 'equity.json'

# Benchmarks & Universes
BENCHMARK_TICKERS = ['RSP', 'SPY', 'BTC-USD', 'GC=F', 'IEF']
CRYPTO_FALLBACK = ['BTC-USD', 'ETH-USD', 'SOL-USD', 'XRP-USD', 'ADA-USD', 'DOGE-USD']
CRYPTO_BLACKLIST = {
    'USDT', 'USDC', 'FDUSD', 'TUSD', 'DAI', 'STETH', 'WSTETH', 'WBTC',
    'WBETH', 'WETH', 'AETHWETH', 'BTCB', 'WEETH', 'USDE', 'USDG', 'USDS', 'CBBTC',
    'XAUT', 'PAXG', 'KAG', 'KAU', 'EURT', 'EURC', 'PYUSD', 'BUSD', 'USDD', 'FRAX'
}
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
MAX_WORKERS_DEFAULT = 3
MAX_WORKERS_CRYPTO = 2
HTTP_TIMEOUT = 10


# ==============================================================================
# ATOMIC I/O & FORMATTING UTILITIES
# ==============================================================================
def save_json_atomic(filepath, data, indent=4):
    """Safely writes JSON to a temporary file first, then atomically replaces target."""
    tmp_path = f"{filepath}.tmp"
    with open(tmp_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=indent)
    os.replace(tmp_path, filepath)


def load_json_safe(filepath, default=None):
    """Loads JSON file with error resilience."""
    if default is None:
        default = {}
    if not os.path.exists(filepath):
        return default
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"[!] Errore lettura {filepath} ({e}). Utilizzo default.")
        return default


def fmt_usd(price):
    """Formats numeric prices into clean USD strings with dynamic precision."""
    if price is None or pd.isna(price):
        return "$0.00"
    try:
        val = float(price)
        return f"${val:,.2f}" if abs(val) >= 1.0 else f"${val:,.6f}"
    except Exception:
        return f"${price}"


def is_rebalancing_schedule(dt=None):
    """Determines if the given date is a rebalancing Friday or monthly rotation."""
    if dt is None:
        dt = datetime.datetime.now()
    is_friday = (dt.weekday() == 4)
    next_fri = dt + datetime.timedelta(days=7)
    is_rotation = is_friday and (next_fri.month != dt.month)
    return is_friday, is_rotation


# ==============================================================================
# DATA INGESTION & NETWORK UTILITIES
# ==============================================================================
def get_sp500_tickers():
    """Fetches the latest list of S&P 500 tickers from Wikipedia."""
    try:
        url = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
        req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as response:
            tables = pd.read_html(response.read())
            return [t.replace('.', '-') for t in tables[0]['Symbol'].tolist()]
    except Exception as e:
        print(f"[!] Errore recupero lista S&P 500 ({e}). Utilizzo fallback...")
        return ['AAPL', 'MSFT', 'NVDA', 'AMZN', 'META', 'GOOGL', 'TSLA', 'JPM', 'LLY', 'AVGO']


def fetch_single_ticker(symbol, period="2y", retries=3):
    """Fetches OHLC daily history for a single ticker via Yahoo Finance API."""
    url = f'https://query2.finance.yahoo.com/v8/finance/chart/{symbol}?range={period}&interval=1d'
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    time.sleep(random.uniform(0.05, 0.25))

    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as response:
                payload = json.loads(response.read().decode())
                result = payload.get('chart', {}).get('result')
                if not result:
                    return symbol, None
                data = result[0]
                timestamps = pd.to_datetime(data['timestamp'], unit='s')
                quote = data['indicators']['quote'][0]

                df = pd.DataFrame({
                    'Open': quote.get('open', []),
                    'High': quote.get('high', []),
                    'Low': quote.get('low', []),
                    'Close': quote.get('close', [])
                }, index=timestamps).ffill().dropna()

                df = df[~df.index.duplicated(keep='first')]
                if not df.empty:
                    return symbol, df
        except Exception:
            time.sleep(0.4 * (attempt + 1))
    return symbol, None


def fetch_bulk_parallel(tickers, max_workers=MAX_WORKERS_DEFAULT):
    """Fetches multiple tickers in parallel with a managed ThreadPoolExecutor."""
    results = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(fetch_single_ticker, sym): sym for sym in tickers}
        for future in as_completed(futures):
            sym, df = future.result()
            if df is not None and not df.empty:
                results[sym] = df
    return results


def get_tradable_crypto_universe():
    """Fetches actively traded spot/perp crypto candidates on Kraken & Yahoo Finance."""
    try:
        req_k = urllib.request.Request(
            'https://futures.kraken.com/derivatives/api/v3/instruments',
            headers={'User-Agent': USER_AGENT}
        )
        kr_data = json.loads(urllib.request.urlopen(req_k, timeout=8).read().decode())['instruments']
        kr_bases = set()
        for d in kr_data:
            if d.get('tradeable'):
                s = d['symbol'].upper().replace('PI_', '').replace('PF_', '').replace('USD', '')
                if s == 'XBT':
                    s = 'BTC'
                kr_bases.add(s)

        url = "https://query2.finance.yahoo.com/v1/finance/screener/predefined/saved?formatted=false&lang=en-US&region=US&scrIds=all_cryptocurrencies_us&start=0&count=100"
        req_y = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
        res_y = urllib.request.urlopen(req_y, timeout=8).read().decode()
        quotes = json.loads(res_y)['finance']['result'][0]['quotes']

        c_ticks = []
        for q in quotes:
            sym = q['symbol']
            base = sym.replace('-USD', '')
            if base not in CRYPTO_BLACKLIST and not any(char.isdigit() for char in base) and base in kr_bases:
                c_ticks.append(sym)
        return c_ticks[:30] if c_ticks else CRYPTO_FALLBACK
    except Exception as e:
        print(f"[!] Errore recupero lista crypto dinamica ({e}). Uso fallback predefinito.")
        return CRYPTO_FALLBACK


# ==============================================================================
# QUANTITATIVE INDICATOR ENGINE
# ==============================================================================
def calc_indicators(df_dict, roc_period=130):
    """Calculates ROC momentum, 150/200 MA, ATR(60), Highest High(60), and Gap volatility."""
    if not df_dict:
        return None

    closes = pd.DataFrame({k: v['Close'] for k, v in df_dict.items()}).ffill()
    highs = pd.DataFrame({k: v['High'] for k, v in df_dict.items()}).ffill()
    lows = pd.DataFrame({k: v['Low'] for k, v in df_dict.items()}).ffill()
    opens = pd.DataFrame({k: v['Open'] for k, v in df_dict.items()}).ffill()
    prev_closes = closes.shift(1)

    ma200 = closes.rolling(window=MA_LONG_PERIOD, min_periods=100).mean()
    ma150 = closes.rolling(window=MA_MID_PERIOD, min_periods=75).mean()

    hl = highs - lows
    hp = (highs - prev_closes).abs()
    lp = (lows - prev_closes).abs()
    tr = pd.DataFrame(np.maximum(hl.values, np.maximum(hp.values, lp.values)),
                      index=closes.index, columns=closes.columns)

    atr = tr.ewm(alpha=ATR_ALPHA, adjust=False).mean()
    score = (closes.pct_change(periods=roc_period) * 100) / ((atr / closes) * 100 + 1e-6)
    highest_high_60 = highs.rolling(window=HH_PERIOD, min_periods=30).max()

    gaps = ((closes - prev_closes) / prev_closes) * 100
    gap_max = gaps.rolling(window=GAP_PERIOD, min_periods=1).max()
    gap_min = gaps.rolling(window=GAP_PERIOD, min_periods=1).min()

    return {
        'c': closes, 'low': lows, 'open': opens, 'high': highs,
        'm200': ma200, 'm150': ma150, 'atr': atr,
        'score': score, 'hh60': highest_high_60,
        'g_max': gap_max, 'g_min': gap_min
    }


def process_engine(inds, atr_multiplier, gap_limit, is_crypto=False):
    """Filters, scores, and ranks asset universe based on quantitative criteria."""
    if not inds or inds['c'].empty:
        return []

    results = []
    for sym in inds['c'].columns:
        if inds['m150'][sym].empty or pd.isna(inds['m150'][sym].iloc[-1]):
            continue

        c = float(inds['c'][sym].iloc[-1])
        m150 = float(inds['m150'][sym].iloc[-1])
        sc = float(inds['score'][sym].iloc[-1]) if pd.notna(inds['score'][sym].iloc[-1]) else -99.0
        a = float(inds['atr'][sym].iloc[-1]) if pd.notna(inds['atr'][sym].iloc[-1]) else 0.0
        hh = float(inds['hh60'][sym].iloc[-1]) if pd.notna(inds['hh60'][sym].iloc[-1]) else c
        g_max = float(inds['g_max'][sym].iloc[-1]) if pd.notna(inds['g_max'][sym].iloc[-1]) else 0.0
        g_min = float(inds['g_min'][sym].iloc[-1]) if pd.notna(inds['g_min'][sym].iloc[-1]) else 0.0

        trail_stop = hh - (atr_multiplier * a)

        # Quantitative admission filters
        if c > 0.000001 and c > m150 and sc > 0 and g_max < gap_limit and g_min > -gap_limit and c > trail_stop:
            res_sym = sym.replace('-USD', '') if is_crypto else sym
            results.append({
                "Ticker": res_sym,
                "Prezzo ($)": round(c, 6 if is_crypto and c < 1 else 2),
                "Momentum Score": round(sc, 2),
                "Stop Loss ($)": round(trail_stop, 6 if is_crypto and trail_stop < 1 else 2)
            })

    df_res = pd.DataFrame(results).sort_values(by="Momentum Score", ascending=False)
    return df_res.to_dict(orient="records")


# ==============================================================================
# MACRO ENGINE & WATERFALL ALLOCATION
# ==============================================================================
def calculate_macro_allocation(b_data):
    """Computes regime metrics and resolves optimal capital distribution via fixed-hierarchy Waterfall."""
    macro = {}
    for t in BENCHMARK_TICKERS:
        if t not in b_data or b_data[t].empty:
            continue
        df = b_data[t]
        price = float(df['Close'].iloc[-1])
        ma200 = float(df['Close'].rolling(MA_LONG_PERIOD, min_periods=100).mean().iloc[-1]) if len(df) >= 100 else price
        macro[t] = {'price': price, 'ma200': ma200}

    allocations = {"Equities": 0, "Crypto": 0, "Gold": 0, "Bonds": 0, "Cash": 0}
    eq_bench = "RSP" if "RSP" in macro else "SPY"
    capital = 100

    # 1. Azioni (Max 70%)
    if eq_bench in macro and macro[eq_bench]['price'] > macro[eq_bench]['ma200']:
        take = min(MAX_EQUITIES_ALLOCATION, capital)
        allocations["Equities"] = take
        capital -= take

    # 2. Crypto (Max 15%)
    if "BTC-USD" in macro and macro["BTC-USD"]['price'] > macro["BTC-USD"]['ma200']:
        take = min(MAX_CRYPTO_ALLOCATION, capital)
        allocations["Crypto"] = take
        capital -= take

    # 3. Oro (Max 10%)
    if "GC=F" in macro and macro["GC=F"]['price'] > macro["GC=F"]['ma200']:
        take = min(MAX_GOLD_ALLOCATION, capital)
        allocations["Gold"] = take
        capital -= take

    # 4. Obbligazioni (Resto del capitale, senza cap se trend positivo)
    if capital > 0:
        if "IEF" in macro and macro["IEF"]['price'] > macro["IEF"]['ma200']:
            allocations["Bonds"] = capital
            capital = 0

    # 5. Cash (Fondo Monetario per tutto cio' che avanza se i Bond sono negativi)
    if capital > 0:
        allocations["Cash"] = capital

    return macro, allocations


def update_macro_regimes(allocations, old_data, today_str):
    """Tracks regime transition dates and detects trigger events for notifications."""
    macro_dates = {}
    macro_events = []
    old_alloc = old_data.get("allocations", {}) if old_data else {}
    old_dates = old_data.get("macro_dates", {}) if old_data else {}

    for engine in ["Equities", "Crypto", "Gold", "Bonds"]:
        was_active = old_alloc.get(engine, 0) > 0
        is_active = allocations.get(engine, 0) > 0

        if was_active == is_active and engine in old_dates:
            macro_dates[engine] = old_dates[engine]
        else:
            macro_dates[engine] = today_str
            if old_data is not None:
                status_label = "🟢 ATTIVATO" if is_active else "🔴 DISATTIVATO"
                macro_events.append(f"⚠️ MACRO REGIME: Il motore {engine} è passato a {status_label}")

    return macro_dates, macro_events


# ==============================================================================
# EQUITY CURVE & PORTFOLIO TRACKING
# ==============================================================================
def update_equity_curve(data_dict, b_inds, eq_inds, cr_inds, today_str):
    """Updates daily OHLC equity curve tracking based on real portfolio holdings & closed history."""
    pf = load_json_safe(PORTFOLIO_FILE, default={"open_positions": {}, "macro_positions": {}, "trade_history": []})

    # 1. Closed trades realized P&L sum (weighted by trade size)
    closed_pnl_usd = sum(
        (t.get("profit_pct", 0.0) / 100.0) * (INITIAL_CAPITAL * t.get("weight", EQUITY_POSITION_WEIGHT))
        for t in pf.get("trade_history", [])
    )

    # 2. Open positions floating P&L sum
    open_pnl_usd = 0.0
    for ticker, pos in pf.get("open_positions", {}).items():
        is_crypto = pos.get("is_crypto", False)
        inds = cr_inds if is_crypto else eq_inds
        sym = ticker + "-USD" if is_crypto else ticker
        entry_p = pos.get("entry_price", 0.0)
        if inds and sym in inds['c'].columns and entry_p > 0:
            cur_p = float(inds['c'][sym].iloc[-1])
            pnl_pct = (cur_p / entry_p - 1.0)
            weight = pos.get("weight", BTC_POSITION_WEIGHT if ticker == "BTC" else ALTCOIN_POSITION_WEIGHT if is_crypto else EQUITY_POSITION_WEIGHT)
            size = INITIAL_CAPITAL * weight
            open_pnl_usd += pnl_pct * size

    # 3. Macro hedges floating P&L sum
    alloc = data_dict.get("allocations", {})
    for asset, sym in [("Gold", "GC=F"), ("Bonds", "IEF")]:
        if alloc.get(asset, 0) > 0 and asset in pf.get("macro_positions", {}):
            pos = pf["macro_positions"][asset]
            entry_p = pos.get("entry_price", 0.0)
            if b_inds and sym in b_inds['c'].columns and entry_p > 0:
                cur_p = float(b_inds['c'][sym].iloc[-1])
                pnl_pct = (cur_p / entry_p - 1.0)
                alloc_cap = INITIAL_CAPITAL * (alloc.get(asset, 0) / 100.0)
                open_pnl_usd += pnl_pct * alloc_cap

    current_portfolio_value = round(INITIAL_CAPITAL + closed_pnl_usd + open_pnl_usd, 2)
    eq_data = load_json_safe(EQUITY_FILE, default={"history": []})
    history = eq_data.setdefault("history", [])

    if not history:
        history.append({
            "date": today_str,
            "open": INITIAL_CAPITAL,
            "high": INITIAL_CAPITAL,
            "low": INITIAL_CAPITAL,
            "close": current_portfolio_value,
            "value": current_portfolio_value
        })
    else:
        last_entry = history[-1]
        if last_entry["date"] == today_str:
            last_entry["close"] = current_portfolio_value
            last_entry["value"] = current_portfolio_value
            last_entry["high"] = max(last_entry.get("high", current_portfolio_value), current_portfolio_value)
            last_entry["low"] = min(last_entry.get("low", current_portfolio_value), current_portfolio_value)
        else:
            prev_close = last_entry["value"]
            history.append({
                "date": today_str,
                "open": prev_close,
                "high": max(prev_close, current_portfolio_value),
                "low": min(prev_close, current_portfolio_value),
                "close": current_portfolio_value,
                "value": current_portfolio_value
            })

    save_json_atomic(EQUITY_FILE, eq_data)
    print(f"[+] Equity Curve Reale aggiornata: {current_portfolio_value:,.2f}")


def update_portfolio(output, b_inds, eq_inds, cr_inds, today_str):
    """Executes trailing stops, weekly additions/liquidations, macro hedge tracking and monthly rotations."""
    pf = load_json_safe(PORTFOLIO_FILE, default={"open_positions": {}, "macro_positions": {}, "trade_history": []})

    is_friday, is_rotation = is_rebalancing_schedule()
    action_log = []

    # 1. Stop Losses & Trailing Stop Updates
    sold_keys = []
    for ticker, pos in pf["open_positions"].items():
        is_crypto = pos.get("is_crypto", False)
        inds = cr_inds if is_crypto else eq_inds
        sym = ticker + "-USD" if is_crypto else ticker

        if inds and sym in inds['c'].columns:
            low_price = float(inds['low'][sym].iloc[-1]) if 'low' in inds else float(inds['c'][sym].iloc[-1])
            close_price = float(inds['c'][sym].iloc[-1])
            pos["current_price"] = close_price

            if is_friday:
                try:
                    atr = float(inds['atr'][sym].iloc[-1])
                    hh = float(inds['hh60'][sym].iloc[-1]) if pd.notna(inds['hh60'][sym].iloc[-1]) else close_price
                    new_stop = hh - (atr * ATR_STOP_MULTIPLIER)
                    if new_stop > pos["stop_loss"]:
                        pos["stop_loss"] = new_stop
                except Exception:
                    pass

            if low_price < pos["stop_loss"]:
                open_price = float(inds['open'][sym].iloc[-1]) if 'open' in inds else close_price
                exit_price = open_price if open_price < pos["stop_loss"] else pos["stop_loss"]
                entry_p = pos.get("entry_price", 0.0)
                profit_pct = (exit_price / entry_p) - 1.0 if entry_p > 0 else 0.0

                pf["trade_history"].append({
                    "ticker": ticker,
                    "entry_date": pos.get("entry_date", today_str),
                    "exit_date": today_str,
                    "entry_price": entry_p,
                    "exit_price": exit_price,
                    "profit_pct": round(profit_pct * 100, 2),
                    "weight": pos.get("weight", EQUITY_POSITION_WEIGHT),
                    "reason": "Stop Loss"
                })
                p_fmt = fmt_usd(exit_price)
                action_log.append(f"🔴 STOP LOSS (VENDITA): {ticker} | Prezzo Uscita: {p_fmt} | P&L: {round(profit_pct*100, 2):+0.2f}%")
                sold_keys.append(ticker)

    for k in sold_keys:
        del pf["open_positions"][k]

    # 2. Track / Update Macro Positions (Gold & Bonds)
    alloc = output.get("allocations", {})
    for asset, sym in [("Gold", "GC=F"), ("Bonds", "IEF")]:
        if alloc.get(asset, 0) > 0:
            if asset not in pf["macro_positions"]:
                price = float(b_inds['c'][sym].iloc[-1]) if b_inds and sym in b_inds['c'].columns else 0.0
                pf["macro_positions"][asset] = {"entry_date": today_str, "entry_price": price, "current_price": price}
                action_log.append(f"🛡️ HEDGE ATTIVATO: {asset} a {price:.2f}")

    for asset, pos in pf["macro_positions"].items():
        sym = "GC=F" if asset == "Gold" else "IEF"
        if b_inds and sym in b_inds['c'].columns:
            pos["current_price"] = float(b_inds['c'][sym].iloc[-1])

    # 3. Monthly Rotation (Sells executed first on rotation Friday to free slots)
    if is_rotation:
        desired = {row["Ticker"]: True for row in output.get("top20", [])}
        desired.update({row["Ticker"]: True for row in output.get("crypto_top", [])})

        sold_rot = []
        for ticker, pos in list(pf["open_positions"].items()):
            if ticker not in desired:
                is_crypto = pos.get("is_crypto", False)
                inds = cr_inds if is_crypto else eq_inds
                sym = ticker + "-USD" if is_crypto else ticker
                entry_p = pos.get("entry_price", 0.0)
                close_price = float(inds['c'][sym].iloc[-1]) if inds and sym in inds['c'].columns else entry_p
                profit_pct = (close_price / entry_p) - 1.0 if entry_p > 0 else 0.0

                pf["trade_history"].append({
                    "ticker": ticker,
                    "entry_date": pos.get("entry_date", today_str),
                    "exit_date": today_str,
                    "entry_price": entry_p,
                    "exit_price": close_price,
                    "profit_pct": round(profit_pct * 100, 2),
                    "weight": pos.get("weight", EQUITY_POSITION_WEIGHT),
                    "reason": "Rotazione"
                })
                p_fmt = fmt_usd(close_price)
                action_log.append(f"🔄 ROTAZIONE (VENDITA): {ticker} | Prezzo Uscita: {p_fmt} | P&L: {round(profit_pct*100, 2):+0.2f}%")
                sold_rot.append(ticker)

        for k in sold_rot:
            del pf["open_positions"][k]

    # 4. Weekly Friday Actions (Forced Sells & New Buys)
    if is_friday:
        forced_sells = []
        for ticker, pos in list(pf["open_positions"].items()):
            is_crypto = pos.get("is_crypto", False)
            if is_crypto and alloc.get("Crypto", 0) == 0:
                forced_sells.append(ticker)
            elif not is_crypto and alloc.get("Equities", 0) == 0:
                forced_sells.append(ticker)

        for ticker in forced_sells:
            pos = pf["open_positions"][ticker]
            is_crypto = pos.get("is_crypto", False)
            inds = cr_inds if is_crypto else eq_inds
            sym = ticker + "-USD" if is_crypto else ticker
            entry_p = pos.get("entry_price", 0.0)
            close_price = float(inds['c'][sym].iloc[-1]) if inds and sym in inds['c'].columns else entry_p
            profit_pct = (close_price / entry_p) - 1.0 if entry_p > 0 else 0.0

            pf["trade_history"].append({
                "ticker": ticker,
                "entry_date": pos.get("entry_date", today_str),
                "exit_date": today_str,
                "entry_price": entry_p,
                "exit_price": close_price,
                "profit_pct": round(profit_pct * 100, 2),
                "weight": pos.get("weight", EQUITY_POSITION_WEIGHT),
                "reason": "Macro Bear"
            })
            p_fmt = fmt_usd(close_price)
            action_log.append(f"🔴 CAMBIO REGIME (VENDITA): {ticker} | Prezzo Uscita: {p_fmt} | P&L: {round(profit_pct*100, 2):+0.2f}%")
            del pf["open_positions"][ticker]

        # Buy equities to deploy cash
        if alloc.get("Equities", 0) > 0:
            current_eq = len([k for k, v in pf["open_positions"].items() if not v.get("is_crypto", False)])
            to_buy = MAX_EQUITY_POSITIONS - current_eq
            if to_buy > 0:
                for row in output.get("top20", []):
                    ticker = row["Ticker"]
                    if ticker not in pf["open_positions"]:
                        p_val = row["Prezzo ($)"]
                        sl_val = row["Stop Loss ($)"]
                        dist_sl = ((sl_val / p_val) - 1.0) * 100 if p_val > 0 else 0.0
                        pf["open_positions"][ticker] = {
                            "entry_date": today_str,
                            "entry_price": p_val,
                            "stop_loss": sl_val,
                            "is_crypto": False,
                            "weight": EQUITY_POSITION_WEIGHT
                        }
                        action_log.append(
                            f"🟢 ACQUISTO AZIONI: {ticker} (Quota: 5%) | Prezzo: ${p_val:,.2f} | Stop Loss: ${sl_val:,.2f} ({dist_sl:+.2f}%)"
                        )
                        to_buy -= 1
                        if to_buy == 0:
                            break

        # Buy crypto top 3 with strict position capping
        if alloc.get("Crypto", 0) > 0:
            current_cr = len([k for k, v in pf["open_positions"].items() if v.get("is_crypto", False)])
            to_buy_cr = MAX_CRYPTO_POSITIONS - current_cr
            if to_buy_cr > 0:
                for row in output.get("crypto_top", []):
                    ticker = row["Ticker"]
                    if ticker not in pf["open_positions"]:
                        p_val = row["Prezzo ($)"]
                        sl_val = row["Stop Loss ($)"]
                        dist_sl = ((sl_val / p_val) - 1.0) * 100 if p_val > 0 else 0.0
                        weight_pct = 10 if ticker == "BTC" else 5
                        weight_dec = BTC_POSITION_WEIGHT if ticker == "BTC" else ALTCOIN_POSITION_WEIGHT
                        p_fmt = fmt_usd(p_val)
                        sl_fmt = fmt_usd(sl_val)
                        pf["open_positions"][ticker] = {
                            "entry_date": today_str,
                            "entry_price": p_val,
                            "stop_loss": sl_val,
                            "is_crypto": True,
                            "weight": weight_dec
                        }
                        action_log.append(
                            f"🟢 ACQUISTO CRYPTO: {ticker} (Quota: {weight_pct}%) | Prezzo: {p_fmt} | Stop Loss: {sl_fmt} ({dist_sl:+.2f}%)"
                        )
                        to_buy_cr -= 1
                        if to_buy_cr == 0:
                            break

        # Close macro hedges if deactivated
        for asset in list(pf["macro_positions"].keys()):
            if alloc.get(asset, 0) == 0:
                pos = pf["macro_positions"][asset]
                sym = "GC=F" if asset == "Gold" else "IEF"
                entry_p = pos.get("entry_price", 0.0)
                exit_price = float(b_inds['c'][sym].iloc[-1]) if b_inds and sym in b_inds['c'].columns else entry_p
                profit_pct = (exit_price / entry_p) - 1.0 if entry_p > 0 else 0.0

                pf["trade_history"].append({
                    "ticker": f"{asset} (Hedge)",
                    "entry_date": pos.get("entry_date", today_str),
                    "exit_date": today_str,
                    "entry_price": entry_p,
                    "exit_price": exit_price,
                    "profit_pct": round(profit_pct * 100, 2),
                    "weight": MAX_GOLD_ALLOCATION / 100.0 if asset == "Gold" else 0.20,
                    "reason": "Hedge Chiuso"
                })
                p_fmt = fmt_usd(exit_price)
                action_log.append(f"🛑 HEDGE CHIUSO (VENDITA): {asset} | Prezzo: {p_fmt} | P&L: {round(profit_pct*100, 2):+0.2f}%")
                del pf["macro_positions"][asset]

    save_json_atomic(PORTFOLIO_FILE, pf)
    return action_log


# ==============================================================================
# TELEGRAM NOTIFICATIONS
# ==============================================================================
def send_telegram_alert(data_dict, action_log):
    """Sends concise formatted markdown alerts to the user's Telegram channel with % and stop losses in $ and %."""
    token = os.environ.get("TELEGRAM_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        print("[-] Credenziali Telegram non configurate. Skip invio notifica.")
        return

    try:
        msg = "🦅 *APEX ENGINE UPDATE* 🦅\n"
        msg += f"🕒 _{data_dict.get('timestamp', '')}_\n\n"

        macro_evs = data_dict.get('macro_events', [])
        if macro_evs:
            msg += "🚨 *ALLERTA MACRO REGIME* 🚨\n"
            for ev in macro_evs:
                msg += f"• {ev}\n"
            msg += "\n"

        if action_log:
            msg += "🚀 *ORDINI DA ESEGUIRE OGGI*\n"
            for log in action_log:
                if any(k in log for k in ("ACQUISTO", "VENDITA", "BEAR", "STOP LOSS", "HEDGE")):
                    msg += f"• {log}\n"
            msg += "\n"

        alloc = data_dict.get('allocations', {})
        eq_icon = "🟢" if alloc.get('Equities', 0) > 0 else "🔴"
        cr_icon = "🟢" if alloc.get('Crypto', 0) > 0 else "🔴"
        g_icon = "🟢" if alloc.get('Gold', 0) > 0 else "🔴"
        b_icon = "🟢" if alloc.get('Bonds', 0) > 0 else "🔴"

        msg += "🎛️ *COCKPIT MACRO*\n"
        msg += f"{eq_icon} Azionario: {alloc.get('Equities', 0)}%\n"
        msg += f"{cr_icon} Crypto: {alloc.get('Crypto', 0)}%\n"
        msg += f"{g_icon} Oro: {alloc.get('Gold', 0)}%\n"
        msg += f"{b_icon} Bond: {alloc.get('Bonds', 0)}%\n"
        msg += f"⚪ Cash: {alloc.get('Cash', 0)}%\n\n"

        pf = load_json_safe(PORTFOLIO_FILE, default={})
        open_pos = pf.get("open_positions", {})
        if open_pos:
            msg += "💼 *IL TUO PORTAFOGLIO (AGGIORNA STOP)*\n"
            for ticker, info in open_pos.items():
                cur_p = info.get("current_price", info.get("entry_price", 0.0))
                sl_p = info.get("stop_loss", 0.0)
                dist_sl = ((sl_p / cur_p) - 1.0) * 100 if cur_p > 0 else 0.0
                msg += f"• *{ticker}* | Prezzo: {fmt_usd(cur_p)} | Stop: `{fmt_usd(sl_p)}` ({dist_sl:+.2f}%)\n"
            msg += "\n"

        is_friday, is_rotation = is_rebalancing_schedule()
        if is_rotation:
            msg += "🔄 *ROTAZIONE MENSILE ATTIVA*\nAccedi alla Dashboard per completare la rotazione dei titoli.\n\n"

        msg += "💡 _Accedi ad Apex Engine per i dettagli operativi._"

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = urllib.parse.urlencode({"chat_id": chat_id, "text": msg, "parse_mode": "Markdown"}).encode('utf-8')
        req = urllib.request.Request(url, data=payload)
        urllib.request.urlopen(req, timeout=HTTP_TIMEOUT)
        print("[+] Notifica Telegram inviata con successo.")
    except Exception as e:
        print(f"[!] Errore invio alert Telegram: {e}")


# ==============================================================================
# MAIN EXECUTION PIPELINE
# ==============================================================================
def main():
    start_time = time.time()
    today_str = datetime.datetime.now().strftime("%Y-%m-%d")
    print("=== AVVIO APEX ENGINE (Genesis Core Pipeline) ===")

    output = {
        "macro": {},
        "allocations": {},
        "macro_dates": {},
        "macro_events": [],
        "top20": [],
        "crypto_top": [],
        "timestamp": datetime.datetime.now().strftime("%d %b %Y, %H:%M (UTC)")
    }

    # 1. Macro Analysis
    print("[1/4] Ingestione & Analisi Macro Benchmark...")
    b_data = fetch_bulk_parallel(BENCHMARK_TICKERS, max_workers=MAX_WORKERS_CRYPTO)
    b_inds = calc_indicators(b_data)
    macro, allocations = calculate_macro_allocation(b_data)
    output["macro"] = macro
    output["allocations"] = allocations

    old_data = load_json_safe(APEX_DATA_FILE, default=None)
    macro_dates, macro_events = update_macro_regimes(allocations, old_data, today_str)
    output["macro_dates"] = macro_dates
    output["macro_events"] = macro_events

    # Load current portfolio to detect held open positions needing daily stop monitoring
    pf = load_json_safe(PORTFOLIO_FILE, default={"open_positions": {}, "macro_positions": {}, "trade_history": []})
    held_eq = [k for k, v in pf.get("open_positions", {}).items() if not v.get("is_crypto", False)]
    held_cr = [f"{k}-USD" for k, v in pf.get("open_positions", {}).items() if v.get("is_crypto", False)]

    # 2. Equities Engine
    eq_inds = None
    if allocations["Equities"] > 0:
        print("[2/4] Elaborazione Universo Azionario S&P 500...")
        eq_ticks = list(set(get_sp500_tickers() + held_eq))
        eq_data = fetch_bulk_parallel(eq_ticks, max_workers=MAX_WORKERS_DEFAULT)
        eq_inds = calc_indicators(eq_data, roc_period=EQUITIES_ROC_PERIOD)
        output["top20"] = process_engine(eq_inds, atr_multiplier=ATR_STOP_MULTIPLIER, gap_limit=EQUITIES_GAP_LIMIT)[:MAX_EQUITY_POSITIONS]
    elif held_eq:
        print("[2/4] Motore Azionario OFF (Semaforo Rosso) - Aggiornamento posizioni aperte...")
        eq_data = fetch_bulk_parallel(held_eq, max_workers=MAX_WORKERS_DEFAULT)
        eq_inds = calc_indicators(eq_data, roc_period=EQUITIES_ROC_PERIOD)
    else:
        print("[2/4] Motore Azionario OFF (Semaforo Rosso).")

    # 3. Crypto Engine
    cr_inds = None
    if allocations["Crypto"] > 0:
        print("[3/4] Elaborazione Universo Crypto (Spot & Perp)...")
        c_ticks = list(set(get_tradable_crypto_universe() + held_cr))
        cr_data = fetch_bulk_parallel(c_ticks, max_workers=MAX_WORKERS_CRYPTO)
        cr_inds = calc_indicators(cr_data, roc_period=CRYPTO_ROC_PERIOD)
        output["crypto_top"] = process_engine(cr_inds, atr_multiplier=ATR_STOP_MULTIPLIER, gap_limit=CRYPTO_GAP_LIMIT, is_crypto=True)[:MAX_CRYPTO_POSITIONS]
    elif held_cr:
        print("[3/4] Motore Crypto OFF (Semaforo Rosso) - Aggiornamento posizioni aperte...")
        cr_data = fetch_bulk_parallel(held_cr, max_workers=MAX_WORKERS_CRYPTO)
        cr_inds = calc_indicators(cr_data, roc_period=CRYPTO_ROC_PERIOD)
    else:
        print("[3/4] Motore Crypto OFF (Semaforo Rosso).")

    # Save Output Atomically
    save_json_atomic(APEX_DATA_FILE, output)

    # 4. Portfolio State & Equity Curve Tracking
    print("[4/4] Aggiornamento Portafoglio, Storico ed Equity Curve...")
    action_log = update_portfolio(output, b_inds, eq_inds, cr_inds, today_str)
    update_equity_curve(output, b_inds, eq_inds, cr_inds, today_str)

    # Telegram Notification (Fridays, Regime Shifts, or Actionable Orders)
    is_friday, _ = is_rebalancing_schedule()
    has_orders = any(any(k in log for k in ("ACQUISTO", "VENDITA", "BEAR", "STOP LOSS", "HEDGE")) for log in action_log)
    if is_friday or output.get("macro_events") or has_orders:
        send_telegram_alert(output, action_log)
    else:
        print("[-] Nessun alert Telegram programmato oggi (attesa venerdì o cambio regime).")

    elapsed = time.time() - start_time
    print(f"=== ESECUZIONE COMPLETATA CON SUCCESSO IN {elapsed:.2f}s ===")


if __name__ == "__main__":
    main()
