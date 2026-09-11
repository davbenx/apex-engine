"""
apex_v2_grid_pbo_cscv.py — PBO-CSCV (Combinatorially Symmetric
Cross-Validation) sulla griglia di sensibilita' dei dial macro di Apex V2
(apex_v2_sensitivity_grid.py), richiesto esplicitamente dall'utente come
completamento del test di robustezza/invalidazione istituzionale.

Domanda a cui risponde: "se avessi scelto la configurazione migliore
guardando solo un sotto-campione, quanto spesso quella scelta si sarebbe
rivelata sotto la mediana nel sotto-campione complementare?" — PBO vicino
al 50% = la selezione non fa meglio del caso; PBO basso = il ranking tra
varianti e' genuinamente riproducibile, non un artefatto del campione.

Per limitare il costo di calcolo (ogni backtest completo ~13 min), la
griglia qui e' un SOTTOINSIEME di quella completa in
apex_v2_sensitivity_grid.py: produzione (riusa la serie gia' salvata su
disco, apex_monthly_returns_extended_gross.csv — nessun nuovo backtest) +
4 varianti nuove (kelly_fraction 0.15/0.40, vol_target 16%/25%) — i 4 dial
piu' centrali, non i base_weight (periferici, gia' mostrata bassa
sensibilita' nella griglia principale).
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
from statistical_validation import pbo_cscv
from metrics import cagr as _cagr, sharpe as _sharpe, max_drawdown as _max_drawdown

TEST_START = "2020-09-30"

GRID = [
    ("Kelly fraction 0.15", 0.15, None),
    ("Kelly fraction 0.40", 0.40, None),
    ("Vol target 16%", None, 0.16),
    ("Vol target 25%", None, 0.25),
]


def main():
    sector_of = json.load(open(SECTOR_MAP_FILE))

    variants = {}
    prod = pd.read_csv(REPO_ROOT / "apex_monthly_returns_extended_gross.csv", index_col=0, parse_dates=True).iloc[:, 0]
    variants["Produzione (0.25/22%/0.50)"] = prod.loc[:SLICE_END]

    for label, kf, vt in GRID:
        print(f"[*] Eseguo backtest: {label} (kelly_fraction={kf}, vol_target={vt})...")
        gross_w, _ = run_full_backtest(sector_of, kelly_fraction=kf, vol_target=vt)
        variants[label] = to_monthly(gross_w).loc[:SLICE_END]

    oos_idx = None
    for label, ret in variants.items():
        test_ret = ret.loc[TEST_START:]
        oos_idx = test_ret.index if oos_idx is None else oos_idx.intersection(test_ret.index)

    print(f"\n{'='*78}\nRIEPILOGO (periodo TEST comune, {len(oos_idx)} mesi)\n{'='*78}")
    print(f"{'Variante':<32}{'CAGR':>9}{'Sharpe':>9}{'MaxDD':>9}")
    perf_cols = []
    for label, ret in variants.items():
        sub = ret.reindex(oos_idx).dropna()
        c, s, dd = _cagr(sub, 12), _sharpe(sub, periods_per_year=12), _max_drawdown(sub)
        print(f"{label:<32}{c*100:>8.2f}%{s:>9.3f}{dd*100:>8.2f}%")
        perf_cols.append(sub.values)

    perf_matrix = np.column_stack(perf_cols)
    n_splits = 8
    usable_len = (len(perf_matrix) // n_splits) * n_splits
    pbo = pbo_cscv(perf_matrix[-usable_len:], n_splits=n_splits)
    print(f"\nPBO-CSCV su {len(variants)} varianti (produzione + 4 dial macro), "
          f"periodo TEST ({usable_len} mesi utili, {n_splits} split): {pbo*100:.1f}%")
    print("(PBO ~50% = la scelta della configurazione di produzione non fa meglio del caso;")
    print(" PBO basso = il ranking tra varianti e' riproducibile fuori campione, non un artefatto)")


if __name__ == "__main__":
    main()
