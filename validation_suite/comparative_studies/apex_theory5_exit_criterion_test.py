"""
apex_theory5_exit_criterion_test.py — Gap #7 della checklist di produzione
per la Teoria #5, richiesto direttamente dall'utente ("bisogna testare i
criteri di uscita e confrontarli con quelli attuali"): se si adotta
low-beta, serve un criterio esplicito per capire QUANDO tornare a low-vol
se in futuro smette di funzionare — non solo la decisione di entrata.

Criterio testato: monitoraggio dello Sharpe ROLLING a 104 settimane (2
anni, stessa finestra gia' usata nei giri precedenti) di low-beta contro
low-vol, controllato ogni 13 settimane (trimestrale, allineato al
ribilanciamento del basket — evita di reagire a rumore settimana per
settimana). Se lo Sharpe rolling di low-beta scende sotto quello di
low-vol, si passa a low-vol fino al prossimo controllo in cui low-beta
torna sopra (regola REVERSIBILE, non un abbandono permanente). Ogni
cambio di basket paga un costo di transazione realistico: la
sovrapposizione titoli tra i due basket e' solo ~6.9% (misurata in
apex_theory5_composition_turnover_test.py), quindi un cambio costa
quanto un ricostituzione quasi completa del basket, non un aggiustamento
marginale.

Confronto: (a) sempre low-vol, (b) sempre low-beta, (c) switching
adattivo con il criterio sopra — sulla stessa finestra (dopo il warmup
del monitoraggio, le prime 104 settimane utili).

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
from apex_v2_engine import V2_CLASS_TICKER
from metrics import cagr as _cagr, sharpe as _sharpe, max_drawdown as _max_drawdown
from statistical_validation import block_bootstrap_ci
from apex_stocks_vs_etf_backtest import (
    DATA_DIR, PERIODS_PER_YEAR, load_weekly_macro, load_weekly_sp500, load_pointintime_snapshots,
)
from sector_cap_grid_test import SECTOR_MAP_FILE
from apex_theory5_lookback_finegrid_test import compute_macro_signal_history, run_basket_variant

MONITOR_WINDOW = 104  # settimane, stessa finestra dei giri precedenti
CHECK_EVERY = 13      # settimane, trimestrale
SWITCH_COST = 0.0090  # costo di transazione di un cambio quasi-completo di basket (15 titoli, ~0.10%/titolo x ~90% sovrapposizione mancante)


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

    print("[*] Calcolo il segnale macro (condiviso)...")
    macro_alloc_history = compute_macro_signal_history(macro_prices, weeks)

    print("[*] Backtest low-vol (produzione)...")
    lowvol = run_basket_variant(26, False, macro_alloc_history, macro_prices, weeks, n,
                                 stock_prices, stock_rets, snapshots, sector_of)
    print("[*] Backtest low-beta (lookback=26)...")
    lowbeta = run_basket_variant(26, True, macro_alloc_history, macro_prices, weeks, n,
                                  stock_prices, stock_rets, snapshots, sector_of)

    common_idx = lowvol["net"].index.intersection(lowbeta["net"].index).sort_values()
    net_lv = lowvol["net"].reindex(common_idx)
    net_lb = lowbeta["net"].reindex(common_idx)

    # Regola di switching: dal punto MONITOR_WINDOW in poi, controllata ogni CHECK_EVERY
    # settimane, usando SOLO dati fino al controllo corrente (nessun lookahead).
    current_choice = "low_beta"  # default di partenza: la scelta decisa
    choice_history = []
    switch_weeks = []
    for i in range(len(common_idx)):
        if i < MONITOR_WINDOW:
            choice_history.append(current_choice)
            continue
        if (i - MONITOR_WINDOW) % CHECK_EVERY == 0:
            window_lv = net_lv.iloc[i - MONITOR_WINDOW:i]
            window_lb = net_lb.iloc[i - MONITOR_WINDOW:i]
            sharpe_lv = _sharpe(window_lv, periods_per_year=PERIODS_PER_YEAR)
            sharpe_lb = _sharpe(window_lb, periods_per_year=PERIODS_PER_YEAR)
            new_choice = "low_beta" if sharpe_lb >= sharpe_lv else "low_vol"
            if new_choice != current_choice:
                switch_weeks.append((common_idx[i], current_choice, new_choice))
            current_choice = new_choice
        choice_history.append(current_choice)

    choice_series = pd.Series(choice_history, index=common_idx)
    adaptive_net = pd.Series(
        np.where(choice_series.values == "low_beta", net_lb.values, net_lv.values), index=common_idx,
    )
    switch_mask = choice_series != choice_series.shift(1)
    switch_mask.iloc[:MONITOR_WINDOW] = False
    adaptive_net = adaptive_net - switch_mask.astype(float) * SWITCH_COST

    oos_idx = common_idx[MONITOR_WINDOW:]
    print(f"\n--- Confronto sulla finestra monitorata ({len(oos_idx)} settimane, "
          f"{oos_idx.min().date()} -> {oos_idx.max().date()}) ---")
    print(f"{'Variante':<30}{'CAGR netto':>12}{'Sharpe netto':>14}{'MaxDD netto':>13}")
    for label, net in [("Sempre low-vol", net_lv.reindex(oos_idx)),
                        ("Sempre low-beta", net_lb.reindex(oos_idx)),
                        ("Switching adattivo", adaptive_net.reindex(oos_idx))]:
        print(f"{label:<30}{_cagr(net, PERIODS_PER_YEAR)*100:>11.2f}%{_sharpe(net, periods_per_year=PERIODS_PER_YEAR):>14.2f}"
              f"{_max_drawdown(net)*100:>12.2f}%")

    print(f"\nCambi di basket nella finestra monitorata: {len(switch_weeks)}")
    for wk, frm, to in switch_weeks:
        print(f"  {wk.date()}: {frm} -> {to}")

    for label, net in [("Sempre low-beta", net_lb.reindex(oos_idx)), ("Switching adattivo", adaptive_net.reindex(oos_idx))]:
        diff = (net - net_lv.reindex(oos_idx)).dropna()
        mean_diff = diff.mean() * PERIODS_PER_YEAR * 100
        lo, hi = block_bootstrap_ci(diff.values, lambda r: pd.Series(r).mean() * PERIODS_PER_YEAR * 100,
                                     block_size=12, ci=0.90, seed=42)
        print(f"\n{label} meno sempre-low-vol:")
        print(f"  Overperformance media: {mean_diff:+.2f}pp/anno, CI 90% [{lo:+.2f}, {hi:+.2f}]pp/anno "
              f"({'ESCLUDE' if lo * hi > 0 else 'INCLUDE'} lo zero)")


if __name__ == "__main__":
    main()
