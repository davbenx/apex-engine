"""
apex_theory1_theory5_second_round_test.py — Secondo giro di verifica,
richiesto direttamente dall'utente, per le due teorie piu' vicine alla
significativita' statistica nel primo giro (apex_continuous_trend_signal_test.py,
Teoria #1, CI 90% [-0.17,+1.44]; apex_beta_basket_selection_test.py, Teoria
#5, CI 90% [-0.10,+2.09]). Un singolo punto stimato non basta a livello
istituzionale — tre controlli aggiuntivi:

  1. SENSIBILITA' alla scelta arbitraria di parametro in ciascuna teoria:
     Teoria #1 (STRENGTH_CAP, quanto puo' arrivare a pesare un trend molto
     forte) e Teoria #5 (finestra di lookback del beta) sono testate su una
     piccola griglia attorno al valore originale — se l'effetto e' reale
     dovrebbe reggere su scelte vicine, non essere un artefatto di un
     singolo valore scelto post-hoc.
  2. STACKING: le due modifiche toccano parti indipendenti del motore
     (Teoria #1: dimensione del peso per TUTTE le classi; Teoria #5: quale
     criterio seleziona i titoli nel basket Equity) — si combinano in modo
     additivo, o si annullano/si sovrappongono?
  3. TRAIN/TEST split (prima meta' vs seconda meta' del campione, split
     temporale non casuale): l'effetto e' stabile nel tempo o e' guidato
     da un sotto-periodo specifico? Calcolato SENZA ricalcolare il
     backtest — si riusa la serie di rendimento gia' prodotta per ciascuna
     configurazione, solo divisa in due meta'.

Nessuna riga di apex_v2_engine.py modificata.
"""

from __future__ import annotations
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "validation_suite" / "framework"))
from apex_v2_engine import (
    compute_v2_macro_signal, select_low_vol_basket, V2_MAX_PER_SECTOR, V2_CLASS_TICKER,
    V2_MA_WEEKS, V2_SHORT_MA_WEEKS, V2_HYSTERESIS_K, V2_HYSTERESIS_MIN, V2_HYSTERESIS_MAX,
    V2_VOL_WINDOW, V2_VOL_TARGET, V2_EQUITY_TOP_N, V2_EQUITY_BUFFER_RANK, _weekly_close, _realized_vol,
)
from metrics import cagr as _cagr, sharpe as _sharpe, max_drawdown as _max_drawdown
from tax_engine import apply_italian_tax as _apply_italian_tax
from statistical_validation import deflated_sharpe_ratio, pbo_cscv, block_bootstrap_ci
from apex_stocks_vs_etf_backtest import (
    DATA_DIR, PERIODS_PER_YEAR, load_weekly_macro, load_weekly_sp500, load_pointintime_snapshots,
    eligible_universe_for_year, build_ohlc_like,
)
from sector_cap_grid_test import SECTOR_MAP_FILE
from apex_beta_basket_selection_test import select_low_beta_basket


def compute_signal_continuous(
    b_data: Dict[str, pd.DataFrame],
    prev_hysteresis_state: Optional[Dict[str, bool]] = None,
    base_weight_per_class: float = 0.50,
    vol_target: float = V2_VOL_TARGET,
    strength_cap: float = 2.0,
) -> Tuple[Dict[str, float], Dict[str, bool], Dict[str, dict]]:
    """Identica a apex_continuous_trend_signal_test.py ma con strength_cap parametrico."""
    state = dict(prev_hysteresis_state) if prev_hysteresis_state else {}
    base_weight = {}
    vols = {}
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


def run_backtest(use_continuous: bool, strength_cap: float, use_low_beta: bool, beta_lookback: int, sector_of: dict):
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
            alloc, hysteresis_state, _debug = compute_signal_continuous(
                b_data, prev_hysteresis_state=hysteresis_state, strength_cap=strength_cap)
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
            if use_low_beta:
                spy_data_upto = build_ohlc_like(macro_prices["SPY"].loc[:wk])
                basket = select_low_beta_basket(eq_data, spy_data_upto, lookback_weeks=beta_lookback,
                                                 prev_tickers=prev_basket_tickers, sector_of=sector_of)
            else:
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

    return {
        "net": port_net_after_costs,
        "cagr_netto": _cagr(port_net_after_costs, PERIODS_PER_YEAR),
        "sharpe_netto": _sharpe(port_net_after_costs, periods_per_year=PERIODS_PER_YEAR),
        "maxdd_netto": _max_drawdown(port_net_after_costs),
    }


# (label, use_continuous, strength_cap, use_low_beta, beta_lookback)
GRID = [
    ("Baseline produzione", False, 2.0, False, 26),
    ("Teoria1: cap=1.5", True, 1.5, False, 26),
    ("Teoria1: cap=2.0 (originale)", True, 2.0, False, 26),
    ("Teoria1: cap=3.0", True, 3.0, False, 26),
    ("Teoria5: lookback=13sett.", False, 2.0, True, 13),
    ("Teoria5: lookback=26sett. (originale)", False, 2.0, True, 26),
    ("Teoria5: lookback=52sett.", False, 2.0, True, 52),
    ("Combinato: Teoria1(cap=2.0) + Teoria5(lookback=26)", True, 2.0, True, 26),
]


def main():
    sector_of = json.load(open(SECTOR_MAP_FILE))

    print(f"{'Config':<50}{'CAGR netto':>12}{'Sharpe netto':>14}{'MaxDD netto':>13}")
    results = {}
    for label, use_cont, cap, use_lb, lb in GRID:
        r = run_backtest(use_cont, cap, use_lb, lb, sector_of)
        results[label] = r
        print(f"{label:<50}{r['cagr_netto']*100:>11.2f}%{r['sharpe_netto']:>14.2f}{r['maxdd_netto']*100:>12.2f}%")

    baseline_label = "Baseline produzione"
    print("\n--- Confronto accoppiato diretto vs baseline ---")
    for label, _, _, _, _ in GRID[1:]:
        diff = (results[label]["net"] - results[baseline_label]["net"]).dropna()
        mean_diff = diff.mean() * PERIODS_PER_YEAR * 100
        lo, hi = block_bootstrap_ci(diff.values, lambda r: pd.Series(r).mean() * PERIODS_PER_YEAR * 100,
                                     block_size=12, ci=0.90, seed=42)
        print(f"  {label:<48} {mean_diff:+6.2f}pp/anno  CI90% [{lo:+.2f}, {hi:+.2f}] "
              f"{'ESCLUDE zero' if lo * hi > 0 else 'include zero'}")

    variant_order = [label for label, _, _, _, _ in GRID]
    perf_matrix = np.column_stack([results[m]["net"].values for m in variant_order])
    n_splits = 8
    usable_len = (len(perf_matrix) // n_splits) * n_splits
    pbo = pbo_cscv(perf_matrix[-usable_len:], n_splits=n_splits)
    print(f"\nPBO-CSCV su {len(variant_order)} configurazioni: {pbo*100:.1f}%")

    best_label = max(variant_order, key=lambda m: results[m]["sharpe_netto"])
    dsr = deflated_sharpe_ratio(results[best_label]["sharpe_netto"], n_trials=len(variant_order), n_obs=len(results[best_label]["net"]))
    print(f"Migliore per Sharpe: {best_label} (Sharpe {results[best_label]['sharpe_netto']:.2f}) — DSR (n_trials={len(variant_order)}): {dsr:.4f}")

    print("\n--- TRAIN/TEST split (prima meta' vs seconda meta' del campione, Sharpe per meta') ---")
    print(f"{'Config':<50}{'Sharpe 1a meta':>16}{'Sharpe 2a meta':>16}")
    for label, _, _, _, _ in GRID:
        net = results[label]["net"]
        mid = len(net) // 2
        first_half, second_half = net.iloc[:mid], net.iloc[mid:]
        s1 = _sharpe(first_half, periods_per_year=PERIODS_PER_YEAR)
        s2 = _sharpe(second_half, periods_per_year=PERIODS_PER_YEAR)
        print(f"{label:<50}{s1:>16.2f}{s2:>16.2f}")


if __name__ == "__main__":
    main()
