"""
apex_v2_sensitivity_grid.py — Griglia di sensibilita' sui 3 dial principali
del segnale macro di Apex V2 (kelly_fraction, vol_target,
base_weight_per_class), richiesta come parte del test di robustezza e
invalidazione istituzionale completo su Apex+Convex.

Principio: una strategia i cui risultati collassano non appena ci si
allontana anche di poco dal punto scelto in produzione e' probabilmente
overfittata a quello specifico punto, non genuinamente robusta. Si testa
quindi un VICINATO attorno ai valori di produzione (kelly_fraction=0.25,
vol_target=0.22, base_weight_per_class=0.50 — §8.28/§8.30), un dial alla
volta (isolando l'effetto di ciascuno), sul periodo TEST walk-forward
(2020-09/2026-08, mai usato per scegliere questi parametri).

Riusa run_full_backtest() di apex_dashboard_stat_regeneration.py (identica
pipeline di produzione), ora esteso con i 3 parametri. Ogni punto della
griglia e' un backtest settimanale completo (~12-13 minuti) — script
pensato per essere eseguito in background.
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

# (label, kelly_fraction, vol_target, base_weight_per_class) — None = default di produzione
GRID = [
    ("Produzione (0.25 / 22% / 0.50)", None, None, None),
    ("Kelly fraction 0.15", 0.15, None, None),
    ("Kelly fraction 0.40", 0.40, None, None),
    ("Vol target 16%", None, 0.16, None),
    ("Vol target 19%", None, 0.19, None),
    ("Vol target 25%", None, 0.25, None),
    ("Vol target 28%", None, 0.28, None),
    ("Base weight 0.35", None, None, 0.35),
    ("Base weight 0.65", None, None, 0.65),
]


def main():
    sector_of = json.load(open(SECTOR_MAP_FILE))
    results = {}
    for label, kf, vt, bw in GRID:
        print("=" * 78)
        print(f"[*] {label} (kelly_fraction={kf}, vol_target={vt}, base_weight={bw})")
        print("=" * 78)
        gross_w, net_w = run_full_backtest(sector_of, kelly_fraction=kf, vol_target=vt, base_weight_per_class=bw)
        gross_m = to_monthly(gross_w).loc[:SLICE_END]
        gross_test = gross_m.loc[TEST_START:]
        stats = {
            "cagr": _cagr(gross_test, 12),
            "sharpe": _sharpe(gross_test, periods_per_year=12),
            "mdd": _max_drawdown(gross_test),
            "calmar": _calmar(gross_test, 12),
        }
        results[label] = stats
        print(f"  CAGR {stats['cagr']*100:+.2f}%  Sharpe {stats['sharpe']:.3f}  "
              f"MaxDD {stats['mdd']*100:.2f}%  Calmar {stats['calmar']:.3f}")

    print("\n" + "=" * 78)
    print("RIEPILOGO GRIGLIA DI SENSIBILITA' (periodo TEST walk-forward, 72 mesi)")
    print("=" * 78)
    print(f"{'Variante':<34}{'CAGR':>9}{'Sharpe':>9}{'MaxDD':>9}{'Calmar':>9}")
    for label, stats in results.items():
        print(f"{label:<34}{stats['cagr']*100:>8.2f}%{stats['sharpe']:>9.3f}{stats['mdd']*100:>8.2f}%{stats['calmar']:>9.3f}")

    sharpes = [s["sharpe"] for s in results.values()]
    print(f"\nSharpe: min {min(sharpes):.3f}, max {max(sharpes):.3f}, "
          f"range {max(sharpes)-min(sharpes):.3f}, produzione {results['Produzione (0.25 / 22% / 0.50)']['sharpe']:.3f}")


if __name__ == "__main__":
    main()
