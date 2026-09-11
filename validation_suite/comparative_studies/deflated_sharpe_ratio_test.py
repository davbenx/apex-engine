"""
deflated_sharpe_ratio_test.py — Estende il Deflated Sharpe Ratio (Bailey &
Lopez de Prado 2014) gia' applicato SOLO ad Apex in
validation_suite/core_regression/test_apex_v2_institutional_validation.py
anche a Convex e al Combinato 70/30 — richiesto come parte del test di
robustezza/invalidazione istituzionale completo su Apex+Convex. Riusa
statistical_validation.deflated_sharpe_ratio (nessuna dipendenza scipy,
stesso principio del resto del repository — vedi quel modulo).

N_trials: nessun conteggio esatto esiste (63 script distinti in
validation_suite/comparative_studies/ al momento di questo giro, molti con
piu' varianti/griglie al loro interno — non un numero univoco). Riportato
su un range placheggiato (20/50/100/200/315) invece di un singolo numero
finto-preciso, stessa scelta onesta del test esistente su Apex.
"""
from __future__ import annotations
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "validation_suite" / "framework"))

import portfolio_manager
from statistical_validation import deflated_sharpe_ratio
from metrics import sharpe as _sharpe

TEST_START = "2020-09-30"
N_TRIALS_GRID = [20, 50, 100, 200, 315]


def main():
    apex = pd.read_csv(REPO_ROOT / "apex_monthly_returns_extended_gross.csv", index_col=0, parse_dates=True).iloc[:, 0]
    convex = pd.read_csv(REPO_ROOT / "convex_monthly_returns.csv", index_col=0, parse_dates=True).iloc[:, 0]
    df_comb = portfolio_manager.load_combined_monthly_history(0.70, 0.30)
    combined = df_comb["return"]

    series = {
        "Apex — intero storico (471m)": apex,
        "Apex — TEST (72m)": apex.loc[TEST_START:],
        "Convex — intero storico (465m)": convex,
        "Convex — TEST (72m)": convex.loc[TEST_START:],
        "Combinato 70/30 — intero storico (465m)": combined,
        "Combinato 70/30 — TEST (72m)": combined.loc[TEST_START:],
    }

    print("=" * 100)
    print("DEFLATED SHARPE RATIO — Apex, Convex, Combinato (estende il test esistente solo su Apex)")
    print("=" * 100)
    header = f"{'Serie':<40}{'n':>5}{'SR':>8}{'skew':>8}{'kurt':>7}"
    for n in N_TRIALS_GRID:
        header += f"{'N='+str(n):>8}"
    print(header)

    for label, ret in series.items():
        n_obs = len(ret)
        sr = _sharpe(ret, periods_per_year=12)
        skew = float(ret.skew())
        kurt = float(ret.kurt()) + 3.0  # pandas .kurt() e' in eccesso (normale=0); la funzione vuole normale=3
        row = f"{label:<40}{n_obs:>5}{sr:>8.3f}{skew:>+8.3f}{kurt:>7.2f}"
        for n_trials in N_TRIALS_GRID:
            dsr = deflated_sharpe_ratio(sr, n_trials=n_trials, n_obs=n_obs, skew=skew, kurtosis=kurt)
            row += f"{dsr:>8.3f}"
        print(row)

    print("\nInterpretazione: DSR > 0.95 = Sharpe realizzato statisticamente superiore al 95-esimo")
    print("percentile del massimo atteso per puro caso dato N prove. DSR ~ 0.5 = indistinguibile dal rumore.")
    print("DSR < 0.5 = l'edge osservato e' PEGGIORE di quanto ci si aspetterebbe dal solo processo di selezione.")


if __name__ == "__main__":
    main()
