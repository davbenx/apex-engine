"""
apex_quality_tilt_low_beta_basket_test.py — Idea #4 della lista di
approfondimento ("quality overlay sul basket low-beta", Asness-Frazzini-
Pedersen 2019 QMJ), finora bloccata: Yahoo Finance non offre fondamentali
storici, e senza un dato genuinamente point-in-time qualunque test
sarebbe viziato da look-ahead (usare oggi il ROE che il mercato non
poteva ancora conoscere in passato).

Altra strada: SEC EDGAR XBRL Company Facts API e' gratuita e riporta per
ogni dato il campo 'filed' — la data REALE di deposito, non la fine del
periodo contabile. Vedi apex_quality_data/fetch_roe_pointintime.py per il
dettaglio del fetch/estrazione (cache locale, 477/503 ticker con dati,
6718 osservazioni annuali). Fattore scelto: ROE = NetIncomeLoss annuale
(solo 10-K/10-K/A) / StockholdersEquity a fine anno fiscale — pillar
"profitability" di QMJ, tag XBRL tra i piu' universali (niente TTM
trimestrale, niente GrossProfit/Revenues che hanno tag eterogenei tra
aziende e nel tempo dopo ASC 606).

Design: la SELEZIONE del basket low-beta resta ESATTAMENTE quella di
produzione (select_low_beta_basket, beta vs SPY, cap settoriale, buffer
di rank) — la qualita' non cambia CHI entra nel basket, solo il PESO
relativo tra i 15 titoli gia' selezionati (equal-weight oggi). Tra i
membri del basket in una data settimana, z-score del ROE piu' recente
CONOSCIUTO a quella data (filed <= settimana; ticker senza dato ROE
disponibile restano a z=0, peso neutro, non vengono esclusi):
  peso_i = (1 + alpha * z_i) clip [0.1, 2.0], poi normalizzato a somma 1
Con alpha=0 il risultato e' identico alla produzione (equal-weight) —
stesso principio di controllo-equivalente delle altre griglie di questa
sessione.

Efficienza: la selezione del basket (quali 15 titoli) e l'allocazione
macro a 4 classi (trend/vol-target) NON dipendono da alpha — un solo giro
costoso; lo z-score di qualita' per settimana e' anch'esso indipendente
da alpha (dipende solo dai membri del basket e dal loro ROE storico) e va
quindi precalcolato una volta sola; solo l'applicazione finale del tilt e
la normalizzazione dei pesi sono ricalcolate per ciascun valore di alpha.

Walk-forward onesto: 3 ere, alpha scelto per ogni era SOLO con lo Sharpe
delle ere precedenti, griglia [0.0 (controllo), 0.3, 0.6, 1.0] — stessa
convenzione di apex_dual_momentum_class_weight_test.py.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path
from datetime import date

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
from apex_quality_data.fetch_roe_pointintime import fetch_bulk as fetch_roe_bulk

ALPHA_GRID = [0.0, 0.3, 0.6, 1.0]  # 0.0 = produzione esatta, equal-weight (controllo)
OTHER_BASE_WEIGHT = 0.50
N_ERAS = 3
CLASSES = list(V2_CLASS_TICKER.keys())


def build_roe_lookup(roe_data: dict[str, list[dict]]) -> dict[str, pd.Series]:
    """Per ticker: Serie ROE indicizzata per data di DEPOSITO (filed), da usare con .asof()
    per il valore piu' recente REALMENTE noto a una data (niente lookahead)."""
    lookup = {}
    for t, rows in roe_data.items():
        if not rows:
            continue
        idx = pd.DatetimeIndex([pd.Timestamp(r["filed"]) for r in rows])
        s = pd.Series([r["roe"] for r in rows], index=idx).sort_index()
        s = s[~s.index.duplicated(keep="last")]
        lookup[t] = s
    return lookup


def quality_z_for_basket(basket: list[str], wk: pd.Timestamp, roe_lookup: dict[str, pd.Series]) -> dict[str, float]:
    raw = {}
    for t in basket:
        s = roe_lookup.get(t)
        if s is None or wk < s.index[0]:
            continue
        val = s.asof(wk)
        if pd.notna(val):
            raw[t] = float(val)
    if len(raw) < 2:
        return {t: 0.0 for t in basket}
    vals = np.array(list(raw.values()))
    mean, std = vals.mean(), vals.std()
    z = {t: ((v - mean) / std if std > 1e-9 else 0.0) for t, v in raw.items()}
    for t in basket:
        z.setdefault(t, 0.0)
    return z


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

    print("[*] Caricamento ROE point-in-time (SEC EDGAR, cache locale)...")
    roe_data = fetch_roe_bulk(all_tickers)
    roe_lookup = build_roe_lookup(roe_data)

    macro_prices = {V2_CLASS_TICKER[c]: load_weekly_macro(V2_CLASS_TICKER[c]) for c in V2_CLASS_TICKER}
    macro_rets_df = pd.DataFrame({c: macro_prices[V2_CLASS_TICKER[c]].pct_change() for c in CLASSES})
    common_index = macro_prices["SPY"].index
    for s in macro_prices.values():
        common_index = common_index.intersection(s.index)
    weeks = list(common_index.sort_values())
    n = len(weeks)

    ief_ret, gld_ret, btc_ret = macro_rets_df["Bonds"], macro_rets_df["Gold"], macro_rets_df["Crypto"]

    hysteresis_state, prev_basket_tickers, current_basket = None, None, []
    is_active_hist, vol_hist, basket_hist, quality_z_hist = [], [], [], []

    MIN_HISTORY = 40
    for i, wk in enumerate(weeks):
        if i < MIN_HISTORY:
            is_active_hist.append(None)
            vol_hist.append(None)
            basket_hist.append(None)
            quality_z_hist.append(None)
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

        basket_hist.append(list(current_basket))
        quality_z_hist.append(quality_z_for_basket(current_basket, wk, roe_lookup) if current_basket else {})

    return {
        "weeks": weeks, "n": n, "is_active_hist": is_active_hist, "vol_hist": vol_hist,
        "basket_hist": basket_hist, "quality_z_hist": quality_z_hist, "stock_rets": stock_rets,
        "ief_ret": ief_ret, "gld_ret": gld_ret, "btc_ret": btc_ret,
    }


def equity_return_series(shared: dict, alpha: float) -> list[float]:
    weeks, n = shared["weeks"], shared["n"]
    basket_hist, quality_z_hist, stock_rets = shared["basket_hist"], shared["quality_z_hist"], shared["stock_rets"]
    out = []
    for i, wk in enumerate(weeks):
        basket = basket_hist[i]
        if not basket:
            out.append(0.0)
            continue
        z = quality_z_hist[i]
        if alpha == 0.0:
            w_raw = {t: 1.0 for t in basket}
        else:
            w_raw = {t: float(np.clip(1.0 + alpha * z.get(t, 0.0), 0.1, 2.0)) for t in basket}
        total = sum(w_raw.values())
        w = {t: v / total for t, v in w_raw.items()}
        ret = sum(w[t] * stock_rets[t].loc[wk] for t in basket if t in stock_rets and wk in stock_rets[t].index)
        out.append(float(ret))
    return out


def run_variant(shared: dict, alpha: float, vol_target: float = V2_VOL_TARGET):
    weeks, n = shared["weeks"], shared["n"]
    is_active_hist, vol_hist = shared["is_active_hist"], shared["vol_hist"]
    equity_return_basket = equity_return_series(shared, alpha)
    MIN_HISTORY = 40

    locked_alloc = None
    macro_alloc_history = []
    for i, wk in enumerate(weeks):
        if i < MIN_HISTORY:
            macro_alloc_history.append(None)
            continue
        is_active, vols = is_active_hist[i], vol_hist[i]
        base_weight = {c: (OTHER_BASE_WEIGHT if is_active.get(c, False) else 0.0) for c in CLASSES}
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
        "Equity": pd.Series(equity_return_basket[valid_from:], index=idx),
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
    print("[*] Passata condivisa (trend/vol/basket/qualita' ROE, una sola volta)...")
    shared = precompute_shared_series(sector_of)

    print("[*] Backtest per ciascun valore della griglia alpha...")
    net_by_alpha, weights_by_alpha = {}, {}
    for alpha in ALPHA_GRID:
        net, w = run_variant(shared, alpha)
        net_by_alpha[alpha] = net
        weights_by_alpha[alpha] = w
        c, s, dd = _cagr(net, PERIODS_PER_YEAR), _sharpe(net, periods_per_year=PERIODS_PER_YEAR), _max_drawdown(net)
        print(f"  alpha={alpha:.1f}  CAGR {c*100:6.2f}%  Sharpe {s:5.2f}  MaxDD {dd*100:7.2f}%")

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
    for label, net in [("Baseline (alpha=0.0, attuale)", baseline_oos), ("Walk-forward (quality tilt)", wf_net)]:
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
