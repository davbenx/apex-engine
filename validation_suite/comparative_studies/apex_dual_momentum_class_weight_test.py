"""
apex_dual_momentum_class_weight_test.py — Idea #4 della lista di
approfondimento ("Dual Momentum tra classi macro", Antonacci 2014): oggi
ogni classe attiva riceve peso nominale UGUALE (50% base) indipendentemente
da quanto forte sia il suo trend rispetto alle altre classi attive nello
stesso momento — un segnale di momentum RELATIVO (non solo assoluto/binario)
non e' mai stato testato.

Rischio esplicito da evitare (motivo per cui questo NON e' la Teoria #3
risk-parity ne' il class-weight beta-pesato, entrambi falliti per lo stesso
meccanismo): quei due schemi pesavano INVERSAMENTE a una misura di rischio
(vol o beta) — Bonds ha valore vicino a zero su entrambe le metriche,
quindi domina strutturalmente qualsiasi inverse-weighting. Qui si pesa
DIRETTAMENTE per FORZA DI MOMENTUM (non inversamente per rischio) — un
meccanismo diverso, ma con un rischio speculare: Bonds ha tipicamente
rendimenti/momentum piu' deboli di Crypto/Equity quando entrambi sono
attivi, quindi potrebbe finire strutturalmente SOTTO-pesato. Non e'
necessariamente un difetto (coerente con la filosofia momentum: meno peso
al trend piu' debole), ma va verificato, non assunto.

Design: tra le classi ATTIVE (trend assoluto gia' confermato, invariato),
il peso nominale base (50%) viene inclinato dal momentum RELATIVO
(z-score del rendimento trailing 12 settimane tra le sole classi attive in
quel momento), non da una misura di rischio:
  peso_i = base_weight * (1 + alpha * z_score_i), clip a [0.1, 2.0] * base_weight
Con 0 o 1 classe attiva non c'e' nulla da confrontare: comportamento
IDENTICO alla produzione.

Walk-forward onesto (stessa disciplina di tutta questa sessione): 3 ere,
alpha scelto per ogni era SOLO con lo Sharpe delle ere precedenti, griglia
[0.0 (= produzione esatta, controllo), 0.3, 0.6, 1.0].

Efficienza: is_active/vol/rendimento trailing per classe non dipendono da
alpha — un solo giro costoso (trend/basket), poi la griglia alpha e' cheap
(stesso principio di apex_crypto_asymmetric_weight_walkforward_test.py).
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

from apex_v2_engine import compute_v2_macro_signal, select_low_beta_basket, V2_CLASS_TICKER, V2_VOL_TARGET
from metrics import cagr as _cagr, sharpe as _sharpe, max_drawdown as _max_drawdown
from tax_engine import apply_italian_tax as _apply_italian_tax
from statistical_validation import pbo_cscv, block_bootstrap_ci
from apex_stocks_vs_etf_backtest import (
    DATA_DIR, PERIODS_PER_YEAR, load_weekly_macro, load_weekly_sp500, load_pointintime_snapshots,
    eligible_universe_for_year, build_ohlc_like,
)
from sector_cap_grid_test import SECTOR_MAP_FILE

ALPHA_GRID = [0.0, 0.3, 0.6, 1.0]  # 0.0 = produzione esatta (controllo)
MOMENTUM_WINDOW = 12  # settimane, non cherry-picked: ~1 trimestre, stessa cadenza del rebuild basket
OTHER_BASE_WEIGHT = 0.50
N_ERAS = 3


def precompute_shared_series(sector_of: dict):
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
    macro_rets = {c: macro_prices[V2_CLASS_TICKER[c]].pct_change() for c in V2_CLASS_TICKER}
    common_index = macro_prices["SPY"].index
    for s in macro_prices.values():
        common_index = common_index.intersection(s.index)
    weeks = list(common_index.sort_values())
    n = len(weeks)

    ief_ret, gld_ret, btc_ret = macro_rets["Bonds"], macro_rets["Gold"], macro_rets["Crypto"]

    hysteresis_state, prev_basket_tickers, current_basket = None, None, []
    is_active_hist, vol_hist, momentum_hist = [], [], []
    equity_return_basket = []

    MIN_HISTORY = 40
    for i, wk in enumerate(weeks):
        if i < MIN_HISTORY:
            is_active_hist.append(None)
            vol_hist.append(None)
            momentum_hist.append(None)
            equity_return_basket.append(0.0)
            continue

        b_data = {V2_CLASS_TICKER[c]: build_ohlc_like(macro_prices[V2_CLASS_TICKER[c]].loc[:wk]) for c in V2_CLASS_TICKER}
        _alloc, hysteresis_state, debug = compute_v2_macro_signal(b_data, prev_hysteresis_state=hysteresis_state)
        is_active_hist.append({c: debug[c]["attivo"] for c in V2_CLASS_TICKER if "attivo" in debug.get(c, {})})
        vol_hist.append({c: (debug[c]["vol_12w_ann_pct"] / 100.0) for c in V2_CLASS_TICKER
                          if debug.get(c, {}).get("vol_12w_ann_pct") is not None})

        mom = {}
        for c in V2_CLASS_TICKER:
            r = macro_rets[c]
            past = r.loc[:wk].iloc[-MOMENTUM_WINDOW:]
            mom[c] = float((1 + past).prod() - 1.0) if len(past) == MOMENTUM_WINDOW else None
        momentum_hist.append(mom)

        def rebuild_basket():
            eligible = eligible_universe_for_year(snapshots, wk.year)
            eq_data = {t: build_ohlc_like(p.loc[:wk]) for t, p in stock_prices.items() if t in eligible}
            spy_data_upto = build_ohlc_like(macro_prices["SPY"].loc[:wk])
            basket = select_low_beta_basket(eq_data, spy_data_upto, prev_tickers=prev_basket_tickers, sector_of=sector_of)
            return [b["Ticker"] for b in basket]

        is_month_end = (i + 1 >= n) or (weeks[i + 1].month != wk.month)
        if not current_basket:
            current_basket = rebuild_basket()
            prev_basket_tickers = set(current_basket)
        elif is_month_end and wk.month in (3, 6, 9, 12):
            current_basket = rebuild_basket()
            prev_basket_tickers = set(current_basket)

        basket_ret = float(np.mean([stock_rets[t].loc[wk] for t in current_basket if t in stock_rets])) if current_basket else 0.0
        equity_return_basket.append(basket_ret)

    return {
        "weeks": weeks, "n": n, "is_active_hist": is_active_hist, "vol_hist": vol_hist, "momentum_hist": momentum_hist,
        "equity_return_basket": equity_return_basket, "ief_ret": ief_ret, "gld_ret": gld_ret, "btc_ret": btc_ret,
    }


def run_variant(shared: dict, alpha: float, vol_target: float = V2_VOL_TARGET):
    weeks, n = shared["weeks"], shared["n"]
    is_active_hist, vol_hist, momentum_hist = shared["is_active_hist"], shared["vol_hist"], shared["momentum_hist"]
    MIN_HISTORY = 40

    locked_alloc = None
    macro_alloc_history = []
    for i, wk in enumerate(weeks):
        if i < MIN_HISTORY:
            macro_alloc_history.append(None)
            continue

        is_active, vols, mom = is_active_hist[i], vol_hist[i], momentum_hist[i]
        active_classes = [c for c in V2_CLASS_TICKER if is_active.get(c, False)]

        base_weight = {c: (OTHER_BASE_WEIGHT if c in active_classes else 0.0) for c in V2_CLASS_TICKER}
        if alpha > 0 and len(active_classes) >= 2:
            mom_vals = [mom.get(c) for c in active_classes]
            if all(v is not None for v in mom_vals):
                arr = np.array(mom_vals)
                std = arr.std()
                z = (arr - arr.mean()) / std if std > 1e-9 else np.zeros_like(arr)
                for c, zi in zip(active_classes, z):
                    tilt = np.clip(1.0 + alpha * zi, 0.1, 2.0)
                    base_weight[c] = OTHER_BASE_WEIGHT * tilt

        port_vol = sum(base_weight[c] * vols[c] for c in V2_CLASS_TICKER if c in vols)
        scale = min(1.0, vol_target / port_vol) if port_vol > 1e-6 else 1.0
        raw = {c: base_weight[c] * scale for c in V2_CLASS_TICKER}
        total_raw = sum(raw.values())
        if total_raw > 1.0:
            raw = {c: w / total_raw for c, w in raw.items()}
        alloc = {c: raw[c] * 100.0 for c in V2_CLASS_TICKER}

        is_month_end = (i + 1 >= n) or (weeks[i + 1].month != wk.month)
        if locked_alloc is None:
            locked_alloc = alloc
        macro_alloc_history.append(dict(locked_alloc))
        if is_month_end:
            locked_alloc = alloc

    valid_from = MIN_HISTORY
    idx = weeks[valid_from:]

    def alloc_frac(cls):
        return pd.Series([macro_alloc_history[i].get(cls, 0.0) / 100.0 for i in range(valid_from, n)], index=idx)

    weights_df = pd.DataFrame({"Equity": alloc_frac("Equities"), "Bonds": alloc_frac("Bonds"),
                                "Gold": alloc_frac("Gold"), "Crypto": alloc_frac("Crypto")})
    returns_df = pd.DataFrame({
        "Equity": pd.Series(shared["equity_return_basket"][valid_from:], index=idx),
        "Bonds": shared["ief_ret"].reindex(idx).fillna(0.0),
        "Gold": shared["gld_ret"].reindex(idx).fillna(0.0),
        "Crypto": shared["btc_ret"].reindex(idx).fillna(0.0),
    })
    tax_types = {"Equity": "REDDITO_DIVERSO", "Bonds": "REDDITO_CAPITALE", "Gold": "REDDITO_DIVERSO", "Crypto": "REDDITO_DIVERSO"}

    weight_change = weights_df.diff().abs().sum(axis=1).fillna(0.0)
    cost_bps_map = {"Equity": 0.0010, "Bonds": 0.0008, "Gold": 0.0010, "Crypto": 0.0010}
    cost_drag = weight_change * np.mean(list(cost_bps_map.values()))
    port_net = _apply_italian_tax(returns_df, weights_df, tax_types=tax_types)
    return port_net - cost_drag, weights_df


def main():
    sector_of = json.load(open(SECTOR_MAP_FILE))
    print("[*] Passata condivisa (trend/vol/momentum/basket, una sola volta)...")
    shared = precompute_shared_series(sector_of)

    print("[*] Backtest per ciascun valore della griglia alpha...")
    net_by_alpha, weights_by_alpha = {}, {}
    for alpha in ALPHA_GRID:
        net, w = run_variant(shared, alpha)
        net_by_alpha[alpha] = net
        weights_by_alpha[alpha] = w
        c, s, dd = _cagr(net, PERIODS_PER_YEAR), _sharpe(net, periods_per_year=PERIODS_PER_YEAR), _max_drawdown(net)
        print(f"  alpha={alpha:.1f}  CAGR {c*100:6.2f}%  Sharpe {s:5.2f}  MaxDD {dd*100:7.2f}%  "
              f"peso medio Bonds={w['Bonds'].mean()*100:4.1f}%  Crypto={w['Crypto'].mean()*100:4.1f}%")

    common_idx = net_by_alpha[ALPHA_GRID[0]].index
    for net in net_by_alpha.values():
        common_idx = common_idx.intersection(net.index)
    common_idx = common_idx.sort_values()
    era_len = len(common_idx) // N_ERAS
    eras = [common_idx[i * era_len:(i + 1) * era_len] for i in range(N_ERAS - 1)]
    eras.append(common_idx[(N_ERAS - 1) * era_len:])
    print(f"\nEre: {[(e.min().date(), e.max().date(), len(e)) for e in eras]}")

    baseline = net_by_alpha[0.0].reindex(common_idx)

    print(f"\n{'Era':<8}{'alpha selezionato':>20}{'Sharpe selezione':>18}")
    wf_segments = []
    for i in range(1, N_ERAS):
        past_idx = common_idx[:i * era_len]
        sharpes_past = {a: _sharpe(net_by_alpha[a].reindex(past_idx).dropna(), periods_per_year=PERIODS_PER_YEAR)
                         for a in ALPHA_GRID}
        best_a = max(sharpes_past, key=sharpes_past.get)
        print(f"Era {i+1:<5}{best_a:>20.1f}{sharpes_past[best_a]:>18.2f}")
        wf_segments.append(net_by_alpha[best_a].reindex(eras[i]).dropna())

    wf_net = pd.concat(wf_segments).sort_index()
    baseline_oos = baseline.reindex(wf_net.index)

    print(f"\n--- OUT-OF-SAMPLE (ere 2+3, {len(wf_net)} settimane) ---")
    for label, net in [("Baseline (alpha=0.0, attuale)", baseline_oos), ("Walk-forward (dual momentum)", wf_net)]:
        c, s, dd = _cagr(net, PERIODS_PER_YEAR), _sharpe(net, periods_per_year=PERIODS_PER_YEAR), _max_drawdown(net)
        print(f"  {label:<35}CAGR {c*100:>8.2f}%   Sharpe {s:>5.2f}   MaxDD {dd*100:>7.2f}%")

    diff = (wf_net - baseline_oos).dropna()
    mean_diff = diff.mean() * PERIODS_PER_YEAR * 100
    lo, hi = block_bootstrap_ci(diff.values, lambda r: pd.Series(r).mean() * PERIODS_PER_YEAR * 100, block_size=12, ci=0.90, seed=42)
    n_better = int((diff > 0).sum())
    print(f"\nConfronto accoppiato diretto (walk-forward meno baseline, solo OOS):")
    print(f"  Overperformance media: {mean_diff:+.2f}pp/anno, CI 90% [{lo:+.2f}, {hi:+.2f}]pp/anno "
          f"({'ESCLUDE' if lo * hi > 0 else 'include'} lo zero)")
    print(f"  Settimane in cui ha fatto meglio: {n_better}/{len(diff)} ({n_better/len(diff)*100:.0f}%)")

    perf_matrix = np.column_stack([net_by_alpha[a].reindex(common_idx).values for a in ALPHA_GRID])
    n_splits = 8
    usable_len = (len(perf_matrix) // n_splits) * n_splits
    pbo = pbo_cscv(perf_matrix[-usable_len:], n_splits=n_splits)
    print(f"\nPBO-CSCV full-sample su {len(ALPHA_GRID)} valori alpha (contesto, non walk-forward): {pbo*100:.1f}%")


if __name__ == "__main__":
    main()
