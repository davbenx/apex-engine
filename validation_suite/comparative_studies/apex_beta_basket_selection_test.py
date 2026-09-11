"""
apex_beta_basket_selection_test.py — Teoria accademica #5 da sondare:
Quality/Betting-Against-Beta (Frazzini-Pedersen 2014, "Betting Against
Beta"; Asness-Frazzini-Pedersen 2019, "Quality Minus Junk") come criterio
alternativo alla bassa VOLATILITA' per select_low_vol_basket.

Limite di dati dichiarato: una vera "Quality" alla Asness-Frazzini-Pedersen
richiede fondamentali (ROE, leva, stabilita' utili, payout) non disponibili
da Yahoo Finance chart API (solo prezzo). Il pezzo di BAB effettivamente
testabile con SOLI dati di prezzo e' il criterio di selezione — BETA
(sensibilita' al mercato, calcolato per regressione contro SPY) invece di
VOLATILITA' REALIZZATA (dispersione assoluta, indipendente dal mercato).
Sono concettualmente diversi: un titolo puo' avere bassa volatilita' ma
alto beta (si muove poco in assoluto ma molto in sintonia col mercato) o
viceversa. La letteratura BAB sostiene che il beta basso e' sistematicamente
sotto-prezzato (investitori vincolati dalla leva pagano un premio per il
beta imballato nei titoli ad alto beta) — un meccanismo diverso da quello
originariamente ipotizzato per il basket low-vol di Apex.

Costruzione: replica IDENTICA di select_low_vol_basket (stesso buffer di
rank, stesso vincolo settoriale, stesso top_n) — l'UNICA differenza e' il
criterio di ranking: beta a 26 settimane contro SPY (stessa finestra di
lookback di V2_EQUITY_VOL_LOOKBACK) invece di volatilita' realizzata.
Nessuna riga di apex_v2_engine.py modificata — funzione standalone in
questo script.
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
    compute_v2_macro_signal, V2_CLASS_TICKER, V2_MAX_PER_SECTOR,
    V2_EQUITY_TOP_N, V2_EQUITY_VOL_LOOKBACK, V2_EQUITY_BUFFER_RANK, _weekly_close,
)
from metrics import cagr as _cagr, sharpe as _sharpe, max_drawdown as _max_drawdown
from tax_engine import apply_italian_tax as _apply_italian_tax
from statistical_validation import deflated_sharpe_ratio, block_bootstrap_ci
from apex_stocks_vs_etf_backtest import (
    DATA_DIR, PERIODS_PER_YEAR, load_weekly_macro, load_weekly_sp500, load_pointintime_snapshots,
    eligible_universe_for_year, build_ohlc_like,
)
from sector_cap_grid_test import SECTOR_MAP_FILE


def select_low_beta_basket(
    eq_data: Dict[str, pd.DataFrame],
    spy_data: pd.DataFrame,
    top_n: int = V2_EQUITY_TOP_N,
    lookback_weeks: int = V2_EQUITY_VOL_LOOKBACK,
    prev_tickers: Optional[set] = None,
    buffer_rank: int = V2_EQUITY_BUFFER_RANK,
    sector_of: Optional[Dict[str, str]] = None,
    max_per_sector: int = V2_MAX_PER_SECTOR,
) -> List[dict]:
    """Replica di select_low_vol_basket (apex_v2_engine.py) — stesso buffer di
    rank e vincolo settoriale, ma ranking per BETA a 26 settimane contro SPY
    invece che per volatilita' realizzata assoluta."""
    spy_wc = _weekly_close(spy_data)
    spy_ret = spy_wc.pct_change().dropna()

    scored = []
    for sym, df in eq_data.items():
        wc = _weekly_close(df)
        ret = wc.pct_change().dropna()
        common = ret.index.intersection(spy_ret.index)
        if len(common) < lookback_weeks + 1:
            continue
        r = ret.reindex(common).iloc[-lookback_weeks:]
        m = spy_ret.reindex(common).iloc[-lookback_weeks:]
        var_m = float(m.var())
        if var_m <= 1e-12 or len(wc) == 0:
            continue
        beta = float(r.cov(m) / var_m)
        scored.append((sym, beta, float(wc.iloc[-1])))

    scored.sort(key=lambda t: t[1])  # beta basso prima
    info_by_sym = {sym: (beta, price) for sym, beta, price in scored}
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


def run_backtest(use_beta_selection: bool, sector_of: dict):
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

    from apex_v2_engine import select_low_vol_basket
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
            spy_data_upto = build_ohlc_like(macro_prices["SPY"].loc[:wk])
            if use_beta_selection:
                basket = select_low_beta_basket(eq_data, spy_data_upto, prev_tickers=prev_basket_tickers, sector_of=sector_of)
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
    baseline = run_backtest(False, sector_of)
    calmar_b = baseline["cagr_netto"] / abs(baseline["maxdd_netto"])
    print(f"{'Basket low-VOLATILITY (produzione)':<45}{baseline['cagr_netto']*100:>11.2f}%{baseline['sharpe_netto']:>14.2f}"
          f"{baseline['maxdd_netto']*100:>12.2f}%{calmar_b:>9.2f}")

    candidate = run_backtest(True, sector_of)
    calmar_c = candidate["cagr_netto"] / abs(candidate["maxdd_netto"])
    print(f"{'Basket low-BETA (Betting Against Beta)':<45}{candidate['cagr_netto']*100:>11.2f}%{candidate['sharpe_netto']:>14.2f}"
          f"{candidate['maxdd_netto']*100:>12.2f}%{calmar_c:>9.2f}")

    diff = (candidate["net"] - baseline["net"]).dropna()
    mean_diff = diff.mean() * PERIODS_PER_YEAR * 100
    lo, hi = block_bootstrap_ci(diff.values, lambda r: pd.Series(r).mean() * PERIODS_PER_YEAR * 100,
                                 block_size=12, ci=0.90, seed=42)
    n_better = int((diff > 0).sum())
    print(f"\nConfronto accoppiato diretto (low-beta meno low-vol):")
    print(f"  Overperformance media: {mean_diff:+.2f}pp/anno, CI 90% [{lo:+.2f}, {hi:+.2f}]pp/anno "
          f"({'ESCLUDE' if lo * hi > 0 else 'INCLUDE'} lo zero)")
    print(f"  Settimane in cui low-beta ha fatto meglio: {n_better}/{len(diff)} ({n_better/len(diff)*100:.0f}%)")

    dsr = deflated_sharpe_ratio(candidate["sharpe_netto"], n_trials=2, n_obs=len(candidate["net"]))
    print(f"  DSR low-beta (n_trials=2): {dsr:.4f}")


if __name__ == "__main__":
    main()
