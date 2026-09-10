"""
apex_crypto_execution_venue_test.py — Due domande dirette dell'utente sulla
gamba Crypto di Apex V2: (1) quanto costano davvero le tre vie di esecuzione
(perpetual Kraken, spot Kraken, ETP fisico stile WBTC su IBKR) al netto di
tasse/fee/TER, e (2) l'ETP/IBIT, che NON tratta 24/7 come spot/perp, fa
perdere qualcosa in performance per via delle ore/giorni di mercato chiuso?

Segnale INVARIATO in tutti e tre gli scenari: compute_v2_macro_signal decide
usando BTC-USD continuo (esattamente come fa oggi in produzione — la
decisione non dipende dal veicolo di esecuzione). Cambia SOLO come si
REALIZZA il rendimento settimanale della classe Crypto una volta che il
segnale dice di essere dentro:
  - perp/spot: rendimento di BTC-USD stesso (il perp traccia lo spot molto
    da vicino via funding — approssimazione dichiarata, nessun basis
    esplicito modellato)
  - ETP: rendimento REALE di IBIT (iShares Bitcoin Trust) — non
    WBTC-ETFP.MI, che su Yahoo ha praticamente zero storico (un solo punto
    dati, verificato) e non permette un confronto storico. IBIT è un proxy
    STRUTTURALE onesto per la domanda "il wrapper regolamentato, aperto solo
    in orario di borsa, fa perdere qualcosa?" — stessa meccanica (NAV
    tracking, arbitraggio creation/redemption, chiuso nei weekend/festivi),
    storico reale dal 2024-01-11 (~2,7 anni, non i 12+ anni di BTC-USD: la
    finestra di confronto onesta è quindi più corta, dichiarato non
    nascosto).

Costi/tasse per via (fonti: convex_engine.py per il TER WBTC reale, ricerca
web di sessione per le fee Kraken, aliquota 26% redditi diversi già
stabilita in tutto questo progetto per ogni strumento crypto):
  - perp Kraken: taker ~0.05% + funding (stima da dati REALI Kraken Futures
    gia' raccolti per altcoin_carry_funding_rate_test.py, ~1 anno) + 26%
  - spot Kraken: taker ~0.26% + 26% (l'utente ha indicato 33% in una nota
    di analisi propria — NON è l'aliquota standard 26% "redditi diversi" già
    documentata e usata ovunque in questo progetto per crypto spot; mostrato
    ENTRAMBI gli scenari fiscali, non scelto uno a caso al posto dell'altro)
  - ETP (IBIT come proxy, TER reale WBTC 0.15% da convex_engine.py) + 26%
"""

from __future__ import annotations
import json
import sys
import time
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "validation_suite" / "framework"))
from apex_v2_engine import compute_v2_macro_signal, select_low_vol_basket, V2_CLASS_TICKER, V2_MAX_PER_SECTOR
from metrics import cagr as _cagr, sharpe as _sharpe, max_drawdown as _max_drawdown
from tax_engine import apply_italian_tax as _apply_italian_tax
from statistical_validation import block_bootstrap_ci
from apex_stocks_vs_etf_backtest import (
    DATA_DIR, PERIODS_PER_YEAR, load_weekly_macro, load_weekly_sp500, load_pointintime_snapshots,
    eligible_universe_for_year, build_ohlc_like,
)
from sector_cap_grid_test import SECTOR_MAP_FILE

IBIT_DATA_FILE = Path(__file__).parent / "apex_stocks_data" / "IBIT_weekly.csv"  # riusa la cache esistente, gitignored
KRAKEN_PERP_TAKER_FEE = 0.0005
KRAKEN_SPOT_TAKER_FEE = 0.0026
WBTC_TER_ANNUAL = 0.0015  # reale, da convex_engine.py (WisdomTree Physical Bitcoin)
TAX_RATE_STANDARD = 0.26  # redditi diversi, gia' stabilito ovunque in questo progetto per crypto (perp/spot/ETP)
TAX_RATE_USER_SPOT_ALT = 0.33  # nota dell'utente per lo spot — mostrato come scenario alternativo, non sostituisce lo standard


def fetch_ibit_weekly() -> None:
    url = "https://query2.finance.yahoo.com/v8/finance/chart/IBIT?range=3y&interval=1d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    res = json.loads(urllib.request.urlopen(req, timeout=15).read().decode())
    result = res["chart"]["result"][0]
    ts = pd.to_datetime(result["timestamp"], unit="s").normalize()
    adj = result["indicators"]["adjclose"][0]["adjclose"]
    daily = pd.Series(adj, index=ts).dropna()
    weekly = daily.resample("W-FRI").last().dropna()
    IBIT_DATA_FILE.parent.mkdir(exist_ok=True)
    weekly.to_csv(IBIT_DATA_FILE)


def estimate_perp_funding_annual() -> float:
    """Funding medio REALE osservato su Kraken Futures BTC (stesso dato gia'
    raccolto per altcoin_carry_funding_rate_test.py, ~1 anno) — se la cache
    non esiste la riscarica qui, stessa fonte."""
    path = REPO_ROOT / "validation_suite" / "comparative_studies" / "carry_funding_data" / "BTC_USD_funding_hourly.csv"
    if not path.exists():
        path.parent.mkdir(exist_ok=True)
        url = "https://futures.kraken.com/derivatives/api/v4/historicalfundingrates?symbol=PF_XBTUSD"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        res = json.loads(urllib.request.urlopen(req, timeout=20).read().decode())
        s = pd.Series({pd.Timestamp(r["timestamp"]): r["relativeFundingRate"] for r in res["rates"]}).sort_index()
        s.to_csv(path)
    hourly = pd.read_csv(path, index_col=0, parse_dates=True).iloc[:, 0]
    return float(-hourly.mean() * 24 * 365)  # segno: positivo = i long pagano, costo per chi e' long


def main():
    if not IBIT_DATA_FILE.exists():
        print("[*] Scarico IBIT da Yahoo Finance...")
        fetch_ibit_weekly()
    ibit_weekly = pd.read_csv(IBIT_DATA_FILE, index_col=0, parse_dates=True).iloc[:, 0]
    ibit_ret = ibit_weekly.pct_change().dropna()
    print(f"IBIT: {len(ibit_weekly)} settimane, {ibit_weekly.index[0].date()} -> {ibit_weekly.index[-1].date()} "
          "(proxy strutturale per WBTC-ETFP.MI, che su Yahoo non ha storico utilizzabile)")

    funding_annual = estimate_perp_funding_annual()
    print(f"Funding perp reale (Kraken Futures, ~1 anno): {funding_annual*100:+.2f}%/anno "
          f"({'costo' if funding_annual > 0 else 'guadagno'} per chi e' long)\n")

    sector_of = json.load(open(SECTOR_MAP_FILE))
    snapshots = load_pointintime_snapshots()
    with open(DATA_DIR / "sp500_tickers.json") as f:
        all_tickers = json.load(f)
    stock_prices = {}
    for t in all_tickers:
        try:
            stock_prices[t] = load_weekly_sp500(t)
        except FileNotFoundError:
            continue

    macro_prices = {V2_CLASS_TICKER[c]: load_weekly_macro(V2_CLASS_TICKER[c]) for c in V2_CLASS_TICKER}
    common_index = macro_prices["SPY"].index
    for s in macro_prices.values():
        common_index = common_index.intersection(s.index)
    weeks = list(common_index)
    n = len(weeks)

    stock_rets = {t: p.pct_change() for t, p in stock_prices.items()}
    ief_ret = macro_prices["IEF"].pct_change()
    gld_ret = macro_prices["GLD"].pct_change()
    btc_ret = macro_prices["BTC-USD"].pct_change()

    hysteresis_state, prev_basket_tickers, current_basket = None, None, []
    locked_alloc = None
    macro_alloc_history, equity_return_basket = [], []

    MIN_HISTORY = 40
    for i, wk in enumerate(weeks):
        if i < MIN_HISTORY:
            macro_alloc_history.append(None)
            equity_return_basket.append(0.0)
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

        def rebuild_basket():
            eligible = eligible_universe_for_year(snapshots, wk.year)
            eq_data = {t: build_ohlc_like(p.loc[:wk]) for t, p in stock_prices.items() if t in eligible}
            basket = select_low_vol_basket(eq_data, prev_tickers=prev_basket_tickers, sector_of=sector_of, max_per_sector=V2_MAX_PER_SECTOR)
            return [b["Ticker"] for b in basket]

        if not current_basket:
            current_basket = rebuild_basket()
            prev_basket_tickers = set(current_basket)
        elif is_month_end and wk.month in (3, 6, 9, 12):
            current_basket = rebuild_basket()
            prev_basket_tickers = set(current_basket)

        basket_ret_this_week = float(np.mean([stock_rets[t].loc[wk] for t in current_basket if t in stock_rets])) if current_basket else 0.0
        equity_return_basket.append(basket_ret_this_week)

    valid_from = MIN_HISTORY
    idx = weeks[valid_from:]

    def alloc_frac(cls):
        return pd.Series([macro_alloc_history[i].get(cls, 0.0) / 100.0 for i in range(valid_from, n)], index=idx)

    w_equity, w_bonds, w_gold, w_crypto = alloc_frac("Equities"), alloc_frac("Bonds"), alloc_frac("Gold"), alloc_frac("Crypto")
    equity_series = pd.Series(equity_return_basket[valid_from:], index=idx)
    bonds_series = ief_ret.reindex(idx).fillna(0.0)
    gold_series = gld_ret.reindex(idx).fillna(0.0)
    btc_series = btc_ret.reindex(idx).fillna(0.0)
    ibit_series = ibit_ret.reindex(idx)  # NaN fuori dalla finestra IBIT (2024-01 in poi) — gestito a valle

    def run_scenario(crypto_series, crypto_tax_rate, crypto_extra_annual_drag, label, restrict_to_ibit_window):
        weights_df = pd.DataFrame({"Equity": w_equity, "Bonds": w_bonds, "Gold": w_gold, "Crypto": w_crypto})
        returns_df = pd.DataFrame({
            "Equity": equity_series, "Bonds": bonds_series, "Gold": gold_series,
            "Crypto": crypto_series.fillna(0.0) - crypto_extra_annual_drag / 52,
        })
        if restrict_to_ibit_window:
            mask = ibit_series.notna()
            weights_df, returns_df = weights_df.loc[mask], returns_df.loc[mask]

        tax_types = {"Equity": "REDDITO_DIVERSO", "Bonds": "REDDITO_CAPITALE", "Gold": "REDDITO_DIVERSO", "Crypto": "REDDITO_DIVERSO"}
        port_gross = (returns_df * weights_df).sum(axis=1)
        weight_change = weights_df.diff().abs().sum(axis=1).fillna(0.0)
        cost_bps_map = {"Equity": 0.0010, "Bonds": 0.0008, "Gold": 0.0010, "Crypto": KRAKEN_PERP_TAKER_FEE}
        cost_drag = weight_change * np.mean(list(cost_bps_map.values()))
        port_gross_after_costs = port_gross - cost_drag

        tax_types_effective = dict(tax_types)
        port_net = _apply_italian_tax(returns_df, weights_df, tax_types=tax_types_effective)
        if crypto_tax_rate != TAX_RATE_STANDARD:
            # la funzione generica usa sempre il 26% standard: applica la differenza come
            # aggiustamento proporzionale solo sulla componente Crypto realizzata (approssimazione
            # dichiarata — un calcolo esatto richiederebbe rifare il ledger fiscale a aliquota
            # diversa per asset, non ancora supportato da tax_engine.py)
            crypto_gross_contrib = (weights_df["Crypto"] * returns_df["Crypto"])
            extra_tax_drag = crypto_gross_contrib.clip(lower=0) * (crypto_tax_rate - TAX_RATE_STANDARD)
            port_net = port_net - extra_tax_drag
        port_net_after_costs = port_net - cost_drag

        print(f"=== {label} ===")
        print(f"  Campione: {len(idx if not restrict_to_ibit_window else returns_df.index)} settimane"
              f"{' (finestra IBIT, 2024-01 in poi)' if restrict_to_ibit_window else ' (storico Apex completo)'}")
        print(f"  CAGR netto: {_cagr(port_net_after_costs, PERIODS_PER_YEAR)*100:.2f}%  |  "
              f"Sharpe netto: {_sharpe(port_net_after_costs, periods_per_year=PERIODS_PER_YEAR):.2f}  |  "
              f"MaxDD netto: {_max_drawdown(port_net_after_costs)*100:.2f}%")
        return port_net_after_costs

    print("########## CONFRONTO SULLA FINESTRA COMUNE (IBIT disponibile, 2024-01 in poi) ##########\n")
    net_perp = run_scenario(btc_series, TAX_RATE_STANDARD, funding_annual, "Perpetual Kraken (26%, funding reale + taker 0.05%)", True)
    net_spot_26 = run_scenario(btc_series, TAX_RATE_STANDARD, 0.0, "Spot Kraken (26%, taker 0.26% — aliquota standard del progetto)", True)
    net_spot_33 = run_scenario(btc_series, TAX_RATE_USER_SPOT_ALT, 0.0, "Spot Kraken (33% — nota dell'utente, scenario alternativo)", True)
    net_etp = run_scenario(ibit_series, TAX_RATE_STANDARD, WBTC_TER_ANNUAL, "ETP fisico stile WBTC (26%, TER 0.15%, proxy IBIT)", True)

    print("\nDifferenza ETP vs perp (stessa finestra, stesso segnale, SOLO il veicolo di esecuzione cambia):")
    print(f"  CAGR netto: {_cagr(net_etp, PERIODS_PER_YEAR)*100:.2f}% contro {_cagr(net_perp, PERIODS_PER_YEAR)*100:.2f}%  "
          f"(differenza {(_cagr(net_etp, PERIODS_PER_YEAR) - _cagr(net_perp, PERIODS_PER_YEAR))*100:+.2f}pp)")
    lo_etp, hi_etp = block_bootstrap_ci(net_etp.values, lambda r: _sharpe(pd.Series(r), periods_per_year=PERIODS_PER_YEAR), block_size=8, ci=0.90, seed=42)
    lo_perp, hi_perp = block_bootstrap_ci(net_perp.values, lambda r: _sharpe(pd.Series(r), periods_per_year=PERIODS_PER_YEAR), block_size=8, ci=0.90, seed=42)
    print(f"  CI 90% Sharpe ETP: [{lo_etp:.2f}, {hi_etp:.2f}]  |  CI 90% Sharpe perp: [{lo_perp:.2f}, {hi_perp:.2f}] "
          "(campione corto, ~2.7 anni — CI larghe attese)")

    print("\n\n########## STORICO APEX COMPLETO (perp vs spot, IBIT non disponibile prima del 2024) ##########\n")
    run_scenario(btc_series, TAX_RATE_STANDARD, funding_annual, "Perpetual Kraken (26%, funding reale + taker 0.05%)", False)
    run_scenario(btc_series, TAX_RATE_STANDARD, 0.0, "Spot Kraken (26%, taker 0.26%)", False)
    run_scenario(btc_series, TAX_RATE_USER_SPOT_ALT, 0.0, "Spot Kraken (33% — nota dell'utente)", False)


if __name__ == "__main__":
    main()
