"""
fetch_crypto_verification_cache.py — Ricostruisce crypto_verification_data/ (40 serie
OHLCV giornaliere via Yahoo Finance, stessa fetch_yahoo_history usata in produzione).

Vedi crypto_verification_data/README.md per lo scopo e i limiti metodologici
espliciti (universo statico, NON survivorship-bias-free come il claim dei 118 asset
point-in-time di CRYPTO_VENTURE_SPEC.md).
"""
from __future__ import annotations
import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from backend import fetch_yahoo_history

TICKERS = [
    "BTC-USD", "ETH-USD", "XRP-USD", "LTC-USD", "DOGE-USD", "ADA-USD", "SOL-USD", "AVAX-USD",
    "LINK-USD", "XLM-USD", "TRX-USD", "ETC-USD", "XMR-USD", "DASH-USD", "ZEC-USD", "EOS-USD",
    "BCH-USD", "ATOM-USD", "ALGO-USD", "FIL-USD", "UNI-USD", "AAVE-USD", "MATIC-USD", "VET-USD",
    "NEAR-USD", "SUI-USD", "ARB-USD", "INJ-USD", "CRV-USD", "ENA-USD", "HBAR-USD", "ICP-USD",
    "APT-USD", "OP-USD", "MKR-USD", "GRT-USD", "SAND-USD", "MANA-USD", "THETA-USD", "EGLD-USD",
]

OUT_DIR = Path(__file__).resolve().parent / "crypto_verification_data"


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    results = {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        # period="10y", non "max": "max"+interval="1d" su Yahoo Chart API restituisce
        # dati sotto-campionati (osservato: ~145 righe su 10 anni invece di ~3650).
        futs = {ex.submit(fetch_yahoo_history, t, "10y", "1d"): t for t in TICKERS}
        for fut in as_completed(futs):
            tkr, df = fut.result()
            results[tkr] = df

    ok, bad = 0, 0
    for tkr, df in results.items():
        if df is not None and len(df) >= 200:
            df.to_csv(OUT_DIR / f"{tkr}.csv")
            ok += 1
            print(f"OK   {tkr:12s} {len(df):5d} righe  {df.index[0].date()} -> {df.index[-1].date()}")
        else:
            bad += 1
            print(f"SKIP {tkr:12s} ({0 if df is None else len(df)} righe)")
    print(f"\nTotale: {ok} salvati, {bad} scartati")


if __name__ == "__main__":
    main()
