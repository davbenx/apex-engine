"""
altcoin_strategy_families_pointintime_test.py — Ricerca sistematica: momentum,
mean reversion, low volatility, trend following, e stop-loss, sull'universo
altcoin POINT-IN-TIME reale (validation_suite/pointintime_data/
cmc_altcoin_pointintime_snapshots.json), a granularita' daily — c'e' QUALCHE
formula che sovraperforma BTC buy&hold a rischio pari o minore, netto tasse
italiane (26%, redditi diversi, pool condiviso) e fee Kraken (0.26%)?

Estende altcoin_vs_btc_daily_backtest.py (riusa build_candidate_weights,
apply_stop_loss_overlay, backtest_strategy — nessuna logica duplicata) con
3 famiglie di segnale mai testate prima in questo progetto:
  - mean_reversion: contrarian, compra l'asset piu' scaduto nel pool
  - low_vol_pick: possiede SOLO il singolo asset a vol piu' bassa (non un
    blend pesato come inverse_vol, gia' testato)
  - trend_following: filtro di trend PER ASSET (prezzo sopra la propria
    media mobile), puo' andare CASH (flat) se nessun asset e' in uptrend —
    diverso da ogni altro candidato, che ripiega sempre su BTC
e lo stop-loss come overlay indipendente su momentum_rotation e
mean_reversion (i due candidati a posizione concentrata singola, dove un
controllo del rischio per-posizione ha piu' senso).

"Carry" (crypto: funding rate dei perpetual) NON e' testato qui con lo
stesso rigore storico — vedi altcoin_carry_funding_rate_test.py per
un'analisi separata e onestamente limitata (solo ~1 anno di storico reale
disponibile via API, contro i ~6-7 anni di questo test).

Validazione: PBO-CSCV su tutti i candidati (stesso periodo/universo — il
caso d'uso naturale del PBO, qui con la griglia piu' ricca mai testata in
questo progetto), DSR sul migliore con n_trials = conteggio REALE dei
candidati provati, block bootstrap CI, e lo stesso controllo di
concentrazione per episodi gia' usato altrove.
"""

from __future__ import annotations
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "framework"))
from metrics import cagr, sharpe, max_drawdown, calmar
from statistical_validation import deflated_sharpe_ratio, pbo_cscv, block_bootstrap_ci
from altcoin_vs_btc_daily_backtest import (
    ALL_TICKERS, DATA_DIR, PERIODS_PER_YEAR, fetch_all_price_data, load_daily,
    load_pointintime_top_alts, build_candidate_weights, apply_stop_loss_overlay, backtest_strategy,
)

STOP_THRESHOLD = -0.15  # stesso ordine di grandezza gia' validato altrove (kelly_backtest, §8.x)


def main():
    if not DATA_DIR.exists() or not any(DATA_DIR.glob("*_daily.csv")):
        print(f"[*] Nessun dato in cache in {DATA_DIR}, scarico da Yahoo Finance...")
        fetch_all_price_data()

    prices = {t: load_daily(t) for t in ALL_TICKERS}
    common = prices["BTC-USD"].index
    for p in prices.values():
        common = common.union(p.index)
    common = common.sort_values()
    common = common[common >= pd.Timestamp("2019-10-01")]

    px = pd.DataFrame({t: prices[t].reindex(common).ffill() for t in ALL_TICKERS})
    rets = px.pct_change().fillna(0.0)
    rets = rets.loc[rets.index[1:]]

    print(f"Simulazione daily: {len(rets)} giorni, {rets.index[0].date()} -> {rets.index[-1].date()}")

    for top_n in (3, 5):
        print(f"\n\n########## UNIVERSO POINT-IN-TIME: TOP-{top_n} ALT PER TRIMESTRE ##########")
        pit_alts = load_pointintime_top_alts(top_n)

        base_candidates = [
            ("btc_only", "BTC buy & hold (baseline)"),
            ("momentum_rotation", f"Momentum: rotazione {{BTC + top-{top_n}}} (vincitore unico)"),
            ("mean_reversion", "Mean reversion: contrarian sull'asset piu' scaduto"),
            ("low_vol_pick", "Low volatility: possiede il singolo asset a vol piu' bassa"),
            ("trend_following", "Trend following: filtro MA per asset, CASH se nessuno in uptrend"),
            ("regime_altseason", f"Regime altseason (BTC vs media top-{top_n} alt)"),
            ("btc_slowdown_switch", "Switch su rallentamento BTC -> singola alt migliore"),
            ("inverse_vol", f"Inverse-vol {{BTC + top-{top_n}}} (blend pesato)"),
        ]

        results = {}
        for mode, label in base_candidates:
            w = build_candidate_weights(rets, pit_alts, mode)
            gross, net = backtest_strategy(w, rets, label)
            results[mode] = {"label": label, "gross": gross, "net": net, "weights": w}

        # Overlay di stop-loss sui due candidati a posizione concentrata singola.
        for base_mode in ("momentum_rotation", "mean_reversion"):
            stopped_key = f"{base_mode}_stopped"
            w_stopped = apply_stop_loss_overlay(results[base_mode]["weights"], rets, stop_threshold=STOP_THRESHOLD)
            label = f"{results[base_mode]['label']} + stop-loss {STOP_THRESHOLD*100:.0f}%"
            gross, net = backtest_strategy(w_stopped, rets, label)
            results[stopped_key] = {"label": label, "gross": gross, "net": net, "weights": w_stopped}

        variant_order = list(results.keys())
        perf_matrix = np.column_stack([results[m]["net"].values for m in variant_order])
        n_splits = 8
        usable_len = (len(perf_matrix) // n_splits) * n_splits
        pbo = pbo_cscv(perf_matrix[-usable_len:], n_splits=n_splits)
        print(f"\nPBO-CSCV su {len(variant_order)} candidati (top-{top_n}): {pbo*100:.1f}% "
              "(vicino al 50% = la selezione del migliore non fa meglio del caso; vicino a 0% = edge robusto)")

        best_mode = max(variant_order, key=lambda m: sharpe(results[m]["net"], periods_per_year=PERIODS_PER_YEAR))
        best_net = results[best_mode]["net"]
        best_sr = sharpe(best_net, periods_per_year=PERIODS_PER_YEAR)
        n_trials_real = len(variant_order)
        dsr = deflated_sharpe_ratio(best_sr, n_trials=n_trials_real, n_obs=len(best_net))
        lo, hi = block_bootstrap_ci(best_net.values, lambda r: sharpe(pd.Series(r), periods_per_year=PERIODS_PER_YEAR),
                                     block_size=30, ci=0.90, seed=42)
        print(f"Migliore per Sharpe netto: {results[best_mode]['label']} (Sharpe {best_sr:.2f} vs "
              f"{sharpe(results['btc_only']['net'], periods_per_year=PERIODS_PER_YEAR):.2f} di BTC)")
        print(f"  DSR (n_trials={n_trials_real}, conteggio reale dei candidati provati): {dsr:.4f}")
        print(f"  CI 90% Sharpe (block bootstrap, blocchi 30gg): [{lo:.2f}, {hi:.2f}]")

        # Lo stop-loss ha davvero aiutato i due candidati su cui e' stato applicato?
        for base_mode in ("momentum_rotation", "mean_reversion"):
            sr_base = sharpe(results[base_mode]["net"], periods_per_year=PERIODS_PER_YEAR)
            sr_stopped = sharpe(results[f"{base_mode}_stopped"]["net"], periods_per_year=PERIODS_PER_YEAR)
            dd_base = max_drawdown(results[base_mode]["net"])
            dd_stopped = max_drawdown(results[f"{base_mode}_stopped"]["net"])
            print(f"  Stop-loss su {base_mode}: Sharpe {sr_base:.2f}->{sr_stopped:.2f}, "
                  f"MaxDD {dd_base*100:.1f}%->{dd_stopped*100:.1f}%")


if __name__ == "__main__":
    main()
