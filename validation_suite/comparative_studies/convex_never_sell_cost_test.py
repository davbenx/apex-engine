"""
convex_never_sell_cost_test.py — Quantifica il costo/beneficio della policy
"mai vendere" di Convex Stack (IPS: ribilanciamento solo tramite nuovi
versamenti, zero vendite) contro un ribilanciamento periodico ipotetico
verso i pesi target ATTUALI (45/15/25/7.5/7.5, invariati — qui si testa la
FREQUENZA di ribilanciamento, non i pesi, gia' testati in
convex_weights_grid_test.py).

Letteratura di riferimento: rebalancing premium / variance harvesting
(Willenbrock 2011, Chambers & Zdanowicz) — ribilanciare periodicamente tra
asset scorrelati puo' aggiungere rendimento "vendendo alto, comprando
basso" in modo automatico. Ma ogni ribilanciamento in Italia e' un evento
fiscale (26% sulla plusvalenza realizzata) — il confronto onesto e' quindi
NETTO di tasse, non lordo.

BUG TROVATO E CORRETTO mentre si costruiva questo test:
framework/tax_engine.py:apply_italian_tax aveva un parametro
`rebalance_every` nella firma ma MAI letto nel corpo della funzione — la
funzione ribilanciava incondizionatamente ogni periodo, a prescindere dal
valore passato. Significa che convex_weights_grid_test.py (test sui PESI,
non sulla frequenza) ha finora implicitamente assunto ribilanciamento
MENSILE per tutte le combinazioni testate — un'assunzione diversa dalla
policy reale di Convex (mai vendere), quindi quella conclusione ("nessuna
combinazione di pesi batte l'attuale") vale sotto ribilanciamento mensile
ipotetico, non sotto la policy reale. Corretto: rebalance_every ora
implementato (None = mai ribilanciare dopo l'allocazione iniziale, N =
ogni N periodi), con test dedicati in test_tax_engine.py, default=1
invariato per compatibilita' con tutti i chiamanti esistenti.

Varianti testate, stessi pesi target 45/15/25/7.5/7.5, stesso universo
proxy/TER/tassazione di convex_weights_grid_test.py:
  - Mensile (rebalance_every=1)
  - Trimestrale (rebalance_every=3)
  - Annuale (rebalance_every=12)
  - MAI (rebalance_every=None) — la policy REALE di Convex
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
from tax_engine import apply_italian_tax, liquidation_tax_adjusted_nav
from statistical_validation import pbo_cscv, block_bootstrap_ci
from kelly_backtest import fetch_universe, load_monthly_series, build_sleeve_returns, BACKTEST_TICKERS

DATA_DIR = Path(__file__).parent / "convex_grid_data"  # stessa cache, riusata

CURRENT_WEIGHTS = {"NTSG_proxy": 0.45, "AVWS_proxy": 0.15, "DBMFE_proxy": 0.25, "PPFB_proxy": 0.075, "WBTC_proxy": 0.075}
TER = {"NTSG_proxy": 0.0025, "AVWS_proxy": 0.0039, "DBMFE_proxy": 0.0075, "PPFB_proxy": 0.0012, "WBTC_proxy": 0.0015}
TAX_TYPE = {
    "NTSG_proxy": "REDDITO_CAPITALE", "AVWS_proxy": "REDDITO_CAPITALE", "DBMFE_proxy": "REDDITO_CAPITALE",
    "PPFB_proxy": "REDDITO_DIVERSO", "WBTC_proxy": "REDDITO_DIVERSO",
}

FREQUENCIES = [
    ("Mensile (rebalance_every=1)", 1),
    ("Trimestrale (rebalance_every=3)", 3),
    ("Annuale (rebalance_every=12)", 12),
    ("MAI (rebalance_every=None, policy reale Convex)", None),
]


def run_one(returns_df: pd.DataFrame, rebalance_every, sub_returns: pd.DataFrame = None):
    weights_with_ter = returns_df.copy()
    for k, ter in TER.items():
        weights_with_ter[k] = returns_df[k] - ter / 12

    net_full, final_state = apply_italian_tax(weights_with_ter, CURRENT_WEIGHTS, tax_types=TAX_TYPE,
                                               rebalance_every=rebalance_every, return_final_state=True)
    gross_full = (weights_with_ter * pd.Series(CURRENT_WEIGHTS)).sum(axis=1)

    if sub_returns is not None:
        idx = sub_returns.index
        net, gross = net_full.loc[idx], gross_full.loc[idx]
    else:
        net, gross = net_full, gross_full

    # NAV "come se si liquidasse tutto oggi" (fine campione, 2026-09) — mai zero anche con
    # rebalance_every=None, che non tassa mai lungo il percorso: la tassa e' solo posticipata,
    # non azzerata (concern d'audit #3, vedi README). Confronto onesto contro varianti che
    # pagano le tasse lungo il percorso, che il solo CAGR "drift" qui sopra non rende.
    liquidated_nav = liquidation_tax_adjusted_nav(final_state, TAX_TYPE)
    drift_nav = float((1 + net_full).prod())
    latent_tax_drag_pct = (drift_nav - liquidated_nav) / drift_nav * 100 if drift_nav > 0 else 0.0

    return {
        "net": net, "gross": gross,
        "cagr_net": cagr(net), "sharpe_net": sharpe(net), "maxdd_net": max_drawdown(net), "calmar_net": calmar(net),
        "cagr_gross": cagr(gross), "liquidated_nav": liquidated_nav, "drift_nav": drift_nav,
        "latent_tax_drag_pct": latent_tax_drag_pct,
    }


def print_table(results: dict, period_label: str):
    print(f"\n--- {period_label} ---")
    print(f"{'Frequenza':<48}{'CAGR netto':>12}{'CAGR lordo':>12}{'Drag fiscale':>13}{'Sharpe netto':>14}{'MaxDD netto':>13}{'Calmar':>9}")
    for label, r in results.items():
        drag = (r["cagr_gross"] - r["cagr_net"]) * 100
        print(f"{label:<48}{r['cagr_net']*100:>11.2f}%{r['cagr_gross']*100:>11.2f}%{drag:>12.2f}pp{r['sharpe_net']:>14.2f}{r['maxdd_net']*100:>12.2f}%{r['calmar_net']:>9.2f}")


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

    results_full, results_test = {}, {}
    for label, freq in FREQUENCIES:
        results_full[label] = run_one(sleeve_returns, freq)
        results_test[label] = run_one(sleeve_returns, freq, sub_returns=test)

    print_table(results_full, "CAMPIONE PIENO")
    print_table(results_test, "TEST (fuori campione, meta' piu' recente)")

    never_label, monthly_label = FREQUENCIES[3][0], FREQUENCIES[0][0]

    print(f"\n--- Passivita' fiscale LATENTE se si liquidasse tutto oggi ({sleeve_returns.index[-1].date()}) ---")
    print(f"{'Frequenza':<48}{'NAV drift (mai tassato)':>24}{'NAV liquidato oggi':>20}{'Tassa latente':>15}")
    for label, freq in FREQUENCIES:
        r = results_full[label]
        print(f"{label:<48}{r['drift_nav']:>23.4f}x{r['liquidated_nav']:>19.4f}x{r['latent_tax_drag_pct']:>14.2f}%")
    never_drag = results_full[never_label]["latent_tax_drag_pct"]
    monthly_drag = results_full[monthly_label]["latent_tax_drag_pct"]
    print(f"\n'{never_label}' ha una tassa latente ({never_drag:.2f}% del NAV drift) che '{monthly_label}' "
          f"non ha ({monthly_drag:.2f}%, gia' pagata lungo il percorso) — il confronto sopra sul CAGR "
          "netto NON la include: e' un vantaggio reale (differire ha valore temporale) ma non gratuito, "
          "e questa e' la sua dimensione quantificata, non zero.")
    diff_full = (results_full[never_label]["net"] - results_full[monthly_label]["net"]).dropna()
    mean_diff_full = diff_full.mean() * 12 * 100
    lo_f, hi_f = block_bootstrap_ci(diff_full.values, lambda r: pd.Series(r).mean() * 12 * 100, block_size=6, ci=0.90, seed=42)
    print(f"\nConfronto diretto MAI meno MENSILE (campione pieno): {mean_diff_full:+.2f}pp/anno, "
          f"CI 90% [{lo_f:+.2f}, {hi_f:+.2f}] ({'ESCLUDE' if lo_f * hi_f > 0 else 'include'} lo zero)")

    diff_test = (results_test[never_label]["net"] - results_test[monthly_label]["net"]).dropna()
    mean_diff_test = diff_test.mean() * 12 * 100
    lo_t, hi_t = block_bootstrap_ci(diff_test.values, lambda r: pd.Series(r).mean() * 12 * 100, block_size=6, ci=0.90, seed=42)
    print(f"Confronto diretto MAI meno MENSILE (solo TEST): {mean_diff_test:+.2f}pp/anno, "
          f"CI 90% [{lo_t:+.2f}, {hi_t:+.2f}] ({'ESCLUDE' if lo_t * hi_t > 0 else 'include'} lo zero)")

    perf_matrix = np.column_stack([results_test[label]["net"].values for label, _ in FREQUENCIES])
    n_splits = 6
    usable_len = (len(perf_matrix) // n_splits) * n_splits
    if usable_len >= n_splits * 2:
        pbo = pbo_cscv(perf_matrix[-usable_len:], n_splits=n_splits)
        print(f"\nPBO-CSCV su {len(FREQUENCIES)} frequenze di ribilanciamento, periodo TEST: {pbo*100:.1f}%")


if __name__ == "__main__":
    main()
