"""
apex_kelly_class_weight_second_round_test.py — Secondo giro di verifica
richiesto dall'utente per Kelly sulle classi macro di Apex
(apex_kelly_class_weight_test.py): risultato promettente ma non ancora
provato (CI 90% sulla differenza [-6,97;+7,26], PBO-CSCV 48,6% — al
livello del rumore), stesso trattamento gia' dato alla Teoria #5
(basket azionario BAB) prima della sua adozione in produzione.

Due assi di stress aggiuntivi rispetto al primo giro:
1. **Sensibilita' alla finestra di stima mu/Sigma**: griglia [104, 156,
   208] settimane (2/3/4 anni) invece del solo 156 fisso — se il
   risultato regge solo a 156 e crolla altrove, era probabilmente un
   punto fortunato, non un effetto robusto.
2. **Walk-forward a 5 ere invece di 3**: piu' punti di decisione OOS
   indipendenti (4 invece di 2), stesso principio di "piu' finestre
   rivelano quello che un solo split nasconde" gia' applicato ripetutamente
   in questa sessione (Teoria #5, Kelly Stack).

Efficienza: trend/vol/basket azionario sono INDIPENDENTI dalla finestra
mu/Sigma (dipendono solo dal segnale di trend di compute_v2_macro_signal,
mai toccato qui) — precalcolati UNA SOLA VOLTA, poi riusati per tutte e 3
le finestre. Solo mu/Sigma/f* (puro calcolo numpy su rendimenti gia'
cachati, nessun rebuild di basket) viene ricalcolato per finestra —
quindi il costo totale resta vicino a un singolo giro completo, non 3x.
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

WINDOW_GRID = [104, 156, 208]  # 2/3/4 anni
KELLY_FRACTION_GRID = [0.0, 0.25, 0.5, 1.0]  # 0.0 = controllo, equal-weight attuale
OTHER_BASE_WEIGHT = 0.50
N_ERAS = 5
CLASSES = list(V2_CLASS_TICKER.keys())
MAX_WINDOW = max(WINDOW_GRID)


def precompute_trend_and_basket(sector_of: dict):
    """Indipendente dalla finestra mu/Sigma — trend/vol/basket azionario,
    identici per ogni configurazione testata in questo script."""
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
    macro_rets_df = pd.DataFrame({c: macro_prices[V2_CLASS_TICKER[c]].pct_change() for c in CLASSES})
    common_index = macro_prices["SPY"].index
    for s in macro_prices.values():
        common_index = common_index.intersection(s.index)
    weeks = list(common_index.sort_values())
    n = len(weeks)

    hysteresis_state, prev_basket_tickers, current_basket = None, None, []
    is_active_hist, vol_hist = [], []
    equity_return_basket = []

    MIN_HISTORY = max(40, MAX_WINDOW)
    for i, wk in enumerate(weeks):
        if i < MIN_HISTORY:
            is_active_hist.append(None)
            vol_hist.append(None)
            equity_return_basket.append(0.0)
            continue

        b_data = {V2_CLASS_TICKER[c]: build_ohlc_like(macro_prices[V2_CLASS_TICKER[c]].loc[:wk]) for c in V2_CLASS_TICKER}
        _alloc, hysteresis_state, debug = compute_v2_macro_signal(b_data, prev_hysteresis_state=hysteresis_state)
        is_active_hist.append({c: debug[c]["attivo"] for c in V2_CLASS_TICKER if "attivo" in debug.get(c, {})})
        vol_hist.append({c: (debug[c]["vol_12w_ann_pct"] / 100.0) for c in V2_CLASS_TICKER
                          if debug.get(c, {}).get("vol_12w_ann_pct") is not None})

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

    ief_ret, gld_ret, btc_ret = macro_rets_df["Bonds"], macro_rets_df["Gold"], macro_rets_df["Crypto"]
    return {
        "weeks": weeks, "n": n, "is_active_hist": is_active_hist, "vol_hist": vol_hist,
        "equity_return_basket": equity_return_basket, "ief_ret": ief_ret, "gld_ret": gld_ret, "btc_ret": btc_ret,
        "macro_rets_df": macro_rets_df,
    }


def compute_f_star_hist(shared: dict, window: int):
    """Solo calcolo numpy su rendimenti gia' cachati — nessun rebuild di
    basket, cheap anche ripetuto per ogni finestra della griglia."""
    weeks, n = shared["weeks"], shared["n"]
    macro_rets_df = shared["macro_rets_df"]
    f_star_hist = []
    MIN_HISTORY = max(40, MAX_WINDOW)
    for i, wk in enumerate(weeks):
        if i < MIN_HISTORY:
            f_star_hist.append(None)
            continue
        window_rets = macro_rets_df.loc[:wk].iloc[-window:]
        if len(window_rets) == window and not window_rets.isna().any().any():
            mu = window_rets.mean().values * 52
            Sigma = window_rets.cov().values * 52
            try:
                f_star = np.linalg.solve(Sigma, mu)
            except np.linalg.LinAlgError:
                f_star = np.full(len(CLASSES), np.nan)
        else:
            f_star = np.full(len(CLASSES), np.nan)
        f_star_hist.append(dict(zip(CLASSES, f_star)))
    return f_star_hist


def run_variant(shared: dict, f_star_hist: list, kelly_frac: float, vol_target: float = V2_VOL_TARGET):
    weeks, n = shared["weeks"], shared["n"]
    is_active_hist, vol_hist = shared["is_active_hist"], shared["vol_hist"]
    MIN_HISTORY = max(40, MAX_WINDOW)

    locked_alloc = None
    macro_alloc_history = []
    for i, wk in enumerate(weeks):
        if i < MIN_HISTORY:
            macro_alloc_history.append(None)
            continue

        is_active, vols, f_star = is_active_hist[i], vol_hist[i], f_star_hist[i]
        active_classes = [c for c in CLASSES if is_active.get(c, False)]

        if kelly_frac == 0.0 or f_star is None or any(pd.isna(f_star.get(c, np.nan)) for c in active_classes) or not active_classes:
            base_weight = {c: (OTHER_BASE_WEIGHT if c in active_classes else 0.0) for c in CLASSES}
        else:
            base_weight = {c: max(0.0, f_star[c]) * kelly_frac if c in active_classes else 0.0 for c in CLASSES}

        port_vol = sum(base_weight[c] * vols[c] for c in CLASSES if c in vols)
        scale = min(1.0, vol_target / port_vol) if port_vol > 1e-6 else 1.0
        raw = {c: base_weight[c] * scale for c in CLASSES}
        total_raw = sum(raw.values())
        if total_raw > 1.0:
            raw = {c: w / total_raw for c, w in raw.items()}
        alloc = {c: raw[c] * 100.0 for c in CLASSES}

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
    return port_net - cost_drag


def main():
    sector_of = json.load(open(SECTOR_MAP_FILE))
    print("[*] Precalcolo trend/vol/basket (indipendente dalla finestra mu/Sigma, una sola volta)...")
    shared = precompute_trend_and_basket(sector_of)

    print("[*] Backtest per ciascuna combinazione (finestra mu/Sigma x frazione Kelly)...")
    net_by_combo = {}
    for window in WINDOW_GRID:
        f_star_hist = compute_f_star_hist(shared, window)
        for frac in KELLY_FRACTION_GRID:
            key = (window, frac)
            net = run_variant(shared, f_star_hist, frac)
            net_by_combo[key] = net
            c, s, dd = _cagr(net, PERIODS_PER_YEAR), _sharpe(net, periods_per_year=PERIODS_PER_YEAR), _max_drawdown(net)
            print(f"  finestra={window:>3} sett.  frac={frac:.2f}  CAGR {c*100:6.2f}%  Sharpe {s:5.2f}  MaxDD {dd*100:7.2f}%")

    # Controllo unico (frac=0.0 e' identico per costruzione a prescindere dalla finestra
    # mu/Sigma, visto che f_star non viene mai usato quando frac=0.0) - dedup per l'indice comune.
    all_keys = list(net_by_combo.keys())
    common_idx = net_by_combo[all_keys[0]].index
    for net in net_by_combo.values():
        common_idx = common_idx.intersection(net.index)
    common_idx = common_idx.sort_values()

    control_key = (WINDOW_GRID[0], 0.0)
    baseline = net_by_combo[control_key].reindex(common_idx)

    era_len = len(common_idx) // N_ERAS
    eras = [common_idx[i * era_len:(i + 1) * era_len] for i in range(N_ERAS - 1)]
    eras.append(common_idx[(N_ERAS - 1) * era_len:])
    print(f"\nEre ({N_ERAS}): {[(e.min().date(), e.max().date(), len(e)) for e in eras]}")

    print(f"\n{'Era':<8}{'combo selezionata (finestra, frac)':>38}{'Sharpe selezione':>18}")
    wf_segments = []
    for i in range(1, N_ERAS):
        past_idx = common_idx[:i * era_len]
        sharpes_past = {key: _sharpe(net.reindex(past_idx).dropna(), periods_per_year=PERIODS_PER_YEAR)
                         for key, net in net_by_combo.items()}
        best_key = max(sharpes_past, key=sharpes_past.get)
        print(f"Era {i+1:<5}{str(best_key):>38}{sharpes_past[best_key]:>18.2f}")
        wf_segments.append(net_by_combo[best_key].reindex(eras[i]).dropna())

    wf_net = pd.concat(wf_segments).sort_index()
    baseline_oos = baseline.reindex(wf_net.index)

    print(f"\n--- OUT-OF-SAMPLE (ere 2-5, {len(wf_net)} settimane) ---")
    for label, net in [("Baseline (equal-weight attuale)", baseline_oos), ("Walk-forward (Kelly, 5 ere)", wf_net)]:
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

    perf_matrix = np.column_stack([net_by_combo[k].reindex(common_idx).values for k in all_keys])
    n_splits = 8
    usable_len = (len(perf_matrix) // n_splits) * n_splits
    pbo = pbo_cscv(perf_matrix[-usable_len:], n_splits=n_splits)
    print(f"\nPBO-CSCV full-sample su {len(all_keys)} combinazioni (finestra x frazione, contesto, non walk-forward): {pbo*100:.1f}%")

    # Sensibilita' diretta: quanto e' stabile il MaxDD tra finestre, a parita' di frac=1.0?
    print("\n--- Sensibilita' diretta: MaxDD a frac=1.0 per ciascuna finestra mu/Sigma ---")
    for window in WINDOW_GRID:
        net = net_by_combo[(window, 1.0)].reindex(common_idx)
        print(f"  finestra={window} sett.: MaxDD {_max_drawdown(net)*100:.2f}%  Sharpe {_sharpe(net, periods_per_year=PERIODS_PER_YEAR):.2f}")
    print(f"  Baseline (equal-weight): MaxDD {_max_drawdown(baseline)*100:.2f}%  Sharpe {_sharpe(baseline, periods_per_year=PERIODS_PER_YEAR):.2f}")


if __name__ == "__main__":
    main()
