"""
apex_basket_size_grid_test.py — Il numero di posizioni nel basket azionario
di Apex V2 (V2_EQUITY_TOP_N=15, apex_v2_engine.py) e' davvero un ottimo, o
una taglia diversa fa meglio? APEX_V2_SPEC.md §8.27 punto 2 aveva gia'
testato un SOLO punto alternativo (20 titoli, buffer-rank 25) e lo aveva
respinto (Calmar/MaxDD peggiori, +26% eventi tassabili) — ma non una vera
griglia. Questo script la completa: {10, 12, 15, 18, 20, 25} titoli, con
buffer_rank = top_n + 5 (stessa convenzione del valore attuale, 15+5=20),
sullo stesso harness walk-forward point-in-time di sector_cap_grid_test.py
(stesso universo S&P 500 reale point-in-time, stesso overlay macro v2,
stessi costi/tasse, sector cap fisso a 2 = valore attuale di produzione,
gia' verificato indifferente in quella grid) — l'unica variabile che cambia
e' la dimensione del basket.

Validazione: PBO-CSCV su tutta la griglia (stesso periodo, stesso universo —
il caso d'uso naturale del PBO) e DSR sul migliore con n_trials = numero di
taglie REALMENTE provate in questo script, oltre alle metriche gia' viste
in sector_cap_grid_test.py (alpha CAPM full-sample e finestra recente).
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
from apex_v2_engine import compute_v2_macro_signal, select_low_vol_basket, V2_CLASS_TICKER
from metrics import cagr as _cagr, sharpe as _sharpe, max_drawdown as _max_drawdown
from tax_engine import apply_italian_tax as _apply_italian_tax
from statistical_validation import deflated_sharpe_ratio, pbo_cscv, block_bootstrap_ci
from apex_stocks_vs_etf_backtest import (
    DATA_DIR, PERIODS_PER_YEAR, load_weekly_macro, load_weekly_sp500, load_pointintime_snapshots,
    eligible_universe_for_year, build_ohlc_like,
)
from sector_cap_grid_test import _capm_alpha, SECTOR_MAP_FILE

FIXED_MAX_PER_SECTOR = 2  # valore attuale di produzione, gia' verificato indifferente in sector_cap_grid_test.py


def run_backtest(top_n: int, buffer_rank: int, sector_of: dict):
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
            basket = select_low_vol_basket(
                eq_data, top_n=top_n, buffer_rank=buffer_rank, prev_tickers=prev_basket_tickers,
                sector_of=sector_of, max_per_sector=FIXED_MAX_PER_SECTOR,
            )
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
    weights_df = pd.DataFrame({"Equity": w_equity, "Bonds": w_bonds, "Gold": w_gold, "Crypto": w_crypto})

    returns_df = pd.DataFrame({
        "Equity": pd.Series(equity_return_basket[valid_from:], index=idx),
        "Bonds": ief_ret.reindex(idx).fillna(0.0),
        "Gold": gld_ret.reindex(idx).fillna(0.0),
        "Crypto": btc_ret.reindex(idx).fillna(0.0),
    })
    tax_types = {"Equity": "REDDITO_DIVERSO", "Bonds": "REDDITO_CAPITALE", "Gold": "REDDITO_DIVERSO", "Crypto": "REDDITO_DIVERSO"}

    port_gross = (returns_df * weights_df).sum(axis=1)
    weight_change = weights_df.diff().abs().sum(axis=1).fillna(0.0)
    cost_bps_map = {"Equity": 0.0010, "Bonds": 0.0008, "Gold": 0.0010, "Crypto": 0.0010}
    cost_drag = weight_change * np.mean(list(cost_bps_map.values()))
    port_gross_after_costs = port_gross - cost_drag
    port_net = _apply_italian_tax(returns_df, weights_df, tax_types=tax_types)
    port_net_after_costs = port_net - cost_drag

    spy_ret_aligned = spy_ret.reindex(idx).fillna(0.0)
    alpha_full, t_full, p_full = _capm_alpha(port_gross_after_costs, spy_ret_aligned)

    idx_dt = pd.DatetimeIndex(idx)
    recent_mask = idx_dt >= pd.Timestamp("2024-02-01")
    recent_idx = idx_dt[recent_mask]
    if recent_mask.sum() > 20:
        alpha_recent, t_recent, p_recent = _capm_alpha(port_gross_after_costs.loc[recent_idx], spy_ret_aligned.loc[recent_idx])
    else:
        alpha_recent, t_recent, p_recent = float("nan"), float("nan"), float("nan")

    return {
        "net": port_net_after_costs,
        "cagr_netto": _cagr(port_net_after_costs, PERIODS_PER_YEAR),
        "sharpe_netto": _sharpe(port_net_after_costs, periods_per_year=PERIODS_PER_YEAR),
        "maxdd_netto": _max_drawdown(port_net_after_costs),
        "alpha_full": alpha_full, "p_full": p_full, "alpha_recent": alpha_recent, "p_recent": p_recent,
    }


def main():
    sector_of = json.load(open(SECTOR_MAP_FILE))
    grid = [10, 12, 15, 18, 20, 25]

    print(f"{'Top-N (buffer=N+5)':<22}{'CAGR netto':>12}{'Sharpe netto':>14}{'MaxDD netto':>13}{'Calmar':>9}{'Alpha 12y':>11}{'p (12y)':>10}{'Alpha rec.':>12}{'p (rec.)':>10}")
    results = {}
    for top_n in grid:
        r = run_backtest(top_n, top_n + 5, sector_of)
        calmar = r["cagr_netto"] / abs(r["maxdd_netto"]) if r["maxdd_netto"] != 0 else float("nan")
        results[top_n] = r
        label = f"{top_n} (attuale)" if top_n == 15 else str(top_n)
        print(f"{label:<22}{r['cagr_netto']*100:>11.2f}%{r['sharpe_netto']:>14.2f}{r['maxdd_netto']*100:>12.2f}%{calmar:>9.2f}"
              f"{r['alpha_full']*100:>10.2f}%{r['p_full']:>10.4f}{r['alpha_recent']*100:>11.2f}%{r['p_recent']:>10.4f}")

    perf_matrix = np.column_stack([results[n]["net"].values for n in grid])
    n_splits = 8
    usable_len = (len(perf_matrix) // n_splits) * n_splits
    pbo = pbo_cscv(perf_matrix[-usable_len:], n_splits=n_splits)
    print(f"\nPBO-CSCV su {len(grid)} taglie di basket: {pbo*100:.1f}% "
          "(vicino al 50% = nessuna taglia batte le altre in modo robusto fuori campione)")

    best_n = max(grid, key=lambda n: results[n]["sharpe_netto"])
    best_net = results[best_n]["net"]
    dsr = deflated_sharpe_ratio(results[best_n]["sharpe_netto"], n_trials=len(grid), n_obs=len(best_net))
    lo, hi = block_bootstrap_ci(best_net.values, lambda r: _sharpe(pd.Series(r), periods_per_year=PERIODS_PER_YEAR),
                                 block_size=12, ci=0.90, seed=42)
    print(f"Migliore per Sharpe netto: top_n={best_n} (Sharpe {results[best_n]['sharpe_netto']:.2f} vs "
          f"{results[15]['sharpe_netto']:.2f} dell'attuale 15)")
    print(f"  DSR (n_trials={len(grid)}, conteggio reale): {dsr:.4f}")
    print(f"  CI 90% Sharpe (block bootstrap): [{lo:.2f}, {hi:.2f}]")


if __name__ == "__main__":
    main()
