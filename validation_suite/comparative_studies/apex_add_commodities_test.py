"""
apex_add_commodities_dbc_test.py — Aggiungere una 5a classe macro, Commodities
(proxy DBC, Invesco DB Commodity Index Tracking Fund, paniere ampio di 14
materie prime a peso energia-pesante), ad Apex V2 migliora la strategia o e'
ridondante con Gold (che gia' copre parte dell'esposizione a materie prime)?

compute_v2_macro_signal() itera su apex_v2_engine.V2_CLASS_TICKER (dict
globale di modulo, non un parametro) — per testare una classe aggiuntiva
senza toccare il file di produzione, questo script sovrascrive
apex_v2_engine.V2_CLASS_TICKER a runtime prima di ogni chiamata (tecnica di
test standard, nessuna modifica permanente al modulo). Stesso harness
walk-forward point-in-time gia' validato in apex_class_size_grid_test.py
(basket azionario reale, universo S&P 500 point-in-time, costi/tasse reali).

Trattamento fiscale DBC: REDDITO_DIVERSO (come Gold/GLD in questo progetto,
non REDDITO_CAPITALE) — DBC e' un ETF US-domiciliato strutturato come
commodity pool, non un fondo UCITS armonizzato, stessa categoria strutturale
di GLD (grantor trust US) gia' trattata come REDDITO_DIVERSO ovunque in
questo progetto.

Limite dichiarato: DBC e' un ETF su FUTURES su materie prime, non spot — il
suo rendimento storico reale incorpora costi di roll (spesso negativi in
regimi di contango prolungato, specialmente nel comparto energia che pesa
>50% dell'indice) che un indice spot di materie prime non avrebbe. Questo e'
il proxy REALE e liquido disponibile per un investitore, non un'approssimazione
peggiorativa arbitraria.
"""

from __future__ import annotations
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "validation_suite" / "framework"))
import apex_v2_engine
from apex_v2_engine import compute_v2_macro_signal, select_low_vol_basket, V2_MAX_PER_SECTOR
from metrics import cagr as _cagr, sharpe as _sharpe, max_drawdown as _max_drawdown
from tax_engine import apply_italian_tax as _apply_italian_tax
from statistical_validation import deflated_sharpe_ratio, pbo_cscv, block_bootstrap_ci
from apex_stocks_vs_etf_backtest import (
    DATA_DIR, PERIODS_PER_YEAR, load_weekly_macro, load_weekly_sp500, load_pointintime_snapshots,
    eligible_universe_for_year, build_ohlc_like, _fetch_weekly_adj,
)
from sector_cap_grid_test import SECTOR_MAP_FILE

BASE_CLASS_TICKER = {"Equities": "SPY", "Bonds": "IEF", "Gold": "GLD", "Crypto": "BTC-USD"}
WITH_COMMODITIES_CLASS_TICKER = dict(BASE_CLASS_TICKER, Commodities="DBC")

# (label, class_ticker_map, base_weight, vol_target)
GRID = [
    ("Attuale (4 classi, 50%/22%)", BASE_CLASS_TICKER, 0.50, 0.22),
    ("+ Commodities/DBC (5 classi, 50%/22% invariato)", WITH_COMMODITIES_CLASS_TICKER, 0.50, 0.22),
    ("+ Commodities/DBC (5 classi, 40%/22%)", WITH_COMMODITIES_CLASS_TICKER, 0.40, 0.22),
    ("+ Commodities/DBC (5 classi, 40%/18%)", WITH_COMMODITIES_CLASS_TICKER, 0.40, 0.18),
]


def fetch_dbc() -> None:
    _fetch_weekly_adj("DBC", "15y").to_csv(DATA_DIR / "DBC_weekly.csv")


def print_correlation_diagnostic(macro_prices: dict) -> None:
    rets = pd.DataFrame({t: p.pct_change() for t, p in macro_prices.items()}).dropna()
    print("--- Correlazione settimanale (rendimenti, campione comune) ---")
    corr = rets.corr()
    print(corr.round(2).to_string())
    print(f"  Campione: {len(rets)} settimane\n")


def run_backtest(class_ticker: dict, base_weight: float, vol_target: float, sector_of: dict):
    apex_v2_engine.V2_CLASS_TICKER = class_ticker  # override runtime, nessuna modifica permanente al modulo
    try:
        snapshots = load_pointintime_snapshots()
        with open(DATA_DIR / "sp500_tickers.json") as f:
            all_tickers = json.load(f)

        stock_prices = {}
        for t in all_tickers:
            try:
                stock_prices[t] = load_weekly_sp500(t)
            except FileNotFoundError:
                continue

        macro_prices = {ticker: load_weekly_macro(ticker) for ticker in class_ticker.values()}
        common_index = macro_prices["SPY"].index
        for s in macro_prices.values():
            common_index = common_index.intersection(s.index)
        weeks = list(common_index)
        n = len(weeks)

        stock_rets = {t: p.pct_change() for t, p in stock_prices.items()}
        ief_ret = macro_prices["IEF"].pct_change()
        gld_ret = macro_prices["GLD"].pct_change()
        btc_ret = macro_prices["BTC-USD"].pct_change()
        dbc_ret = macro_prices["DBC"].pct_change() if "DBC" in macro_prices else None

        hysteresis_state, prev_basket_tickers, current_basket = None, None, []
        locked_alloc = None
        macro_alloc_history, equity_return_basket = [], []

        MIN_HISTORY = 40
        for i, wk in enumerate(weeks):
            if i < MIN_HISTORY:
                macro_alloc_history.append(None)
                equity_return_basket.append(0.0)
                continue

            b_data = {ticker: build_ohlc_like(macro_prices[ticker].loc[:wk]) for ticker in class_ticker.values()}
            alloc, hysteresis_state, _debug = compute_v2_macro_signal(
                b_data, prev_hysteresis_state=hysteresis_state,
                base_weight_per_class=base_weight, vol_target=vol_target,
            )

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

        weights_data = {
            "Equity": alloc_frac("Equities"), "Bonds": alloc_frac("Bonds"),
            "Gold": alloc_frac("Gold"), "Crypto": alloc_frac("Crypto"),
        }
        returns_data = {
            "Equity": pd.Series(equity_return_basket[valid_from:], index=idx),
            "Bonds": ief_ret.reindex(idx).fillna(0.0),
            "Gold": gld_ret.reindex(idx).fillna(0.0),
            "Crypto": btc_ret.reindex(idx).fillna(0.0),
        }
        tax_types = {"Equity": "REDDITO_DIVERSO", "Bonds": "REDDITO_CAPITALE", "Gold": "REDDITO_DIVERSO", "Crypto": "REDDITO_DIVERSO"}

        w_commodities = None
        if "Commodities" in class_ticker:
            weights_data["Commodities"] = alloc_frac("Commodities")
            returns_data["Commodities"] = dbc_ret.reindex(idx).fillna(0.0)
            tax_types["Commodities"] = "REDDITO_DIVERSO"  # come Gold/GLD: ETF US non-UCITS, stessa categoria strutturale
            w_commodities = weights_data["Commodities"]

        weights_df = pd.DataFrame(weights_data)
        returns_df = pd.DataFrame(returns_data)

        port_gross = (returns_df * weights_df).sum(axis=1)
        weight_change = weights_df.diff().abs().sum(axis=1).fillna(0.0)
        cost_bps_map = {"Equity": 0.0010, "Bonds": 0.0008, "Gold": 0.0010, "Crypto": 0.0010, "Commodities": 0.0010}
        cost_drag = weight_change * np.mean([cost_bps_map[c] for c in weights_df.columns])
        port_net = _apply_italian_tax(returns_df, weights_df, tax_types=tax_types)
        port_net_after_costs = port_net - cost_drag

        return {
            "net": port_net_after_costs,
            "cagr_netto": _cagr(port_net_after_costs, PERIODS_PER_YEAR),
            "sharpe_netto": _sharpe(port_net_after_costs, periods_per_year=PERIODS_PER_YEAR),
            "maxdd_netto": _max_drawdown(port_net_after_costs),
            "avg_gross_exposure": weights_df.sum(axis=1).mean(),
            "w_commodities": w_commodities,
        }
    finally:
        apex_v2_engine.V2_CLASS_TICKER = BASE_CLASS_TICKER  # ripristina sempre, anche in caso di eccezione


def main():
    if not (DATA_DIR / "DBC_weekly.csv").exists():
        print("[*] Scarico DBC da Yahoo Finance...")
        fetch_dbc()

    sector_of = json.load(open(SECTOR_MAP_FILE))

    macro_prices_all = {t: load_weekly_macro(t) for t in ["SPY", "IEF", "GLD", "BTC-USD", "DBC"]}
    print_correlation_diagnostic(macro_prices_all)

    print(f"{'Config':<48}{'CAGR netto':>12}{'Sharpe netto':>14}{'MaxDD netto':>13}{'Calmar':>9}{'Espos. media':>13}")
    results = {}
    for label, class_ticker, bw, vt in GRID:
        r = run_backtest(class_ticker, bw, vt, sector_of)
        calmar = r["cagr_netto"] / abs(r["maxdd_netto"]) if r["maxdd_netto"] != 0 else float("nan")
        results[label] = r
        print(f"{label:<48}{r['cagr_netto']*100:>11.2f}%{r['sharpe_netto']:>14.2f}{r['maxdd_netto']*100:>12.2f}%{calmar:>9.2f}"
              f"{r['avg_gross_exposure']*100:>12.1f}%")

    print()
    for label, _, _, _ in GRID:
        wc = results[label]["w_commodities"]
        if wc is not None:
            active = wc > 1e-9
            print(f"{label}: Commodities attiva {active.mean()*100:.1f}% delle settimane "
                  f"({int(active.sum())}/{len(wc)}), esposizione media quando attiva {wc[active].mean()*100:.1f}%")

    variant_order = [label for label, _, _, _ in GRID]
    perf_matrix = np.column_stack([results[m]["net"].values for m in variant_order])
    n_splits = 8
    usable_len = (len(perf_matrix) // n_splits) * n_splits
    pbo = pbo_cscv(perf_matrix[-usable_len:], n_splits=n_splits)
    print(f"\nPBO-CSCV su {len(variant_order)} configurazioni (con/senza Commodities): {pbo*100:.1f}% "
          "(vicino al 50% = nessuna combinazione batte le altre in modo robusto)")

    best_label = max(variant_order, key=lambda m: results[m]["sharpe_netto"])
    baseline_label = "Attuale (4 classi, 50%/22%)"
    best_net = results[best_label]["net"]
    dsr = deflated_sharpe_ratio(results[best_label]["sharpe_netto"], n_trials=len(variant_order), n_obs=len(best_net))
    lo, hi = block_bootstrap_ci(best_net.values, lambda r: _sharpe(pd.Series(r), periods_per_year=PERIODS_PER_YEAR),
                                 block_size=12, ci=0.90, seed=42)
    print(f"\nMigliore per Sharpe netto: {best_label} (Sharpe {results[best_label]['sharpe_netto']:.2f} vs "
          f"{results[baseline_label]['sharpe_netto']:.2f} dell'attuale a 4 classi)")
    print(f"  DSR (n_trials={len(variant_order)}, conteggio reale): {dsr:.4f}")
    print(f"  CI 90% Sharpe (block bootstrap): [{lo:.2f}, {hi:.2f}]")

    # Confronto accoppiato diretto: baseline vs la miglior variante con Commodities
    if best_label != baseline_label:
        diff_series = (results[best_label]["net"] - results[baseline_label]["net"]).dropna()
        mean_diff_annual = diff_series.mean() * PERIODS_PER_YEAR * 100
        lo_d, hi_d = block_bootstrap_ci(diff_series.values, lambda r: pd.Series(r).mean() * PERIODS_PER_YEAR * 100,
                                         block_size=12, ci=0.90, seed=42)
        n_weeks_better = int((diff_series > 0).sum())
        print(f"\nConfronto accoppiato diretto ({best_label} meno baseline 4 classi):")
        print(f"  Overperformance media annualizzata: {mean_diff_annual:+.2f}pp/anno")
        print(f"  CI 90% (block bootstrap): [{lo_d:+.2f}, {hi_d:+.2f}]pp/anno "
              f"({'ESCLUDE' if lo_d * hi_d > 0 else 'INCLUDE'} lo zero)")
        print(f"  Settimane in cui la variante con Commodities ha fatto meglio: {n_weeks_better}/{len(diff_series)} "
              f"({n_weeks_better/len(diff_series)*100:.0f}%)")


if __name__ == "__main__":
    main()
