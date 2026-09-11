"""
apex_theory1_rolling_attribution_test.py — Terzo giro di verifica per la
Teoria #1 (segnale di trend continuo), richiesto direttamente dall'utente
("dobbiamo vederci chiaro"). Il secondo giro ha mostrato un singolo split
train/test (prima meta' vs seconda meta') in cui la Teoria #1 (cap=3.0,
la piu' forte) risultava leggermente PEGGIORE del baseline nella seconda
meta' nonostante la significativita' sull'intero campione — ma un singolo
split e' un solo punto dati sulla stabilita' temporale, e non dice QUALE
classe guida la differenza.

Due diagnostici qui, sullo stesso paio di configurazioni (baseline binario
vs continuo cap=3.0, basket azionario di produzione INVARIATO in entrambi
per isolare solo l'effetto Teoria #1):
  1. SHARPE ROLLING a finestra di 104 settimane (2 anni), calcolato ogni
     26 settimane lungo tutto il campione — mostra COME evolve nel tempo
     il vantaggio (o svantaggio) della versione continua, non solo un
     prima/dopo aggregato.
  2. ATTRIBUZIONE PER CLASSE: per ciascuna classe macro (Equity/Bonds/
     Gold/Crypto), calcola il contributo cumulato alla differenza di
     rendimento (continuo meno binario) — quale classe guida il
     vantaggio full-sample, e quella classe continua a contribuire
     positivamente anche nella seconda meta' del campione o no?

Nessuna riga di apex_v2_engine.py modificata.
"""

from __future__ import annotations
import json
import sys
from pathlib import Path
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "validation_suite" / "framework"))
from apex_v2_engine import (
    compute_v2_macro_signal, select_low_vol_basket, V2_MAX_PER_SECTOR, V2_CLASS_TICKER,
    V2_MA_WEEKS, V2_SHORT_MA_WEEKS, V2_HYSTERESIS_K, V2_HYSTERESIS_MIN, V2_HYSTERESIS_MAX,
    V2_VOL_WINDOW, V2_VOL_TARGET, _weekly_close, _realized_vol,
)
from metrics import cagr as _cagr, sharpe as _sharpe, max_drawdown as _max_drawdown
from tax_engine import apply_italian_tax as _apply_italian_tax
from apex_stocks_vs_etf_backtest import (
    DATA_DIR, PERIODS_PER_YEAR, load_weekly_macro, load_weekly_sp500, load_pointintime_snapshots,
    eligible_universe_for_year, build_ohlc_like,
)
from sector_cap_grid_test import SECTOR_MAP_FILE

STRENGTH_CAP = 3.0  # la configurazione piu' forte/significativa del secondo giro
ROLLING_WINDOW = 104  # 2 anni


def compute_signal_continuous(b_data, prev_hysteresis_state=None, base_weight_per_class=0.50,
                               vol_target=V2_VOL_TARGET, strength_cap=STRENGTH_CAP):
    state = dict(prev_hysteresis_state) if prev_hysteresis_state else {}
    base_weight, vols = {}, {}
    for cls, ticker in V2_CLASS_TICKER.items():
        wc = _weekly_close(b_data.get(ticker))
        v = _realized_vol(wc, V2_VOL_WINDOW)
        if v is not None:
            vols[cls] = v
    for cls, ticker in V2_CLASS_TICKER.items():
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
        strength = float(np.clip(dist / band, 1.0, strength_cap)) if (is_active and band > 1e-9) else 1.0
        base_weight[cls] = base_weight_per_class * strength if is_active else 0.0

    port_vol = sum(base_weight.get(cls, 0.0) * vols[cls] for cls in V2_CLASS_TICKER if cls in vols)
    scale = min(1.0, vol_target / port_vol) if port_vol > 1e-6 else 1.0
    raw_weights = {cls: base_weight.get(cls, 0.0) * scale for cls in V2_CLASS_TICKER}
    total_raw = sum(raw_weights.values())
    if total_raw > 1.0:
        raw_weights = {cls: w / total_raw for cls, w in raw_weights.items()}
    allocations = {cls: round(raw_weights.get(cls, 0.0) * 100.0, 2) for cls in V2_CLASS_TICKER}
    return allocations, state, {}


def run_backtest(use_continuous: bool, sector_of: dict):
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

    macro_prices = {V2_CLASS_TICKER[c]: load_weekly_macro(V2_CLASS_TICKER[c]) for c in V2_CLASS_TICKER}
    common_index = macro_prices["SPY"].index
    for s in macro_prices.values():
        common_index = common_index.intersection(s.index)
    weeks = list(common_index)
    n = len(weeks)

    ief_ret = macro_prices["IEF"].pct_change()
    gld_ret = macro_prices["GLD"].pct_change()
    btc_ret = macro_prices["BTC-USD"].pct_change()

    hysteresis_state, prev_basket_tickers, current_basket = None, None, []
    locked_alloc = None
    macro_alloc_history, equity_return_basket = [], []

    MIN_HISTORY = 40
    for i, wk in enumerate(weeks):
        if i < MIN_HISTORY:
            macro_alloc_history.append(None)
            equity_return_basket.append(0.0)
            continue
        b_data = {V2_CLASS_TICKER[c]: build_ohlc_like(macro_prices[V2_CLASS_TICKER[c]].loc[:wk]) for c in V2_CLASS_TICKER}
        if use_continuous:
            alloc, hysteresis_state, _debug = compute_signal_continuous(b_data, prev_hysteresis_state=hysteresis_state)
        else:
            alloc, hysteresis_state, _debug = compute_v2_macro_signal(b_data, prev_hysteresis_state=hysteresis_state)
        is_month_end = (i + 1 >= n) or (weeks[i + 1].month != wk.month)
        if locked_alloc is None:
            locked_alloc = alloc
        macro_alloc_history.append(dict(locked_alloc))
        if is_month_end:
            locked_alloc = alloc

        def rebuild_basket():
            eligible = eligible_universe_for_year(snapshots, wk.year)
            eq_data = {t: build_ohlc_like(p.loc[:wk]) for t, p in stock_prices.items() if t in eligible}
            basket = select_low_vol_basket(eq_data, prev_tickers=prev_basket_tickers, sector_of=sector_of, max_per_sector=V2_MAX_PER_SECTOR)
            return [b["Ticker"] for b in basket]

        if not current_basket:
            current_basket = rebuild_basket()
            prev_basket_tickers = set(current_basket)
        elif is_month_end and wk.month in (3, 6, 9, 12):
            current_basket = rebuild_basket()
            prev_basket_tickers = set(current_basket)

        basket_ret = float(np.mean([stock_rets[t].loc[wk] for t in current_basket if t in stock_rets])) if current_basket else 0.0
        equity_return_basket.append(basket_ret)

    valid_from = MIN_HISTORY
    idx = weeks[valid_from:]

    def alloc_frac(cls):
        return pd.Series([macro_alloc_history[i].get(cls, 0.0) / 100.0 for i in range(valid_from, n)], index=idx)

    weights_df = pd.DataFrame({
        "Equity": alloc_frac("Equities"), "Bonds": alloc_frac("Bonds"),
        "Gold": alloc_frac("Gold"), "Crypto": alloc_frac("Crypto"),
    })
    returns_df = pd.DataFrame({
        "Equity": pd.Series(equity_return_basket[valid_from:], index=idx),
        "Bonds": ief_ret.reindex(idx).fillna(0.0),
        "Gold": gld_ret.reindex(idx).fillna(0.0),
        "Crypto": btc_ret.reindex(idx).fillna(0.0),
    })
    tax_types = {"Equity": "REDDITO_DIVERSO", "Bonds": "REDDITO_CAPITALE", "Gold": "REDDITO_DIVERSO", "Crypto": "REDDITO_DIVERSO"}

    weight_change = weights_df.diff().abs().sum(axis=1).fillna(0.0)
    cost_bps_map = {"Equity": 0.0010, "Bonds": 0.0008, "Gold": 0.0010, "Crypto": 0.0010}
    cost_drag = weight_change * np.mean(list(cost_bps_map.values()))
    port_net = _apply_italian_tax(returns_df, weights_df, tax_types=tax_types)
    port_net_after_costs = port_net - cost_drag

    # contributo lordo per classe (peso x rendimento, PRE-tasse — la tassazione e' path-dependent
    # a livello di ledger complessivo, non scomponibile in modo esatto per classe; il lordo e'
    # comunque la misura corretta per capire QUALE classe guida la differenza di posizionamento)
    class_contrib = returns_df * weights_df

    return {"net": port_net_after_costs, "weights_df": weights_df, "class_contrib": class_contrib}


def main():
    sector_of = json.load(open(SECTOR_MAP_FILE))

    print("[*] Backtest baseline (binario)...")
    baseline = run_backtest(False, sector_of)
    print("[*] Backtest continuo (cap=3.0)...")
    candidate = run_backtest(True, sector_of)

    net_b, net_c = baseline["net"], candidate["net"]
    diff = (net_c - net_b).dropna()

    print(f"\n--- SHARPE ROLLING ({ROLLING_WINDOW} settimane), ogni 26 settimane ---")
    print(f"{'Fine finestra':<14}{'Sharpe baseline':>18}{'Sharpe continuo':>18}{'Differenza':>13}")
    for i in range(ROLLING_WINDOW, len(net_b), 26):
        window_b = net_b.iloc[i - ROLLING_WINDOW:i]
        window_c = net_c.iloc[i - ROLLING_WINDOW:i]
        sb = _sharpe(window_b, periods_per_year=PERIODS_PER_YEAR)
        sc = _sharpe(window_c, periods_per_year=PERIODS_PER_YEAR)
        print(f"{net_b.index[i-1].date()!s:<14}{sb:>18.2f}{sc:>18.2f}{sc-sb:>+13.2f}")

    print(f"\n--- ATTRIBUZIONE PER CLASSE: contributo cumulato alla differenza (continuo meno binario) ---")
    cc_b, cc_c = baseline["class_contrib"], candidate["class_contrib"]
    common_idx = cc_b.index.intersection(cc_c.index)
    diff_by_class = (cc_c.reindex(common_idx) - cc_b.reindex(common_idx))
    mid = len(common_idx) // 2
    first_half_idx, second_half_idx = common_idx[:mid], common_idx[mid:]

    print(f"{'Classe':<10}{'Contributo cumul. 1a meta':>28}{'Contributo cumul. 2a meta':>28}{'Totale':>12}")
    for cls in ["Equity", "Bonds", "Gold", "Crypto"]:
        c1 = diff_by_class.loc[first_half_idx, cls].sum() * 100
        c2 = diff_by_class.loc[second_half_idx, cls].sum() * 100
        tot = c1 + c2
        print(f"{cls:<10}{c1:>27.2f}%{c2:>27.2f}%{tot:>11.2f}%")

    print(f"\nDifferenza totale cumulata (continuo meno binario, somma di tutte le classi): "
          f"{diff_by_class.sum().sum()*100:+.2f}% su tutto il campione")


if __name__ == "__main__":
    main()
