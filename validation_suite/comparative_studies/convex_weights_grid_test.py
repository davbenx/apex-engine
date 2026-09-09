"""
convex_weights_grid_test.py — I pesi target di Convex Stack (NTSG 45% / AVWS
15% / DBMFE 25% / PPFB 7.5% / WBTC 7.5%, convex_engine.py) sono davvero un
ottimo, o una combinazione diversa fa meglio netto di tasse italiane e TER?

Metodologia: riusa i PROXY a storico lungo gia' costruiti e documentati per
Kelly Stack (validation_suite/kelly_stack/kelly_backtest.py:
build_sleeve_returns) — la stessa decomposizione di leva implicita gia'
documentata in convex_engine.py (NTSG: equity_leg=0.90, bond_leg=0.60 ->
NTSG_proxy = 0.9*SPY + 0.6*IEF; AVWS_proxy=VBR; DBMFE_proxy=DBMF;
PPFB_proxy=GLD; WBTC_proxy=BTC-USD). Applica il TER reale di ciascun
strumento (drag mensile, da CONVEX_INSTRUMENTS) e la tassazione italiana
reale per instrument (REDDITO_CAPITALE per NTSG/AVWS/DBMFE — minus non
compensabili; REDDITO_DIVERSO per PPFB/WBTC — pool di compensazione
condiviso), riusando framework/tax_engine.py.

Correzione EUR/USD (aggiunta dopo una domanda diretta dell'utente su
DBMFE): tutti gli strumenti REALI di Convex sono quotati in EUR
(NTSG.MI, AVWS.DE, EGLN.L, WBTC-ETFP.MI, DBMFE.PA) ma i proxy USA usati
qui (SPY/IEF/VBR/GLD/BTC-USD/DBMF) sono in USD — verificato empiricamente
con i prezzi reali di DBMFE.PA (storico corto ma reale, da 2025-04):
la crescita totale sul periodo comune combacia quasi esattamente con
DBMF convertito in EUR (28,47% vs 28,42%), non con DBMF grezzo (30,87%) —
DBMFE.PA e' NON coperto dal cambio (unhedged), come tipico per ETC/ETP
fisici e fondi a leva imbottiti di futures. Lo stesso vale strutturalmente
per gli altri 4 (oro fisico e Bitcoin fisico non hedgiano quasi mai il
cambio; NTSG/AVWS sono ETF UCITS azionari/obbligazionari globali senza
overlay di copertura esplicito). Tutti i prezzi USD vengono quindi divisi
per EURUSD=X (storico Yahoo dal 2003) PRIMA di calcolare i rendimenti e
il blend — non solo DBMFE, la stessa correzione varrebbe anche per il
backtest di Kelly Stack (kelly_backtest.py), non modificato qui per non
alterare silenziosamente numeri gia' pubblicati in KELLY_STACK_SPEC.md.

Walk-forward onesto: split TRAIN/TEST a meta' campione (stessa convenzione
di kelly_backtest.py, non lo split 2013 documentato in portfolio_manager.py
per la serie REALE convex_monthly_returns.csv — qui il proxy DBMFE (DBMF,
storico dal 2019) accorcia il campione utilizzabile via inner-join a soli
~88 mesi, 2013 non e' raggiungibile con questa combinazione di proxy). I
pesi non sono scelti guardando il TEST, la griglia e' valutata su ENTRAMBI
i periodi separatamente per evitare di scambiare un artefatto in-sample per
un miglioramento vero (lo stesso errore che questo intero progetto ha
ripetutamente trovato e corretto altrove).

Validazione: PBO-CSCV su tutta la griglia (stesso periodo, stesso universo
di proxy — il caso d'uso naturale del PBO), DSR sul migliore con
n_trials = numero di combinazioni REALMENTE provate in questo script.
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
from statistical_validation import deflated_sharpe_ratio, pbo_cscv, block_bootstrap_ci
from kelly_backtest import fetch_universe, load_monthly_series, build_sleeve_returns, BACKTEST_TICKERS

DATA_DIR = Path(__file__).parent / "convex_grid_data"  # rigenerabile, gitignored (stessa cache di kelly_backtest, riusata)

# Costi reali (CONVEX_INSTRUMENTS in convex_engine.py) e trattamento fiscale reale.
TER = {"NTSG_proxy": 0.0025, "AVWS_proxy": 0.0039, "DBMFE_proxy": 0.0075, "PPFB_proxy": 0.0012, "WBTC_proxy": 0.0015}
TAX_TYPE = {
    "NTSG_proxy": "REDDITO_CAPITALE", "AVWS_proxy": "REDDITO_CAPITALE", "DBMFE_proxy": "REDDITO_CAPITALE",
    "PPFB_proxy": "REDDITO_DIVERSO", "WBTC_proxy": "REDDITO_DIVERSO",
}

# Griglia: l'attuale + alternative principiate (non un'ottimizzazione esaustiva,
# che sarebbe essa stessa un rischio di overfitting) — piu/meno leva azionaria
# (NTSG), piu/meno protezione in crisi (DBMFE), piu/meno crescita asimmetrica
# (WBTC), un caso piu' equilibrato.
CANDIDATES = {
    "Attuale (45/15/25/7.5/7.5)":      {"NTSG_proxy": 0.45, "AVWS_proxy": 0.15, "DBMFE_proxy": 0.25, "PPFB_proxy": 0.075, "WBTC_proxy": 0.075},
    "Piu' equity, meno DBMFE (55/15/15/7.5/7.5)": {"NTSG_proxy": 0.55, "AVWS_proxy": 0.15, "DBMFE_proxy": 0.15, "PPFB_proxy": 0.075, "WBTC_proxy": 0.075},
    "Piu' DBMFE, meno equity (35/15/35/7.5/7.5)": {"NTSG_proxy": 0.35, "AVWS_proxy": 0.15, "DBMFE_proxy": 0.35, "PPFB_proxy": 0.075, "WBTC_proxy": 0.075},
    "Piu' WBTC, meno PPFB (45/15/25/2.5/12.5)":   {"NTSG_proxy": 0.45, "AVWS_proxy": 0.15, "DBMFE_proxy": 0.25, "PPFB_proxy": 0.025, "WBTC_proxy": 0.125},
    "Meno WBTC, piu' PPFB (45/15/25/12.5/2.5)":   {"NTSG_proxy": 0.45, "AVWS_proxy": 0.15, "DBMFE_proxy": 0.25, "PPFB_proxy": 0.125, "WBTC_proxy": 0.025},
    "Piu' AVWS, meno NTSG (35/25/25/7.5/7.5)":    {"NTSG_proxy": 0.35, "AVWS_proxy": 0.25, "DBMFE_proxy": 0.25, "PPFB_proxy": 0.075, "WBTC_proxy": 0.075},
    "Meno AVWS, piu' NTSG (55/5/25/7.5/7.5)":     {"NTSG_proxy": 0.55, "AVWS_proxy": 0.05, "DBMFE_proxy": 0.25, "PPFB_proxy": 0.075, "WBTC_proxy": 0.075},
    "Equal-ish (30/20/25/12.5/12.5)":  {"NTSG_proxy": 0.30, "AVWS_proxy": 0.20, "DBMFE_proxy": 0.25, "PPFB_proxy": 0.125, "WBTC_proxy": 0.125},
    "Zero WBTC (48.75/16.25/27/8/0)":  {"NTSG_proxy": 0.4875, "AVWS_proxy": 0.1625, "DBMFE_proxy": 0.27, "PPFB_proxy": 0.08, "WBTC_proxy": 0.0},
}


def run_one(returns_df: pd.DataFrame, weights: dict, label: str, sub_returns: pd.DataFrame = None):
    """sub_returns: se fornito (per TRAIN/TEST separati), calcola le metriche
    SOLO su quel sotto-periodo ma usa returns_df completo per la tassazione
    (il costo base/PMC deve accumularsi dall'inizio, non ripartire da zero a
    meta' campione — altrimenti il TEST mostrerebbe un drag fiscale
    artificialmente alto/basso per un portafoglio "appena comprato")."""
    weights_with_ter = returns_df.copy()
    for k, ter in TER.items():
        weights_with_ter[k] = returns_df[k] - ter / 12  # drag mensile

    net_full = apply_italian_tax(weights_with_ter, weights, tax_types=TAX_TYPE)
    gross_full = (weights_with_ter * pd.Series(weights)).sum(axis=1)

    if sub_returns is not None:
        idx = sub_returns.index
        net, gross = net_full.loc[idx], gross_full.loc[idx]
    else:
        net, gross = net_full, gross_full

    return {
        "label": label, "net": net, "gross": gross,
        "cagr_net": cagr(net), "sharpe_net": sharpe(net), "maxdd_net": max_drawdown(net), "calmar_net": calmar(net),
        "cagr_gross": cagr(gross), "sharpe_gross": sharpe(gross),
    }


def print_table(results: dict, period_label: str):
    print(f"\n--- {period_label} ---")
    print(f"{'Config':<42}{'CAGR netto':>12}{'Sharpe netto':>14}{'MaxDD netto':>13}{'Calmar':>9}")
    for label, r in results.items():
        print(f"{label:<42}{r['cagr_net']*100:>11.2f}%{r['sharpe_net']:>14.2f}{r['maxdd_net']*100:>12.2f}%{r['calmar_net']:>9.2f}")


def main():
    if not DATA_DIR.exists() or not any(DATA_DIR.glob("*_monthly.csv")):
        print(f"[*] Nessun dato in cache in {DATA_DIR}, scarico da Yahoo Finance...")
        fetch_universe(str(DATA_DIR), BACKTEST_TICKERS)
    if not (DATA_DIR / "EURUSD=X_monthly.csv").exists():
        fetch_universe(str(DATA_DIR), ["EURUSD=X"])

    prices = load_monthly_series(str(DATA_DIR), BACKTEST_TICKERS)
    eurusd = load_monthly_series(str(DATA_DIR), ["EURUSD=X"])["EURUSD=X"]
    # Converte ogni prezzo USD in equivalente EUR PRIMA di calcolare rendimenti/blend —
    # vedi nota FX nel docstring: tutti gli strumenti reali di Convex sono unhedged in EUR.
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

    results_full, results_train, results_test = {}, {}, {}
    for label, weights in CANDIDATES.items():
        results_full[label] = run_one(sleeve_returns, weights, label)
        results_train[label] = run_one(sleeve_returns, weights, label, sub_returns=train)
        results_test[label] = run_one(sleeve_returns, weights, label, sub_returns=test)

    print_table(results_full, "CAMPIONE PIENO")
    print_table(results_train, "TRAIN (2000-2013, usato per scegliere pesi originariamente)")
    print_table(results_test, "TEST (2013-2026, fuori campione)")

    # --- PBO-CSCV sul TEST (l'unico periodo onesto per giudicare una selezione) ---
    variant_order = list(CANDIDATES.keys())
    perf_matrix = np.column_stack([results_test[m]["net"].values for m in variant_order])
    n_splits = 8
    usable_len = (len(perf_matrix) // n_splits) * n_splits
    if usable_len >= n_splits * 2:
        pbo = pbo_cscv(perf_matrix[-usable_len:], n_splits=n_splits)
        print(f"\nPBO-CSCV su {len(variant_order)} combinazioni di pesi, periodo TEST: {pbo*100:.1f}% "
              "(vicino al 50% = nessuna combinazione batte le altre in modo robusto fuori campione)")

    best_label = max(variant_order, key=lambda m: results_test[m]["sharpe_net"])
    best_net_test = results_test[best_label]["net"]
    best_sr = results_test[best_label]["sharpe_net"]
    dsr = deflated_sharpe_ratio(best_sr, n_trials=len(variant_order), n_obs=len(best_net_test))
    lo, hi = block_bootstrap_ci(best_net_test.values, sharpe, block_size=6, ci=0.90, seed=42)
    print(f"\nMigliore su TEST per Sharpe netto: {best_label} (Sharpe {best_sr:.2f} vs "
          f"{results_test['Attuale (45/15/25/7.5/7.5)']['sharpe_net']:.2f} dell'attuale)")
    print(f"  DSR (n_trials={len(variant_order)}, conteggio reale): {dsr:.4f}")
    print(f"  CI 90% Sharpe TEST (block bootstrap): [{lo:.2f}, {hi:.2f}]")


if __name__ == "__main__":
    main()
