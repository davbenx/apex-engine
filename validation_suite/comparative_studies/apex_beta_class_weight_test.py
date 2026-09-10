"""
apex_beta_class_weight_test.py — Il criterio low-beta (Teoria #5) e' stato
validato per SELEZIONARE i titoli nel basket Equity. La domanda naturale
successiva dell'utente ("low beta si puo' testare anche sulle asset
class?"): pesare le 4 classi macro (Equity/Bonds/Gold/Crypto) per il
BETA rispetto all'equity (SPY, l'asset "di mercato" nel paniere) invece
che per la volatilita' assoluta, quando piu' di una e' attiva.

Distinzione importante dalla Teoria #3 (risk parity per volatilita', gia'
FALSIFICATA in modo netto — CI 90% [-12.00,-2.50]pp/anno): quel test
penalizzava Crypto per la sua volatilita' ASSOLUTA alta, indipendentemente
dal fatto che la sua CORRELAZIONE con l'equity sia bassa (0.09-0.17 nelle
misure di questa sessione) — un asset puo' essere molto volatile ma poco
"di mercato" (beta basso) se si muove in modo largamente indipendente da
SPY. Pesare per beta invece che per volatilita' assoluta potrebbe non
penalizzare Crypto allo stesso modo, correggendo il meccanismo di
fallimento identificato nella Teoria #3.

Costruzione: stessa identica logica di ingresso/uscita (isteresi +
conferma multi-timeframe) della produzione — cambia SOLO come si
distribuisce il peso nozionale TRA le classi attive: inversamente
proporzionale al beta ASSOLUTO rispetto a SPY (floor a 0.10 per evitare
esplosioni quando il beta e' vicino a zero, come tipicamente per Bonds),
mantenendo la stessa esposizione lorda totale pre-vol-target del
baseline (n_attive x base_weight_per_class). Equity stessa ha beta=1 per
definizione (e' il riferimento).

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
    eligible_universe_for_year, build_ohlc_like,
)
from sector_cap_grid_test import SECTOR_MAP_FILE

BETA_FLOOR = 0.10
BETA_WINDOW = V2_VOL_WINDOW  # 12 settimane, stessa finestra usata per la volatilita' in produzione


def compute_signal_beta_weighted(
    b_data: Dict[str, pd.DataFrame],
    prev_hysteresis_state: Optional[Dict[str, bool]] = None,
    base_weight_per_class: float = 0.50,
    vol_target: float = V2_VOL_TARGET,
) -> Tuple[Dict[str, float], Dict[str, bool], Dict[str, dict]]:
    state = dict(prev_hysteresis_state) if prev_hysteresis_state else {}
    is_active_map, vols, betas = {}, {}, {}

    spy_wc = _weekly_close(b_data.get("SPY"))
    spy_ret = spy_wc.pct_change().dropna()

    for cls, ticker in V2_CLASS_TICKER.items():
        wc = _weekly_close(b_data.get(ticker))
        v = _realized_vol(wc, V2_VOL_WINDOW)
        if v is not None:
            vols[cls] = v
        if cls == "Equities":
            betas[cls] = 1.0
            continue
        ret = wc.pct_change().dropna()
        common = ret.index.intersection(spy_ret.index)
        if len(common) >= BETA_WINDOW + 1:
            r = ret.reindex(common).iloc[-BETA_WINDOW:]
            m = spy_ret.reindex(common).iloc[-BETA_WINDOW:]
            var_m = float(m.var())
            if var_m > 1e-12:
                betas[cls] = float(r.cov(m) / var_m)

    for cls, ticker in V2_CLASS_TICKER.items():
        df = b_data.get(ticker)
        wc = _weekly_close(df)
        if len(wc) < V2_MA_WEEKS:
            is_active_map[cls] = False
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
        is_active_map[cls] = is_active

    active_classes = [c for c in V2_CLASS_TICKER if is_active_map.get(c)]
    n_active = len(active_classes)
    base_weight = {cls: 0.0 for cls in V2_CLASS_TICKER}
    if n_active > 0:
        active_with_beta = [c for c in active_classes if c in betas]
        if active_with_beta:
            inv_beta = {c: 1.0 / max(abs(betas[c]), BETA_FLOOR) for c in active_with_beta}
            inv_beta_sum = sum(inv_beta.values())
            for cls in active_with_beta:
                base_weight[cls] = base_weight_per_class * n_active * inv_beta[cls] / inv_beta_sum
            for cls in active_classes:
                if cls not in betas:
                    base_weight[cls] = base_weight_per_class
        else:
            for cls in active_classes:
                base_weight[cls] = base_weight_per_class

    port_vol = sum(base_weight.get(cls, 0.0) * vols[cls] for cls in V2_CLASS_TICKER if cls in vols)
    scale = min(1.0, vol_target / port_vol) if port_vol > 1e-6 else 1.0
    raw_weights = {cls: base_weight.get(cls, 0.0) * scale for cls in V2_CLASS_TICKER}
    total_raw = sum(raw_weights.values())
    if total_raw > 1.0:
        raw_weights = {cls: w / total_raw for cls, w in raw_weights.items()}

    allocations = {cls: round(raw_weights.get(cls, 0.0) * 100.0, 2) for cls in V2_CLASS_TICKER}
    return allocations, state, {"betas": betas}


def run_backtest(signal_fn, sector_of: dict):
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
        alloc, hysteresis_state, _debug = signal_fn(b_data, prev_hysteresis_state=hysteresis_state)
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
        "avg_gross_exposure": weights_df.sum(axis=1).mean(),
        "weights_df": weights_df,
    }


def main():
    sector_of = json.load(open(SECTOR_MAP_FILE))

    print(f"{'Variante':<45}{'CAGR netto':>12}{'Sharpe netto':>14}{'MaxDD netto':>13}{'Calmar':>9}{'Espos. media':>13}")
    baseline = run_backtest(compute_v2_macro_signal, sector_of)
    calmar_b = baseline["cagr_netto"] / abs(baseline["maxdd_netto"])
    print(f"{'Baseline: peso nozionale uguale (produzione)':<45}{baseline['cagr_netto']*100:>11.2f}%{baseline['sharpe_netto']:>14.2f}"
          f"{baseline['maxdd_netto']*100:>12.2f}%{calmar_b:>9.2f}{baseline['avg_gross_exposure']*100:>12.1f}%")

    candidate = run_backtest(compute_signal_beta_weighted, sector_of)
    calmar_c = candidate["cagr_netto"] / abs(candidate["maxdd_netto"])
    print(f"{'Beta-weighted (peso inv. proporzionale a |beta|)':<45}{candidate['cagr_netto']*100:>11.2f}%{candidate['sharpe_netto']:>14.2f}"
          f"{candidate['maxdd_netto']*100:>12.2f}%{calmar_c:>9.2f}{candidate['avg_gross_exposure']*100:>12.1f}%")

    print("\nEsposizione media per classe (quando attiva) — baseline vs beta-weighted:")
    for cls in ["Equity", "Bonds", "Gold", "Crypto"]:
        wb = baseline["weights_df"][cls]
        wc = candidate["weights_df"][cls]
        ab, ac = wb[wb > 1e-9], wc[wc > 1e-9]
        print(f"  {cls:<8} baseline: {ab.mean()*100:>5.1f}% (n={len(ab)})   "
              f"beta-weighted: {ac.mean()*100:>5.1f}% (n={len(ac)})")

    diff = (candidate["net"] - baseline["net"]).dropna()
    mean_diff = diff.mean() * PERIODS_PER_YEAR * 100
    lo, hi = block_bootstrap_ci(diff.values, lambda r: pd.Series(r).mean() * PERIODS_PER_YEAR * 100,
                                 block_size=12, ci=0.90, seed=42)
    n_better = int((diff > 0).sum())
    print(f"\nConfronto accoppiato diretto (beta-weighted meno baseline nozionale uguale):")
    print(f"  Overperformance media: {mean_diff:+.2f}pp/anno, CI 90% [{lo:+.2f}, {hi:+.2f}]pp/anno "
          f"({'ESCLUDE' if lo * hi > 0 else 'INCLUDE'} lo zero)")
    print(f"  Settimane in cui beta-weighted ha fatto meglio: {n_better}/{len(diff)} ({n_better/len(diff)*100:.0f}%)")

    dsr = deflated_sharpe_ratio(candidate["sharpe_netto"], n_trials=2, n_obs=len(candidate["net"]))
    print(f"  DSR beta-weighted (n_trials=2): {dsr:.4f}")


if __name__ == "__main__":
    main()
