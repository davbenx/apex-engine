"""
altcoin_btc_vol_targeting_test.py — Volatility targeting sulla singola
posizione BTC (non "quale moneta scegliere" tra le altcoin — tutte le
famiglie di selezione sono gia' state testate e falsificate in
altcoin_strategy_families_pointintime_test.py — ma QUANTO esporsi a BTC
stesso), richiesto esplicitamente dall'utente come strategia accademica
non ancora provata sull'universo crypto.

Letteratura di riferimento: vol targeting (Moreira & Muir 2017, "Volatility
Managed Portfolios") — scalare l'esposizione inversamente alla vol
realizzata recente tende a migliorare lo Sharpe di serie con vol clustering
forte, riducendo l'esposizione nei periodi piu' rischiosi. Diverso dal
"trend following" gia' testato e fallito (quello sposta l'esposizione
in base alla DIREZIONE del prezzo, non alla sua vol).

Riusa l'infrastruttura di altcoin_vs_btc_daily_backtest.py
(fetch/load/backtest_strategy — nessuna logica duplicata), senza leva
(esposizione BTC cappata a 1.0 — nessun leverage crypto in produzione),
il resto implicitamente cash a rendimento zero quando la vol e' alta.

Griglia: lookback realized vol {20, 30, 60} giorni x vol target annualizzata
{40%, 60%, 80%} (BTC storico oscilla tipicamente 50-100% annualizzato) —
9 varianti + baseline BTC buy&hold 100% flat.
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
    DATA_DIR, PERIODS_PER_YEAR, fetch_all_price_data, load_daily, backtest_strategy,
)

LOOKBACKS = [20, 30, 60]
TARGET_VOLS = [0.40, 0.60, 0.80]


def vol_target_weights(ret: pd.Series, lookback: int, target_vol: float) -> pd.DataFrame:
    realized_vol = ret.rolling(lookback).std() * np.sqrt(PERIODS_PER_YEAR)
    exposure = (target_vol / realized_vol).clip(upper=1.0).fillna(0.0)
    # primi `lookback` giorni: nessuna stima di vol ancora disponibile -> resta a 0
    # (backtest_strategy imposta comunque BTC=1.0 il primissimo giorno come default)
    return pd.DataFrame({"BTC-USD": exposure})


def main():
    if not (DATA_DIR / "BTC_USD_daily.csv").exists():
        print(f"[*] Nessun dato in cache in {DATA_DIR}, scarico da Yahoo Finance...")
        fetch_all_price_data()

    px = load_daily("BTC-USD")
    ret = px.pct_change().dropna()
    ret = ret.loc[ret.index >= pd.Timestamp("2019-10-01")]
    returns_df = pd.DataFrame({"BTC-USD": ret})
    print(f"Simulazione daily BTC: {len(ret)} giorni, {ret.index[0].date()} -> {ret.index[-1].date()}")

    results = {}
    baseline_w = pd.DataFrame({"BTC-USD": pd.Series(1.0, index=ret.index)})
    gross, net = backtest_strategy(baseline_w, returns_df, "BTC buy & hold 100% (baseline)")
    results["btc_only"] = {"label": "BTC buy & hold 100% (baseline)", "gross": gross, "net": net}

    for lb in LOOKBACKS:
        for tv in TARGET_VOLS:
            label = f"Vol target {tv*100:.0f}% (lookback {lb}g)"
            w = vol_target_weights(ret, lb, tv)
            gross, net = backtest_strategy(w, returns_df, label)
            results[f"vt_{lb}_{tv}"] = {"label": label, "gross": gross, "net": net}

    variant_order = list(results.keys())
    perf_matrix = np.column_stack([results[m]["net"].values for m in variant_order])
    n_splits = 8
    usable_len = (len(perf_matrix) // n_splits) * n_splits
    pbo = pbo_cscv(perf_matrix[-usable_len:], n_splits=n_splits)
    print(f"\nPBO-CSCV su {len(variant_order)} varianti (1 baseline + 9 vol-target): {pbo*100:.1f}%")

    best_mode = max(variant_order, key=lambda m: sharpe(results[m]["net"], periods_per_year=PERIODS_PER_YEAR))
    best_net = results[best_mode]["net"]
    best_sr = sharpe(best_net, periods_per_year=PERIODS_PER_YEAR)
    dsr = deflated_sharpe_ratio(best_sr, n_trials=len(variant_order), n_obs=len(best_net))
    print(f"Migliore per Sharpe netto: {results[best_mode]['label']} (Sharpe {best_sr:.2f}) — DSR {dsr:.3f}")

    diff = (results[best_mode]["net"] - results["btc_only"]["net"]).dropna()
    lo, hi = block_bootstrap_ci(diff.values, lambda r: pd.Series(r).mean() * PERIODS_PER_YEAR * 100,
                                 block_size=30, ci=0.90, seed=42)
    mean_diff = diff.mean() * PERIODS_PER_YEAR * 100
    print(f"\n{results[best_mode]['label']} meno BTC buy&hold: {mean_diff:+.2f}pp/anno, "
          f"CI90 [{lo:+.2f}, {hi:+.2f}] ({'ESCLUDE' if lo * hi > 0 else 'include'} lo zero)")

    print(f"\n{'Variante':<32}{'CAGR netto':>12}{'Sharpe netto':>14}{'MaxDD netto':>13}{'Calmar netto':>14}")
    for m in variant_order:
        net = results[m]["net"]
        print(f"{results[m]['label']:<32}{cagr(net, PERIODS_PER_YEAR)*100:>11.2f}%"
              f"{sharpe(net, periods_per_year=PERIODS_PER_YEAR):>14.3f}{max_drawdown(net)*100:>12.2f}%"
              f"{calmar(net, PERIODS_PER_YEAR):>14.3f}")


if __name__ == "__main__":
    main()
