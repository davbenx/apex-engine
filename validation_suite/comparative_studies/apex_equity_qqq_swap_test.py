"""
apex_equity_qqq_swap_test.py — Richiesta diretta dell'utente: sostituire la
gamba Equity di Apex V2 (segnale di trend su SPY + basket di 15 titoli
S&P 500 a bassa volatilita', REDDITO_DIVERSO) con QQQ (Invesco QQQ Trust,
Nasdaq-100) sia come segnale di timing sia come esposizione realizzata
diretta (nessuna selezione di titoli individuali).

Attenzione dichiarata: select_low_vol_basket() NON e' mai stato scelto per
generare alpha (il suo stesso docstring lo dice: "l'audit ha dimostrato che
il momentum non ne ha su questo universo") — e' stato scelto apposta per
ottenere il trattamento fiscale REDDITO_DIVERSO (minusvalenze compensabili)
mantenendo comunque beta azionario liquido. QQQ e' un ETF/UIT — tassato
REDDITO_CAPITALE (come IEF/TIP in questo progetto), minusvalenze NON
compensabili. Il cambio richiesto quindi mescola TRE effetti diversi:
  (1) qualita' del segnale di trend/isteresi (QQQ vs SPY)
  (2) beta sottostante realizzato (Nasdaq-100 concentrato in tech/growth
      contro basket S&P 500 a bassa volatilita', tipicamente Utilities/
      Consumer Staples/Healthcare difensivi)
  (3) trattamento fiscale (REDDITO_CAPITALE non compensabile vs
      REDDITO_DIVERSO compensabile)

Per non confondere questi tre effetti in un numero solo, si testano 3
varianti sulla STESSA finestra:
  A) Baseline attuale: segnale SPY, basket S&P 500 low-vol, REDDITO_DIVERSO
  B) Solo segnale QQQ: segnale QQQ, basket S&P 500 low-vol INVARIATO,
     REDDITO_DIVERSO INVARIATO — isola l'effetto (1)
  C) Pacchetto completo richiesto: segnale QQQ, esposizione diretta su QQQ
     (nessun basket), REDDITO_CAPITALE — isola (2)+(3) rispetto a B, e
     l'effetto totale rispetto ad A

Nessuna riga di apex_v2_engine.py modificata — V2_CLASS_TICKER sovrascritto
a runtime, stessa tecnica di apex_add_commodities_test.py.
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
import apex_v2_engine
from apex_v2_engine import compute_v2_macro_signal, select_low_vol_basket, V2_MAX_PER_SECTOR
from metrics import cagr as _cagr, sharpe as _sharpe, max_drawdown as _max_drawdown
from tax_engine import apply_italian_tax as _apply_italian_tax
from statistical_validation import deflated_sharpe_ratio, pbo_cscv, block_bootstrap_ci
from apex_stocks_vs_etf_backtest import (
    DATA_DIR, PERIODS_PER_YEAR, load_weekly_macro, load_weekly_sp500, load_pointintime_snapshots,
    eligible_universe_for_year, build_ohlc_like, _fetch_weekly_adj,
)
from sector_cap_grid_test import SECTOR_MAP_FILE

BASE_CLASS_TICKER = {"Equities": "SPY", "Bonds": "IEF", "Gold": "GLD", "Crypto": "BTC-USD"}
QQQ_SIGNAL_CLASS_TICKER = {"Equities": "QQQ", "Bonds": "IEF", "Gold": "GLD", "Crypto": "BTC-USD"}


def fetch_qqq() -> None:
    _fetch_weekly_adj("QQQ", "15y").to_csv(DATA_DIR / "QQQ_weekly.csv")


def run_backtest(class_ticker: dict, use_qqq_direct: bool, equity_tax_type: str, sector_of: dict,
                  base_weight: float = 0.50, vol_target: float = 0.22):
    """use_qqq_direct=True: la gamba Equity realizza il rendimento diretto di QQQ
    (nessun basket di stock picking). use_qqq_direct=False: realizza il rendimento
    del basket S&P 500 a bassa volatilita' come in produzione — indipendentemente
    da quale ticker guida il SEGNALE (class_ticker['Equities'])."""
    apex_v2_engine.V2_CLASS_TICKER = class_ticker
    try:
        snapshots = load_pointintime_snapshots()
        with open(DATA_DIR / "sp500_tickers.json") as f:
            all_tickers = json.load(f)

        stock_prices = {}
        if not use_qqq_direct:
            for t in all_tickers:
                try:
                    stock_prices[t] = load_weekly_sp500(t)
                except FileNotFoundError:
                    continue
            stock_rets = {t: p.pct_change() for t, p in stock_prices.items()}

        macro_prices = {ticker: load_weekly_macro(ticker) for ticker in class_ticker.values()}
        common_index = macro_prices["SPY" if "SPY" in class_ticker.values() else "QQQ"].index
        # forza comunque l'intersezione con SPY (per l'universo S&P 500 point-in-time, serve
        # sempre anche se il segnale usa QQQ) cosi' la finestra e' identica in tutte le varianti
        spy_idx = load_weekly_macro("SPY").index
        common_index = common_index.intersection(spy_idx)
        for s in macro_prices.values():
            common_index = common_index.intersection(s.index)
        weeks = list(common_index)
        n = len(weeks)

        ief_ret = macro_prices["IEF"].pct_change()
        gld_ret = macro_prices["GLD"].pct_change()
        btc_ret = macro_prices["BTC-USD"].pct_change()
        equity_direct_ret = macro_prices[class_ticker["Equities"]].pct_change() if use_qqq_direct else None

        hysteresis_state, prev_basket_tickers, current_basket = None, None, []
        locked_alloc = None
        macro_alloc_history, equity_return_basket = [], []

        MIN_HISTORY = 40
        for i, wk in enumerate(weeks):
            if i < MIN_HISTORY:
                macro_alloc_history.append(None)
                equity_return_basket.append(0.0)
                continue

            b_data = {ticker: build_ohlc_like(macro_prices[ticker].loc[:wk]) for ticker in class_ticker.values()}
            alloc, hysteresis_state, _debug = compute_v2_macro_signal(
                b_data, prev_hysteresis_state=hysteresis_state,
                base_weight_per_class=base_weight, vol_target=vol_target,
            )

            is_month_end = (i + 1 >= n) or (weeks[i + 1].month != wk.month)
            if locked_alloc is None:
                locked_alloc = alloc
            macro_alloc_history.append(dict(locked_alloc))
            if is_month_end:
                locked_alloc = alloc

            if not use_qqq_direct:
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

                basket_ret_this_week = float(np.mean([stock_rets[t].loc[wk] for t in current_basket if t in stock_rets])) if current_basket else 0.0
                equity_return_basket.append(basket_ret_this_week)
            else:
                equity_return_basket.append(0.0)  # non usato quando use_qqq_direct=True

        valid_from = MIN_HISTORY
        idx = weeks[valid_from:]

        def alloc_frac(cls):
            return pd.Series([macro_alloc_history[i].get(cls, 0.0) / 100.0 for i in range(valid_from, n)], index=idx)

        weights_df = pd.DataFrame({
            "Equity": alloc_frac("Equities"), "Bonds": alloc_frac("Bonds"),
            "Gold": alloc_frac("Gold"), "Crypto": alloc_frac("Crypto"),
        })
        equity_ret_series = (equity_direct_ret.reindex(idx).fillna(0.0) if use_qqq_direct
                              else pd.Series(equity_return_basket[valid_from:], index=idx))
        returns_df = pd.DataFrame({
            "Equity": equity_ret_series,
            "Bonds": ief_ret.reindex(idx).fillna(0.0),
            "Gold": gld_ret.reindex(idx).fillna(0.0),
            "Crypto": btc_ret.reindex(idx).fillna(0.0),
        })
        tax_types = {"Equity": equity_tax_type, "Bonds": "REDDITO_CAPITALE", "Gold": "REDDITO_DIVERSO", "Crypto": "REDDITO_DIVERSO"}

        weight_change = weights_df.diff().abs().sum(axis=1).fillna(0.0)
        cost_bps_map = {"Equity": 0.0008 if use_qqq_direct else 0.0010, "Bonds": 0.0008, "Gold": 0.0010, "Crypto": 0.0010}
        cost_drag = weight_change * np.mean(list(cost_bps_map.values()))
        port_net = _apply_italian_tax(returns_df, weights_df, tax_types=tax_types)
        port_net_after_costs = port_net - cost_drag

        return {
            "net": port_net_after_costs,
            "cagr_netto": _cagr(port_net_after_costs, PERIODS_PER_YEAR),
            "sharpe_netto": _sharpe(port_net_after_costs, periods_per_year=PERIODS_PER_YEAR),
            "maxdd_netto": _max_drawdown(port_net_after_costs),
        }
    finally:
        apex_v2_engine.V2_CLASS_TICKER = BASE_CLASS_TICKER


def main():
    if not (DATA_DIR / "QQQ_weekly.csv").exists():
        print("[*] Scarico QQQ da Yahoo Finance...")
        fetch_qqq()

    sector_of = json.load(open(SECTOR_MAP_FILE))

    spy = load_weekly_macro("SPY")
    qqq = load_weekly_macro("QQQ")
    common = spy.index.intersection(qqq.index)
    corr = spy.reindex(common).pct_change().corr(qqq.reindex(common).pct_change())
    print(f"Correlazione settimanale SPY-QQQ ({len(common)} settimane): {corr:.3f}\n")

    variants = [
        ("A) Baseline: segnale SPY + basket S&P500 low-vol (REDDITO_DIVERSO)", BASE_CLASS_TICKER, False, "REDDITO_DIVERSO"),
        ("B) Solo segnale QQQ, basket S&P500 low-vol invariato (REDDITO_DIVERSO)", QQQ_SIGNAL_CLASS_TICKER, False, "REDDITO_DIVERSO"),
        ("C) Pacchetto completo: segnale QQQ + esposizione diretta QQQ (REDDITO_CAPITALE)", QQQ_SIGNAL_CLASS_TICKER, True, "REDDITO_CAPITALE"),
    ]

    print(f"{'Variante':<70}{'CAGR netto':>12}{'Sharpe netto':>14}{'MaxDD netto':>13}{'Calmar':>9}")
    results = {}
    for label, class_ticker, use_direct, tax_type in variants:
        r = run_backtest(class_ticker, use_direct, tax_type, sector_of)
        calmar = r["cagr_netto"] / abs(r["maxdd_netto"]) if r["maxdd_netto"] != 0 else float("nan")
        results[label] = r
        print(f"{label:<70}{r['cagr_netto']*100:>11.2f}%{r['sharpe_netto']:>14.2f}{r['maxdd_netto']*100:>12.2f}%{calmar:>9.2f}")

    labels = [v[0] for v in variants]
    common_idx = results[labels[0]]["net"].index
    for l in labels[1:]:
        common_idx = common_idx.intersection(results[l]["net"].index)
    perf_matrix = np.column_stack([results[l]["net"].reindex(common_idx).values for l in labels])
    n_splits = 8
    usable_len = (len(perf_matrix) // n_splits) * n_splits
    pbo = pbo_cscv(perf_matrix[-usable_len:], n_splits=n_splits)
    print(f"\nPBO-CSCV su {len(labels)} varianti (A/B/C): {pbo*100:.1f}%")

    def paired(label_a, label_b, tag):
        diff = (results[label_b]["net"] - results[label_a]["net"]).dropna()
        mean_diff = diff.mean() * PERIODS_PER_YEAR * 100
        lo, hi = block_bootstrap_ci(diff.values, lambda r: pd.Series(r).mean() * PERIODS_PER_YEAR * 100,
                                     block_size=12, ci=0.90, seed=42)
        n_better = int((diff > 0).sum())
        print(f"\n{tag}:")
        print(f"  Overperformance media: {mean_diff:+.2f}pp/anno, CI 90% [{lo:+.2f}, {hi:+.2f}]pp/anno "
              f"({'ESCLUDE' if lo * hi > 0 else 'INCLUDE'} lo zero), vince {n_better}/{len(diff)} settimane "
              f"({n_better/len(diff)*100:.0f}%)")

    paired(labels[0], labels[1], "A -> B: effetto ISOLATO del solo cambio segnale (SPY->QQQ)")
    paired(labels[1], labels[2], "B -> C: effetto ISOLATO del cambio beta+basket+tasse (basket->QQQ diretto, REDDITO_CAPITALE)")
    paired(labels[0], labels[2], "A -> C: effetto TOTALE del pacchetto completo richiesto")


if __name__ == "__main__":
    main()
