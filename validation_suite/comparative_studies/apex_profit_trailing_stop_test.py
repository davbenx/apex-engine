"""
apex_profit_trailing_stop_test.py — Ha senso un trailing stop su BTC e Oro
in Apex V2, attivato SOLO dopo che la posizione è andata un po' in
profitto (non un trailing stop dall'ingresso)? Domanda diretta
dell'utente, mai testata prima in questo progetto — APEX_V2_SPEC.md dice
solo "non esiste uno stop-loss per singola posizione: testato
esplicitamente e respinto" (§8.x, riferito però a uno stop DA ingresso su
azioni, non a un trailing-dal-picco attivato dal profitto su una CLASSE
macro come BTC/Oro — un meccanismo diverso, mai provato).

Meccanismo (nessuna logica duplicata: overlay indipendente sul peso GIÀ
deciso da compute_v2_macro_signal, stesso principio generale di
altcoin_vs_btc_daily_backtest.apply_stop_loss_overlay ma con
un'ATTIVAZIONE ritardata al profitto, non un trailing dall'ingresso):
  1. Quando la classe (BTC o Oro) diventa attiva, si registra il prezzo
     di ingresso (noto PRIMA che il rendimento della settimana si
     realizzi — niente lookahead).
  2. Il peso resta quello deciso dal segnale esistente finché il
     guadagno dall'ingresso non supera `arm_gain` (es. 15%) — lo stop
     resta "disarmato", niente si stacca per la normale volatilità prima
     che si sia formato un vero profitto.
  3. Una volta armato, si traccia il picco di prezzo da quel momento; se
     il prezzo scende oltre `trail_dd` dal picco, il peso della classe
     viene forzato a zero fino alla prossima riattivazione naturale del
     segnale esistente (trend/isteresi/vol-target, invariati).

Stessa griglia walk-forward point-in-time reale (S&P 500 point-in-time,
overlay macro v2, costi/tasse reali) di apex_class_size_grid_test.py.
Validazione: PBO-CSCV sulla griglia, DSR sul migliore, block bootstrap CI.
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
from apex_v2_engine import compute_v2_macro_signal, select_low_vol_basket, V2_CLASS_TICKER, V2_MAX_PER_SECTOR
from metrics import cagr as _cagr, sharpe as _sharpe, max_drawdown as _max_drawdown
from tax_engine import apply_italian_tax as _apply_italian_tax
from statistical_validation import deflated_sharpe_ratio, pbo_cscv, block_bootstrap_ci
from apex_stocks_vs_etf_backtest import (
    DATA_DIR, PERIODS_PER_YEAR, load_weekly_macro, load_weekly_sp500, load_pointintime_snapshots,
    eligible_universe_for_year, build_ohlc_like,
)
from sector_cap_grid_test import SECTOR_MAP_FILE

GRID = [
    ("Nessuno stop (attuale)", None, None),
    ("Arma 10% / trail 10%", 0.10, 0.10),
    ("Arma 15% / trail 10%", 0.15, 0.10),
    ("Arma 15% / trail 15%", 0.15, 0.15),
    ("Arma 20% / trail 15%", 0.20, 0.15),
]


def apply_profit_activated_trailing_stop(weight_series: pd.Series, price_series: pd.Series, arm_gain: float, trail_dd: float) -> pd.Series:
    """Nessun lookahead: la decisione sulla riga i usa solo prezzi noti PRIMA che
    il rendimento della riga i si realizzi — price_series.shift(1), non il prezzo
    della riga i stessa (che rifletterebbe gia' il rendimento che si sta per
    applicare)."""
    known_price = price_series.shift(1)
    out = weight_series.copy()
    n = len(weight_series)
    entry_price, armed, peak, stopped = None, False, None, False

    for i in range(n):
        active = weight_series.iloc[i] > 1e-9
        prev_active = i > 0 and weight_series.iloc[i - 1] > 1e-9
        if active and not prev_active:
            entry_price = known_price.iloc[i]
            armed, peak, stopped = False, None, False

        if not active:
            continue
        if stopped:
            out.iloc[i] = 0.0
            continue
        p = known_price.iloc[i]
        if entry_price is None or pd.isna(entry_price) or pd.isna(p):
            continue

        gain = p / entry_price - 1.0
        if not armed and gain >= arm_gain:
            armed, peak = True, p
        if armed:
            peak = max(peak, p)
            if p / peak - 1.0 < -trail_dd:
                stopped = True
                out.iloc[i] = 0.0

    return out


def run_backtest(arm_gain, trail_dd, sector_of):
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

    valid_from = MIN_HISTORY
    idx = weeks[valid_from:]

    def alloc_frac(cls):
        return pd.Series([macro_alloc_history[i].get(cls, 0.0) / 100.0 for i in range(valid_from, n)], index=idx)

    w_equity, w_bonds, w_gold, w_crypto = alloc_frac("Equities"), alloc_frac("Bonds"), alloc_frac("Gold"), alloc_frac("Crypto")

    if arm_gain is not None:
        gld_price_aligned = macro_prices["GLD"].reindex(idx)
        btc_price_aligned = macro_prices["BTC-USD"].reindex(idx)
        w_gold = apply_profit_activated_trailing_stop(w_gold, gld_price_aligned, arm_gain, trail_dd)
        w_crypto = apply_profit_activated_trailing_stop(w_crypto, btc_price_aligned, arm_gain, trail_dd)

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
    cost_bps_map = {"Equity": 0.0010, "Bonds": 0.0008, "Gold": 0.0010, "Crypto": 0.0010}
    cost_drag = weight_change * np.mean(list(cost_bps_map.values()))
    port_gross_after_costs = port_gross - cost_drag
    port_net = _apply_italian_tax(returns_df, weights_df, tax_types=tax_types)
    port_net_after_costs = port_net - cost_drag

    return {
        "net": port_net_after_costs,
        "cagr_netto": _cagr(port_net_after_costs, PERIODS_PER_YEAR),
        "sharpe_netto": _sharpe(port_net_after_costs, periods_per_year=PERIODS_PER_YEAR),
        "maxdd_netto": _max_drawdown(port_net_after_costs),
        "gold_active_weeks": int((w_gold > 1e-9).sum()),
        "crypto_active_weeks": int((w_crypto > 1e-9).sum()),
    }


def main():
    sector_of = json.load(open(SECTOR_MAP_FILE))

    print(f"{'Config':<26}{'CAGR netto':>12}{'Sharpe netto':>14}{'MaxDD netto':>13}{'Calmar':>9}{'Sett. Oro attive':>18}{'Sett. BTC attive':>18}")
    results = {}
    for label, arm, trail in GRID:
        r = run_backtest(arm, trail, sector_of)
        calmar = r["cagr_netto"] / abs(r["maxdd_netto"]) if r["maxdd_netto"] != 0 else float("nan")
        results[label] = r
        print(f"{label:<26}{r['cagr_netto']*100:>11.2f}%{r['sharpe_netto']:>14.2f}{r['maxdd_netto']*100:>12.2f}%{calmar:>9.2f}"
              f"{r['gold_active_weeks']:>18}{r['crypto_active_weeks']:>18}")

    variant_order = [label for label, _, _ in GRID]
    perf_matrix = np.column_stack([results[m]["net"].values for m in variant_order])
    n_splits = 8
    usable_len = (len(perf_matrix) // n_splits) * n_splits
    pbo = pbo_cscv(perf_matrix[-usable_len:], n_splits=n_splits)
    print(f"\nPBO-CSCV su {len(variant_order)} configurazioni: {pbo*100:.1f}% "
          "(vicino al 50% = nessuna configurazione batte le altre in modo robusto)")

    best_label = max(variant_order, key=lambda m: results[m]["sharpe_netto"])
    best_net = results[best_label]["net"]
    dsr = deflated_sharpe_ratio(results[best_label]["sharpe_netto"], n_trials=len(variant_order), n_obs=len(best_net))
    lo, hi = block_bootstrap_ci(best_net.values, lambda r: _sharpe(pd.Series(r), periods_per_year=PERIODS_PER_YEAR),
                                 block_size=12, ci=0.90, seed=42)
    print(f"\nMigliore per Sharpe netto: {best_label} (Sharpe {results[best_label]['sharpe_netto']:.2f} vs "
          f"{results['Nessuno stop (attuale)']['sharpe_netto']:.2f} dell'attuale)")
    print(f"  DSR (n_trials={len(variant_order)}, conteggio reale): {dsr:.4f}")
    print(f"  CI 90% Sharpe (block bootstrap): [{lo:.2f}, {hi:.2f}]")


if __name__ == "__main__":
    main()
