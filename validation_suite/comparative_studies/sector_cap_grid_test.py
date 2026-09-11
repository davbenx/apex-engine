"""
sector_cap_grid_test.py — L'utente contesta a memoria che l'ottimo per
V2_MAX_PER_SECTOR fosse 4-5, non 2 (il valore adottato in produzione,
APEX_V2_SPEC.md §8.7). Verificato per iscritto: §8.7 e la history git di
apex_v2_engine.py mostrano solo un confronto a due punti ("nessun vincolo"
vs "max 2/settore"), il parametro non e' mai stato 4 o 5 in nessun commit.
Questo script chiude la domanda con una vera grid search: {Nessuno, 2, 3, 4,
5} testati sullo stesso identico harness walk-forward point-in-time di
apex_stocks_vs_etf_backtest.py (stesso universo S&P 500 reale point-in-time,
stesso overlay macro v2, stessi costi/tasse) — l'unica variabile che cambia
e' max_per_sector, con dati SETTORE REALI ora recuperabili (fetch_sector_map
di backend.py, corretto in questa sessione: l'endpoint quoteSummary
richiedeva un cookie+crumb non gestito, causa del 401 che teneva il vincolo
§8.7 silenziosamente disattivo in produzione).

Due finestre riportate, come nell'originale §8.7: campione pieno (~12-15
anni) e finestra recente Feb 2024-oggi (dove la concentrazione settoriale
aveva eroso la significativita' dell'alpha).
"""

from __future__ import annotations
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]  # validation_suite/comparative_studies/ -> validation_suite/ -> repo root
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "validation_suite" / "framework"))
from apex_v2_engine import compute_v2_macro_signal, select_low_vol_basket, V2_CLASS_TICKER
from metrics import cagr as _cagr, sharpe as _sharpe, max_drawdown as _max_drawdown
from tax_engine import apply_italian_tax as _apply_italian_tax
from apex_stocks_vs_etf_backtest import (
    DATA_DIR, POINTINTIME_FILE, TRANSACTION_COST_BPS, PERIODS_PER_YEAR,
    load_weekly_macro, load_weekly_sp500, load_pointintime_snapshots,
    eligible_universe_for_year, build_ohlc_like,
)

SECTOR_MAP_FILE = DATA_DIR / "sp500_sector_map.json"


def _capm_alpha(port_ret: pd.Series, bench_ret: pd.Series) -> tuple[float, float, float]:
    """Alpha annualizzato via OLS (port - rf ~ beta*(bench - rf) + alpha), rf=0
    (stessa convenzione usata altrove in questo progetto per i confronti netti).
    t-stat/p-value via approssimazione normale (no scipy, stesso stile di
    statistical_validation._norm_cdf) — valida per n grande come nei nostri
    campioni settimanali pluriennali."""
    from statistical_validation import _norm_cdf
    y = port_ret.values
    x = bench_ret.values
    n = len(y)
    X = np.column_stack([np.ones(n), x])
    beta_hat, resid, _, _ = np.linalg.lstsq(X, y, rcond=None)
    alpha_weekly, beta = beta_hat
    fitted = X @ beta_hat
    residuals = y - fitted
    dof = n - 2
    sigma2 = np.sum(residuals ** 2) / dof
    xtx_inv = np.linalg.inv(X.T @ X)
    se_alpha = np.sqrt(sigma2 * xtx_inv[0, 0])
    t_stat = alpha_weekly / se_alpha if se_alpha > 0 else 0.0
    p_value = 2 * (1 - _norm_cdf(abs(t_stat)))
    alpha_annual = alpha_weekly * 52
    return alpha_annual, t_stat, p_value


def run_backtest(max_per_sector, sector_of):
    sector_map_for_measurement = sector_of  # sempre la mappa reale, anche quando il vincolo e' disattivo
    if max_per_sector is None:
        sector_of = None  # "nessun vincolo": sector_ok() e' sempre True se sector_of e' vuoto/None
        max_per_sector = 999
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

    stock_rets = {t: p.pct_change() for t, p in stock_prices.items()}
    spy_ret = macro_prices["SPY"].pct_change()
    ief_ret = macro_prices["IEF"].pct_change()
    gld_ret = macro_prices["GLD"].pct_change()
    btc_ret = macro_prices["BTC-USD"].pct_change()

    hysteresis_state = None
    prev_basket_tickers = None
    current_basket = []
    locked_alloc = None
    macro_alloc_history = []
    equity_return_basket = []
    worst_concentration = []

    MIN_HISTORY = 40
    for i, wk in enumerate(weeks):
        if i < MIN_HISTORY:
            macro_alloc_history.append(None)
            equity_return_basket.append(0.0)
            continue

        b_data = {
            V2_CLASS_TICKER["Equities"]: build_ohlc_like(macro_prices["SPY"].loc[:wk]),
            V2_CLASS_TICKER["Bonds"]: build_ohlc_like(macro_prices["IEF"].loc[:wk]),
            V2_CLASS_TICKER["Gold"]: build_ohlc_like(macro_prices["GLD"].loc[:wk]),
            V2_CLASS_TICKER["Crypto"]: build_ohlc_like(macro_prices["BTC-USD"].loc[:wk]),
        }
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
            basket = select_low_vol_basket(
                eq_data, prev_tickers=prev_basket_tickers,
                sector_of=sector_of, max_per_sector=max_per_sector,
            )
            tickers = [b["Ticker"] for b in basket]
            secs = [sector_map_for_measurement.get(t) for t in tickers if sector_map_for_measurement.get(t)]
            conc = (pd.Series(secs).value_counts().iloc[0] / max(len(tickers), 1)) if secs else 0.0
            return tickers, conc

        if not current_basket:
            current_basket, conc = rebuild_basket()
            prev_basket_tickers = set(current_basket)
            worst_concentration.append(conc)
        elif is_month_end and wk.month in (3, 6, 9, 12):
            current_basket, conc = rebuild_basket()
            prev_basket_tickers = set(current_basket)
            worst_concentration.append(conc)

        basket_ret_this_week = float(np.mean([stock_rets[t].loc[wk] for t in current_basket if t in stock_rets])) if current_basket else 0.0
        equity_return_basket.append(basket_ret_this_week)

    valid_from = MIN_HISTORY
    idx = weeks[valid_from:]

    def alloc_frac(cls):
        return pd.Series([macro_alloc_history[i].get(cls, 0.0) / 100.0 for i in range(valid_from, n)], index=idx)

    w_equity, w_bonds, w_gold, w_crypto = alloc_frac("Equities"), alloc_frac("Bonds"), alloc_frac("Gold"), alloc_frac("Crypto")
    weights_df = pd.DataFrame({"Equity": w_equity, "Bonds": w_bonds, "Gold": w_gold, "Crypto": w_crypto})

    returns_df = pd.DataFrame({
        "Equity": pd.Series(equity_return_basket[valid_from:], index=idx),
        "Bonds": ief_ret.reindex(idx).fillna(0.0),
        "Gold": gld_ret.reindex(idx).fillna(0.0),
        "Crypto": btc_ret.reindex(idx).fillna(0.0),
    })
    tax_types = {"Equity": "REDDITO_DIVERSO", "Bonds": "REDDITO_CAPITALE", "Gold": "REDDITO_DIVERSO", "Crypto": "REDDITO_DIVERSO"}

    port_gross = (returns_df * weights_df).sum(axis=1)
    weight_change = weights_df.diff().abs().sum(axis=1).fillna(0.0)
    cost_bps_map = {"Equity": TRANSACTION_COST_BPS["stock"], "Bonds": TRANSACTION_COST_BPS["etf"], "Gold": 0.0010, "Crypto": 0.0010}
    cost_drag = weight_change * np.mean(list(cost_bps_map.values()))
    port_gross_after_costs = port_gross - cost_drag
    port_net = _apply_italian_tax(returns_df, weights_df, tax_types=tax_types)
    port_net_after_costs = port_net - cost_drag

    spy_ret_aligned = spy_ret.reindex(idx).fillna(0.0)
    alpha_full, t_full, p_full = _capm_alpha(port_gross_after_costs, spy_ret_aligned)

    idx_dt = pd.DatetimeIndex(idx)
    recent_mask = idx_dt >= pd.Timestamp("2024-02-01")
    recent_idx = idx_dt[recent_mask]
    if recent_mask.sum() > 20:
        alpha_recent, t_recent, p_recent = _capm_alpha(port_gross_after_costs.loc[recent_idx], spy_ret_aligned.loc[recent_idx])
    else:
        alpha_recent, t_recent, p_recent = float("nan"), float("nan"), float("nan")

    return {
        "cagr_netto": _cagr(port_net_after_costs, PERIODS_PER_YEAR),
        "sharpe_netto": _sharpe(port_net_after_costs, periods_per_year=PERIODS_PER_YEAR),
        "maxdd_netto": _max_drawdown(port_net_after_costs),
        "worst_concentration": max(worst_concentration) if worst_concentration else float("nan"),
        "alpha_full": alpha_full, "t_full": t_full, "p_full": p_full,
        "alpha_recent": alpha_recent, "t_recent": t_recent, "p_recent": p_recent,
    }


def main():
    sector_of = json.load(open(SECTOR_MAP_FILE))
    configs = [("Nessun vincolo", None), ("Max 2/settore (attuale)", 2), ("Max 3/settore", 3), ("Max 4/settore", 4), ("Max 5/settore", 5)]

    print(f"{'Config':<26}{'CAGR netto':>12}{'Sharpe netto':>14}{'MaxDD netto':>13}{'Calmar':>9}{'Conc.max':>10}{'Alpha 12y':>11}{'p (12y)':>10}{'Alpha rec.':>12}{'p (rec.)':>10}")
    for label, mps in configs:
        r = run_backtest(mps, sector_of)
        calmar = r["cagr_netto"] / abs(r["maxdd_netto"]) if r["maxdd_netto"] != 0 else float("nan")
        print(f"{label:<26}{r['cagr_netto']*100:>11.2f}%{r['sharpe_netto']:>14.2f}{r['maxdd_netto']*100:>12.2f}%{calmar:>9.2f}{r['worst_concentration']*100:>9.1f}%{r['alpha_full']*100:>10.2f}%{r['p_full']:>10.4f}{r['alpha_recent']*100:>11.2f}%{r['p_recent']:>10.4f}")


if __name__ == "__main__":
    main()
