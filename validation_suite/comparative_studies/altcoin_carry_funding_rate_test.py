"""
altcoin_carry_funding_rate_test.py — "Carry" per crypto (rendimento dal
funding rate dei perpetual futures, non da un tasso di interesse come nel
carry FX classico) su BTC + alcune delle top point-in-time alt.

LIMITE DICHIARATO, non nascosto: il funding rate storico reale e' ottenuto
dall'API pubblica di Kraken Futures (historicalfundingrates), che restituisce
SOLO ~1 anno di storico (non e' un limite di questo script — l'API stessa
ignora richieste di date piu' vecchie, verificato). Questo test copre quindi
un campione di ~1 anno (2025-09/2026-09), non i ~6-7 anni degli altri test
in questa cartella — un DSR/PBO su un campione cosi' corto va letto con
molta piu' cautela (n_obs basso pesa esplicitamente nella formula del DSR).

Semplificazione dichiarata: questo NON e' un vero carry trade market-neutral
(long spot + short perpetual per incassare il funding senza rischio
direzionale, che richiederebbe di modellare anche la gamba short — non
presente altrove in questo framework, solo long-only spot). E' un test piu'
modesto ma onesto: TILT direzionale long-only verso l'asset con il funding
piu' favorevole (piu' negativo — quando i long pagano meno o vengono
pagati), sommando il rendimento di funding EFFETTIVAMENTE incassato al
rendimento spot dell'asset, non un carry "gratuito" isolato dal rischio di
prezzo.

Convenzione: relativeFundingRate positivo = i long pagano gli short
(convenzione standard perpetual). Il rendimento di funding per chi e' LONG
e' quindi -relativeFundingRate per periodo.
"""

from __future__ import annotations
import json
import sys
import time
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "framework"))
from metrics import cagr, sharpe, max_drawdown, calmar
from statistical_validation import deflated_sharpe_ratio, pbo_cscv
from altcoin_vs_btc_daily_backtest import load_daily, DATA_DIR as DAILY_PRICE_DIR

FUNDING_DATA_DIR = Path(__file__).parent / "carry_funding_data"  # rigenerabile, gitignored
PERIODS_PER_YEAR = 365
SYMBOLS = {
    "BTC-USD": "PF_XBTUSD", "ETH-USD": "PF_ETHUSD", "SOL-USD": "PF_SOLUSD",
    "XRP-USD": "PF_XRPUSD", "ADA-USD": "PF_ADAUSD", "DOGE-USD": "PF_DOGEUSD",
}


def fetch_all_funding_data() -> None:
    FUNDING_DATA_DIR.mkdir(exist_ok=True)
    for ticker, kraken_symbol in SYMBOLS.items():
        url = f"https://futures.kraken.com/derivatives/api/v4/historicalfundingrates?symbol={kraken_symbol}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        res = json.loads(urllib.request.urlopen(req, timeout=20).read().decode())
        rates = res["rates"]
        s = pd.Series(
            {pd.Timestamp(r["timestamp"]): r["relativeFundingRate"] for r in rates}
        ).sort_index()
        s.to_csv(FUNDING_DATA_DIR / f"{ticker.replace('-', '_')}_funding_hourly.csv")
        time.sleep(0.3)


def load_daily_funding_yield(ticker: str) -> pd.Series:
    """Rendimento di funding GIORNALIERO per chi e' LONG (somma delle -relativeFundingRate
    orarie del giorno, non il valore medio — il funding si accumula ogni ora)."""
    path = FUNDING_DATA_DIR / f"{ticker.replace('-', '_')}_funding_hourly.csv"
    hourly = pd.read_csv(path, index_col=0, parse_dates=True).iloc[:, 0]
    hourly.index = hourly.index.tz_localize(None)  # i prezzi daily (load_daily) sono tz-naive: allinea, altrimenti reindex fallisce silenziosamente (tutto NaN)
    daily_long_yield = (-hourly).resample("D").sum()
    return daily_long_yield


def main():
    if not FUNDING_DATA_DIR.exists() or not any(FUNDING_DATA_DIR.glob("*_funding_hourly.csv")):
        print(f"[*] Nessun dato di funding in cache in {FUNDING_DATA_DIR}, scarico da Kraken Futures...")
        fetch_all_funding_data()

    funding = {t: load_daily_funding_yield(t) for t in SYMBOLS}
    common = funding["BTC-USD"].index
    for s in funding.values():
        common = common.intersection(s.index)
    print(f"Campione funding rate reale (Kraken Futures): {len(common)} giorni, "
          f"{common.min().date()} -> {common.max().date()} — SOLO ~1 anno, limite dell'API, non di questo script.")

    print(f"\n{'Asset':<10}{'Funding annualizzato (yield al long)':>40}")
    for t in SYMBOLS:
        annualized = funding[t].reindex(common).mean() * 365 * 100
        print(f"{t:<10}{annualized:>39.2f}%")

    prices = {t: load_daily(t) for t in SYMBOLS}
    spot_rets = {t: prices[t].pct_change().reindex(common).fillna(0.0) for t in SYMBOLS}
    funding_yield = {t: funding[t].reindex(common).fillna(0.0) for t in SYMBOLS}
    total_rets = pd.DataFrame({t: spot_rets[t] + funding_yield[t] for t in SYMBOLS})
    spot_only_rets = pd.DataFrame({t: spot_rets[t] for t in SYMBOLS})

    # Candidato: ogni giorno, long sull'asset con il funding TRAILING (7gg, no lookahead
    # tramite shift(1)) piu' favorevole (piu' negativo) tra il pool — un tilt direzionale,
    # non un carry market-neutral (vedi limite dichiarato sopra).
    trail_funding = pd.DataFrame({t: funding_yield[t].rolling(7).mean() for t in SYMBOLS}).shift(1)
    valid_rows = trail_funding.dropna(how="all").index
    best_carry = trail_funding.loc[valid_rows].idxmin(axis=1)  # piu' negativo = piu' favorevole al long
    carry_weights = pd.DataFrame(0.0, index=common, columns=list(SYMBOLS.keys()))
    carry_weights.loc[~carry_weights.index.isin(valid_rows), "BTC-USD"] = 1.0  # warm-up: default BTC
    for date, asset in best_carry.items():
        carry_weights.loc[date, asset] = 1.0

    port_total = (carry_weights * total_rets).sum(axis=1)
    port_spot_only_of_same_picks = (carry_weights * spot_only_rets).sum(axis=1)
    btc_total = total_rets["BTC-USD"]
    btc_spot = spot_only_rets["BTC-USD"]

    print(f"\n{'Serie':<50}{'CAGR':>10}{'Sharpe':>9}{'MaxDD':>9}")
    for label, series in [
        ("BTC spot-only (no funding)", btc_spot),
        ("BTC spot+funding (se fosse long perpetual)", btc_total),
        ("Carry tilt: spot-only delle stesse scelte", port_spot_only_of_same_picks),
        ("Carry tilt: spot+funding (il vero candidato)", port_total),
    ]:
        print(f"{label:<50}{cagr(series, PERIODS_PER_YEAR)*100:>9.1f}%{sharpe(series, periods_per_year=PERIODS_PER_YEAR):>9.2f}"
              f"{max_drawdown(series)*100:>8.1f}%")

    perf_matrix = np.column_stack([btc_total.values, port_total.values])
    n_splits = 4  # campione corto (~1 anno): meno split di quelli usati altrove (8), altrimenti blocchi troppo piccoli
    usable_len = (len(perf_matrix) // n_splits) * n_splits
    if usable_len >= n_splits * 2:
        pbo = pbo_cscv(perf_matrix[-usable_len:], n_splits=n_splits)
        print(f"\nPBO-CSCV (BTC long vs carry tilt, campione corto ~1 anno): {pbo*100:.1f}%")
    dsr = deflated_sharpe_ratio(sharpe(port_total, periods_per_year=PERIODS_PER_YEAR), n_trials=2, n_obs=len(port_total))
    print(f"DSR del carry tilt (n_trials=2, n_obs={len(port_total)} — CAMPIONE CORTO, DSR poco informativo qui): {dsr:.4f}")
    print("\nAvvertenza: ~1 anno di dati non e' sufficiente per un verdetto istituzionale robusto su carry — "
          "questi numeri sono indicativi, non una conclusione allo stesso livello di rigore degli altri test in questa cartella.")


if __name__ == "__main__":
    main()
