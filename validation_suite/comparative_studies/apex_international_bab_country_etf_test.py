"""
apex_international_bab_country_etf_test.py — Idea #1 della lista di
approfondimento ("campione indipendente non-US per BAB/Betting Against
Beta"), finora bloccata: la Teoria #5 (`apex_beta_basket_selection_test.py`,
gia' adottata in produzione — Apex seleziona oggi il basket azionario per
BETA vs SPY, non piu' per volatilita' assoluta) e' stata validata SOLO sul
mercato azionario USA. Un secondo campione, indipendente e non-US, servirebbe
a rafforzare (o indebolire) la fiducia nel meccanismo di fondo — ma testarlo
con la stessa tecnica (selezione titolo-per-titolo dentro FTSE100/STOXX600)
richiede un elenco datato delle variazioni di composizione dell'indice
("point-in-time membership"), che Wikipedia fornisce per l'S&P 500 ma non
in forma pulita/scaricabile per gli indici europei — blocco dichiarato.

Altra strada: invece di BAB titolo-per-titolo dentro un indice nazionale,
si testa BAB a livello di PAESE/MERCATO — esattamente come Frazzini &
Pedersen (2014) verificano l'anomalia anche "across asset classes/paesi",
non solo dentro un singolo indice. Non serve nessuna storia di
composizione: l'universo e' un paniere FISSO di ETF-paese (l'azione stessa
di beta-selection avviene tra ETF, non tra le migliaia di titoli
sottostanti), quindi il problema del point-in-time membership non si pone
affatto — ogni ETF-paese e' l'unita' investibile stessa dal giorno del
lancio, non un proxy di un indice che cambia composizione.

Universo: 15 ETF Paese sviluppato di iShares MSCI con storico dal
1996-04 (30 anni, molto piu' lungo dei 626/1355 settimane usati nei test
IntlEquities precedenti su EFA, che parte solo dal 2001): Giappone (EWJ),
Germania (EWG), Regno Unito (EWU), Francia (EWQ), Australia (EWA), Canada
(EWC), Svizzera (EWL), Svezia (EWD), Spagna (EWP), Italia (EWI), Paesi
Bassi (EWN), Austria (EWO), Belgio (EWK), Singapore (EWS), Hong Kong
(EWH). Nota sui limiti: e' una selezione di ETF che sono sopravvissuti
fino a oggi con lo stesso ticker dal 1996 (nessun paese "delistato" nel
senso in cui puo' esserlo un'azienda, ma la persistenza del prodotto ETF
stesso e' comunque un criterio di scelta a posteriori, dichiarato qui).

Benchmark per il calcolo del beta: paniere equal-weight degli stessi 15
ETF (non EFA, per non limitare il campione al 2001 e restare internamente
coerenti — analogo a un "mercato mondiale ex-USA" auto-costruito).

Design: beta trailing 26 settimane (stessa finestra di produzione,
V2_EQUITY_BETA_LOOKBACK), ribilanciamento trimestrale (stessa cadenza del
basket azionario Apex), basket low-beta = 7 ETF a beta piu' basso,
basket high-beta = 7 ETF a beta piu' alto (il quindicesimo, mediano,
escluso da entrambi per simmetria).
"""
from __future__ import annotations

import time
import random
import urllib.request
import urllib.error
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "validation_suite" / "framework"))

from metrics import cagr as _cagr, sharpe as _sharpe, max_drawdown as _max_drawdown
from statistical_validation import pbo_cscv, block_bootstrap_ci
from apex_stocks_vs_etf_backtest import PERIODS_PER_YEAR

USER_AGENT = "Mozilla/5.0 (compatible; ApexEngineResearch/1.0; contact@apexengine.research)"
HTTP_TIMEOUT = 20
CACHE_DIR = Path(__file__).parent / "apex_country_etf_data"

UNIVERSE = ["EWJ", "EWG", "EWU", "EWQ", "EWA", "EWC", "EWL", "EWD", "EWP", "EWI", "EWN", "EWO", "EWK", "EWS", "EWH"]
BETA_WINDOW = 26  # settimane — stessa di V2_EQUITY_BETA_LOOKBACK in produzione
N_LOW, N_HIGH = 7, 7  # su 15, il 15-esimo (mediano) resta escluso da entrambi
MIN_HISTORY = 60  # settimane di warmup prima della prima formazione basket


def _fetch_daily_full(ticker: str) -> pd.Series:
    cache_file = CACHE_DIR / f"{ticker}.csv"
    if cache_file.exists():
        return pd.read_csv(cache_file, index_col=0, parse_dates=True).iloc[:, 0]
    p1 = int(pd.Timestamp("1996-01-01").timestamp())
    p2 = int(pd.Timestamp.utcnow().timestamp())
    url = f"https://query2.finance.yahoo.com/v8/finance/chart/{ticker}?period1={p1}&period2={p2}&interval=1d"
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            res = json.loads(urllib.request.urlopen(req, timeout=HTTP_TIMEOUT).read().decode())
            result = res["chart"]["result"][0]
            ts = pd.to_datetime(result["timestamp"], unit="s")
            close = pd.Series(result["indicators"]["quote"][0]["close"], index=ts).dropna()
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            close.to_csv(cache_file, header=["Close"])
            return close
        except (urllib.error.HTTPError, urllib.error.URLError, KeyError, IndexError):
            time.sleep(1.0 + attempt)
    raise RuntimeError(f"Fetch fallito per {ticker}")


def load_weekly_returns() -> dict[str, pd.Series]:
    rets = {}
    for t in UNIVERSE:
        daily = _fetch_daily_full(t)
        weekly = daily.resample("W-FRI").last().dropna()
        rets[t] = weekly.pct_change().dropna()
        time.sleep(random.uniform(0.05, 0.15))
    return rets


def build_benchmark(rets: dict[str, pd.Series], common_index: pd.DatetimeIndex) -> pd.Series:
    df = pd.DataFrame({t: r.reindex(common_index) for t, r in rets.items()})
    return df.mean(axis=1)  # equal-weight, "mondo sviluppato ex-USA" auto-costruito


def trailing_beta(asset_ret: pd.Series, bench_ret: pd.Series, upto_idx: int, window: int) -> float | None:
    r = asset_ret.iloc[max(0, upto_idx - window):upto_idx]
    m = bench_ret.iloc[max(0, upto_idx - window):upto_idx]
    if len(r) < window:
        return None
    var_m = float(m.var())
    if var_m <= 1e-12:
        return None
    return float(r.cov(m) / var_m)


def run_backtest(rets: dict[str, pd.Series], bench: pd.Series, weeks: list) -> dict[str, pd.Series]:
    n = len(weeks)
    low_basket, high_basket = [], []
    low_ret_hist, high_ret_hist, eq_ret_hist = [], [], []

    for i, wk in enumerate(weeks):
        if i < MIN_HISTORY:
            low_ret_hist.append(0.0)
            high_ret_hist.append(0.0)
            eq_ret_hist.append(float(bench.iloc[i]) if i < len(bench) else 0.0)
            continue

        is_month_end = (i + 1 >= n) or (weeks[i + 1].month != wk.month)
        need_reform = (not low_basket) or (is_month_end and wk.month in (3, 6, 9, 12))
        if need_reform:
            betas = {}
            for t in UNIVERSE:
                b = trailing_beta(rets[t], bench, i, BETA_WINDOW)
                if b is not None:
                    betas[t] = b
            ranked = sorted(betas, key=betas.get)
            if len(ranked) >= N_LOW + N_HIGH:
                low_basket = ranked[:N_LOW]
                high_basket = ranked[-N_HIGH:]

        low_ret = float(np.mean([rets[t].iloc[i] for t in low_basket if i < len(rets[t])])) if low_basket else 0.0
        high_ret = float(np.mean([rets[t].iloc[i] for t in high_basket if i < len(rets[t])])) if high_basket else 0.0
        eq_ret = float(np.mean([rets[t].iloc[i] for t in UNIVERSE if i < len(rets[t])]))
        low_ret_hist.append(low_ret)
        high_ret_hist.append(high_ret)
        eq_ret_hist.append(eq_ret)

    idx = pd.DatetimeIndex(weeks)
    return {
        "low_beta": pd.Series(low_ret_hist, index=idx).iloc[MIN_HISTORY:],
        "high_beta": pd.Series(high_ret_hist, index=idx).iloc[MIN_HISTORY:],
        "equal_weight": pd.Series(eq_ret_hist, index=idx).iloc[MIN_HISTORY:],
    }


def main():
    print(f"[*] Fetch storico giornaliero completo per {len(UNIVERSE)} ETF Paese (1996-2026, cache locale)...")
    rets = load_weekly_returns()

    common_index = None
    for t, r in rets.items():
        common_index = r.index if common_index is None else common_index.intersection(r.index)
    weeks = list(common_index.sort_values())
    print(f"[*] Campione comune: {len(weeks)} settimane, {weeks[0].date()} -> {weeks[-1].date()}")

    rets = {t: r.reindex(weeks).fillna(0.0) for t, r in rets.items()}
    bench_full = build_benchmark(rets, pd.DatetimeIndex(weeks))

    print("[*] Backtest: basket low-beta/high-beta/equal-weight, ribilanciamento trimestrale, beta trailing 26 sett...")
    result = run_backtest(rets, bench_full, weeks)

    print(f"\n{'Variante':<20}{'CAGR':>10}{'Sharpe':>10}{'MaxDD':>10}")
    for label, key in [("Low-beta (7/15)", "low_beta"), ("High-beta (7/15)", "high_beta"), ("Equal-weight (15)", "equal_weight")]:
        net = result[key]
        c, s, dd = _cagr(net, PERIODS_PER_YEAR), _sharpe(net, periods_per_year=PERIODS_PER_YEAR), _max_drawdown(net)
        print(f"{label:<20}{c*100:>9.2f}%{s:>10.2f}{dd*100:>9.2f}%")

    diff_vs_eq = (result["low_beta"] - result["equal_weight"]).dropna()
    mean_diff = diff_vs_eq.mean() * PERIODS_PER_YEAR * 100
    lo, hi = block_bootstrap_ci(diff_vs_eq.values, lambda r: pd.Series(r).mean() * PERIODS_PER_YEAR * 100, block_size=26, ci=0.90, seed=42)
    n_better = int((diff_vs_eq > 0).sum())
    print(f"\nConfronto accoppiato diretto (low-beta meno equal-weight):")
    print(f"  Overperformance media: {mean_diff:+.2f}pp/anno, CI 90% [{lo:+.2f}, {hi:+.2f}]pp/anno "
          f"({'ESCLUDE' if lo * hi > 0 else 'include'} lo zero)")
    print(f"  Settimane in cui ha fatto meglio: {n_better}/{len(diff_vs_eq)} ({n_better/len(diff_vs_eq)*100:.0f}%)")

    diff_lh = (result["low_beta"] - result["high_beta"]).dropna()
    mean_lh = diff_lh.mean() * PERIODS_PER_YEAR * 100
    lo2, hi2 = block_bootstrap_ci(diff_lh.values, lambda r: pd.Series(r).mean() * PERIODS_PER_YEAR * 100, block_size=26, ci=0.90, seed=42)
    print(f"\nSpread classico BAB (low-beta meno high-beta, long-short):")
    print(f"  Overperformance media: {mean_lh:+.2f}pp/anno, CI 90% [{lo2:+.2f}, {hi2:+.2f}]pp/anno "
          f"({'ESCLUDE' if lo2 * hi2 > 0 else 'include'} lo zero)")

    perf_matrix = np.column_stack([result["low_beta"].values, result["high_beta"].values, result["equal_weight"].values])
    n_splits = 8
    usable_len = (len(perf_matrix) // n_splits) * n_splits
    pbo = pbo_cscv(perf_matrix[-usable_len:], n_splits=n_splits)
    print(f"\nPBO-CSCV su 3 varianti (low/high/equal-weight): {pbo*100:.1f}%")

    print("\n--- Robustezza per sotto-periodo (nessun parametro da selezionare qui: solo split temporale) ---")
    n_sub = 4
    sub_len = len(weeks[MIN_HISTORY:]) // n_sub
    idx_all = result["low_beta"].index
    for i in range(n_sub):
        sub_idx = idx_all[i * sub_len: (i + 1) * sub_len] if i < n_sub - 1 else idx_all[i * sub_len:]
        if len(sub_idx) < 20:
            continue
        low_s, high_s, eq_s = result["low_beta"].reindex(sub_idx), result["high_beta"].reindex(sub_idx), result["equal_weight"].reindex(sub_idx)
        print(f"  {sub_idx.min().date()} -> {sub_idx.max().date()} ({len(sub_idx)} sett.): "
              f"low-beta Sharpe {_sharpe(low_s, periods_per_year=PERIODS_PER_YEAR):5.2f}  "
              f"high-beta Sharpe {_sharpe(high_s, periods_per_year=PERIODS_PER_YEAR):5.2f}  "
              f"equal-weight Sharpe {_sharpe(eq_s, periods_per_year=PERIODS_PER_YEAR):5.2f}")


if __name__ == "__main__":
    main()
