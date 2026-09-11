"""
fetch_delisted_sp500_prices.py — Corregge il survivorship bias scoperto
nell'audit istituzionale (validation_suite/README.md): l'universo prezzi
usato dal backtest azionario di Apex era costruito da get_sp500_tickers()
(i membri ATTUALI dell'S&P 500), non dall'unione di tutti i membri
storici — qualunque titolo delistato/acquisito/rimosso dall'indice dal
2012 in poi era quindi invisibile al backtest anche se il filtro di
eleggibilita' point-in-time lo considerava corretto, nonostante fosse
teoricamente selezionabile (225/500 mancanti nel solo 2012, 45%).

Verificato PRIMA di scrivere questo script che l'API di Yahoo Finance
serve ancora dati storici per una parte sostanziale dei titoli delistati/
acquisiti (es. AET: storico completo; BBBY: solo la coda finale prima del
fallimento; APC: parziale) — non tutti, ma abbastanza da valere il
tentativo, cosa che lo script di fetch originale non aveva mai provato
perche' partiva dalla lista sbagliata di ticker.

Scarica SOLO i ticker storici mancanti (unione di tutti gli snapshot
point-in-time 2012-2026, meno quelli gia' presenti) — non ritocca i file
gia' scaricati.
"""
from __future__ import annotations
import json
import time
import urllib.request
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
POINTINTIME_FILE = REPO_ROOT / "validation_suite" / "pointintime_data" / "sp500_pointintime_snapshots.json"
DATA_DIR = Path(__file__).parent / "apex_stocks_data"


def _fetch_weekly_adj(ticker: str, rng: str = "15y") -> pd.Series:
    url = f"https://query2.finance.yahoo.com/v8/finance/chart/{ticker}?range={rng}&interval=1d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    res = json.loads(urllib.request.urlopen(req, timeout=15).read().decode())
    result = res["chart"]["result"][0]
    ts = pd.to_datetime(result["timestamp"], unit="s")
    adj = result["indicators"]["adjclose"][0]["adjclose"]
    daily = pd.Series(adj, index=ts).dropna()
    return daily.resample("W-FRI").last().dropna()


def main():
    snapshots = json.load(open(POINTINTIME_FILE))
    all_hist_tickers = set()
    for year, tickers in snapshots.items():
        all_hist_tickers |= set(t.replace(".", "-") for t in tickers)

    have_files = set()
    for fp in DATA_DIR.glob("sp500_*_weekly.csv"):
        ticker = fp.stem[len("sp500_"):-len("_weekly")].replace("_", "-")
        have_files.add(ticker)

    to_fetch = sorted(all_hist_tickers - have_files)
    print(f"[*] Universo storico completo: {len(all_hist_tickers)} ticker unici (2012-2026)")
    print(f"[*] Gia' presenti: {len(have_files)}")
    print(f"[*] Da scaricare (delistati/acquisiti/rimossi, prima mai tentati): {len(to_fetch)}")

    ok, fail, partial = 0, 0, 0
    failed_tickers = []
    for i, t in enumerate(to_fetch):
        try:
            w = _fetch_weekly_adj(t)
            if len(w) >= 20:
                safe_name = t.replace("-", "_").replace(".", "_")
                w.to_csv(DATA_DIR / f"sp500_{safe_name}_weekly.csv")
                if len(w) < 200:
                    partial += 1
                else:
                    ok += 1
            else:
                fail += 1
                failed_tickers.append(t)
        except Exception:
            fail += 1
            failed_tickers.append(t)
        if (i + 1) % 25 == 0:
            print(f"    ... {i+1}/{len(to_fetch)} processati (ok={ok}, parziali={partial}, falliti={fail})")
        time.sleep(0.15)

    print(f"\n[*] Completato: {ok} con storico sostanziale (>=200 settimane), "
          f"{partial} parziali (20-199 settimane), {fail} falliti su {len(to_fetch)} tentati.")
    print(f"[*] Copertura finale: {len(have_files) + ok + partial}/{len(all_hist_tickers)} "
          f"({(len(have_files)+ok+partial)/len(all_hist_tickers)*100:.1f}%)")
    if failed_tickers:
        print(f"\nTicker falliti (nessun dato disponibile, probabilmente delisting troppo vecchio "
              f"o simbolo non riconosciuto da Yahoo): {failed_tickers}")

    # Aggiorna sp500_tickers.json con l'unione storica completa, cosi' i
    # backtest che leggono quel manifest vedano davvero tutti i ticker
    all_current_files = sorted(have_files | set(to_fetch))
    with open(DATA_DIR / "sp500_tickers.json", "w") as f:
        json.dump(all_current_files, f)
    print(f"\n[*] sp500_tickers.json aggiornato: {len(all_current_files)} ticker (era {len(have_files)} prima -- "
          f"nota: include anche eventuali falliti, load_weekly_sp500 li salta con FileNotFoundError, comportamento nativo gia' gestito da run_full_backtest)")


if __name__ == "__main__":
    main()
