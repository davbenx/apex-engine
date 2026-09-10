"""
apex_stable_beta_basket_test.py — Prossimo passo naturale dopo il terzo
giro di verifica della Teoria #5 (`apex_theory5_lookback_finegrid_test.py`):
invece di continuare a cercare un singolo lookback "ottimale" (che la
griglia fine ha mostrato essere in una banda 16-33 settimane, ma con
variazione punto-per-punto che e' in parte rumore di stima — un beta
calcolato su UNA sola finestra e' una stima statisticamente rumorosa),
si stabilizza il criterio di selezione mediando il beta su PIU' finestre
contemporaneamente (13/26/39/52 settimane — un ventaglio che copre da 3
mesi a 1 anno) invece di sceglierne una sola.

Questo e' un vincolo di STABILITA' TEMPORALE esplicito nella costruzione
del segnale stesso (non nel backtest) — un principio comune nella
letteratura sui fattori (es. combinare piu' orizzonti di momentum invece
di uno solo, gia' citato come possibile teoria da sondare in
APEX_V2_SPEC.md/README — qui applicato al beta invece che al momentum).
Riduce la varianza di stima del ranking rispetto a un singolo lookback,
a costo di reagire piu' lentamente a cambi di regime del beta di un
titolo.

Nessuna riga di apex_v2_engine.py modificata.
"""

from __future__ import annotations
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "validation_suite" / "framework"))
from apex_v2_engine import (
    compute_v2_macro_signal, select_low_vol_basket, V2_MAX_PER_SECTOR, V2_CLASS_TICKER,
    V2_EQUITY_TOP_N, V2_EQUITY_BUFFER_RANK, _weekly_close,
)
from metrics import cagr as _cagr, sharpe as _sharpe, max_drawdown as _max_drawdown
from tax_engine import apply_italian_tax as _apply_italian_tax
from statistical_validation import deflated_sharpe_ratio, block_bootstrap_ci
from apex_stocks_vs_etf_backtest import (
    DATA_DIR, PERIODS_PER_YEAR, load_weekly_macro, load_weekly_sp500, load_pointintime_snapshots,
    eligible_universe_for_year, build_ohlc_like,
)
from sector_cap_grid_test import SECTOR_MAP_FILE

STABLE_WINDOWS = [13, 26, 39, 52]


def select_stable_beta_basket(
    eq_data: Dict[str, pd.DataFrame],
    spy_data: pd.DataFrame,
    windows: List[int] = STABLE_WINDOWS,
    top_n: int = V2_EQUITY_TOP_N,
    prev_tickers: Optional[set] = None,
    buffer_rank: int = V2_EQUITY_BUFFER_RANK,
    sector_of: Optional[Dict[str, str]] = None,
    max_per_sector: int = V2_MAX_PER_SECTOR,
) -> List[dict]:
    """Come select_low_beta_basket ma il beta di ranking e' la MEDIA del beta
    calcolato su piu' finestre (13/26/39/52 settimane) invece di una sola —
    riduce la varianza di stima del criterio di selezione."""
    spy_wc = _weekly_close(spy_data)
    spy_ret = spy_wc.pct_change().dropna()
    max_window = max(windows)

    scored = []
    for sym, df in eq_data.items():
        wc = _weekly_close(df)
        ret = wc.pct_change().dropna()
        common = ret.index.intersection(spy_ret.index)
        if len(common) < max_window + 1:
            continue
        betas = []
        for w in windows:
            r = ret.reindex(common).iloc[-w:]
            m = spy_ret.reindex(common).iloc[-w:]
            var_m = float(m.var())
            if var_m > 1e-12:
                betas.append(float(r.cov(m) / var_m))
        if not betas or len(wc) == 0:
            continue
        stable_beta = float(np.mean(betas))
        scored.append((sym, stable_beta, float(wc.iloc[-1])))

    scored.sort(key=lambda t: t[1])
    ranked_syms = [sym for sym, _, _ in scored]
    rank_of = {sym: i for i, sym in enumerate(ranked_syms)}
    sector_of = sector_of or {}
    sector_count: Dict[str, int] = {}
    result: List[str] = []

    def sector_ok(sym: str) -> bool:
        s = sector_of.get(sym)
        return True if s is None else sector_count.get(s, 0) < max_per_sector

    def add(sym: str):
        result.append(sym)
        s = sector_of.get(sym)
        if s is not None:
            sector_count[s] = sector_count.get(s, 0) + 1

    prev_tickers = prev_tickers or set()
    incumbents_sorted = sorted(
        [s for s in prev_tickers if rank_of.get(s, 10**9) < buffer_rank],
        key=lambda s: rank_of.get(s, 10**9),
    )
    for sym in incumbents_sorted:
        if len(result) >= top_n:
            break
        if sector_ok(sym):
            add(sym)
    for sym in ranked_syms:
        if len(result) >= top_n:
            break
        if sym in result:
            continue
        if sector_ok(sym):
            add(sym)

    return [{"Ticker": sym} for sym in result[:top_n]]


def run_backtest(selection_mode: str, sector_of: dict):
    """selection_mode: 'low_vol' (produzione) | 'stable_beta' (nuovo)"""
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
            if selection_mode == "stable_beta":
                spy_data_upto = build_ohlc_like(macro_prices["SPY"].loc[:wk])
                basket = select_stable_beta_basket(eq_data, spy_data_upto, prev_tickers=prev_basket_tickers, sector_of=sector_of)
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


def main():
    sector_of = json.load(open(SECTOR_MAP_FILE))

    print(f"{'Variante':<45}{'CAGR netto':>12}{'Sharpe netto':>14}{'MaxDD netto':>13}{'Calmar':>9}")
    baseline = run_backtest("low_vol", sector_of)
    calmar_b = baseline["cagr_netto"] / abs(baseline["maxdd_netto"])
    print(f"{'Baseline produzione (low-vol, lookback=26)':<45}{baseline['cagr_netto']*100:>11.2f}%{baseline['sharpe_netto']:>14.2f}"
          f"{baseline['maxdd_netto']*100:>12.2f}%{calmar_b:>9.2f}")

    candidate = run_backtest("stable_beta", sector_of)
    calmar_c = candidate["cagr_netto"] / abs(candidate["maxdd_netto"])
    print(f"{'Beta stabilizzato (media 13/26/39/52 sett.)':<45}{candidate['cagr_netto']*100:>11.2f}%{candidate['sharpe_netto']:>14.2f}"
          f"{candidate['maxdd_netto']*100:>12.2f}%{calmar_c:>9.2f}")

    diff = (candidate["net"] - baseline["net"]).dropna()
    mean_diff = diff.mean() * PERIODS_PER_YEAR * 100
    lo, hi = block_bootstrap_ci(diff.values, lambda r: pd.Series(r).mean() * PERIODS_PER_YEAR * 100,
                                 block_size=12, ci=0.90, seed=42)
    n_better = int((diff > 0).sum())
    print(f"\nConfronto accoppiato diretto (beta stabilizzato meno baseline produzione):")
    print(f"  Overperformance media: {mean_diff:+.2f}pp/anno, CI 90% [{lo:+.2f}, {hi:+.2f}]pp/anno "
          f"({'ESCLUDE' if lo * hi > 0 else 'INCLUDE'} lo zero)")
    print(f"  Settimane in cui il beta stabilizzato ha fatto meglio: {n_better}/{len(diff)} ({n_better/len(diff)*100:.0f}%)")

    dsr = deflated_sharpe_ratio(candidate["sharpe_netto"], n_trials=2, n_obs=len(candidate["net"]))
    print(f"  DSR beta stabilizzato (n_trials=2): {dsr:.4f}")

    print("\n--- TRAIN/TEST split (prima meta' vs seconda meta', Sharpe per meta') ---")
    for label, r in [("Baseline produzione", baseline), ("Beta stabilizzato", candidate)]:
        net = r["net"]
        mid = len(net) // 2
        s1 = _sharpe(net.iloc[:mid], periods_per_year=PERIODS_PER_YEAR)
        s2 = _sharpe(net.iloc[mid:], periods_per_year=PERIODS_PER_YEAR)
        print(f"  {label:<45} 1a meta': {s1:>6.2f}   2a meta': {s2:>6.2f}")


if __name__ == "__main__":
    main()
