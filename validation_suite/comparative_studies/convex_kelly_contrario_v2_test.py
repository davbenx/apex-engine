"""
convex_kelly_contrario_v2_test.py — Definisce e testa due meccanismi
concreti per "Kelly al contrario su Convex", richiesti esplicitamente
dall'utente dopo che il primo tentativo (PAC contrarian a 12 mesi,
`convex_contrarian_kelly_pac_test.py`) aveva dato risultati deboli/misti
sia sul campione corto (81 mesi) sia su quello esteso (313 mesi, vedi
`convex_kelly_extended_history_retest.py` Parte 2).

Meccanismo A raffinata — PAC contrarian con finestra rivista
--------------------------------------------------------------
Il test originale usava una finestra di 12 mesi per lo z-score contrarian
cross-sezionale. Ma un rendimento trailing a 12 mesi e' storicamente un
segnale di MOMENTUM (Jegadeesh-Titman 1993), non di reversal — l'effetto
di reversal di lungo periodo (De Bondt-Thaler 1985) opera su orizzonti di
3-5 anni. Qui si testano finestre 24/36/60 mesi, incrociate con uno
shrinkage extra della correlazione (blend 30% verso l'identita') per
verificare la robustezza della stima Kelly stessa.

Meccanismo B — Kelly sul lato vendita
--------------------------------------
Invece di ribilanciare PPFB a soglia fissa (+50% sul target), la soglia
di trim diventa funzione di un edge stimato in stile Kelly (mu/sigma^2)
su una finestra trailing (12 o 24 mesi), mappato attraverso un
percentile ESPANSIVO (nessun lookahead — solo dati fino a t) della sua
stessa storia:
  - edge alto (trend forte, percentile vicino a 1) -> soglia si allarga
    (fino a 1.85x il target) -> lascia correre la posizione.
  - edge basso/negativo (trend esaurito, percentile vicino a 0) -> soglia
    si restringe (fino a 1.15x il target) -> vende prima, protegge i
    guadagni prima di un'inversione.
Meccanismo "standalone": usa solo la storia della sleeve stessa, nessun
accoppiamento con Apex (rispetta il principio "ogni motore robusto da
solo" dichiarato dall'utente).

Entrambi testati sul campione esteso a 4 sleeve (NTSG/AVWS/DBMFE/PPFB,
2000-09 -> 2026-09, 313 mesi) gia' usato in
`convex_kelly_extended_history_retest.py`, stesso split TRAIN/TEST 50/50,
stessa disciplina di reporting (CAGR/Sharpe/MaxDD, CI bootstrap a blocchi,
PBO-CSCV).
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
GATE_MONTHS = 12
MONTHLY_CONTRIBUTION = 0.01
START_DATE = "2000-09-30"


def load_sleeve_returns() -> pd.DataFrame:
    df = pd.read_csv(DATA_FILE, index_col=0, parse_dates=True)[KEYS]
    return df.loc[START_DATE:].dropna(how="any")


# ============================================================================
# Meccanismo B — Kelly sul lato vendita (soglia di trim dinamica)
# ============================================================================

def edge_percentile_series(edge: pd.Series) -> pd.Series:
    """Percentile espansivo di edge[t] dentro la storia edge[0..t] — niente lookahead."""
    vals = edge.values
    n = len(vals)
    out = np.full(n, np.nan)
    for i in range(n):
        if np.isnan(vals[i]):
            continue
        hist = vals[: i + 1]
        hist = hist[~np.isnan(hist)]
        if len(hist) < 6:
            continue
        out[i] = (hist <= vals[i]).mean()
    return pd.Series(out, index=edge.index)


def dynamic_threshold_series(returns_col: pd.Series, window: int, base: float = TOLERANCE_MULT,
                              half_range: float = 0.35) -> pd.Series:
    mu = returns_col.rolling(window).mean()
    var = returns_col.rolling(window).var(ddof=0)
    edge = mu / var.replace(0, np.nan)
    pct = edge_percentile_series(edge)
    thr = base + (pct - 0.5) * 2 * half_range
    return thr.fillna(base).clip(base - half_range, base + half_range)


def simulate_trim_dynamic(sleeve_returns: pd.DataFrame, threshold: pd.Series | float,
                           gate_mode: str, gate_months: int = GATE_MONTHS) -> pd.Series:
    values = {k: CURRENT_WEIGHTS[k] for k in KEYS}
    cost_basis = dict(values)
    loss_pool = 0.0
    last_trim_month = {k: -10**9 for k in KEYS}
    months_over = {k: 0 for k in KEYS}

    net_returns = []
    nav_prev = sum(values.values())
    for i, (dt, row) in enumerate(sleeve_returns.iterrows()):
        for k in KEYS:
            values[k] *= (1.0 + row[k] - TER[k] / 12.0)
        nav_before_trim = sum(values.values())
        thr_now = threshold.iloc[i] if isinstance(threshold, pd.Series) else threshold

        for k in TRIM_SLEEVES:
            w = values[k] / nav_before_trim
            tgt = CURRENT_WEIGHTS[k]
            is_over = w > tgt * thr_now
            if not is_over:
                months_over[k] = 0
                continue
            months_over[k] += 1
            if gate_mode == "cooldown" and (i - last_trim_month[k]) < gate_months:
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

        nav_after = sum(values.values())
        net_returns.append(nav_after / nav_prev - 1.0)
        nav_prev = nav_after

    return pd.Series(net_returns, index=sleeve_returns.index)


def run_mechanism_b(sleeve_returns: pd.DataFrame):
    print("\n" + "=" * 78)
    print("MECCANISMO B — Kelly sul lato vendita (soglia di trim dinamica su PPFB)")
    print("=" * 78)

    split = len(sleeve_returns) // 2
    oos = sleeve_returns.iloc[split:]
    oos_idx = oos.index

    ppfb = sleeve_returns["PPFB_proxy"]
    thr_w12 = dynamic_threshold_series(ppfb, 12)
    thr_w24 = dynamic_threshold_series(ppfb, 24)

    variants = {}
    for thr_label, thr in [("Fisso 1.5x", TOLERANCE_MULT), ("Dinamico w=12", thr_w12), ("Dinamico w=24", thr_w24)]:
        for gate_label, gate_mode in [("nessun cancello", "none"), ("cooldown 12m", "cooldown")]:
            key = f"{thr_label} + {gate_label}"
            variants[key] = simulate_trim_dynamic(sleeve_returns, thr, gate_mode)

    print(f"\n{'Variante (solo OOS)':<32}{'CAGR':>9}{'Sharpe':>9}{'MaxDD':>9}{'Calmar':>9}")
    for label, net in variants.items():
        sub = net.reindex(oos_idx).dropna()
        c, s, dd, cal = _cagr(sub, 12), _sharpe(sub, periods_per_year=12), _max_drawdown(sub), _calmar(sub, 12)
        print(f"{label:<32}{c*100:>8.2f}%{s:>9.2f}{dd*100:>8.2f}%{cal:>9.2f}")

    baseline_label = "Fisso 1.5x + nessun cancello"
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

    n_trims = {}
    for thr_label, thr in [("Fisso 1.5x", TOLERANCE_MULT), ("Dinamico w=12", thr_w12), ("Dinamico w=24", thr_w24)]:
        net = variants[f"{thr_label} + nessun cancello"]
        n_trims[thr_label] = None
    print("\n(soglie dinamiche — statistiche descrittive sul periodo OOS)")
    for label, thr in [("w=12", thr_w12), ("w=24", thr_w24)]:
        sub = thr.reindex(oos_idx).dropna()
        print(f"  Dinamico {label}: media={sub.mean():.3f}x  min={sub.min():.3f}x  max={sub.max():.3f}x")


# ============================================================================
# Meccanismo A raffinata — PAC contrarian, finestra e shrinkage rivisti
# ============================================================================

def contrarian_mu_series(returns: pd.DataFrame, window: int) -> pd.DataFrame:
    trailing = (1 + returns[KEYS]).rolling(window).apply(lambda x: x.prod() - 1.0, raw=True)
    z = trailing.sub(trailing.mean(axis=1), axis=0).div(trailing.std(axis=1, ddof=0).replace(0, np.nan), axis=0)
    return (-z).fillna(0.0)


def build_sigma(calib: pd.DataFrame, extra_shrink: float = 0.0) -> np.ndarray:
    mu, sigma, corr = _calibrate_mu_sigma_corr(calib, KEYS, use_shrinkage=True)
    sigma_arr = np.array([sigma[k] for k in KEYS])
    if extra_shrink > 0:
        corr = (1 - extra_shrink) * corr + extra_shrink * np.eye(len(KEYS))
    return corr * np.outer(sigma_arr, sigma_arr)


def simulate_pac(sleeve_returns: pd.DataFrame, mu_contrarian: pd.DataFrame | None, Sigma: np.ndarray | None,
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
                und_keys = list(underweight.keys())
                if len(und_keys) == 1:
                    f_star = {und_keys[0]: 1.0}
                else:
                    idx = [KEYS.index(k) for k in und_keys]
                    Sigma_sub = Sigma[np.ix_(idx, idx)]
                    mu_sub = np.array([mu_contrarian.iloc[i][k] for k in und_keys])
                    try:
                        f_sub = np.linalg.solve(Sigma_sub, mu_sub)
                    except np.linalg.LinAlgError:
                        f_sub = np.zeros(len(und_keys))
                    f_sub = np.clip(f_sub, 0.0, None)
                    f_star = dict(zip(und_keys, f_sub))
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


def run_mechanism_a(sleeve_returns: pd.DataFrame):
    print("\n" + "=" * 78)
    print("MECCANISMO A RAFFINATA — PAC contrarian, finestra 24/36/60m + extra shrinkage")
    print("=" * 78)

    split = len(sleeve_returns) // 2
    calib, oos = sleeve_returns.iloc[:split], sleeve_returns.iloc[split:]
    oos_idx = oos.index

    variants = {}
    variants["Winner-take-all (oggi)"] = simulate_pac(sleeve_returns, None, None, "winner_take_all")
    variants["Deficit-proporzionale"] = simulate_pac(sleeve_returns, None, None, "deficit_proportional")

    for window in (12, 24, 36, 60):
        mu_contrarian = contrarian_mu_series(sleeve_returns, window)
        for shrink_label, extra_shrink in [("shrink std", 0.0), ("shrink extra 30%", 0.3)]:
            Sigma = build_sigma(calib, extra_shrink)
            label = f"Kelly contrarian w={window}m, {shrink_label}"
            variants[label] = simulate_pac(sleeve_returns, mu_contrarian, Sigma, "kelly_contrarian")

    print(f"\n{'Variante (solo OOS)':<38}{'CAGR':>9}{'Sharpe':>9}{'MaxDD':>9}{'Calmar':>9}")
    for label, net in variants.items():
        sub = net.reindex(oos_idx).dropna()
        c, s, dd, cal = _cagr(sub, 12), _sharpe(sub, periods_per_year=12), _max_drawdown(sub), _calmar(sub, 12)
        print(f"{label:<38}{c*100:>8.2f}%{s:>9.2f}{dd*100:>8.2f}%{cal:>9.2f}")

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
        print(f"  {label:<38}{mean_diff:+7.2f}pp/anno  CI90 [{lo:+.2f}, {hi:+.2f}] "
              f"({'ESCLUDE' if lo * hi > 0 else 'include'} lo zero)  mesi migliori {n_better}/{len(diff)}")

    perf_matrix = np.column_stack([variants[k].reindex(oos_idx).values for k in variants])
    n_splits = 8
    usable_len = (len(perf_matrix) // n_splits) * n_splits
    pbo = pbo_cscv(perf_matrix[-usable_len:], n_splits=n_splits)
    print(f"\nPBO-CSCV su {len(variants)} varianti, periodo OOS ({usable_len} mesi utili): {pbo*100:.1f}%")


def main():
    sleeve_returns = load_sleeve_returns()
    print(f"Campione a 4 sleeve (NTSG/AVWS/DBMFE/PPFB): {len(sleeve_returns)} mesi, "
          f"{sleeve_returns.index[0].date()} -> {sleeve_returns.index[-1].date()}")
    run_mechanism_b(sleeve_returns)
    run_mechanism_a(sleeve_returns)


if __name__ == "__main__":
    main()
