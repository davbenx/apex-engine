"""
apex_kelly_vs_flat_bootstrap_robustness.py — Robustezza del CI bootstrap sul
confronto Kelly (sistema ATTUALE) vs sistema PRECEDENTE
(apex_kelly_vs_flat_v2_comparison.py), richiesta dall'utente dopo che il
fix del survivorship bias ha fatto perdere significativita' al CI90 sul
CAGR (era [-0.78, +8.51], includeva lo zero, con block_size=12 fisso).

Il CI originale usava un SOLO block_size (12 mesi), una scelta arbitraria
(researcher degree of freedom): se la conclusione ("non significativo")
dipendesse da quella scelta specifica, sarebbe un artefatto, non un
risultato robusto. Qui si ripete il bootstrap su piu' block_size (3/6/12/24
mesi) E su piu' metriche (non solo CAGR, anche Sharpe — la metrica su cui
la tesi "risk-adjusted e' comunque migliore" si appoggia).

Differenza dal bootstrap originale: qui il resampling e' APPAIATO — stessi
indici temporali ricampionati per ENTRAMBI i sistemi nello stesso draw —
cosi' si preserva la correlazione tra le due serie (stesso mese buono/
cattivo di mercato per entrambe), non solo l'autocorrelazione di ciascuna.
Il bootstrap originale (block_bootstrap_ci) resample solo la serie DIFF
gia' calcolata, che e' equivalente per una metrica lineare come la media
(CAGR-diff approssimato) ma non per una metrica non lineare come lo Sharpe
di ciascun ramo — da cui la necessita' di una versione paired qui.
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

from apex_dashboard_stat_regeneration import run_full_backtest, to_monthly, SLICE_END
from sector_cap_grid_test import SECTOR_MAP_FILE
from metrics import cagr as _cagr, sharpe as _sharpe, max_drawdown as _max_drawdown, calmar as _calmar

TEST_START = "2020-09-30"
OUT_DIR = Path(__file__).parent / "apex_sensitivity_series"
OUT_DIR.mkdir(exist_ok=True)

BLOCK_SIZES = [3, 6, 12, 24]
N_BOOTSTRAP = 3000
CI = 0.90


def paired_block_bootstrap_diff(old_arr: np.ndarray, new_arr: np.ndarray, metric_fn,
                                 n_bootstrap: int, block_size: int, ci: float, seed: int = 42):
    """Bootstrap a blocchi mobili (Moving Block Bootstrap) APPAIATO: ogni
    draw ricampiona gli STESSI indici temporali per vecchio e nuovo sistema,
    poi calcola metric_fn su ciascun ramo e la differenza (nuovo - vecchio).
    Preserva sia l'autocorrelazione di ciascuna serie sia la correlazione
    incrociata tra le due (stesso regime di mercato in ogni draw)."""
    rng = np.random.default_rng(seed)
    n = len(old_arr)
    n_blocks = int(np.ceil(n / block_size))
    diffs = []
    for _ in range(n_bootstrap):
        block_starts = rng.integers(0, n - block_size + 1, size=n_blocks)
        idx = np.concatenate([np.arange(s, s + block_size) for s in block_starts])[:n]
        diffs.append(metric_fn(new_arr[idx]) - metric_fn(old_arr[idx]))
    diffs = np.array(diffs)
    alpha = (1 - ci) / 2
    lo, hi = np.percentile(diffs, [alpha * 100, (1 - alpha) * 100])
    return float(lo), float(hi), float(diffs.mean())


def cagr_pct(r):
    return _cagr(pd.Series(r), periods_per_year=12) * 100


def sharpe_metric(r):
    return _sharpe(pd.Series(r), periods_per_year=12)


def main():
    sector_of = json.load(open(SECTOR_MAP_FILE))

    print("[*] Backtest sistema PRECEDENTE (kelly_fraction=0.0)...")
    gross_w_old, _ = run_full_backtest(sector_of, kelly_fraction=0.0)
    gross_m_old = to_monthly(gross_w_old).loc[:SLICE_END]

    print("[*] Backtest sistema ATTUALE (kelly_fraction=produzione)...")
    gross_w_new, _ = run_full_backtest(sector_of, kelly_fraction=None)
    gross_m_new = to_monthly(gross_w_new).loc[:SLICE_END]

    gross_m_old.to_csv(OUT_DIR / "kelly_vs_flat_gross_old.csv", header=["ret"])
    gross_m_new.to_csv(OUT_DIR / "kelly_vs_flat_gross_new.csv", header=["ret"])

    windows = {
        f"TEST walk-forward ({TEST_START} -> {SLICE_END})": (gross_m_old.loc[TEST_START:], gross_m_new.loc[TEST_START:]),
        f"Intero storico ({gross_m_old.index.min().date()} -> {SLICE_END})": (gross_m_old, gross_m_new),
    }

    for label, (old_s, new_s) in windows.items():
        old_arr = old_s.values
        new_arr = new_s.values
        n = len(old_arr)
        print("\n" + "=" * 92)
        print(f"{label} — n={n} mesi — bootstrap appaiato, {N_BOOTSTRAP} draw per block_size")
        print("=" * 92)

        for metric_name, metric_fn, unit in [("CAGR", cagr_pct, "pp/anno"), ("Sharpe", sharpe_metric, "")]:
            print(f"\n  Metrica: {metric_name}")
            print(f"  {'block_size':>12}{'diff media':>14}{'CI90 lower':>14}{'CI90 upper':>14}{'esclude 0?':>12}")
            for bs in BLOCK_SIZES:
                if bs >= n:
                    continue
                lo, hi, mean_d = paired_block_bootstrap_diff(old_arr, new_arr, metric_fn,
                                                               N_BOOTSTRAP, bs, CI, seed=42)
                excludes_zero = "SI" if lo * hi > 0 else "no"
                unit_str = f"{unit}" if unit else ""
                print(f"  {bs:>10}m {mean_d:>+11.3f}{unit_str} {lo:>+11.3f}{unit_str} {hi:>+11.3f}{unit_str} {excludes_zero:>12}")

    print("\n" + "=" * 92)
    print("Nota: se la colonna 'esclude 0?' cambia tra i block_size (es. SI a 3, no a 24), la")
    print("conclusione di significativita' e' sensibile alla scelta arbitraria di block_size —")
    print("va riportata come fragile/dipendente dal metodo, non come fatto stabilito.")
    print("=" * 92)


if __name__ == "__main__":
    main()
