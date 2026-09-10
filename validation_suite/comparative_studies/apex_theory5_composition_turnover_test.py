"""
apex_theory5_composition_turnover_test.py — Gap #3 e #4 della checklist di
produzione per la Teoria #5, richiesti direttamente dall'utente ("procedi
punto per punto"): (3) il basket low-beta ruota titoli piu' spesso di
quello low-vol? (costi di transazione reali non ancora confrontati
esplicitamente); (4) COSA seleziona low-beta rispetto a low-vol — stessi
settori? stessa concentrazione? Rilevante soprattutto perche' il vincolo
settoriale (V2_MAX_PER_SECTOR) e' di fatto INATTIVO in produzione in
questo momento (endpoint settori Yahoo 401, vedi apex_stocks_vs_etf_backtest.py).

Non serve un backtest di portafoglio completo per questo — solo la
sequenza di ricostruzioni trimestrali del basket (calendario, indipendente
dal segnale macro) per low-vol (produzione) e low-beta (lookback=26,
il valore di produzione, per un confronto diretto e onesto).

Nessuna riga di apex_v2_engine.py modificata.
"""

from __future__ import annotations
import json
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "validation_suite" / "framework"))
from apex_v2_engine import select_low_vol_basket, V2_MAX_PER_SECTOR, V2_CLASS_TICKER
from apex_stocks_vs_etf_backtest import (
    DATA_DIR, load_weekly_macro, load_weekly_sp500, load_pointintime_snapshots,
    eligible_universe_for_year, build_ohlc_like,
)
from sector_cap_grid_test import SECTOR_MAP_FILE
from apex_beta_basket_selection_test import select_low_beta_basket

LOOKBACK = 26
MIN_HISTORY = 40


def collect_basket_history(use_low_beta: bool, sector_of: dict):
    snapshots = load_pointintime_snapshots()
    with open(DATA_DIR / "sp500_tickers.json") as f:
        all_tickers = json.load(f)
    stock_prices = {}
    for t in all_tickers:
        try:
            stock_prices[t] = load_weekly_sp500(t)
        except FileNotFoundError:
            continue

    macro_prices = {V2_CLASS_TICKER[c]: load_weekly_macro(V2_CLASS_TICKER[c]) for c in V2_CLASS_TICKER}
    common_index = macro_prices["SPY"].index
    for s in macro_prices.values():
        common_index = common_index.intersection(s.index)
    weeks = list(common_index)
    n = len(weeks)

    prev_basket_tickers, current_basket = None, []
    basket_history = []  # (settimana, set di ticker)

    for i, wk in enumerate(weeks):
        if i < MIN_HISTORY:
            continue
        is_month_end = (i + 1 >= n) or (weeks[i + 1].month != wk.month)

        def rebuild_basket():
            eligible = eligible_universe_for_year(snapshots, wk.year)
            eq_data = {t: build_ohlc_like(p.loc[:wk]) for t, p in stock_prices.items() if t in eligible}
            if use_low_beta:
                spy_data_upto = build_ohlc_like(macro_prices["SPY"].loc[:wk])
                basket = select_low_beta_basket(eq_data, spy_data_upto, lookback_weeks=LOOKBACK,
                                                 prev_tickers=prev_basket_tickers, sector_of=sector_of)
            else:
                basket = select_low_vol_basket(eq_data, lookback_weeks=LOOKBACK, prev_tickers=prev_basket_tickers,
                                                sector_of=sector_of, max_per_sector=V2_MAX_PER_SECTOR)
            return [b["Ticker"] for b in basket]

        if not current_basket:
            current_basket = rebuild_basket()
            prev_basket_tickers = set(current_basket)
            basket_history.append((wk, set(current_basket)))
        elif is_month_end and wk.month in (3, 6, 9, 12):
            current_basket = rebuild_basket()
            prev_basket_tickers = set(current_basket)
            basket_history.append((wk, set(current_basket)))

    return basket_history


def main():
    sector_of = json.load(open(SECTOR_MAP_FILE))

    print("[*] Ricostruisco lo storico basket low-vol (produzione)...")
    hist_lowvol = collect_basket_history(False, sector_of)
    print("[*] Ricostruisco lo storico basket low-beta (lookback=26)...")
    hist_lowbeta = collect_basket_history(True, sector_of)

    def turnover_stats(hist, label):
        changes = []
        for i in range(1, len(hist)):
            prev_set, cur_set = hist[i - 1][1], hist[i][1]
            n_changed = len(cur_set - prev_set)
            changes.append(n_changed)
        top_n = len(hist[0][1])
        print(f"\n--- Turnover: {label} ---")
        print(f"  Ricostruzioni trimestrali: {len(hist)}")
        print(f"  Titoli sostituiti per ricostruzione: media {sum(changes)/len(changes):.1f}/{top_n} "
              f"({sum(changes)/len(changes)/top_n*100:.0f}%), mediana {sorted(changes)[len(changes)//2]}, "
              f"min/max {min(changes)}/{max(changes)}")
        return changes

    ch_lowvol = turnover_stats(hist_lowvol, "low-vol (produzione)")
    ch_lowbeta = turnover_stats(hist_lowbeta, "low-beta (lookback=26)")

    def sector_concentration(hist, label):
        sector_counts_per_rebuild = []
        for wk, basket in hist:
            secs = [sector_of.get(t, "N/D") for t in basket]
            c = Counter(secs)
            top_sector, top_count = c.most_common(1)[0]
            sector_counts_per_rebuild.append((top_sector, top_count, len(basket)))
        avg_top_frac = sum(c / n for _, c, n in sector_counts_per_rebuild) / len(sector_counts_per_rebuild)
        all_secs = Counter()
        for wk, basket in hist:
            all_secs.update(sector_of.get(t, "N/D") for t in basket)
        print(f"\n--- Concentrazione settoriale: {label} ---")
        print(f"  Quota media del settore piu' rappresentato per ricostruzione: {avg_top_frac*100:.1f}%")
        print(f"  Distribuzione settoriale cumulata (tutte le ricostruzioni, top 6): {all_secs.most_common(6)}")

    sector_concentration(hist_lowvol, "low-vol (produzione)")
    sector_concentration(hist_lowbeta, "low-beta (lookback=26)")

    overlap = []
    for (wk1, s1), (wk2, s2) in zip(hist_lowvol, hist_lowbeta):
        assert wk1 == wk2
        overlap.append(len(s1 & s2) / len(s1 | s2))
    print(f"\n--- Sovrapposizione titoli tra i due basket (Jaccard, stessa data) ---")
    print(f"  Media: {sum(overlap)/len(overlap)*100:.1f}%  |  Min: {min(overlap)*100:.1f}%  |  Max: {max(overlap)*100:.1f}%")


if __name__ == "__main__":
    main()
