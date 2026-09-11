"""
apex_production_confirmation_backtest.py — Backtest di CONFERMA dopo
l'implementazione in produzione (apex_v2_engine.py, backend.py) del
passaggio da select_low_vol_basket a select_low_beta_basket (§8.29 di
APEX_V2_SPEC.md). A differenza di tutti gli script precedenti di
validation_suite/, che duplicavano la logica di selezione low-beta per
poterla testare PRIMA che esistesse in produzione, questo importa
DIRETTAMENTE le funzioni reali ora shippate in apex_v2_engine.py — nessuna
duplicazione, e' il codice che gira davvero.

Produce: (1) le statistiche finali CAGR/Sharpe/MaxDD/Calmar per baseline
(low-vol, storico) e produzione (low-beta, ora attivo), (2) i dati serie
per il grafico equity curve + drawdown (salvati come CSV, il grafico vero
e proprio viene pubblicato come artifact separato).
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
from apex_v2_engine import (  # import DIRETTO dal modulo di produzione, nessuna duplicazione
    compute_v2_macro_signal, select_low_vol_basket, select_low_beta_basket,
    V2_MAX_PER_SECTOR, V2_CLASS_TICKER, V2_EQUITY_BETA_LOOKBACK,
)
from metrics import cagr as _cagr, sharpe as _sharpe, max_drawdown as _max_drawdown
from tax_engine import apply_italian_tax as _apply_italian_tax
from statistical_validation import block_bootstrap_ci
from apex_stocks_vs_etf_backtest import (
    DATA_DIR, PERIODS_PER_YEAR, load_weekly_macro, load_weekly_sp500, load_pointintime_snapshots,
    eligible_universe_for_year, build_ohlc_like,
)
from sector_cap_grid_test import SECTOR_MAP_FILE

OUTPUT_DIR = Path(__file__).parent / "production_confirmation_output"


def run_backtest(use_production_selection: bool, sector_of: dict):
    """use_production_selection=True: select_low_beta_basket (produzione, ora reale).
    False: select_low_vol_basket (storico, per confronto)."""
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
            if use_production_selection:
                spy_data_upto = build_ohlc_like(macro_prices["SPY"].loc[:wk])
                basket = select_low_beta_basket(eq_data, spy_data_upto, prev_tickers=prev_basket_tickers, sector_of=sector_of)
            else:
                basket = select_low_vol_basket(eq_data, prev_tickers=prev_basket_tickers, sector_of=sector_of, max_per_sector=V2_MAX_PER_SECTOR)
            return [b["Ticker"] for b in basket]

        # Il rendimento di QUESTA settimana usa il basket cosi' com'era PRIMA di
        # qualunque ribasket deciso questa stessa settimana — corretto per allinearsi
        # ad apex_stocks_vs_etf_backtest.py e apex_dashboard_stat_regeneration.py (era
        # invertito qui: il basket appena ricostruito con beta calcolata fino a QUESTA
        # settimana inclusa ne guadagnava anche il rendimento, una fuga same-bar —
        # concern d'audit #2, vedi README). Il nuovo basket comincia a rendere dalla
        # settimana SUCCESSIVA alla ricostruzione, mai da quella in cui e' deciso.
        basket_ret = float(np.mean([stock_rets[t].loc[wk] for t in current_basket if t in stock_rets])) if current_basket else 0.0
        equity_return_basket.append(basket_ret)

        if not current_basket:
            current_basket = rebuild_basket()
            prev_basket_tickers = set(current_basket)
        elif is_month_end and wk.month in (3, 6, 9, 12):
            current_basket = rebuild_basket()
            prev_basket_tickers = set(current_basket)

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

    return port_net_after_costs


def main():
    sector_of = json.load(open(SECTOR_MAP_FILE))
    OUTPUT_DIR.mkdir(exist_ok=True)

    print(f"[*] Verifica: select_low_beta_basket usa V2_EQUITY_BETA_LOOKBACK = {V2_EQUITY_BETA_LOOKBACK} settimane (produzione)")
    print("[*] Backtest baseline storico (select_low_vol_basket)...")
    net_lowvol = run_backtest(False, sector_of)
    print("[*] Backtest PRODUZIONE ATTUALE (select_low_beta_basket, import diretto da apex_v2_engine.py)...")
    net_lowbeta = run_backtest(True, sector_of)

    common_idx = net_lowvol.index.intersection(net_lowbeta.index)
    net_lowvol, net_lowbeta = net_lowvol.reindex(common_idx), net_lowbeta.reindex(common_idx)

    equity_lowvol = (1 + net_lowvol).cumprod()
    equity_lowbeta = (1 + net_lowbeta).cumprod()
    dd_lowvol = equity_lowvol / equity_lowvol.cummax() - 1.0
    dd_lowbeta = equity_lowbeta / equity_lowbeta.cummax() - 1.0

    out = pd.DataFrame({
        "equity_lowvol": equity_lowvol, "equity_lowbeta": equity_lowbeta,
        "drawdown_lowvol": dd_lowvol, "drawdown_lowbeta": dd_lowbeta,
    })
    out.to_csv(OUTPUT_DIR / "equity_drawdown_series.csv")
    print(f"[*] Serie salvate in {OUTPUT_DIR / 'equity_drawdown_series.csv'}")

    print(f"\n{'Variante':<45}{'CAGR netto':>12}{'Sharpe netto':>14}{'MaxDD netto':>13}{'Calmar':>9}")
    stats = {}
    for label, net in [("Storico (select_low_vol_basket)", net_lowvol),
                        ("PRODUZIONE ATTUALE (select_low_beta_basket)", net_lowbeta)]:
        c, s, dd = _cagr(net, PERIODS_PER_YEAR), _sharpe(net, periods_per_year=PERIODS_PER_YEAR), _max_drawdown(net)
        calmar = c / abs(dd) if dd != 0 else float("nan")
        stats[label] = {"cagr": c, "sharpe": s, "maxdd": dd, "calmar": calmar}
        print(f"{label:<45}{c*100:>11.2f}%{s:>14.2f}{dd*100:>12.2f}%{calmar:>9.2f}")

    diff = (net_lowbeta - net_lowvol).dropna()
    mean_diff = diff.mean() * PERIODS_PER_YEAR * 100
    lo, hi = block_bootstrap_ci(diff.values, lambda r: pd.Series(r).mean() * PERIODS_PER_YEAR * 100,
                                 block_size=12, ci=0.90, seed=42)
    print(f"\nConfronto accoppiato diretto (produzione low-beta meno storico low-vol):")
    print(f"  Overperformance media: {mean_diff:+.2f}pp/anno, CI 90% [{lo:+.2f}, {hi:+.2f}]pp/anno")

    with open(OUTPUT_DIR / "confirmation_stats.json", "w") as f:
        json.dump({
            "stats": stats, "paired_diff_pp_per_year": mean_diff, "paired_ci90": [lo, hi],
            "n_weeks": len(common_idx), "period": [str(common_idx.min().date()), str(common_idx.max().date())],
        }, f, indent=2)
    print(f"[*] Statistiche salvate in {OUTPUT_DIR / 'confirmation_stats.json'}")


if __name__ == "__main__":
    main()
