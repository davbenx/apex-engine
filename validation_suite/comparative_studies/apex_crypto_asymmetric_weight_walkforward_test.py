"""
apex_crypto_asymmetric_weight_walkforward_test.py — Approfondimento
richiesto esplicitamente dall'utente ("sì approfondisci") dopo la scoperta
collaterale nel test satellite BTC (altcoin_satellite_btc_confound_test.py):
il vol-target lascia capacita' di rischio inutilizzata sulla classe Crypto,
e alzarla (in QUALUNQUE forma, satellite incluso) migliora il backtest in
modo monotono — ma con segnali d'allarme (Sharpe piatto, MaxDD raddoppia,
PBO-CSCV 70% sulla versione BTC) che indicano "leva su cio' che e' andato
bene storicamente" (BTC CAGR 38,25% standalone nel campione), non skill.

Qui il test e' fatto correttamente: non un satellite bolt-on ma un
base_weight_per_class ASIMMETRICO (Crypto sopra il 50% base, le altre 3
classi invariate a 50%) — concettualmente distinto da
apex_class_size_grid_test.py (che alza il tetto per TUTTE le classi
uniformemente) e dal satellite (che aggiunge una sleeve separata fuori
dal meccanismo di vol-target). E soprattutto: **selezione walk-forward
onesta senza look-ahead**, esattamente lo stesso principio gia' applicato
alla Teoria #5 azionaria e al low-beta altcoin — mai fatto finora su
questo asse.

Efficienza: is_active[classe][settimana] e vols[classe][settimana] NON
dipendono da crypto_base_weight (dipendono solo da prezzo/trend/vol
dell'asset, non dal dimensionamento) — calcolati una sola volta con
compute_v2_macro_signal(base_weight_per_class=0.50) di default, poi
ogni candidato della griglia ricalcola SOLO l'allocazione finale
(base_weight per classe -> vol-scale -> rinormalizzazione no-leva) dai
valori precalcolati, senza rifare l'intero giro trend/isteresi per ogni
punto della griglia. Stesso principio di riuso gia' usato per i tanti
walk-forward precedenti in questa cartella.
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

CRYPTO_WEIGHT_GRID = [0.50, 0.65, 0.75, 0.90, 1.00]  # 0.50 = attuale/controllo, le altre classi restano SEMPRE a 0.50
OTHER_BASE_WEIGHT = 0.50
N_ERAS = 3


def precompute_shared_series(sector_of: dict):
    """Un solo giro costoso su tutta la storia: is_active/vol per classe
    (indipendenti da crypto_base_weight) e il basket azionario low-beta
    reale di produzione (indipendente dal sizing macro). Tutto il resto
    (griglia crypto_base_weight) riusa questi risultati senza ricalcolo."""
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
    is_active_hist, vol_hist = [], []
    equity_return_basket = []

    MIN_HISTORY = 40
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

    return {
        "weeks": weeks, "n": n, "is_active_hist": is_active_hist, "vol_hist": vol_hist,
        "equity_return_basket": equity_return_basket, "ief_ret": ief_ret, "gld_ret": gld_ret, "btc_ret": btc_ret,
    }


def run_variant(shared: dict, crypto_base_weight: float, vol_target: float = V2_VOL_TARGET):
    """Ricalcolo CHEAP dell'allocazione per un dato crypto_base_weight, dai
    valori precalcolati in shared — nessun nuovo giro su trend/basket."""
    weeks, n = shared["weeks"], shared["n"]
    is_active_hist, vol_hist = shared["is_active_hist"], shared["vol_hist"]
    MIN_HISTORY = 40

    locked_alloc = None
    macro_alloc_history = []
    for i, wk in enumerate(weeks):
        if i < MIN_HISTORY:
            macro_alloc_history.append(None)
            continue

        is_active, vols = is_active_hist[i], vol_hist[i]
        base_weight = {c: (crypto_base_weight if c == "Crypto" else OTHER_BASE_WEIGHT) if is_active.get(c, False) else 0.0
                       for c in V2_CLASS_TICKER}
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
    return port_net - cost_drag, weights_df["Crypto"]


def main():
    sector_of = json.load(open(SECTOR_MAP_FILE))
    print("[*] Passata condivisa (trend/vol/basket, una sola volta)...")
    shared = precompute_shared_series(sector_of)

    print("[*] Backtest per ciascun valore della griglia crypto_base_weight...")
    net_by_cw, crypto_exposure_by_cw = {}, {}
    for cw in CRYPTO_WEIGHT_GRID:
        net, crypto_w = run_variant(shared, cw)
        net_by_cw[cw] = net
        crypto_exposure_by_cw[cw] = crypto_w
        c, s, dd = _cagr(net, PERIODS_PER_YEAR), _sharpe(net, periods_per_year=PERIODS_PER_YEAR), _max_drawdown(net)
        print(f"  crypto_base_weight={cw:.2f}  esposiz.crypto media={crypto_w.mean()*100:5.1f}%  "
              f"CAGR {c*100:6.2f}%  Sharpe {s:5.2f}  MaxDD {dd*100:7.2f}%")

    common_idx = net_by_cw[CRYPTO_WEIGHT_GRID[0]].index
    for net in net_by_cw.values():
        common_idx = common_idx.intersection(net.index)
    common_idx = common_idx.sort_values()
    era_len = len(common_idx) // N_ERAS
    eras = [common_idx[i * era_len:(i + 1) * era_len] for i in range(N_ERAS - 1)]
    eras.append(common_idx[(N_ERAS - 1) * era_len:])
    print(f"\nEre: {[(e.min().date(), e.max().date(), len(e)) for e in eras]}")

    baseline = net_by_cw[0.50].reindex(common_idx)

    print(f"\n{'Era':<8}{'crypto_base_weight selezionato':>32}{'Sharpe selezione':>18}")
    wf_segments = []
    for i in range(1, N_ERAS):
        past_idx = common_idx[:i * era_len]
        sharpes_past = {cw: _sharpe(net_by_cw[cw].reindex(past_idx).dropna(), periods_per_year=PERIODS_PER_YEAR)
                         for cw in CRYPTO_WEIGHT_GRID}
        best_cw = max(sharpes_past, key=sharpes_past.get)
        print(f"Era {i+1:<5}{best_cw:>32.2f}{sharpes_past[best_cw]:>18.2f}")
        wf_segments.append(net_by_cw[best_cw].reindex(eras[i]).dropna())

    wf_net = pd.concat(wf_segments).sort_index()
    baseline_oos = baseline.reindex(wf_net.index)

    print(f"\n--- OUT-OF-SAMPLE (ere 2+3, {len(wf_net)} settimane, "
          f"{wf_net.index.min().date()} -> {wf_net.index.max().date()}) ---")
    for label, net in [("Baseline (crypto_base_weight=0.50, attuale)", baseline_oos),
                        ("Walk-forward (crypto asimmetrico)", wf_net)]:
        c, s, dd = _cagr(net, PERIODS_PER_YEAR), _sharpe(net, periods_per_year=PERIODS_PER_YEAR), _max_drawdown(net)
        print(f"  {label:<45}CAGR {c*100:>8.2f}%   Sharpe {s:>5.2f}   MaxDD {dd*100:>7.2f}%")

    diff = (wf_net - baseline_oos).dropna()
    mean_diff = diff.mean() * PERIODS_PER_YEAR * 100
    lo, hi = block_bootstrap_ci(diff.values, lambda r: pd.Series(r).mean() * PERIODS_PER_YEAR * 100, block_size=12, ci=0.90, seed=42)
    n_better = int((diff > 0).sum())
    print(f"\nConfronto accoppiato diretto (walk-forward meno baseline, solo OOS):")
    print(f"  Overperformance media: {mean_diff:+.2f}pp/anno, CI 90% [{lo:+.2f}, {hi:+.2f}]pp/anno "
          f"({'ESCLUDE' if lo * hi > 0 else 'include'} lo zero)")
    print(f"  Settimane in cui ha fatto meglio: {n_better}/{len(diff)} ({n_better/len(diff)*100:.0f}%)")

    perf_matrix = np.column_stack([net_by_cw[cw].reindex(common_idx).values for cw in CRYPTO_WEIGHT_GRID])
    n_splits = 8
    usable_len = (len(perf_matrix) // n_splits) * n_splits
    pbo = pbo_cscv(perf_matrix[-usable_len:], n_splits=n_splits)
    print(f"\nPBO-CSCV full-sample su {len(CRYPTO_WEIGHT_GRID)} valori crypto_base_weight (contesto, non walk-forward): {pbo*100:.1f}%")

    # Sensibilita': quanto viene dagli ultimi anni (2023-2026, bull run BTC) vs
    # dal resto? Se il vantaggio sparisce escludendoli, e' concentrato in un
    # singolo episodio, non un effetto stabile nel tempo.
    pre_idx = common_idx[common_idx < pd.Timestamp("2023-01-01")]
    if len(pre_idx) > 52:
        print(f"\n--- Sensibilita': stesso confronto ESCLUDENDO 2023-2026 ({len(pre_idx)} settimane, "
              f"fino a {pre_idx.max().date()}) ---")
        diff_pre = (net_by_cw[1.00].reindex(pre_idx) - baseline.reindex(pre_idx)).dropna()
        mean_diff_pre = diff_pre.mean() * PERIODS_PER_YEAR * 100
        lo_p, hi_p = block_bootstrap_ci(diff_pre.values, lambda r: pd.Series(r).mean() * PERIODS_PER_YEAR * 100, block_size=12, ci=0.90, seed=42)
        print(f"  crypto_base_weight=1.00 meno baseline, pre-2023: {mean_diff_pre:+.2f}pp/anno, "
              f"CI 90% [{lo_p:+.2f}, {hi_p:+.2f}] ({'ESCLUDE' if lo_p * hi_p > 0 else 'include'} lo zero)")


if __name__ == "__main__":
    main()
