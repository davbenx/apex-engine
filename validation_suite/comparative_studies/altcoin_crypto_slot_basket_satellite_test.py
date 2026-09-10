"""
altcoin_crypto_slot_basket_satellite_test.py — Approfondimento richiesto
esplicitamente dall'utente dopo la falsificazione walk-forward del pick
singolo low-beta (altcoin_low_beta_weekly_walkforward_test.py: PBO 55-60%,
CI enormi, segno instabile per era): "bisogna anche investigare il numero
di posizioni altcoin, l'universo e le percentuali (sostituiscono Bitcoin o
sono extra?)".

Nota di onesta' statistica: il meccanismo di base (quale moneta scegliere
nello slot Crypto in base al beta vs BTC) NON ha superato il walk-forward
nella sua forma piu' semplice (N=1). Le due estensioni sotto (basket N>1,
satellite extra) aggiungono ulteriori gradi di liberta' su un campione gia'
corto e rumoroso — ci si aspetta a priori che peggiorino, non migliorino,
il PBO. Testate comunque su richiesta esplicita, con la stessa disciplina
statistica delle verifiche precedenti (PBO-CSCV, bootstrap CI accoppiato).

Nessuna selezione di finestra walk-forward qui: si usa vol_window=13
settimane FISSO (valore centrale della griglia [4,8,13,20,26], non
scelto post-hoc) per evitare di impilare un altro livello di ottimizzazione
in-sample sopra la scelta di basket-size/satellite-pct — la griglia
combinata (basket_n x satellite_pct) e' gia' un multiple-testing surface
sufficiente, controllato via PBO-CSCV.

PARTE A — Basket (sostituzione, livello-strumento): lo slot Crypto resta
100% investito, ma invece di UN solo altcoin a beta piu' basso vs BTC, ne
possiede N equal-weight (nuova mode "low_beta_basket" in
build_candidate_weights, altcoin_vs_btc_daily_backtest.py). Testato su
entrambi gli universi point-in-time (top-3, top-5 alt/trimestre) con
basket_n coerente con la dimensione dell'universo.

PARTE B — Satellite (extra, livello-portafoglio Apex intero): lo slot
Crypto NON cambia (resta BTC, produzione attuale) — si aggiunge una sleeve
satellite separata, attiva SOLO nelle settimane in cui il segnale di trend
Apex per la classe Crypto e' ON (stesso timing, nessun nuovo segnale),
dimensionata a satellite_pct fisso del NAV, investita nel singolo altcoin a
beta piu' basso vs BTC. E' un'aggiunta di rischio incrementale reale (gross
exposure totale del portafoglio sale di satellite_pct nelle settimane
attive), non una sostituzione — risponde letteralmente a "extra" tassata
come REDDITO_DIVERSO al pari di BTC, riusando apply_italian_tax del motore
di produzione a 4 classi (stessa struttura di
apex_production_confirmation_backtest.py, qui parametrizzata sulla classe
Crypto invece che su quella Equity).
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

from statistical_validation import pbo_cscv, block_bootstrap_ci
from metrics import sharpe, cagr, max_drawdown
from altcoin_vs_btc_daily_backtest import (
    ALL_TICKERS, DATA_DIR, fetch_all_price_data, load_daily,
    load_pointintime_top_alts, build_candidate_weights, backtest_strategy,
)
from apex_v2_engine import (
    compute_v2_macro_signal, select_low_beta_basket, V2_MAX_PER_SECTOR, V2_CLASS_TICKER,
)
from tax_engine import apply_italian_tax
from apex_stocks_vs_etf_backtest import (
    DATA_DIR as STOCKS_DATA_DIR, load_weekly_macro, load_weekly_sp500, load_pointintime_snapshots,
    eligible_universe_for_year, build_ohlc_like,
)
from sector_cap_grid_test import SECTOR_MAP_FILE

WEEKLY_PERIODS_PER_YEAR = 52
SHORT_WINDOW, LONG_WINDOW, TRAIL_WINDOW = 3, 9, 4
FIXED_BETA_WINDOW = 13  # valore centrale della griglia, non ottimizzato — vedi docstring


def _weekly_alt_returns():
    if not DATA_DIR.exists() or not any(DATA_DIR.glob("*_daily.csv")):
        print(f"[*] Nessun dato in cache in {DATA_DIR}, scarico da Yahoo Finance...")
        fetch_all_price_data()
    prices_daily = {t: load_daily(t) for t in ALL_TICKERS}
    common = prices_daily["BTC-USD"].index
    for p in prices_daily.values():
        common = common.union(p.index)
    common = common.sort_values()
    common = common[common >= pd.Timestamp("2019-10-01")]
    px_daily = pd.DataFrame({t: prices_daily[t].reindex(common).ffill() for t in ALL_TICKERS})
    px_weekly = px_daily.resample("W-FRI").last()
    rets = px_weekly.pct_change().fillna(0.0)  # fix gia' applicato nel walk-forward test
    return rets.loc[rets.index[1:]]


def part_a_basket():
    print("\n########## PARTE A — BASKET (sostituzione, livello-strumento) ##########")
    rets = _weekly_alt_returns()

    for top_n, basket_sizes in [(3, [1, 2]), (5, [1, 2, 3, 5])]:
        print(f"\n--- Universo point-in-time TOP-{top_n} alt/trimestre ---")
        pit_alts = load_pointintime_top_alts(top_n)

        w_btc = build_candidate_weights(rets, pit_alts, "btc_only",
                                         short_window=SHORT_WINDOW, long_window=LONG_WINDOW, trail_window=TRAIL_WINDOW, vol_window=4)
        _, net_btc = backtest_strategy(w_btc, rets, "BTC buy & hold", periods_per_year=WEEKLY_PERIODS_PER_YEAR, verbose=False)

        net_by_n = {}
        for n in basket_sizes:
            mode = "low_beta_pick" if n == 1 else "low_beta_basket"
            w = build_candidate_weights(rets, pit_alts, mode, short_window=SHORT_WINDOW, long_window=LONG_WINDOW,
                                         trail_window=TRAIL_WINDOW, vol_window=FIXED_BETA_WINDOW, basket_n=n)
            _, net = backtest_strategy(w, rets, f"low_beta basket N={n}", periods_per_year=WEEKLY_PERIODS_PER_YEAR, verbose=False)
            net_by_n[n] = net

        common_idx = net_btc.index
        for n in basket_sizes:
            common_idx = common_idx.intersection(net_by_n[n].index)
        common_idx = common_idx.sort_values()

        print(f"{'Variante':<28}{'CAGR':>10}{'Sharpe':>9}{'MaxDD':>10}{'vs BTC pp/anno':>18}{'CI90':>22}")
        c, s, dd = cagr(net_btc.reindex(common_idx), WEEKLY_PERIODS_PER_YEAR), sharpe(net_btc.reindex(common_idx), periods_per_year=WEEKLY_PERIODS_PER_YEAR), max_drawdown(net_btc.reindex(common_idx))
        print(f"{'BTC buy & hold':<28}{c*100:>9.2f}%{s:>9.2f}{dd*100:>9.2f}%{'--':>18}{'--':>22}")
        for n in basket_sizes:
            net = net_by_n[n].reindex(common_idx)
            c, s, dd = cagr(net, WEEKLY_PERIODS_PER_YEAR), sharpe(net, periods_per_year=WEEKLY_PERIODS_PER_YEAR), max_drawdown(net)
            diff = (net - net_btc.reindex(common_idx)).dropna()
            mean_diff = diff.mean() * WEEKLY_PERIODS_PER_YEAR * 100
            lo, hi = block_bootstrap_ci(diff.values, lambda r: pd.Series(r).mean() * WEEKLY_PERIODS_PER_YEAR * 100, block_size=8, ci=0.90, seed=42)
            label = "Basket N=1 (pick singolo)" if n == 1 else f"Basket N={n}"
            print(f"{label:<28}{c*100:>9.2f}%{s:>9.2f}{dd*100:>9.2f}%{mean_diff:>+17.2f}   [{lo:+.2f}, {hi:+.2f}]")

        perf_matrix = np.column_stack([net_btc.reindex(common_idx).values] + [net_by_n[n].reindex(common_idx).values for n in basket_sizes])
        n_splits = 6
        usable_len = (len(perf_matrix) // n_splits) * n_splits
        pbo = pbo_cscv(perf_matrix[-usable_len:], n_splits=n_splits)
        print(f"PBO-CSCV su {1+len(basket_sizes)} configurazioni (BTC + basket N={basket_sizes}): {pbo*100:.1f}%")


def _run_apex_with_crypto_variant(satellite_pct: float, sector_of: dict, alt_pick_ret: pd.Series):
    """Motore Apex a 4 classi (Equity/Bonds/Gold/Crypto), identico a
    apex_production_confirmation_backtest.run_backtest ma con lo slot Crypto
    parametrizzato: satellite_pct=0.0 -> produzione attuale (solo BTC).
    satellite_pct>0 -> sleeve extra attiva quando la classe Crypto e' ON,
    dimensionata a satellite_pct del NAV, sul singolo alt a beta piu' basso
    vs BTC (alt_pick_ret, gia' calcolato su base weekly con vol_window=13)."""
    snapshots = load_pointintime_snapshots()
    with open(STOCKS_DATA_DIR / "sp500_tickers.json") as f:
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
            spy_data_upto = build_ohlc_like(macro_prices["SPY"].loc[:wk])
            basket = select_low_beta_basket(eq_data, spy_data_upto, prev_tickers=prev_basket_tickers, sector_of=sector_of)
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

    crypto_frac = alloc_frac("Crypto")
    satellite_weight = (crypto_frac > 0).astype(float) * satellite_pct

    weights_df = pd.DataFrame({
        "Equity": alloc_frac("Equities"), "Bonds": alloc_frac("Bonds"),
        "Gold": alloc_frac("Gold"), "Crypto": crypto_frac, "AltSatellite": satellite_weight,
    })
    returns_df = pd.DataFrame({
        "Equity": pd.Series(equity_return_basket[valid_from:], index=idx),
        "Bonds": ief_ret.reindex(idx).fillna(0.0),
        "Gold": gld_ret.reindex(idx).fillna(0.0),
        "Crypto": btc_ret.reindex(idx).fillna(0.0),
        "AltSatellite": alt_pick_ret.reindex(idx).fillna(0.0),
    })
    tax_types = {"Equity": "REDDITO_DIVERSO", "Bonds": "REDDITO_CAPITALE", "Gold": "REDDITO_DIVERSO",
                 "Crypto": "REDDITO_DIVERSO", "AltSatellite": "REDDITO_DIVERSO"}

    weight_change = weights_df.diff().abs().sum(axis=1).fillna(0.0)
    cost_bps_map = {"Equity": 0.0010, "Bonds": 0.0008, "Gold": 0.0010, "Crypto": 0.0010, "AltSatellite": 0.0010}
    cost_drag = weight_change * np.mean(list(cost_bps_map.values()))
    port_net = apply_italian_tax(returns_df, weights_df, tax_types=tax_types)
    return port_net - cost_drag


def part_b_satellite():
    print("\n\n########## PARTE B — SATELLITE (extra, livello-portafoglio) ##########")
    sector_of = json.load(open(SECTOR_MAP_FILE))

    rets = _weekly_alt_returns()
    pit_alts = load_pointintime_top_alts(5)  # universo piu' ampio per il satellite (piu' scelta -> beta piu' basso raggiungibile)
    w_pick = build_candidate_weights(rets, pit_alts, "low_beta_pick", short_window=SHORT_WINDOW, long_window=LONG_WINDOW,
                                      trail_window=TRAIL_WINDOW, vol_window=FIXED_BETA_WINDOW)
    alt_pick_ret = (w_pick.shift(1) * rets).sum(axis=1)

    results = {}
    for satellite_pct in (0.0, 0.10, 0.25, 0.50):
        print(f"[*] Backtest portafoglio Apex, satellite_pct={satellite_pct:.0%}...")
        results[satellite_pct] = _run_apex_with_crypto_variant(satellite_pct, sector_of, alt_pick_ret)

    common_idx = results[0.0].index
    for r in results.values():
        common_idx = common_idx.intersection(r.index)
    common_idx = common_idx.sort_values()

    print(f"\n{'Satellite %':<14}{'CAGR netto':>12}{'Sharpe netto':>14}{'MaxDD netto':>13}{'vs baseline pp/anno':>22}{'CI90':>22}")
    base = results[0.0].reindex(common_idx)
    for pct, net in results.items():
        net = net.reindex(common_idx)
        c, s, dd = cagr(net, WEEKLY_PERIODS_PER_YEAR), sharpe(net, periods_per_year=WEEKLY_PERIODS_PER_YEAR), max_drawdown(net)
        if pct == 0.0:
            print(f"{'0% (baseline)':<14}{c*100:>11.2f}%{s:>14.2f}{dd*100:>12.2f}%{'--':>22}{'--':>22}")
        else:
            diff = (net - base).dropna()
            mean_diff = diff.mean() * WEEKLY_PERIODS_PER_YEAR * 100
            lo, hi = block_bootstrap_ci(diff.values, lambda r: pd.Series(r).mean() * WEEKLY_PERIODS_PER_YEAR * 100, block_size=12, ci=0.90, seed=42)
            print(f"{pct:>13.0%}{c*100:>11.2f}%{s:>14.2f}{dd*100:>12.2f}%{mean_diff:>+21.2f}   [{lo:+.2f}, {hi:+.2f}]")

    perf_matrix = np.column_stack([results[pct].reindex(common_idx).values for pct in results])
    n_splits = 6
    usable_len = (len(perf_matrix) // n_splits) * n_splits
    pbo = pbo_cscv(perf_matrix[-usable_len:], n_splits=n_splits)
    print(f"PBO-CSCV su {len(results)} configurazioni (satellite_pct = {list(results.keys())}): {pbo*100:.1f}%")


def main():
    part_a_basket()
    part_b_satellite()


if __name__ == "__main__":
    main()
