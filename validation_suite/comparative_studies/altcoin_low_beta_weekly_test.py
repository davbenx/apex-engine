"""
altcoin_low_beta_weekly_test.py — Domanda diretta dell'utente dopo il
fallimento di low_beta_pick a granularita' daily
(altcoin_strategy_families_pointintime_test.py, Sharpe netto 0.39/0.07
contro 0.84 di BTC): "low beta altcoin weekly sarebbe diverso?"

Due variabili DISTINTE nascoste in questa domanda, separate qui:
  1. GRANULARITA' pura: stessa finestra di beta in tempo di CALENDARIO
     (~4 settimane, equivalente ai 30 giorni del test daily), ma decisione
     presa settimanalmente invece che ogni giorno — isola se la sola
     granularita' conta (probabilmente no, stesso principio gia' visto
     per gli altri candidati in altcoin_vs_btc_weekly_pointintime_backtest.py,
     dove BTC vinceva comunque).
  2. FINESTRA DI STIMA del beta piu' LUNGA: il test daily usava ~6
     settimane di calendario (30gg) per stimare il beta — molto piu'
     corto della banda 22-33 settimane che ha funzionato per il basket
     azionario Apex (Teoria #5). Qui si testano 4, 13 e 26 settimane per
     isolare se la finestra corta (non la granularita' daily in se') era
     il vero problema.

Riusa build_candidate_weights (low_beta_pick, gia' aggiunto in
altcoin_vs_btc_daily_backtest.py) parametrizzato su vol_window invece di
duplicare la logica.
"""

from __future__ import annotations
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "framework"))
from statistical_validation import deflated_sharpe_ratio, pbo_cscv, block_bootstrap_ci
from metrics import sharpe, cagr, max_drawdown
from altcoin_vs_btc_daily_backtest import (
    ALL_TICKERS, DATA_DIR, fetch_all_price_data, load_daily,
    load_pointintime_top_alts, build_candidate_weights, backtest_strategy,
)

PERIODS_PER_YEAR = 52
SHORT_WINDOW, LONG_WINDOW, TRAIL_WINDOW = 3, 9, 4  # invariati, non usati da low_beta_pick
BETA_WINDOW_GRID = [4, 13, 26]  # settimane: ~1 mese (equiv. daily), ~3 mesi, ~6 mesi (banda Apex)


def main():
    if not DATA_DIR.exists() or not any(DATA_DIR.glob("*_daily.csv")):
        print(f"[*] Nessun dato in cache in {DATA_DIR}, scarico da Yahoo Finance...")
        fetch_all_price_data()

    prices_daily = {t: load_daily(t) for t in ALL_TICKERS}
    common = prices_daily["BTC-USD"].index
    for p in prices_daily.values():
        common = common.union(p.index)
    common = common.sort_values()
    common = common[common >= pd.Timestamp("2019-10-01")]

    px_daily = pd.DataFrame({t: prices_daily[t].reindex(common).ffill() for t in ALL_TICKERS})
    px_weekly = px_daily.resample("W-FRI").last()
    rets = px_weekly.pct_change().dropna()

    print(f"Simulazione weekly (universo point-in-time reale): {len(rets)} settimane, "
          f"{rets.index[0].date()} -> {rets.index[-1].date()}")

    for top_n in (3, 5):
        print(f"\n\n########## UNIVERSO POINT-IN-TIME: TOP-{top_n} ALT PER TRIMESTRE (WEEKLY) ##########")
        pit_alts = load_pointintime_top_alts(top_n)

        results = {}
        w_btc = build_candidate_weights(rets, pit_alts, "btc_only",
                                         short_window=SHORT_WINDOW, long_window=LONG_WINDOW, trail_window=TRAIL_WINDOW, vol_window=4)
        gross, net = backtest_strategy(w_btc, rets, "BTC buy & hold (baseline)", periods_per_year=PERIODS_PER_YEAR)
        results["btc_only"] = {"label": "BTC buy & hold (baseline)", "net": net}

        for beta_window in BETA_WINDOW_GRID:
            label = f"Low beta pick (finestra beta = {beta_window} sett.)"
            w = build_candidate_weights(rets, pit_alts, "low_beta_pick",
                                         short_window=SHORT_WINDOW, long_window=LONG_WINDOW, trail_window=TRAIL_WINDOW, vol_window=beta_window)
            gross, net = backtest_strategy(w, rets, label, periods_per_year=PERIODS_PER_YEAR)
            results[f"low_beta_{beta_window}"] = {"label": label, "net": net}

        variant_order = list(results.keys())
        perf_matrix = np.column_stack([results[m]["net"].values for m in variant_order])
        n_splits = 8
        usable_len = (len(perf_matrix) // n_splits) * n_splits
        pbo = pbo_cscv(perf_matrix[-usable_len:], n_splits=n_splits)
        print(f"\nPBO-CSCV su {len(variant_order)} candidati (top-{top_n}, weekly): {pbo*100:.1f}%")

        best_mode = max(variant_order, key=lambda m: sharpe(results[m]["net"], periods_per_year=PERIODS_PER_YEAR))
        best_net = results[best_mode]["net"]
        best_sr = sharpe(best_net, periods_per_year=PERIODS_PER_YEAR)
        dsr = deflated_sharpe_ratio(best_sr, n_trials=len(variant_order), n_obs=len(best_net))
        print(f"Migliore per Sharpe netto: {results[best_mode]['label']} (Sharpe {best_sr:.2f} vs "
              f"{sharpe(results['btc_only']['net'], periods_per_year=PERIODS_PER_YEAR):.2f} di BTC)")
        print(f"  DSR (n_trials={len(variant_order)}, conteggio reale): {dsr:.4f}")

        for beta_window in BETA_WINDOW_GRID:
            net = results[f"low_beta_{beta_window}"]["net"]
            diff = (net - results["btc_only"]["net"]).dropna()
            mean_diff = diff.mean() * PERIODS_PER_YEAR * 100
            lo, hi = block_bootstrap_ci(diff.values, lambda r: pd.Series(r).mean() * PERIODS_PER_YEAR * 100,
                                         block_size=6, ci=0.90, seed=42)
            print(f"  low_beta({beta_window}sett.) meno BTC: CAGR {cagr(net, PERIODS_PER_YEAR)*100:.2f}%  "
                  f"Sharpe {sharpe(net, periods_per_year=PERIODS_PER_YEAR):.2f}  MaxDD {max_drawdown(net)*100:.2f}%  "
                  f"| diff {mean_diff:+.2f}pp/anno CI90% [{lo:+.2f},{hi:+.2f}] "
                  f"({'ESCLUDE' if lo*hi>0 else 'include'} zero)")


if __name__ == "__main__":
    main()
