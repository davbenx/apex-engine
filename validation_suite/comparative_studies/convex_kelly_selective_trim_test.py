"""
convex_kelly_selective_trim_test.py — Proposta diretta dell'utente: applicare
Kelly frazionario ai pesi TARGET delle 5 sleeve di Convex Stack, ma mantenere
il ribilanciamento attivo SOLO su Oro (PPFB) e WBTC (le uniche due a Reddito
Diverso, che compensano le minusvalenze), quando superano +50% del loro peso
target — la stessa regola gia' in produzione (`convex_engine.py`,
tolerance_max = target x1.5) — aggiungendo pero' un "limite temporale" al
trigger del trim.

Perche' questo NON e' una riproposta di Kelly Stack (gia' testato e scartato,
KELLY_STACK_SPEC.md): li' il ribilanciamento attivo toccava TUTTE le sleeve,
incluse le 3 a Reddito di Capitale (NTSG/AVWS/DBMFE, minusvalenze NON
compensabili) — la causa diagnosticata del crollo dello Sharpe netto
(turnover fiscalmente svantaggioso). Qui Kelly cambia SOLO il target verso
cui le sleeve driftano liberamente (nessuna vendita forzata su NTSG/AVWS/
DBMFE, mai) — il meccanismo di trim attivo resta identico a oggi nella sua
portata (solo le 2 sleeve gia' fiscalmente favorevoli), cambia solo la
soglia (target Kelly invece di target fisso) e si aggiunge un cancello
temporale per evitare di rincorrere oscillazioni ravvicinate.

Tre varianti di "limite temporale" testate (scelta dell'utente: "testerei
la migliore opzione"):
  - cooldown: dopo un trim su una sleeve, nessun altro trim sulla STESSA
    sleeve per almeno GATE_MONTHS mesi, anche se la soglia e' risuperata prima.
  - persistence: il trim scatta solo se il peso resta sopra la soglia per
    almeno GATE_MONTHS mesi CONSECUTIVI, non al primo superamento.
  - calendar: al massimo 1 trim per sleeve per anno solare.

Ogni combinazione (target fisso/Kelly) x (nessun cancello/cooldown/
persistence/calendar) e' un simulatore CUSTOM (non un wrapper di
framework/tax_engine.apply_italian_tax con rebalance_every, che ribilancia
TUTTE le sleeve verso il target ogni periodo programmato — un meccanismo
diverso da "non tradare mai NTSG/AVWS/DBMFE, tradare PPFB/WBTC solo sopra
soglia"): tiene traccia esplicita di valore/costo-base per sleeve (PMC,
stessa logica di framework/tax_engine.py) e di un pool cumulativo di
minusvalenze compensabili SOLO per le sleeve a Reddito Diverso.

Kelly target: f*=Sigma^-1 mu (stesso metodo di apex_v2_engine, frazione
0.25 per coerenza con la scelta gia' adottata in produzione per Apex — vedi
APEX_V2_SPEC.md §8.30), clippato a >=0 e rinormalizzato a somma 1 (Convex e'
sempre 100% investito, nessuna liquidita' residua come in Apex). Sigma/mu
stimati con shrinkage di Ledoit-Wolf (_calibrate_mu_sigma_corr, gia'
validato in kelly_backtest.py) — necessario qui, campione molto piu' corto
di quello di Apex (81 mesi, limitato da DBMFE_proxy dal 2019).

Metodologia walk-forward (stessa disciplina di kelly_backtest.py e di tutta
questa sessione): calibrato SOLO sulla prima meta' del campione (40 mesi),
applicato SENZA ri-ottimizzare sulla seconda meta' (41 mesi, OOS).
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
from kelly_backtest import fetch_universe, load_monthly_series, build_sleeve_returns, BACKTEST_TICKERS, _calibrate_mu_sigma_corr
from convex_never_sell_cost_test import CURRENT_WEIGHTS, TER, TAX_TYPE, DATA_DIR

TRIM_SLEEVES = ("PPFB_proxy", "WBTC_proxy")  # solo Reddito Diverso, invariato rispetto a produzione
TOLERANCE_MULT = 1.5  # +50% sopra il target -> trim, stesso valore gia' in produzione (convex_engine.py)
TAX_RATE = 0.26
KELLY_FRACTION = 0.25  # coerente con la scelta gia' adottata per Apex (APEX_V2_SPEC.md §8.30)
GATE_MONTHS = 12  # cooldown/persistence: 12 mesi, valore singolo scelto per il primo giro (non una griglia)


def compute_kelly_targets(calib: pd.DataFrame, keys: list[str], fraction: float = KELLY_FRACTION) -> dict[str, float]:
    mu, sigma, corr = _calibrate_mu_sigma_corr(calib, keys, use_shrinkage=True)
    mu_arr = np.array([mu[k] for k in keys])
    sigma_arr = np.array([sigma[k] for k in keys])
    Sigma = corr * np.outer(sigma_arr, sigma_arr)
    f_star = np.linalg.solve(Sigma, mu_arr)
    f_star = np.clip(f_star, 0.0, None) * fraction
    total = f_star.sum()
    if total <= 1e-9:
        return {k: CURRENT_WEIGHTS[k] for k in keys}  # fallback: nessun edge stimabile, resta sul target attuale
    return dict(zip(keys, f_star / total))


def simulate(sleeve_returns: pd.DataFrame, target_weights: dict[str, float], gate_mode: str, gate_months: int = GATE_MONTHS) -> pd.Series:
    """Simulatore custom: NTSG/AVWS/DBMFE driftano liberamente, mai tradate.
    PPFB/WBTC vengono trimmate a `target_weights[sleeve]` quando il peso corrente
    supera target*TOLERANCE_MULT E il gate (gate_mode) lo permette. Proceeds netti
    di tassa redistribuiti pro-rata sulle altre 4 sleeve (stessa idea del PAC che
    reinveste sempre, senza modellare nuovi versamenti espliciti).

    gate_mode: "none" (comportamento di produzione oggi, nessun cancello),
    "cooldown" (min gate_months mesi tra due trim sulla stessa sleeve),
    "persistence" (serve stare sopra soglia gate_months mesi consecutivi),
    "calendar" (max 1 trim per sleeve per anno solare).
    """
    keys = list(sleeve_returns.columns)
    values = {k: target_weights[k] for k in keys}  # NAV iniziale = 1.0
    cost_basis = dict(values)
    loss_pool = 0.0
    last_trim_month = {k: -10**9 for k in keys}
    months_over = {k: 0 for k in keys}
    trims_this_year = {k: {} for k in keys}  # sleeve -> {anno: conteggio}

    net_returns = []
    nav_prev = sum(values.values())
    for i, (dt, row) in enumerate(sleeve_returns.iterrows()):
        for k in keys:
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

            other_keys = [o for o in keys if o != k]
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


def main():
    if not DATA_DIR.exists() or not any(DATA_DIR.glob("*_monthly.csv")):
        fetch_universe(str(DATA_DIR), BACKTEST_TICKERS)
    if not (DATA_DIR / "EURUSD=X_monthly.csv").exists():
        fetch_universe(str(DATA_DIR), ["EURUSD=X"])

    prices = load_monthly_series(str(DATA_DIR), BACKTEST_TICKERS)
    eurusd = load_monthly_series(str(DATA_DIR), ["EURUSD=X"])["EURUSD=X"]
    prices_eur = {}
    for ticker, series in prices.items():
        idx = series.index.intersection(eurusd.index)
        prices_eur[ticker] = (series.reindex(idx) / eurusd.reindex(idx)).dropna()
    sleeve_returns = build_sleeve_returns(prices_eur)
    keys = list(sleeve_returns.columns)
    print(f"Campione: {len(sleeve_returns)} mesi, {sleeve_returns.index[0].date()} -> {sleeve_returns.index[-1].date()}")

    split = len(sleeve_returns) // 2
    calib, oos = sleeve_returns.iloc[:split], sleeve_returns.iloc[split:]
    print(f"TRAIN (calibrazione Kelly): {len(calib)} mesi ({calib.index[0].date()}->{calib.index[-1].date()})")
    print(f"TEST (OOS, nessuna ri-ottimizzazione): {len(oos)} mesi ({oos.index[0].date()}->{oos.index[-1].date()})")

    kelly_targets = compute_kelly_targets(calib, keys)
    blended_targets = {k: 0.5 * CURRENT_WEIGHTS[k] + 0.5 * kelly_targets[k] for k in keys}
    print(f"\nTarget attuali (fissi):  {', '.join(f'{k}={v*100:.1f}%' for k, v in CURRENT_WEIGHTS.items())}")
    print(f"Target Kelly (frac 0.25): {', '.join(f'{k}={v*100:.1f}%' for k, v in kelly_targets.items())}")
    print(f"Target blend 50/50:      {', '.join(f'{k}={v*100:.1f}%' for k, v in blended_targets.items())}")
    print("  ^ blend aggiunto per prudenza: la riallocazione Kelly pura e' estrema (NTSG quasi "
          "azzerato) su un campione di calibrazione corto (40 mesi) e potenzialmente specifico "
          "al regime 2019-2023 (shock tassi 2022) — vedi discussione nel README.")

    variants = {}
    for tgt_label, tgt in [("Fisso", CURRENT_WEIGHTS), ("Kelly", kelly_targets), ("Blend50/50", blended_targets)]:
        for gate_label, gate_mode in [("nessun cancello (oggi)", "none"), ("cooldown 12m", "cooldown"),
                                       ("persistence 12m", "persistence"), ("calendar 1/anno", "calendar")]:
            key = f"{tgt_label} + {gate_label}"
            variants[key] = simulate(sleeve_returns, tgt, gate_mode)

    print(f"\n{'Variante':<38}{'CAGR':>9}{'Sharpe':>9}{'MaxDD':>9}{'Calmar':>9}")
    for label, net in variants.items():
        c, s, dd, cal = _cagr(net, 12), _sharpe(net, periods_per_year=12), _max_drawdown(net), _calmar(net, 12)
        print(f"{label:<38}{c*100:>8.2f}%{s:>9.2f}{dd*100:>8.2f}%{cal:>9.2f}")

    print(f"\n{'Variante (solo OOS)':<38}{'CAGR':>9}{'Sharpe':>9}{'MaxDD':>9}{'Calmar':>9}")
    oos_idx = oos.index
    for label, net in variants.items():
        sub = net.reindex(oos_idx).dropna()
        c, s, dd, cal = _cagr(sub, 12), _sharpe(sub, periods_per_year=12), _max_drawdown(sub), _calmar(sub, 12)
        print(f"{label:<38}{c*100:>8.2f}%{s:>9.2f}{dd*100:>8.2f}%{cal:>9.2f}")

    baseline_label = "Fisso + nessun cancello (oggi)"
    baseline_oos = variants[baseline_label].reindex(oos_idx)
    print(f"\nConfronto accoppiato diretto vs baseline attuale ({baseline_label}), solo OOS:")
    for label, net in variants.items():
        if label == baseline_label:
            continue
        diff = (net.reindex(oos_idx) - baseline_oos).dropna()
        mean_diff = diff.mean() * 12 * 100
        lo, hi = block_bootstrap_ci(diff.values, lambda r: pd.Series(r).mean() * 12 * 100, block_size=6, ci=0.90, seed=42)
        print(f"  {label:<38}{mean_diff:+7.2f}pp/anno  CI90 [{lo:+.2f}, {hi:+.2f}] "
              f"({'ESCLUDE' if lo * hi > 0 else 'include'} lo zero)")

    perf_matrix = np.column_stack([variants[k].reindex(oos_idx).values for k in variants])
    n_splits = 6
    usable_len = (len(perf_matrix) // n_splits) * n_splits
    if usable_len >= n_splits * 2:
        pbo = pbo_cscv(perf_matrix[-usable_len:], n_splits=n_splits)
        print(f"\nPBO-CSCV su {len(variants)} varianti, periodo OOS: {pbo*100:.1f}%")
    else:
        print(f"\nPBO-CSCV non calcolabile: campione OOS troppo corto ({len(oos_idx)} mesi) per {n_splits} split utili.")


if __name__ == "__main__":
    main()
