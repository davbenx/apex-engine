"""
apex_yield_curve_regime_filter_test.py — Idea #6 della lista di
approfondimento: un filtro di regime INDIPENDENTE dal prezzo, a differenza
di tutto il segnale Apex attuale (sempre derivato da MA/volatilita' del
prezzo stesso). La curva dei rendimenti invertita (10Y sotto il 3M) e' tra
i predittori di recessione piu' robusti in letteratura (Estrella-Mishkin
1996 e successivi — la spread 10Y-3M usata dalla NY Fed stessa).

Design: filtro ADDITIVO (AND), non sostitutivo, solo sulla classe Equities
(la curva invertita e' specificamente un segnale di ciclo azionario/
recessione, non direttamente rilevante per Bonds/Gold/Crypto): Equities
resta attiva SOLO se il trend di prezzo lo conferma (invariato) E la curva
non e' invertita in quel momento (spread 10Y-3M >= 0, ^TNX - ^IRX,
contemporaneo — nessun parametro di lag introdotto apposta, per non
aggiungere un'altra dimensione da ottimizzare).

Solo 2 varianti (nessuna griglia da selezionare in walk-forward — e' una
scelta di design binaria, non un parametro continuo): baseline (attuale)
vs filtrato. Confronto diretto con PBO-CSCV e bootstrap CI sulla
differenza accoppiata, stessa metodologia statistica di tutta la sessione.

Nota onesta dichiarata in anticipo: la curva invertita predice la
recessione con un RITARDO tipico di 6-18 mesi (spesso le azioni salgono
ancora per un po' dopo l'inversione, il classico "ultimo rally") — un
filtro contemporaneo potrebbe quindi disattivare Equities troppo presto
rispetto al vero punto di svolta, un costo di opportunity reale anche se
il filtro "funzionasse" nel prevedere la direzione di fondo.
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


def compute_macro_signal_yc_filter(b_data, prev_hysteresis_state, curve_inverted: bool, use_filter: bool, vol_target=V2_VOL_TARGET):
    """Copia di compute_v2_macro_signal con un solo AND aggiuntivo su
    Equities: se use_filter e curve_inverted, Equities forzata a 0%
    indipendentemente dal trend di prezzo (che resta comunque tracciato in
    state, cosi' l'isteresi non si disallinea quando il filtro si toglie)."""
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

        if cls == "Equities" and use_filter and curve_inverted:
            is_active = False  # filtro di regime: override, ma lo stato di isteresi (trend_long_on) resta tracciato sopra

        base_weight[cls] = BASE_WEIGHT_PER_CLASS if is_active else 0.0

    port_vol = sum(base_weight.get(cls, 0.0) * vols[cls] for cls in V2_CLASS_TICKER if cls in vols)
    scale = min(1.0, vol_target / port_vol) if port_vol > 1e-6 else 1.0
    raw_weights = {cls: base_weight.get(cls, 0.0) * scale for cls in V2_CLASS_TICKER}
    total_raw = sum(raw_weights.values())
    if total_raw > 1.0:
        raw_weights = {cls: w / total_raw for cls, w in raw_weights.items()}
    allocations = {cls: round(raw_weights.get(cls, 0.0) * 100.0, 2) for cls in V2_CLASS_TICKER}
    return allocations, state


def run_variant(use_filter: bool, sector_of: dict, yc_spread: pd.Series):
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

    MIN_HISTORY = 40
    for i, wk in enumerate(weeks):
        if i < MIN_HISTORY:
            macro_alloc_history.append(None)
            equity_return_basket.append(0.0)
            continue

        b_data = {V2_CLASS_TICKER[c]: build_ohlc_like(macro_prices[V2_CLASS_TICKER[c]].loc[:wk]) for c in V2_CLASS_TICKER}
        inverted = bool(yc_spread.loc[wk] < 0)
        alloc, hysteresis_state = compute_macro_signal_yc_filter(b_data, hysteresis_state, inverted, use_filter)
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
    return port_net - cost_drag, (yc_spread.reindex(idx) < 0)


def main():
    ensure_yield_data()
    sector_of = json.load(open(SECTOR_MAP_FILE))
    tnx = load_weekly_macro("^TNX")
    irx = load_weekly_macro("^IRX")
    common = tnx.index.intersection(irx.index)
    yc_spread = (tnx.reindex(common) - irx.reindex(common)).dropna()
    n_inverted_weeks = int((yc_spread < 0).sum())
    print(f"[*] Curva 10Y-3M: {len(yc_spread)} settimane, {n_inverted_weeks} invertite "
          f"({n_inverted_weeks/len(yc_spread)*100:.1f}%), {yc_spread.index.min().date()} -> {yc_spread.index.max().date()}")

    print("[*] Baseline (nessun filtro)...")
    net_baseline, inv_flag = run_variant(False, sector_of, yc_spread)
    print("[*] Filtrato (curva invertita -> Equities forzata a 0%)...")
    net_filtered, _ = run_variant(True, sector_of, yc_spread)

    common_idx = net_baseline.index.intersection(net_filtered.index)
    common_idx = common_idx.sort_values()
    base, filt = net_baseline.reindex(common_idx), net_filtered.reindex(common_idx)

    print(f"\n{'Variante':<30}{'CAGR netto':>12}{'Sharpe netto':>14}{'MaxDD netto':>13}")
    for label, net in [("Baseline (attuale)", base), ("Filtrato (curva 10Y-3M)", filt)]:
        c, s, dd = _cagr(net, PERIODS_PER_YEAR), _sharpe(net, periods_per_year=PERIODS_PER_YEAR), _max_drawdown(net)
        print(f"{label:<30}{c*100:>11.2f}%{s:>14.2f}{dd*100:>12.2f}%")

    diff = (filt - base).dropna()
    mean_diff = diff.mean() * PERIODS_PER_YEAR * 100
    lo, hi = block_bootstrap_ci(diff.values, lambda r: pd.Series(r).mean() * PERIODS_PER_YEAR * 100, block_size=12, ci=0.90, seed=42)
    n_better = int((diff > 0).sum())
    print(f"\nConfronto accoppiato diretto (filtrato meno baseline):")
    print(f"  Overperformance media: {mean_diff:+.2f}pp/anno, CI 90% [{lo:+.2f}, {hi:+.2f}]pp/anno "
          f"({'ESCLUDE' if lo * hi > 0 else 'include'} lo zero)")
    print(f"  Settimane in cui ha fatto meglio: {n_better}/{len(diff)} ({n_better/len(diff)*100:.0f}%)")

    perf_matrix = np.column_stack([base.values, filt.values])
    n_splits = 8
    usable_len = (len(perf_matrix) // n_splits) * n_splits
    pbo = pbo_cscv(perf_matrix[-usable_len:], n_splits=n_splits)
    print(f"\nPBO-CSCV su 2 configurazioni (baseline/filtrato): {pbo*100:.1f}%")


if __name__ == "__main__":
    main()
