"""
Apex Multi-Asset Quantitative Engine v2
Timing multi-asset (isteresi + vol-targeting) su SPY/IEF/GLD/BTC-USD + basket
azionario a bassa volatilita', tracking di portafoglio e notifiche Telegram.
Specifica completa: APEX_V2_SPEC.md.
"""

import datetime
import io
import json
import os
import random
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd

from apex_v2_engine import (
    compute_v2_macro_signal, select_low_vol_basket, is_quarter_end_month,
    V2_CLASS_TICKER, V2_EQUITY_TOP_N,
)

# ==============================================================================
# CONFIGURATION & CONSTANTS
# ==============================================================================
INITIAL_CAPITAL = 100_000.0

# Persistence File Names
APEX_DATA_FILE = 'apex_data.json'
PORTFOLIO_FILE = 'portfolio.json'
EQUITY_FILE = 'equity.json'

# Benchmarks (solo per display/FX — il segnale di timing usa V2_CLASS_TICKER)
DISPLAY_TICKERS = ['EURUSD=X']

USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
MAX_WORKERS_DEFAULT = 3
MAX_WORKERS_CRYPTO = 2
HTTP_TIMEOUT = 10


# ==============================================================================
# ATOMIC I/O & FORMATTING UTILITIES
# ==============================================================================
def save_json_atomic(filepath, data, indent=4):
    """Writes JSON data to a temporary file before atomic rename to prevent corruption."""
    temp_file = f"{filepath}.tmp"
    with open(temp_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=indent)
    os.replace(temp_file, filepath)


def load_json_safe(filepath, default=None):
    """Reads JSON data with error handling and fallback defaults."""
    if not os.path.exists(filepath):
        return default if default is not None else {}
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"[!] Errore lettura {filepath}: {e}")
        return default if default is not None else {}


def format_currency(val):
    """Formats numeric value to currency string without hardcoded symbols."""
    return f"{val:,.0f}"


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


def compute_should_decide(now_dt, prev_state, just_migrating):
    """Vero se e' il momento di ricalcolare la decisione mensile (segnale + eventuale
    ribilanciamento, §6 della spec). Finestra negli ultimi 5 giorni del mese + flag
    persistito (`last_decision_month`) invece del solo "e' venerdi' adesso": i workflow
    schedulati di GitHub Actions possono slittare di ore, a volte oltre mezzanotte UTC —
    un'esecuzione pensata per l'ultimo venerdi' del mese puo' partire di sabato, e con un
    controllo sul solo giorno corrente la decisione mensile verrebbe saltata per l'intero
    mese. Con la finestra, la prima esecuzione giornaliera negli ultimi 5 giorni del mese
    la cattura comunque, una sola volta (vedi APEX_V2_SPEC.md §8.13)."""
    current_month_str = now_dt.strftime("%Y-%m")
    near_month_end = (now_dt + datetime.timedelta(days=5)).month != now_dt.month
    return just_migrating or (near_month_end and prev_state.get("last_decision_month") != current_month_str)


def compute_weekly_due(today_str, last_alert_str):
    """Vero se sono passati almeno 6 giorni dall'ultimo alert Telegram inviato con
    successo. Sostituisce il controllo "e' venerdi' adesso" per l'heartbeat settimanale,
    per lo stesso motivo di `compute_should_decide` — vedi APEX_V2_SPEC.md §8.13."""
    if not last_alert_str:
        return True
    try:
        days_since = (datetime.datetime.strptime(today_str, "%Y-%m-%d") - datetime.datetime.strptime(last_alert_str, "%Y-%m-%d")).days
    except ValueError:
        return True
    return days_since >= 6


def compute_executing_pending(prev_pending, latest_market_date_str):
    """Vero se una decisione in attesa (§8.14 di APEX_V2_SPEC.md) va eseguita ORA: serve
    che l'ultima barra di mercato realmente disponibile (tipicamente la chiusura SPY, che
    segue il calendario borsistico USA) sia successiva al giorno in cui la decisione e'
    stata presa — non basta che sia passato un giorno di calendario, altrimenti
    un'esecuzione ritardata nel weekend (nessun nuovo giorno di borsa) eseguirebbe
    comunque alla stessa identica chiusura del venerdi' usata per decidere, con ritardo
    zero reale nonostante il ritardo di calendario. Cosi' un'esecuzione di sabato/domenica
    resta in attesa fino al primo vero giorno di borsa successivo (lunedi')."""
    if not prev_pending:
        return False
    decided_date = prev_pending.get("decided_date", "")
    return bool(latest_market_date_str) and latest_market_date_str > decided_date


# ==============================================================================
# DATA INGESTION & UNIVERSE DISCOVERY
# ==============================================================================
def get_sp500_tickers():
    """Fetches constituent tickers of S&P 500 from Wikipedia with clean formatting."""
    try:
        url = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
        req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
        html = urllib.request.urlopen(req, timeout=HTTP_TIMEOUT).read().decode('utf-8')
        df = pd.read_html(io.StringIO(html))[0]
        return [t.replace('.', '-') for t in df['Symbol'].tolist()]
    except Exception as e:
        print(f"[!] Errore recupero lista S&P 500 ({e}). Uso fallback minimizzato.")
        return ['AAPL', 'NVDA', 'MSFT', 'AMZN', 'GOOGL', 'META', 'TSLA', 'AVGO', 'COST', 'AMD']


def fetch_yahoo_history(ticker, period='2y', interval='1d'):
    """Retrieves OHLC price series from Yahoo Finance Chart API."""
    try:
        url = f"https://query2.finance.yahoo.com/v8/finance/chart/{ticker}?range={period}&interval={interval}"
        req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
        res = json.loads(urllib.request.urlopen(req, timeout=HTTP_TIMEOUT).read().decode())
        result = res['chart']['result'][0]
        timestamps = pd.to_datetime(result['timestamp'], unit='s')
        quote = result['indicators']['quote'][0]

        df = pd.DataFrame({
            'Open': quote['open'],
            'High': quote['high'],
            'Low': quote['low'],
            'Close': quote['close']
        }, index=timestamps).ffill().dropna()
        return ticker, df
    except Exception:
        return ticker, pd.DataFrame()


def download_universe_batch(tickers, max_workers=MAX_WORKERS_DEFAULT, desc="Asset"):
    """Downloads historical data concurrently using ThreadPoolExecutor."""
    results = {}
    print(f"[*] Inizio download {desc} ({len(tickers)} strumenti)...")
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(fetch_yahoo_history, sym): sym for sym in tickers}
        for future in as_completed(futures):
            sym, df = future.result()
            if not df.empty and len(df) >= 30:
                results[sym] = df
            time.sleep(random.uniform(0.05, 0.15))
    print(f"[+] Download {desc} completato: {len(results)}/{len(tickers)} validi.")
    return results


fetch_bulk_parallel = download_universe_batch


def fetch_sector(ticker):
    """Recupera il settore GICS (endpoint Yahoo quoteSummary/assetProfile), stesso stile
    di fetch_yahoo_history — nessuna dipendenza da yfinance."""
    try:
        url = f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{ticker}?modules=assetProfile"
        req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
        res = json.loads(urllib.request.urlopen(req, timeout=HTTP_TIMEOUT).read().decode())
        profile = res['quoteSummary']['result'][0]['assetProfile']
        return ticker, profile.get('sector')
    except Exception:
        return ticker, None


def fetch_sector_map(tickers, max_workers=MAX_WORKERS_DEFAULT):
    """Recupera il settore per una lista di ticker, in parallelo. Fail-open per singolo
    titolo: select_low_vol_basket tratta un settore mancante come non vincolato, non
    come motivo per bloccare la selezione (vedi APEX_V2_SPEC.md §8.7)."""
    sector_of = {}
    print(f"[*] Recupero settori ({len(tickers)} titoli)...")
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(fetch_sector, sym): sym for sym in tickers}
        for future in as_completed(futures):
            sym, sector = future.result()
            if sector:
                sector_of[sym] = sector
            time.sleep(random.uniform(0.05, 0.15))
    print(f"[+] Settori recuperati: {len(sector_of)}/{len(tickers)}")
    return sector_of


# ==============================================================================
# PREZZI CORRENTI (v2 non ha bisogno degli indicatori pesanti di v1 — nessuno
# stop-loss per posizione, nessuna selezione per momentum: vedi APEX_V2_SPEC.md)
# ==============================================================================
def latest_prices(data_dict):
    """Restituisce l'ultimo prezzo di chiusura giornaliero per ciascun simbolo scaricato."""
    return {sym: float(df['Close'].iloc[-1]) for sym, df in data_dict.items() if not df.empty}


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
def mark_to_market_and_compound_nav(pf, prices_by_ticker):
    """
    Fa crescere pf["nav_usd"] in modo COMPOSTO: nav_oggi = nav_ieri * (1 + rendimento
    pesato del giorno sulle posizioni gia' aperte). Va chiamata PRIMA che
    update_portfolio chiuda/riapra posizioni (usa il "current_price" di ieri come base
    del rendimento), cosi' la rotazione stessa non altera il NAV (a parte i costi).

    Sostituisce un bug: la vecchia update_equity_curve ricalcolava il NAV da zero ogni
    notte come "capitale iniziale + somma di tutto il P&L storico usando il capitale
    INIZIALE (non quello composto) come base dei pesi" — ignorava completamente la
    crescita composta, e il giorno della migrazione v1->v2 (che ha aggiunto ~24 righe
    di chiusura insieme) ha fatto crollare il NAV mostrato da $243.770 a $160.436, un
    salto fittizio, non una perdita di mercato reale.
    """
    nav_usd = pf.get("nav_usd")
    if nav_usd is None:
        eq = load_json_safe(EQUITY_FILE, default={"history": []})
        hist = eq.get("history", [])
        nav_usd = hist[-1]["value"] if hist else INITIAL_CAPITAL

    daily_return = 0.0
    price_ratios = {}
    for ticker, pos in pf.get("open_positions", {}).items():
        sym = ticker + "-USD" if pos.get("is_crypto") else ticker
        old_price = pos.get("current_price", pos.get("entry_price", 0.0))
        new_price = prices_by_ticker.get(sym)
        if new_price is not None and old_price and old_price > 0:
            ratio = new_price / old_price
            price_ratios[ticker] = ratio
            daily_return += pos.get("weight", 0.0) * (ratio - 1.0)
            pos["current_price"] = new_price

    # "weight" era congelato al target dell'ultimo ribilanciamento — mai aggiornato per
    # riflettere la deriva di prezzo tra un ribilanciamento e l'altro. Un titolo che
    # corre non pesava mai di piu' agli occhi del sistema, e viceversa: la crescita
    # composta di ogni singola posizione (non solo del NAV totale) veniva sottostimata,
    # e "Peso (%)" in dashboard mostrava il vecchio target, non il peso vero attuale.
    # Ora si aggiorna insieme al NAV, con la stessa formula: nuovo peso = vecchio peso *
    # rendimento della posizione / rendimento del portafoglio.
    if (1.0 + daily_return) > 1e-9:
        for ticker, pos in pf.get("open_positions", {}).items():
            if ticker in price_ratios:
                pos["weight"] = pos.get("weight", 0.0) * price_ratios[ticker] / (1.0 + daily_return)

    nav_usd *= (1.0 + daily_return)
    pf["nav_usd"] = nav_usd
    return nav_usd


def update_equity_curve(nav_usd, today_str):
    """Registra pf["nav_usd"] (gia' composto da mark_to_market_and_compound_nav) nella
    curva OHLC giornaliera. Non ricalcola piu' il NAV da trade_history — vedi sopra."""
    current_portfolio_value = round(nav_usd, 2)
    eq_data = load_json_safe(EQUITY_FILE, default={"history": []})
    history = eq_data.setdefault("history", [])

    # "live": True marca le righe scritte da QUESTA funzione, cioe' dalle
    # esecuzioni notturne reali in produzione — generate_v2_track_record.py
    # (replay storico offline) scrive le sue voci direttamente, mai tramite
    # questa funzione, quindi non porta mai questo campo. app.py lo usa per
    # distinguere onestamente "simulazione storica" da "forward-tracking dal
    # vivo" nell'etichetta del grafico invece di chiamare tutto "backtest"
    # a tempo indeterminato.
    if not history:
        history.append({
            "date": today_str,
            "open": INITIAL_CAPITAL,
            "high": INITIAL_CAPITAL,
            "low": INITIAL_CAPITAL,
            "close": current_portfolio_value,
            "value": current_portfolio_value,
            "live": True
        })
    else:
        last_entry = history[-1]
        if last_entry["date"] == today_str:
            last_entry["close"] = current_portfolio_value
            last_entry["value"] = current_portfolio_value
            last_entry["high"] = max(last_entry.get("high", current_portfolio_value), current_portfolio_value)
            last_entry["low"] = min(last_entry.get("low", current_portfolio_value), current_portfolio_value)
            last_entry["live"] = True
        else:
            prev_close = last_entry["value"]
            history.append({
                "date": today_str,
                "open": prev_close,
                "high": max(prev_close, current_portfolio_value),
                "low": min(prev_close, current_portfolio_value),
                "close": current_portfolio_value,
                "value": current_portfolio_value,
                "live": True
            })

    save_json_atomic(EQUITY_FILE, eq_data)
    print(f"[+] Equity Curve Reale aggiornata: {current_portfolio_value:,.2f}")


def _close_position(pf, ticker, pos, exit_price, exit_date, reason, action_log, verb="CHIUSURA"):
    entry_p = pos.get("entry_price", 0.0)
    profit_pct = (exit_price / entry_p - 1.0) if entry_p > 0 else 0.0
    pf.setdefault("trade_history", []).append({
        "ticker": ticker,
        "entry_date": pos.get("entry_date", exit_date),
        "exit_date": exit_date,
        "entry_price": entry_p,
        "exit_price": exit_price,
        "profit_pct": round(profit_pct * 100, 2),
        "weight": pos.get("weight", 0.0),
        "reason": reason,
    })
    action_log.append(f"🔴 {verb}: {ticker} | Prezzo Uscita: {fmt_usd(exit_price)} | Rendimento: {round(profit_pct * 100, 2):+0.2f}%")


def update_portfolio(allocations, basket, prices_by_ticker, today_str):
    """
    Ribilancia il portafoglio verso i pesi target Apex v2 (vedi APEX_V2_SPEC.md §2-4).
    Ogni posizione la cui composizione (basket trimestrale) o il cui peso (vol-target
    mensile) cambia viene chiusa e riaperta: e' il modello di turnover gia' validato
    nel backtest (~109 eventi tassabili/anno), non un incidente di implementazione.

    Nessuno stop-loss per singola posizione (cambiamento deliberato rispetto a v1 —
    vedi APEX_V2_SPEC.md §4): l'uscita avviene solo per rotazione del basket o
    disattivazione della classe di attivo.
    """
    pf = load_json_safe(PORTFOLIO_FILE, default={"open_positions": {}, "trade_history": []})
    action_log = []

    # Migrazione one-time da v1: liquida tutto cio' che il vecchio motore aveva aperto,
    # una volta sola (vedi APEX_V2_SPEC.md §9 — decisione esplicita dell'utente).
    if not pf.get("v2_migrated", False):
        for ticker, pos in list(pf.get("open_positions", {}).items()):
            sym = ticker + "-USD" if pos.get("is_crypto") else ticker
            exit_price = prices_by_ticker.get(sym, pos.get("entry_price", 0.0))
            _close_position(pf, ticker, pos, exit_price, today_str, "🔁 Migrazione a v2", action_log, verb="MIGRAZIONE V2 (VENDITA)")
        for asset, pos in list(pf.get("macro_positions", {}).items()):
            # Chiusura di migrazione: l'entry_price di v1 per "Gold" era in convenzione
            # GC=F (futures, $/oncia), non GLD (ETF, scala di prezzo completamente diversa
            # ~1/10) — usare prices_by_ticker["GLD"] qui produrrebbe un profit_pct falsato
            # da mismatch di unita' di misura, non un rendimento reale. Si usa invece
            # l'ultimo current_price gia' tracciato da v1 nella stessa convenzione dell'entry.
            exit_price = pos.get("current_price", pos.get("entry_price", 0.0))
            _close_position(pf, f"{asset} (Hedge)", pos, exit_price, today_str, "🔁 Migrazione a v2", action_log, verb="MIGRAZIONE V2 (CHIUSURA HEDGE)")
        pf["open_positions"] = {}
        pf["macro_positions"] = {}
        pf["v2_migrated"] = True

    current = pf.get("open_positions", {})

    # Pesi target: basket azionario equal-weight dentro lo slot Equities, poi IEF/GLD/BTC
    target = {}
    n_basket = max(1, len(basket))
    eq_slot = allocations.get("Equities", 0.0) / 100.0
    for row in basket:
        target[row["Ticker"]] = eq_slot / n_basket
    if allocations.get("Bonds", 0.0) > 0:
        target["IEF"] = allocations["Bonds"] / 100.0
    if allocations.get("Gold", 0.0) > 0:
        target["GLD"] = allocations["Gold"] / 100.0
    if allocations.get("Crypto", 0.0) > 0:
        target["BTC"] = allocations["Crypto"] / 100.0

    EPS = 1e-4  # tolleranza sotto la quale non vale la pena ribilanciare (rumore di calcolo)
    # Stessa convenzione di costo usata in tutti i backtest (APEX_V2_SPEC.md §8.2 test 2):
    # 8bps per le classi-ETF (IEF/GLD/BTC), 10bps per i singoli titoli del basket.
    turnover_cost_frac = 0.0

    def cost_bps(tkr):
        return 8.0 if tkr in ("IEF", "GLD", "BTC") else 10.0

    def record_trade(ticker, entry_price, exit_price, entry_date, traded_weight, reason):
        profit_pct = (exit_price / entry_price - 1.0) if entry_price > 0 else 0.0
        pf.setdefault("trade_history", []).append({
            "ticker": ticker, "entry_date": entry_date, "exit_date": today_str,
            "entry_price": entry_price, "exit_price": exit_price,
            "profit_pct": round(profit_pct * 100, 2), "weight": round(traded_weight, 6),
            "reason": reason,
        })
        action_log.append(f"🔴 CHIUSURA: {ticker} | Prezzo Uscita: {fmt_usd(exit_price)} | Rendimento: {round(profit_pct * 100, 2):+0.2f}%")
        return profit_pct

    # Ribilancia le posizioni gia' detenute: NIENTE PIU' chiusura+riapertura totale ad ogni
    # cambio di peso (bug corretto — vedi APEX_V2_SPEC.md §8.8). Si negozia solo il delta:
    # un aumento di peso compra solo la quota aggiunta e aggiorna il costo medio ponderato
    # (PMC) delle azioni gia' detenute; una riduzione vende solo la quota in eccesso e
    # REALIZZA plusvalenza solo su quella, lasciando il resto con costo/data d'ingresso
    # originali. Costo di transazione applicato solo sul delta effettivamente negoziato,
    # non piu' sull'intera posizione ad ogni ribilanciamento mensile.
    for ticker, pos in list(current.items()):
        tgt_w = target.get(ticker)
        sym = ticker + "-USD" if pos.get("is_crypto") else ticker
        price = prices_by_ticker.get(sym, pos.get("current_price", pos.get("entry_price", 0.0)))
        cur_w = pos.get("weight", 0.0)
        entry_price = pos.get("entry_price", price)

        if tgt_w is None:
            record_trade(ticker, entry_price, price, pos.get("entry_date", today_str), cur_w, "🔄 Uscito da basket/classe disattivata")
            turnover_cost_frac += cur_w * (cost_bps(ticker) / 10000.0)
            del current[ticker]
            continue

        delta_w = tgt_w - cur_w
        if abs(delta_w) <= EPS:
            pos["current_price"] = price
            continue

        if delta_w > 0:
            # Incremento: costa solo la quota aggiunta; costo medio ponderato (PMC) sulle
            # azioni combinate — matematicamente equivalente al calcolo per azioni reali
            # (vedi test_backend.py), qui espresso in termini di peso/NAV.
            old_shares_equiv = (cur_w / entry_price) if entry_price > 0 else 0.0
            new_shares_equiv = (delta_w / price) if price > 0 else 0.0
            total_shares_equiv = old_shares_equiv + new_shares_equiv
            if total_shares_equiv > 0:
                pos["entry_price"] = (cur_w + delta_w) / total_shares_equiv
            pos["weight"] = tgt_w
            pos["current_price"] = price
            action_log.append(f"🟢 INCREMENTO: {ticker} ({cur_w*100:.2f}% → {tgt_w*100:.2f}%) | Prezzo: {fmt_usd(price)}")
            turnover_cost_frac += delta_w * (cost_bps(ticker) / 10000.0)
        else:
            trimmed_w = -delta_w
            record_trade(ticker, entry_price, price, pos.get("entry_date", today_str), trimmed_w, "⚖️ Ribilanciamento mensile (trim parziale)")
            pos["weight"] = tgt_w
            pos["current_price"] = price
            turnover_cost_frac += trimmed_w * (cost_bps(ticker) / 10000.0)

    # Apri le posizioni completamente nuove (non ancora in portafoglio)
    for ticker, tgt_w in target.items():
        if ticker in current or tgt_w <= EPS:
            continue
        is_crypto = (ticker == "BTC")
        sym = ticker + "-USD" if is_crypto else ticker
        price = prices_by_ticker.get(sym)
        if price is None or price <= 0:
            action_log.append(f"⚠️ Impossibile aprire {ticker}: prezzo non disponibile")
            continue
        current[ticker] = {
            "entry_date": today_str,
            "entry_price": price,
            "current_price": price,
            "stop_loss": 0.0,  # v2 non usa stop per posizione — vedi APEX_V2_SPEC.md §4
            "is_crypto": is_crypto,
            "weight": tgt_w,
        }
        action_log.append(f"🟢 APERTURA: {ticker} (peso {tgt_w * 100:.2f}%) | Prezzo: {fmt_usd(price)}")
        turnover_cost_frac += tgt_w * (cost_bps(ticker) / 10000.0)

    # Aggiorna il prezzo corrente delle posizioni rimaste invariate
    for ticker, pos in current.items():
        sym = ticker + "-USD" if pos.get("is_crypto") else ticker
        if sym in prices_by_ticker:
            pos["current_price"] = prices_by_ticker[sym]

    pf["open_positions"] = current
    pf["macro_positions"] = {}  # v2: oro/bond vivono in open_positions come le altre posizioni
    if turnover_cost_frac > 0:
        pf["nav_usd"] = pf.get("nav_usd", INITIAL_CAPITAL) * (1.0 - turnover_cost_frac)
    save_json_atomic(PORTFOLIO_FILE, pf)
    return action_log


PROXIES = {
    "GLD": {"name": "Oro", "ucits": "8PSE", "full": "Oro (8PSE / GLD)"},
    "IEF": {"name": "Obbligazioni", "ucits": "LMTH", "full": "Obbligazioni (LMTH / IEF)"},
    "BTC": {"name": "Bitcoin", "ucits": "IB1T", "full": "Bitcoin (IB1T / BTC)"},
    "Cash": {"name": "Monetario", "ucits": "XEON", "full": "Monetario (XEON)"},
}


def get_display_ticker(ticker):
    """Restituisce il nome dello strumento comprensivo di proxy UCITS per gli asset macro."""
    if ticker in PROXIES:
        return PROXIES[ticker]["full"]
    return ticker


def compute_rebalance_orders_structured(open_positions, target_allocations, basket, prices_by_ticker):
    """
    Calcola gli ordini di ribilanciamento in formato strutturato (percentuali, quote,
    prezzi, suddivisione Vendite/Acquisti) sin dal venerdì sera della decisione,
    permettendo all'utente di inserire gli ordini con calma per il lunedì.
    """
    target = {}
    n_basket = max(1, len(basket))
    eq_slot = target_allocations.get("Equities", 0.0) / 100.0
    for row in basket:
        target[row["Ticker"]] = eq_slot / n_basket
    if target_allocations.get("Bonds", 0.0) > 0:
        target["IEF"] = target_allocations["Bonds"] / 100.0
    if target_allocations.get("Gold", 0.0) > 0:
        target["GLD"] = target_allocations["Gold"] / 100.0
    if target_allocations.get("Crypto", 0.0) > 0:
        target["BTC"] = target_allocations["Crypto"] / 100.0

    EPS = 1e-4
    sells = []
    buys = []
    action_log = []

    all_tickers = sorted(list(set(list(open_positions.keys()) + list(target.keys()))))
    for ticker in all_tickers:
        cur_w = open_positions.get(ticker, {}).get("weight", 0.0)
        tgt_w = target.get(ticker, 0.0)
        delta_w = tgt_w - cur_w
        if abs(delta_w) <= EPS:
            continue

        is_crypto = (ticker == "BTC") or open_positions.get(ticker, {}).get("is_crypto", False)
        sym = ticker + "-USD" if is_crypto else ticker
        price = prices_by_ticker.get(sym, open_positions.get(ticker, {}).get("current_price", open_positions.get(ticker, {}).get("entry_price", 0.0)))
        
        cur_w_pct = cur_w * 100.0
        tgt_w_pct = tgt_w * 100.0
        delta_w_pct = delta_w * 100.0
        display_name = get_display_ticker(ticker)

        if tgt_w <= EPS and cur_w > EPS:
            entry_p = open_positions.get(ticker, {}).get("entry_price", price)
            pnl_pct = ((price / entry_p) - 1.0) * 100 if entry_p > 0 else 0.0
            order_info = {
                "action": "CHIUSURA",
                "action_type": "SELL",
                "ticker": ticker,
                "display_name": display_name,
                "cur_w_pct": round(cur_w_pct, 2),
                "tgt_w_pct": 0.0,
                "delta_w_pct": round(delta_w_pct, 2),
                "price": price,
                "pnl_pct": round(pnl_pct, 2),
                "is_crypto": is_crypto,
                "desc": f"Liquidazione 100% della posizione ({cur_w_pct:.2f}% del portafoglio)"
            }
            sells.append(order_info)
            action_log.append(f"CHIUSURA: {display_name} | Vende {cur_w_pct:.2f}% pf (100% posizione) | Prezzo rif: {fmt_usd(price)} | P&L: {pnl_pct:+0.2f}%")
        elif delta_w < -EPS:
            order_info = {
                "action": "TRIM",
                "action_type": "SELL",
                "ticker": ticker,
                "display_name": display_name,
                "cur_w_pct": round(cur_w_pct, 2),
                "tgt_w_pct": round(tgt_w_pct, 2),
                "delta_w_pct": round(delta_w_pct, 2),
                "price": price,
                "is_crypto": is_crypto,
                "desc": f"Riduzione a {tgt_w_pct:.2f}% pf (-{abs(delta_w_pct):.2f}% pf)"
            }
            sells.append(order_info)
            action_log.append(f"TRIM: {display_name} | Riduce di {abs(delta_w_pct):.2f}% pf (da {cur_w_pct:.2f}% → {tgt_w_pct:.2f}%) | Prezzo rif: {fmt_usd(price)}")
        elif cur_w <= EPS and tgt_w > EPS:
            order_info = {
                "action": "APERTURA",
                "action_type": "BUY",
                "ticker": ticker,
                "display_name": display_name,
                "cur_w_pct": 0.0,
                "tgt_w_pct": round(tgt_w_pct, 2),
                "delta_w_pct": round(delta_w_pct, 2),
                "price": price,
                "is_crypto": is_crypto,
                "desc": f"Nuovo acquisto quota {tgt_w_pct:.2f}% del portafoglio"
            }
            buys.append(order_info)
            action_log.append(f"APERTURA: {display_name} | Acquista {tgt_w_pct:.2f}% pf | Prezzo rif: {fmt_usd(price)}")
        elif delta_w > EPS:
            order_info = {
                "action": "INCREMENTO",
                "action_type": "BUY",
                "ticker": ticker,
                "display_name": display_name,
                "cur_w_pct": round(cur_w_pct, 2),
                "tgt_w_pct": round(tgt_w_pct, 2),
                "delta_w_pct": round(delta_w_pct, 2),
                "price": price,
                "is_crypto": is_crypto,
                "desc": f"Aumento a {tgt_w_pct:.2f}% pf (+{delta_w_pct:.2f}% pf)"
            }
            buys.append(order_info)
            action_log.append(f"INCREMENTO: {display_name} | Aumenta di +{delta_w_pct:.2f}% pf (da {cur_w_pct:.2f}% → {tgt_w_pct:.2f}%) | Prezzo rif: {fmt_usd(price)}")

    return {"sells": sells, "buys": buys, "orders": sells + buys, "action_log": action_log}


# ==============================================================================
# TELEGRAM NOTIFICATIONS
# ==============================================================================
def send_telegram_alert(data_dict, action_log, is_rotation_now=None, pending_orders_struct=None):
    """Notifica Telegram istituzionale e lean: ordini suddivisi rigorosamente in
    1. VENDITE (fai prima cassa) e 2. ACQUISTI (impiega liquidità), con percentuali
    di portafoglio esatte e timing esplicito per l'apertura di Lunedì."""
    token = os.environ.get("TELEGRAM_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        print("[-] Credenziali Telegram non configurate. Skip invio notifica.")
        return False

    try:
        alloc = data_dict.get('allocations', {})
        macro_evs = data_dict.get('macro_events', [])
        date_str = data_dict.get('timestamp', '').split(',')[0].strip()
        if is_rotation_now is None:
            _, is_rotation_now = is_rebalancing_schedule()

        def _dot(pct):
            return "[●]" if pct > 0 else "[○]"

        signals_line = (
            f"*REGIMI DI MERCATO*\n"
            f"• Azioni: {_dot(alloc.get('Equities', 0))} {alloc.get('Equities', 0):.0f}%\n"
            f"• Bitcoin: {_dot(alloc.get('Crypto', 0))} {alloc.get('Crypto', 0):.0f}%\n"
            f"• Oro: {_dot(alloc.get('Gold', 0))} {alloc.get('Gold', 0):.0f}%\n"
            f"• Obbligazioni: {_dot(alloc.get('Bonds', 0))} {alloc.get('Bonds', 0):.0f}%\n"
            f"• Monetario: [—] {alloc.get('Cash', 0):.0f}%"
        )

        pf = load_json_safe(PORTFOLIO_FILE, default={})
        open_pos = pf.get("open_positions", {})
        
        # Recupera ordini strutturati se disponibili
        struct = pending_orders_struct
        if not struct and pf.get("pending_orders"):
            sells = [o for o in pf.get("pending_orders", []) if o.get("action_type") == "SELL"]
            buys = [o for o in pf.get("pending_orders", []) if o.get("action_type") == "BUY"]
            if sells or buys:
                struct = {"sells": sells, "buys": buys}

        if action_log or macro_evs or struct:
            msg = f"*APEX QUANTITATIVE ENGINE* · {date_str}\n\n"

            if macro_evs:
                msg += "*CAMBIO DI REGIME MACRO*\n"
                for ev in macro_evs:
                    clean_ev = ev.replace("⚠️ MACRO REGIME: ", "").replace("⚠️ ", "").replace("🟢 ", "").replace("🔴 ", "")
                    msg += f"• {clean_ev}\n"
                msg += "\n"

            if struct and (struct.get("sells") or struct.get("buys")):
                msg += "*ORDINI OPERATIVI PER LUNEDÌ*\n"
                msg += "Esecuzione: Apertura mercati USA (15:30 CET)\n\n"
                if struct.get("sells"):
                    msg += "*1. VENDITE (Fai prima cassa)*\n"
                    for o in struct["sells"]:
                        act = o.get("action", "VENDITA")
                        disp = o.get("display_name") or get_display_ticker(o.get("ticker", ""))
                        desc = o.get("desc", "")
                        px = fmt_usd(o.get("price"))
                        msg += f"• {act}: `{disp}` | {desc} | Prezzo rif: {px}\n"
                    msg += "\n"
                if struct.get("buys"):
                    msg += "*2. ACQUISTI (Impiega liquidità)*\n"
                    for o in struct["buys"]:
                        act = o.get("action", "ACQUISTO")
                        disp = o.get("display_name") or get_display_ticker(o.get("ticker", ""))
                        desc = o.get("desc", "")
                        px = fmt_usd(o.get("price"))
                        msg += f"• {act}: `{disp}` | {desc} | Prezzo rif: {px}\n"
                    msg += "\n"
            elif action_log:
                msg += "*ORDINI DA ESEGUIRE*\n"
                for log in action_log:
                    clean = log
                    for e in ("🟢 ", "🔴 ", "🔁 ", "⚖️ ", "🔄 "):
                        clean = clean.replace(e, "")
                    msg += f"• {clean}\n"
                msg += "\n"

            msg += f"{signals_line}\n\nQuote, controvalori e dettagli operativi su Dashboard."
        else:
            if open_pos:
                weighted_pnl = sum(
                    p.get("weight", 0.0) * (((p.get("current_price", p.get("entry_price", 0.0)) / p["entry_price"]) - 1.0) * 100)
                    for p in open_pos.values() if p.get("entry_price", 0) > 0
                )
                status_line = f"Portafoglio invariato ({weighted_pnl:+.2f}% su {len(open_pos)} posizioni attive).\nNessuna operazione richiesta sul broker per Lunedì."
            else:
                status_line = "Nessuna posizione aperta al momento.\nNessuna operazione richiesta per Lunedì."

            msg = f"*APEX QUANTITATIVE ENGINE* · {date_str}\n\n{status_line}\n\n{signals_line}"

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = urllib.parse.urlencode({"chat_id": chat_id, "text": msg, "parse_mode": "Markdown"}).encode('utf-8')
        req = urllib.request.Request(url, data=payload)
        urllib.request.urlopen(req, timeout=HTTP_TIMEOUT)
        print("[+] Notifica Telegram inviata con successo.")
        return True
    except Exception as e:
        print(f"[!] Errore invio alert Telegram: {e}")
        return False


# ==============================================================================
# MAIN EXECUTION PIPELINE
# ==============================================================================
def main():
    start_time = time.time()
    now_dt = datetime.datetime.now()
    today_str = now_dt.strftime("%Y-%m-%d")
    print("=== AVVIO APEX ENGINE v2 (Timing Multi-Asset + Basket Azionario Low-Vol) ===")
    print("    Vedi APEX_V2_SPEC.md per la specifica completa.")

    pf_check = load_json_safe(PORTFOLIO_FILE, default={"open_positions": {}, "trade_history": []})
    just_migrating = not pf_check.get("v2_migrated", False)

    old_data = load_json_safe(APEX_DATA_FILE, default=None)
    prev_state = (old_data or {}).get("v2_state", {}) or {}
    prev_hysteresis = prev_state.get("hysteresis", {})
    prev_basket = prev_state.get("basket", [])
    prev_pending = prev_state.get("pending_decision")

    current_month_str = now_dt.strftime("%Y-%m")
    should_decide = compute_should_decide(now_dt, prev_state, just_migrating)
    # Decisione ed esecuzione NON avvengono piu' nella stessa esecuzione (vedi
    # APEX_V2_SPEC.md §8.14): la decisione si calcola oggi sull'ultima chiusura
    # settimanale disponibile, ma resta "in attesa" (`pending_decision`) finche' non
    # e' disponibile una barra di mercato realmente successiva al giorno della
    # decisione — per una decisione presa di venerdi', e' la chiusura di lunedi'
    # (primo vero giorno di borsa successivo). Corregge un disallineamento reale con
    # i backtest validati (che usano esattamente questo ritardo, mai zero) e rende i
    # prezzi comunicati all'utente realistici (non piu' l'ultima chiusura del
    # venerdi', irraggiungibile nel weekend). Nessun trattamento speciale per BTC
    # (negoziabile nel weekend): testato esplicitamente e la parita' con le altre
    # classi (esecuzione al lunedi' per tutti) e' risultata la scelta migliore.
    deciding_new = should_decide and not prev_pending

    output = {
        "macro": {},
        "allocations": (old_data or {}).get("allocations") or {"Equities": 0, "Bonds": 0, "Gold": 0, "Crypto": 0, "Cash": 100},
        "macro_dates": (old_data or {}).get("macro_dates", {}),
        "macro_events": [],
        "top20": prev_basket,
        "crypto_top": (old_data or {}).get("crypto_top", []),
        "v2_state": dict(prev_state) if prev_state else {"hysteresis": {}, "basket": [], "basket_quarter": None, "last_decision_month": None, "pending_decision": None},
        "timestamp": datetime.datetime.now().strftime("%d %b %Y, %H:%M (UTC)"),
    }

    # 1. Segnale macro (SPY/IEF/GLD/BTC-USD): scaricato sempre per il monitoraggio prezzi
    # e per sapere se la barra di mercato e' avanzata abbastanza da eseguire una
    # decisione in attesa; la decisione stessa (isteresi + vol-target) e' ricalcolata
    # solo quando deciding_new.
    print("[1/4] Ingestione Segnale Macro (SPY/IEF/GLD/BTC-USD)...")
    signal_tickers = list(dict.fromkeys(list(V2_CLASS_TICKER.values()) + DISPLAY_TICKERS))
    b_data = fetch_bulk_parallel(signal_tickers, max_workers=MAX_WORKERS_CRYPTO)

    output['eur_usd'] = round(float(b_data['EURUSD=X']['Close'].iloc[-1]), 4) if b_data.get('EURUSD=X') is not None and not b_data['EURUSD=X'].empty else 1.0850
    output["macro"] = {t: {"price": float(b_data[t]['Close'].iloc[-1])} for t in V2_CLASS_TICKER.values() if t in b_data and not b_data[t].empty}

    spy_df = b_data.get("SPY")
    latest_market_date_str = spy_df.index[-1].strftime("%Y-%m-%d") if spy_df is not None and not spy_df.empty else None
    executing_pending = compute_executing_pending(prev_pending, latest_market_date_str)

    pf = load_json_safe(PORTFOLIO_FILE, default={"open_positions": {}, "trade_history": []})
    held_eq = [t for t in pf.get("open_positions", {}).keys() if t not in ("IEF", "GLD", "BTC")]

    new_pending = prev_pending
    eq_data = {}

    # 2. Basket azionario: ricalcolato su tutto l'S&P 500 solo a fine trimestre (o alla
    # primissima decisione dopo la migrazione, se cade fuori trimestre); altrimenti si
    # mantiene il basket gia' in portafoglio (§4 della spec). La riselezione avviene
    # SOLO nel giorno della decisione (deciding_new), non in quello dell'esecuzione:
    # stessa separazione i / i+1 usata nei backtest validati.
    pending_orders_struct = None
    if deciding_new:
        allocations_new, new_hysteresis, debug = compute_v2_macro_signal(b_data, prev_hysteresis)
        print(f"    Decisione calcolata: {allocations_new} — in attesa della prossima barra di mercato per l'esecuzione.")

        if allocations_new.get("Equities", 0) > 0:
            need_full_universe = is_quarter_end_month(now_dt) or not prev_basket
            if need_full_universe:
                print("[2/4] Riselezione basket azionario a bassa volatilita' su tutto l'S&P 500 (decisione)...")
                eq_ticks = list(set(get_sp500_tickers() + held_eq))
                eq_data = fetch_bulk_parallel(eq_ticks, max_workers=MAX_WORKERS_DEFAULT)
                sector_of = fetch_sector_map(list(eq_data.keys()), max_workers=MAX_WORKERS_DEFAULT)
                new_basket = select_low_vol_basket(eq_data, top_n=V2_EQUITY_TOP_N, prev_tickers=set(held_eq), sector_of=sector_of)
            else:
                print("[2/4] Nessuna rotazione trimestrale in questa decisione: mantengo il basket azionario attuale.")
                new_basket = prev_basket
                tickers_needed = list(set([row["Ticker"] for row in prev_basket] + held_eq))
                if tickers_needed:
                    eq_data = fetch_bulk_parallel(tickers_needed, max_workers=MAX_WORKERS_DEFAULT)
        else:
            print("[2/4] Classe Equity disattivata nella nuova decisione.")
            new_basket = []
            if held_eq:
                eq_data = fetch_bulk_parallel(held_eq, max_workers=MAX_WORKERS_DEFAULT)

        new_pending = {
            "allocations": allocations_new,
            "hysteresis": new_hysteresis,
            "signal_debug": debug,
            "basket": new_basket,
            "decided_date": today_str,
            "decided_month": current_month_str,
        }
        output["v2_state"]["last_decision_month"] = current_month_str
    elif executing_pending:
        print(f"[2/4] Esecuzione della decisione presa il {prev_pending['decided_date']}: {prev_pending['allocations']}")
        incoming_basket = prev_pending.get("basket", [])
        tickers_needed = list(set([row["Ticker"] for row in incoming_basket] + [row["Ticker"] for row in prev_basket] + held_eq))
        if tickers_needed:
            eq_data = fetch_bulk_parallel(tickers_needed, max_workers=MAX_WORKERS_DEFAULT)
    else:
        if prev_pending:
            print(f"    Decisione del {prev_pending['decided_date']} ancora in attesa della prossima barra di mercato: nessuna nuova decisione oggi.")
        else:
            print("    Non e' negli ultimi giorni del mese (o la decisione di questo mese e' gia' stata presa): resta l'ultima decisione attiva.")
        tickers_needed = list(set([row["Ticker"] for row in prev_basket] + held_eq))
        if tickers_needed:
            eq_data = fetch_bulk_parallel(tickers_needed, max_workers=MAX_WORKERS_DEFAULT)

    # L'allocazione/basket "attivi" (mostrati in dashboard, usati per il ribilanciamento
    # vero) diventano quelli della decisione SOLO il giorno dell'esecuzione — nel giorno
    # in cui viene solo decisa, il portafoglio reale non e' ancora cambiato, quindi
    # dashboard e Telegram continuano a mostrare i valori precedenti.
    if executing_pending:
        allocations = prev_pending["allocations"]
        basket = prev_pending.get("basket", [])
        macro_dates, macro_events = update_macro_regimes(allocations, old_data, today_str)
        output["allocations"] = allocations
        output["macro_dates"] = macro_dates
        output["macro_events"] = macro_events
        output["v2_state"]["hysteresis"] = prev_pending["hysteresis"]
        output["v2_state"]["signal_debug"] = prev_pending["signal_debug"]
        if basket != prev_basket:
            output["v2_state"]["basket_quarter"] = prev_pending.get("decided_month")
    else:
        allocations = output["allocations"]
        basket = prev_basket

    output["v2_state"]["pending_decision"] = None if executing_pending else new_pending
    output["v2_state"]["basket"] = basket
    output["top20"] = basket  # compatibilita' di schema con la dashboard esistente

    # 3. Crypto: solo BTC-USD, nessuna rotazione altcoin (testata e respinta — vedi Apex Allocation §7-bis)
    print("[3/4] Prezzo BTC-USD...")
    if allocations.get("Crypto", 0) > 0 and b_data.get("BTC-USD") is not None and not b_data["BTC-USD"].empty:
        output["crypto_top"] = [{"Ticker": "BTC", "Prezzo ($)": round(float(b_data["BTC-USD"]["Close"].iloc[-1]), 2), "Stop Loss ($)": 0.0}]
    else:
        output["crypto_top"] = []

    prices_by_ticker = {}
    prices_by_ticker.update(latest_prices(b_data))
    prices_by_ticker.update(latest_prices(eq_data))

    # Calcola ordini pendenti se oggi è giorno di decisione
    if deciding_new:
        pending_orders_struct = compute_rebalance_orders_structured(pf.get("open_positions", {}), allocations_new, new_basket, prices_by_ticker)
        if new_pending:
            new_pending["orders"] = pending_orders_struct["orders"]
            new_pending["action_log"] = pending_orders_struct["action_log"]
        pf["pending_orders"] = pending_orders_struct["orders"]
        pf["pending_orders_date"] = today_str
        pf["last_action_log"] = pending_orders_struct["action_log"]
        pf["last_action_date"] = today_str

    save_json_atomic(APEX_DATA_FILE, output)

    # 4. Ribilanciamento (solo il giorno dell'esecuzione) + tracking quotidiano dell'equity curve
    print("[4/4] Aggiornamento Portafoglio ed Equity Curve...")
    nav_usd = mark_to_market_and_compound_nav(pf, prices_by_ticker)
    save_json_atomic(PORTFOLIO_FILE, pf)

    if executing_pending:
        action_log = update_portfolio(allocations, basket, prices_by_ticker, today_str)
        pf_after = load_json_safe(PORTFOLIO_FILE, default={"open_positions": {}, "trade_history": []})
        nav_usd = pf_after.get("nav_usd", nav_usd)
        pf_after["pending_orders"] = []  # ordini eseguiti
        if action_log:
            pf_after["last_action_log"] = action_log
            pf_after["last_action_date"] = today_str
        save_json_atomic(PORTFOLIO_FILE, pf_after)
    else:
        action_log = (pending_orders_struct["action_log"] if pending_orders_struct else [])

    update_equity_curve(nav_usd, today_str)

    has_orders = any(any(k in log for k in ("APERTURA", "CHIUSURA", "MIGRAZIONE", "Ribilanciamento", "Uscito", "TRIM", "INCREMENTO")) for log in action_log) or bool(pending_orders_struct and pending_orders_struct.get("orders"))

    pf_state = load_json_safe(PORTFOLIO_FILE, default={})
    last_alert_str = pf_state.get("last_telegram_alert_date")
    weekly_due = compute_weekly_due(today_str, last_alert_str)

    if weekly_due or output.get("macro_events") or has_orders:
        sent = send_telegram_alert(output, action_log, is_rotation_now=executing_pending, pending_orders_struct=pending_orders_struct)
        if sent:
            pf_state["last_telegram_alert_date"] = today_str
            save_json_atomic(PORTFOLIO_FILE, pf_state)
    else:
        print("[-] Nessun alert Telegram programmato oggi (nessun ordine/cambio regime, heartbeat settimanale non ancora dovuto).")

    elapsed = time.time() - start_time
    print(f"=== ESECUZIONE COMPLETATA CON SUCCESSO IN {elapsed:.2f}s ===")


if __name__ == "__main__":
    main()
