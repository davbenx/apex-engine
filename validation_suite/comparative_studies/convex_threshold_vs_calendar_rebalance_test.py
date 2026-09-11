"""
convex_threshold_vs_calendar_rebalance_test.py — Ribilanciamento "a soglia
di tolleranza" (tolerance-band rebalancing, Daryanani 2008, Masters 2003)
contro il ribilanciamento a calendario, richiesto esplicitamente
dall'utente come strategia accademica non ancora provata su Convex Stack.

Letteratura di riferimento: ribilanciare quando il peso di una sleeve si
allontana dal target oltre una soglia (non a data fissa) puo' catturare il
"rebalancing premium" in modo piu' efficiente — meno eventi fiscali totali
a parita' di aderenza al target, perche' un asset che oscilla dentro la
banda senza mai romperla non genera mai una vendita/tassa inutile.

Riusa lo stesso universo/pesi/TER/tassazione di convex_weights_grid_test.py
e convex_never_sell_cost_test.py (stessi 5 proxy, pesi target 45/15/25/
7.5/7.5) e lo stesso framework (`apply_italian_tax`, ora esteso con
`rebalance_threshold` — vedi tax_engine.py). Confronta contro le stesse 4
baseline a calendario gia' testate (mensile/trimestrale/annuale/mai), non
le riesegue da zero.
"""
from __future__ import annotations
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "validation_suite" / "framework"))
sys.path.insert(0, str(REPO_ROOT / "validation_suite" / "kelly_stack"))
from metrics import cagr, sharpe, max_drawdown, calmar
from tax_engine import apply_italian_tax
from statistical_validation import pbo_cscv, block_bootstrap_ci
from kelly_backtest import fetch_universe, load_monthly_series, build_sleeve_returns, BACKTEST_TICKERS

DATA_DIR = Path(__file__).parent / "convex_grid_data"  # stessa cache di convex_never_sell_cost_test.py

CURRENT_WEIGHTS = {"NTSG_proxy": 0.45, "AVWS_proxy": 0.15, "DBMFE_proxy": 0.25, "PPFB_proxy": 0.075, "WBTC_proxy": 0.075}
TER = {"NTSG_proxy": 0.0025, "AVWS_proxy": 0.0039, "DBMFE_proxy": 0.0075, "PPFB_proxy": 0.0012, "WBTC_proxy": 0.0015}
TAX_TYPE = {
    "NTSG_proxy": "REDDITO_CAPITALE", "AVWS_proxy": "REDDITO_CAPITALE", "DBMFE_proxy": "REDDITO_CAPITALE",
    "PPFB_proxy": "REDDITO_DIVERSO", "WBTC_proxy": "REDDITO_DIVERSO",
}

CALENDAR_VARIANTS = [
    ("Mensile (calendario)", {"rebalance_every": 1}),
    ("Trimestrale (calendario)", {"rebalance_every": 3}),
    ("Annuale (calendario)", {"rebalance_every": 12}),
    ("MAI (policy reale Convex)", {"rebalance_every": None}),
]
THRESHOLD_VARIANTS = [
    ("Soglia 3 punti peso", {"rebalance_threshold": 0.03}),
    ("Soglia 5 punti peso", {"rebalance_threshold": 0.05}),
    ("Soglia 10 punti peso", {"rebalance_threshold": 0.10}),
    ("Soglia 15 punti peso", {"rebalance_threshold": 0.15}),
    ("Soglia 20 punti peso", {"rebalance_threshold": 0.20}),
]
ALL_VARIANTS = CALENDAR_VARIANTS + THRESHOLD_VARIANTS


def run_one(returns_df: pd.DataFrame, kwargs: dict, sub_returns: pd.DataFrame = None):
    weights_with_ter = returns_df.copy()
    for k, ter in TER.items():
        weights_with_ter[k] = returns_df[k] - ter / 12

    net_full = apply_italian_tax(weights_with_ter, CURRENT_WEIGHTS, tax_types=TAX_TYPE, **kwargs)
    gross_full = (weights_with_ter * pd.Series(CURRENT_WEIGHTS)).sum(axis=1)

    if sub_returns is not None:
        idx = sub_returns.index
        net, gross = net_full.loc[idx], gross_full.loc[idx]
    else:
        net, gross = net_full, gross_full

    return {
        "net": net, "gross": gross,
        "cagr_net": cagr(net), "sharpe_net": sharpe(net), "maxdd_net": max_drawdown(net), "calmar_net": calmar(net),
        "cagr_gross": cagr(gross),
    }


def n_rebalance_events(returns_df: pd.DataFrame, kwargs: dict) -> int:
    """Conta quante volte scatta il ribilanciamento (evento fiscale), per
    quantificare il costo OPERATIVO oltre a quello fiscale/di rendimento —
    meno eventi a parita' di rendimento e' un vantaggio pratico a se'."""
    weights_with_ter = returns_df.copy()
    for k, ter in TER.items():
        weights_with_ter[k] = returns_df[k] - ter / 12
    keys = list(CURRENT_WEIGHTS.keys())
    nav = 1.0
    value = {k: CURRENT_WEIGHTS[k] * nav for k in keys}
    events = 0
    rebalance_every = kwargs.get("rebalance_every", 1)
    rebalance_threshold = kwargs.get("rebalance_threshold")
    for i, (_, row) in enumerate(weights_with_ter.iterrows()):
        for k in keys:
            value[k] *= (1 + row[k])
        weights_now = {k: value[k] for k in keys}
        nav_est = sum(weights_now.values())  # senza leva (somma pesi target = 1.0 qui), coincide col notional totale
        if rebalance_threshold is not None:
            drift = max(abs(weights_now[k] / nav_est - CURRENT_WEIGHTS[k]) for k in keys) if nav_est > 1e-12 else 0.0
            should = drift > rebalance_threshold
        else:
            should = rebalance_every is not None and (i + 1) % rebalance_every == 0
        if should:
            events += 1
            for k in keys:
                value[k] = CURRENT_WEIGHTS[k] * nav_est
    return events


def print_table(results: dict, events: dict, period_label: str):
    print(f"\n--- {period_label} ---")
    print(f"{'Variante':<28}{'CAGR netto':>12}{'CAGR lordo':>12}{'Drag fiscale':>13}{'Sharpe netto':>14}{'MaxDD netto':>13}{'Calmar':>9}{'N eventi':>10}")
    for label, r in results.items():
        drag = (r["cagr_gross"] - r["cagr_net"]) * 100
        print(f"{label:<28}{r['cagr_net']*100:>11.2f}%{r['cagr_gross']*100:>11.2f}%{drag:>12.2f}pp"
              f"{r['sharpe_net']:>14.2f}{r['maxdd_net']*100:>12.2f}%{r['calmar_net']:>9.2f}{events.get(label, '-'):>10}")


def main():
    if not DATA_DIR.exists() or not any(DATA_DIR.glob("*_monthly.csv")):
        print(f"[*] Nessun dato in cache in {DATA_DIR}, scarico da Yahoo Finance...")
        fetch_universe(str(DATA_DIR), BACKTEST_TICKERS)
    if not (DATA_DIR / "EURUSD=X_monthly.csv").exists():
        fetch_universe(str(DATA_DIR), ["EURUSD=X"])

    prices = load_monthly_series(str(DATA_DIR), BACKTEST_TICKERS)
    eurusd = load_monthly_series(str(DATA_DIR), ["EURUSD=X"])["EURUSD=X"]
    prices_eur = {}
    for ticker, series in prices.items():
        common_idx = series.index.intersection(eurusd.index)
        prices_eur[ticker] = (series.reindex(common_idx) / eurusd.reindex(common_idx)).dropna()
    sleeve_returns = build_sleeve_returns(prices_eur)
    print(f"Campione: {len(sleeve_returns)} mesi, {sleeve_returns.index[0].date()} -> {sleeve_returns.index[-1].date()}")

    split_idx = len(sleeve_returns) // 2
    train = sleeve_returns.iloc[:split_idx]
    test = sleeve_returns.iloc[split_idx:]
    print(f"TRAIN: {len(train)} mesi ({train.index[0].date()}->{train.index[-1].date()})  |  "
          f"TEST: {len(test)} mesi ({test.index[0].date()}->{test.index[-1].date()})")

    results_full, results_test, events_full = {}, {}, {}
    for label, kwargs in ALL_VARIANTS:
        results_full[label] = run_one(sleeve_returns, kwargs)
        results_test[label] = run_one(sleeve_returns, kwargs, sub_returns=test)
        events_full[label] = n_rebalance_events(sleeve_returns, kwargs)

    print_table(results_full, events_full, "CAMPIONE PIENO")
    print_table(results_test, events_full, "TEST (fuori campione, meta' piu' recente)")

    monthly_label = CALENDAR_VARIANTS[0][0]
    best_threshold_label = max(THRESHOLD_VARIANTS, key=lambda kv: results_test[kv[0]]["sharpe_net"])[0]
    print(f"\nMiglior soglia su Sharpe netto (periodo TEST): {best_threshold_label} "
          f"(Sharpe {results_test[best_threshold_label]['sharpe_net']:.3f} contro "
          f"{results_test[monthly_label]['sharpe_net']:.3f} del mensile)")

    diff_full = (results_full[best_threshold_label]["net"] - results_full[monthly_label]["net"]).dropna()
    mean_diff_full = diff_full.mean() * 12 * 100
    lo_f, hi_f = block_bootstrap_ci(diff_full.values, lambda r: pd.Series(r).mean() * 12 * 100, block_size=6, ci=0.90, seed=42)
    print(f"\n{best_threshold_label} meno Mensile (campione pieno): {mean_diff_full:+.2f}pp/anno, "
          f"CI 90% [{lo_f:+.2f}, {hi_f:+.2f}] ({'ESCLUDE' if lo_f * hi_f > 0 else 'include'} lo zero)")

    diff_test = (results_test[best_threshold_label]["net"] - results_test[monthly_label]["net"]).dropna()
    mean_diff_test = diff_test.mean() * 12 * 100
    lo_t, hi_t = block_bootstrap_ci(diff_test.values, lambda r: pd.Series(r).mean() * 12 * 100, block_size=6, ci=0.90, seed=42)
    print(f"{best_threshold_label} meno Mensile (solo TEST): {mean_diff_test:+.2f}pp/anno, "
          f"CI 90% [{lo_t:+.2f}, {hi_t:+.2f}] ({'ESCLUDE' if lo_t * hi_t > 0 else 'include'} lo zero)")

    never_label = CALENDAR_VARIANTS[3][0]
    print(f"\n--- Confronto contro la policy REALE di produzione ({never_label}), non contro il mensile ---")
    for label, r_test in [(l, results_test[l]) for l, _ in THRESHOLD_VARIANTS + [CALENDAR_VARIANTS[2]]]:
        diff = (r_test["net"] - results_test[never_label]["net"]).dropna()
        mean_diff = diff.mean() * 12 * 100
        lo, hi = block_bootstrap_ci(diff.values, lambda r: pd.Series(r).mean() * 12 * 100, block_size=6, ci=0.90, seed=42)
        print(f"  {label:<26} vs {never_label}: {mean_diff:+6.2f}pp/anno CAGR  CI90 [{lo:+.2f},{hi:+.2f}] "
              f"({'ESCLUDE' if lo * hi > 0 else 'include'} lo zero)  Sharpe {r_test['sharpe_net']:.3f} vs {results_test[never_label]['sharpe_net']:.3f}  "
              f"MaxDD {r_test['maxdd_net']*100:.2f}% vs {results_test[never_label]['maxdd_net']*100:.2f}%")

    perf_matrix = np.column_stack([results_test[label]["net"].values for label, _ in ALL_VARIANTS])
    n_splits = 6
    usable_len = (len(perf_matrix) // n_splits) * n_splits
    if usable_len >= n_splits * 2:
        pbo = pbo_cscv(perf_matrix[-usable_len:], n_splits=n_splits)
        print(f"\nPBO-CSCV su {len(ALL_VARIANTS)} varianti (calendario + soglia), periodo TEST: {pbo*100:.1f}%")


if __name__ == "__main__":
    main()
