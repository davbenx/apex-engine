"""
apex_yield_curve_lagged_filter_test.py — Approfondimento richiesto
dall'utente del test precedente (apex_yield_curve_regime_filter_test.py,
risultato sfumato: filtro CONTEMPORANEO sulla curva 10Y-3M peggiorava
leggermente Sharpe/MaxDD, coerente col rischio dichiarato in anticipo —
la curva invertita predice la recessione con un ritardo tipico di 6-18
mesi, quindi un filtro contemporaneo taglia l'esposizione troppo presto).

Qui si introduce esplicitamente quel ritardo: Equities forzata a 0% se la
curva ERA invertita `lag_weeks` settimane fa (non ora), invece di reagire
all'inversione nell'istante in cui accade. Griglia [0 (= test precedente,
contemporaneo), 26 (~6 mesi), 52 (~12 mesi)] — il range tipico di ritardo
recessione-dopo-inversione citato in letteratura (Estrella-Mishkin).

Walk-forward onesto: 3 ere, lag_weeks scelto per ogni era SOLO con lo
Sharpe delle ere precedenti — stessa disciplina di skip-month (il segnale
di trend stesso cambia con lag_weeks, non solo il peso a valle: non si
puo' riusare una singola passata precalcolata, serve un giro completo per
candidato, griglia tenuta a 3 valori apposta per questo).
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

from apex_v2_engine import (
    select_low_beta_basket, V2_CLASS_TICKER, V2_MA_WEEKS, V2_SHORT_MA_WEEKS,
    V2_HYSTERESIS_K, V2_HYSTERESIS_MIN, V2_HYSTERESIS_MAX, V2_VOL_WINDOW, V2_VOL_TARGET,
)
from metrics import cagr as _cagr, sharpe as _sharpe, max_drawdown as _max_drawdown
from tax_engine import apply_italian_tax as _apply_italian_tax
from statistical_validation import pbo_cscv, block_bootstrap_ci
from apex_stocks_vs_etf_backtest import (
    DATA_DIR, PERIODS_PER_YEAR, load_weekly_macro, load_weekly_sp500, load_pointintime_snapshots,
    eligible_universe_for_year, build_ohlc_like, _fetch_weekly_adj,
)
from sector_cap_grid_test import SECTOR_MAP_FILE

BASE_WEIGHT_PER_CLASS = 0.50
LAG_WEEKS_GRID = [0, 26, 52]  # 0 = contemporaneo (test precedente), ~6 mesi, ~12 mesi
N_ERAS = 3


def _weekly_close(df):
    if df is None or df.empty:
        return pd.Series(dtype=float)
    return df["Close"].resample("W-FRI").last().dropna()


def _realized_vol(weekly_close, window):
    if len(weekly_close) < window + 1:
        return None
    r = weekly_close.pct_change().dropna().iloc[-window:]
    v = float(r.std() * np.sqrt(52))
    return v if v > 1e-6 else None


def ensure_yield_data():
    for t in ["^TNX", "^IRX"]:
        f = DATA_DIR / f"{t}_weekly.csv"
        if not f.exists():
            print(f"[*] Fetch {t}...")
            _fetch_weekly_adj(t, "20y").to_csv(f)


def compute_macro_signal_yc_filter(b_data, prev_hysteresis_state, curve_inverted: bool, vol_target=V2_VOL_TARGET):
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

        if cls == "Equities" and curve_inverted:
            is_active = False

        base_weight[cls] = BASE_WEIGHT_PER_CLASS if is_active else 0.0

    port_vol = sum(base_weight.get(cls, 0.0) * vols[cls] for cls in V2_CLASS_TICKER if cls in vols)
    scale = min(1.0, vol_target / port_vol) if port_vol > 1e-6 else 1.0
    raw_weights = {cls: base_weight.get(cls, 0.0) * scale for cls in V2_CLASS_TICKER}
    total_raw = sum(raw_weights.values())
    if total_raw > 1.0:
        raw_weights = {cls: w / total_raw for cls, w in raw_weights.items()}
    allocations = {cls: round(raw_weights.get(cls, 0.0) * 100.0, 2) for cls in V2_CLASS_TICKER}
    return allocations, state


def run_variant(lag_weeks: int, sector_of: dict, yc_spread: pd.Series):
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
    common_index = common_index.intersection(yc_spread.index)
    weeks = list(common_index.sort_values())
    n = len(weeks)

    ief_ret = macro_prices["IEF"].pct_change()
    gld_ret = macro_prices["GLD"].pct_change()
    btc_ret = macro_prices["BTC-USD"].pct_change()

    hysteresis_state, prev_basket_tickers, current_basket = None, None, []
    locked_alloc = None
    macro_alloc_history, equity_return_basket = [], []

    MIN_HISTORY = 40 + max(LAG_WEEKS_GRID)
    for i, wk in enumerate(weeks):
        if i < MIN_HISTORY:
            macro_alloc_history.append(None)
            equity_return_basket.append(0.0)
            continue

        b_data = {V2_CLASS_TICKER[c]: build_ohlc_like(macro_prices[V2_CLASS_TICKER[c]].loc[:wk]) for c in V2_CLASS_TICKER}
        lagged_wk = weeks[i - lag_weeks]
        inverted = bool(yc_spread.loc[lagged_wk] < 0)
        alloc, hysteresis_state = compute_macro_signal_yc_filter(b_data, hysteresis_state, inverted)
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
            basket = select_low_beta_basket(eq_data, spy_data_upto, prev_tickers=prev_basket_tickers, sector_of=sector_of)
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

        basket_ret = float(np.mean([stock_rets[t].loc[wk] for t in current_basket if t in stock_rets])) if current_basket else 0.0
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
    ensure_yield_data()
    sector_of = json.load(open(SECTOR_MAP_FILE))
    tnx = load_weekly_macro("^TNX")
    irx = load_weekly_macro("^IRX")
    common = tnx.index.intersection(irx.index)
    yc_spread = (tnx.reindex(common) - irx.reindex(common)).dropna()

    net_by_lag = {}
    for lag in LAG_WEEKS_GRID:
        print(f"[*] lag_weeks={lag}...")
        net_by_lag[lag] = run_variant(lag, sector_of, yc_spread)
        c, s, dd = _cagr(net_by_lag[lag], PERIODS_PER_YEAR), _sharpe(net_by_lag[lag], periods_per_year=PERIODS_PER_YEAR), _max_drawdown(net_by_lag[lag])
        print(f"  CAGR {c*100:6.2f}%  Sharpe {s:5.2f}  MaxDD {dd*100:7.2f}%")

    common_idx = net_by_lag[LAG_WEEKS_GRID[0]].index
    for net in net_by_lag.values():
        common_idx = common_idx.intersection(net.index)
    common_idx = common_idx.sort_values()
    era_len = len(common_idx) // N_ERAS
    eras = [common_idx[i * era_len:(i + 1) * era_len] for i in range(N_ERAS - 1)]
    eras.append(common_idx[(N_ERAS - 1) * era_len:])
    print(f"\nEre: {[(e.min().date(), e.max().date(), len(e)) for e in eras]}")

    baseline = net_by_lag[0].reindex(common_idx)  # 0 = nessun filtro attivo con lag>len(storia): qui baseline e' lag=0 (contemporaneo, gia' testato) per confronto interno alla griglia

    print(f"\n{'Era':<8}{'lag_weeks selezionato':>22}{'Sharpe selezione':>18}")
    wf_segments = []
    for i in range(1, N_ERAS):
        past_idx = common_idx[:i * era_len]
        sharpes_past = {lg: _sharpe(net_by_lag[lg].reindex(past_idx).dropna(), periods_per_year=PERIODS_PER_YEAR)
                         for lg in LAG_WEEKS_GRID}
        best_lg = max(sharpes_past, key=sharpes_past.get)
        print(f"Era {i+1:<5}{best_lg:>22}{sharpes_past[best_lg]:>18.2f}")
        wf_segments.append(net_by_lag[best_lg].reindex(eras[i]).dropna())

    wf_net = pd.concat(wf_segments).sort_index()
    baseline_oos = baseline.reindex(wf_net.index)

    print(f"\n--- OUT-OF-SAMPLE (ere 2+3, {len(wf_net)} settimane) ---")
    for label, net in [("Baseline (lag=0, filtro contemporaneo)", baseline_oos), ("Walk-forward (lag ottimale per era)", wf_net)]:
        c, s, dd = _cagr(net, PERIODS_PER_YEAR), _sharpe(net, periods_per_year=PERIODS_PER_YEAR), _max_drawdown(net)
        print(f"  {label:<40}CAGR {c*100:>8.2f}%   Sharpe {s:>5.2f}   MaxDD {dd*100:>7.2f}%")

    diff = (wf_net - baseline_oos).dropna()
    mean_diff = diff.mean() * PERIODS_PER_YEAR * 100
    lo, hi = block_bootstrap_ci(diff.values, lambda r: pd.Series(r).mean() * PERIODS_PER_YEAR * 100, block_size=12, ci=0.90, seed=42)
    n_better = int((diff > 0).sum())
    print(f"\nConfronto accoppiato diretto (walk-forward meno baseline lag=0, solo OOS):")
    print(f"  Overperformance media: {mean_diff:+.2f}pp/anno, CI 90% [{lo:+.2f}, {hi:+.2f}]pp/anno "
          f"({'ESCLUDE' if lo * hi > 0 else 'include'} lo zero)")
    print(f"  Settimane in cui ha fatto meglio: {n_better}/{len(diff)} ({n_better/len(diff)*100:.0f}%)")

    perf_matrix = np.column_stack([net_by_lag[lg].reindex(common_idx).values for lg in LAG_WEEKS_GRID])
    n_splits = 8
    usable_len = (len(perf_matrix) // n_splits) * n_splits
    pbo = pbo_cscv(perf_matrix[-usable_len:], n_splits=n_splits)
    print(f"\nPBO-CSCV full-sample su {len(LAG_WEEKS_GRID)} valori lag_weeks (contesto, non walk-forward): {pbo*100:.1f}%")
    print("\n[*] Nota: baseline qui e' lag=0 (filtro contemporaneo, gia' testato in "
          "apex_yield_curve_regime_filter_test.py: CAGR 19.17%/Sharpe 1.22/MaxDD -19.29% contro "
          "CAGR 18.98%/Sharpe 1.25/MaxDD -18.49% di NESSUN filtro/produzione reale — vedi README per il confronto completo).")


if __name__ == "__main__":
    main()
