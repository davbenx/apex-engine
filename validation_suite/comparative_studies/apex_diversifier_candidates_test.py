"""
apex_diversifier_candidates_test.py — Oltre alle Commodities (DBC/PDBC, vedi
apex_add_commodities_test.py, nessun miglioramento robusto), quali altre
classi potrebbero diversificare Apex V2? Richiesta diretta dell'utente:
"analizziamo tutto, anche valuta, manager futures, trend, tips" + verifica
di un ETF specifico (UEQC) che si e' rivelato essere un prodotto di
commodity CARRY reale (non l'ennesimo beta ingenuo).

Candidati testati, ciascuno come 5a classe macro con la STESSA logica di
trend/isteresi/vol-target di compute_v2_macro_signal (nessuna
reimplementazione):
  - Currency:          UUP   (Invesco DB US Dollar Index Bullish Fund)
  - TIPS:               TIP   (iShares TIPS Bond ETF)
  - Managed Futures:    DBMF  (iMGP DBi Managed Futures Strategy ETF — stesso
                          proxy US gia' usato per DBMFE in Convex)
  - Trend (puro CTA):   KMLM  (KFA/Mount Lucas Managed Futures Index Strategy
                          ETF — replica indice di trend-following, blend
                          diverso da DBMF)
  - Commodity Carry:    UEQC.DE (UBS CMCI Commodity Carry SF UCITS ETF) —
                          l'ETF chiesto direttamente dall'utente. A differenza
                          di PDBC (long-only "miglior contratto lungo la
                          curva", gia' testato in apex_add_commodities_test.py,
                          quasi identico a DBC, corr. 0.99), CMCI Commodity
                          Carry e' un indice construito esplicitamente sul
                          fattore di carry (term structure) — piu' vicino
                          alla letteratura accademica (Erb & Harvey 2006).

Trattamento fiscale (coerente con le classificazioni REALI gia' stabilite in
questo progetto per gli stessi tipi di veicolo):
  - UUP: REDDITO_DIVERSO — come DBC (stesso sponsor/struttura, "Invesco DB",
    commodity pool su futures, non un fondo OICR).
  - TIP: REDDITO_CAPITALE — come IEF (fondo iShares registrato, stessa
    famiglia strutturale).
  - DBMF/KMLM: REDDITO_CAPITALE — come DBMFE.PA in convex_engine.py (fondo
    '40 Act/UCITS registrato che replica CTA, non un commodity pool/ETC).
  - UEQC.DE: REDDITO_CAPITALE — come NTSG.MI/AVWS.DE/DBMFE.PA (fondo UCITS).

UEQC.DE e' denominato in EUR (a differenza di tutto il resto del paniere
macro di Apex, tutto USD) — convertito in equivalente USD via EURUSD=X
PRIMA di essere usato, stessa tecnica gia' validata empiricamente per i
proxy Convex in convex_weights_grid_test.py (altrimenti il rumore
FX/EURUSD si mescola al segnale, bias gia' trovato e corretto in questa
sessione).

Limite dichiarato sulle finestre campione: DBMF (2019+, ~7.4 anni), KMLM
(2020+, ~5.8 anni) e UEQC.DE (2020+, ~6.7 anni) hanno storico reale molto
piu' corto di UUP/TIP (~19-20 anni) e del resto del paniere Apex (~12 anni,
vincolo di BTC-USD). Ogni candidato viene confrontato con un baseline a 4
classi RICALCOLATO sulla stessa identica finestra campione (stesso
approccio gia' usato in apex_crypto_execution_venue_test.py per la finestra
IBIT) — mai un confronto tra finestre diverse.
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
import apex_v2_engine
from apex_v2_engine import compute_v2_macro_signal, select_low_vol_basket, V2_MAX_PER_SECTOR
from metrics import cagr as _cagr, sharpe as _sharpe, max_drawdown as _max_drawdown
from tax_engine import apply_italian_tax as _apply_italian_tax
from statistical_validation import block_bootstrap_ci
from apex_stocks_vs_etf_backtest import (
    DATA_DIR, PERIODS_PER_YEAR, load_weekly_macro, load_weekly_sp500, load_pointintime_snapshots,
    eligible_universe_for_year, build_ohlc_like, _fetch_weekly_adj,
)
from sector_cap_grid_test import SECTOR_MAP_FILE

BASE_CLASS_TICKER = {"Equities": "SPY", "Bonds": "IEF", "Gold": "GLD", "Crypto": "BTC-USD"}

# (label, ticker_reale, ticker_dati_da_usare, tax_type, needs_fx_eur_to_usd)
CANDIDATES = [
    ("Currency (UUP)", "UUP", "UUP", "REDDITO_DIVERSO", False),
    ("TIPS (TIP)", "TIP", "TIP", "REDDITO_CAPITALE", False),
    ("Managed Futures (DBMF)", "DBMF", "DBMF", "REDDITO_CAPITALE", False),
    ("Trend (KMLM)", "KMLM", "KMLM", "REDDITO_CAPITALE", False),
    ("Commodity Carry (UEQC.DE)", "UEQC.DE", "UEQC_USD", "REDDITO_CAPITALE", True),
]
CANDIDATE_BASE_WEIGHT, CANDIDATE_VOL_TARGET = 0.40, 0.22  # stessa dimensione "controllata" gia' usata per DBC/PDBC


def fetch_and_prepare(label, real_ticker, data_ticker, needs_fx):
    if needs_fx:
        eurusd_path = DATA_DIR / "EURUSD_X_weekly.csv"
        if not eurusd_path.exists():
            _fetch_weekly_adj("EURUSD=X", "15y").to_csv(eurusd_path)
        raw_path = DATA_DIR / f"{real_ticker.replace('.', '_')}_weekly.csv"
        if not raw_path.exists():
            _fetch_weekly_adj(real_ticker, "15y").to_csv(raw_path)
        eur_price = pd.read_csv(raw_path, index_col=0, parse_dates=True).iloc[:, 0]
        eurusd = pd.read_csv(eurusd_path, index_col=0, parse_dates=True).iloc[:, 0]
        common_idx = eur_price.index.intersection(eurusd.index)
        usd_equivalent = (eur_price.reindex(common_idx) * eurusd.reindex(common_idx)).dropna()
        usd_equivalent.to_csv(DATA_DIR / f"{data_ticker}_weekly.csv")
    else:
        path = DATA_DIR / f"{data_ticker.replace('-', '_')}_weekly.csv"
        if not path.exists():
            _fetch_weekly_adj(real_ticker, "15y").to_csv(path)


def run_backtest(class_ticker: dict, extra_class: str, extra_tax_type: str,
                  base_weight: float, vol_target: float, sector_of: dict):
    apex_v2_engine.V2_CLASS_TICKER = class_ticker
    try:
        snapshots = load_pointintime_snapshots()
        with open(DATA_DIR / "sp500_tickers.json") as f:
            all_tickers = json.load(f)

        stock_prices = {}
        for t in all_tickers:
            try:
                stock_prices[t] = load_weekly_sp500(t)
            except FileNotFoundError:
                continue

        macro_prices = {ticker: load_weekly_macro(ticker) for ticker in class_ticker.values()}
        common_index = macro_prices["SPY"].index
        for s in macro_prices.values():
            common_index = common_index.intersection(s.index)
        weeks = list(common_index)
        n = len(weeks)

        stock_rets = {t: p.pct_change() for t, p in stock_prices.items()}
        ief_ret = macro_prices["IEF"].pct_change()
        gld_ret = macro_prices["GLD"].pct_change()
        btc_ret = macro_prices["BTC-USD"].pct_change()
        extra_ticker = class_ticker.get(extra_class)
        extra_ret = macro_prices[extra_ticker].pct_change() if extra_ticker else None

        hysteresis_state, prev_basket_tickers, current_basket = None, None, []
        locked_alloc = None
        macro_alloc_history, equity_return_basket = [], []

        MIN_HISTORY = 40
        for i, wk in enumerate(weeks):
            if i < MIN_HISTORY:
                macro_alloc_history.append(None)
                equity_return_basket.append(0.0)
                continue

            b_data = {ticker: build_ohlc_like(macro_prices[ticker].loc[:wk]) for ticker in class_ticker.values()}
            alloc, hysteresis_state, _debug = compute_v2_macro_signal(
                b_data, prev_hysteresis_state=hysteresis_state,
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

            basket_ret_this_week = float(np.mean([stock_rets[t].loc[wk] for t in current_basket if t in stock_rets])) if current_basket else 0.0
            equity_return_basket.append(basket_ret_this_week)

        valid_from = MIN_HISTORY
        idx = weeks[valid_from:]

        def alloc_frac(cls):
            return pd.Series([macro_alloc_history[i].get(cls, 0.0) / 100.0 for i in range(valid_from, n)], index=idx)

        weights_data = {
            "Equity": alloc_frac("Equities"), "Bonds": alloc_frac("Bonds"),
            "Gold": alloc_frac("Gold"), "Crypto": alloc_frac("Crypto"),
        }
        returns_data = {
            "Equity": pd.Series(equity_return_basket[valid_from:], index=idx),
            "Bonds": ief_ret.reindex(idx).fillna(0.0),
            "Gold": gld_ret.reindex(idx).fillna(0.0),
            "Crypto": btc_ret.reindex(idx).fillna(0.0),
        }
        tax_types = {"Equity": "REDDITO_DIVERSO", "Bonds": "REDDITO_CAPITALE", "Gold": "REDDITO_DIVERSO", "Crypto": "REDDITO_DIVERSO"}

        w_extra = None
        if extra_ticker:
            weights_data[extra_class] = alloc_frac(extra_class)
            returns_data[extra_class] = extra_ret.reindex(idx).fillna(0.0)
            tax_types[extra_class] = extra_tax_type
            w_extra = weights_data[extra_class]

        weights_df = pd.DataFrame(weights_data)
        returns_df = pd.DataFrame(returns_data)

        weight_change = weights_df.diff().abs().sum(axis=1).fillna(0.0)
        cost_bps_map = {"Equity": 0.0010, "Bonds": 0.0008, "Gold": 0.0010, "Crypto": 0.0010}
        cost_bps_map[extra_class] = 0.0010
        cost_drag = weight_change * np.mean([cost_bps_map[c] for c in weights_df.columns])
        port_net = _apply_italian_tax(returns_df, weights_df, tax_types=tax_types)
        port_net_after_costs = port_net - cost_drag

        return {"net": port_net_after_costs, "weights_df": weights_df, "w_extra": w_extra}
    finally:
        apex_v2_engine.V2_CLASS_TICKER = BASE_CLASS_TICKER


def report(net: pd.Series, label: str):
    calmar = _cagr(net, PERIODS_PER_YEAR) / abs(_max_drawdown(net)) if _max_drawdown(net) != 0 else float("nan")
    print(f"  {label:<38}CAGR: {_cagr(net, PERIODS_PER_YEAR)*100:>7.2f}%   "
          f"Sharpe: {_sharpe(net, periods_per_year=PERIODS_PER_YEAR):>5.2f}   "
          f"MaxDD: {_max_drawdown(net)*100:>7.2f}%   Calmar: {calmar:>5.2f}")


def main():
    for label, real_ticker, data_ticker, tax_type, needs_fx in CANDIDATES:
        path = DATA_DIR / f"{data_ticker.replace('-', '_')}_weekly.csv"
        if not path.exists():
            print(f"[*] Preparo dati per {label} ({real_ticker})...")
            fetch_and_prepare(label, real_ticker, data_ticker, needs_fx)

    sector_of = json.load(open(SECTOR_MAP_FILE))

    # Correlazione settimanale di TUTTI i candidati vs il paniere Apex esistente
    # (ciascuno sulla propria finestra disponibile, dichiarato non nascosto)
    print("--- Correlazione settimanale di ciascun candidato vs SPY/IEF/GLD/BTC-USD ---")
    base_prices = {t: load_weekly_macro(t) for t in BASE_CLASS_TICKER.values()}
    for label, _, data_ticker, _, _ in CANDIDATES:
        cand_price = load_weekly_macro(data_ticker)
        rets = pd.DataFrame({**{k: v.pct_change() for k, v in base_prices.items()},
                              data_ticker: cand_price.pct_change()}).dropna()
        corr_row = rets.corr()[data_ticker].drop(data_ticker)
        print(f"  {label:<32}n={len(rets):<5} " + "  ".join(f"{k}={v:+.2f}" for k, v in corr_row.items()))
    print()

    baseline_full = run_backtest(BASE_CLASS_TICKER, "___none___", "REDDITO_DIVERSO", 0.50, 0.22, sector_of)
    print("--- Baseline a 4 classi (50%/22%, storico Apex completo, per riferimento) ---")
    report(baseline_full["net"], "Baseline (finestra completa)")
    print()

    for label, real_ticker, data_ticker, tax_type, needs_fx in CANDIDATES:
        class_ticker = {**BASE_CLASS_TICKER, label: data_ticker}
        cand_result = run_backtest(class_ticker, label, tax_type, CANDIDATE_BASE_WEIGHT, CANDIDATE_VOL_TARGET, sector_of)

        # Baseline RICALCOLATO sulla stessa finestra del candidato (mai confronto tra finestre diverse)
        common_win = cand_result["net"].index
        baseline_win = baseline_full["net"].reindex(common_win).dropna()
        cand_win = cand_result["net"].reindex(baseline_win.index)

        print(f"=== {label} — proxy {real_ticker}, finestra comune {len(baseline_win)} settimane "
              f"({baseline_win.index.min().date()} -> {baseline_win.index.max().date()}) ===")
        report(baseline_win, "Baseline 4 classi (stessa finestra)")
        report(cand_win, f"+ {label} (5 classi, 40%/22%)")

        w_extra = cand_result["w_extra"].reindex(baseline_win.index)
        active = w_extra > 1e-9
        print(f"  {label} attiva {active.mean()*100:.1f}% delle settimane ({int(active.sum())}/{len(w_extra)}), "
              f"esposizione media quando attiva {w_extra[active].mean()*100:.1f}%" if active.sum() > 0 else
              f"  {label} MAI attiva in questa finestra")

        diff = (cand_win - baseline_win).dropna()
        if len(diff) >= 16:
            mean_diff_annual = diff.mean() * PERIODS_PER_YEAR * 100
            block = max(4, min(12, len(diff) // 10))
            lo, hi = block_bootstrap_ci(diff.values, lambda r: pd.Series(r).mean() * PERIODS_PER_YEAR * 100,
                                         block_size=block, ci=0.90, seed=42)
            n_better = int((diff > 0).sum())
            print(f"  Confronto accoppiato: overperformance media {mean_diff_annual:+.2f}pp/anno, "
                  f"CI 90% [{lo:+.2f}, {hi:+.2f}]pp/anno ({'ESCLUDE' if lo * hi > 0 else 'INCLUDE'} lo zero), "
                  f"vince {n_better}/{len(diff)} settimane ({n_better/len(diff)*100:.0f}%)")
        print()


if __name__ == "__main__":
    main()
