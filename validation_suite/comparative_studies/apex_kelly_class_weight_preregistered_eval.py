"""
apex_kelly_class_weight_preregistered_eval.py — Valutazione diretta della
CONFIGURAZIONE FISSA pre-registrata (finestra mu/Sigma 208 settimane,
frazione Kelly 0.25 — la scelta raccomandata dopo i due giri di verifica
in apex_kelly_class_weight_test.py e apex_kelly_class_weight_second_round_test.py).

Perche' questo script e non solo rileggere i log precedenti: il numero
"OOS" riportato nel secondo giro (Sharpe 1.14 vs 1.00) e' quello del
WALK-FORWARD che cambia combinazione ogni era (era 2 ha usato 104/0.5,
non 208/0.25) — utile per validare il MECCANISMO in generale, ma diverso
dalla domanda "se avessi fissato ESATTAMENTE 208/0.25 dall'inizio e non
l'avessi mai piu' toccato, come si sarebbe comportato nel periodo che
l'analisi non ha usato per scegliere i parametri?" — la domanda
rilevante per decidere se DEPLOYARE questa regola fissa in produzione.
Qui isoliamo quella singola combinazione fissa e la confrontiamo con la
baseline attuale (equal-weight) SOLO sul periodo successivo alla prima
era (che sarebbe stata usata per la scelta dei parametri in un vero
deployment pre-registrato).
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "validation_suite" / "framework"))

from metrics import cagr as _cagr, sharpe as _sharpe, max_drawdown as _max_drawdown, calmar as _calmar
from statistical_validation import block_bootstrap_ci
from apex_stocks_vs_etf_backtest import PERIODS_PER_YEAR
from sector_cap_grid_test import SECTOR_MAP_FILE
from apex_kelly_class_weight_second_round_test import (
    precompute_trend_and_basket, compute_f_star_hist, run_variant, N_ERAS,
)

WINDOW = 208
FRAC = 0.25


def main():
    sector_of = json.load(open(SECTOR_MAP_FILE))
    print("[*] Precalcolo condiviso (identico ai due giri precedenti)...")
    shared = precompute_trend_and_basket(sector_of)

    print(f"[*] Backtest configurazione pre-registrata (finestra={WINDOW}, frac={FRAC}) e controllo (frac=0.0)...")
    f_star_hist = compute_f_star_hist(shared, WINDOW)
    net_kelly = run_variant(shared, f_star_hist, FRAC)
    net_baseline = run_variant(shared, f_star_hist, 0.0)

    common_idx = net_kelly.index.intersection(net_baseline.index).sort_values()
    net_kelly = net_kelly.reindex(common_idx)
    net_baseline = net_baseline.reindex(common_idx)

    era_len = len(common_idx) // N_ERAS
    era1_end = common_idx[era_len - 1]
    oos_idx = common_idx[era_len:]  # ere 2-5: il periodo che un deployment pre-registrato dopo l'era 1 non avrebbe ancora visto

    print(f"\nCampione totale: {common_idx.min().date()} -> {common_idx.max().date()} ({len(common_idx)} sett.)")
    print(f"Era 1 (avrebbe informato la scelta dei parametri): fino a {era1_end.date()}")
    print(f"Periodo OOS valutato qui (ere 2-5): {oos_idx.min().date()} -> {oos_idx.max().date()} ({len(oos_idx)} sett.)")

    print(f"\n{'Periodo':<12}{'Variante':<28}{'CAGR':>10}{'Sharpe':>9}{'MaxDD':>9}{'Calmar':>9}")
    for period_label, idx in [("Full-sample", common_idx), ("OOS (ere 2-5)", oos_idx)]:
        for label, net in [("Apex attuale (equal-weight)", net_baseline), (f"Apex + Kelly ({WINDOW}sett/frac{FRAC})", net_kelly)]:
            sub = net.reindex(idx).dropna()
            c, s, dd = _cagr(sub, PERIODS_PER_YEAR), _sharpe(sub, periods_per_year=PERIODS_PER_YEAR), _max_drawdown(sub)
            cal = _calmar(sub, PERIODS_PER_YEAR)
            print(f"{period_label:<12}{label:<28}{c*100:>9.2f}%{s:>9.2f}{dd*100:>8.2f}%{cal:>9.2f}")

    diff_oos = (net_kelly.reindex(oos_idx) - net_baseline.reindex(oos_idx)).dropna()
    mean_diff = diff_oos.mean() * PERIODS_PER_YEAR * 100
    lo, hi = block_bootstrap_ci(diff_oos.values, lambda r: pd.Series(r).mean() * PERIODS_PER_YEAR * 100, block_size=12, ci=0.90, seed=42)
    n_better = int((diff_oos > 0).sum())
    print(f"\nConfronto accoppiato diretto, SOLO OOS (ere 2-5), configurazione fissa {WINDOW}/{FRAC} (non walk-forward):")
    print(f"  Overperformance media: {mean_diff:+.2f}pp/anno, CI 90% [{lo:+.2f}, {hi:+.2f}]pp/anno "
          f"({'ESCLUDE' if lo * hi > 0 else 'include'} lo zero)")
    print(f"  Settimane in cui Kelly ha fatto meglio: {n_better}/{len(diff_oos)} ({n_better/len(diff_oos)*100:.0f}%)")


if __name__ == "__main__":
    main()
