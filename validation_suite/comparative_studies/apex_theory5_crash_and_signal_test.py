"""
apex_theory5_crash_and_signal_test.py — Gap #5 e #6 della checklist di
produzione per la Teoria #5, richiesti direttamente dall'utente ("procedi
punto per punto"):
  (5) comportamento nei crash SPECIFICI (COVID 2020, bear market 2022),
      non solo nelle statistiche medie aggregate del backtest completo —
      un basket ok in media potrebbe nascondere un rischio di coda diverso.
  (6) interazione col segnale di timing: il timing macro Equity usa SPY
      come riferimento — se low-beta seleziona titoli sistematicamente
      meno correlati a SPY, potrebbe crearsi un disallineamento tra
      "quando il segnale dice ON/OFF" e "come si comporta davvero il
      basket".

Usa la serie di rendimento SOLO del basket azionario (ignorando il peso
macro/tasse/costi — non serve un backtest di portafoglio completo per
questi due controlli, solo il comportamento realizzato del basket stesso).

Nessuna riga di apex_v2_engine.py modificata.
"""

from __future__ import annotations
import json
import sys
from pathlib import Path

import numpy as np
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

CRASH_WINDOWS = [
    ("COVID crash 2020", "2020-02-14", "2020-03-27"),
    ("Bear market 2022", "2022-01-01", "2022-10-14"),
]


def collect_basket_returns(use_low_beta: bool, sector_of: dict):
    snapshots = load_pointintime_snapshots()
    with open(DATA_DIR / "sp500_tickers.json") as f:
        all_tickers = json.load(f)
    stock_prices = {}
    for t in all_tickers:
        try:
            stock_prices[t] = load_weekly_sp500(t)
        except FileNotFoundError:
            continue
    stock_rets = {t: p.pct_change() for t, p in stock_prices.items()}

    spy_price = load_weekly_macro("SPY")
    common_index = spy_price.index
    weeks = list(common_index)
    n = len(weeks)

    prev_basket_tickers, current_basket = None, []
    basket_ret_hist = []

    for i, wk in enumerate(weeks):
        if i < MIN_HISTORY:
            basket_ret_hist.append(np.nan)
            continue
        is_month_end = (i + 1 >= n) or (weeks[i + 1].month != wk.month)

        def rebuild_basket():
            eligible = eligible_universe_for_year(snapshots, wk.year)
            eq_data = {t: build_ohlc_like(p.loc[:wk]) for t, p in stock_prices.items() if t in eligible}
            if use_low_beta:
                spy_data_upto = build_ohlc_like(spy_price.loc[:wk])
                basket = select_low_beta_basket(eq_data, spy_data_upto, lookback_weeks=LOOKBACK,
                                                 prev_tickers=prev_basket_tickers, sector_of=sector_of)
            else:
                basket = select_low_vol_basket(eq_data, lookback_weeks=LOOKBACK, prev_tickers=prev_basket_tickers,
                                                sector_of=sector_of, max_per_sector=V2_MAX_PER_SECTOR)
            return [b["Ticker"] for b in basket]

        if not current_basket:
            current_basket = rebuild_basket()
            prev_basket_tickers = set(current_basket)
        elif is_month_end and wk.month in (3, 6, 9, 12):
            current_basket = rebuild_basket()
            prev_basket_tickers = set(current_basket)

        basket_ret = float(np.mean([stock_rets[t].loc[wk] for t in current_basket if t in stock_rets])) if current_basket else np.nan
        basket_ret_hist.append(basket_ret)

    return pd.Series(basket_ret_hist, index=weeks).dropna()


def main():
    sector_of = json.load(open(SECTOR_MAP_FILE))

    print("[*] Ricostruisco i rendimenti del basket low-vol (produzione)...")
    ret_lowvol = collect_basket_returns(False, sector_of)
    print("[*] Ricostruisco i rendimenti del basket low-beta (lookback=26)...")
    ret_lowbeta = collect_basket_returns(True, sector_of)

    spy_price = load_weekly_macro("SPY")
    spy_ret = spy_price.pct_change().reindex(ret_lowvol.index)

    print("\n--- Gap #6: correlazione col segnale di timing (SPY) ---")
    corr_lowvol = ret_lowvol.corr(spy_ret)
    corr_lowbeta = ret_lowbeta.reindex(ret_lowvol.index).corr(spy_ret)
    print(f"  Correlazione basket low-vol vs SPY:  {corr_lowvol:.3f}")
    print(f"  Correlazione basket low-beta vs SPY: {corr_lowbeta:.3f}")
    print(f"  Differenza: {corr_lowbeta - corr_lowvol:+.3f} "
          f"({'low-beta MENO correlato a SPY (rischio di disallineamento col segnale)' if corr_lowbeta < corr_lowvol else 'low-beta PIU correlato a SPY (allineamento simile o migliore)'})")

    print("\n--- Gap #5: comportamento nei crash specifici ---")
    for label, start, end in CRASH_WINDOWS:
        mask = (ret_lowvol.index >= start) & (ret_lowvol.index <= end)
        window_idx = ret_lowvol.index[mask]
        if len(window_idx) == 0:
            print(f"  {label}: nessun dato in questa finestra (fuori campione)")
            continue
        cum_lowvol = (1 + ret_lowvol.loc[window_idx]).prod() - 1
        cum_lowbeta = (1 + ret_lowbeta.reindex(window_idx).fillna(0.0)).prod() - 1
        cum_spy = (1 + spy_ret.reindex(window_idx).fillna(0.0)).prod() - 1
        print(f"  {label} ({window_idx.min().date()} -> {window_idx.max().date()}, {len(window_idx)} settimane):")
        print(f"    SPY:            {cum_spy*100:+7.2f}%")
        print(f"    Basket low-vol:  {cum_lowvol*100:+7.2f}%")
        print(f"    Basket low-beta: {cum_lowbeta*100:+7.2f}%")
        print(f"    Differenza (low-beta meno low-vol): {(cum_lowbeta-cum_lowvol)*100:+.2f}pp")


if __name__ == "__main__":
    main()
