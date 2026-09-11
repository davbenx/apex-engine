"""
altcoin_vs_btc_weekly_pointintime_backtest.py — Isola la variabile "universo"
dalla variabile "granularita' del segnale", che erano confuse tra
altcoin_vs_btc_backtest.py (settimanale, universo FISSO ETH/SOL) e
altcoin_vs_btc_daily_backtest.py (daily, universo POINT-IN-TIME reale):
il primo mostrava alcuni candidati battere BTC su Sharpe, il secondo no —
ma i due test differivano su ENTRAMBE le dimensioni contemporaneamente, non
si poteva dire quale delle due spiegasse la differenza.

Qui: STESSO universo point-in-time reale del test daily (28 trimestri,
top-3/top-5 alt per market cap, cmc_altcoin_pointintime_snapshots.json),
ma segnale/decisione valutati SETTIMANALMENTE (dati daily riaggregati a
fine settimana, W-FRI) invece che ogni giorno. Se il risultato assomiglia
al daily (BTC vince), la granularita' non era la spiegazione del
ribaltamento nel test settimanale originale — era l'universo fisso
ETH/SOL. Se assomiglia al settimanale originale, la granularita' conta
davvero.

Finestre di lookback riscalate in settimane per coprire lo stesso arco di
tempo di calendario del test daily (20gg->3sett, 60gg->9sett, 30gg->4sett)
— non lo stesso NUMERO di periodi, che significherebbe un lookback ~7x piu'
lungo in calendario.

Riusa interamente la logica di altcoin_vs_btc_daily_backtest.py
(build_candidate_weights, backtest_strategy, universo point-in-time, tasse,
fee Kraken) parametrizzata — nessuna logica duplicata.
"""

from __future__ import annotations
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "framework"))
from statistical_validation import deflated_sharpe_ratio, pbo_cscv, block_bootstrap_ci
from metrics import sharpe, cagr
from altcoin_vs_btc_daily_backtest import (
    ALL_TICKERS, DATA_DIR, fetch_all_price_data, load_daily,
    load_pointintime_top_alts, build_candidate_weights, backtest_strategy,
)

PERIODS_PER_YEAR = 52

# Finestre daily -> equivalente settimanale a parita' di arco di calendario
# (giorni/7, arrotondato): short 20gg~=3sett, long 60gg~=9sett, trail/vol 30gg~=4sett.
SHORT_WINDOW = 3
LONG_WINDOW = 9
TRAIL_WINDOW = 4
VOL_WINDOW = 4


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
        for mode, label in [
            ("btc_only", "BTC buy & hold (baseline)"),
            ("regime_altseason", f"Regime altseason weekly (top-{top_n} point-in-time)"),
            ("btc_slowdown_switch", f"Switch su rallentamento BTC -> singola alt migliore (top-{top_n})"),
            ("momentum_rotation", f"Rotazione momentum weekly {{BTC + top-{top_n}}} (vincitore unico)"),
            ("inverse_vol", f"Inverse-vol {{BTC + top-{top_n}}} (ribilanciato su cambio pool/vol)"),
        ]:
            w = build_candidate_weights(
                rets, pit_alts, mode,
                short_window=SHORT_WINDOW, long_window=LONG_WINDOW, trail_window=TRAIL_WINDOW, vol_window=VOL_WINDOW,
            )
            gross, net = backtest_strategy(w, rets, label, periods_per_year=PERIODS_PER_YEAR)
            results[mode] = {"label": label, "gross": gross, "net": net, "weights": w}

        variant_order = list(results.keys())
        perf_matrix = np.column_stack([results[m]["net"].values for m in variant_order])
        n_splits = 8
        usable_len = (len(perf_matrix) // n_splits) * n_splits
        pbo = pbo_cscv(perf_matrix[-usable_len:], n_splits=n_splits)
        print(f"\nPBO-CSCV su {len(variant_order)} candidati (top-{top_n}, weekly): {pbo*100:.1f}% "
              "(vicino al 50% = la selezione del migliore non fa meglio del caso)")

        best_mode = max(variant_order, key=lambda m: sharpe(results[m]["net"], periods_per_year=PERIODS_PER_YEAR))
        best_net = results[best_mode]["net"]
        best_sr = sharpe(best_net, periods_per_year=PERIODS_PER_YEAR)
        dsr = deflated_sharpe_ratio(best_sr, n_trials=len(variant_order), n_obs=len(best_net))
        lo, hi = block_bootstrap_ci(best_net.values, lambda r: sharpe(pd.Series(r), periods_per_year=PERIODS_PER_YEAR),
                                     block_size=6, ci=0.90, seed=42)
        print(f"Migliore per Sharpe netto: {results[best_mode]['label']} (Sharpe {best_sr:.2f} vs "
              f"{sharpe(results['btc_only']['net'], periods_per_year=PERIODS_PER_YEAR):.2f} di BTC)")
        print(f"  DSR (n_trials={len(variant_order)}, conteggio reale): {dsr:.4f}")
        print(f"  CI 90% Sharpe (block bootstrap, blocchi 6 settimane): [{lo:.2f}, {hi:.2f}]")

        regime_net = results["regime_altseason"]["net"]
        regime_alt_weeks = (results["regime_altseason"]["weights"]["BTC-USD"] < 0.5)
        episodes, in_ep, start = [], False, None
        for date, val in regime_alt_weeks.items():
            if val and not in_ep:
                in_ep, start = True, date
            elif not val and in_ep:
                in_ep = False
                episodes.append((start, date))
        if in_ep:
            episodes.append((start, regime_alt_weeks.index[-1]))
        episodes_long = sorted([(s, e) for s, e in episodes if (e - s).days >= 14], key=lambda p: -(p[1] - p[0]).days)[:2]
        if episodes_long:
            mask_top2 = pd.Series(False, index=regime_net.index)
            for s, e in episodes_long:
                mask_top2 |= (regime_net.index >= s) & (regime_net.index <= e)
            net_excluding_top2 = regime_net.copy()
            net_excluding_top2[mask_top2] = 0.0
            print(f"Concentrazione per episodi (regime altseason, top-{top_n}): 2 episodi piu' lunghi = "
                  f"{[(s.date(), e.date()) for s, e in episodes_long]}, {mask_top2.sum()}/{len(regime_net)} settimane "
                  f"({mask_top2.mean()*100:.0f}%). CAGR netto escludendoli: {cagr(net_excluding_top2, PERIODS_PER_YEAR)*100:.2f}% "
                  f"(contro {cagr(regime_net, PERIODS_PER_YEAR)*100:.2f}% con tutto il campione).")


if __name__ == "__main__":
    main()
