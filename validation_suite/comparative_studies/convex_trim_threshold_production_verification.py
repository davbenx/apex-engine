"""
convex_trim_threshold_production_verification.py — Verifica quantitativa indipendente
del cambio di trim_threshold PPFB/WBTC (0.1125 -> 0.13125, ossia 1.5x -> 1.75x il
peso target del 7.5%) introdotto da lavoro esterno a questa sessione.

Il commento inline nel codice (portfolio_manager.py/convex_engine.py) rivendica per la
nuova soglia "Sharpe 0.99, riduce il drag fiscale e preserva il MaxDD a -15.86%", ma
l'audit indipendente di questa sessione non ha trovato alcuno script o studio nel repo
che riproduca quei numeri specifici. Questo script:

1. Riusa la logica gia' validata di simulate_trim_threshold (identica a
   convex_weights_threshold_sensitivity.py Parte B) per testare ESATTAMENTE 1.5x vs
   1.75x su PPFB, con incrementi fini vicino al valore di produzione.
2. Estende lo stesso test a WBTC (finora mai testato in nessuno script del repo),
   sull'orizzonte 2014-10->2026-09 in cui WBTC_proxy ha dati (144 mesi), a 5 sleeve
   con rinormalizzazione dei pesi quando una sleeve manca.
3. Riporta CAGR/Sharpe/MaxDD/Calmar NETTI da tasse italiane (26%, compensazione
   minusvalenze) per ciascuna soglia, per una decisione informata.

Nessun nuovo fetch dati: riusa convex_sleeve_returns_extended.csv gia' in repo.
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
TER = {"NTSG_proxy": 0.0025, "AVWS_proxy": 0.0039, "DBMFE_proxy": 0.0075, "PPFB_proxy": 0.0012, "WBTC_proxy": 0.0015}
TAX_RATE = 0.26


def load_sleeves() -> pd.DataFrame:
    return pd.read_csv(SLEEVE_FILE, index_col=0, parse_dates=True)


def print_stats_row(label: str, ret: pd.Series):
    c, s, dd, cal = _cagr(ret, 12), _sharpe(ret, periods_per_year=12), _max_drawdown(ret), _calmar(ret, 12)
    print(f"{label:<28}{c*100:>8.2f}%{s:>9.3f}{dd*100:>8.2f}%{cal:>9.3f}")


def simulate_trim_threshold(sleeve_returns: pd.DataFrame, keys: list, target_weights: dict,
                             trim_key: str, tolerance_mult: float) -> pd.Series:
    """Identica alla logica gia' validata in convex_weights_threshold_sensitivity.py,
    generalizzata a N sleeve e a una chiave di trim parametrica (PPFB o WBTC)."""
    values = dict(target_weights)
    cost_basis = dict(values)
    loss_pool = 0.0
    net_returns = []
    nav_prev = sum(values.values())
    for dt, row in sleeve_returns.iterrows():
        for k in keys:
            r = row[k]
            if pd.isna(r):
                continue  # sleeve non ancora disponibile: valore congelato (nessun rendimento)
            values[k] *= (1.0 + r - TER[k] / 12.0)
        nav_now = sum(values.values())
        w = values[trim_key] / nav_now
        tgt = target_weights[trim_key]
        if w > tgt * tolerance_mult:
            new_value = tgt * nav_now
            sold_gross = values[trim_key] - new_value
            basis_sold = cost_basis[trim_key] * (sold_gross / values[trim_key])
            gain = sold_gross - basis_sold
            if gain > 0:
                usable_loss = min(gain, loss_pool)
                loss_pool -= usable_loss
                tax = (gain - usable_loss) * TAX_RATE
            else:
                loss_pool += -gain
                tax = 0.0
            net_proceeds = sold_gross - tax
            cost_basis[trim_key] -= basis_sold
            values[trim_key] = new_value
            other_keys = [o for o in keys if o != trim_key]
            other_total = sum(values[o] for o in other_keys)
            for o in other_keys:
                share = values[o] / other_total if other_total > 1e-12 else 1.0 / len(other_keys)
                values[o] += net_proceeds * share
                cost_basis[o] += net_proceeds * share
            nav_now = sum(values.values())
        net_returns.append(nav_now / nav_prev - 1.0)
        nav_prev = nav_now
    return pd.Series(net_returns, index=sleeve_returns.index)


def part_ppfb():
    sleeves = load_sleeves()
    keys4 = ["NTSG_proxy", "AVWS_proxy", "DBMFE_proxy", "PPFB_proxy"]
    raw_w4 = {"NTSG_proxy": 0.45, "AVWS_proxy": 0.15, "DBMFE_proxy": 0.25, "PPFB_proxy": 0.075}
    s = sum(raw_w4.values())
    w4 = {k: v / s for k, v in raw_w4.items()}
    sub = sleeves[keys4].loc["2000-09-30":].dropna(how="any")

    print("=" * 68)
    print(f"PPFB — 1.5x (produzione VECCHIA, 11.25%) vs 1.75x (produzione NUOVA, 13.125%)")
    print(f"{len(sub)} mesi, 2000-09 -> 2026-08")
    print("=" * 68)
    print(f"{'Soglia':<28}{'CAGR':>9}{'Sharpe':>9}{'MaxDD':>9}{'Calmar':>9}")
    results = {}
    for mult in (1.40, 1.45, 1.50, 1.60, 1.70, 1.75, 1.80, 1.90, 2.00):
        ret = simulate_trim_threshold(sub, keys4, w4, "PPFB_proxy", mult)
        results[mult] = ret
        tag = " (VECCHIA prod.)" if mult == 1.50 else (" (NUOVA prod.)" if mult == 1.75 else "")
        print_stats_row(f"{mult}x{tag}", ret)

    old, new = results[1.50], results[1.75]
    print(f"\nDiff NUOVA(1.75x) vs VECCHIA(1.50x): CAGR {(_cagr(new,12)-_cagr(old,12))*100:+.3f}pp   "
          f"Sharpe {_sharpe(new,periods_per_year=12)-_sharpe(old,periods_per_year=12):+.4f}   "
          f"MaxDD {(_max_drawdown(new)-_max_drawdown(old))*100:+.3f}pp")
    return old, new


def part_wbtc():
    sleeves = load_sleeves()
    keys5 = ["NTSG_proxy", "AVWS_proxy", "DBMFE_proxy", "PPFB_proxy", "WBTC_proxy"]
    raw_w5 = {"NTSG_proxy": 0.45, "AVWS_proxy": 0.15, "DBMFE_proxy": 0.25, "PPFB_proxy": 0.075, "WBTC_proxy": 0.075}
    s = sum(raw_w5.values())
    w5 = {k: v / s for k, v in raw_w5.items()}
    sub = sleeves[keys5].loc["2014-10-31":].dropna(how="any")

    print(f"\n{'='*68}")
    print(f"WBTC — 1.5x (produzione VECCHIA, 11.25%) vs 1.75x (produzione NUOVA, 13.125%)")
    print(f"{len(sub)} mesi, 2014-10 -> 2026-08 (mai testato prima in questo repo)")
    print("=" * 68)
    print(f"{'Soglia':<28}{'CAGR':>9}{'Sharpe':>9}{'MaxDD':>9}{'Calmar':>9}")
    results = {}
    for mult in (1.40, 1.45, 1.50, 1.60, 1.70, 1.75, 1.80, 1.90, 2.00):
        ret = simulate_trim_threshold(sub, keys5, w5, "WBTC_proxy", mult)
        results[mult] = ret
        tag = " (VECCHIA prod.)" if mult == 1.50 else (" (NUOVA prod.)" if mult == 1.75 else "")
        print_stats_row(f"{mult}x{tag}", ret)

    old, new = results[1.50], results[1.75]
    print(f"\nDiff NUOVA(1.75x) vs VECCHIA(1.50x): CAGR {(_cagr(new,12)-_cagr(old,12))*100:+.3f}pp   "
          f"Sharpe {_sharpe(new,periods_per_year=12)-_sharpe(old,periods_per_year=12):+.4f}   "
          f"MaxDD {(_max_drawdown(new)-_max_drawdown(old))*100:+.3f}pp")
    return old, new


if __name__ == "__main__":
    part_ppfb()
    part_wbtc()
