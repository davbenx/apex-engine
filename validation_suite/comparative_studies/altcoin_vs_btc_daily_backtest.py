"""
altcoin_vs_btc_daily_backtest.py — Seguito di altcoin_vs_btc_backtest.py
(settimanale, universo fisso ETH/SOL) dopo due obiezioni dell'utente:

1. "un segnale settimanale puo' essere troppo lento" per i regimi crypto —
   qui la decisione (non necessariamente il trade) e' valutata OGNI GIORNO.
2. l'universo altcoin era scelto a memoria (ETH/SOL), non point-in-time —
   qui usa validation_suite/pointintime_data/cmc_altcoin_pointintime_snapshots.json
   (28 trimestri reali 2019-2026, classifica CoinMarketCap storica via
   Wayback Machine) per determinare quali erano davvero le "top alt" in
   ciascun trimestre, escludendo BTC/stablecoin/wrapped token.

Domanda dell'utente: c'e' una formula (picking altseason, o uno switch
BTC->altcoin quando BTC "rallenta") che sovraperforma BTC buy&hold a
rischio pari o minore, al netto di tasse italiane (26%, redditi diversi,
pool condiviso) e fee Kraken (taker 0.26%)?

Turnover: le decisioni sono discrete (un regime, o il vincitore di
momentum) e vengono APPLICATE solo quando la decisione cambia rispetto al
giorno prima — non un ribilanciamento forzato ogni giorno. E' cosi' che un
segnale "valutato ogni giorno" resta a basso turnover: controlla spesso,
non necessariamente tradare spesso.

Validazione istituzionale (non solo un numero puntuale): PBO-CSCV su tutti
i candidati (stesso periodo, stesso universo — il caso d'uso naturale per
cui PBO esiste), DSR sul migliore con n_trials = numero di candidati
REALMENTE provati in questo script (conteggio onesto, non stimato), block
bootstrap CI sullo Sharpe del migliore, e lo stesso controllo di
concentrazione per episodi gia' usato nella versione settimanale.
"""

from __future__ import annotations
import json
import sys
import time
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "framework"))
from metrics import cagr, sharpe, max_drawdown, calmar
from tax_engine import apply_italian_tax
from statistical_validation import deflated_sharpe_ratio, pbo_cscv, block_bootstrap_ci

DATA_DIR = Path(__file__).parent / "altcoin_daily_data"  # rigenerabile, non tracciato in git (.gitignore)
POINTINTIME_FILE = Path(__file__).resolve().parents[1] / "pointintime_data" / "cmc_altcoin_pointintime_snapshots.json"
KRAKEN_TAKER_FEE = 0.0026
PERIODS_PER_YEAR = 365  # crypto tradano 24/7, non 252 come le borse azionarie

STABLES = {"USDT", "USDC", "DAI", "BUSD", "TUSD", "USDP", "GUSD", "FRAX", "USDD",
           "USTC", "UST", "PAX", "SUSD", "LUSD", "FDUSD", "PYUSD", "EURT", "USDE"}
WRAPPED = {"WBTC", "WETH", "STETH", "WSTETH", "RETH", "CBETH", "WBETH", "BETH", "HBTC", "RENBTC"}

# Universo fetchabile: BTC + ogni moneta mai apparsa nella top-5 alt (ex BTC/stable/
# wrapped) in uno qualsiasi dei 28 trimestri point-in-time. Alcune hanno storico
# corto su Yahoo (SOL da 2020-04, DOT/TON da 2020-08) — range esplicito lungo
# ("8y") per le altre, "max" per queste ultime (il loro storico reale e' < 10
# anni, non rischia la coercizione mensile di Yahoo su span lunghi).
LONG_HISTORY = ["BTC-USD", "ETH-USD", "XRP-USD", "BCH-USD", "LTC-USD", "EOS-USD",
                "BSV-USD", "BNB-USD", "ADA-USD", "DOGE-USD", "LINK-USD", "TRX-USD"]
SHORT_HISTORY = ["SOL-USD", "DOT-USD", "TON-USD"]
ALL_TICKERS = LONG_HISTORY + SHORT_HISTORY


def _fetch_daily_adj(ticker: str, rng: str) -> pd.Series:
    url = f"https://query2.finance.yahoo.com/v8/finance/chart/{ticker}?range={rng}&interval=1d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    res = json.loads(urllib.request.urlopen(req, timeout=15).read().decode())
    result = res["chart"]["result"][0]
    ts = pd.to_datetime(result["timestamp"], unit="s").normalize()
    adj = result["indicators"]["adjclose"][0]["adjclose"]
    return pd.Series(adj, index=ts).dropna()


def fetch_all_price_data() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    for t in LONG_HISTORY:
        _fetch_daily_adj(t, "8y").to_csv(DATA_DIR / f"{t.replace('-', '_')}_daily.csv")
        time.sleep(0.2)
    for t in SHORT_HISTORY:
        _fetch_daily_adj(t, "max").to_csv(DATA_DIR / f"{t.replace('-', '_')}_daily.csv")
        time.sleep(0.2)


def load_daily(ticker: str) -> pd.Series:
    return pd.read_csv(DATA_DIR / f"{ticker.replace('-', '_')}_daily.csv", index_col=0, parse_dates=True).iloc[:, 0]


def load_pointintime_top_alts(top_n: int) -> dict:
    """{data_snapshot: [simboli top_n alt, escl. BTC/stable/wrapped]}, ordinato per data."""
    raw = json.load(open(POINTINTIME_FILE))
    out = {}
    for date_key, snap in raw.items():
        coins = [c for c in snap["coins"] if c["symbol"] not in STABLES and c["symbol"] not in WRAPPED and c["symbol"] != "BTC"]
        coins_sorted = sorted(coins, key=lambda c: c["rank"] or 9999)
        out[pd.Timestamp(date_key)] = [c["symbol"] for c in coins_sorted[:top_n]]
    return dict(sorted(out.items()))


def eligible_alts_asof(pointintime_top_alts: dict, day: pd.Timestamp) -> list:
    """Nessun lookahead: usa lo snapshot piu' recente CON data <= day. Prima del
    primo snapshot disponibile (2019-10), usa comunque il primo (fallback,
    stesso principio di eligible_universe_for_year per l'S&P 500)."""
    applicable = [d for d in pointintime_top_alts if d <= day]
    key = max(applicable) if applicable else min(pointintime_top_alts)
    return pointintime_top_alts[key]


def build_candidate_weights(
    rets: pd.DataFrame, pointintime_top_alts: dict, mode: str,
    short_window: int = 20, long_window: int = 60, trail_window: int = 30, vol_window: int = 30,
    trend_window: int = None,
) -> pd.DataFrame:
    """Ritorna un DataFrame di pesi TARGET (uno per colonna in rets.columns),
    un peso per ogni periodo, calcolato SENZA lookahead (decisione del
    periodo t valutata sui dati fino a t, applicata al rendimento di t+1
    tramite lo shift a valle in backtest_strategy). Le decisioni discrete
    vengono "bloccate" (locked_weights) finche' non cambiano, per un
    turnover realistico anche con un segnale controllato ogni periodo.

    *_window sono in NUMERO DI PERIODI della serie `rets` (giorni per la
    versione daily, settimane per la versione weekly costruita riusando
    questa stessa funzione con `rets` settimanale e finestre equivalenti in
    settimane, non lo stesso numero — vedi altcoin_vs_btc_weekly_pointintime_backtest.py)."""
    idx = rets.index
    cols = list(rets.columns)
    trend_window = trend_window if trend_window is not None else long_window
    btc_trail_short = (1 + rets["BTC-USD"]).rolling(short_window).apply(lambda x: x.prod() - 1, raw=False)
    btc_trail_long = (1 + rets["BTC-USD"]).rolling(long_window).apply(lambda x: x.prod() - 1, raw=False)
    trail_alt = {c: (1 + rets[c]).rolling(trail_window).apply(lambda x: x.prod() - 1, raw=False) for c in cols}
    vol_alt = {c: rets[c].rolling(vol_window).std() for c in cols}
    price_idx = {c: (1 + rets[c]).cumprod() for c in cols}
    trend_ma = {c: price_idx[c].rolling(trend_window).mean() for c in cols}
    warmup_short = max(short_window, trail_window)
    warmup_long = max(long_window, trail_window)
    warmup_trend = max(trend_window, trail_window)

    weights_rows = []
    locked = {c: 0.0 for c in cols}
    locked["BTC-USD"] = 1.0
    prev_decision = None

    for i, day in enumerate(idx):
        alts_today = eligible_alts_asof(pointintime_top_alts, day)
        alts_today = [a + "-USD" for a in alts_today if (a + "-USD") in cols]

        if mode == "btc_only":
            decision = ("BTC",)

        elif mode == "regime_altseason":
            if i < warmup_short:
                decision = ("BTC",)
            else:
                btc_r = btc_trail_short.iloc[i]
                alt_r = np.mean([trail_alt[a].iloc[i] for a in alts_today]) if alts_today else -np.inf
                decision = ("ALTS_EQUAL", tuple(alts_today)) if (alt_r > btc_r) else ("BTC",)

        elif mode == "btc_slowdown_switch":
            if i < warmup_long:
                decision = ("BTC",)
            else:
                slowing = btc_trail_short.iloc[i] < btc_trail_long.iloc[i] * 0.5  # ritmo recente sotto meta' del ritmo di fondo
                if slowing and alts_today:
                    best_alt = max(alts_today, key=lambda a: trail_alt[a].iloc[i] if not pd.isna(trail_alt[a].iloc[i]) else -np.inf)
                    decision = ("SINGLE", best_alt)
                else:
                    decision = ("BTC",)

        elif mode == "momentum_rotation":
            if i < warmup_short:
                decision = ("BTC",)
            else:
                pool = ["BTC-USD"] + alts_today
                best = max(pool, key=lambda a: trail_alt[a].iloc[i] if not pd.isna(trail_alt[a].iloc[i]) else -np.inf)
                decision = ("SINGLE", best)

        elif mode == "inverse_vol":
            if i < warmup_short or not alts_today:
                decision = ("BTC",)
            else:
                pool = ["BTC-USD"] + alts_today
                vols = {a: vol_alt[a].iloc[i] for a in pool}
                if any(pd.isna(v) or v <= 1e-9 for v in vols.values()):
                    decision = ("BTC",)
                else:
                    inv = {a: 1 / v for a, v in vols.items()}
                    total = sum(inv.values())
                    decision = ("WEIGHTED", tuple((a, inv[a] / total) for a in pool))

        elif mode == "mean_reversion":
            # Contrarian: scommette sul rimbalzo dell'asset PIU' scaduto (trailing return
            # piu' basso) nel pool — ipotesi opposta al momentum, stessa finestra trail_window.
            if i < warmup_short:
                decision = ("BTC",)
            else:
                pool = ["BTC-USD"] + alts_today
                worst = min(pool, key=lambda a: trail_alt[a].iloc[i] if not pd.isna(trail_alt[a].iloc[i]) else np.inf)
                decision = ("SINGLE", worst)

        elif mode == "low_vol_pick":
            # Diverso da inverse_vol: qui si POSSIEDE SOLO il singolo asset a volatilita'
            # realizzata piu' bassa nel pool, non un blend pesato su tutti.
            if i < warmup_short:
                decision = ("BTC",)
            else:
                pool = ["BTC-USD"] + alts_today
                vols = {a: vol_alt[a].iloc[i] for a in pool}
                valid = {a: v for a, v in vols.items() if not pd.isna(v) and v > 1e-9}
                decision = ("SINGLE", min(valid, key=valid.get)) if valid else ("BTC",)

        elif mode == "trend_following":
            # Filtro di trend PER ASSET (prezzo sopra la propria media mobile a
            # trend_window periodi, non un confronto relativo come momentum/regime):
            # equal-weight su tutti gli asset del pool (BTC incluso) in uptrend; CASH
            # (0% ovunque, non BTC di default) se nessuno lo e' — un vero stato "flat",
            # diverso da tutte le altre modalita' che ripiegano sempre su BTC.
            if i < warmup_trend:
                decision = ("BTC",)
            else:
                pool = ["BTC-USD"] + alts_today
                trending = [a for a in pool if not pd.isna(trend_ma[a].iloc[i]) and price_idx[a].iloc[i] > trend_ma[a].iloc[i]]
                decision = ("ALTS_EQUAL", tuple(trending)) if trending else ("CASH",)
        else:
            raise ValueError(mode)

        if decision != prev_decision:
            locked = {c: 0.0 for c in cols}
            if decision[0] == "BTC":
                locked["BTC-USD"] = 1.0
            elif decision[0] == "SINGLE":
                locked[decision[1]] = 1.0
            elif decision[0] == "ALTS_EQUAL":
                pool = decision[1]
                if pool:
                    for a in pool:
                        locked[a] = 1.0 / len(pool)
                else:
                    locked["BTC-USD"] = 1.0
            elif decision[0] == "WEIGHTED":
                for a, w in decision[1]:
                    locked[a] = w
            prev_decision = decision

        weights_rows.append(dict(locked))

    return pd.DataFrame(weights_rows, index=idx)


def apply_stop_loss_overlay(
    weights_df: pd.DataFrame, rets: pd.DataFrame, stop_threshold: float = -0.15, recovery_asset: str = "BTC-USD",
) -> pd.DataFrame:
    """Overlay applicabile a QUALSIASI weights_df prodotto da build_candidate_weights
    (nessuna logica duplicata per-strategia) — stesso principio di
    kelly_backtest.apply_per_sleeve_stop_loss, qui a livello di intera posizione
    invece che per singola sleeve indipendente.

    Timing (nessun lookahead): weights_df e' nella convenzione PRE-shift (riga t =
    decisione presa a chiusura del periodo t, applicata al rendimento di t+1 da
    backtest_strategy piu' a valle). Il rendimento REALIZZATO dalla decisione presa
    alla riga t e' quindi rets.iloc[t+1] — questa funzione traccia il valore cumulato
    (e il drawdown dal picco) di ciascun blocco contiguo di decisione costante usando
    esattamente questa relazione. Se lo stop scatta osservando il rendimento
    realizzato alla riga k, il recovery_asset sostituisce la decisione ORIGINALE
    dalla riga k in poi (che dopo lo shift a valle diventera' effettivo dal
    rendimento di k+1, mai prima) fino alla fine del blocco originale — da li' la
    strategia base riprende con la sua prossima decisione, del tutto indipendente."""
    idx = weights_df.index
    n = len(idx)
    out = weights_df.copy()

    row = 0
    while row < n:
        block_end = row
        while block_end + 1 < n and weights_df.iloc[block_end + 1].equals(weights_df.iloc[row]):
            block_end += 1

        peak, value = 1.0, 1.0
        for realize_at in range(row + 1, block_end + 2):  # rendimento realizzato dalla decisione di riga row..block_end
            if realize_at >= n:
                break
            decision_row = realize_at - 1
            period_ret = float((weights_df.iloc[decision_row] * rets.iloc[realize_at]).sum())
            value *= (1 + period_ret)
            peak = max(peak, value)
            if peak > 1e-12 and (value / peak - 1) < stop_threshold:
                out.iloc[realize_at:block_end + 1] = 0.0
                out.loc[idx[realize_at:block_end + 1], recovery_asset] = 1.0
                break

        row = block_end + 1

    return out


def backtest_strategy(weights_df: pd.DataFrame, returns_df: pd.DataFrame, label: str, verbose: bool = True, periods_per_year: int = PERIODS_PER_YEAR):
    """weights_df.iloc[i] e' la decisione presa usando dati fino alla CHIUSURA
    del periodo i (incluso il rendimento di quel periodo stesso, gia' noto a
    chiusura) — va applicata al rendimento del periodo i+1, non di i stesso,
    altrimenti la decisione "conosce" in parte l'esito che sta per tradare
    (look-ahead). shift(1) qui, un solo punto per tutti i candidati, invece
    di richiederlo a ogni chiamante di build_candidate_weights."""
    weights_df = weights_df.shift(1)
    weights_df.iloc[0] = 0.0
    weights_df.iloc[0, weights_df.columns.get_loc("BTC-USD")] = 1.0  # primo periodo: nessuna decisione ancora presa, default BTC
    tax_types = {c: "REDDITO_DIVERSO" for c in weights_df.columns}

    port_gross = (weights_df * returns_df).sum(axis=1)
    weight_change = weights_df.diff().abs().sum(axis=1).fillna(0.0)
    cost_drag = weight_change * KRAKEN_TAKER_FEE
    port_gross_after_costs = port_gross - cost_drag

    port_net = apply_italian_tax(returns_df, weights_df, tax_types=tax_types)
    port_net_after_costs = port_net - cost_drag

    if verbose:
        n_trades = int((weight_change > 1e-9).sum())
        print(f"\n=== {label} ===")
        print(f"CAGR lordo (con costi Kraken): {cagr(port_gross_after_costs, periods_per_year)*100:.2f}%  |  "
              f"CAGR netto (con tasse): {cagr(port_net_after_costs, periods_per_year)*100:.2f}%")
        print(f"Sharpe lordo: {sharpe(port_gross_after_costs, periods_per_year=periods_per_year):.2f}  |  "
              f"Sharpe netto: {sharpe(port_net_after_costs, periods_per_year=periods_per_year):.2f}")
        print(f"Vol annualizzata: {port_gross_after_costs.std()*np.sqrt(periods_per_year)*100:.1f}%")
        print(f"MaxDD lordo: {max_drawdown(port_gross_after_costs)*100:.2f}%  |  "
              f"MaxDD netto: {max_drawdown(port_net_after_costs)*100:.2f}%")
        print(f"Calmar netto: {calmar(port_net_after_costs, periods_per_year):.2f}  |  Periodi di trade: {n_trades}/{len(weights_df)}")
    return port_gross_after_costs, port_net_after_costs


def main():
    if not DATA_DIR.exists() or not any(DATA_DIR.glob("*_daily.csv")):
        print(f"[*] Nessun dato in cache in {DATA_DIR}, scarico da Yahoo Finance...")
        fetch_all_price_data()

    prices = {t: load_daily(t) for t in ALL_TICKERS}
    common = prices["BTC-USD"].index
    for p in prices.values():
        common = common.union(p.index)
    common = common.sort_values()
    common = common[common >= pd.Timestamp("2019-10-01")]

    px = pd.DataFrame({t: prices[t].reindex(common).ffill() for t in ALL_TICKERS})
    rets = px.pct_change().fillna(0.0)
    rets = rets.loc[rets.index[1:]]  # scarta la prima riga (rendimento indefinito)

    print(f"Simulazione daily: {len(rets)} giorni, {rets.index[0].date()} -> {rets.index[-1].date()}")

    for top_n in (3, 5):
        print(f"\n\n########## UNIVERSO POINT-IN-TIME: TOP-{top_n} ALT PER TRIMESTRE ##########")
        pit_alts = load_pointintime_top_alts(top_n)

        results = {}
        for mode, label in [
            ("btc_only", "BTC buy & hold (baseline)"),
            ("regime_altseason", f"Regime altseason daily (top-{top_n} point-in-time)"),
            ("btc_slowdown_switch", f"Switch su rallentamento BTC -> singola alt migliore (top-{top_n})"),
            ("momentum_rotation", f"Rotazione momentum daily {{BTC + top-{top_n}}} (vincitore unico)"),
            ("inverse_vol", f"Inverse-vol {{BTC + top-{top_n}}} (ribilanciato su cambio pool/vol)"),
        ]:
            w = build_candidate_weights(rets, pit_alts, mode)
            gross, net = backtest_strategy(w, rets, label)
            results[mode] = {"label": label, "gross": gross, "net": net, "weights": w}

        # --- PBO-CSCV: il vincitore in-sample tra questi candidati e' anche il migliore fuori campione? ---
        variant_order = list(results.keys())
        perf_matrix = np.column_stack([results[m]["net"].values for m in variant_order])
        n_splits = 8
        usable_len = (len(perf_matrix) // n_splits) * n_splits
        pbo = pbo_cscv(perf_matrix[-usable_len:], n_splits=n_splits)
        print(f"\nPBO-CSCV su {len(variant_order)} candidati (top-{top_n}): {pbo*100:.1f}% "
              "(vicino al 50% = la selezione del migliore non fa meglio del caso; vicino a 0% = edge robusto)")

        # --- DSR + bootstrap CI sul candidato con lo Sharpe netto migliore ---
        best_mode = max(variant_order, key=lambda m: sharpe(results[m]["net"], periods_per_year=PERIODS_PER_YEAR))
        best_net = results[best_mode]["net"]
        best_sr = sharpe(best_net, periods_per_year=PERIODS_PER_YEAR)
        n_trials_real = len(variant_order)  # conteggio onesto: solo i candidati provati in QUESTO script
        dsr = deflated_sharpe_ratio(best_sr, n_trials=n_trials_real, n_obs=len(best_net))
        lo, hi = block_bootstrap_ci(best_net.values, lambda r: sharpe(pd.Series(r), periods_per_year=PERIODS_PER_YEAR),
                                     block_size=30, ci=0.90, seed=42)
        print(f"Migliore per Sharpe netto: {results[best_mode]['label']} (Sharpe {best_sr:.2f})")
        print(f"  DSR (n_trials={n_trials_real}, conteggio reale dei candidati provati): {dsr:.4f}")
        print(f"  CI 90% Sharpe (block bootstrap, blocchi 30gg): [{lo:.2f}, {hi:.2f}]")
        if best_mode == "btc_only":
            print("  Nota sul PBO: BTC buy&hold non tradando mai e' quasi automaticamente il migliore in ogni fold "
                  "(non ha whipsaw da timing) — un PBO basso qui NON e' evidenza di un edge di selezione sofisticato, "
                  "e' semplicemente la conferma che nessuno dei candidati attivi supera il non-fare-nulla.")

        # --- Concentrazione per episodi del candidato "regime altseason" (il piu' vicino alla domanda originale) ---
        regime_net = results["regime_altseason"]["net"]
        regime_weights_alt_days = (results["regime_altseason"]["weights"]["BTC-USD"] < 0.5)
        episodes, in_ep, start = [], False, None
        for date, val in regime_weights_alt_days.items():
            if val and not in_ep:
                in_ep, start = True, date
            elif not val and in_ep:
                in_ep = False
                episodes.append((start, date))
        if in_ep:
            episodes.append((start, regime_weights_alt_days.index[-1]))
        episodes_long = sorted([(s, e) for s, e in episodes if (e - s).days >= 14], key=lambda p: -(p[1] - p[0]).days)[:2]
        if episodes_long:
            mask_top2 = pd.Series(False, index=regime_net.index)
            for s, e in episodes_long:
                mask_top2 |= (regime_net.index >= s) & (regime_net.index <= e)
            net_excluding_top2 = regime_net.copy()
            net_excluding_top2[mask_top2] = 0.0
            print(f"\nConcentrazione per episodi (regime altseason, top-{top_n}): 2 episodi piu' lunghi = "
                  f"{[(s.date(), e.date()) for s, e in episodes_long]}, {mask_top2.sum()}/{len(regime_net)} giorni "
                  f"({mask_top2.mean()*100:.0f}%). CAGR netto escludendoli: {cagr(net_excluding_top2, PERIODS_PER_YEAR)*100:.2f}% "
                  f"(contro {cagr(regime_net, PERIODS_PER_YEAR)*100:.2f}% con tutto il campione).")


if __name__ == "__main__":
    main()
