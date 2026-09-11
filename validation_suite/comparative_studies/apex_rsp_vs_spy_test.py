"""
apex_rsp_vs_spy_test.py — Idea proposta direttamente dall'utente: "usare RSP
al posto di SPY". SPY (S&P 500 cap-weighted) e' oggi usato in DUE punti
distinti e indipendenti:
  1. Segnale di TIMING della classe Equities (MA40w/MA20w, isteresi) —
     compute_v2_macro_signal.
  2. BENCHMARK per il ranking beta nella selezione del basket azionario —
     select_low_beta_basket.
RSP (Invesco S&P 500 Equal Weight) e' un proxy naturale per "il mercato
medio" invece che "il mercato dominato dalle mega-cap" — motivazione
accademica: un indice equal-weight non e' concentrato sulle stesse ~10
mega-cap che pesano ~35% di SPY, quindi sia il segnale di timing sia il
benchmark di beta potrebbero catturare dinamiche diverse.

Le due sostituzioni sono CONCETTUALMENTE INDIPENDENTI (una riguarda QUANDO
investire, l'altra QUALI titoli scegliere quando si investe) — testate
separatamente E insieme per isolare quale, se una, guida un eventuale
risultato (stessa disciplina "isola la variabile" usata in tutta questa
sessione, es. Teoria #5 vs class-weight, satellite vs basket).

4 varianti sullo stesso harness walk-forward point-in-time gia' validato
(apex_production_confirmation_backtest.py):
  A. Baseline produzione (timing=SPY, beta-benchmark=SPY)
  B. Timing=RSP, beta-benchmark=SPY (cambia SOLO quando investire)
  C. Timing=SPY, beta-benchmark=RSP (cambia SOLO quali titoli)
  D. Timing=RSP, beta-benchmark=RSP (cambia entrambi)
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

from apex_v2_engine import compute_v2_macro_signal, select_low_beta_basket, V2_CLASS_TICKER, V2_EQUITY_TOP_N
from metrics import cagr as _cagr, sharpe as _sharpe, max_drawdown as _max_drawdown, calmar as _calmar
from tax_engine import apply_italian_tax as _apply_italian_tax
from statistical_validation import pbo_cscv, block_bootstrap_ci
from apex_stocks_vs_etf_backtest import (
    DATA_DIR, PERIODS_PER_YEAR, load_weekly_macro, load_weekly_sp500, load_pointintime_snapshots,
    eligible_universe_for_year, build_ohlc_like, _fetch_weekly_adj,
)
from sector_cap_grid_test import SECTOR_MAP_FILE

RSP_FILE = DATA_DIR / "RSP_weekly.csv"


def ensure_rsp_data():
    if not RSP_FILE.exists():
        print("[*] Fetch RSP (non in cache)...")
        _fetch_weekly_adj("RSP", "25y").to_csv(RSP_FILE)


def run_variant(timing_ticker: str, beta_benchmark_ticker: str, sector_of: dict, macro_prices: dict):
    """timing_ticker/beta_benchmark_ticker: 'SPY' o 'RSP' — quale serie di
    prezzo alimenta rispettivamente il segnale di trend della classe
    Equities e il benchmark beta in select_low_beta_basket. Il resto
    (Bonds/Gold/Crypto, tasse, costi, basket engine) e' identico alla
    produzione — solo questi due input cambiano."""
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

    common_index = macro_prices["SPY"].index
    for s in macro_prices.values():
        common_index = common_index.intersection(s.index)
    common_index = common_index.intersection(macro_prices["RSP"].index)
    weeks = list(common_index.sort_values())
    n = len(weeks)

    ief_ret = macro_prices["IEF"].pct_change()
    gld_ret = macro_prices["GLD"].pct_change()
    btc_ret = macro_prices["BTC-USD"].pct_change()

    timing_px = macro_prices[timing_ticker]
    beta_px = macro_prices[beta_benchmark_ticker]

    hysteresis_state, prev_basket_tickers, current_basket = None, None, []
    locked_alloc = None
    macro_alloc_history, equity_return_basket = [], []

    MIN_HISTORY = 40
    for i, wk in enumerate(weeks):
        if i < MIN_HISTORY:
            macro_alloc_history.append(None)
            equity_return_basket.append(0.0)
            continue

        b_data = {
            "SPY": build_ohlc_like(timing_px.loc[:wk]),  # chiave "SPY" richiesta da V2_CLASS_TICKER, contenuto = timing_ticker scelto
            "IEF": build_ohlc_like(macro_prices["IEF"].loc[:wk]),
            "GLD": build_ohlc_like(macro_prices["GLD"].loc[:wk]),
            "BTC-USD": build_ohlc_like(macro_prices["BTC-USD"].loc[:wk]),
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
            beta_data_upto = build_ohlc_like(beta_px.loc[:wk])
            basket = select_low_beta_basket(eq_data, beta_data_upto, top_n=V2_EQUITY_TOP_N, prev_tickers=prev_basket_tickers, sector_of=sector_of)
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

        basket_ret = float(np.mean([stock_rets[t].loc[wk] for t in current_basket if t in stock_rets and wk in stock_rets[t].index])) if current_basket else 0.0
        equity_return_basket.append(basket_ret)

    valid_from = MIN_HISTORY
    idx = weeks[valid_from:]

    def alloc_frac(cls):
        return pd.Series([macro_alloc_history[i].get(cls, 0.0) / 100.0 for i in range(valid_from, n)], index=idx)

    weights_df = pd.DataFrame({"Equity": alloc_frac("Equities"), "Bonds": alloc_frac("Bonds"),
                                "Gold": alloc_frac("Gold"), "Crypto": alloc_frac("Crypto")})
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
    return port_net - cost_drag


def main():
    ensure_rsp_data()
    sector_of = json.load(open(SECTOR_MAP_FILE))
    macro_prices = {
        "SPY": load_weekly_macro("SPY"), "IEF": load_weekly_macro("IEF"),
        "GLD": load_weekly_macro("GLD"), "BTC-USD": load_weekly_macro("BTC-USD"),
        "RSP": pd.read_csv(RSP_FILE, index_col=0, parse_dates=True).iloc[:, 0],
    }

    variants = [
        ("A. Baseline (timing=SPY, beta=SPY, produzione)", "SPY", "SPY"),
        ("B. Timing=RSP, beta=SPY", "RSP", "SPY"),
        ("C. Timing=SPY, beta=RSP", "SPY", "RSP"),
        ("D. Timing=RSP, beta=RSP", "RSP", "RSP"),
    ]

    results = {}
    for label, timing_t, beta_t in variants:
        print(f"[*] {label}...")
        results[label] = run_variant(timing_t, beta_t, sector_of, macro_prices)

    common_idx = results[variants[0][0]].index
    for r in results.values():
        common_idx = common_idx.intersection(r.index)
    common_idx = common_idx.sort_values()

    baseline = results[variants[0][0]].reindex(common_idx)
    print(f"\n{'Variante':<38}{'CAGR netto':>12}{'Sharpe netto':>14}{'MaxDD netto':>13}{'vs baseline pp/anno':>22}{'CI90':>22}")
    for label, _, _ in variants:
        net = results[label].reindex(common_idx)
        c, s, dd = _cagr(net, PERIODS_PER_YEAR), _sharpe(net, periods_per_year=PERIODS_PER_YEAR), _max_drawdown(net)
        if label == variants[0][0]:
            print(f"{label:<38}{c*100:>11.2f}%{s:>14.2f}{dd*100:>12.2f}%{'--':>22}{'--':>22}")
        else:
            diff = (net - baseline).dropna()
            mean_diff = diff.mean() * PERIODS_PER_YEAR * 100
            lo, hi = block_bootstrap_ci(diff.values, lambda r: pd.Series(r).mean() * PERIODS_PER_YEAR * 100, block_size=12, ci=0.90, seed=42)
            print(f"{label:<38}{c*100:>11.2f}%{s:>14.2f}{dd*100:>12.2f}%{mean_diff:>+21.2f}   [{lo:+.2f}, {hi:+.2f}]")

    perf_matrix = np.column_stack([results[label].reindex(common_idx).values for label, _, _ in variants])
    n_splits = 8
    usable_len = (len(perf_matrix) // n_splits) * n_splits
    pbo = pbo_cscv(perf_matrix[-usable_len:], n_splits=n_splits)
    print(f"\nPBO-CSCV su {len(variants)} configurazioni (SPY/RSP x timing/beta): {pbo*100:.1f}%")


if __name__ == "__main__":
    main()
