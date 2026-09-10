"""
altcoin_low_beta_weekly_walkforward_test.py — Approfondimento richiesto
direttamente dall'utente ("approfondisci low beta altcoin weekly con
walk-forward e piu' storico") dopo il risultato preliminare di
altcoin_low_beta_weekly_test.py (low_beta_pick batte BTC con finestra beta
a 26 settimane, ma PBO ~45% e CI enormi — troppo debole per contare).

Due correzioni rispetto al test preliminare:

1. **BUG TROVATO E CORRETTO — "piu' storico" recuperato da un fix, non da
   nuova raccolta dati**: altcoin_vs_btc_weekly_pointintime_backtest.py (e
   di conseguenza altcoin_low_beta_weekly_test.py, che ne riusava la
   struttura) costruiva `rets` con `.dropna()` sull'intero DataFrame a 15
   colonne — qualunque riga con anche UN SOLO ticker mancante veniva
   scartata. TON-USD (inception reale 2020-08-24, la piu' tarda delle 15)
   faceva perdere ~11 mesi di storico VALIDO (2019-10 -> 2020-08) anche se
   TON non era eleggibile come "top alt" in quel periodo (non esisteva
   ancora, quindi mai nel pool point-in-time). La versione daily
   (altcoin_vs_btc_daily_backtest.py, altcoin_strategy_families_pointintime_test.py)
   usa correttamente `.fillna(0.0)`, non `.dropna()` — qui replicato.
   Recupera il campione da 315 a ~363 settimane (l'intera finestra
   disponibile dal primo snapshot point-in-time, 2019-10-01).

2. **Walk-forward SENZA look-ahead nella selezione della finestra beta**,
   stesso principio di apex_theory5_walkforward_selection_test.py (gia'
   applicato al basket azionario Apex): il campione e' diviso in 3 ere
   consecutive non sovrapposte; per ogni era successiva alla prima, la
   finestra beta "migliore" e' scelta SOLO con lo Sharpe delle ere
   precedenti, mai quella corrente, poi applicata SOLO sull'era corrente
   (mai vista prima della scelta). Le ere 2+3 concatenate danno il
   risultato out-of-sample onesto.

Riusa build_candidate_weights (low_beta_pick, gia' in
altcoin_vs_btc_daily_backtest.py) e backtest_strategy — nessuna logica
duplicata.
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
SHORT_WINDOW, LONG_WINDOW, TRAIL_WINDOW = 3, 9, 4
BETA_WINDOW_GRID = [4, 8, 13, 20, 26]
N_ERAS = 3


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
    rets = px_weekly.pct_change().fillna(0.0)  # FIX: era .dropna(), perdeva ~11 mesi per TON-USD
    rets = rets.loc[rets.index[1:]]

    print(f"Simulazione weekly (bug fillna corretto): {len(rets)} settimane, "
          f"{rets.index[0].date()} -> {rets.index[-1].date()} "
          f"(prima del fix: 315 settimane da 2020-09-04 — recuperate ~{len(rets)-315} settimane)")

    for top_n in (3, 5):
        print(f"\n\n########## UNIVERSO POINT-IN-TIME: TOP-{top_n} ALT PER TRIMESTRE (WEEKLY, walk-forward) ##########")
        pit_alts = load_pointintime_top_alts(top_n)

        w_btc = build_candidate_weights(rets, pit_alts, "btc_only",
                                         short_window=SHORT_WINDOW, long_window=LONG_WINDOW, trail_window=TRAIL_WINDOW, vol_window=4)
        _, net_btc = backtest_strategy(w_btc, rets, "BTC buy & hold", periods_per_year=PERIODS_PER_YEAR, verbose=False)

        # Serie complete per ciascuna finestra della griglia (calcolate una sola volta,
        # poi affettate per era — stesso principio di efficienza gia' usato per Apex equity).
        net_by_window = {}
        for bw in BETA_WINDOW_GRID:
            w = build_candidate_weights(rets, pit_alts, "low_beta_pick",
                                         short_window=SHORT_WINDOW, long_window=LONG_WINDOW, trail_window=TRAIL_WINDOW, vol_window=bw)
            _, net = backtest_strategy(w, rets, f"low_beta_pick(bw={bw})", periods_per_year=PERIODS_PER_YEAR, verbose=False)
            net_by_window[bw] = net

        common_idx = net_btc.index
        for bw in BETA_WINDOW_GRID:
            common_idx = common_idx.intersection(net_by_window[bw].index)
        common_idx = common_idx.sort_values()
        era_len = len(common_idx) // N_ERAS
        eras = [common_idx[i * era_len:(i + 1) * era_len] for i in range(N_ERAS - 1)]
        eras.append(common_idx[(N_ERAS - 1) * era_len:])

        print(f"Ere: {[(e.min().date(), e.max().date(), len(e)) for e in eras]}")

        wf_segments = []
        print(f"{'Era':<8}{'Finestra beta selezionata':>28}{'Sharpe selezione':>18}")
        for i in range(1, N_ERAS):
            past_idx = common_idx[:i * era_len]
            sharpes_past = {bw: sharpe(net_by_window[bw].reindex(past_idx).dropna(), periods_per_year=PERIODS_PER_YEAR)
                             for bw in BETA_WINDOW_GRID}
            best_bw = max(sharpes_past, key=sharpes_past.get)
            print(f"Era {i+1:<5}{best_bw:>28}{sharpes_past[best_bw]:>18.2f}")
            wf_segments.append(net_by_window[best_bw].reindex(eras[i]).dropna())

        wf_net = pd.concat(wf_segments).sort_index()
        btc_oos = net_btc.reindex(wf_net.index)

        print(f"\n--- OUT-OF-SAMPLE (ere 2+3, {len(wf_net)} settimane, "
              f"{wf_net.index.min().date()} -> {wf_net.index.max().date()}) ---")
        for label, net in [("BTC buy & hold", btc_oos), ("Low-beta pick (walk-forward)", wf_net)]:
            print(f"  {label:<32}CAGR {cagr(net, PERIODS_PER_YEAR)*100:>8.2f}%   "
                  f"Sharpe {sharpe(net, periods_per_year=PERIODS_PER_YEAR):>5.2f}   "
                  f"MaxDD {max_drawdown(net)*100:>7.2f}%")

        diff = (wf_net - btc_oos).dropna()
        mean_diff = diff.mean() * PERIODS_PER_YEAR * 100
        lo, hi = block_bootstrap_ci(diff.values, lambda r: pd.Series(r).mean() * PERIODS_PER_YEAR * 100,
                                     block_size=8, ci=0.90, seed=42)
        n_better = int((diff > 0).sum())
        print(f"\nConfronto accoppiato diretto (walk-forward low-beta meno BTC, solo OOS):")
        print(f"  Overperformance media: {mean_diff:+.2f}pp/anno, CI 90% [{lo:+.2f}, {hi:+.2f}]pp/anno "
              f"({'ESCLUDE' if lo * hi > 0 else 'include'} lo zero)")
        print(f"  Settimane in cui ha fatto meglio: {n_better}/{len(diff)} ({n_better/len(diff)*100:.0f}%)")

        # PBO-CSCV sulla griglia intera (full-sample, per contesto — NON e' il numero
        # walk-forward, che resta il test principale onesto sopra)
        perf_matrix = np.column_stack([net_btc.reindex(common_idx).values] +
                                       [net_by_window[bw].reindex(common_idx).values for bw in BETA_WINDOW_GRID])
        n_splits = 6
        usable_len = (len(perf_matrix) // n_splits) * n_splits
        pbo = pbo_cscv(perf_matrix[-usable_len:], n_splits=n_splits)
        print(f"  PBO-CSCV full-sample su {1+len(BETA_WINDOW_GRID)} configurazioni (contesto, non walk-forward): {pbo*100:.1f}%")


if __name__ == "__main__":
    main()
