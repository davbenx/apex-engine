"""
apex_convex_cost_stress_test.py — Stress test su costi di transazione/
slippage (Apex) e TER (Convex), richiesto come parte del test di
robustezza/invalidazione istituzionale completo. Una strategia il cui
edge sopravvive solo sotto assunzioni di costo generose e' fragile nella
pratica reale (slippage su titoli meno liquidi, spread bid-ask reali sugli
ETF, differenze tra TER dichiarato e costo totale di possesso).

Apex: esegue UN SOLO backtest completo a parametri di produzione con
return_components=True (espone weights_df/returns_df senza ripetere il
loop settimanale), poi riapplica il cost_drag con moltiplicatori diversi
(1x/2x/3x/5x/10x sui 8-10bps attuali di turnover) — analiticamente, senza
richiedere altri backtest completi.

Convex: nessun backtest necessario — il TER e' gia' una detrazione
mensile diretta sulle sleeve returns, si rialza semplicemente il
coefficiente.
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
COST_MULTIPLIERS = [1.0, 2.0, 3.0, 5.0, 10.0]


def apex_cost_stress():
    sector_of = json.load(open(SECTOR_MAP_FILE))
    print("[*] Eseguo backtest di produzione con componenti esposte (un solo run)...")
    _, _, comp = run_full_backtest(sector_of, return_components=True)

    weight_change = comp["weight_change"]
    port_gross = comp["port_gross"]
    port_net = comp["port_net"]
    base_bps = float(np.mean(list(comp["cost_bps_map"].values())))

    print(f"\nCosto base (produzione): {base_bps*10000:.1f}bps medi sul turnover settimanale delle classi macro")
    print(f"Turnover settimanale medio: {weight_change.mean()*100:.2f}% del portafoglio")

    print(f"\n{'='*78}\nAPEX — Stress su costi di transazione/slippage (periodo TEST, 72 mesi)\n{'='*78}")
    print(f"{'Moltiplicatore costo':<26}{'bps effettivi':>15}{'CAGR lordo':>12}{'Sharpe':>9}{'MaxDD':>9}")
    for mult in COST_MULTIPLIERS:
        cost_drag = weight_change * base_bps * mult
        gross_stressed_w = port_gross - cost_drag
        gross_stressed_m = to_monthly(gross_stressed_w).loc[:SLICE_END]
        gross_test = gross_stressed_m.loc[TEST_START:]
        c, s, dd = _cagr(gross_test, 12), _sharpe(gross_test, periods_per_year=12), _max_drawdown(gross_test)
        label = f"{mult}x{' (produzione)' if mult == 1.0 else ''}"
        print(f"{label:<26}{base_bps*mult*10000:>13.1f}bps{c*100:>11.2f}%{s:>9.3f}{dd*100:>8.2f}%")

    base_case = to_monthly(port_gross - weight_change * base_bps).loc[:SLICE_END].loc[TEST_START:]
    extreme_case = to_monthly(port_gross - weight_change * base_bps * 10.0).loc[:SLICE_END].loc[TEST_START:]
    print(f"\nImpatto totale a 10x il costo attuale (scenario estremo, quasi implausibile per un basket di 15 "
          f"titoli large/mid-cap): {(_cagr(extreme_case,12) - _cagr(base_case,12))*100:+.2f}pp/anno di CAGR")


def convex_ter_stress():
    sleeve_file = REPO_ROOT / "validation_suite" / "comparative_studies" / "convex_extended_data" / "convex_sleeve_returns_extended.csv"
    sleeves = pd.read_csv(sleeve_file, index_col=0, parse_dates=True)
    keys = ["NTSG_proxy", "AVWS_proxy", "DBMFE_proxy", "PPFB_proxy", "WBTC_proxy"]
    raw_w = {"NTSG_proxy": 0.45, "AVWS_proxy": 0.15, "DBMFE_proxy": 0.25, "PPFB_proxy": 0.075, "WBTC_proxy": 0.075}
    ter_base = {"NTSG_proxy": 0.0025, "AVWS_proxy": 0.0039, "DBMFE_proxy": 0.0075, "PPFB_proxy": 0.0012, "WBTC_proxy": 0.0015}

    def portfolio_return(ter_mult: float) -> pd.Series:
        out = []
        for dt, row in sleeves[keys].iterrows():
            avail = {k: row[k] - (ter_base[k] * ter_mult) / 12.0 for k in keys if pd.notna(row[k])}
            if not avail:
                out.append(0.0)
                continue
            w_total = sum(raw_w[k] for k in avail)
            out.append(sum(raw_w[k] / w_total * v for k, v in avail.items()) if w_total > 0 else 0.0)
        return pd.Series(out, index=sleeves.index)

    print(f"\n{'='*78}\nCONVEX — Stress sul TER (intero storico, {len(sleeves)} mesi)\n{'='*78}")
    print(f"{'Moltiplicatore TER':<26}{'TER medio pond.':>16}{'CAGR':>10}{'Sharpe':>9}{'MaxDD':>9}")
    weighted_ter_base = sum(raw_w[k] * ter_base[k] for k in keys)
    for mult in [1.0, 1.5, 2.0, 3.0]:
        ret = portfolio_return(mult)
        c, s, dd = _cagr(ret, 12), _sharpe(ret, periods_per_year=12), _max_drawdown(ret)
        label = f"{mult}x{' (produzione)' if mult == 1.0 else ''}"
        print(f"{label:<26}{weighted_ter_base*mult*100:>15.3f}%{c*100:>9.2f}%{s:>9.3f}{dd*100:>8.2f}%")


def main():
    apex_cost_stress()
    convex_ter_stress()


if __name__ == "__main__":
    main()
