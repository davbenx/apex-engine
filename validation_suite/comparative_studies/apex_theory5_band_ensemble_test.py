"""
apex_theory5_band_ensemble_test.py — Quinto giro di verifica sulla Teoria
#5, richiesto direttamente dall'utente ("procedi" sull'idea di isolare e
verificare la banda 22-33 settimane invece di trattarla come parte della
griglia piu' ampia di 9 punti, dove il rischio di data-snooping nel
selezionare post-hoc "i 3 migliori" e' reale).

Approccio diverso dal quarto giro (media del CRITERIO beta su piu'
finestre, che ha DILUITO il segnale): qui si costruisce un ENSEMBLE dei
RISULTATI — 6 basket indipendenti selezionati ciascuno con il proprio
lookback nella banda interna (22/24/26/28/30/33 settimane, quella che nella
griglia fine del terzo giro mostrava il vantaggio piu' consistente), poi
si media la SERIE DI RENDIMENTO netta risultante dei 6 portafogli — un
"fondo di fondi" che preserva la selezione titoli distinta di ciascun
lookback invece di appiattirla in un unico criterio di ranking medio prima
della selezione.

Due test statistici mirati, scoped SOLO su questa banda (non sulla griglia
intera di 9 punti, per non riprodurre lo stesso rischio di selezione
post-hoc gia' segnalato):
  1. PBO-CSCV su {baseline, i 6 lookback della banda, l'ensemble} — 8
     configurazioni, non 9+.
  2. Confronto accoppiato diretto + train/test split dell'ENSEMBLE contro
     il baseline di produzione — il test di significativita' congiunta
     piu' pulito per "la banda nel suo insieme e' un effetto reale?".

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
from statistical_validation import deflated_sharpe_ratio, pbo_cscv, block_bootstrap_ci
from apex_stocks_vs_etf_backtest import (
    DATA_DIR, PERIODS_PER_YEAR, load_weekly_macro, load_weekly_sp500, load_pointintime_snapshots,
)
from sector_cap_grid_test import SECTOR_MAP_FILE
from apex_theory5_lookback_finegrid_test import compute_macro_signal_history, run_basket_variant

BAND = [22, 24, 26, 28, 30, 33]


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

    print("[*] Baseline produzione (low-vol, lookback=26)...")
    baseline = run_basket_variant(26, False, macro_alloc_history, macro_prices, weeks, n,
                                   stock_prices, stock_rets, snapshots, sector_of)

    print(f"{'Lookback (low-beta)':<22}{'CAGR netto':>12}{'Sharpe netto':>14}{'MaxDD netto':>13}")
    band_results = {}
    for lb in BAND:
        r = run_basket_variant(lb, True, macro_alloc_history, macro_prices, weeks, n,
                                stock_prices, stock_rets, snapshots, sector_of)
        band_results[lb] = r
        print(f"{lb:<22}{r['cagr_netto']*100:>11.2f}%{r['sharpe_netto']:>14.2f}{r['maxdd_netto']*100:>12.2f}%")

    # Ensemble: media della SERIE DI RENDIMENTO netta dei 6 portafogli (ciascuno con la propria
    # selezione titoli indipendente per lookback) — un "fondo di fondi", non una media del
    # criterio di ranking prima della selezione (quello e' il quarto giro, che ha diluito il segnale).
    common_idx = band_results[BAND[0]]["net"].index
    for lb in BAND[1:]:
        common_idx = common_idx.intersection(band_results[lb]["net"].index)
    ensemble_net = pd.concat([band_results[lb]["net"].reindex(common_idx) for lb in BAND], axis=1).mean(axis=1)
    ensemble_cagr = _cagr(ensemble_net, PERIODS_PER_YEAR)
    ensemble_sharpe = _sharpe(ensemble_net, periods_per_year=PERIODS_PER_YEAR)
    ensemble_maxdd = _max_drawdown(ensemble_net)
    print(f"\n{'ENSEMBLE (media dei 6 portafogli)':<22}{ensemble_cagr*100:>11.2f}%{ensemble_sharpe:>14.2f}{ensemble_maxdd*100:>12.2f}%")
    print(f"{'Baseline produzione':<22}{baseline['cagr_netto']*100:>11.2f}%{baseline['sharpe_netto']:>14.2f}{baseline['maxdd_netto']*100:>12.2f}%")

    diff = (ensemble_net.reindex(common_idx) - baseline["net"].reindex(common_idx)).dropna()
    mean_diff = diff.mean() * PERIODS_PER_YEAR * 100
    lo, hi = block_bootstrap_ci(diff.values, lambda r: pd.Series(r).mean() * PERIODS_PER_YEAR * 100,
                                 block_size=12, ci=0.90, seed=42)
    n_better = int((diff > 0).sum())
    print(f"\nConfronto accoppiato diretto (ensemble meno baseline produzione):")
    print(f"  Overperformance media: {mean_diff:+.2f}pp/anno, CI 90% [{lo:+.2f}, {hi:+.2f}]pp/anno "
          f"({'ESCLUDE' if lo * hi > 0 else 'INCLUDE'} lo zero)")
    print(f"  Settimane in cui l'ensemble ha fatto meglio: {n_better}/{len(diff)} ({n_better/len(diff)*100:.0f}%)")

    dsr = deflated_sharpe_ratio(ensemble_sharpe, n_trials=len(BAND) + 2, n_obs=len(ensemble_net))
    print(f"  DSR ensemble (n_trials={len(BAND)+2}, conta baseline+banda+ensemble): {dsr:.4f}")

    variant_order = ["baseline"] + [f"lb{lb}" for lb in BAND] + ["ensemble"]
    series_map = {"baseline": baseline["net"], "ensemble": ensemble_net, **{f"lb{lb}": band_results[lb]["net"] for lb in BAND}}
    common_stat_index = series_map["baseline"].index
    for v in variant_order[1:]:
        common_stat_index = common_stat_index.intersection(series_map[v].index)
    perf_matrix = np.column_stack([series_map[v].reindex(common_stat_index).values for v in variant_order])
    n_splits = 8
    usable_len = (len(perf_matrix) // n_splits) * n_splits
    pbo = pbo_cscv(perf_matrix[-usable_len:], n_splits=n_splits)
    print(f"\nPBO-CSCV su {len(variant_order)} configurazioni (baseline + banda 22-33 + ensemble): {pbo*100:.1f}%")

    print("\n--- TRAIN/TEST split (prima meta' vs seconda meta', Sharpe per meta') ---")
    for label, net in [("Baseline produzione", baseline["net"]), ("Ensemble (banda 22-33)", ensemble_net)]:
        mid = len(net) // 2
        s1 = _sharpe(net.iloc[:mid], periods_per_year=PERIODS_PER_YEAR)
        s2 = _sharpe(net.iloc[mid:], periods_per_year=PERIODS_PER_YEAR)
        print(f"  {label:<28} 1a meta': {s1:>6.2f}   2a meta': {s2:>6.2f}")


if __name__ == "__main__":
    main()
