"""
apex_bab_long_short_quantified_test.py — Stima quantificata (dichiaratamente
approssimativa) di una gamba Betting-Against-Beta VERA (long basso beta +
short alto beta, scalati a beta-neutralita' — Frazzini-Pedersen 2014),
richiesta dall'utente nell'esperimento mentale "rimuoviamo i vincoli
(leva, short) ma teniamo il CAGR netto italiano vincolante".

Perche' questo NON e' un backtest allo stesso livello di rigore del resto
del progetto — limiti dichiarati esplicitamente:
  1. Storico limitato a 2012+ (stesso limite dati point-in-time S&P 500 di
     select_low_beta_basket) — 14 anni, non i 39 del resto di Apex.
  2. Costo di prestito titoli (borrow fee) e dividendi dovuti sullo short:
     NON esistono dati reali per questi costi in questo progetto — usati
     valori assunti (dichiarati, con sensitivity), non misurati.
  3. Trattamento fiscale: assume l'esecuzione via CFD/future (route
     realistica per un retail italiano che vuole shortare azioni USA),
     tassati REDDITO_DIVERSO (compensa minusvalenze) — un'assunzione
     OTTIMISTICA dichiarata; uno short via prestito titoli reale su
     azioni potrebbe avere trattamento diverso.
  4. Nessun margin call / rischio di richiamo margine modellato — un vero
     short ha rischio di perdita illimitata e richiede monitoraggio attivo
     che questo backtest non cattura.

Costruzione: al ribasket trimestrale (stessa cadenza/beta a 26 settimane
di select_low_beta_basket), due basket da 15 titoli — long sui beta piu'
bassi, short sui beta piu' alti (stesso buffer di rank/vincolo settoriale).
Scalati alla Frazzini-Pedersen: peso_long = 1/beta_medio_long (leva se
beta<1, il caso tipico), peso_short = 1/beta_medio_short (deleva se
beta>1) — la combinazione e' approssimativamente beta-neutra rispetto a
SPY per costruzione. La gamba short e' modellata come una posizione LONGA
sintetica sul rendimento NEGATO del basket high-beta (matematicamente
equivalente a uno short, e permette di riusare tax_engine.apply_italian_tax
senza doverne riscrivere la logica per posizioni negative) meno i costi
di finanziamento/dividendo dichiarati.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "validation_suite" / "framework"))

from apex_v2_engine import V2_EQUITY_TOP_N, V2_EQUITY_BETA_LOOKBACK, V2_EQUITY_BUFFER_RANK, V2_MAX_PER_SECTOR, _weekly_close
from apex_stocks_vs_etf_backtest import (
    DATA_DIR, load_weekly_sp500, load_pointintime_snapshots, eligible_universe_for_year, build_ohlc_like,
)
from apex_dashboard_stat_regeneration import EXT_DATA_DIR, spliced_price_index, SPLICE_SPEC, BASKET_SELECTION_FROM_YEAR, BASKET_STOCK_COST_BPS
from sector_cap_grid_test import SECTOR_MAP_FILE
from metrics import cagr as _cagr, sharpe as _sharpe, max_drawdown as _max_drawdown, calmar as _calmar, sortino_ratio, ulcer_index
from tax_engine import apply_italian_tax
from statistical_validation import block_bootstrap_ci

TEST_START = "2020-09-30"
SLICE_END = "2026-08-31"
MAX_LEVERAGE = 3.0  # cap dichiarato sulla leva 1/beta per gamba — vedi commento inline sopra

# Assunzioni dichiarate, NON misurate — sensitivity su due scenari
BORROW_FEE_ANNUAL = {"base": 0.005, "stress": 0.015}      # 50bps / 150bps annuo sul nozionale short
DIV_YIELD_ANNUAL = {"base": 0.012, "stress": 0.020}       # dividendo dovuto sullo short — assunto piu' basso del mercato (nomi high-beta spesso growth, dividendi bassi)


def _beta_ranked(eq_data: Dict[str, pd.DataFrame], spy_wc: pd.Series, lookback: int):
    spy_ret = spy_wc.pct_change().dropna()
    scored = []
    for sym, df in eq_data.items():
        wc = _weekly_close(df)
        ret = wc.pct_change().dropna()
        common = ret.index.intersection(spy_ret.index)
        if len(common) < lookback + 1:
            continue
        r, m = ret.reindex(common).iloc[-lookback:], spy_ret.reindex(common).iloc[-lookback:]
        var_m = float(m.var())
        if var_m <= 1e-12:
            continue
        scored.append((sym, float(r.cov(m) / var_m)))
    return scored  # [(sym, beta), ...] non ordinato


def _pick_basket(ranked_syms: List[str], prev_tickers: Optional[set], sector_of: dict,
                  top_n=V2_EQUITY_TOP_N, buffer_rank=V2_EQUITY_BUFFER_RANK, max_per_sector=V2_MAX_PER_SECTOR) -> List[str]:
    rank_of = {sym: i for i, sym in enumerate(ranked_syms)}
    sector_count: Dict[str, int] = {}
    result: List[str] = []

    def sector_ok(sym):
        s = sector_of.get(sym)
        return True if s is None else sector_count.get(s, 0) < max_per_sector

    def add(sym):
        result.append(sym)
        s = sector_of.get(sym)
        if s is not None:
            sector_count[s] = sector_count.get(s, 0) + 1

    prev_tickers = prev_tickers or set()
    incumbents = sorted([s for s in prev_tickers if rank_of.get(s, 10**9) < buffer_rank], key=lambda s: rank_of.get(s, 10**9))
    for sym in incumbents:
        if len(result) >= top_n:
            break
        if sector_ok(sym):
            add(sym)
    for sym in ranked_syms:
        if len(result) >= top_n:
            break
        if sym not in result and sector_ok(sym):
            add(sym)
    return result[:top_n]


def main():
    sector_of = json.load(open(SECTOR_MAP_FILE))
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

    spy_price = spliced_price_index(*SPLICE_SPEC["SPY"])
    weeks = [w for w in spy_price.index if w.year >= BASKET_SELECTION_FROM_YEAR]

    prev_long, prev_short = None, None
    cur_long, cur_short = [], []
    beta_long, beta_short = 1.0, 1.0
    r_long_hist, r_short_hist, w_long_hist, w_short_hist, turnover_cost_hist = [], [], [], [], []

    for i, wk in enumerate(weeks):
        # 1. rendimento della settimana usa i basket COSI' COM'ERANO prima di un
        #    eventuale ribasket questa settimana (stessa disciplina no-lookahead
        #    del concern #2 corretto oggi altrove in questa sessione)
        r_long = float(np.mean([stock_rets[t].loc[wk] for t in cur_long if t in stock_rets and wk in stock_rets[t].index])) if cur_long else 0.0
        r_short = float(np.mean([stock_rets[t].loc[wk] for t in cur_short if t in stock_rets and wk in stock_rets[t].index])) if cur_short else 0.0
        r_long_hist.append(r_long); r_short_hist.append(r_short)
        # Cap di leva [0, MAX_LEVERAGE]: 1/beta esplode (o cambia segno) quando il beta
        # medio del basket si avvicina a zero o diventa negativo — un evento raro ma
        # reale su finestre di 26 settimane, non un caso patologico da ignorare. Le
        # implementazioni reali di BAB (Frazzini-Pedersen incluso) limitano sempre la
        # leva per questo motivo — senza cap, un singolo trimestre con beta vicino a
        # zero produce leva/rendimenti numericamente assurdi (verificato: senza questo
        # cap, CAGR lordo implausibile >69% e NAV che va a zero, CAGR netto NaN).
        w_long_hist.append(float(np.clip(1.0 / beta_long, 0.0, MAX_LEVERAGE)) if beta_long > 1e-6 else 0.0)
        w_short_hist.append(float(np.clip(1.0 / beta_short, 0.0, MAX_LEVERAGE)) if beta_short > 1e-6 else 0.0)

        # 2. ribasket trimestrale (beta a 26 sett., stessa cadenza di produzione)
        is_month_end = (i + 1 >= len(weeks)) or (weeks[i + 1].month != wk.month)
        turnover_cost_hist.append(0.0)
        if is_month_end and wk.month in (3, 6, 9, 12):
            eligible = eligible_universe_for_year(snapshots, wk.year)
            eq_data = {t: build_ohlc_like(p.loc[:wk]) for t, p in stock_prices.items() if t in eligible}
            spy_data_upto = build_ohlc_like(spy_price.loc[:wk])
            scored = _beta_ranked(eq_data, _weekly_close(spy_data_upto), V2_EQUITY_BETA_LOOKBACK)
            if scored:
                scored_low = sorted(scored, key=lambda t: t[1])
                scored_high = sorted(scored, key=lambda t: -t[1])
                new_long = _pick_basket([s for s, _ in scored_low], prev_long, sector_of)
                new_short = _pick_basket([s for s, _ in scored_high], prev_short, sector_of)
                beta_of = dict(scored)
                new_beta_long = float(np.mean([beta_of[s] for s in new_long])) if new_long else 1.0
                new_beta_short = float(np.mean([beta_of[s] for s in new_short])) if new_short else 1.0

                if prev_long is not None:
                    n_swap_l = len(set(new_long) - prev_long)
                    n_swap_s = len(set(new_short) - prev_short)
                    cost = 0.0
                    if n_swap_l > 0 and new_long:
                        cost += n_swap_l * 2 * ((1.0 / new_beta_long) / len(new_long)) * BASKET_STOCK_COST_BPS
                    if n_swap_s > 0 and new_short:
                        cost += n_swap_s * 2 * ((1.0 / new_beta_short) / len(new_short)) * BASKET_STOCK_COST_BPS
                    turnover_cost_hist[-1] = cost

                cur_long, cur_short = new_long, new_short
                beta_long, beta_short = new_beta_long, new_beta_short
                prev_long, prev_short = set(cur_long), set(cur_short)

    idx = pd.DatetimeIndex(weeks)
    r_long_s = pd.Series(r_long_hist, index=idx)
    r_short_s = pd.Series(r_short_hist, index=idx)
    w_long_s = pd.Series(w_long_hist, index=idx)
    w_short_s = pd.Series(w_short_hist, index=idx)
    turnover_cost_s = pd.Series(turnover_cost_hist, index=idx)

    print(f"Campione: {len(idx)} settimane, {idx.min().date()} -> {idx.max().date()} "
          f"(limite 2012+, stesso dato point-in-time di select_low_beta_basket)")
    print(f"Beta medio long (finale): {beta_long:.2f}  |  Beta medio short (finale): {beta_short:.2f}  |  "
          f"Leva media long ~{w_long_s.mean():.2f}x  |  Deleva media short ~{w_short_s.mean():.2f}x")

    results = {}
    for scenario in ("base", "stress"):
        borrow_wk = BORROW_FEE_ANNUAL[scenario] / 52
        div_wk = DIV_YIELD_ANNUAL[scenario] / 52
        # gamba short come posizione LUNGA sintetica sul rendimento NEGATO (equivalente
        # economico di uno short) meno i costi di finanziamento/dividendo per quella settimana
        r_short_synthetic = -r_short_s - (borrow_wk + div_wk) * (w_short_s > 0)

        returns_df = pd.DataFrame({"long_leg": r_long_s, "short_leg": r_short_synthetic})
        weights_df = pd.DataFrame({"long_leg": w_long_s, "short_leg": w_short_s})
        tax_types = {"long_leg": "REDDITO_DIVERSO", "short_leg": "REDDITO_DIVERSO"}  # assunzione CFD/future, vedi docstring

        # rebalance_every=13 (~trimestrale): approssimazione dichiarata — i pesi
        # target sono in realta' statici tra un ribasket e l'altro (rebalance_every=1
        # realizzerebbe tassa ogni settimana anche senza un vero ribasket, solo per
        # la divergenza naturale tra le due gambe: eccessivamente punitivo e non
        # rappresentativo della cadenza reale trimestrale del ribasket).
        net = apply_italian_tax(returns_df, weights_df, tax_types=tax_types, rebalance_every=13)
        gross = (returns_df * weights_df).sum(axis=1) - turnover_cost_s
        net = net - turnover_cost_s

        gross_m = (1 + gross).resample("ME").apply(lambda x: x.prod() - 1.0)
        net_m = (1 + net).resample("ME").apply(lambda x: x.prod() - 1.0)
        results[scenario] = (gross_m, net_m)

    for scenario in ("base", "stress"):
        gross_m, net_m = results[scenario]
        print(f"\n{'='*78}\nSCENARIO {scenario.upper()} "
              f"(borrow {BORROW_FEE_ANNUAL[scenario]*100:.1f}%/anno, dividendo dovuto {DIV_YIELD_ANNUAL[scenario]*100:.1f}%/anno)\n{'='*78}")
        for label, g, n in [
            ("Intero campione (2012-2026)", gross_m, net_m),
            ("Periodo TEST (2020-09+)", gross_m.loc[TEST_START:], net_m.loc[TEST_START:]),
        ]:
            print(f"\n  {label} — {len(g)} mesi")
            print(f"    CAGR lordo:  {_cagr(g,12)*100:+7.2f}%   CAGR netto: {_cagr(n,12)*100:+7.2f}%")
            print(f"    Sharpe lordo: {_sharpe(g,periods_per_year=12):6.3f}   Sortino: {sortino_ratio(g,periods_per_year=12):6.3f}")
            print(f"    MaxDD lordo: {_max_drawdown(g)*100:7.2f}%   Calmar: {_calmar(g,12):6.3f}   Ulcer: {ulcer_index(g):5.2f}")

    gross_base_test = results["base"][0].loc[TEST_START:]
    lo, hi = block_bootstrap_ci(gross_base_test.values, lambda r: pd.Series(r).mean() * 12 * 100, block_size=6, ci=0.90, seed=42)
    mean_ann = gross_base_test.mean() * 12 * 100
    print(f"\nCI90 sul CAGR lordo scenario BASE, periodo TEST: {mean_ann:+.2f}pp/anno [{lo:+.2f}, {hi:+.2f}] "
          f"({'ESCLUDE' if lo*hi>0 else 'include'} lo zero)")


if __name__ == "__main__":
    main()
