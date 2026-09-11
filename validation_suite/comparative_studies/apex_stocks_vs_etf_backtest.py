"""
apex_stocks_vs_etf_backtest.py — Confronto reale, netto di tasse italiane e
costi di transazione: basket di 15 titoli individuali (redditi diversi,
compensabili) contro un ETF azionario equivalente (redditi di capitale, non
compensabili) come posizione della gamba azionaria di Apex v2, a parita' di
segnale macro (isteresi adattiva + multi-timeframe + vol-target, parametri
ATTUALI di produzione — APEX_V2_SPEC.md §8.28, non i vecchi 0.25/0.13 usati
nel confronto originale di §8.3, superato da allora).

Riusa le funzioni REALI di produzione (apex_v2_engine.compute_v2_macro_signal,
select_low_vol_basket) — non una riimplementazione — e la stessa logica di
tassazione italiana gia' validata in validation_suite/framework/tax_engine.py
(apply_italian_tax, generalizzata per pesi variabili nel tempo).

Universo: filtrato per ELEGGIBILITA' POINT-IN-TIME (uno snapshot storico
REALE della composizione S&P 500 per ogni anno 2012-2026, ricostruito
dalle revisioni Wikipedia della pagina "List of S&P 500 companies" — non
la composizione attuale applicata retroattivamente). Anni senza revisione
recuperabile (rate-limit Wikipedia): fallback sullo snapshot dell'anno
piu' vicino disponibile.

**BUG REALE TROVATO E PARZIALMENTE CORRETTO in questa sessione (audit di
robustezza istituzionale)**: fino a qui l'universo PREZZI veniva costruito
da get_sp500_tickers() di backend.py — SOLO i membri ATTUALI dell'indice
— non dall'unione dei membri storici. Il filtro di eleggibilita' sopra e'
davvero point-in-time, ma non aveva NULLA da selezionare per un titolo
delistato/acquisito/rimosso dall'indice, anche se eleggibile quell'anno:
survivorship bias classico, che l'affermazione originale di questo
docstring ("non la composizione attuale applicata retroattivamente")
nascondeva senza volerlo — il problema non era nel filtro di eleggibilita'
(corretto), ma nell'universo prezzi a monte (sbagliato). Misurato: 45% dei
membri eleggibili 2012 senza alcun file prezzo prima della correzione.
Corretto con fetch_delisted_sp500_prices.py (unione di tutti gli snapshot
2012-2026, non solo i membri attuali) — copertura salita dal 60,9% al
77,8% dello storico completo (334 ticker tentati, 195 falliti con 404
genuino da Yahoo — simboli purgati per delisting/going-private troppo
vecchi, es. WBA/TWTR/CELG/TIF, non risolvibile con questa fonte dati
gratuita). Resta un gap residuo, dichiarato: ~28% mancante ancora nel
2012, in calo fino a ~1% nel 2026 — vedi validation_suite/README.md per i
numeri completi e l'impatto quantificato sulla ri-validazione.

Settori: NON applicato un vincolo di concentrazione settoriale
(select_low_vol_basket con sector_of=None). Non e' solo un limite di questo
test: l'endpoint Yahoo usato da backend.fetch_sector_map in produzione
risponde ora 401 Unauthorized (verificato in questa sessione) — il vincolo
"§8.7, max 2 titoli/settore" e' quindi silenziosamente INATTIVO anche nel
sistema live in questo momento (fail-open by design, nessun errore
visibile). Testare senza sector cap qui riflette lo stato REALE attuale
della produzione, non un'approssimazione peggiore di essa.
"""

from __future__ import annotations
import json
import sys
import time
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]  # validation_suite/comparative_studies/ -> validation_suite/ -> repo root
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "validation_suite" / "framework"))
from apex_v2_engine import compute_v2_macro_signal, select_low_vol_basket, V2_CLASS_TICKER
from metrics import cagr as _cagr, sharpe as _sharpe, max_drawdown as _max_drawdown
from tax_engine import apply_italian_tax as _apply_italian_tax
from backend import get_sp500_tickers

REPO_DIR = Path(__file__).parent
DATA_DIR = REPO_DIR / "apex_stocks_data"  # prezzi: rigenerabili, non tracciati in git (.gitignore)
POINTINTIME_FILE = REPO_ROOT / "validation_suite" / "pointintime_data" / "sp500_pointintime_snapshots.json"  # tracciato in git: non banale da rigenerare (Wikipedia rate-limit)
TRANSACTION_COST_BPS = {"stock": 0.0010, "etf": 0.0008}
PERIODS_PER_YEAR = 52  # serie SETTIMANALI — bug reale trovato e corretto: cagr/sharpe di
# framework/metrics.py di default assumono rendimenti mensili (periods_per_year=12); usarle
# su una serie settimanale senza specificare 52 sottostima sistematicamente sia il CAGR sia
# lo Sharpe (anni impliciti gonfiati di un fattore ~4.3x). Bug presente nella prima versione
# di questo file e propagato a sector_cap_grid_test.py e altcoin_vs_btc_backtest.py (corretti
# nello stesso commit) — tutti i numeri "Sharpe"/"CAGR" riportati prima di questa correzione
# per backtest settimanali in questa sessione erano sbagliati (sottostimati).


def _fetch_weekly_adj(ticker: str, rng: str) -> pd.Series:
    url = f"https://query2.finance.yahoo.com/v8/finance/chart/{ticker}?range={rng}&interval=1d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    res = json.loads(urllib.request.urlopen(req, timeout=15).read().decode())
    result = res["chart"]["result"][0]
    ts = pd.to_datetime(result["timestamp"], unit="s")
    adj = result["indicators"]["adjclose"][0]["adjclose"]
    daily = pd.Series(adj, index=ts).dropna()
    return daily.resample("W-FRI").last().dropna()


def fetch_all_price_data() -> None:
    """Scarica prezzi settimanali aggiustati per SPY/IEF/GLD/BTC-USD e per
    l'intero universo S&P 500 attuale (get_sp500_tickers, funzione reale di
    backend.py). range='15y' esplicito, non 'max': Yahoo declassa
    silenziosamente 'max' a granularita' mensile su span lunghi (bug trovato
    in questa sessione)."""
    DATA_DIR.mkdir(exist_ok=True)
    for t in ["SPY", "IEF", "GLD"]:
        _fetch_weekly_adj(t, "15y").to_csv(DATA_DIR / f"{t}_weekly.csv")
        time.sleep(0.2)
    _fetch_weekly_adj("BTC-USD", "12y").to_csv(DATA_DIR / "BTC_USD_weekly.csv")

    tickers = get_sp500_tickers()
    with open(DATA_DIR / "sp500_tickers.json", "w") as f:
        json.dump(tickers, f)
    ok, fail = 0, 0
    for t in tickers:
        try:
            w = _fetch_weekly_adj(t, "15y")
            if len(w) > 100:
                w.to_csv(DATA_DIR / f"sp500_{t.replace('-', '_').replace('.', '_')}_weekly.csv")
                ok += 1
            else:
                fail += 1
        except Exception:
            fail += 1
        time.sleep(0.15)
    print(f"Prezzi scaricati: {ok} ok, {fail} falliti su {len(tickers)} ticker S&P 500.")


def load_weekly_macro(ticker: str) -> pd.Series:
    return pd.read_csv(DATA_DIR / f"{ticker.replace('-', '_')}_weekly.csv", index_col=0, parse_dates=True).iloc[:, 0]


def load_weekly_sp500(ticker: str) -> pd.Series:
    path = DATA_DIR / f"sp500_{ticker.replace('-', '_').replace('.', '_')}_weekly.csv"
    return pd.read_csv(path, index_col=0, parse_dates=True).iloc[:, 0]


def build_ohlc_like(series: pd.Series) -> pd.DataFrame:
    return pd.DataFrame({"Close": series})


def load_pointintime_snapshots() -> dict:
    with open(POINTINTIME_FILE) as f:
        raw = json.load(f)
    return {int(y): set(t.replace(".", "-") for t in tickers) for y, tickers in raw.items()}


def eligible_universe_for_year(snapshots: dict, year: int) -> set:
    if year in snapshots:
        return snapshots[year]
    available = sorted(snapshots.keys())
    closest = min(available, key=lambda y: abs(y - year))
    return snapshots[closest]


def main():
    if not DATA_DIR.exists() or not any(DATA_DIR.glob("sp500_*_weekly.csv")):
        print(f"[*] Nessun dato di prezzo in cache in {DATA_DIR}, scarico da Yahoo Finance...")
        fetch_all_price_data()

    snapshots = load_pointintime_snapshots()
    print(f"Snapshot point-in-time disponibili per gli anni: {sorted(snapshots.keys())}")

    with open(DATA_DIR / "sp500_tickers.json") as f:
        all_tickers = json.load(f)

    stock_prices = {}
    for t in all_tickers:
        try:
            stock_prices[t] = load_weekly_sp500(t)
        except FileNotFoundError:
            continue
    print(f"Prezzi caricati per {len(stock_prices)}/{len(all_tickers)} titoli dell'universo attuale")

    macro_prices = {V2_CLASS_TICKER[c]: load_weekly_macro(V2_CLASS_TICKER[c]) for c in V2_CLASS_TICKER}
    common_index = macro_prices["SPY"].index
    for s in macro_prices.values():
        common_index = common_index.intersection(s.index)
    weeks = list(common_index)
    n = len(weeks)
    print(f"Simulazione su {n} settimane, {weeks[0].date()} -> {weeks[-1].date()}")

    stock_rets = {t: p.pct_change() for t, p in stock_prices.items()}
    spy_ret = macro_prices["SPY"].pct_change()
    ief_ret = macro_prices["IEF"].pct_change()
    gld_ret = macro_prices["GLD"].pct_change()
    btc_ret = macro_prices["BTC-USD"].pct_change()

    hysteresis_state = None
    prev_basket_tickers = None
    current_basket = []
    locked_alloc = None
    macro_alloc_history = []
    equity_return_basket = []
    equity_return_spy = []

    MIN_HISTORY = 40
    for i, wk in enumerate(weeks):
        if i < MIN_HISTORY:
            macro_alloc_history.append(None)
            equity_return_basket.append(0.0)
            equity_return_spy.append(0.0)
            continue

        b_data = {
            V2_CLASS_TICKER["Equities"]: build_ohlc_like(macro_prices["SPY"].loc[:wk]),
            V2_CLASS_TICKER["Bonds"]: build_ohlc_like(macro_prices["IEF"].loc[:wk]),
            V2_CLASS_TICKER["Gold"]: build_ohlc_like(macro_prices["GLD"].loc[:wk]),
            V2_CLASS_TICKER["Crypto"]: build_ohlc_like(macro_prices["BTC-USD"].loc[:wk]),
        }
        alloc, hysteresis_state, _debug = compute_v2_macro_signal(b_data, prev_hysteresis_state=hysteresis_state)

        is_month_end = (i + 1 >= n) or (weeks[i + 1].month != wk.month)
        if locked_alloc is None:
            locked_alloc = alloc
        macro_alloc_history.append(dict(locked_alloc))
        if is_month_end:
            locked_alloc = alloc

        if not current_basket:
            eligible = eligible_universe_for_year(snapshots, wk.year)
            eq_data = {t: build_ohlc_like(p.loc[:wk]) for t, p in stock_prices.items() if t in eligible}
            basket = select_low_vol_basket(eq_data, prev_tickers=prev_basket_tickers, sector_of=None)
            current_basket = [b["Ticker"] for b in basket]
            prev_basket_tickers = set(current_basket)

        basket_ret_this_week = float(np.mean([stock_rets[t].loc[wk] for t in current_basket if t in stock_rets])) if current_basket else 0.0
        equity_return_basket.append(basket_ret_this_week)
        equity_return_spy.append(float(spy_ret.loc[wk]) if not np.isnan(spy_ret.loc[wk]) else 0.0)

        if is_month_end and wk.month in (3, 6, 9, 12):
            eligible = eligible_universe_for_year(snapshots, wk.year)
            eq_data = {t: build_ohlc_like(p.loc[:wk]) for t, p in stock_prices.items() if t in eligible}
            basket = select_low_vol_basket(eq_data, prev_tickers=prev_basket_tickers, sector_of=None)
            current_basket = [b["Ticker"] for b in basket]
            prev_basket_tickers = set(current_basket)

    valid_from = MIN_HISTORY
    idx = weeks[valid_from:]

    def alloc_frac(cls):
        return pd.Series([macro_alloc_history[i].get(cls, 0.0) / 100.0 for i in range(valid_from, n)], index=idx)

    w_equity = alloc_frac("Equities")
    w_bonds = alloc_frac("Bonds")
    w_gold = alloc_frac("Gold")
    w_crypto = alloc_frac("Crypto")

    bonds_series = ief_ret.reindex(idx).fillna(0.0)
    gold_series = gld_ret.reindex(idx).fillna(0.0)
    crypto_series = btc_ret.reindex(idx).fillna(0.0)
    equity_basket_series = pd.Series(equity_return_basket[valid_from:], index=idx)
    equity_spy_series = pd.Series(equity_return_spy[valid_from:], index=idx)

    weights_df = pd.DataFrame({"Equity": w_equity, "Bonds": w_bonds, "Gold": w_gold, "Crypto": w_crypto})

    results = {}
    for label, equity_series, equity_tax_type, equity_cost_bps in [
        ("BASKET (15 titoli individuali, point-in-time)", equity_basket_series, "REDDITO_DIVERSO", TRANSACTION_COST_BPS["stock"]),
        ("SPY (ETF azionario)", equity_spy_series, "REDDITO_CAPITALE", TRANSACTION_COST_BPS["etf"]),
    ]:
        returns_df = pd.DataFrame({"Equity": equity_series, "Bonds": bonds_series, "Gold": gold_series, "Crypto": crypto_series})
        tax_types = {"Equity": equity_tax_type, "Bonds": "REDDITO_CAPITALE", "Gold": "REDDITO_DIVERSO", "Crypto": "REDDITO_DIVERSO"}

        port_gross = (returns_df * weights_df).sum(axis=1)
        weight_change = weights_df.diff().abs().sum(axis=1).fillna(0.0)
        cost_bps_map = {"Equity": equity_cost_bps, "Bonds": TRANSACTION_COST_BPS["etf"], "Gold": 0.0010, "Crypto": 0.0010}
        avg_cost_bps = np.mean(list(cost_bps_map.values()))
        cost_drag = weight_change * avg_cost_bps
        port_gross_after_costs = port_gross - cost_drag

        port_net = _apply_italian_tax(returns_df, weights_df, tax_types=tax_types)
        port_net_after_costs = port_net - cost_drag

        cagr_g = _cagr(port_gross_after_costs, PERIODS_PER_YEAR)
        sharpe_g = _sharpe(port_gross_after_costs, periods_per_year=PERIODS_PER_YEAR)
        dd_g = _max_drawdown(port_gross_after_costs)
        cagr_n = _cagr(port_net_after_costs, PERIODS_PER_YEAR)
        sharpe_n = _sharpe(port_net_after_costs, periods_per_year=PERIODS_PER_YEAR)
        dd_n = _max_drawdown(port_net_after_costs)
        results[label] = (cagr_g, sharpe_g, dd_g, cagr_n, sharpe_n, dd_n)

        print(f"\n=== {label} ===")
        print(f"CAGR lordo: {cagr_g*100:.2f}%  |  CAGR netto: {cagr_n*100:.2f}%")
        print(f"Sharpe lordo: {sharpe_g:.2f}  |  Sharpe netto: {sharpe_n:.2f}")
        print(f"MaxDD lordo: {dd_g*100:.2f}%  |  MaxDD netto: {dd_n*100:.2f}%")
        print(f"Calmar netto: {cagr_n/abs(dd_n):.2f}" if dd_n != 0 else "Calmar netto: n/d")


if __name__ == "__main__":
    main()
