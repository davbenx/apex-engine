"""
apex_theory5_walkforward_selection_test.py — Gap #1 della checklist di
produzione per la Teoria #5, richiesto direttamente dall'utente ("procedi
punto per punto"): la banda 22-33 settimane e' stata IDENTIFICATA usando
l'intero campione di 586 settimane (griglia fine, terzo giro) e poi
TESTATA sullo stesso campione — un rischio di look-ahead nella SELEZIONE
del parametro, distinto da qualunque intervallo di confidenza calcolato
dopo. Un vero walk-forward sceglie il lookback usando SOLO dati passati,
poi lo applica su dati MAI visti prima di quella scelta.

Disegno: il campione utile (~546 settimane, dal termine del warmup) e'
diviso in 4 ere non sovrapposte consecutive (~136 settimane, ~2.6 anni
ciascuna). L'era 1 e' SOLO training iniziale (nessuna valutazione). Per
ciascuna era successiva (2, 3, 4), si sceglie il lookback con lo Sharpe
migliore calcolato SOLO sulle ere precedenti (finestra espandibile, non
solo l'era immediatamente precedente — piu' realistico di come si
selezionerebbe un parametro in produzione), poi si valuta quella scelta
SOLO sull'era corrente (mai vista prima della selezione). Le ere 2+3+4
out-of-sample vengono concatenate nel risultato finale.

Confronto: (a) selezione walk-forward adattiva, (b) lookback fisso a
26 settimane (il valore di produzione, scelto a priori senza guardare
i dati), (c) baseline attuale (basket low-vol), tutti sulla STESSA
finestra out-of-sample (ere 2+3+4) per un confronto onesto.

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

LOOKBACK_GRID = [16, 20, 22, 24, 26, 28, 30, 33, 39]
N_ERAS = 4


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

    print("[*] Backtest baseline (low-vol, produzione)...")
    baseline = run_basket_variant(26, False, macro_alloc_history, macro_prices, weeks, n,
                                   stock_prices, stock_rets, snapshots, sector_of)

    print(f"[*] Backtest dei {len(LOOKBACK_GRID)} candidati low-beta (una sola volta ciascuno, poi affettati per era)...")
    lb_results = {}
    for lb in LOOKBACK_GRID:
        lb_results[lb] = run_basket_variant(lb, True, macro_alloc_history, macro_prices, weeks, n,
                                             stock_prices, stock_rets, snapshots, sector_of)
        print(f"    lookback={lb} fatto")

    common_idx = baseline["net"].index
    for lb in LOOKBACK_GRID:
        common_idx = common_idx.intersection(lb_results[lb]["net"].index)
    common_idx = common_idx.sort_values()

    era_len = len(common_idx) // N_ERAS
    eras = [common_idx[i * era_len:(i + 1) * era_len] for i in range(N_ERAS - 1)]
    eras.append(common_idx[(N_ERAS - 1) * era_len:])  # ultima era prende il resto

    print(f"\nEre: {[(e.min().date(), e.max().date(), len(e)) for e in eras]}\n")

    wf_segments = []
    fixed26_segments = []
    print(f"{'Era':<8}{'Selezionato (su ere precedenti)':>34}{'Sharpe selezione':>18}")
    for i in range(1, N_ERAS):
        past_idx = common_idx[:i * era_len]
        sharpes_past = {lb: _sharpe(lb_results[lb]["net"].reindex(past_idx).dropna(), periods_per_year=PERIODS_PER_YEAR)
                         for lb in LOOKBACK_GRID}
        best_lb = max(sharpes_past, key=sharpes_past.get)
        print(f"Era {i+1:<5}{best_lb:>34}{sharpes_past[best_lb]:>18.2f}")

        wf_segments.append(lb_results[best_lb]["net"].reindex(eras[i]).dropna())
        fixed26_segments.append(lb_results[26]["net"].reindex(eras[i]).dropna())

    wf_net = pd.concat(wf_segments).sort_index()
    fixed26_net = pd.concat(fixed26_segments).sort_index()
    baseline_oos = baseline["net"].reindex(wf_net.index).dropna()
    wf_net = wf_net.reindex(baseline_oos.index)
    fixed26_net = fixed26_net.reindex(baseline_oos.index)

    print(f"\n--- Risultati OUT-OF-SAMPLE (ere 2+3+4, {len(baseline_oos)} settimane, "
          f"{baseline_oos.index.min().date()} -> {baseline_oos.index.max().date()}) ---")
    print(f"{'Variante':<45}{'CAGR netto':>12}{'Sharpe netto':>14}{'MaxDD netto':>13}")
    for label, net in [("Baseline produzione (low-vol)", baseline_oos),
                        ("Low-beta fisso a 26 sett. (a priori)", fixed26_net),
                        ("Low-beta walk-forward (adattivo)", wf_net)]:
        calmar = _cagr(net, PERIODS_PER_YEAR) / abs(_max_drawdown(net)) if _max_drawdown(net) != 0 else float("nan")
        print(f"{label:<45}{_cagr(net, PERIODS_PER_YEAR)*100:>11.2f}%{_sharpe(net, periods_per_year=PERIODS_PER_YEAR):>14.2f}"
              f"{_max_drawdown(net)*100:>12.2f}%")

    for label, net in [("Low-beta fisso a 26 sett.", fixed26_net), ("Low-beta walk-forward", wf_net)]:
        diff = (net - baseline_oos).dropna()
        mean_diff = diff.mean() * PERIODS_PER_YEAR * 100
        lo, hi = block_bootstrap_ci(diff.values, lambda r: pd.Series(r).mean() * PERIODS_PER_YEAR * 100,
                                     block_size=12, ci=0.90, seed=42)
        n_better = int((diff > 0).sum())
        print(f"\n{label} meno baseline (solo OOS):")
        print(f"  Overperformance media: {mean_diff:+.2f}pp/anno, CI 90% [{lo:+.2f}, {hi:+.2f}]pp/anno "
              f"({'ESCLUDE' if lo * hi > 0 else 'INCLUDE'} lo zero)")
        print(f"  Settimane in cui ha fatto meglio: {n_better}/{len(diff)} ({n_better/len(diff)*100:.0f}%)")


if __name__ == "__main__":
    main()
