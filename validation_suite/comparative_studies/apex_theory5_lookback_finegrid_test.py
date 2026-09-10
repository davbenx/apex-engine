"""
apex_theory5_lookback_finegrid_test.py — Terzo giro di verifica per la
Teoria #5 (basket azionario low-beta), richiesto direttamente dall'utente
("dobbiamo vederci chiaro"). Il secondo giro ha testato solo 3 punti
(13/26/52 settimane) con un pattern NON monotono — troppo pochi punti per
distinguere un vero "sweet spot" da rumore su un singolo valore fortunato.
Qui si testa una griglia fine di 9 lookback (16/20/22/24/26/28/30/33/39
settimane) per vedere la FORMA reale della relazione.

Ottimizzazione: il segnale macro (isteresi/vol-target sulle 4 classi) e'
IDENTICO in tutte le varianti (la Teoria #5 tocca SOLO il criterio di
selezione del basket azionario, non il timing macro) — calcolato UNA VOLA
SOLA e riusato per ogni lookback, invece di ricalcolarlo da zero 9 volte
(il costo dominante del walk-forward e' comunque il rebuild trimestrale
del basket su ~500 titoli, non evitabile, ma il segnale macro e' condiviso).

Nessuna riga di apex_v2_engine.py modificata.
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
from apex_v2_engine import (
    compute_v2_macro_signal, select_low_vol_basket, V2_MAX_PER_SECTOR, V2_CLASS_TICKER,
)
from metrics import cagr as _cagr, sharpe as _sharpe, max_drawdown as _max_drawdown
from tax_engine import apply_italian_tax as _apply_italian_tax
from statistical_validation import block_bootstrap_ci
from apex_stocks_vs_etf_backtest import (
    DATA_DIR, PERIODS_PER_YEAR, load_weekly_macro, load_weekly_sp500, load_pointintime_snapshots,
    eligible_universe_for_year, build_ohlc_like,
)
from sector_cap_grid_test import SECTOR_MAP_FILE
from apex_beta_basket_selection_test import select_low_beta_basket

LOOKBACK_GRID = [16, 20, 22, 24, 26, 28, 30, 33, 39]
MIN_HISTORY = 40


def compute_macro_signal_history(macro_prices, weeks):
    hysteresis_state, locked_alloc = None, None
    macro_alloc_history = []
    n = len(weeks)
    for i, wk in enumerate(weeks):
        if i < MIN_HISTORY:
            macro_alloc_history.append(None)
            continue
        b_data = {V2_CLASS_TICKER[c]: build_ohlc_like(macro_prices[V2_CLASS_TICKER[c]].loc[:wk]) for c in V2_CLASS_TICKER}
        alloc, hysteresis_state, _debug = compute_v2_macro_signal(b_data, prev_hysteresis_state=hysteresis_state)
        is_month_end = (i + 1 >= n) or (weeks[i + 1].month != wk.month)
        if locked_alloc is None:
            locked_alloc = alloc
        macro_alloc_history.append(dict(locked_alloc))
        if is_month_end:
            locked_alloc = alloc
    return macro_alloc_history


def run_basket_variant(lookback, use_low_beta, macro_alloc_history, macro_prices, weeks, n,
                        stock_prices, stock_rets, snapshots, sector_of):
    prev_basket_tickers, current_basket = None, []
    equity_return_basket = []

    for i, wk in enumerate(weeks):
        if i < MIN_HISTORY:
            equity_return_basket.append(0.0)
            continue
        is_month_end = (i + 1 >= n) or (weeks[i + 1].month != wk.month)

        def rebuild_basket():
            eligible = eligible_universe_for_year(snapshots, wk.year)
            eq_data = {t: build_ohlc_like(p.loc[:wk]) for t, p in stock_prices.items() if t in eligible}
            if use_low_beta:
                spy_data_upto = build_ohlc_like(macro_prices["SPY"].loc[:wk])
                basket = select_low_beta_basket(eq_data, spy_data_upto, lookback_weeks=lookback,
                                                 prev_tickers=prev_basket_tickers, sector_of=sector_of)
            else:
                basket = select_low_vol_basket(eq_data, lookback_weeks=lookback, prev_tickers=prev_basket_tickers,
                                                sector_of=sector_of, max_per_sector=V2_MAX_PER_SECTOR)
            return [b["Ticker"] for b in basket]

        if not current_basket:
            current_basket = rebuild_basket()
            prev_basket_tickers = set(current_basket)
        elif is_month_end and wk.month in (3, 6, 9, 12):
            current_basket = rebuild_basket()
            prev_basket_tickers = set(current_basket)

        basket_ret = float(np.mean([stock_rets[t].loc[wk] for t in current_basket if t in stock_rets])) if current_basket else 0.0
        equity_return_basket.append(basket_ret)

    valid_from = MIN_HISTORY
    idx = weeks[valid_from:]

    def alloc_frac(cls):
        return pd.Series([macro_alloc_history[i].get(cls, 0.0) / 100.0 for i in range(valid_from, n)], index=idx)

    ief_ret = macro_prices["IEF"].pct_change()
    gld_ret = macro_prices["GLD"].pct_change()
    btc_ret = macro_prices["BTC-USD"].pct_change()

    weights_df = pd.DataFrame({
        "Equity": alloc_frac("Equities"), "Bonds": alloc_frac("Bonds"),
        "Gold": alloc_frac("Gold"), "Crypto": alloc_frac("Crypto"),
    })
    returns_df = pd.DataFrame({
        "Equity": pd.Series(equity_return_basket[valid_from:], index=idx),
        "Bonds": ief_ret.reindex(idx).fillna(0.0),
        "Gold": gld_ret.reindex(idx).fillna(0.0),
        "Crypto": btc_ret.reindex(idx).fillna(0.0),
    })
    tax_types = {"Equity": "REDDITO_DIVERSO", "Bonds": "REDDITO_CAPITALE", "Gold": "REDDITO_DIVERSO", "Crypto": "REDDITO_DIVERSO"}

    weight_change = weights_df.diff().abs().sum(axis=1).fillna(0.0)
    cost_bps_map = {"Equity": 0.0010, "Bonds": 0.0008, "Gold": 0.0010, "Crypto": 0.0010}
    cost_drag = weight_change * np.mean(list(cost_bps_map.values()))
    port_net = _apply_italian_tax(returns_df, weights_df, tax_types=tax_types)
    port_net_after_costs = port_net - cost_drag

    return {
        "net": port_net_after_costs,
        "cagr_netto": _cagr(port_net_after_costs, PERIODS_PER_YEAR),
        "sharpe_netto": _sharpe(port_net_after_costs, periods_per_year=PERIODS_PER_YEAR),
        "maxdd_netto": _max_drawdown(port_net_after_costs),
    }


def main():
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
    stock_rets = {t: p.pct_change() for t, p in stock_prices.items()}

    macro_prices = {V2_CLASS_TICKER[c]: load_weekly_macro(V2_CLASS_TICKER[c]) for c in V2_CLASS_TICKER}
    common_index = macro_prices["SPY"].index
    for s in macro_prices.values():
        common_index = common_index.intersection(s.index)
    weeks = list(common_index)
    n = len(weeks)

    print("[*] Calcolo il segnale macro (condiviso da tutte le varianti)...")
    macro_alloc_history = compute_macro_signal_history(macro_prices, weeks)

    print(f"\n{'Lookback (bassa vol)':<25}{'CAGR':>9}{'Sharpe':>9}{'MaxDD':>9}   ||   "
          f"{'Lookback (low-beta)':<25}{'CAGR':>9}{'Sharpe':>9}{'MaxDD':>9}")

    baseline_lowvol_26 = run_basket_variant(26, False, macro_alloc_history, macro_prices, weeks, n,
                                             stock_prices, stock_rets, snapshots, sector_of)

    results_beta = {}
    results_lowvol_grid = {}
    for lb in LOOKBACK_GRID:
        r_beta = run_basket_variant(lb, True, macro_alloc_history, macro_prices, weeks, n,
                                     stock_prices, stock_rets, snapshots, sector_of)
        results_beta[lb] = r_beta
        r_lowvol = run_basket_variant(lb, False, macro_alloc_history, macro_prices, weeks, n,
                                       stock_prices, stock_rets, snapshots, sector_of) if lb != 26 else baseline_lowvol_26
        results_lowvol_grid[lb] = r_lowvol
        print(f"{lb:<25}{r_lowvol['cagr_netto']*100:>8.2f}%{r_lowvol['sharpe_netto']:>9.2f}{r_lowvol['maxdd_netto']*100:>8.2f}%   ||   "
              f"{lb:<25}{r_beta['cagr_netto']*100:>8.2f}%{r_beta['sharpe_netto']:>9.2f}{r_beta['maxdd_netto']*100:>8.2f}%")

    print(f"\n{'Lookback':<12}{'low-beta meno low-vol (stesso lookback)':>42}{'CI 90%':>28}")
    for lb in LOOKBACK_GRID:
        diff = (results_beta[lb]["net"] - results_lowvol_grid[lb]["net"]).dropna()
        mean_diff = diff.mean() * PERIODS_PER_YEAR * 100
        lo, hi = block_bootstrap_ci(diff.values, lambda r: pd.Series(r).mean() * PERIODS_PER_YEAR * 100,
                                     block_size=12, ci=0.90, seed=42)
        tag = "ESCLUDE zero" if lo * hi > 0 else "include zero"
        print(f"{lb:<12}{mean_diff:>+41.2f}pp/anno   [{lo:+.2f}, {hi:+.2f}] {tag}")

    print("\n--- low-beta a ciascun lookback confrontato SEMPRE contro il baseline di produzione (low-vol, lookback=26) ---")
    for lb in LOOKBACK_GRID:
        diff = (results_beta[lb]["net"] - baseline_lowvol_26["net"]).dropna()
        mean_diff = diff.mean() * PERIODS_PER_YEAR * 100
        lo, hi = block_bootstrap_ci(diff.values, lambda r: pd.Series(r).mean() * PERIODS_PER_YEAR * 100,
                                     block_size=12, ci=0.90, seed=42)
        tag = "ESCLUDE zero" if lo * hi > 0 else "include zero"
        print(f"  low-beta(lookback={lb}) vs baseline produzione:  {mean_diff:+.2f}pp/anno  CI90% [{lo:+.2f}, {hi:+.2f}] {tag}")


if __name__ == "__main__":
    main()
