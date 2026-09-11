"""
apex_bond_value_signal_test.py — Teoria accademica #4 da sondare: value
cross-asset (Asness-Moskowitz-Pedersen 2013, "Value and Momentum
Everywhere" — value e momentum sono storicamente segnali complementari/
decorrelati). Apex V2 oggi usa SOLO trend/momentum, mai una componente di
valutazione.

Limite di dati dichiarato: un test rigoroso per l'Equity richiederebbe
CAPE/P-E storico, non disponibile in modo pulito e affidabile da Yahoo
Finance (solo prezzo, non fondamentali storici, senza affidarsi a scraping
di fonti esterne meno controllabili). Questo script testa quindi SOLO la
gamba Bonds, dove un proxy di value reale ed ELEGANTE esiste gia' nei dati
disponibili: il rendimento del Treasury 10Y (^TNX, ticker reale Yahoo).
Rendimento alto rispetto alla propria distribuzione storica trailing =
bond "a sconto" (prezzo basso, valore alto) = allocazione maggiore;
rendimento basso = bond costoso = allocazione minore. Equity/Gold/Crypto
restano sul segnale di trend esistente, invariato.

Costruzione: stessa identica logica di ingresso/uscita (isteresi + conferma
multi-timeframe) della produzione per TUTTE le classi — l'UNICA differenza
e' che il peso di Bonds, una volta attivo, e' scalato da dove il rendimento
10Y attuale si trova nel proprio percentile trailing a 3 anni (156
settimane): moltiplicatore 0.5x al percentile piu' basso (rendimento basso,
bond costoso) fino a 1.5x al percentile piu' alto (rendimento alto, bond a
sconto), 1.0x al percentile mediano (neutro, comportamento invariato).

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
from statistical_validation import deflated_sharpe_ratio, block_bootstrap_ci
from apex_stocks_vs_etf_backtest import (
    DATA_DIR, PERIODS_PER_YEAR, load_weekly_macro, load_weekly_sp500, load_pointintime_snapshots,
    eligible_universe_for_year, build_ohlc_like, _fetch_weekly_adj,
)
from sector_cap_grid_test import SECTOR_MAP_FILE

YIELD_LOOKBACK_WEEKS = 156  # 3 anni, finestra trailing per il percentile del rendimento 10Y


def fetch_tnx() -> None:
    _fetch_weekly_adj("^TNX", "15y").to_csv(DATA_DIR / "^TNX_weekly.csv")


def compute_signal_bond_value(
    b_data: Dict[str, pd.DataFrame],
    yield_percentile: Optional[float],
    prev_hysteresis_state: Optional[Dict[str, bool]] = None,
    base_weight_per_class: float = 0.50,
    vol_target: float = V2_VOL_TARGET,
) -> Tuple[Dict[str, float], Dict[str, bool], Dict[str, dict]]:
    """Identica a compute_v2_macro_signal — l'UNICA differenza e' che il peso di
    Bonds, se attivo, e' scalato da 0.5x (rendimento al percentile piu' basso
    della propria storia trailing, bond costoso) a 1.5x (percentile piu' alto,
    bond a sconto). yield_percentile in [0,1] o None se dati insufficienti."""
    state = dict(prev_hysteresis_state) if prev_hysteresis_state else {}
    base_weight = {}
    debug = {}
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
            debug[cls] = {"note": "dati insufficienti"}
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

        value_mult = 1.0
        if cls == "Bonds" and is_active and yield_percentile is not None:
            value_mult = float(0.5 + yield_percentile * 1.0)  # 0.5x..1.5x

        base_weight[cls] = base_weight_per_class * value_mult if is_active else 0.0
        debug[cls] = {"distanza_pct": round(dist * 100, 2), "attivo": is_active, "value_mult": round(value_mult, 2)}

    port_vol = sum(base_weight.get(cls, 0.0) * vols[cls] for cls in V2_CLASS_TICKER if cls in vols)
    scale = min(1.0, vol_target / port_vol) if port_vol > 1e-6 else 1.0
    raw_weights = {cls: base_weight.get(cls, 0.0) * scale for cls in V2_CLASS_TICKER}
    total_raw = sum(raw_weights.values())
    if total_raw > 1.0:
        raw_weights = {cls: w / total_raw for cls, w in raw_weights.items()}

    allocations = {cls: round(raw_weights.get(cls, 0.0) * 100.0, 2) for cls in V2_CLASS_TICKER}
    return allocations, state, debug


def run_backtest(use_value_tilt: bool, sector_of: dict, base_weight: float = 0.50, vol_target: float = 0.22):
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
    tnx = load_weekly_macro("^TNX") if use_value_tilt else None
    common_index = macro_prices["SPY"].index
    for s in macro_prices.values():
        common_index = common_index.intersection(s.index)
    if use_value_tilt:
        common_index = common_index.intersection(tnx.index)
    weeks = list(common_index)
    n = len(weeks)

    ief_ret = macro_prices["IEF"].pct_change()
    gld_ret = macro_prices["GLD"].pct_change()
    btc_ret = macro_prices["BTC-USD"].pct_change()

    hysteresis_state, prev_basket_tickers, current_basket = None, None, []
    locked_alloc = None
    macro_alloc_history, equity_return_basket = [], []

    MIN_HISTORY = max(40, YIELD_LOOKBACK_WEEKS if use_value_tilt else 0)
    for i, wk in enumerate(weeks):
        if i < MIN_HISTORY:
            macro_alloc_history.append(None)
            equity_return_basket.append(0.0)
            continue

        yield_pctl = None
        if use_value_tilt:
            trailing_yield = tnx.loc[:wk].iloc[-YIELD_LOOKBACK_WEEKS:]
            current_yield = float(trailing_yield.iloc[-1])
            yield_pctl = float((trailing_yield < current_yield).mean())

        b_data = {V2_CLASS_TICKER[c]: build_ohlc_like(macro_prices[V2_CLASS_TICKER[c]].loc[:wk]) for c in V2_CLASS_TICKER}
        alloc, hysteresis_state, _debug = compute_signal_bond_value(
            b_data, yield_pctl, prev_hysteresis_state=hysteresis_state,
            base_weight_per_class=base_weight, vol_target=vol_target,
        )
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

    return {
        "net": port_net_after_costs,
        "cagr_netto": _cagr(port_net_after_costs, PERIODS_PER_YEAR),
        "sharpe_netto": _sharpe(port_net_after_costs, periods_per_year=PERIODS_PER_YEAR),
        "maxdd_netto": _max_drawdown(port_net_after_costs),
        "weights_df": weights_df,
    }


def main():
    if not (DATA_DIR / "TNX_weekly.csv").exists():
        print("[*] Scarico ^TNX (rendimento Treasury 10Y) da Yahoo Finance...")
        fetch_tnx()

    sector_of = json.load(open(SECTOR_MAP_FILE))

    print(f"{'Variante':<45}{'CAGR netto':>12}{'Sharpe netto':>14}{'MaxDD netto':>13}{'Calmar':>9}")
    baseline = run_backtest(False, sector_of)
    calmar_b = baseline["cagr_netto"] / abs(baseline["maxdd_netto"])
    print(f"{'Baseline: Bonds peso fisso (produzione)':<45}{baseline['cagr_netto']*100:>11.2f}%{baseline['sharpe_netto']:>14.2f}"
          f"{baseline['maxdd_netto']*100:>12.2f}%{calmar_b:>9.2f}")

    candidate = run_backtest(True, sector_of)
    calmar_c = candidate["cagr_netto"] / abs(candidate["maxdd_netto"])
    print(f"{'Bonds value-tilted (percentile rendim. 10Y)':<45}{candidate['cagr_netto']*100:>11.2f}%{candidate['sharpe_netto']:>14.2f}"
          f"{candidate['maxdd_netto']*100:>12.2f}%{calmar_c:>9.2f}")

    wb_base = baseline["weights_df"]["Bonds"]
    wb_cand = candidate["weights_df"]["Bonds"]
    common_idx = wb_base.index.intersection(wb_cand.index)
    print(f"\nEsposizione media Bonds quando attiva: baseline {wb_base[wb_base>1e-9].mean()*100:.1f}%  "
          f"value-tilted {wb_cand[wb_cand>1e-9].mean()*100:.1f}%")

    diff = (candidate["net"].reindex(common_idx) - baseline["net"].reindex(common_idx)).dropna()
    mean_diff = diff.mean() * PERIODS_PER_YEAR * 100
    lo, hi = block_bootstrap_ci(diff.values, lambda r: pd.Series(r).mean() * PERIODS_PER_YEAR * 100,
                                 block_size=12, ci=0.90, seed=42)
    n_better = int((diff > 0).sum())
    print(f"\nConfronto accoppiato diretto (value-tilted meno baseline, stessa finestra {len(diff)} settimane):")
    print(f"  Overperformance media: {mean_diff:+.2f}pp/anno, CI 90% [{lo:+.2f}, {hi:+.2f}]pp/anno "
          f"({'ESCLUDE' if lo * hi > 0 else 'INCLUDE'} lo zero)")
    print(f"  Settimane in cui il value-tilt ha fatto meglio: {n_better}/{len(diff)} ({n_better/len(diff)*100:.0f}%)")

    dsr = deflated_sharpe_ratio(candidate["sharpe_netto"], n_trials=2, n_obs=len(candidate["net"]))
    print(f"  DSR value-tilt (n_trials=2): {dsr:.4f}")


if __name__ == "__main__":
    main()
