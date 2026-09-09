"""
altcoin_vs_btc_backtest.py — C'e' una strategia su altcoin che sovraperforma
BTC-USD a parita' o minor rischio, al netto di tasse italiane (26%, redditi
diversi — stesso trattamento per BTC e altcoin, nessuna asimmetria fiscale
da sfruttare qui a differenza del confronto titoli/ETF di
apex_stocks_vs_etf_backtest.py) e costi reali di trading spot su Kraken
(taker ~0.26%, fascia volumi piu' bassa, verificato via ricerca web
settembre 2026 — non un numero a memoria)?

Contesto: Apex ha gia' testato (APEX_V2_SPEC.md §8.1) due varianti di
espansione crypto DENTRO il proprio overlay macro completo (mix statico
70/30 BTC/ETH, basket low-vol top-2 di 5) — entrambe peggiorano ogni
metrica rispetto a BTC-only. Questo script testa la domanda in modo
INDIPENDENTE dall'overlay macro di Apex (una sleeve crypto stand-alone,
non annegata nel resto del sistema) con candidati NON gia' testati li'
(rotazione per momentum, pesatura inverse-vol) — cita ma non duplica quel
test.

Cadenza: decisione/ribilanciamento SETTIMANALE (non mensile come Apex per
l'azionario) — le crypto tradano 24/7, settimanale resta un turnover basso
(coerente col principio "mai daily" del progetto) senza richiedere il
modello di deriva tra ribilanciamenti mensili che avrebbe complicato
inutilmente il confronto per un caso con target spesso costante.

Riusa _apply_italian_tax di kelly_backtest.py (gia' validata, gestisce
correttamente NAV/valore nozionale/PMC) invece di una nuova funzione ad-hoc.
"""

from __future__ import annotations
import json
import time
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

from kelly_backtest import _cagr, _sharpe, _max_drawdown, _apply_italian_tax

DATA_DIR = Path(__file__).parent / "altcoin_data"  # rigenerabile, non tracciato in git (.gitignore)
KRAKEN_TAKER_FEE = 0.0026  # verificato via ricerca web, fascia volume piu' bassa
COINS = ["BTC-USD", "ETH-USD", "SOL-USD", "BNB-USD", "XRP-USD", "ADA-USD", "AVAX-USD", "LTC-USD", "DOGE-USD"]


def _fetch_weekly_adj(ticker: str, rng: str) -> pd.Series:
    url = f"https://query2.finance.yahoo.com/v8/finance/chart/{ticker}?range={rng}&interval=1d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    res = json.loads(urllib.request.urlopen(req, timeout=15).read().decode())
    result = res["chart"]["result"][0]
    ts = pd.to_datetime(result["timestamp"], unit="s")
    adj = result["indicators"]["adjclose"][0]["adjclose"]
    daily = pd.Series(adj, index=ts).dropna()
    return daily.resample("W-FRI").last().dropna()


def fetch_all_price_data() -> None:
    """range esplicito ('12y' per BTC/LTC, 'max' per le altre) — Yahoo declassa
    silenziosamente 'max' a granularita' mensile per span molto lunghi (bug
    trovato in questa sessione); BTC/LTC hanno storico >10 anni, le altre no."""
    DATA_DIR.mkdir(exist_ok=True)
    for t in COINS:
        rng = "12y" if t in ("BTC-USD", "LTC-USD") else "max"
        w = _fetch_weekly_adj(t, rng)
        w.to_csv(DATA_DIR / f"{t.replace('-', '_')}_weekly.csv")
        time.sleep(0.3)


def load_weekly(ticker: str) -> pd.Series:
    return pd.read_csv(DATA_DIR / f"{ticker.replace('-', '_')}_weekly.csv", index_col=0, parse_dates=True).iloc[:, 0]


def backtest_strategy(weights_df: pd.DataFrame, returns_df: pd.DataFrame, label: str):
    tax_types = {c: "REDDITO_DIVERSO" for c in weights_df.columns}  # tutte le crypto, stesso trattamento, stesso pool

    port_gross = (weights_df * returns_df).sum(axis=1)
    weight_change = weights_df.diff().abs().sum(axis=1).fillna(0.0)
    cost_drag = weight_change * KRAKEN_TAKER_FEE
    port_gross_after_costs = port_gross - cost_drag

    port_net = _apply_italian_tax(returns_df, weights_df, tax_types=tax_types)
    port_net_after_costs = port_net - cost_drag

    print(f"\n=== {label} ===")
    print(f"CAGR lordo (con costi Kraken): {_cagr(port_gross_after_costs)*100:.2f}%  |  CAGR netto (con tasse): {_cagr(port_net_after_costs)*100:.2f}%")
    print(f"Sharpe lordo: {_sharpe(port_gross_after_costs):.2f}  |  Sharpe netto: {_sharpe(port_net_after_costs):.2f}")
    print(f"Vol annualizzata: {port_gross_after_costs.std()*np.sqrt(52)*100:.1f}%")
    print(f"MaxDD lordo: {_max_drawdown(port_gross_after_costs)*100:.2f}%  |  MaxDD netto: {_max_drawdown(port_net_after_costs)*100:.2f}%")
    return port_gross_after_costs, port_net_after_costs


def main():
    if not DATA_DIR.exists() or not any(DATA_DIR.glob("*_weekly.csv")):
        print(f"[*] Nessun dato in cache in {DATA_DIR}, scarico da Yahoo Finance...")
        fetch_all_price_data()

    coins = ["BTC-USD", "ETH-USD", "SOL-USD"]
    prices = {c: load_weekly(c) for c in coins}
    rets = {c: p.pct_change().dropna() for c, p in prices.items()}

    common = rets["BTC-USD"].index.intersection(rets["ETH-USD"].index).intersection(rets["SOL-USD"].index)
    df3 = pd.DataFrame({c: rets[c].reindex(common) for c in coins}).dropna()

    # --- Baseline: BTC buy & hold ---
    w_btc = pd.DataFrame({"BTC-USD": 1.0, "ETH-USD": 0.0, "SOL-USD": 0.0}, index=df3.index)
    backtest_strategy(w_btc, df3, "BTC buy & hold (baseline)")

    # --- Candidato 1: equal-weight BTC/ETH/SOL, ribilanciato settimanale ---
    w_equal = pd.DataFrame(1 / 3, index=df3.index, columns=df3.columns)
    backtest_strategy(w_equal, df3, "Equal-weight BTC/ETH/SOL")

    # --- Candidato 2: inverse-vol weighted BTC/ETH/SOL ---
    vol_window = 12
    inv_vol_weights = []
    for i in range(len(df3)):
        if i < vol_window:
            inv_vol_weights.append({c: 1 / 3 for c in df3.columns})
            continue
        trailing = df3.iloc[i - vol_window:i]
        inv_vol = 1 / trailing.std()
        w = inv_vol / inv_vol.sum()
        inv_vol_weights.append(w.to_dict())
    w_invvol = pd.DataFrame(inv_vol_weights, index=df3.index)
    backtest_strategy(w_invvol, df3, "Inverse-vol weighted BTC/ETH/SOL")

    # --- Candidato 3: rotazione momentum (12 settimane), 100% sulla moneta migliore ---
    mom_window = 12
    mom_weights = []
    for i in range(len(df3)):
        if i < mom_window:
            mom_weights.append({c: (1.0 if c == "BTC-USD" else 0.0) for c in df3.columns})
            continue
        trailing_cum = (1 + df3.iloc[i - mom_window:i]).prod() - 1
        best = trailing_cum.idxmax()
        mom_weights.append({c: (1.0 if c == best else 0.0) for c in df3.columns})
    w_mom = pd.DataFrame(mom_weights, index=df3.index)
    backtest_strategy(w_mom, df3, "Rotazione momentum 12 settimane (100% sul migliore)")

    # --- Candidato 4: momentum ma con floor 30% BTC (meno all-or-nothing) ---
    mom_weights_floor = []
    for i in range(len(df3)):
        if i < mom_window:
            mom_weights_floor.append({"BTC-USD": 1.0, "ETH-USD": 0.0, "SOL-USD": 0.0})
            continue
        trailing_cum = (1 + df3.iloc[i - mom_window:i]).prod() - 1
        best = trailing_cum.idxmax()
        w = {c: 0.0 for c in df3.columns}
        w["BTC-USD"] += 0.30
        w[best] += 0.70 if best != "BTC-USD" else 0.0
        if best == "BTC-USD":
            w["BTC-USD"] = 1.0
        mom_weights_floor.append(w)
    w_mom_floor = pd.DataFrame(mom_weights_floor, index=df3.index)
    backtest_strategy(w_mom_floor, df3, "Rotazione momentum con floor 30% BTC")

    # --- Candidato 5: rotazione di REGIME — sposta su alt SOLO quando BTC perde forza
    # relativa (altseason), altrimenti 100% BTC. Diverso dal candidato 3 (rotazione
    # momentum sempre attiva tra le 3): qui BTC e' la posizione di default, gli alt
    # sono l'eccezione condizionale — la domanda esplicita dell'utente.
    window = 12
    btc_trail = (1 + df3["BTC-USD"]).rolling(window).apply(lambda x: x.prod() - 1)
    alt_trail = pd.concat([
        (1 + df3["ETH-USD"]).rolling(window).apply(lambda x: x.prod() - 1),
        (1 + df3["SOL-USD"]).rolling(window).apply(lambda x: x.prod() - 1),
    ], axis=1).mean(axis=1)
    rel_strength = (btc_trail - alt_trail).shift(1)  # deciso a fine settimana t-1, applicato al rendimento di t

    regime_weights = []
    for i in range(len(df3)):
        if pd.isna(rel_strength.iloc[i]):
            regime_weights.append({"BTC-USD": 1.0, "ETH-USD": 0.0, "SOL-USD": 0.0})
            continue
        if rel_strength.iloc[i] < 0:
            regime_weights.append({"BTC-USD": 0.0, "ETH-USD": 0.5, "SOL-USD": 0.5})
        else:
            regime_weights.append({"BTC-USD": 1.0, "ETH-USD": 0.0, "SOL-USD": 0.0})
    w_regime = pd.DataFrame(regime_weights, index=df3.index)
    gross_regime, net_regime = backtest_strategy(w_regime, df3, "Rotazione di regime (alt SOLO quando BTC perde forza relativa)")

    # Quanto dipende dai 2 episodi piu' lunghi? Se azzero il contributo di quelle
    # settimane (le tratto come se fossero rimaste a rendimento zero), quanto
    # cambia il CAGR netto — diagnostica sulla concentrazione del risultato.
    is_altseason = (rel_strength < 0)
    episodes, in_ep, start = [], False, None
    for date, val in is_altseason.items():
        if val and not in_ep:
            in_ep, start = True, date
        elif not val and in_ep:
            in_ep = False
            episodes.append((start, date))
    if in_ep:
        episodes.append((start, is_altseason.index[-1]))
    episodes_long = sorted([(s, e) for s, e in episodes if (e - s).days >= 28], key=lambda p: -(p[1] - p[0]).days)[:2]
    print(f"\nEpisodi di 'altseason' piu' lunghi nel campione: {[(s.date(), e.date()) for s, e in episodes_long]}")
    mask_top2 = pd.Series(False, index=net_regime.index)
    for s, e in episodes_long:
        mask_top2 |= (net_regime.index >= s) & (net_regime.index <= e)
    net_excluding_top2 = net_regime.copy()
    net_excluding_top2[mask_top2] = 0.0
    print(f"CAGR netto ESCLUDENDO i 2 episodi piu' lunghi: {_cagr(net_excluding_top2)*100:.2f}% "
          f"(contro {_cagr(net_regime)*100:.2f}% con tutto il campione) — "
          f"{mask_top2.sum()}/{len(net_regime)} settimane escluse ({mask_top2.mean()*100:.0f}%)")

    print("\nRiferimento: Apex ha gia' testato (APEX_V2_SPEC.md §8.1, dentro l'overlay macro completo)")
    print("mix 70/30 BTC/ETH e basket low-vol top-2/5: Sharpe 1.39->1.36/1.26, entrambe peggiori di BTC-only.")


if __name__ == "__main__":
    main()
