"""
altcoin_satellite_btc_confound_test.py — Controllo di confondimento per
altcoin_crypto_slot_basket_satellite_test.py Parte B: il satellite
low-beta-altcoin ha mostrato +3.2/+8.2/+17.0pp/anno (CI 90% escludono
sempre lo zero) con PBO-CSCV 15% — in netto contrasto con la Parte A
(pick/basket low-beta NON batte BTC in modo robusto, PBO 40%, CI enormi).

Ipotesi da falsificare: il miglioramento non viene dalla SELEZIONE
low-beta, ma semplicemente dall'aggiungere PIU' esposizione crypto in
generale (il vol-target lasciava capacita' di rischio inutilizzata, e
crypto e' salita moltissimo nel campione — BTC CAGR 38.25% standalone).
Se e' cosi', lo stesso satellite investito in BTC anziche' nel pick
low-beta dovrebbe produrre un miglioramento simile o maggiore.

Riusa _run_apex_with_crypto_variant identica, cambiando solo la serie di
rendimento del satellite (BTC invece del pick low-beta).
"""
from __future__ import annotations
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "validation_suite" / "framework"))

from statistical_validation import pbo_cscv, block_bootstrap_ci
from metrics import sharpe, cagr, max_drawdown
from apex_stocks_vs_etf_backtest import load_weekly_macro, load_weekly_sp500, load_pointintime_snapshots
from sector_cap_grid_test import SECTOR_MAP_FILE
from altcoin_crypto_slot_basket_satellite_test import _run_apex_with_crypto_variant, WEEKLY_PERIODS_PER_YEAR
import json

def main():
    sector_of = json.load(open(SECTOR_MAP_FILE))
    btc = load_weekly_macro("BTC-USD")
    btc_ret = btc.pct_change()

    results = {}
    for satellite_pct in (0.0, 0.10, 0.25, 0.50):
        print(f"[*] Backtest portafoglio Apex, satellite_pct={satellite_pct:.0%} (satellite = BTC, controfattuale)...")
        results[satellite_pct] = _run_apex_with_crypto_variant(satellite_pct, sector_of, btc_ret)

    common_idx = results[0.0].index
    for r in results.values():
        common_idx = common_idx.intersection(r.index)
    common_idx = common_idx.sort_values()

    print(f"\n{'Satellite %':<14}{'CAGR netto':>12}{'Sharpe netto':>14}{'MaxDD netto':>13}{'vs baseline pp/anno':>22}{'CI90':>22}")
    base = results[0.0].reindex(common_idx)
    for pct, net in results.items():
        net = net.reindex(common_idx)
        c, s, dd = cagr(net, WEEKLY_PERIODS_PER_YEAR), sharpe(net, periods_per_year=WEEKLY_PERIODS_PER_YEAR), max_drawdown(net)
        if pct == 0.0:
            print(f"{'0% (baseline)':<14}{c*100:>11.2f}%{s:>14.2f}{dd*100:>12.2f}%{'--':>22}{'--':>22}")
        else:
            diff = (net - base).dropna()
            mean_diff = diff.mean() * WEEKLY_PERIODS_PER_YEAR * 100
            lo, hi = block_bootstrap_ci(diff.values, lambda r: pd.Series(r).mean() * WEEKLY_PERIODS_PER_YEAR * 100, block_size=12, ci=0.90, seed=42)
            print(f"{pct:>13.0%}{c*100:>11.2f}%{s:>14.2f}{dd*100:>12.2f}%{mean_diff:>+21.2f}   [{lo:+.2f}, {hi:+.2f}]")

    perf_matrix = np.column_stack([results[pct].reindex(common_idx).values for pct in results])
    n_splits = 6
    usable_len = (len(perf_matrix) // n_splits) * n_splits
    pbo = pbo_cscv(perf_matrix[-usable_len:], n_splits=n_splits)
    print(f"PBO-CSCV su {len(results)} configurazioni (satellite_pct = {list(results.keys())}, satellite=BTC): {pbo*100:.1f}%")

if __name__ == "__main__":
    main()
