"""
convex_extended_history_reconstruction.py — Ricostruisce Convex Stack fino al
1987-06-30 (stesso inizio utile della serie estesa di Apex,
apex_dashboard_stat_regeneration.py), richiesto esplicitamente dall'utente.
Il collo di bottiglia dichiarato: DBMFE_proxy (oggi solo `DBMF`, storico dal
2019-05) — i CTA sistematici non hanno quasi mai avuto un prodotto quotato
retail-accessibile con storico lungo (a differenza di equity/bond/oro, dove
fondi indice esistono da decenni). Il resto delle sleeve ha lo stesso
problema in forma minore: AVWS_proxy (`VBR`, dal 2004) e' anch'esso troppo
corto per il 1987.

== Trovare un proxy migliore per DBMFE ==

Nessun singolo ticker fetchabile replica un CTA sistematico multi-mercato con
storico dagli anni '80 (i managed futures fund storici — Campbell, Winton,
Dunn — non sono mai stati quotati pubblicamente con prezzo giornaliero
disponibile). La strada seguita, con precedente diretto gia' in questo
repository (`kelly_stack/kelly_backtest.py:compute_tsmom_sleeve_returns`,
metodologia Moskowitz-Ooi-Pedersen 2012 "Time Series Momentum", la stessa
usata dai CTA sistematici reali — Winton, Dunn Capital, AHL): costruire un
indice SINTETICO di trend-following applicando il segnale TSMOM (long/flat
in base al segno del rendimento cumulato a 12 mesi, posizioni scalate a
vol-target comune) sugli STESSI proxy macro gia' estesi per Apex
(VFINX/VUSTX/GC=F, gia' in cache in apex_macro_extended_data/) — universo
CRESCENTE nel tempo (Equity+Bonds dal 1987, +Gold dal 2000-08 quando GC=F
diventa disponibile), poi raccordato con `DBMF` reale dal 2019-05.

Validazione: la stessa formula a 3 mercati, calcolata SUL periodo in cui
DBMF reale esiste (2019-05 in poi, usando SPY/IEF/GLD reali, non proxy),
correlata col rendimento reale di DBMF — un CTA reale tratta ~20-35 mercati
(valute, tassi, indici, commodity), quindi una correlazione MODESTA (non
alta) e' il risultato atteso e accettabile, non un fallimento del proxy.

== Estensione di AVWS (secondo collo di bottiglia, non richiesto esplicitamente
ma necessario per raggiungere il 1987 sull'intero portafoglio) ==

VBR (oggi) parte dal 2004. Splice aggiuntivo: NAESX (Vanguard Small-Cap
Index, non value-tilted — dal 1985-01, unico proxy disponibile per il
1987-1993) -> DFSVX (DFA US Small Cap Value, genuinamente value-tilted,
stesso stile fattoriale di AVWS, dal 1993-03) -> VBR (dal 2004-02, gia'
usato). Limite dichiarato: 1987-1993 usa un proxy SENZA tilt value (solo
small-cap), un'approssimazione piu' grezza delle altre gambe.

== Oro e Crypto: limite invariato, non un nuovo problema ==

PPFB (oro) resta vincolato a GC=F dal 2000-08 (stessa scelta deliberata di
Apex — niente proxy azionari auriferi pre-2000, contaminerebbero la classe
con beta equity, vedi apex_dashboard_stat_regeneration.py). WBTC resta
vincolato a BTC-USD dal 2014-09 (nessun mercato crypto liquido affidabile
prima). PRIMA di queste date, i pesi Convex sono RINORMALIZZATI tra le
sole sleeve disponibili quell'anno — la stessa logica gia' usata da Apex
per la gamba Equity pre-2012 (mai inventare un rendimento che non esiste).
"""
from __future__ import annotations
import sys
import time
import urllib.request
import urllib.error
import json
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "validation_suite" / "framework"))
sys.path.insert(0, str(REPO_ROOT / "validation_suite" / "kelly_stack"))

from metrics import cagr as _cagr, sharpe as _sharpe, max_drawdown as _max_drawdown, calmar as _calmar
from kelly_backtest import compute_tsmom_sleeve_returns
from apex_dashboard_stat_regeneration import spliced_return as apex_spliced_return, EXT_DATA_DIR as APEX_EXT_DIR

USER_AGENT = "Mozilla/5.0 (compatible; ApexEngineResearch/1.0; contact@apexengine.research)"
HTTP_TIMEOUT = 20
CACHE_DIR = Path(__file__).parent / "convex_extended_data"
DBMF_MONTHLY = Path(__file__).parent / "convex_grid_data" / "DBMF_monthly.csv"

CURRENT_WEIGHTS = {"NTSG_proxy": 0.45, "AVWS_proxy": 0.15, "DBMFE_proxy": 0.25, "PPFB_proxy": 0.075, "WBTC_proxy": 0.075}


def _fetch_daily_full(ticker: str, start="1985-01-01") -> pd.Series:
    cache_file = CACHE_DIR / f"{ticker}.csv"
    if cache_file.exists():
        return pd.read_csv(cache_file, index_col=0, parse_dates=True).iloc[:, 0]
    p1 = int(pd.Timestamp(start).timestamp())
    p2 = int(pd.Timestamp.now().timestamp())
    url = f"https://query2.finance.yahoo.com/v8/finance/chart/{ticker}?period1={p1}&period2={p2}&interval=1d"
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            res = json.loads(urllib.request.urlopen(req, timeout=HTTP_TIMEOUT).read().decode())
            result = res["chart"]["result"][0]
            ts = pd.to_datetime(result["timestamp"], unit="s")
            adjclose = result["indicators"].get("adjclose", [{}])[0].get("adjclose")
            close = adjclose if adjclose is not None else result["indicators"]["quote"][0]["close"]
            s = pd.Series(close, index=ts).dropna()
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            s.to_csv(cache_file, header=["Close"])
            return s
        except (urllib.error.HTTPError, urllib.error.URLError, KeyError, IndexError):
            time.sleep(1.0 + attempt)
    raise RuntimeError(f"Fetch fallito per {ticker}")


def monthly_return(daily: pd.Series) -> pd.Series:
    m = daily.resample("ME").last().dropna()
    return m.pct_change().dropna()


def splice_monthly_returns(legs: list[tuple[pd.Series, pd.Timestamp | None, pd.Timestamp | None]]) -> pd.Series:
    """legs: lista di (serie_rendimenti_mensili, start_incl, end_escl) — concatena
    in ordine, ogni leg tagliata alla propria finestra, nessuna sovrapposizione.

    Raccorda a livello di PREZZO (base=100, cumulato dai rendimenti di ciascuna
    leg), non di rendimento gia' calcolato — evita l'artefatto per cui il primo
    mese di una nuova leg (pct_change richiede un valore precedente) sparirebbe
    altrimenti come un buco di un mese ad ogni giunzione (stesso principio di
    apex_dashboard_stat_regeneration.spliced_return, che raccorda per rendimento
    ma partendo da un prezzo continuo — qui la sorgente sono gia' rendimenti
    separati, quindi si ricostruisce il prezzo PRIMA di raccordare)."""
    parts = []
    for ret, start, end in legs:
        r = ret
        if start is not None:
            r = r.loc[r.index >= start]
        if end is not None:
            r = r.loc[r.index < end]
        parts.append(r)
    combined = pd.concat(parts).sort_index()
    price = 100.0 * (1 + combined).cumprod()
    return price.pct_change().dropna()


def build_avws_proxy_ext() -> pd.Series:
    naesx = monthly_return(_fetch_daily_full("NAESX"))
    dfsvx = monthly_return(_fetch_daily_full("DFSVX"))
    vbr = monthly_return(_fetch_daily_full("VBR"))
    cut1, cut2 = pd.Timestamp("1993-03-01"), pd.Timestamp("2004-03-01")
    return splice_monthly_returns([(naesx, None, cut1), (dfsvx, cut1, cut2), (vbr, cut2, None)])


def build_ntsg_proxy_ext() -> pd.Series:
    spy_ret = apex_spliced_return("VFINX_weekly.csv", "SPY_weekly.csv", "1993-01-29")
    ief_ret = apex_spliced_return("VUSTX_weekly.csv", "IEF_weekly.csv", "2002-08-02")
    spy_m = (1 + spy_ret).resample("ME").prod() - 1.0
    ief_m = (1 + ief_ret).resample("ME").prod() - 1.0
    common = spy_m.index.intersection(ief_m.index)
    return 0.90 * spy_m.reindex(common) + 0.60 * ief_m.reindex(common)


def build_macro_price_levels_monthly() -> pd.DataFrame:
    """Prezzi mensili sintetici Base=100 per SPY/IEF/GLD (raccordo Apex, stessa
    fonte/metodologia di apex_dashboard_stat_regeneration.py) — servono a
    compute_tsmom_sleeve_returns, che lavora su LIVELLI, non su rendimenti."""
    rets = {}
    rets["SPY"] = apex_spliced_return("VFINX_weekly.csv", "SPY_weekly.csv", "1993-01-29")
    rets["IEF"] = apex_spliced_return("VUSTX_weekly.csv", "IEF_weekly.csv", "2002-08-02")
    rets["GLD"] = apex_spliced_return("GC_F_weekly.csv", "GLD_weekly.csv", "2004-11-19")
    prices = {}
    for k, r in rets.items():
        m = (1 + r).resample("ME").prod() - 1.0
        prices[k] = 100.0 * (1 + m).cumprod()
    return pd.DataFrame(prices)


def build_dbmfe_proxy_ext(macro_prices: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Ritorna (serie_estesa_raccordata, serie_sintetica_sull_intero_periodo_per_validazione).

    Punto di passaggio dal segnale a 2 mercati (Equity+Bonds) a quello a 3
    (+Gold) NON e' la data nominale in cui GC=F diventa disponibile
    (TSMOM_GOLD_START): compute_tsmom_sleeve_returns richiede il proprio
    periodo di warmup (12 mesi di momentum + finestra di volatilita') PRIMA
    di produrre un segnale valido sui dati che vede — usando la data nominale
    si aprirebbe un buco di ~14 mesi (ne' il segnale a 2 ne' quello a 3
    mercati coprirebbero quel periodo). Si usa invece l'inizio REALE
    dell'indice di three_asset_full (dopo il proprio warmup) come cutover,
    tenendo il segnale a 2 mercati come ponte fino a quel momento."""
    two_asset = compute_tsmom_sleeve_returns({"SPY": macro_prices["SPY"], "IEF": macro_prices["IEF"]})
    three_asset_full = compute_tsmom_sleeve_returns(macro_prices[["SPY", "IEF", "GLD"]].dropna().to_dict("series"))
    three_asset_cutover = three_asset_full.index.min()

    dbmf_m = monthly_return(_fetch_daily_full("DBMF", start="2019-01-01"))
    if not DBMF_MONTHLY.exists():
        raise FileNotFoundError(f"{DBMF_MONTHLY} mancante — atteso dai test Convex gia' eseguiti in questa sessione")
    # dbmf_m.index.min() (non DBMF_REAL_START nominale): il primo NAV di DBMF non ha un
    # rendimento associabile (serve un valore precedente per pct_change) — quel mese
    # resta coperto dal sintetico a 3 mercati, stesso principio del cutover sull'oro sopra.
    dbmf_cutover = dbmf_m.index.min()

    extended = splice_monthly_returns([
        (two_asset, None, three_asset_cutover),
        (three_asset_full, three_asset_cutover, dbmf_cutover),
        (dbmf_m, dbmf_cutover, None),
    ])
    return extended, three_asset_full


def main():
    print("[*] Costruzione NTSG_proxy esteso (0.9*SPY + 0.6*IEF, raccordo Apex gia' validato)...")
    ntsg = build_ntsg_proxy_ext()
    print(f"    {ntsg.index[0].date()} -> {ntsg.index[-1].date()}, {len(ntsg)} mesi")

    print("[*] Costruzione AVWS_proxy esteso (NAESX -> DFSVX -> VBR)...")
    avws = build_avws_proxy_ext()
    print(f"    {avws.index[0].date()} -> {avws.index[-1].date()}, {len(avws)} mesi")

    print("[*] Costruzione DBMFE_proxy esteso (TSMOM sintetico 2/3 mercati -> DBMF reale)...")
    macro_prices = build_macro_price_levels_monthly()
    dbmfe, dbmfe_synthetic_full = build_dbmfe_proxy_ext(macro_prices)
    print(f"    {dbmfe.index[0].date()} -> {dbmfe.index[-1].date()}, {len(dbmfe)} mesi")

    print("[*] Validazione: TSMOM sintetico (3 mercati) vs DBMF reale, periodo di sovrapposizione...")
    dbmf_real_m = monthly_return(_fetch_daily_full("DBMF", start="2019-01-01"))
    overlap = dbmfe_synthetic_full.index.intersection(dbmf_real_m.index)
    corr = dbmfe_synthetic_full.reindex(overlap).corr(dbmf_real_m.reindex(overlap))
    print(f"    Correlazione TSMOM sintetico vs DBMF reale ({len(overlap)} mesi comuni): {corr:.3f}")

    print("[*] Gold (GC=F) e Crypto (BTC-USD): stesso limite di Apex, nessuna estensione ulteriore...")
    gld_ret = apex_spliced_return("GC_F_weekly.csv", "GLD_weekly.csv", "2004-11-19")
    gld_m = (1 + gld_ret).resample("ME").prod() - 1.0
    btc_daily = _fetch_daily_full("BTC-USD", start="2014-01-01")
    btc_m = monthly_return(btc_daily)
    print(f"    Gold disponibile da {gld_m.index[0].date()}, Crypto da {btc_m.index[0].date()}")

    print("\n[*] Assemblaggio portafoglio Convex esteso, pesi rinormalizzati tra le sole sleeve disponibili...")
    all_dates = ntsg.index.union(avws.index).union(dbmfe.index).union(gld_m.index).union(btc_m.index).sort_values()
    sleeves = {"NTSG_proxy": ntsg, "AVWS_proxy": avws, "DBMFE_proxy": dbmfe, "PPFB_proxy": gld_m, "WBTC_proxy": btc_m}

    port_rets = []
    for dt in all_dates:
        avail = {k: s.loc[dt] for k, s in sleeves.items() if dt in s.index}
        if not avail:
            continue
        w_total = sum(CURRENT_WEIGHTS[k] for k in avail)
        port_ret = sum(CURRENT_WEIGHTS[k] / w_total * v for k, v in avail.items())
        port_rets.append((dt, port_ret, len(avail)))

    port = pd.Series({d: r for d, r, _ in port_rets}).sort_index()
    n_sleeves = pd.Series({d: n for d, _, n in port_rets}).sort_index()
    print(f"\nPortafoglio esteso: {port.index[0].date()} -> {port.index[-1].date()}, {len(port)} mesi (lordo, pre-costi/tasse)")
    for n in sorted(n_sleeves.unique()):
        sub = n_sleeves[n_sleeves == n]
        print(f"  {n} sleeve disponibili: {sub.index[0].date()} -> {sub.index[-1].date()} ({len(sub)} mesi)")

    c, s, dd, cal = _cagr(port, 12), _sharpe(port, periods_per_year=12), _max_drawdown(port), _calmar(port, 12)
    print(f"\nCAGR lordo {c*100:.2f}%  Sharpe {s:.2f}  MaxDD {dd*100:.2f}%  Calmar {cal:.2f}  (intero campione esteso)")

    # Confronto sul campione gia' usato in questa sessione (2019-06+, DBMF-limited)
    short_sample = port.loc["2019-06-30":]
    c2, s2, dd2 = _cagr(short_sample, 12), _sharpe(short_sample, periods_per_year=12), _max_drawdown(short_sample)
    print(f"Sotto-periodo 2019-06+ (confronto coi test gia' fatti in questa sessione, ~stessi pesi correnti): "
          f"CAGR {c2*100:.2f}%  Sharpe {s2:.2f}  MaxDD {dd2*100:.2f}%")

    out_file = Path(__file__).parent / "convex_extended_data" / "convex_monthly_returns_extended_gross.csv"
    port.to_csv(out_file, header=["return"])
    print(f"\n[*] Salvato: {out_file}")

    sleeve_df = pd.DataFrame(sleeves)  # NaN dove la sleeve non e' ancora disponibile — non riempito, uso esplicito a valle
    sleeve_out = Path(__file__).parent / "convex_extended_data" / "convex_sleeve_returns_extended.csv"
    sleeve_df.to_csv(sleeve_out)
    print(f"[*] Salvato: {sleeve_out} (rendimenti per sleeve, NaN dove non ancora disponibile — riuso per i test Kelly)")


if __name__ == "__main__":
    main()
