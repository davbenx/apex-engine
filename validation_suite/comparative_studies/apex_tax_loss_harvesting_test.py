"""
apex_tax_loss_harvesting_test.py — Quantifica il "tax alpha" di un ribasket
consapevole delle minusvalenze (tax-loss harvesting), richiesto dall'utente
come alternativa che migliora il netto-tasse SENZA toccare CAGR lordo ne'
rischio (a differenza di leva/short, gia' quantificati e scartati sopra).

Idea: `select_low_beta_basket` ruota i titoli SOLO per rank di beta. Un
titolo nella "zona cuscinetto" (rank 15-19 su un top_n=15/buffer_rank=20 —
verrebbe tenuto per isteresi) non guarda MAI se e' in perdita o in
guadagno. A parita' di beta, vendere prima chi e' in perdita (minusvalenza
compensabile, REDDITO_DIVERSO) e tenere piu' a lungo chi e' in guadagno
(differire la tassa) non cambia l'esposizione al mercato — sposta solo
QUANDO si paga il fisco.

Variante HARVEST testata (conservativa, non la piu' aggressiva possibile):
tra gli incumbent nella zona cuscinetto (rank 15-19) che la regola normale
terrebbe per isteresi, chi e' in MINUSVALENZA non realizzata viene comunque
venduto (harvest accelerato); chi e' in PLUSVALENZA segue la regola
normale (tenuto, tassa differita — nessun cambiamento li'). I titoli nel
vero top-15 per beta non vengono mai toccati da questa regola (restano per
merito, non per fisco). Una versione piu' aggressiva (harvest anche dentro
il top-15 con sostituto quasi-equivalente) e' possibile ma non testata qui
— turnover/costo aggiuntivo da giustificare a parte.

Semplificazione dichiarata: ciascuno slot del basket rappresenta sempre
esattamente 1/n_basket del NAV della sola sleeve Equity (stessa convenzione
gia' implicita nel resto del progetto, che calcola il rendimento lordo
della sleeve come media semplice dei rendimenti settimanali dei titoli
detenuti — equivalente a un ribilanciamento a pesi uguali implicito). La
tassa e' simulata SOLO sulla sleeve Equity in isolamento (non condivide il
pool di minusvalenze REDDITO_DIVERSO con Crypto come fa la produzione
reale — limite dichiarato, isola l'effetto per non confondere risultati).
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
from apex_dashboard_stat_regeneration import spliced_price_index, SPLICE_SPEC, BASKET_SELECTION_FROM_YEAR
from sector_cap_grid_test import SECTOR_MAP_FILE
from metrics import cagr as _cagr, sharpe as _sharpe, max_drawdown as _max_drawdown, calmar as _calmar
from statistical_validation import block_bootstrap_ci

TEST_START = "2020-09-30"
TAX_RATE = 0.26


def _beta_ranked_syms(eq_data: Dict[str, pd.DataFrame], spy_wc: pd.Series, lookback: int) -> List[str]:
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
    scored.sort(key=lambda t: t[1])
    return [s for s, _ in scored]


def _decide_basket(ranked_syms: List[str], prev_tickers: Optional[set], sector_of: dict,
                    at_loss: Optional[Dict[str, bool]], harvest: bool,
                    top_n=V2_EQUITY_TOP_N, buffer_rank=V2_EQUITY_BUFFER_RANK, max_per_sector=V2_MAX_PER_SECTOR) -> List[str]:
    rank_of = {sym: i for i, sym in enumerate(ranked_syms)}
    sector_count: Dict[str, int] = {}
    result: List[str] = []
    at_loss = at_loss or {}

    def sector_ok(sym):
        s = sector_of.get(sym)
        return True if s is None else sector_count.get(s, 0) < max_per_sector

    def add(sym):
        result.append(sym)
        s = sector_of.get(sym)
        if s is not None:
            sector_count[s] = sector_count.get(s, 0) + 1

    prev_tickers = prev_tickers or set()
    # incumbenti in zona cuscinetto (rank < buffer_rank): tenuti per isteresi, TRANNE
    # se harvest=True e sono in minusvalenza non realizzata -> venduti per raccogliere
    # la perdita anche se l'isteresi li avrebbe tenuti.
    incumbents = sorted([s for s in prev_tickers if rank_of.get(s, 10**9) < buffer_rank], key=lambda s: rank_of.get(s, 10**9))
    for sym in incumbents:
        if len(result) >= top_n:
            break
        if harvest and at_loss.get(sym, False):
            continue  # raccolta minusvalenza: non rinnovato per isteresi, venduto sotto
        if sector_ok(sym):
            add(sym)
    for sym in ranked_syms:
        if len(result) >= top_n:
            break
        if sym not in result and sector_ok(sym):
            add(sym)
    return result[:top_n]


def run_variant(weeks, spy_price, stock_prices, stock_rets, snapshots, sector_of, harvest: bool):
    n_basket = V2_EQUITY_TOP_N
    prev_tickers = None
    current_basket: List[str] = []
    entry_price: Dict[str, float] = {}
    nav = 1.0
    loss_pool = 0.0
    gross_rets, net_rets, tax_events = [], [], []

    for i, wk in enumerate(weeks):
        gross_ret = float(np.mean([stock_rets[t].loc[wk] for t in current_basket if t in stock_rets and wk in stock_rets[t].index])) if current_basket else 0.0
        gross_rets.append(gross_ret)
        nav_after_market = nav * (1 + gross_ret)

        is_month_end = (i + 1 >= len(weeks)) or (weeks[i + 1].month != wk.month)
        tax_due = 0.0
        if is_month_end and wk.month in (3, 6, 9, 12):
            eligible = eligible_universe_for_year(snapshots, wk.year)
            eq_data = {t: build_ohlc_like(p.loc[:wk]) for t, p in stock_prices.items() if t in eligible}
            spy_data_upto = build_ohlc_like(spy_price.loc[:wk])
            ranked_syms = _beta_ranked_syms(eq_data, _weekly_close(spy_data_upto), V2_EQUITY_BETA_LOOKBACK)
            if ranked_syms:
                cur_price = {t: float(stock_prices[t].loc[:wk].iloc[-1]) for t in current_basket if t in stock_prices}
                at_loss = {t: (cur_price.get(t, entry_price.get(t, 1.0)) < entry_price.get(t, 1e18)) for t in current_basket}
                new_basket = _decide_basket(ranked_syms, prev_tickers, sector_of, at_loss, harvest)

                dropped = set(current_basket) - set(new_basket)
                for sym in dropped:
                    px_exit = cur_price.get(sym)
                    px_entry = entry_price.get(sym)
                    if px_exit is None or px_entry is None:
                        continue
                    gain_frac = px_exit / px_entry - 1.0
                    gain_eur = gain_frac * (nav_after_market / n_basket)
                    if gain_eur > 0:
                        offset = min(gain_eur, loss_pool)
                        loss_pool -= offset
                        tax_due += (gain_eur - offset) * TAX_RATE
                    else:
                        loss_pool += -gain_eur

                for sym in new_basket:
                    if sym not in current_basket:
                        entry_price[sym] = float(stock_prices[sym].loc[:wk].iloc[-1])

                current_basket = new_basket
                prev_tickers = set(current_basket)

        nav_after_tax = nav_after_market - tax_due
        net_rets.append(nav_after_tax / nav - 1.0)
        tax_events.append(tax_due)
        nav = nav_after_tax

    idx = pd.DatetimeIndex(weeks)
    return pd.Series(gross_rets, index=idx), pd.Series(net_rets, index=idx), pd.Series(tax_events, index=idx)


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

    print(f"Campione: {len(weeks)} settimane, {weeks[0].date()} -> {weeks[-1].date()} (limite 2012+)")

    print("[*] Variante BASELINE (nessun tax-loss harvesting)...")
    g_base, n_base, tax_base = run_variant(weeks, spy_price, stock_prices, stock_rets, snapshots, sector_of, harvest=False)
    print("[*] Variante HARVEST (raccolta minusvalenze nella zona cuscinetto)...")
    g_harv, n_harv, tax_harv = run_variant(weeks, spy_price, stock_prices, stock_rets, snapshots, sector_of, harvest=True)

    idx = pd.DatetimeIndex(weeks)
    gm_base = (1 + g_base).resample("ME").apply(lambda x: x.prod() - 1)
    nm_base = (1 + n_base).resample("ME").apply(lambda x: x.prod() - 1)
    gm_harv = (1 + g_harv).resample("ME").apply(lambda x: x.prod() - 1)
    nm_harv = (1 + n_harv).resample("ME").apply(lambda x: x.prod() - 1)

    for label, g, n in [("BASELINE", gm_base, nm_base), ("HARVEST", gm_harv, nm_harv)]:
        print(f"\n--- {label} (intero campione 2012-2026, {len(g)} mesi) ---")
        print(f"  CAGR lordo: {_cagr(g,12)*100:+7.2f}%   CAGR netto: {_cagr(n,12)*100:+7.2f}%   drag fiscale: {(_cagr(g,12)-_cagr(n,12))*100:5.2f}pp")
        print(f"  Sharpe lordo: {_sharpe(g,periods_per_year=12):6.3f}   MaxDD lordo: {_max_drawdown(g)*100:7.2f}%   Calmar: {_calmar(g,12):6.3f}")
        g_t, n_t = g.loc[TEST_START:], n.loc[TEST_START:]
        print(f"  [TEST 2020-09+] CAGR lordo: {_cagr(g_t,12)*100:+7.2f}%   CAGR netto: {_cagr(n_t,12)*100:+7.2f}%   drag: {(_cagr(g_t,12)-_cagr(n_t,12))*100:5.2f}pp")

    print(f"\nEventi fiscali totali (somma tasse pagate, index=1.0 iniziale):")
    print(f"  BASELINE: {tax_base.sum():.4f}   HARVEST: {tax_harv.sum():.4f}")

    diff_gross = (gm_harv - gm_base).dropna()
    diff_net = (nm_harv - nm_base).dropna()
    print(f"\nDifferenza HARVEST - BASELINE, media mensile annualizzata:")
    print(f"  Lordo: {diff_gross.mean()*12*100:+.3f}pp/anno (deve essere ~0: stesso beta-merit, solo timing fiscale diverso)")
    lo, hi = block_bootstrap_ci(diff_net.dropna().values, lambda r: pd.Series(r).mean() * 12 * 100, block_size=6, ci=0.90, seed=42)
    mean_net_diff = diff_net.mean() * 12 * 100
    print(f"  Netto: {mean_net_diff:+.3f}pp/anno  CI90 [{lo:+.3f}, {hi:+.3f}] ({'ESCLUDE' if lo*hi>0 else 'include'} lo zero)")


if __name__ == "__main__":
    main()
