"""
apex_v2_vs_v3_full_comparison.py — Confronto diretto tra il sistema COMPLETO
"v2" (basket low-vol + target-vol fisso 0.50/22%, nessun Kelly — §8.28) e il
sistema COMPLETO "v3" attuale (basket low-beta + Kelly frazionario 0.25 —
§8.29/§8.30), richiesto esplicitamente dall'utente ("Apex v3 rende meno di
Apex v2?").

Perche' un nuovo script invece di riusare apex_beta_basket_selection_test.py
(vecchio confronto low-vol/low-beta) o apex_kelly_vs_flat_v2_comparison.py
(vecchio confronto Kelly/no-Kelly): NESSUNO dei due isola correttamente
questo confronto oggi.
  - apex_beta_basket_selection_test.py e' precedente al fix del
    survivorship bias, al fix della fuga same-bar nel ribasket e al fix
    del costo di turnover del basket (concern #2/#4 di oggi) — confronta
    due basket entrambi calcolati su una pipeline ormai nota per essere
    distorta, e non include Kelly da nessuna delle due parti.
  - apex_kelly_vs_flat_v2_comparison.py isola SOLO l'effetto Kelly, con
    select_low_beta_basket su ENTRAMBI i lati — non risponde alla domanda
    "v2 completo vs v3 completo" (due variabili cambiano insieme: basket
    E pesatura).

Qui entrambi i lati usano la STESSA pipeline dati corretta (survivorship
bias fix, same-bar leak fix, costo di turnover) — l'unica differenza tra
v2 e v3 e' esattamente le due modifiche reali intercorse in produzione,
nessun'altra variabile confondente.
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
        "cagr_gross": _cagr(gross_m, 12), "cagr_net": _cagr(net_m, 12),
        "volatility": float(gross_m.std() * np.sqrt(12)),
        "sharpe": _sharpe(gross_m, periods_per_year=12), "sortino": sortino_ratio(gross_m, periods_per_year=12),
        "max_drawdown": _max_drawdown(gross_m), "calmar": _calmar(gross_m, 12), "ulcer_index": ulcer_index(gross_m),
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
    print("APEX v2 (basket LOW-VOL + target-vol fisso 0.50/22%, NESSUN Kelly, §8.28)")
    print("=" * 78)
    print("[*] Eseguo backtest completo (use_low_vol_basket=True, kelly_fraction=0.0)...")
    gross_w_v2, net_w_v2 = run_full_backtest(sector_of, kelly_fraction=0.0, use_low_vol_basket=True)
    gross_m_v2 = to_monthly(gross_w_v2).loc[:SLICE_END]
    net_m_v2 = to_monthly(net_w_v2).loc[:SLICE_END]

    print("\n" + "=" * 78)
    print("APEX v3 (basket LOW-BETA + Kelly frazionario 0.25, §8.29/§8.30 — PRODUZIONE)")
    print("=" * 78)
    print("[*] Eseguo backtest completo (use_low_vol_basket=False, kelly_fraction=default)...")
    gross_w_v3, net_w_v3 = run_full_backtest(sector_of, kelly_fraction=None, use_low_vol_basket=False)
    gross_m_v3 = to_monthly(gross_w_v3).loc[:SLICE_END]
    net_m_v3 = to_monthly(net_w_v3).loc[:SLICE_END]

    gross_v2_test, net_v2_test = gross_m_v2.loc[TEST_START:], net_m_v2.loc[TEST_START:]
    gross_v3_test, net_v3_test = gross_m_v3.loc[TEST_START:], net_m_v3.loc[TEST_START:]

    print("\n" + "=" * 78)
    print(f"CONFRONTO — Periodo TEST walk-forward ({TEST_START} -> {SLICE_END}, {len(gross_v2_test)} mesi)")
    print("=" * 78)
    stats_v2_test = compute_stats(gross_v2_test, net_v2_test)
    stats_v3_test = compute_stats(gross_v3_test, net_v3_test)
    print_stats("Apex v2 (low-vol, no Kelly)", stats_v2_test)
    print_stats("Apex v3 (low-beta + Kelly, produzione)", stats_v3_test)

    print(f"\n{'Metrica':<16}{'v2':>14}{'v3':>14}{'Delta (v3-v2)':>16}")
    for k, label in [("cagr_gross", "CAGR lordo"), ("cagr_net", "CAGR netto"), ("sharpe", "Sharpe"),
                      ("sortino", "Sortino"), ("max_drawdown", "MaxDD"), ("calmar", "Calmar"),
                      ("ulcer_index", "Ulcer Index"), ("volatility", "Volatilita'")]:
        o, n = stats_v2_test[k], stats_v3_test[k]
        if k in ("cagr_gross", "cagr_net", "max_drawdown", "volatility"):
            print(f"{label:<16}{o*100:>13.2f}%{n*100:>13.2f}%{(n-o)*100:>+15.2f}pp")
        else:
            print(f"{label:<16}{o:>14.3f}{n:>14.3f}{(n-o):>+16.3f}")

    diff = (gross_v3_test - gross_v2_test).dropna()
    mean_diff = diff.mean() * 12 * 100
    lo, hi = block_bootstrap_ci(diff.values, lambda r: pd.Series(r).mean() * 12 * 100, block_size=12, ci=0.90, seed=42)
    n_better = int((diff > 0).sum())
    print(f"\nDifferenza appaiata mensile (v3 - v2), lordo, periodo TEST:")
    print(f"  {mean_diff:+.2f}pp/anno  CI90 [{lo:+.2f}, {hi:+.2f}]  "
          f"({'ESCLUDE' if lo * hi > 0 else 'include'} lo zero)  mesi migliori {n_better}/{len(diff)}")

    print("\n" + "=" * 78)
    print(f"CONTESTO — Intero storico ({gross_m_v2.index.min().date()} -> {gross_m_v2.index.max().date()}, {len(gross_m_v2)} mesi)")
    print("=" * 78)
    stats_v2_full = compute_stats(gross_m_v2, net_m_v2)
    stats_v3_full = compute_stats(gross_m_v3, net_m_v3)
    print_stats("Apex v2 — intero storico", stats_v2_full)
    print_stats("Apex v3 — intero storico", stats_v3_full)

    diff_full = (gross_m_v3 - gross_m_v2).dropna()
    mean_diff_full = diff_full.mean() * 12 * 100
    lo_f, hi_f = block_bootstrap_ci(diff_full.values, lambda r: pd.Series(r).mean() * 12 * 100, block_size=12, ci=0.90, seed=42)
    print(f"\nDifferenza appaiata mensile (v3 - v2), lordo, intero storico:")
    print(f"  {mean_diff_full:+.2f}pp/anno  CI90 [{lo_f:+.2f}, {hi_f:+.2f}]  "
          f"({'ESCLUDE' if lo_f * hi_f > 0 else 'include'} lo zero)")


if __name__ == "__main__":
    main()
