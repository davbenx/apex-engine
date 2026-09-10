"""
fetch_roe_pointintime.py — Recupero point-in-time del ROE (Return on Equity)
da SEC EDGAR XBRL Company Facts API, per sbloccare l'idea #4 in coda
("quality overlay sul basket low-beta"), finora bloccata perche' Yahoo
Finance non offre fondamentali storici.

Perche' SEC EDGAR e' genuinamente point-in-time e Yahoo no: ogni fatto XBRL
riporta il campo 'filed' — la DATA REALE in cui l'azienda ha depositato il
modulo che conteneva quel numero, non la data di fine periodo contabile.
Un utile 2019 diventa "noto al mercato" solo quando il 10-K e' stato
depositato (tipicamente 2-3 mesi dopo la fine dell'anno fiscale, a volte
di piu' per 10-K/A) — usare 'filed' invece di 'end' e' l'unico modo di
evitare look-ahead bias con questi dati.

Design scelto per semplicita' e copertura, non per completezza:
- Un solo fattore, ROE = NetIncomeLoss annuale / StockholdersEquity a fine
  anno fiscale, presi SOLO da moduli 10-K/10-K/A (niente TTM trimestrale:
  sommare trimestri con tag eterogenei tra aziende e' un'altra fonte di
  errore, e la letteratura quality/QMJ ribilancia comunque su base annuale
  o semestrale, non trimestrale).
- Tag scelti (NetIncomeLoss, StockholdersEquity) sono tra i piu' universali
  nello schema us-gaap (voci obbligatorie di conto economico/stato
  patrimoniale) — a differenza di GrossProfit o Revenues (tag names
  cambiati con ASC 606 nel 2018, non tutte le aziende riportano un
  GrossProfit esplicito, specialmente i finanziari).
- Ticker senza dati (IPO recenti, mismatch di ticker, o tag mancanti)
  restano semplicemente NON in cache — il chiamante li tratta come
  "qualita' neutra" (z-score 0), non li esclude dall'universo, altrimenti
  si introdurrebbe un bias di selezione diverso.

Rate limit: SEC richiede un User-Agent con contatto (fair access policy,
non serve autenticazione) e tollera un ritmo moderato — qui throttled a
un piccolo pool di worker con pausa random, stesso pattern di
backend.download_universe_batch.
"""
from __future__ import annotations

import json
import time
import random
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

USER_AGENT = "Mozilla/5.0 (compatible; ApexEngineResearch/1.0; contact@apexengine.research)"
HTTP_TIMEOUT = 20
MAX_WORKERS = 5

THIS_DIR = Path(__file__).parent
CACHE_DIR = THIS_DIR / "roe_cache"
TICKER_MAP_FILE = THIS_DIR / "sec_ticker_cik_map.json"


def _get(url: str) -> dict:
    last_exc = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            return json.loads(urllib.request.urlopen(req, timeout=HTTP_TIMEOUT).read().decode())
        except Exception as e:  # IncompleteRead/ConnectionError/timeout: transitorio, ritenta
            last_exc = e
            time.sleep(0.5 + attempt)
    raise last_exc


def load_ticker_cik_map() -> dict:
    if TICKER_MAP_FILE.exists():
        return json.load(open(TICKER_MAP_FILE))
    data = _get("https://www.sec.gov/files/company_tickers.json")
    by_ticker = {v["ticker"].upper(): str(v["cik_str"]).zfill(10) for v in data.values()}
    json.dump(by_ticker, open(TICKER_MAP_FILE, "w"))
    return by_ticker


def _resolve_cik(ticker: str, cik_map: dict) -> str | None:
    candidates = [ticker, ticker.replace("-", ""), ticker.replace("-", "."), ticker.replace(".", "-")]
    for c in candidates:
        if c.upper() in cik_map:
            return cik_map[c.upper()]
    return None


def _extract_annual_roe(facts: dict) -> list[dict]:
    gaap = facts.get("facts", {}).get("us-gaap", {})
    ni_facts = gaap.get("NetIncomeLoss", {}).get("units", {}).get("USD", [])
    se_facts = gaap.get("StockholdersEquity", {}).get("units", {}).get("USD", [])
    if not ni_facts or not se_facts:
        return []

    def is_annual_duration(f):
        try:
            from datetime import date
            start = date.fromisoformat(f["start"])
            end = date.fromisoformat(f["end"])
            return 330 <= (end - start).days <= 380
        except Exception:
            return False

    ni_annual = {f["end"]: f for f in ni_facts if f.get("form", "").startswith("10-K") and is_annual_duration(f)}
    se_by_end = {f["end"]: f for f in se_facts if f.get("form", "").startswith("10-K")}

    rows = []
    for end, ni_f in ni_annual.items():
        se_f = se_by_end.get(end)
        if se_f is None or se_f["val"] <= 0:
            continue
        roe = ni_f["val"] / se_f["val"]
        filed = max(ni_f["filed"], se_f["filed"])  # nota realmente al mercato solo quando ENTRAMBI depositati
        rows.append({"end": end, "filed": filed, "roe": roe})
    rows.sort(key=lambda r: r["filed"])
    # se piu' filing coprono lo stesso 'end' (es. 10-K/A che corregge), tiene l'ultimo depositato
    dedup = {}
    for r in rows:
        dedup[r["end"]] = r
    return sorted(dedup.values(), key=lambda r: r["filed"])


def fetch_one(ticker: str, cik_map: dict) -> tuple[str, list[dict] | None]:
    cache_file = CACHE_DIR / f"{ticker}.json"
    if cache_file.exists():
        return ticker, json.load(open(cache_file))
    cik = _resolve_cik(ticker, cik_map)
    if cik is None:
        return ticker, None
    try:
        facts = _get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json")
        rows = _extract_annual_roe(facts)
    except Exception:
        return ticker, None
    json.dump(rows, open(cache_file, "w"))
    return ticker, rows


def fetch_bulk(tickers: list[str]) -> dict[str, list[dict]]:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cik_map = load_ticker_cik_map()
    results = {}
    to_fetch = [t for t in tickers if not (CACHE_DIR / f"{t}.json").exists()]
    for t in tickers:
        if (CACHE_DIR / f"{t}.json").exists():
            results[t] = json.load(open(CACHE_DIR / f"{t}.json"))
    print(f"[*] ROE point-in-time: {len(tickers) - len(to_fetch)} gia' in cache, {len(to_fetch)} da scaricare da SEC EDGAR...")
    if to_fetch:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
            futures = {ex.submit(fetch_one, t, cik_map): t for t in to_fetch}
            done = 0
            for fut in as_completed(futures):
                t, rows = fut.result()
                if rows is not None:
                    results[t] = rows
                done += 1
                if done % 50 == 0:
                    print(f"    {done}/{len(to_fetch)}...")
                time.sleep(random.uniform(0.05, 0.12))
    n_ok = sum(1 for t in tickers if results.get(t))
    print(f"[+] ROE disponibile per {n_ok}/{len(tickers)} ticker.")
    return results


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(THIS_DIR.parent))
    with open(THIS_DIR.parent / "apex_stocks_data" / "sp500_tickers.json") as f:
        all_tickers = json.load(f)
    data = fetch_bulk(all_tickers)
    n_rows = sum(len(v) for v in data.values())
    print(f"Totale righe annuali ROE: {n_rows}")
