"""
apex_international_equities_class_test.py — Idea #7 della lista di
approfondimento: diversificazione geografica reale. Apex e' oggi 100%
azionario USA (basket S&P 500) e asset in USD — la letteratura su home
bias (Ilmanen "Expected Returns", Asness) e' tra le piu' robuste in
finanza: nessuna garanzia che lo S&P 500 sovraperformi gli altri mercati
sviluppati nei prossimi 30 anni quanto ha fatto negli ultimi 30.

Design: aggiunta di una QUINTA classe macro indipendente, "IntlEquities",
su EFA (iShares MSCI EAFE — Europa + Giappone + Australasia + Estremo
Oriente, copre esattamente "Europa, Giappone" richiesto), stesso
meccanismo di trend/isteresi delle altre 4 classi (MA40w/20w, banda
adattiva alla volatilita', vol-target di portafoglio invariato). Nessuna
selezione titolo-per-titolo (esposizione ampia via ETF) — aggira
deliberatamente il limite dei dati point-in-time che ha bloccato il test
BAB non-US (idea #1, ancora in coda). Trattamento fiscale REDDITO_DIVERSO,
stessa classificazione di GLD in questo progetto (ETF domiciliato USA non
UCITS).

Solo 2 varianti (nessun parametro continuo da selezionare in walk-forward,
e' una scelta di design binaria: aggiungere o no la classe): baseline
attuale (4 classi) vs 5 classi con IntlEquities. Efficienza: il basket
azionario low-beta USA e' IDENTICO in entrambe le varianti (non dipende
da EFA) — calcolato una sola volta e riusato.
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

from apex_v2_engine import (
    select_low_beta_basket, V2_CLASS_TICKER, V2_MA_WEEKS, V2_SHORT_MA_WEEKS,
    V2_HYSTERESIS_K, V2_HYSTERESIS_MIN, V2_HYSTERESIS_MAX, V2_VOL_WINDOW, V2_VOL_TARGET,
)
from metrics import cagr as _cagr, sharpe as _sharpe, max_drawdown as _max_drawdown
from tax_engine import apply_italian_tax as _apply_italian_tax
from statistical_validation import pbo_cscv, block_bootstrap_ci
from apex_stocks_vs_etf_backtest import (
    DATA_DIR, PERIODS_PER_YEAR, load_weekly_macro, load_weekly_sp500, load_pointintime_snapshots,
    eligible_universe_for_year, build_ohlc_like, _fetch_weekly_adj,
)
from sector_cap_grid_test import SECTOR_MAP_FILE

BASE_WEIGHT_PER_CLASS = 0.50
CLASSES_5 = dict(V2_CLASS_TICKER, IntlEquities="EFA")


def _weekly_close(df):
    if df is None or df.empty:
        return pd.Series(dtype=float)
    return df["Close"].resample("W-FRI").last().dropna()


def _realized_vol(weekly_close, window):
    if len(weekly_close) < window + 1:
        return None
    r = weekly_close.pct_change().dropna().iloc[-window:]
    v = float(r.std() * np.sqrt(52))
    return v if v > 1e-6 else None


def ensure_efa_data():
    f = DATA_DIR / "EFA_weekly.csv"
    if not f.exists():
        print("[*] Fetch EFA...")
        _fetch_weekly_adj("EFA", "25y").to_csv(f)


def compute_macro_signal_n_classes(b_data, prev_hysteresis_state, classes_ticker: dict, vol_target=V2_VOL_TARGET):
    """Generalizzazione di compute_v2_macro_signal a un numero arbitrario di
    classi (dict nome->ticker) — stessa logica esatta per classe, nessun
    accoppiamento tra classi salvo il vol-target di portafoglio e il
    limite di non-leva, gia' cosi' in produzione."""
    state = dict(prev_hysteresis_state) if prev_hysteresis_state else {}
    base_weight, vols = {}, {}

    for cls, ticker in classes_ticker.items():
        wc = _weekly_close(b_data.get(ticker))
        v = _realized_vol(wc, V2_VOL_WINDOW)
        if v is not None:
            vols[cls] = v

    for cls, ticker in classes_ticker.items():
        df = b_data.get(ticker)
        wc = _weekly_close(df)
        if len(wc) < V2_MA_WEEKS:
            base_weight[cls] = 0.0
            continue

        ma_long = wc.rolling(V2_MA_WEEKS, min_periods=V2_MA_WEEKS).mean()
        ma_short = wc.rolling(V2_SHORT_MA_WEEKS, min_periods=V2_SHORT_MA_WEEKS).mean()
        price = float(wc.iloc[-1])
        ma_long_val = float(ma_long.iloc[-1])
        ma_short_val = float(ma_short.iloc[-1]) if not np.isnan(ma_short.iloc[-1]) else ma_long_val
        dist = (price / ma_long_val - 1.0) if ma_long_val > 0 else 0.0

        wk_vol = (vols[cls] / float(np.sqrt(52))) if cls in vols else 0.02
        band = float(max(V2_HYSTERESIS_MIN, min(V2_HYSTERESIS_MAX, V2_HYSTERESIS_K * wk_vol)))

        was_active = bool(state.get(cls, False))
        trend_long_on = (dist > -band) if was_active else (dist > band)
        trend_short_on = price > ma_short_val if ma_short_val > 0 else False
        is_active = trend_long_on and trend_short_on
        state[cls] = trend_long_on
        base_weight[cls] = BASE_WEIGHT_PER_CLASS if is_active else 0.0

    port_vol = sum(base_weight.get(cls, 0.0) * vols[cls] for cls in classes_ticker if cls in vols)
    scale = min(1.0, vol_target / port_vol) if port_vol > 1e-6 else 1.0
    raw_weights = {cls: base_weight.get(cls, 0.0) * scale for cls in classes_ticker}
    total_raw = sum(raw_weights.values())
    if total_raw > 1.0:
        raw_weights = {cls: w / total_raw for cls, w in raw_weights.items()}
    allocations = {cls: round(raw_weights.get(cls, 0.0) * 100.0, 2) for cls in classes_ticker}
    return allocations, state


def precompute_equity_basket(sector_of: dict, weeks, macro_prices, stock_prices, stock_rets, snapshots):
    hysteresis_state_dummy = None
    prev_basket_tickers, current_basket = None, []
    equity_return_basket = []
    n = len(weeks)
    MIN_HISTORY = 40
    for i, wk in enumerate(weeks):
        if i < MIN_HISTORY:
            equity_return_basket.append(0.0)
            continue
        b_data = {V2_CLASS_TICKER[c]: build_ohlc_like(macro_prices[V2_CLASS_TICKER[c]].loc[:wk]) for c in V2_CLASS_TICKER}
        alloc, hysteresis_state_dummy = compute_macro_signal_n_classes(b_data, hysteresis_state_dummy, V2_CLASS_TICKER)
        is_month_end = (i + 1 >= n) or (weeks[i + 1].month != wk.month)

        def rebuild_basket():
            eligible = eligible_universe_for_year(snapshots, wk.year)
            eq_data = {t: build_ohlc_like(p.loc[:wk]) for t, p in stock_prices.items() if t in eligible}
            spy_data_upto = build_ohlc_like(macro_prices["SPY"].loc[:wk])
            basket = select_low_beta_basket(eq_data, spy_data_upto, prev_tickers=prev_basket_tickers, sector_of=sector_of)
            return [b["Ticker"] for b in basket]

        if alloc.get("Equities", 0) <= 0:
            current_basket = []
            prev_basket_tickers = None
        elif not current_basket:
            current_basket = rebuild_basket()
            prev_basket_tickers = set(current_basket)
        elif is_month_end and wk.month in (3, 6, 9, 12):
            current_basket = rebuild_basket()
            prev_basket_tickers = set(current_basket)

        basket_ret = float(np.mean([stock_rets[t].loc[wk] for t in current_basket if t in stock_rets])) if current_basket else 0.0
        equity_return_basket.append(basket_ret)
    return equity_return_basket


def run_variant(classes_ticker: dict, weeks, macro_prices, macro_rets, equity_return_basket):
    n = len(weeks)
    hysteresis_state = None
    locked_alloc = None
    macro_alloc_history = []
    MIN_HISTORY = 40
    for i, wk in enumerate(weeks):
        if i < MIN_HISTORY:
            macro_alloc_history.append(None)
            continue
        b_data = {ticker: build_ohlc_like(macro_prices[ticker].loc[:wk]) for ticker in classes_ticker.values()}
        alloc, hysteresis_state = compute_macro_signal_n_classes(b_data, hysteresis_state, classes_ticker)
        is_month_end = (i + 1 >= n) or (weeks[i + 1].month != wk.month)
        if locked_alloc is None:
            locked_alloc = alloc
        macro_alloc_history.append(dict(locked_alloc))
        if is_month_end:
            locked_alloc = alloc

    valid_from = MIN_HISTORY
    idx = weeks[valid_from:]

    def alloc_frac(cls):
        return pd.Series([macro_alloc_history[i].get(cls, 0.0) / 100.0 for i in range(valid_from, n)], index=idx)

    weights_data = {"Equity": alloc_frac("Equities"), "Bonds": alloc_frac("Bonds"), "Gold": alloc_frac("Gold"), "Crypto": alloc_frac("Crypto")}
    returns_data = {
        "Equity": pd.Series(equity_return_basket[valid_from:], index=idx),
        "Bonds": macro_rets["IEF"].reindex(idx).fillna(0.0),
        "Gold": macro_rets["GLD"].reindex(idx).fillna(0.0),
        "Crypto": macro_rets["BTC-USD"].reindex(idx).fillna(0.0),
    }
    tax_types = {"Equity": "REDDITO_DIVERSO", "Bonds": "REDDITO_CAPITALE", "Gold": "REDDITO_DIVERSO", "Crypto": "REDDITO_DIVERSO"}

    if "IntlEquities" in classes_ticker:
        weights_data["IntlEquities"] = alloc_frac("IntlEquities")
        returns_data["IntlEquities"] = macro_rets["EFA"].reindex(idx).fillna(0.0)
        tax_types["IntlEquities"] = "REDDITO_DIVERSO"

    weights_df = pd.DataFrame(weights_data)
    returns_df = pd.DataFrame(returns_data)

    weight_change = weights_df.diff().abs().sum(axis=1).fillna(0.0)
    cost_bps_map = {k: 0.0010 for k in weights_data}
    cost_bps_map["Bonds"] = 0.0008
    cost_drag = weight_change * np.mean(list(cost_bps_map.values()))
    port_net = _apply_italian_tax(returns_df, weights_df, tax_types=tax_types)
    return port_net - cost_drag, weights_df


def main():
    ensure_efa_data()
    sector_of = json.load(open(SECTOR_MAP_FILE))
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

    macro_prices = {ticker: load_weekly_macro(ticker) if ticker != "EFA" else load_weekly_macro("EFA") for ticker in CLASSES_5.values()}
    common_index = macro_prices["SPY"].index
    for s in macro_prices.values():
        common_index = common_index.intersection(s.index)
    weeks = list(common_index.sort_values())
    macro_rets = {ticker: macro_prices[ticker].pct_change() for ticker in CLASSES_5.values()}

    print(f"[*] Campione comune (limitato da EFA 2001+ o da BTC 2014+, il piu' tardo): {len(weeks)} settimane, "
          f"{weeks[0].date()} -> {weeks[-1].date()}")

    print("[*] Precalcolo basket azionario low-beta USA (identico in entrambe le varianti)...")
    equity_return_basket = precompute_equity_basket(sector_of, weeks, macro_prices, stock_prices, stock_rets, snapshots)

    print("[*] Baseline (4 classi, attuale)...")
    net_4, w_4 = run_variant(V2_CLASS_TICKER, weeks, macro_prices, macro_rets, equity_return_basket)
    print("[*] 5 classi (+ IntlEquities/EFA)...")
    net_5, w_5 = run_variant(CLASSES_5, weeks, macro_prices, macro_rets, equity_return_basket)

    common_idx = net_4.index.intersection(net_5.index).sort_values()
    n4, n5 = net_4.reindex(common_idx), net_5.reindex(common_idx)

    print(f"\n{'Variante':<30}{'CAGR netto':>12}{'Sharpe netto':>14}{'MaxDD netto':>13}")
    for label, net in [("Baseline (4 classi)", n4), ("5 classi (+IntlEquities)", n5)]:
        c, s, dd = _cagr(net, PERIODS_PER_YEAR), _sharpe(net, periods_per_year=PERIODS_PER_YEAR), _max_drawdown(net)
        print(f"{label:<30}{c*100:>11.2f}%{s:>14.2f}{dd*100:>12.2f}%")
    print(f"  Peso medio IntlEquities: {w_5['IntlEquities'].mean()*100:.1f}%")

    diff = (n5 - n4).dropna()
    mean_diff = diff.mean() * PERIODS_PER_YEAR * 100
    lo, hi = block_bootstrap_ci(diff.values, lambda r: pd.Series(r).mean() * PERIODS_PER_YEAR * 100, block_size=12, ci=0.90, seed=42)
    n_better = int((diff > 0).sum())
    print(f"\nConfronto accoppiato diretto (5 classi meno baseline):")
    print(f"  Overperformance media: {mean_diff:+.2f}pp/anno, CI 90% [{lo:+.2f}, {hi:+.2f}]pp/anno "
          f"({'ESCLUDE' if lo * hi > 0 else 'include'} lo zero)")
    print(f"  Settimane in cui ha fatto meglio: {n_better}/{len(diff)} ({n_better/len(diff)*100:.0f}%)")

    perf_matrix = np.column_stack([n4.values, n5.values])
    n_splits = 8
    usable_len = (len(perf_matrix) // n_splits) * n_splits
    pbo = pbo_cscv(perf_matrix[-usable_len:], n_splits=n_splits)
    print(f"\nPBO-CSCV su 2 configurazioni (4/5 classi): {pbo*100:.1f}%")


if __name__ == "__main__":
    main()
