"""
apex_class_size_grid_test.py — La dimensione delle posizioni PER CLASSE
macro (Equities/Bonds/Gold/Crypto) in Apex V2 e' davvero un ottimo, o una
combinazione base_weight/vol_target diversa fa meglio? APEX_V2_SPEC.md
§8.17/§8.19/§8.21/§8.24/§8.25/§8.28 ha gia' esplorato ESTESAMENTE questo
spazio (convergendo su base_weight=50%/vol_target=22%, "Percorso B") con
gli script di ricerca del progetto (non nel repo, research/ gitignored) —
questo script lo rifa' in modo indipendente, riproducibile e con gli
strumenti di invalidazione istituzionale ora disponibili (PBO/DSR/bootstrap,
mai usati nella ricerca originale), sullo stesso harness walk-forward
point-in-time gia' validato (basket azionario reale, universo S&P 500
point-in-time, costi/tasse reali).

base_weight_per_class e vol_target sono stati appena esposti come parametri
di compute_v2_macro_signal (apex_v2_engine.py) — prima erano letterali
hardcoded, non testabili senza duplicare la funzione.

Griglia: {base_weight, vol_target} attorno al valore attuale (0.50, 0.22),
incl. il valore precedente (0.25, 0.13) per confermare che il progetto non
sia tornato indietro per errore.
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
from apex_v2_engine import compute_v2_macro_signal, select_low_vol_basket, V2_CLASS_TICKER, V2_MAX_PER_SECTOR
from metrics import cagr as _cagr, sharpe as _sharpe, max_drawdown as _max_drawdown
from tax_engine import apply_italian_tax as _apply_italian_tax
from statistical_validation import deflated_sharpe_ratio, pbo_cscv, block_bootstrap_ci
from apex_stocks_vs_etf_backtest import (
    DATA_DIR, PERIODS_PER_YEAR, load_weekly_macro, load_weekly_sp500, load_pointintime_snapshots,
    eligible_universe_for_year, build_ohlc_like,
)
from sector_cap_grid_test import SECTOR_MAP_FILE

# (base_weight_per_class, vol_target) — l'attuale (Percorso B) + il valore precedente
# (§8.19/§8.21, pre-Percorso B) + un ventaglio principiato attorno all'attuale.
GRID = [
    ("Precedente (25%/13%, pre-Percorso B)", 0.25, 0.13),
    ("Piu' piccolo (35%/18%)", 0.35, 0.18),
    ("Attuale (50%/22%, Percorso B)", 0.50, 0.22),
    ("Piu' grande (60%/22%)", 0.60, 0.22),
    ("Piu' grande (50%/28%)", 0.50, 0.28),
    ("Molto piu' grande (75%/22%)", 0.75, 0.22),
    ("Molto piu' grande (50%/35%)", 0.50, 0.35),
    # "Nessun tetto": base_weight_per_class=1.0 rende INNOCUA la rinormalizzazione
    # esplicita (apex_v2_engine.py righe ~132-140, "mai a leva" strutturale per
    # qualunque valore) l'UNICO limite alla dimensione per classe, invece del
    # letterale 0.50/0.60/0.75 testato sopra — mai provato prima (richiesta diretta
    # dell'utente: "hai provato senza tetto?").
    ("Nessun tetto per classe (100%/22%)", 1.0, 0.22),
    ("Nessun tetto per classe (100%/13%)", 1.0, 0.13),
]


def run_backtest(base_weight: float, vol_target: float, sector_of: dict):
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
            basket = select_low_vol_basket(
                eq_data, prev_tickers=prev_basket_tickers, sector_of=sector_of, max_per_sector=V2_MAX_PER_SECTOR,
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

    return {
        "net": port_net_after_costs,
        "cagr_netto": _cagr(port_net_after_costs, PERIODS_PER_YEAR),
        "sharpe_netto": _sharpe(port_net_after_costs, periods_per_year=PERIODS_PER_YEAR),
        "maxdd_netto": _max_drawdown(port_net_after_costs),
        "avg_gross_exposure": weights_df.sum(axis=1).mean(),
    }


def main():
    sector_of = json.load(open(SECTOR_MAP_FILE))

    print(f"{'Config':<34}{'CAGR netto':>12}{'Sharpe netto':>14}{'MaxDD netto':>13}{'Calmar':>9}{'Espos. media':>13}")
    results = {}
    for label, bw, vt in GRID:
        r = run_backtest(bw, vt, sector_of)
        calmar = r["cagr_netto"] / abs(r["maxdd_netto"]) if r["maxdd_netto"] != 0 else float("nan")
        results[label] = r
        print(f"{label:<34}{r['cagr_netto']*100:>11.2f}%{r['sharpe_netto']:>14.2f}{r['maxdd_netto']*100:>12.2f}%{calmar:>9.2f}"
              f"{r['avg_gross_exposure']*100:>12.1f}%")

    variant_order = [label for label, _, _ in GRID]
    perf_matrix = np.column_stack([results[m]["net"].values for m in variant_order])
    n_splits = 8
    usable_len = (len(perf_matrix) // n_splits) * n_splits
    pbo = pbo_cscv(perf_matrix[-usable_len:], n_splits=n_splits)
    print(f"\nPBO-CSCV su {len(variant_order)} combinazioni base_weight/vol_target: {pbo*100:.1f}% "
          "(vicino al 50% = nessuna combinazione batte le altre in modo robusto)")

    best_label = max(variant_order, key=lambda m: results[m]["sharpe_netto"])
    best_net = results[best_label]["net"]
    dsr = deflated_sharpe_ratio(results[best_label]["sharpe_netto"], n_trials=len(variant_order), n_obs=len(best_net))
    lo, hi = block_bootstrap_ci(best_net.values, lambda r: _sharpe(pd.Series(r), periods_per_year=PERIODS_PER_YEAR),
                                 block_size=12, ci=0.90, seed=42)
    current_label = "Attuale (50%/22%, Percorso B)"
    print(f"\nMigliore per Sharpe netto: {best_label} (Sharpe {results[best_label]['sharpe_netto']:.2f} vs "
          f"{results[current_label]['sharpe_netto']:.2f} dell'attuale)")
    print(f"  DSR (n_trials={len(variant_order)}, conteggio reale): {dsr:.4f}")
    print(f"  CI 90% Sharpe (block bootstrap): [{lo:.2f}, {hi:.2f}]")


if __name__ == "__main__":
    main()
