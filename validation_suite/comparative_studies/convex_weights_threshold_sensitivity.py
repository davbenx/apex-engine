"""
convex_weights_threshold_sensitivity.py — Griglia di sensibilita' sui pesi
target (45/15/25/7.5/7.5) e sulla soglia di trim (TOLERANCE_MULT=1.5x) di
Convex, richiesta come parte del test di robustezza/invalidazione
istituzionale completo. Nessun nuovo fetch di dati — riusa
convex_sleeve_returns_extended.csv (465 mesi, 1987-12->2026-08).

Parte A — pesi target: per ciascun set di pesi alternativo, il rendimento
di portafoglio e' ricostruito rinormalizzando tra le sleeve disponibili a
ogni data (stessa logica di convex_extended_history_reconstruction.py),
sull'intero storico disponibile.

Parte B — soglia di trim: riusa la logica di simulate_trim (gia' validata
in convex_kelly_extended_history_retest.py) sul sottoinsieme a 4 sleeve
(NTSG/AVWS/DBMFE/PPFB, 2000-09->2026-08, 313 mesi — la stessa finestra
gia' usata per i test Kelly-su-Convex di questa sessione).
"""
from __future__ import annotations
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "validation_suite" / "framework"))

from metrics import cagr as _cagr, sharpe as _sharpe, max_drawdown as _max_drawdown, calmar as _calmar

SLEEVE_FILE = REPO_ROOT / "validation_suite" / "comparative_studies" / "convex_extended_data" / "convex_sleeve_returns_extended.csv"
KEYS5 = ["NTSG_proxy", "AVWS_proxy", "DBMFE_proxy", "PPFB_proxy", "WBTC_proxy"]
TER = {"NTSG_proxy": 0.0025, "AVWS_proxy": 0.0039, "DBMFE_proxy": 0.0075, "PPFB_proxy": 0.0012, "WBTC_proxy": 0.0015}

WEIGHT_VARIANTS = {
    "Produzione (45/15/25/7.5/7.5)": {"NTSG_proxy": 0.45, "AVWS_proxy": 0.15, "DBMFE_proxy": 0.25, "PPFB_proxy": 0.075, "WBTC_proxy": 0.075},
    "NTSG-pesante (60/10/15/7.5/7.5)": {"NTSG_proxy": 0.60, "AVWS_proxy": 0.10, "DBMFE_proxy": 0.15, "PPFB_proxy": 0.075, "WBTC_proxy": 0.075},
    "DBMFE-pesante (30/15/40/7.5/7.5)": {"NTSG_proxy": 0.30, "AVWS_proxy": 0.15, "DBMFE_proxy": 0.40, "PPFB_proxy": 0.075, "WBTC_proxy": 0.075},
    "Equipesato (25/25/25/12.5/12.5)": {"NTSG_proxy": 0.25, "AVWS_proxy": 0.25, "DBMFE_proxy": 0.25, "PPFB_proxy": 0.125, "WBTC_proxy": 0.125},
    "AVWS-pesante (30/35/20/7.5/7.5)": {"NTSG_proxy": 0.30, "AVWS_proxy": 0.35, "DBMFE_proxy": 0.20, "PPFB_proxy": 0.075, "WBTC_proxy": 0.075},
}


def load_sleeves() -> pd.DataFrame:
    return pd.read_csv(SLEEVE_FILE, index_col=0, parse_dates=True)[KEYS5]


def portfolio_return_renormalized(sleeves: pd.DataFrame, weights: dict) -> pd.Series:
    out = []
    for dt, row in sleeves.iterrows():
        avail = {k: row[k] - TER[k] / 12.0 for k in KEYS5 if pd.notna(row[k])}
        if not avail:
            out.append(0.0)
            continue
        w_total = sum(weights[k] for k in avail)
        out.append(sum(weights[k] / w_total * v for k, v in avail.items()) if w_total > 0 else 0.0)
    return pd.Series(out, index=sleeves.index)


def print_stats_row(label: str, ret: pd.Series):
    c, s, dd, cal = _cagr(ret, 12), _sharpe(ret, periods_per_year=12), _max_drawdown(ret), _calmar(ret, 12)
    print(f"{label:<34}{c*100:>8.2f}%{s:>9.3f}{dd*100:>8.2f}%{cal:>9.3f}")


def part_a_weights():
    sleeves = load_sleeves()
    print("=" * 78)
    print(f"PARTE A — Sensibilita' ai pesi target (intero storico, {len(sleeves)} mesi, 1987-12->2026-08)")
    print("=" * 78)
    print(f"{'Variante':<34}{'CAGR':>9}{'Sharpe':>9}{'MaxDD':>9}{'Calmar':>9}")
    results = {}
    for label, w in WEIGHT_VARIANTS.items():
        ret = portfolio_return_renormalized(sleeves, w)
        results[label] = ret
        print_stats_row(label, ret)

    prod = results["Produzione (45/15/25/7.5/7.5)"]
    print(f"\nConfronto diretto vs Produzione (intero storico):")
    for label, ret in results.items():
        if label.startswith("Produzione"):
            continue
        common = ret.index.intersection(prod.index)
        diff = (ret.loc[common] - prod.loc[common])
        print(f"  {label:<34} diff CAGR: {(_cagr(ret,12)-_cagr(prod,12))*100:+.2f}pp   diff Sharpe: {_sharpe(ret,periods_per_year=12)-_sharpe(prod,periods_per_year=12):+.3f}")


# ============================================================================
# Parte B — soglia di trim (4 sleeve, 2000-09->2026-08, 313 mesi)
# ============================================================================
KEYS4 = ["NTSG_proxy", "AVWS_proxy", "DBMFE_proxy", "PPFB_proxy"]
RAW_W4 = {"NTSG_proxy": 0.45, "AVWS_proxy": 0.15, "DBMFE_proxy": 0.25, "PPFB_proxy": 0.075}
_w4sum = sum(RAW_W4.values())
CURRENT_W4 = {k: v / _w4sum for k, v in RAW_W4.items()}
TAX_RATE = 0.26
START4 = "2000-09-30"


def simulate_trim_threshold(sleeve_returns: pd.DataFrame, tolerance_mult: float) -> pd.Series:
    values = dict(CURRENT_W4)
    cost_basis = dict(values)
    loss_pool = 0.0
    net_returns = []
    nav_prev = sum(values.values())
    for i, (dt, row) in enumerate(sleeve_returns.iterrows()):
        for k in KEYS4:
            values[k] *= (1.0 + row[k] - TER[k] / 12.0)
        nav_now = sum(values.values())
        k = "PPFB_proxy"
        w = values[k] / nav_now
        tgt = CURRENT_W4[k]
        if w > tgt * tolerance_mult:
            new_value = tgt * nav_now
            sold_gross = values[k] - new_value
            basis_sold = cost_basis[k] * (sold_gross / values[k])
            gain = sold_gross - basis_sold
            if gain > 0:
                usable_loss = min(gain, loss_pool)
                loss_pool -= usable_loss
                tax = (gain - usable_loss) * TAX_RATE
            else:
                loss_pool += -gain
                tax = 0.0
            net_proceeds = sold_gross - tax
            cost_basis[k] -= basis_sold
            values[k] = new_value
            other_keys = [o for o in KEYS4 if o != k]
            other_total = sum(values[o] for o in other_keys)
            for o in other_keys:
                share = values[o] / other_total if other_total > 1e-12 else 1.0 / len(other_keys)
                values[o] += net_proceeds * share
                cost_basis[o] += net_proceeds * share
            nav_now = sum(values.values())
        net_returns.append(nav_now / nav_prev - 1.0)
        nav_prev = nav_now
    return pd.Series(net_returns, index=sleeve_returns.index)


def part_b_threshold():
    sleeves = load_sleeves()[KEYS4].loc[START4:].dropna(how="any")
    print(f"\n{'='*78}\nPARTE B — Sensibilita' alla soglia di trim PPFB ({len(sleeves)} mesi, 2000-09->2026-08)\n{'='*78}")
    print(f"{'Soglia (x target)':<34}{'CAGR':>9}{'Sharpe':>9}{'MaxDD':>9}{'Calmar':>9}")
    results = {}
    for mult in (1.15, 1.3, 1.5, 1.7, 2.0, 3.0):
        ret = simulate_trim_threshold(sleeves, mult)
        results[mult] = ret
        label = f"{mult}x{' (produzione)' if mult == 1.5 else ''}"
        print_stats_row(label, ret)

    prod = results[1.5]
    print(f"\nConfronto diretto vs soglia di produzione (1.5x):")
    for mult, ret in results.items():
        if mult == 1.5:
            continue
        print(f"  {mult}x{'':<28} diff CAGR: {(_cagr(ret,12)-_cagr(prod,12))*100:+.3f}pp   diff Sharpe: {_sharpe(ret,periods_per_year=12)-_sharpe(prod,periods_per_year=12):+.4f}")


def main():
    part_a_weights()
    part_b_threshold()


if __name__ == "__main__":
    main()
