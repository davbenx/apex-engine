"""
apex_dashboard_stat_regeneration.py — Rigenera apex_monthly_returns_extended.csv
/ _gross.csv (radice del repo) con select_low_beta_basket, dopo la scoperta
dell'utente che le card statistiche del dashboard (get_apex_metrics/
get_combined_dual_engine_metrics in portfolio_manager.py) sono numeri statici
fermi al 3 settembre — prima del passaggio a low-beta di questa sessione — e
la "philosophy" mostrava ancora testualmente "Low-Vol".

Non e' un tentativo di riprodurre bit-per-bit la pipeline esterna originale
(research/, non in questo repo — verificato: mai committata in nessun branch,
esclusa da .gitignore, non presente nemmeno su questa macchina sandbox,
quindi irraggiungibile da questa sessione) — l'utente ha scelto esplicitamente
"rigenero io in-repo" sapendo che la metodologia non sarebbe identica.

Estensione richiesta esplicitamente dall'utente ("vai il piu' indietro
possibile usando i migliori proxy") rispetto alla prima versione di questo
script (che si fermava a 2014-11, la finestra del file originale):
- **Equities**: VFINX (Vanguard 500 Index Fund, total return con dividendi,
  storico dal 1986-09) raccordato con SPY dal 1993-01 (inception reale ETF).
- **Bonds**: VUSTX (Vanguard Long-Term Treasury, total return, dal 1986-09)
  raccordato con IEF dal 2002-08. Duration diversa (VUSTX ~lunga, IEF 7-10y)
  — approssimazione dichiarata, non lo stesso profilo di tasso esatto.
- **Gold**: GC=F (futures oro COMEX continuo, dal 2000-08) raccordato con GLD
  dal 2004-11. Scartati i proxy piu' vecchi disponibili (fondi/indici di
  azioni minerarie aurifere, es. ^XAU dal 1983, FKRCX dal 1980): espongono a
  rischio azionario/operativo, non al prezzo dell'oro fisico — avrebbero
  contaminato la classe "Gold" con beta equity, il problema che questa classe
  esiste apposta per evitare.
- **Crypto**: BTC-USD reale dal 2014-09, NESSUN proxy prima — Bitcoin non
  aveva mercati liquidi affidabili prima (dati Mt. Gox 2010-2013 inattendibili
  e non disponibili qui). Sotto quella data la classe resta a 0% (dati
  insufficienti, comportamento nativo di compute_v2_macro_signal).
Raccordo per RENDIMENTO (concatenazione di rendimenti settimanali proxy/reale
al punto di passaggio), non per livello di prezzo grezzo — nessun salto/
discontinuita' artificiale nella serie.

**Vincolo di onesta' point-in-time**: la selezione a livello di SINGOLO
TITOLO (select_low_beta_basket) resta limitata al 2012+ (limite dei dati di
composizione S&P 500 point-in-time, rate-limit Wikipedia — vedi
apex_stocks_vs_etf_backtest.py). PRIMA del 2012 usare comunque la selezione
per-titolo userebbe una composizione dell'indice non nota all'epoca (look-
ahead bias) — quindi PRIMA del 2012 lo slot Equity, quando attivo, rende
come l'INDICE PROXY stesso (VFINX/SPY), non come un basket selezionato;
DAL 2012 in poi, selezione reale low-beta point-in-time, nessun cambiamento
rispetto alla produzione.

Il resto della metodologia e' identico alla prima versione (motore Apex 4
classi gia' validato in questa sessione — compute_v2_macro_signal 50%/22%,
V2_EQUITY_BETA_LOOKBACK=26, buffer/settore invariati; GROSS = rendimento
pesato grezzo, nessuna tassa/costo; NETTO = apply_italian_tax + costi
realistici; ricampionato mensile, composto).

L'utente ha inoltre chiesto che grafici/NAV/metriche mostrate siano al LORDO
di tasse — gia' la convenzione esistente del resto della dashboard (vedi
commento "lordo-primario/netto-stimato-secondario" in
portfolio_manager.load_combined_monthly_history): questo script continua a
produrre ANCHE la serie netta (usata per le cifre "netto stimato" secondarie
mostrate accanto al lordo), ma la serie primaria/di riferimento resta la
GROSS.
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

from apex_v2_engine import compute_v2_macro_signal, select_low_beta_basket, select_low_vol_basket, V2_CLASS_TICKER
from metrics import (
    cagr as _cagr, sharpe as _sharpe, max_drawdown as _max_drawdown, calmar as _calmar,
    sortino_ratio, ulcer_index,
)
from tax_engine import apply_italian_tax as _apply_italian_tax
from apex_stocks_vs_etf_backtest import (
    DATA_DIR, load_weekly_sp500, load_pointintime_snapshots,
    eligible_universe_for_year, build_ohlc_like,
)
from sector_cap_grid_test import SECTOR_MAP_FILE

EXT_DATA_DIR = Path(__file__).parent / "apex_macro_extended_data"
SLICE_END = "2026-08-31"
BASKET_SELECTION_FROM_YEAR = 2012  # limite dati point-in-time S&P 500 — vedi docstring
# Stesso 10bps per titolo usato da backend.py:update_portfolio (produzione live) e da
# cost_bps_map["Equity"] sotto — unica fonte per evitare la stessa incoerenza segnalata
# dall'audit qualitativo tra i driver di backtest (concern #2, vedi README).
BASKET_STOCK_COST_BPS = 0.0010

# (proxy_file, real_file, real_start) per classe — raccordo per RENDIMENTO
SPLICE_SPEC = {
    "SPY": ("VFINX_weekly.csv", "SPY_weekly.csv", "1993-01-29"),
    "IEF": ("VUSTX_weekly.csv", "IEF_weekly.csv", "2002-08-02"),
    "GLD": ("GC_F_weekly.csv", "GLD_weekly.csv", "2004-11-19"),
    "BTC-USD": (None, "BTC_USD_weekly.csv", None),
}


def _load_ext(fname: str) -> pd.Series:
    return pd.read_csv(EXT_DATA_DIR / fname, index_col=0, parse_dates=True).iloc[:, 0]


def spliced_return(proxy_file, real_file, real_start) -> pd.Series:
    """Concatena rendimenti settimanali PROXY (prima di real_start) e REALI
    (da real_start in poi) — nessuna discontinuita' di livello prezzo, perche'
    si raccordano rendimenti, non prezzi grezzi con scale diverse."""
    real = _load_ext(real_file)
    real_ret = real.pct_change().dropna()
    if proxy_file is None:
        return real_ret
    proxy = _load_ext(proxy_file)
    proxy_ret = proxy.pct_change().dropna()
    cutoff = pd.Timestamp(real_start)
    return pd.concat([proxy_ret.loc[:cutoff].iloc[:-1], real_ret.loc[cutoff:]]).sort_index()


def spliced_price_index(proxy_file, real_file, real_start) -> pd.Series:
    """Serie di prezzo sintetica Base=100 costruita dal rendimento raccordato
    (spliced_return) — serve a compute_v2_macro_signal, che lavora su livelli
    di prezzo (MA/distanza), non su rendimenti."""
    ret = spliced_return(proxy_file, real_file, real_start)
    return 100.0 * (1 + ret).cumprod()


def run_full_backtest(sector_of: dict, kelly_fraction: float | None = None,
                       vol_target: float | None = None, base_weight_per_class: float | None = None,
                       return_components: bool = False, use_low_vol_basket: bool = False):
    """kelly_fraction/vol_target/base_weight_per_class=None (default) usano il
    default di produzione di compute_v2_macro_signal (rispettivamente
    V2_KELLY_FRACTION=0.25, V2_VOL_TARGET=0.22, 0.50 — il sistema ATTUALE).
    kelly_fraction=0.0 riproduce esattamente il sistema PRECEDENTE (§8.28,
    senza Kelly — vedi apex_kelly_vs_flat_v2_comparison.py). vol_target e
    base_weight_per_class esposti per la griglia di sensibilità dei
    parametri richiesta dall'utente (vedi
    apex_v2_sensitivity_grid.py) — non toccano nulla se lasciati a None.

    use_low_vol_basket=True sostituisce select_low_beta_basket (default,
    criterio di produzione ATTUALE dal §8.29) con select_low_vol_basket (il
    criterio PRECEDENTE) — combinato con kelly_fraction=0.0 riproduce la
    versione "v2" completa (basket low-vol + target-vol fisso, nessun
    Kelly) sulla stessa pipeline dati corretta (survivorship bias, same-bar
    leak, costo turnover) usata per la serie canonica attuale — richiesto
    dall'utente per un confronto diretto v2-vs-v3 non contaminato da bug
    ormai corretti solo su un lato del confronto."""
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

    macro_prices = {ticker: spliced_price_index(*SPLICE_SPEC[ticker]) for ticker in V2_CLASS_TICKER.values()}
    equity_index_ret = spliced_return(*SPLICE_SPEC["SPY"])  # rendimento indice puro, usato come proxy pre-2012 per lo slot Equity

    # Solo SPY(proxy)/IEF(proxy) determinano l'inizio del walk-forward (VFINX/
    # VUSTX dal 1986-09): Gold (proxy dal 2000-08) e Crypto (dal 2014-09)
    # contribuiscono 0% finche' non hanno 40 settimane proprie di storico,
    # gestito nativamente da compute_v2_macro_signal — NON si intersecano i 4
    # indici sull'ultimo ad iniziare, altrimenti si perderebbero ~14 anni di
    # storia Equity/Bonds pre-Gold-proxy/pre-BTC.
    common_index = macro_prices["SPY"].index.intersection(macro_prices["IEF"].index)
    weeks = list(common_index.sort_values())
    n = len(weeks)

    ief_ret = spliced_return(*SPLICE_SPEC["IEF"])
    gld_ret = spliced_return(*SPLICE_SPEC["GLD"])
    btc_ret = spliced_return(*SPLICE_SPEC["BTC-USD"])

    hysteresis_state, prev_basket_tickers, current_basket = None, None, []
    locked_alloc = None
    macro_alloc_history, equity_return_basket, basket_turnover_cost = [], [], []

    MIN_HISTORY = 40
    for i, wk in enumerate(weeks):
        if i < MIN_HISTORY:
            macro_alloc_history.append(None)
            equity_return_basket.append(0.0)
            basket_turnover_cost.append(0.0)
            continue

        b_data = {}
        for c, ticker in V2_CLASS_TICKER.items():
            px = macro_prices[ticker]
            px_upto = px.loc[:wk]
            b_data[ticker] = build_ohlc_like(px_upto) if len(px_upto) > 0 else pd.DataFrame()
        signal_kwargs = {}
        if kelly_fraction is not None:
            signal_kwargs["kelly_fraction"] = kelly_fraction
        if vol_target is not None:
            signal_kwargs["vol_target"] = vol_target
        if base_weight_per_class is not None:
            signal_kwargs["base_weight_per_class"] = base_weight_per_class
        alloc, hysteresis_state, _debug = compute_v2_macro_signal(b_data, prev_hysteresis_state=hysteresis_state, **signal_kwargs)
        is_month_end = (i + 1 >= n) or (weeks[i + 1].month != wk.month)
        if locked_alloc is None:
            locked_alloc = alloc
        macro_alloc_history.append(dict(locked_alloc))
        if is_month_end:
            locked_alloc = alloc

        def rebuild_basket():
            eligible = eligible_universe_for_year(snapshots, wk.year)
            eq_data = {t: build_ohlc_like(p.loc[:wk]) for t, p in stock_prices.items() if t in eligible}
            if use_low_vol_basket:
                basket = select_low_vol_basket(eq_data, prev_tickers=prev_basket_tickers, sector_of=sector_of)
            else:
                spy_data_upto = build_ohlc_like(macro_prices["SPY"].loc[:wk])
                basket = select_low_beta_basket(eq_data, spy_data_upto, prev_tickers=prev_basket_tickers, sector_of=sector_of)
            return [b["Ticker"] for b in basket]

        basket_turnover_cost.append(0.0)
        stock_selection_era = wk.year >= BASKET_SELECTION_FROM_YEAR

        # 1. Il rendimento di QUESTA settimana usa il basket cosi' com'era PRIMA di
        #    qualunque ribasket deciso questa stessa settimana — mai il basket appena
        #    ricostruito con beta calcolata fino a QUESTA settimana inclusa, che
        #    sarebbe una fuga same-bar (il basket "sa" gia' il proprio rendimento
        #    della settimana in cui entra — concern d'audit #2, vedi README). Il
        #    nuovo basket, quando questa settimana lo aggiorna, comincia a rendere
        #    dalla settimana SUCCESSIVA (vedi punto 2 sotto).
        if alloc.get("Equities", 0) <= 0:
            basket_ret = 0.0
        elif stock_selection_era:
            basket_ret = float(np.mean([stock_rets[t].loc[wk] for t in current_basket if t in stock_rets and wk in stock_rets[t].index])) if current_basket else 0.0
        else:
            # Prima del 2012: rendimento dell'indice proxy stesso (VFINX/SPY),
            # non della selezione per-titolo — vedi docstring del modulo.
            basket_ret = float(equity_index_ret.loc[wk]) if wk in equity_index_ret.index else 0.0
        equity_return_basket.append(basket_ret)

        # 2. ORA si decide il basket per la settimana SUCCESSIVA (la beta usa dati
        #    fino a wk incluso, ma il basket risultante conta solo a partire dal
        #    prossimo rendimento, mai da quello di wk stessa appena registrato sopra).
        if alloc.get("Equities", 0) <= 0:
            current_basket = []
            prev_basket_tickers = None
        elif not stock_selection_era:
            current_basket = []  # sotto il 2012: nessuna composizione S&P point-in-time nota, niente selezione per-titolo (look-ahead altrimenti)
        elif not current_basket:
            # Primo ingresso nello slot Equity (da 0% a >0%): il costo e' gia' interamente
            # coperto dal turnover di CLASSE sotto (weight_change su "Equity" salta da 0 al
            # peso pieno, a 10bps sull'intero nozionale — stesso totale che pagare 10bps su
            # ciascuno dei 15 titoli separatamente, la cost e' lineare nel nozionale
            # scambiato). Nessun costo aggiuntivo qui, altrimenti sarebbe un doppio conteggio.
            current_basket = rebuild_basket()
            prev_basket_tickers = set(current_basket)
        elif is_month_end and wk.month in (3, 6, 9, 12):
            # Ribasket trimestrale A PARITA' (circa) di peso di classe: qui il turnover di
            # CLASSE sopra non vede nulla (il peso "Equity" aggregato non cambia), ma sotto
            # il cofano si vendono i titoli usciti e si comprano quelli entrati — il costo
            # mancante segnalato dall'audit qualitativo (concern #4, README). Charge one-time
            # sui soli titoli EFFETTIVAMENTE scambiati (mai sull'intero basket per un turnover
            # parziale), stessa convenzione "solo il delta" di backend.py:update_portfolio.
            new_basket = rebuild_basket()
            n_swapped = len(set(new_basket) - prev_basket_tickers)
            if n_swapped > 0 and len(new_basket) > 0:
                eq_frac_this_week = macro_alloc_history[i]["Equities"] / 100.0
                basket_turnover_cost[i] = n_swapped * 2 * (eq_frac_this_week / len(new_basket)) * BASKET_STOCK_COST_BPS
            current_basket = new_basket
            prev_basket_tickers = set(current_basket)

    valid_from = MIN_HISTORY
    idx = weeks[valid_from:]

    def alloc_frac(cls):
        return pd.Series([macro_alloc_history[i].get(cls, 0.0) / 100.0 for i in range(valid_from, n)], index=idx)

    weights_df = pd.DataFrame({"Equity": alloc_frac("Equities"), "Bonds": alloc_frac("Bonds"),
                                "Gold": alloc_frac("Gold"), "Crypto": alloc_frac("Crypto")})
    returns_df = pd.DataFrame({
        "Equity": pd.Series(equity_return_basket[valid_from:], index=idx),
        "Bonds": ief_ret.reindex(idx).fillna(0.0),
        "Gold": gld_ret.reindex(idx).fillna(0.0),
        "Crypto": btc_ret.reindex(idx).fillna(0.0),
    })
    tax_types = {"Equity": "REDDITO_DIVERSO", "Bonds": "REDDITO_CAPITALE", "Gold": "REDDITO_DIVERSO", "Crypto": "REDDITO_DIVERSO"}

    port_gross = (returns_df * weights_df).sum(axis=1)
    weight_change = weights_df.diff().abs().sum(axis=1).fillna(0.0)
    cost_bps_map = {"Equity": BASKET_STOCK_COST_BPS, "Bonds": 0.0008, "Gold": 0.0010, "Crypto": 0.0010}
    basket_turnover_series = pd.Series(basket_turnover_cost[valid_from:], index=idx)
    # weight_change*media_bps copre il turnover di CLASSE (quanto cambia il peso aggregato
    # Equity/Bonds/Gold/Crypto); basket_turnover_series copre SEPARATAMENTE il turnover
    # interno del basket di 15 titoli (rotazione trimestrale a parita' di peso di classe —
    # concern #4 dell'audit, invisibile al turnover di classe per costruzione).
    cost_drag = weight_change * np.mean(list(cost_bps_map.values())) + basket_turnover_series
    port_gross_after_costs = port_gross - cost_drag
    port_net = _apply_italian_tax(returns_df, weights_df, tax_types=tax_types)
    port_net_after_costs = port_net - cost_drag

    if return_components:
        # Esposto per lo stress test di costo/slippage (vedi
        # apex_cost_stress_test.py): permette di ri-applicare un
        # cost_multiplier diverso SENZA ripetere il loop settimanale
        # costoso — weights_df/returns_df/weight_change non dipendono dal
        # coefficiente di costo, solo il passo finale (cost_drag) lo usa.
        return port_gross_after_costs, port_net_after_costs, {
            "weights_df": weights_df, "returns_df": returns_df, "weight_change": weight_change,
            "port_gross": port_gross, "port_net": port_net, "tax_types": tax_types,
            "cost_bps_map": cost_bps_map, "basket_turnover_series": basket_turnover_series,
        }
    return port_gross_after_costs, port_net_after_costs


def to_monthly(weekly_ret: pd.Series) -> pd.Series:
    return (1 + weekly_ret).resample("ME").apply(lambda x: x.prod() - 1.0)


def main():
    sector_of = json.load(open(SECTOR_MAP_FILE))
    print("[*] Backtest completo Apex 4-classi con proxy estesi (VFINX/VUSTX/GC=F dal 1986-2000) + select_low_beta_basket dal 2012...")
    gross_w, net_w = run_full_backtest(sector_of)

    gross_m = to_monthly(gross_w).loc[:SLICE_END]
    net_m = to_monthly(net_w).loc[:SLICE_END]
    print(f"Serie mensile: {len(gross_m)} mesi, {gross_m.index.min().date()} -> {gross_m.index.max().date()}")

    gross_out = REPO_ROOT / "apex_monthly_returns_extended_gross.csv"
    net_out = REPO_ROOT / "apex_monthly_returns_extended.csv"
    gross_m.to_csv(gross_out)
    net_m.to_csv(net_out)
    print(f"[*] Salvati: {gross_out.name}, {net_out.name}")

    TEST_START = "2020-09-30"
    gross_test = gross_m.loc[TEST_START:]
    net_test = net_m.loc[TEST_START:]
    print(f"\nPeriodo TEST: {len(gross_test)} mesi, {gross_test.index.min().date()} -> {gross_test.index.max().date()}")

    stats = {
        "cagr_net": round(_cagr(net_test, 12), 4),
        "cagr_gross": round(_cagr(gross_test, 12), 4),
        "volatility": round(float(gross_test.std() * np.sqrt(12)), 4),
        "sharpe": round(_sharpe(gross_test, periods_per_year=12), 3),
        "sortino": round(sortino_ratio(gross_test, periods_per_year=12), 3),
        "max_drawdown": round(_max_drawdown(gross_test), 4),
        "calmar": round(_calmar(gross_test, 12), 3),
        "ulcer_index": round(ulcer_index(gross_test), 2),
        "volatility_netto_stimato": round(float(net_test.std() * np.sqrt(12)), 4),
        "sharpe_netto_stimato": round(_sharpe(net_test, periods_per_year=12), 3),
        "sortino_netto_stimato": round(sortino_ratio(net_test, periods_per_year=12), 3),
        "max_drawdown_netto_stimato": round(_max_drawdown(net_test), 4),
        "calmar_netto_stimato": round(_calmar(net_test, 12), 3),
    }
    print("\nNuove statistiche get_apex_metrics() (periodo TEST, 72 mesi attesi):")
    for k, v in stats.items():
        print(f"  {k}: {v}")

    # --- Combinato 50/50 con Convex (INVARIATO — Convex non usa selezione
    # azionaria beta/vol, il basket switch di Apex non lo tocca) ---
    cx_path = REPO_ROOT / "convex_monthly_returns.csv"
    if cx_path.exists():
        cx = pd.read_csv(cx_path, index_col=0, parse_dates=True).iloc[:, 0]
        common = gross_test.index.intersection(cx.index)
        combined_gross = 0.5 * gross_test.reindex(common) + 0.5 * cx.reindex(common)
        # cagr_net combinato = media pesata delle stime nette dei due componenti,
        # stessa convenzione documentata in get_combined_dual_engine_metrics():
        # Apex usa la sua serie netta reale (tasse italiane modellate), Convex
        # l'haircut fisso 26% sul CAGR lordo (approssimazione dichiarata, invariata).
        combined_cagr_net = 0.5 * _cagr(net_test.reindex(common), 12) + 0.5 * (_cagr(cx.reindex(common), 12) * (1 - 0.26))
        print(f"\nCombinato 50/50 Apex(nuovo)/Convex(invariato), {len(common)} mesi comuni:")
        print(f"  cagr_gross: {round(_cagr(combined_gross, 12), 4)}")
        print(f"  cagr_net (stima): {round(combined_cagr_net, 4)}")
        print(f"  volatility: {round(float(combined_gross.std() * np.sqrt(12)), 4)}")
        print(f"  sharpe: {round(_sharpe(combined_gross, periods_per_year=12), 3)}")
        print(f"  sortino: {round(sortino_ratio(combined_gross, periods_per_year=12), 3)}")
        print(f"  max_drawdown: {round(_max_drawdown(combined_gross), 4)}")
        print(f"  calmar: {round(_calmar(combined_gross, 12), 3)}")
        print(f"  ulcer_index: {round(ulcer_index(combined_gross), 2)}")
        print(f"  correlation: {round(float(gross_test.reindex(common).corr(cx.reindex(common))), 3)}")
    else:
        print("\n[!] convex_monthly_returns.csv non trovato, salto il ricalcolo del combinato.")


if __name__ == "__main__":
    main()
