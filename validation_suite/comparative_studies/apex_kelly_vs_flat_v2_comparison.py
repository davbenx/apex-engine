"""
apex_kelly_vs_flat_v2_comparison.py — Confronto diretto tra il sistema Apex V2
PRECEDENTE (§8.28: base_weight_per_class=0.50 fisso + vol_target=0.22, "target
vol e cap 50%") e quello ATTUALE (stesso vol-target/cap 50%, ma con la
pesatura Kelly frazionaria del §8.30 sopra — kelly_fraction=0.25/
kelly_window=208 settimane) sovrapposta, richiesto esplicitamente
dall'utente per vedere i due sistemi affiancati con lo stesso rigore
statistico usato nel resto di questa sessione.

Riusa `run_full_backtest()` di apex_dashboard_stat_regeneration.py (identica
pipeline di produzione — stessi proxy storici, stessa selezione azionaria
low-beta dal 2012+, stessi costi/tasse), ora parametrizzata con
kelly_fraction: 0.0 riproduce esattamente il sistema precedente (Kelly
disattivato -> fallback nativo al peso fisso 0.50), None usa il default di
produzione (0.25).

Importante: NON e' un secondo giro di validazione indipendente — e' lo
stesso identico backtest gia' usato per adottare Kelly in produzione
(risultati gia' citati nel docstring di get_apex_metrics()), qui ripetuto
con uno script dedicato e riproducibile per la richiesta esplicita di
confronto, con l'aggiunta di un CI bootstrap a blocchi sulla differenza
appaiata mensile (non presente nel giro originale).
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
from metrics import cagr as _cagr, sharpe as _sharpe, max_drawdown as _max_drawdown, calmar as _calmar, sortino_ratio, ulcer_index
from statistical_validation import block_bootstrap_ci

TEST_START = "2020-09-30"


def compute_stats(gross_m: pd.Series, net_m: pd.Series) -> dict:
    return {
        "cagr_gross": _cagr(gross_m, 12),
        "cagr_net": _cagr(net_m, 12),
        "volatility": float(gross_m.std() * np.sqrt(12)),
        "sharpe": _sharpe(gross_m, periods_per_year=12),
        "sortino": sortino_ratio(gross_m, periods_per_year=12),
        "max_drawdown": _max_drawdown(gross_m),
        "calmar": _calmar(gross_m, 12),
        "ulcer_index": ulcer_index(gross_m),
    }


def print_stats(label: str, stats: dict):
    print(f"\n{label}")
    print(f"  CAGR lordo:     {stats['cagr_gross']*100:+7.2f}%")
    print(f"  CAGR netto:     {stats['cagr_net']*100:+7.2f}%")
    print(f"  Volatilita':    {stats['volatility']*100:7.2f}%")
    print(f"  Sharpe:         {stats['sharpe']:7.3f}")
    print(f"  Sortino:        {stats['sortino']:7.3f}")
    print(f"  MaxDD:          {stats['max_drawdown']*100:7.2f}%")
    print(f"  Calmar:         {stats['calmar']:7.3f}")
    print(f"  Ulcer Index:    {stats['ulcer_index']:7.2f}")


def main():
    sector_of = json.load(open(SECTOR_MAP_FILE))

    print("=" * 78)
    print("SISTEMA PRECEDENTE (kelly_fraction=0.0 -> base_weight fisso 0.50, vol_target 0.22)")
    print("=" * 78)
    print("[*] Eseguo backtest completo (kelly_fraction=0.0)...")
    gross_w_old, net_w_old = run_full_backtest(sector_of, kelly_fraction=0.0)
    gross_m_old = to_monthly(gross_w_old).loc[:SLICE_END]
    net_m_old = to_monthly(net_w_old).loc[:SLICE_END]

    print("\n" + "=" * 78)
    print("SISTEMA ATTUALE (kelly_fraction=0.25 default -> Kelly frazionario sulle classi attive)")
    print("=" * 78)
    print("[*] Eseguo backtest completo (kelly_fraction=default produzione)...")
    gross_w_new, net_w_new = run_full_backtest(sector_of, kelly_fraction=None)
    gross_m_new = to_monthly(gross_w_new).loc[:SLICE_END]
    net_m_new = to_monthly(net_w_new).loc[:SLICE_END]

    # -------------------------------------------------------------------
    # Periodo TEST walk-forward (2020-09/2026-08, 72 mesi) — stessa finestra
    # mostrata in dashboard da get_apex_metrics()
    # -------------------------------------------------------------------
    gross_old_test = gross_m_old.loc[TEST_START:]
    net_old_test = net_m_old.loc[TEST_START:]
    gross_new_test = gross_m_new.loc[TEST_START:]
    net_new_test = net_m_new.loc[TEST_START:]

    print("\n" + "=" * 78)
    print(f"CONFRONTO — Periodo TEST walk-forward ({TEST_START} -> {SLICE_END}, "
          f"{len(gross_old_test)} mesi, mai usato per scegliere i parametri)")
    print("=" * 78)
    stats_old_test = compute_stats(gross_old_test, net_old_test)
    stats_new_test = compute_stats(gross_new_test, net_new_test)
    print_stats("Sistema PRECEDENTE (target vol 22% + cap 50%)", stats_old_test)
    print_stats("Sistema ATTUALE (+ Kelly frazionario 0.25)", stats_new_test)

    print(f"\n{'Metrica':<16}{'Precedente':>14}{'Attuale':>14}{'Delta':>12}")
    for k, label in [("cagr_gross", "CAGR lordo"), ("cagr_net", "CAGR netto"), ("sharpe", "Sharpe"),
                      ("sortino", "Sortino"), ("max_drawdown", "MaxDD"), ("calmar", "Calmar"),
                      ("ulcer_index", "Ulcer Index"), ("volatility", "Volatilita'")]:
        o, n = stats_old_test[k], stats_new_test[k]
        if k in ("cagr_gross", "cagr_net", "max_drawdown", "volatility"):
            print(f"{label:<16}{o*100:>13.2f}%{n*100:>13.2f}%{(n-o)*100:>+11.2f}pp")
        else:
            print(f"{label:<16}{o:>14.3f}{n:>14.3f}{(n-o):>+12.3f}")

    diff = (gross_new_test - gross_old_test).dropna()
    mean_diff = diff.mean() * 12 * 100
    lo, hi = block_bootstrap_ci(diff.values, lambda r: pd.Series(r).mean() * 12 * 100, block_size=12, ci=0.90, seed=42)
    n_better = int((diff > 0).sum())
    print(f"\nDifferenza appaiata mensile (Attuale - Precedente), lordo, periodo TEST:")
    print(f"  {mean_diff:+.2f}pp/anno  CI90 [{lo:+.2f}, {hi:+.2f}]  "
          f"({'ESCLUDE' if lo * hi > 0 else 'include'} lo zero)  mesi migliori {n_better}/{len(diff)}")

    # -------------------------------------------------------------------
    # Intero storico disponibile (1987-06+, per contesto — non la cifra
    # mostrata in dashboard, che resta il TEST period sopra)
    # -------------------------------------------------------------------
    print("\n" + "=" * 78)
    print(f"CONTESTO — Intero storico ({gross_m_old.index.min().date()} -> {gross_m_old.index.max().date()}, "
          f"{len(gross_m_old)} mesi, include il periodo usato per scegliere i parametri)")
    print("=" * 78)
    stats_old_full = compute_stats(gross_m_old, net_m_old)
    stats_new_full = compute_stats(gross_m_new, net_m_new)
    print_stats("Sistema PRECEDENTE — intero storico", stats_old_full)
    print_stats("Sistema ATTUALE — intero storico", stats_new_full)


if __name__ == "__main__":
    main()
