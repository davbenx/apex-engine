"""
convex_kelly_extended_history_retest.py — Ri-esegue i due test Kelly-su-
Convex di questa sessione (`convex_kelly_selective_trim_test.py`, target
Kelly + trim selettivo gated; `convex_contrarian_kelly_pac_test.py`, PAC
contrarian) sul campione esteso fino al 1987
(`convex_extended_history_reconstruction.py`), richiesto esplicitamente
dall'utente dopo che entrambi i test originali erano stati segnalati come
a bassa confidenza per il campione troppo corto (81 mesi, 2019-2026, mai
attraversata una vera crisi).

Compromesso dichiarato: WBTC (Crypto) ha dati solo dal 2014-10 — troppo
corto per l'obiettivo di catturare 2000-2002/2008. Qui si usa un
sotto-insieme a 4 sleeve (NTSG/AVWS/DBMFE/PPFB, Crypto escluso), pesi
target RINORMALIZZATI a somma 1 (45/15/25/7.5 -> 48.65/16.22/27.03/8.11%),
dal 2000-09-30 (quando tutte e 4 sono simultaneamente disponibili) al
2026-09-30 — 313 mesi contro gli 81 originali, quasi 4x, e include
davvero il crollo dot-com (2000-2002) e la crisi finanziaria (2008) nel
TRAIN, non solo nel folklore.

Stessa logica di simulazione dei due script originali (copiata, non
importata, per evitare dipendenze implicite dal dizionario di pesi a 5
sleeve di convex_never_sell_cost_test.py) — trim ancora limitato a PPFB
(Reddito Diverso, unica sleeve a reddito diverso rimasta nel sotto-
insieme a 4).
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
sys.path.insert(0, str(REPO_ROOT / "validation_suite" / "kelly_stack"))

from metrics import cagr as _cagr, sharpe as _sharpe, max_drawdown as _max_drawdown, calmar as _calmar
from statistical_validation import pbo_cscv, block_bootstrap_ci
from kelly_backtest import _calibrate_mu_sigma_corr

DATA_FILE = Path(__file__).parent / "convex_extended_data" / "convex_sleeve_returns_extended.csv"
KEYS = ["NTSG_proxy", "AVWS_proxy", "DBMFE_proxy", "PPFB_proxy"]
RAW_WEIGHTS = {"NTSG_proxy": 0.45, "AVWS_proxy": 0.15, "DBMFE_proxy": 0.25, "PPFB_proxy": 0.075}
_wsum = sum(RAW_WEIGHTS.values())
CURRENT_WEIGHTS = {k: v / _wsum for k, v in RAW_WEIGHTS.items()}
TER = {"NTSG_proxy": 0.0025, "AVWS_proxy": 0.0039, "DBMFE_proxy": 0.0075, "PPFB_proxy": 0.0012}
TAX_TYPE = {"NTSG_proxy": "REDDITO_CAPITALE", "AVWS_proxy": "REDDITO_CAPITALE",
            "DBMFE_proxy": "REDDITO_CAPITALE", "PPFB_proxy": "REDDITO_DIVERSO"}
TRIM_SLEEVES = ("PPFB_proxy",)
TOLERANCE_MULT = 1.5
TAX_RATE = 0.26
KELLY_FRACTION = 0.25
GATE_MONTHS = 12
MOMENTUM_WINDOW = 12
MONTHLY_CONTRIBUTION = 0.01
START_DATE = "2000-09-30"  # tutte e 4 le sleeve disponibili da qui


def load_sleeve_returns() -> pd.DataFrame:
    df = pd.read_csv(DATA_FILE, index_col=0, parse_dates=True)[KEYS]
    return df.loc[START_DATE:].dropna(how="any")


# ============================================================================
# Parte 1: target Kelly + trim selettivo gated (da convex_kelly_selective_trim_test.py)
# ============================================================================

def compute_kelly_targets(calib: pd.DataFrame, fraction: float = KELLY_FRACTION) -> dict[str, float]:
    mu, sigma, corr = _calibrate_mu_sigma_corr(calib, KEYS, use_shrinkage=True)
    mu_arr = np.array([mu[k] for k in KEYS])
    sigma_arr = np.array([sigma[k] for k in KEYS])
    Sigma = corr * np.outer(sigma_arr, sigma_arr)
    f_star = np.linalg.solve(Sigma, mu_arr)
    f_star = np.clip(f_star, 0.0, None) * fraction
    total = f_star.sum()
    if total <= 1e-9:
        return dict(CURRENT_WEIGHTS)
    return dict(zip(KEYS, f_star / total))


def simulate_trim(sleeve_returns: pd.DataFrame, target_weights: dict[str, float], gate_mode: str, gate_months: int = GATE_MONTHS) -> pd.Series:
    values = {k: target_weights[k] for k in KEYS}
    cost_basis = dict(values)
    loss_pool = 0.0
    last_trim_month = {k: -10**9 for k in KEYS}
    months_over = {k: 0 for k in KEYS}
    trims_this_year = {k: {} for k in KEYS}

    net_returns = []
    nav_prev = sum(values.values())
    for i, (dt, row) in enumerate(sleeve_returns.iterrows()):
        for k in KEYS:
            values[k] *= (1.0 + row[k] - TER[k] / 12.0)
        nav_before_trim = sum(values.values())

        for k in TRIM_SLEEVES:
            w = values[k] / nav_before_trim
            tgt = target_weights[k]
            is_over = w > tgt * TOLERANCE_MULT
            if not is_over:
                months_over[k] = 0
                continue
            months_over[k] += 1
            if gate_mode == "cooldown" and (i - last_trim_month[k]) < gate_months:
                continue
            if gate_mode == "persistence" and months_over[k] < gate_months:
                continue
            if gate_mode == "calendar" and trims_this_year[k].get(dt.year, 0) >= 1:
                continue

            new_value = tgt * nav_before_trim
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
            other_keys = [o for o in KEYS if o != k]
            other_total = sum(values[o] for o in other_keys)
            for o in other_keys:
                share = values[o] / other_total if other_total > 1e-12 else 1.0 / len(other_keys)
                values[o] += net_proceeds * share
                cost_basis[o] += net_proceeds * share
            last_trim_month[k] = i
            months_over[k] = 0
            trims_this_year[k][dt.year] = trims_this_year[k].get(dt.year, 0) + 1

        nav_after = sum(values.values())
        net_returns.append(nav_after / nav_prev - 1.0)
        nav_prev = nav_after

    return pd.Series(net_returns, index=sleeve_returns.index)


def run_part1(sleeve_returns: pd.DataFrame):
    print("\n" + "=" * 78)
    print("PARTE 1 — Target Kelly + trim selettivo gated (4 sleeve, 2000-09 -> 2026-09)")
    print("=" * 78)

    split = len(sleeve_returns) // 2
    calib, oos = sleeve_returns.iloc[:split], sleeve_returns.iloc[split:]
    print(f"TRAIN: {len(calib)} mesi ({calib.index[0].date()}->{calib.index[-1].date()}) — include 2000-2002 e 2008")
    print(f"TEST (OOS): {len(oos)} mesi ({oos.index[0].date()}->{oos.index[-1].date()}) — include 2020 e 2022")

    kelly_targets = compute_kelly_targets(calib)
    blended_targets = {k: 0.5 * CURRENT_WEIGHTS[k] + 0.5 * kelly_targets[k] for k in KEYS}
    print(f"\nTarget attuali (rinormalizzati): {', '.join(f'{k}={v*100:.1f}%' for k, v in CURRENT_WEIGHTS.items())}")
    print(f"Target Kelly (frac 0.25):        {', '.join(f'{k}={v*100:.1f}%' for k, v in kelly_targets.items())}")
    print(f"Target blend 50/50:              {', '.join(f'{k}={v*100:.1f}%' for k, v in blended_targets.items())}")

    variants = {}
    for tgt_label, tgt in [("Fisso", CURRENT_WEIGHTS), ("Kelly", kelly_targets), ("Blend50/50", blended_targets)]:
        for gate_label, gate_mode in [("nessun cancello", "none"), ("cooldown 12m", "cooldown"),
                                       ("persistence 12m", "persistence"), ("calendar 1/anno", "calendar")]:
            key = f"{tgt_label} + {gate_label}"
            variants[key] = simulate_trim(sleeve_returns, tgt, gate_mode)

    oos_idx = oos.index
    print(f"\n{'Variante (solo OOS)':<32}{'CAGR':>9}{'Sharpe':>9}{'MaxDD':>9}{'Calmar':>9}")
    for label, net in variants.items():
        sub = net.reindex(oos_idx).dropna()
        c, s, dd, cal = _cagr(sub, 12), _sharpe(sub, periods_per_year=12), _max_drawdown(sub), _calmar(sub, 12)
        print(f"{label:<32}{c*100:>8.2f}%{s:>9.2f}{dd*100:>8.2f}%{cal:>9.2f}")

    baseline_label = "Fisso + nessun cancello"
    baseline_oos = variants[baseline_label].reindex(oos_idx)
    print(f"\nConfronto accoppiato diretto vs baseline attuale ({baseline_label}), solo OOS:")
    for label, net in variants.items():
        if label == baseline_label:
            continue
        diff = (net.reindex(oos_idx) - baseline_oos).dropna()
        mean_diff = diff.mean() * 12 * 100
        lo, hi = block_bootstrap_ci(diff.values, lambda r: pd.Series(r).mean() * 12 * 100, block_size=12, ci=0.90, seed=42)
        print(f"  {label:<32}{mean_diff:+7.2f}pp/anno  CI90 [{lo:+.2f}, {hi:+.2f}] "
              f"({'ESCLUDE' if lo * hi > 0 else 'include'} lo zero)")

    perf_matrix = np.column_stack([variants[k].reindex(oos_idx).values for k in variants])
    n_splits = 8
    usable_len = (len(perf_matrix) // n_splits) * n_splits
    pbo = pbo_cscv(perf_matrix[-usable_len:], n_splits=n_splits)
    print(f"\nPBO-CSCV su {len(variants)} varianti, periodo OOS ({usable_len} mesi utili): {pbo*100:.1f}%")


# ============================================================================
# Parte 2: Kelly contrarian sul PAC (da convex_contrarian_kelly_pac_test.py)
# ============================================================================

def contrarian_mu_series(returns: pd.DataFrame, window: int) -> pd.DataFrame:
    trailing = (1 + returns[KEYS]).rolling(window).apply(lambda x: x.prod() - 1.0, raw=True)
    z = trailing.sub(trailing.mean(axis=1), axis=0).div(trailing.std(axis=1, ddof=0).replace(0, np.nan), axis=0)
    return (-z).fillna(0.0)


def simulate_pac(sleeve_returns: pd.DataFrame, mu_contrarian: pd.DataFrame, Sigma: np.ndarray,
                  allocation_rule: str, monthly_contribution: float = MONTHLY_CONTRIBUTION) -> pd.Series:
    values = {k: CURRENT_WEIGHTS[k] for k in KEYS}
    cost_basis = dict(values)
    loss_pool = 0.0

    net_returns = []
    nav_prev = sum(values.values())
    for i, (dt, row) in enumerate(sleeve_returns.iterrows()):
        for k in KEYS:
            values[k] *= (1.0 + row[k] - TER[k] / 12.0)
        nav_now = sum(values.values())

        for k in TRIM_SLEEVES:
            w = values[k] / nav_now
            tgt = CURRENT_WEIGHTS[k]
            if w <= tgt * TOLERANCE_MULT:
                continue
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
            other_keys = [o for o in KEYS if o != k]
            other_total = sum(values[o] for o in other_keys)
            for o in other_keys:
                share = values[o] / other_total if other_total > 1e-12 else 1.0 / len(other_keys)
                values[o] += net_proceeds * share
                cost_basis[o] += net_proceeds * share
            nav_now = sum(values.values())

        deficits = {k: max(0.0, CURRENT_WEIGHTS[k] - values[k] / nav_now) for k in KEYS}
        underweight = {k: d for k, d in deficits.items() if d > 1e-9}
        contribution = monthly_contribution * 1.0

        if underweight:
            if allocation_rule == "winner_take_all":
                target = max(underweight, key=underweight.get)
                alloc = {target: contribution}
            elif allocation_rule == "deficit_proportional":
                total_deficit = sum(underweight.values())
                alloc = {k: contribution * d / total_deficit for k, d in underweight.items()}
            elif allocation_rule == "kelly_contrarian":
                mu_vec = np.array([mu_contrarian.iloc[i][k] if k in underweight else -1e6 for k in KEYS])
                try:
                    f_star = np.linalg.solve(Sigma, np.clip(mu_vec, -1e6, None))
                except np.linalg.LinAlgError:
                    f_star = np.zeros(len(KEYS))
                f_star = {k: max(0.0, f_star[j]) for j, k in enumerate(KEYS) if k in underweight}
                total_f = sum(f_star.values())
                if total_f > 1e-9:
                    alloc = {k: contribution * v / total_f for k, v in f_star.items()}
                else:
                    total_deficit = sum(underweight.values())
                    alloc = {k: contribution * d / total_deficit for k, d in underweight.items()}
            else:
                raise ValueError(allocation_rule)
            for k, amt in alloc.items():
                values[k] += amt
                cost_basis[k] += amt
            nav_now = sum(values.values())

        net_returns.append((nav_now - contribution) / nav_prev - 1.0)
        nav_prev = nav_now

    return pd.Series(net_returns, index=sleeve_returns.index)


def run_part2(sleeve_returns: pd.DataFrame):
    print("\n" + "=" * 78)
    print("PARTE 2 — Kelly contrarian sul PAC mensile (4 sleeve, 2000-09 -> 2026-09)")
    print("=" * 78)

    split = len(sleeve_returns) // 2
    calib, oos = sleeve_returns.iloc[:split], sleeve_returns.iloc[split:]

    mu, sigma, corr = _calibrate_mu_sigma_corr(calib, KEYS, use_shrinkage=True)
    sigma_arr = np.array([sigma[k] for k in KEYS])
    Sigma = corr * np.outer(sigma_arr, sigma_arr)
    mu_contrarian = contrarian_mu_series(sleeve_returns, MOMENTUM_WINDOW)

    variants = {}
    for label, rule in [("Winner-take-all (oggi)", "winner_take_all"),
                         ("Deficit-proporzionale", "deficit_proportional"),
                         ("Kelly contrarian", "kelly_contrarian")]:
        variants[label] = simulate_pac(sleeve_returns, mu_contrarian, Sigma, rule)

    oos_idx = oos.index
    print(f"\n{'Variante (solo OOS)':<26}{'CAGR':>9}{'Sharpe':>9}{'MaxDD':>9}{'Calmar':>9}")
    for label, net in variants.items():
        sub = net.reindex(oos_idx).dropna()
        c, s, dd, cal = _cagr(sub, 12), _sharpe(sub, periods_per_year=12), _max_drawdown(sub), _calmar(sub, 12)
        print(f"{label:<26}{c*100:>8.2f}%{s:>9.2f}{dd*100:>8.2f}%{cal:>9.2f}")

    baseline_label = "Winner-take-all (oggi)"
    baseline_oos = variants[baseline_label].reindex(oos_idx)
    print(f"\nConfronto accoppiato diretto vs baseline attuale, solo OOS:")
    for label, net in variants.items():
        if label == baseline_label:
            continue
        diff = (net.reindex(oos_idx) - baseline_oos).dropna()
        mean_diff = diff.mean() * 12 * 100
        lo, hi = block_bootstrap_ci(diff.values, lambda r: pd.Series(r).mean() * 12 * 100, block_size=12, ci=0.90, seed=42)
        n_better = int((diff > 0).sum())
        print(f"  {label:<26}{mean_diff:+7.2f}pp/anno  CI90 [{lo:+.2f}, {hi:+.2f}] "
              f"({'ESCLUDE' if lo * hi > 0 else 'include'} lo zero)  mesi migliori {n_better}/{len(diff)}")

    perf_matrix = np.column_stack([variants[k].reindex(oos_idx).values for k in variants])
    n_splits = 8
    usable_len = (len(perf_matrix) // n_splits) * n_splits
    pbo = pbo_cscv(perf_matrix[-usable_len:], n_splits=n_splits)
    print(f"\nPBO-CSCV su {len(variants)} varianti, periodo OOS ({usable_len} mesi utili): {pbo*100:.1f}%")


def main():
    sleeve_returns = load_sleeve_returns()
    print(f"Campione a 4 sleeve (NTSG/AVWS/DBMFE/PPFB, Crypto escluso — dati insufficienti dal 2000): "
          f"{len(sleeve_returns)} mesi, {sleeve_returns.index[0].date()} -> {sleeve_returns.index[-1].date()}")
    run_part1(sleeve_returns)
    run_part2(sleeve_returns)


if __name__ == "__main__":
    main()
