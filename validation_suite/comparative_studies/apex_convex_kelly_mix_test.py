"""
apex_convex_kelly_mix_test.py — Idea "Kelly tra Apex e Convex stessi",
richiesta diretta dall'utente dopo il controllo di calibrazione della
leva di Convex (README, "Ricalibrazione Kelly della leva di Convex").
Kelly Stack (KELLY_STACK_SPEC.md) ha gia' applicato pesi Kelly ALLE
SLEEVE INTERNE di Convex in modo esaustivo (8 round di risultati, 20+
varianti) — non ripetuto qui. Mai testato: il MIX tra i due motori
INTERI (oggi 50/50 di default in home_app.py/portfolio_manager.py).

Calcolo diretto, nessun backtest: usa le stesse due serie reali gia'
dietro le cifre di dashboard (apex_monthly_returns_extended_gross.csv,
471 mesi dal 1987-06 dopo l'estensione storica; convex_monthly_returns.csv,
312 mesi dal 2000-09, gia' lorda per costruzione).

Due risultati distinti, entrambi riportati:
1. Kelly PIENO non vincolato (f*=Sigma^-1 mu) — puo' implicare leva
   combinata >100% o un peso negativo, entrambi non direttamente
   implementabili con un semplice mix percentuale tra due prodotti gia'
   esistenti (nessuno dei due permette una posizione corta sull'altro).
2. Kelly vincolato al simplesso (w_apex + w_convex = 1, entrambi >= 0) —
   il problema realmente rilevante per la decisione "che percentuale del
   capitale in ciascuno dei due motori", senza aggiungere leva ulteriore
   oltre quella gia' imbottita in ciascun motore. Massimizzato via
   approssimazione del secondo ordine alla crescita geometrica attesa
   (stesso risultato standard di Merton usato in KELLY_STACK_SPEC.md §2),
   verificato con una grid search fine come controllo indipendente.

Stesso avvertimento di onesta' statistica gia' dato per la leva di
Convex: Kelly pieno e' estremamente sensibile all'errore di stima di mu,
qui ancora di piu' con un solo grado di liberta' effettivo (2 asset) e
una finestra comune piu' corta della storia intera di Apex.
"""

from __future__ import annotations
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "validation_suite" / "framework"))
from metrics import cagr as _cagr, sharpe as _sharpe, max_drawdown as _max_drawdown


def geometric_growth_approx(w_apex, mu_a, mu_c, var_a, var_c, cov_ac):
    """Approssimazione al secondo ordine di E[log(1+r)] per un mix a 2
    asset senza leva aggiuntiva (w_apex + w_convex = 1) — stesso risultato
    di Merton (utilita' logaritmica, tempo continuo) usato per f*=Sigma^-1 mu,
    qui vincolato al simplesso invece che risolto in forma chiusa
    (il vincolo di uguaglianza a somma 1 rende la soluzione chiusa piu'
    scomoda del semplice Sigma^-1 mu non vincolato; una parabola in w e'
    piu' diretta e altrettanto esatta al secondo ordine)."""
    w_convex = 1.0 - w_apex
    mu_p = w_apex * mu_a + w_convex * mu_c
    var_p = (w_apex ** 2) * var_a + (w_convex ** 2) * var_c + 2 * w_apex * w_convex * cov_ac
    return mu_p - 0.5 * var_p


def main():
    apex = pd.read_csv(REPO_ROOT / "apex_monthly_returns_extended_gross.csv", index_col=0, parse_dates=True).iloc[:, 0]
    convex = pd.read_csv(REPO_ROOT / "convex_monthly_returns.csv", index_col=0, parse_dates=True).iloc[:, 0]
    common = apex.index.intersection(convex.index)
    a, c = apex.reindex(common), convex.reindex(common)
    print(f"Campione comune: {len(common)} mesi, {common.min().date()} -> {common.max().date()}")

    mu_a, mu_c = float(a.mean() * 12), float(c.mean() * 12)
    var_a, var_c = float(a.var() * 12), float(c.var() * 12)
    sigma_a, sigma_c = var_a ** 0.5, var_c ** 0.5
    rho = float(a.corr(c))
    cov_ac = rho * sigma_a * sigma_c

    print(f"\nApex:   mu={mu_a*100:.2f}%/anno  sigma={sigma_a*100:.2f}%/anno  Sharpe={_sharpe(a, periods_per_year=12):.3f}")
    print(f"Convex: mu={mu_c*100:.2f}%/anno  sigma={sigma_c*100:.2f}%/anno  Sharpe={_sharpe(c, periods_per_year=12):.3f}")
    print(f"Correlazione: {rho:.3f}")

    # --- 1. Kelly pieno non vincolato: f* = Sigma^-1 mu ---
    Sigma = np.array([[var_a, cov_ac], [cov_ac, var_c]])
    mu_vec = np.array([mu_a, mu_c])
    f_star = np.linalg.solve(Sigma, mu_vec)
    print(f"\n--- Kelly pieno NON vincolato (puo' implicare leva combinata o peso negativo) ---")
    print(f"  f*_Apex={f_star[0]*100:.1f}%  f*_Convex={f_star[1]*100:.1f}%  (somma={f_star.sum()*100:.1f}%)")
    for frac, label in [(1.0, "pieno"), (0.5, "mezzo-Kelly"), (0.25, "quarto-Kelly")]:
        print(f"  {label}: Apex={f_star[0]*frac*100:.1f}%  Convex={f_star[1]*frac*100:.1f}%")

    # --- 2. Kelly vincolato al simplesso (w_apex+w_convex=1, no leva extra) ---
    ws = np.linspace(0.0, 1.0, 10001)
    growth = np.array([geometric_growth_approx(w, mu_a, mu_c, var_a, var_c, cov_ac) for w in ws])
    best_idx = int(np.argmax(growth))
    w_best = ws[best_idx]
    print(f"\n--- Kelly vincolato al simplesso (w_Apex + w_Convex = 1, nessuna leva extra) ---")
    print(f"  Mix Kelly-ottimale: {w_best*100:.1f}% Apex / {(1-w_best)*100:.1f}% Convex")
    print(f"  Crescita attesa approssimata a questo mix: {growth[best_idx]*100:.2f}%/anno")
    g_5050 = geometric_growth_approx(0.5, mu_a, mu_c, var_a, var_c, cov_ac)
    print(f"  Crescita attesa approssimata al 50/50 attuale: {g_5050*100:.2f}%/anno")
    print(f"  Differenza (ottimo - attuale): {(growth[best_idx]-g_5050)*100:+.2f}pp/anno (SOLO differenza attesa in-sample, non un test walk-forward)")

    # --- Confronto empirico diretto: mix reali costruiti dalle serie vere ---
    print(f"\n--- Confronto empirico diretto (serie reali, non solo approssimazione) ---")
    print(f"{'Mix':<20}{'CAGR':>10}{'Sharpe':>10}{'MaxDD':>10}")
    for w in [0.0, 0.3, 0.5, w_best, 0.7, 1.0]:
        mix = w * a + (1 - w) * c
        label = f"{w*100:.0f}/{(1-w)*100:.0f}" if w not in (w_best,) else f"{w*100:.1f}/{(1-w)*100:.1f} (ottimo)"
        cg, sr, dd = _cagr(mix, 12), _sharpe(mix, periods_per_year=12), _max_drawdown(mix)
        print(f"{label:<20}{cg*100:>9.2f}%{sr:>10.3f}{dd*100:>9.2f}%")


if __name__ == "__main__":
    main()
