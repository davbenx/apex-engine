"""
fetch_live_prices.py — Recupero programmato di prezzi live (Yahoo Finance).

Perché esiste: il fetch live a runtime dalla dashboard (Streamlit Community
Cloud) fallisce spesso perché Yahoo Finance limita/blocca il pool di IP
condivisi degli host cloud — la dashboard mostrava "Benchmark SPY non
raggiungibile" e i prezzi Convex ricadevano silenziosamente sui valori
segnaposto. Questo script gira invece su un runner GitHub Actions (IP non
condiviso con altri utenti Streamlit Cloud, stesso meccanismo già usato e
funzionante per backend.py/update_data.yml) e scrive un file cache che la
dashboard legge localmente — nessun fetch a runtime, nessuna esposizione al
rate-limit.

Esecuzione manuale: python fetch_live_prices.py
"""
import datetime
import json
import urllib.request

CONVEX_TICKERS = {
    "NTSG": "NTSG.MI",
    "AVWS": "AVWS.DE",
    "DBMFE": "DBMF",
    "PPFB": "SGLD.MI",
    "WBTC": "WBTC-ETFP.MI",
}

OUTPUT_FILE = "live_prices_cache.json"


def _fetch_chart(ticker, rng="5d", interval="1d"):
    url = f"https://query2.finance.yahoo.com/v8/finance/chart/{ticker}?range={rng}&interval={interval}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=10) as res:
        return json.loads(res.read().decode())


def fetch_convex_prices():
    prices = {}
    for key, ticker in CONVEX_TICKERS.items():
        try:
            data = _fetch_chart(ticker, rng="5d")
            closes = data["chart"]["result"][0]["indicators"]["quote"][0]["close"]
            last = next(c for c in reversed(closes) if c is not None)
            prices[key] = float(last)
            print(f"  {key:6s} ({ticker:14s}): {last:.4f}")
        except Exception as e:
            print(f"  {key:6s} ({ticker:14s}): ERRORE - {e}")
    return prices


def fetch_spy_history(rng="10y"):
    try:
        data = _fetch_chart("SPY", rng=rng)
        result = data["chart"]["result"][0]
        timestamps = result["timestamp"]
        quote = result["indicators"]["quote"][0]
        history = []
        for ts, o, h, l, c in zip(timestamps, quote["open"], quote["high"], quote["low"], quote["close"]):
            if c is None:
                continue
            date = datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m-%d")
            history.append({
                "date": date,
                "open": o if o is not None else c,
                "high": h if h is not None else c,
                "low": l if l is not None else c,
                "close": c,
            })
        print(f"  SPY: {len(history)} punti, {history[0]['date']} -> {history[-1]['date']}")
        return history
    except Exception as e:
        print(f"  SPY: ERRORE - {e}")
        return []


def main():
    print("[*] Recupero prezzi Convex...")
    convex_prices = fetch_convex_prices()
    print("[*] Recupero storico SPY...")
    spy_history = fetch_spy_history()

    cache = {
        "fetched_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "convex_prices": convex_prices,
        "spy_history": spy_history,
    }

    with open(OUTPUT_FILE, "w") as f:
        json.dump(cache, f, indent=2)

    ok_convex = len(convex_prices) == len(CONVEX_TICKERS)
    ok_spy = len(spy_history) > 0
    print(f"\n[{'OK' if ok_convex and ok_spy else 'PARZIALE'}] Scritto {OUTPUT_FILE}: "
          f"{len(convex_prices)}/{len(CONVEX_TICKERS)} prezzi Convex, "
          f"{len(spy_history)} punti SPY")


if __name__ == "__main__":
    main()
