"""
portfolio_manager.py — Modulo di Sintesi e Integrazione Dual-Engine (APEX CONVEX)
==================================================================================
Principi Guida: Lean, Frictionless, Robusto.
Combina il motore tattico attivo (Apex Engine) con il motore strategico passivo (Convex Stack).
Consente l'aggiornamento dei parametri utente (campi compilabili salvati in config.json).
"""

from __future__ import annotations
import datetime
import json
import os
from typing import Dict, Any, Tuple
import pandas as pd
import numpy as np

import convex_engine

CONFIG_FILE = os.path.join(os.path.dirname(__file__), "config.json")
CONVEX_FILE = os.path.join(os.path.dirname(__file__), "convex_portfolio.json")

# Soglia di scostamento (punti percentuali) sopra la quale il segnale macro corrente
# e la composizione EFFETTIVAMENTE detenuta (fissata all'ultima decisione mensile
# eseguita) sono considerati "non ancora riallineati" — usata da page_apex.py e
# home_app.py per evitare di dichiarare "portafoglio allineato" nei giorni centrali
# del mese, quando i due possono divergere molto per disegno (decisione/esecuzione
# solo mensile, §6 di APEX_V2_SPEC.md) pur non essendoci ancora ordini in coda.
MID_CYCLE_DRIFT_THRESHOLD_PP = 10.0


def compute_apex_signal_drift_pct(open_positions: Dict[str, Any], signal_allocations: Dict[str, float]) -> float:
    """Scostamento massimo (punti percentuali) tra il peso Azioni/Crypto detenuto ORA
    in open_positions e quello richiesto dal segnale macro corrente signal_allocations.
    Unica fonte per questo calcolo — prima duplicato indipendentemente in page_apex.py
    e home_app.py, rischiando un disallineamento silenzioso tra le due pagine se una
    veniva aggiornata (es. per un bug fix) e l'altra no."""
    held_eq_pct = sum(
        v.get("weight", 0.0) * 100.0 for k, v in open_positions.items()
        if not v.get("is_crypto", False) and k not in ("GLD", "IEF")
    )
    held_cr_pct = sum(
        v.get("weight", 0.0) * 100.0 for k, v in open_positions.items() if v.get("is_crypto", False)
    )
    signal_allocations = signal_allocations or {}
    drift_eq = abs(signal_allocations.get("Equities", 0.0) - held_eq_pct)
    drift_cr = abs(signal_allocations.get("Crypto", 0.0) - held_cr_pct)
    return max(drift_eq, drift_cr)


ASSET_CLASSES_INFO = {
    "Azioni": {
        "color": "#3DDC97",
        "short_name": "Azioni",
        "svg": '<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="{style}"><polyline points="22 7 13.5 15.5 8.5 10.5 2 17"></polyline><polyline points="16 7 22 7 22 13"></polyline></svg>',
    },
    "Obbligazioni": {
        "color": "#4E80EE",
        "short_name": "Obbligazioni",
        "svg": '<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="{style}"><line x1="3" y1="21" x2="21" y2="21"></line><line x1="3" y1="10" x2="21" y2="10"></line><polyline points="5 6 12 3 19 6"></polyline><line x1="6" y1="10" x2="6" y2="21"></line><line x1="10" y1="10" x2="10" y2="21"></line><line x1="14" y1="10" x2="14" y2="21"></line><line x1="18" y1="10" x2="18" y2="21"></line></svg>',
    },
    "Futures gestiti": {
        "color": "#E07A5F",
        "short_name": "Futures gestiti",
        "svg": '<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="{style}"><circle cx="12" cy="12" r="10"></circle><polygon points="16.24 7.76 14.12 14.12 7.76 16.24 9.88 9.88 16.24 7.76"></polygon></svg>',
    },
    "Oro": {
        "color": "#E5B233",
        "short_name": "Oro",
        "svg": '<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="{style}"><polygon points="8.5 6 15.5 6 17 12 7 12" /><polygon points="2.5 13 9.5 13 11 19 1 19" /><polygon points="14.5 13 21.5 13 23 19 13 19" /></svg>',
    },
    "Cryptovalute": {
        "color": "#F7931A",
        "short_name": "Cryptovalute",
        "svg": '<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="{style}"><path d="M7 6h6a3 3 0 0 1 0 6H7zm0 6h7a3 3 0 0 1 0 6H7z"></path><line x1="10" y1="3" x2="10" y2="6"></line><line x1="14" y1="3" x2="14" y2="6"></line><line x1="10" y1="18" x2="10" y2="21"></line><line x1="14" y1="18" x2="14" y2="21"></line><line x1="7" y1="6" x2="7" y2="18"></line></svg>',
    },
    "Liquidità": {
        "color": "#8E877F",
        "short_name": "Liquidità",
        "svg": '<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="{style}"><rect x="2" y="6" width="20" height="12" rx="2"></rect><circle cx="12" cy="12" r="2.5"></circle><line x1="6" y1="12" x2="6.01" y2="12"></line><line x1="18" y1="12" x2="18.01" y2="12"></line></svg>',
    },
}

CONVEX_INSTRUMENTS_METADATA = {
    "NTSG": {
        "isin": "IE00077IIPQ8",
        "name": "WisdomTree Global Efficient Core UCITS ETF",
        "exchange": "Borsa Italiana (MIL)",
        "currency": "EUR",
        "ter": 0.0025,
        "tax_regime": "Reddito di Capitale (non compensa minus)",
        "tax_type": "capitale",
        "target_weight": 0.45,
        "trim_threshold": None,
        "role": "Nucleo bilanciato globale a leva 1.5x (90% azionario globale + 60% Treasury USA tramite futures incorporati senza debito a margine)",
        "driver": "Equity Risk Premium + Term Premium con leva strutturale e rebalancing dividend yield.",
    },
    "AVWS": {
        "isin": "IE0003R87OG3",
        "name": "Avantis World Small Cap Value UCITS ETF",
        "exchange": "XETRA (FRA)",
        "currency": "EUR",
        "ter": 0.0039,
        "tax_regime": "Reddito di Capitale (non compensa minus)",
        "tax_type": "capitale",
        "target_weight": 0.15,
        "trim_threshold": None,
        "role": "Fattore Small Cap Value globale (esposizione Dimensional factor: Size + Value + Profitability)",
        "driver": "Premio accademico al fattore Value su titoli a bassa capitalizzazione e alta redditività.",
    },
    "DBMFE": {
        "isin": "LU2951555403",
        "name": "iMGP DBi Managed Futures Strategy UCITS",
        "exchange": "Euronext Paris (PAR)",
        "currency": "EUR",
        "ter": 0.0075,
        "tax_regime": "Reddito di Capitale (non compensa minus)",
        "tax_type": "capitale",
        "target_weight": 0.25,
        "trim_threshold": None,
        "role": "Trend-following sistematico multi-asset anti-crisi (Crisis Alpha che replica i 20 maggiori CTA mondiali)",
        "driver": "Long/Short sistematico su 40+ futures (valute, tassi, materie prime, indici) non correlato all'azionario.",
    },
    "PPFB": {
        "isin": "IE00B4ND3602",
        "name": "iShares Physical Gold ETC",
        "exchange": "London Stock Exchange (LSE) / XETRA",
        "currency": "EUR",
        "ter": 0.0012,
        "tax_regime": "Reddito Diverso (compensa minusvalenze)",
        "tax_type": "diverso",
        "target_weight": 0.075,
        "trim_threshold": 0.13125,
        "role": "Riserva di valore reale tangibile contro svalutazione monetaria e shock geopolitici sistemici",
        "driver": "Safe-haven reale senza rischio di credito. Vendita parziale disciplinata solo sopra il 13.13% (+75% target, verifica trimestrale).",
    },
    "WBTC": {
        "isin": "GB00BJYDH287",
        "name": "WisdomTree Physical Bitcoin",
        "exchange": "Borsa Italiana (MIL) / XETRA",
        "currency": "EUR",
        "ter": 0.0015,
        "tax_regime": "Reddito Diverso (compensa minusvalenze)",
        "tax_type": "diverso",
        "target_weight": 0.075,
        "trim_threshold": 0.13125,
        "role": "Convessità asimmetrica monetaria digitale e riserva antifragile a scarsità assoluta",
        "driver": "Rendimenti asimmetrici esponenziali. Trim disciplinato sopra il 13.13% (+75% target, verifica trimestrale) per monetizzare i run rialzisti e riallocare a costo zero.",
    },
}

def get_macro_class_svg(classe: str, size: int = 15, color: str = None, style: str = "") -> str:
    """Restituisce l'icona SVG vettoriale ufficiale e univoca per la classe di attivo."""
    inline_style = f"display:inline-block; vertical-align:middle; flex-shrink:0; {style}"
    c = str(classe).strip().lower()
    if "obbligazion" in c or "bond" in c or c.startswith("obblig"):
        key = "Obbligazioni"
    elif "azion" in c or "equity" in c or "stock" in c:
        key = "Azioni"
    elif "oro" in c or "gold" in c:
        key = "Oro"
    elif "btc" in c or "bitcoin" in c or "crypto" in c or "cryptovalute" in c:
        key = "Cryptovalute"
    elif "future" in c or "cta" in c or "managed" in c:
        key = "Futures gestiti"
    elif "liquid" in c or "cash" in c:
        key = "Liquidità"
    else:
        key = "Liquidità"

    info = ASSET_CLASSES_INFO.get(key, ASSET_CLASSES_INFO.get("Cryptovalute" if "btc" in key.lower() or "crypto" in key.lower() else "Liquidità"))
    use_color = color if color is not None else info["color"]
    return info["svg"].format(size=size, color=use_color, style=inline_style)


def get_class_color(classe: str) -> str:
    """Restituisce il colore univoco ufficiale per ciascuna classe di attivo."""
    c = str(classe).strip().lower()
    if "obbligazion" in c or "bond" in c or c.startswith("obblig"):
        return ASSET_CLASSES_INFO["Obbligazioni"]["color"]
    elif "azion" in c or "equity" in c or "stock" in c:
        return ASSET_CLASSES_INFO["Azioni"]["color"]
    elif "oro" in c or "gold" in c:
        return ASSET_CLASSES_INFO["Oro"]["color"]
    elif "btc" in c or "bitcoin" in c or "crypto" in c or "cryptovalute" in c:
        return ASSET_CLASSES_INFO["Cryptovalute"]["color"]
    elif "future" in c or "cta" in c or "managed" in c:
        return ASSET_CLASSES_INFO["Futures gestiti"]["color"]
    elif "liquid" in c or "cash" in c:
        return ASSET_CLASSES_INFO["Liquidità"]["color"]
    return ASSET_CLASSES_INFO["Liquidità"]["color"]


def clean_crypto_ticker(sym: Any) -> str:
    """Restituisce il solo ticker standard della cryptovaluta (es. BTC, ETH, SOL, LUNC).

    Rimuove suffissi di coppia come -USD e normalizza denominazioni estese (es. Bitcoin Core Ballast -> BTC).
    """
    if sym is None or pd.isna(sym):
        return ""
    s = str(sym).strip()
    s_upper = s.upper()
    if s_upper in ("BITCOIN", "BITCOIN CORE BALLAST", "BITCOIN CORE", "BTC-USD", "BTC", "CORE BALLAST", "BALLAST"):
        return "BTC"
    if s_upper in ("ETHEREUM", "ETH-USD", "ETH"):
        return "ETH"
    if s_upper in ("SOLANA", "SOL-USD", "SOL"):
        return "SOL"
    if s_upper.endswith("-USD"):
        return s_upper[:-4]
    return s



def get_default_convex_holdings_100k(prices: Dict[str, float] = None, target_capital: float = 100000.0) -> Dict[str, Any]:
    """
    Calcola le quote di default per un capitale standard di 100.000 € in Convex Stack
    perfettamente allineato ai pesi target (NTSG 45%, AVWS 15%, DBMFE 25%, PPFB 7.5%, WBTC 7.5%).
    La liquidita residua non allocata in quote intere viene assegnata alla cassa fino a raggiungere esattamente 100.000 €.
    """
    base_prices = {"NTSG": 28.69, "AVWS": 25.64, "DBMFE": 123.50, "PPFB": 75.15, "WBTC": 16.60}
    p = {**base_prices, **(prices or {})}
    
    target_weights = {"NTSG": 0.45, "AVWS": 0.15, "DBMFE": 0.25, "PPFB": 0.075, "WBTC": 0.075}
    shares = {}
    for k, w in target_weights.items():
        price = max(0.01, float(p.get(k, base_prices.get(k, 1.0))))
        shares[k] = int((target_capital * w) / price)
        
    invested = sum(shares[k] * float(p.get(k, base_prices.get(k, 1.0))) for k in shares)
    cash = max(0.0, target_capital - invested)
    return {
        "cash_eur": round(cash, 2),
        "holdings": {k: {"shares": float(shares[k]), "last_price": float(p.get(k, base_prices.get(k, 1.0)))} for k in shares},
        "last_updated": datetime.date.today().strftime("%Y-%m-%d")
    }


def load_config() -> Dict[str, Any]:
    """Carica la configurazione utente persistita o restituisce i valori standard."""
    defaults = {
        "apex_capital_eur": 100000.0,
        "convex_capital_eur": 100000.0,
        "monthly_pac_eur": 500.0,
        "pac_annual_growth": 0.04,
        "target_apex_ratio": 0.70,
        "target_convex_ratio": 0.30,
        "last_updated": "2026-09-14"
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                data = json.load(f)
                defaults.update(data)
        except Exception:
            pass
    return defaults


def save_config(config_dict: Dict[str, Any]) -> bool:
    """Salva i parametri compilabili dell'utente in config.json."""
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(config_dict, f, indent=4)
        return True
    except Exception:
        return False


def load_convex_portfolio(prices: Dict[str, float] = None) -> Dict[str, Any]:
    """Carica le posizioni attuali dei 5 asset in Convex Stack. Se assenti o vuote, restituisce il default istituzionale da 100k €."""
    if os.path.exists(CONVEX_FILE):
        try:
            with open(CONVEX_FILE, "r") as f:
                data = json.load(f)
                h = data.get("holdings", {})
                if bool(h) and any(v.get("shares", 0.0) > 0 for v in h.values()):
                    return data
        except Exception:
            pass
    return get_default_convex_holdings_100k(prices)


def save_convex_portfolio(data: Dict[str, Any]) -> bool:
    """Salva le posizioni di Convex Stack."""
    try:
        with open(CONVEX_FILE, "w") as f:
            json.dump(data, f, indent=4)
        return True
    except Exception:
        return False



# ==============================================================================
# METRICHE REALI CALCOLATE — sostituiscono i placeholder fabbricati precedenti
# ==============================================================================
# Fonte: backtest effettivi, non stime. Calcolate il 2026-09-02.
#   - Apex: motore di produzione (compute_v2_macro_signal, apex_v2_engine.py),
#     esecuzione settimanale reale (decisione venerdi', esecuzione lunedi',
#     nessuno stop-loss, crypto solo BTC — configurazione validata come migliore
#     dopo aver testato 6+ meccanismi di protezione nella sessione di ricerca
#     principale; ogni altro meccanismo provato peggiora Sharpe e/o MaxDD).
#     Serie mensile NETTA (tasse italiane 26% CGT + riporto minusvalenze 4 anni
#     GIA' applicate anno per anno nel motore, essendo Apex una strategia a
#     trading attivo con realizzo annuale).
#   - Convex: catena di proxy corretta (pesi di capitale corretti: NTSG 45%/
#     AVWS 15%/DBMFE 25%/PPFB 7.5%/WBTC 7.5%, NON i pesi nozionali 67.5%/ecc.
#     erroneamente usati nello script originale; TER corretto 0.3788%/anno;
#     SENZA l'estensione Fama-French fino al 1963, che si è rivelata rumore
#     gaussiano iniettato per ~18%+ anche nel caso migliore, non storia reale).
#     Serie mensile LORDA per costruzione (l'IPS di Convex prevede zero vendite
#     — ribilanciamento solo tramite nuovi versamenti — quindi le tasse sono
#     differite alla vendita finale, non realizzate anno per anno come in Apex).
#     Per un confronto onesto qui viene mostrato un valore "netto" APPROSSIMATO
#     (haircut del 26% sulla plusvalenza cumulata dell'intera finestra) — è
#     una stima, non una simulazione fiscale posizione-per-posizione.
#   - Finestra comune reale a entrambe le serie: 2014-11 -> 2026-08 (142 mesi).
#     Limitata da BTC-USD (2014-09+, usato sia nel segnale macro Apex sia nella
#     sleeve WBTC di Convex) e dalla disponibilita' di dati point-in-time.
#   - Metodologia completa, script e dati grezzi: research/convex/ in
#     MasterStrategyApp (apex_convex_correlation.py, convex_phase2_full.py,
#     final_dashboard_stats.pkl).
# Se questi numeri non vengono più aggiornati con un nuovo backtest, NON
# aggiungere valori "a occhio" — ricalcolare con gli script sopra o segnalare
# esplicitamente il dato come stimato/non aggiornato.
# ==============================================================================

# ==============================================================================
# PERCHE' SOLO IL PERIODO TEST (fuori campione) — non piu' 2014-2026/2000-2026
# ==============================================================================
# Correzione importante: le metriche restituite qui erano prima calcolate sulla
# finestra COMPLETA (Apex 2014-11/2026-08, Convex 2000-09/2026-08), che include
# sia il periodo usato per SCEGLIERE i parametri della strategia (TRAIN) sia il
# periodo mai visto durante quella scelta (TEST) — mescolati senza distinzione,
# quindi ottimisticamente distorti rispetto a una vera prova fuori campione.
# Ora restituiscono SOLO il periodo TEST, lo stesso standard walk-forward gia'
# usato in tutta la ricerca di questo progetto (vedi APEX_V2_SPEC.md §8.25 e
# research/convex/convex_optimize_v2.py):
#   - Apex: TRAIN 1987-06-30 -> 2020-08-31 (399 mesi), TEST 2020-09-30 ->
#     2026-08-31 (72 mesi). Storia TRAIN estesa da 2014-11 a 1987-06 (vedi
#     apex_dashboard_stat_regeneration.py, richiesto dall'utente "vai il piu'
#     indietro possibile usando i migliori proxy" — VFINX/VUSTX/GC=F raccordati
#     con SPY/IEF/GLD reali; selezione azionaria per singolo titolo resta
#     vincolata al 2012+ per onesta' point-in-time, prima usa il rendimento
#     dell'indice proxy stesso). Le cifre TEST period sotto sono IDENTICHE a
#     prima dell'estensione (verificato) — lo split 2020-09-30 e' a valle di
#     tutta la storia estesa, nessun effetto sulla finestra mostrata.
#   - Convex: la validazione dei pesi 45/15/25/7.5/7.5 in convex_optimize_v2.py
#     usa TRAIN 2000-09-30 -> 2013-09-30, TEST 2013-10-31 -> 2026-08-31 (155
#     mesi, tutti fuori campione). La cifra MOSTRATA in dashboard pero' usa un
#     SOTTOINSIEME di quel TEST period, 2020-09-30 -> 2026-08-31 (72 mesi) —
#     la stessa identica finestra di Apex e del combinato, non i 155 mesi
#     interi: le tre cifre affiancate devono condividere la stessa finestra o
#     il confronto tra loro (e il combinato che sembra "battere" una delle due
#     componenti) diventa fuorviante, anche se ciascuna singola cifra resta
#     onestamente fuori campione. Ricalcolato da convex_monthly_returns.csv
#     (lorda per costruzione — Convex non vende se non per rari trim).
#     cagr_net resta l'approssimazione dichiarata (haircut 26% sulla
#     plusvalenza cumulata del periodo mostrato, non una simulazione fiscale
#     posizione-per-posizione).
#
# ECCEZIONE DICHIARATA: max_drawdown_storico. La tile "Calo Massimo Storico"
# in dashboard afferma testualmente "il calo peggiore MAI vissuto/registrato"
# — un'affermazione sull'INTERO storico, non sulla sola finestra TEST. Prima
# della correzione qui sotto, quella tile mostrava il MaxDD della finestra
# TEST (72 mesi) pur affermando "mai" — un numero che non supportava la
# propria etichetta, e che non coincideva con il grafico storico esteso
# sotto di essa (Apex 1987-06+, Convex 1987-12+, Combinato 1987-12+),
# segnalato dall'utente come inconsistenza. Ogni funzione sotto espone quindi
# un secondo campo, max_drawdown_storico, calcolato sull'INTERO storico
# disponibile (stessa serie del grafico) — unico campo qui che rompe
# deliberatamente la convenzione "solo TEST period": la propria etichetta
# in dashboard lo richiede per essere vera.
# ==============================================================================

def get_apex_metrics() -> Dict[str, Any]:
    """Metriche reali di Apex Engine sul solo periodo di validazione fuori
    campione (TEST 2020-09-30 -> 2026-08-31, 72 mesi mai usati per scegliere
    i parametri della strategia) — vedi nota sopra per la metodologia.
    Le metriche di rischio (sharpe/sortino/max_drawdown/calmar/volatility)
    sono calcolate sulla serie LORDA (apex_monthly_returns_extended_gross.csv,
    stesso TEST period) -- coerenti con equity.json/il grafico, che non
    modella alcuna tassa, ed E' la cifra primaria mostrata in dashboard
    (convenzione lordo-primario/netto-stimato-secondario). I campi
    *_netto_stimato usano invece la serie netta (apex_monthly_returns_extended.csv,
    tasse italiane reali modellate anno per anno) -- una stima più rigorosa
    dell'haircut fisso usato per Convex, ma pur sempre calcolata su un
    backtest di ricerca separato dalla curva live, non identica ad essa.
    Rigenerate con select_low_beta_basket e storia estesa a 1987-06 (proxy
    VFINX/VUSTX/GC=F) — vedi apex_dashboard_stat_regeneration.py e
    validation_suite/README.md. Le cifre del periodo TEST sono identiche a
    prima dell'estensione storica (split 2020-09-30 a valle, non impattato).

    Rigenerate una seconda volta dopo l'adozione della pesatura Kelly
    frazionaria tra le classi macro attive (APEX_V2_SPEC.md §8.30,
    kelly_fraction=0.25/kelly_window=208 settimane, default di
    compute_v2_macro_signal — vedi apex_v2_engine.py): il miglioramento e'
    netto su tutto il periodo TEST (Sharpe 1.245->1.675 con l'universo
    dell'epoca, vedi sotto per il numero corretto).

    **Rigenerate una TERZA volta dopo la scoperta e correzione (parziale)
    del survivorship bias nell'universo azionario** (audit di robustezza
    istituzionale — vedi validation_suite/README.md, sezione "Test di
    robustezza e invalidazione istituzionale completo"):
    `select_low_beta_basket` pescava da un universo prezzi costruito dai
    membri ATTUALI dell'S&P 500, non dall'unione dei membri storici — un
    titolo delistato/acquisito/rimosso dall'indice era invisibile al
    backtest anche se eleggibile quell'anno (45% dei membri eleggibili
    2012 senza alcun file prezzo). Corretto con
    fetch_delisted_sp500_prices.py (copertura storica dal 60.9% al 77.8%
    — non al 100%: Yahoo Finance non serve piu' storico per titoli
    delistati troppo vecchi o con simbolo purgato; altre 3 fonti gratuite
    testate e scartate, vedi README). Effetto sul periodo TEST: **Sharpe
    1.675->1.380, MaxDD -10.44%->-10.59%, CAGR lordo 24.66%->20.18%** —
    la correzione ha ridotto le cifre mostrate, confermando che il bias
    le gonfiava. Griglia di sensibilita' e PBO-CSCV (9 varianti,
    apex_v2_sensitivity_grid.py) ripetuti sull'universo corretto: PBO-CSCV
    37.1% (sotto la soglia di rumore — il ranking resta riproducibile),
    range di Sharpe 1.334-1.415 (nessun collasso vicino ai parametri di
    produzione).

    **Rigenerate una QUARTA volta correggendo 2 dei 4 concern residui
    dell'audit qualitativo** (richiesto dall'utente: "parti con i 4
    concern"; vedi validation_suite/README.md): (1) una fuga same-bar nel
    ribasket trimestrale — il basket appena ricostruito con beta calcolata
    fino alla settimana wk ne guadagnava anche il rendimento, invece di
    iniziare dalla settimana successiva; (2) il costo di transazione sul
    turnover INTERNO del basket di 15 titoli (rotazione trimestrale a
    parita' di peso di classe), invisibile al turnover di classe
    aggregato e mancante nel backtest pur essendo gia' caricato dal
    sistema live (backend.update_portfolio, 10bps). Effetto sul periodo
    TEST: **Sharpe 1.380->1.36, CAGR lordo 20.18%->19.61%, MaxDD
    -10.59%->-10.44%** (leggermente migliore: rimuovere il vantaggio
    same-bar riduce anche un po' di rumore favorevole).

    **Rigenerate una QUINTA volta integrando il motore Crypto Frontier Venture
    nello slot Crypto** (architettura Dual-Regime Bitcoin Core + Altseason
    Breakout Satellite Top 25, validata 2018-2026):
    ante-2018 timing macro Bitcoin Core, dal 2018-10 motore Frontier Venture
    completo con 7 slot liquidi Top 25, breakout Donchian 30d, stop ATR 2.5x,
    stagnation time-stop a 21 giorni, de-risking free-ride al +125% e trailing
    stop post-de-risking al -30%. Serie primaria LORDA con tax_enabled=False,
    serie netta con fiscalità italiana al 26% e zainetto fiscale.
    Effetto sul periodo TEST (72 mesi OOS): **CAGR lordo 19.61%->21.84%,
    Sharpe 1.36->1.474, Sortino 2.35->2.456, Calmar 1.88->1.898, Ulcer Index
    3.62->3.93**. Il Max Drawdown OOS resta rigorosamente controllato a -11.51%
    e il Max Drawdown storico multi-decennale (1987-2026) resta a -14.83%.

    **Rigenerate una SESTA volta correggendo un bug reale in
    apex_dashboard_stat_regeneration.py** (`import os` mancante a livello di
    modulo, causava un NameError inghiottito silenziosamente da un
    try/except che faceva ricadere l'intera classe Crypto su rendimenti
    BTC-only, escludendo il motore Frontier Venture dall'intera serie senza
    alcun segnale visibile — la rigenerazione precedente che produsse i
    numeri sopra era quindi anch'essa silenziosamente degradata). Effetto
    sul periodo TEST reincludendo correttamente il motore: **CAGR lordo
    21.84%->21.10%, Sharpe 1.474->1.361, Sortino 2.456->2.250, Calmar
    1.898->1.871, Ulcer Index 3.93->6.21** (volatilita' e drawdown piu'
    realistici del vero motore di rotazione altcoin rispetto al proxy
    BTC-only che li sottostimava). Il Max Drawdown storico multi-decennale
    ricalcolato sull'intera serie 1987-2026 coincide ora con quello del solo
    periodo TEST (-11.28%): il calo peggiore dell'intera storia e' avvenuto
    proprio dentro la finestra OOS piu' recente, non prima."""
    return {
        "name": "Apex Engine (Tattico Alpha)",
        "cagr_net": 0.1554,
        "cagr_gross": 0.2110,
        "volatility": 0.1497,
        "sharpe": 1.361,
        "sortino": 2.250,
        "max_drawdown": -0.1128,
        "max_drawdown_storico": -0.1128,
        "calmar": 1.871,
        "ulcer_index": 6.21,
        "volatility_netto_stimato": 0.1385,
        "sharpe_netto_stimato": 1.116,
        "sortino_netto_stimato": 1.830,
        "max_drawdown_netto_stimato": -0.1655,
        "calmar_netto_stimato": 0.939,
        "test_period": "2020–2026 (72 mesi)",
        "storico_period": "1987–2026 (471 mesi)",
        "cash_drag_protection": "100% Liquidità remunerata a tassi governativi T-Bill 3M nelle fasi orso",
        "philosophy": "Selezione trimestrale di 15 azioni stabili dell'S&P 500, gestione dei trend macro con filtri anti-rumore, allocazione ponderata tra le classi attive e motore crypto a controllo del rischio."
    }


def get_convex_metrics() -> Dict[str, Any]:
    """Metriche reali di Convex Stack sul periodo di validazione fuori campione."""
    return {
        "name": "Convex Stack (Strategico PAC)",
        "cagr_net": 0.1356,
        "cagr_gross": 0.1688,
        "volatility": 0.1304,
        "sharpe": 1.252,
        "sortino": 1.519,
        "max_drawdown": -0.1576,
        "max_drawdown_storico": -0.2116,
        "calmar": 1.071,
        "ulcer_index": 3.79,
        "test_period": "2020–2026 (72 mesi)",
        "storico_period": "1987–2026 (465 mesi)",
        "embedded_leverage": "Esposizione amplificata a 1.225x senza debito personale",
        "philosophy": "Esposizione efficiente su azioni e bond mondiali (NTSG 45%), piccole aziende di valore (AVWS 15%), protezione attiva nelle crisi (DBMFE 25%) e riserve reali in Oro fisico e Bitcoin (7.5% ciascuno)."
    }


def get_combined_dual_engine_metrics() -> Dict[str, Any]:
    """Metriche reali della combinazione APEX+CONVEX al mix target STANDARD 70/30.

    Ricalcolate insieme al sesto ciclo di get_apex_metrics() (correzione del bug
    import-os che escludeva silenziosamente il motore Crypto Frontier Venture —
    vedi il docstring di get_apex_metrics()). Ricalcolate inoltre al vero mix
    70/30 (apex_dashboard_stat_regeneration.py calcolava qui un blend 50/50,
    disallineato dal target_apex_ratio=0.70 di default in config.json e dal
    "70/30 STANDARD" gia' dichiarato in questo stesso docstring — bug corretto)."""
    return {
        "name": "APEX CONVEX (Dual-Engine)",
        "cagr_net": 0.1457,
        "cagr_gross": 0.2009,
        "volatility": 0.1217,
        "sharpe": 1.574,
        "sortino": 3.072,
        "max_drawdown": -0.0778,
        "max_drawdown_storico": -0.0957,
        "calmar": 2.583,
        "ulcer_index": 2.98,
        "correlation": 0.280,
        "test_period": "2020–2026 (72 mesi)",
        "storico_period": "1987–2026 (465 mesi)",
        "synergy_summary": (
            "Unire il 70% di Apex Engine e il 30% di Convex Stack massimizza il rendimento riducendo al minimo i rischi: "
            "il portafoglio genera un rendimento del +20,09% medio annuo lordo (+14,57% netto stimato), con una perdita "
            "massima contenuta ad appena il -7,78% negli ultimi 6 anni e al -9,57% nell'intero storico dal 1987. "
            "Un risultato nettamente più sicuro rispetto ai singoli motori presi da soli, grazie alla bassissima "
            "correlazione (0,28) che consente alle due strategie di compensarsi a vicenda."
        )
    }


def compute_unified_portfolio(
    apex_val: float,
    convex_report: convex_engine.ConvexPortfolioReport,
    monthly_pac: float = 500.0,
    target_apex_ratio: float = 0.70,
    apex_allocations: Dict[str, float] = None
) -> Dict[str, Any]:
    """
    Consolida il patrimonio totale e genera la vista unificata ad alto livello.

    apex_allocations: pesi REALI correnti di Apex per classe, nella stessa scala
    0-100 di apex_data.json["allocations"] (es. {"Equities": 32.65, "Bonds": 0.0,
    "Gold": 0.0, "Crypto": 32.65, "Cash": 34.7}). Sommano sempre a 100 perché Apex
    non usa leva — a differenza di Convex, dove la leva incorporata di NTSG fa
    sommare l'esposizione nozionale oltre il 100% del capitale.
    Se None (dato live non disponibile), usa un fallback esplicito — MAI un dato
    fabbricato spacciato per reale.
    """
    APEX_ALLOC_FALLBACK_USED = apex_allocations is None
    if apex_allocations is None:
        # Fallback esplicito, solo se il dato live non è disponibile — non è
        # una stima di Apex, è un placeholder dichiarato tale a chi legge.
        apex_allocations = {"Equities": 65.0, "Bonds": 15.0, "Gold": 10.0, "Crypto": 10.0, "Cash": 0.0}
    convex_val = convex_report.total_value
    tot_wealth = apex_val + convex_val
    if tot_wealth <= 0:
        tot_wealth = 1.0

    current_apex_w = apex_val / tot_wealth
    current_convex_w = convex_val / tot_wealth

    # Se Apex è sotto il target (es. < 40%), consiglia di dirigere parte del PAC
    # verso Apex; altrimenti versa normalmente in Convex Stack sull'asset più
    # sottopesato (la stessa logica di convex_engine.evaluate_convex_stack).
    smart_flow_note = ""
    smart_flow_destination = "Convex Stack"
    equilibrio_note = f"I due motori sono in equilibrio ({current_apex_w*100:.1f}% Apex / {current_convex_w*100:.1f}% Convex)."
    if monthly_pac <= 0:
        # Nessun versamento impostato per questo mese — non c'è nulla da
        # consigliare (né qui né sotto: convex_report.pac_action è None in
        # questo caso, va gestito esplicitamente per non andare in crash).
        smart_flow_destination = "Nessuno"
        smart_flow_note = "Nessun versamento PAC impostato per questo mese — nessuna azione da consigliare."
    elif current_apex_w < (target_apex_ratio - 0.05):
        smart_flow_destination = "Apex Engine (o metà e metà)"
        smart_flow_note = (
            f"Apex Engine è sottopesato ({current_apex_w*100:.1f}% contro un obiettivo del {target_apex_ratio*100:.1f}%). "
            f"Versa la rata mensile di {monthly_pac:.0f} € su Apex Engine (oppure metà e metà) "
            f"per riequilibrare l'allocazione tramite nuovi apporti di liquidità."
        )
    elif convex_report.pac_action is not None:
        smart_flow_note = (
            f"{equilibrio_note} "
            f"Versa l'intera rata di {monthly_pac:.0f} € su Convex Stack, acquistando "
            f"{convex_report.pac_action.recommended_asset} ({convex_report.pac_action.estimated_shares} quote)."
        )
    else:
        # monthly_pac > 0 ma pac_action è comunque None (es. tutti gli
        # strumenti già al target esatto) — non c'è nulla da consigliare, non
        # è un errore da nascondere con un crash.
        smart_flow_note = f"{equilibrio_note} Nessun asset risulta sottopesato al momento."

    # Raggi X aggregati delle macro-asset class su tutto il patrimonio.
    # Apex: pesi REALI correnti (v. apex_allocations sopra) — mai sommano oltre
    # il 100% del capitale Apex, perché Apex non usa leva. Possono includere
    # una quota di Cash reale anche ampia (fino al 100% nei bear market macro).
    apex_eq  = apex_val * (apex_allocations.get("Equities", 0.0) / 100.0)
    apex_bd  = apex_val * (apex_allocations.get("Bonds", 0.0) / 100.0)
    apex_gld = apex_val * (apex_allocations.get("Gold", 0.0) / 100.0)
    apex_cr  = apex_val * (apex_allocations.get("Crypto", 0.0) / 100.0)
    apex_cash = apex_val * (apex_allocations.get("Cash", 0.0) / 100.0)

    # Convex: da convex_report.macro_exposure. Queste 5 categorie sommano a
    # ~122.5% del capitale Convex (NON un bug — è la leva 1.5x di NTSG,
    # interamente incorporata nell'ETF, nessun debito a margine personale).
    conv_eq  = convex_val * convex_report.macro_exposure["Azionario Globale (Large/Mid + Small SCV)"]
    conv_bd  = convex_val * convex_report.macro_exposure["Obbligazionario Governativo (Treasury Futures)"]
    conv_cta = convex_val * convex_report.macro_exposure["Managed Futures (Crisis Alpha CTA)"]
    conv_gld = convex_val * convex_report.macro_exposure["Oro Fisico (Riserva Reale)"]
    conv_cr  = convex_val * convex_report.macro_exposure.get("Cryptovalute (Convessità Asimmetrica)", 0.0)
    conv_cash = convex_val * convex_report.macro_exposure.get("Liquidità Cassa", 0.0)

    macro_breakdown = {
        "Azioni": (apex_eq + conv_eq) / tot_wealth,
        "Obbligazioni": (apex_bd + conv_bd) / tot_wealth,
        "Futures gestiti": conv_cta / tot_wealth,
        "Oro": (apex_gld + conv_gld) / tot_wealth,
        "Cryptovalute": (apex_cr + conv_cr) / tot_wealth,
    }
    # Liquidità reale (mai negativa) ed esposizione nozionale totale (può
    # legittimamente superare il 100% per via della leva incorporata di Convex)
    # sono due numeri concettualmente diversi — non vanno confusi in un'unica
    # voce "resto" che prima si azzerava silenziosamente quando negativa.
    idle_cash_pct = (apex_cash + conv_cash) / tot_wealth
    total_notional_pct = sum(macro_breakdown.values()) + idle_cash_pct

    return {
        "total_wealth_eur": tot_wealth,
        "apex_value_eur": apex_val,
        "convex_value_eur": convex_val,
        "apex_weight": current_apex_w,
        "convex_weight": current_convex_w,
        "target_apex_ratio": target_apex_ratio,
        "smart_flow_destination": smart_flow_destination,
        "smart_flow_note": smart_flow_note,
        "macro_breakdown": macro_breakdown,
        "idle_cash_pct": idle_cash_pct,
        "total_notional_pct": total_notional_pct,
        "apex_allocation_is_fallback": APEX_ALLOC_FALLBACK_USED
    }


def load_apex_contiguous_history() -> pd.DataFrame:
    """
    Carica la serie storica lorda di Apex Engine (471 mesi 1987-06 -> 2026-08)
    e raccorda in modo contiguo (senza salti o scalini) gli eventuali dati di operatività
    reale (live) registrati a partire dal 14 settembre 2026.
    Restituisce un DataFrame con colonne ['return', 'value', 'roll_max', 'drawdown'].
    """
    base_dir = os.path.dirname(__file__)
    apex_file = os.path.join(base_dir, "apex_monthly_returns_extended_gross.csv")
    if not os.path.exists(apex_file):
        return pd.DataFrame()

    apex_ret = pd.read_csv(apex_file, index_col=0, parse_dates=True).iloc[:, 0]
    df_apex = pd.DataFrame({"return": apex_ret})
    df_apex["value"] = (1.0 + apex_ret).cumprod() * 100.0

    # Raccordo contiguo con equity.json per eventuali registrazioni live dal 2026-09-14 in poi
    eq_file = os.path.join(base_dir, "equity.json")
    if os.path.exists(eq_file):
        try:
            with open(eq_file, "r") as f:
                eq_data = json.load(f)
            hist = eq_data.get("history", [])
            live_entries = [h for h in hist if h.get("date", "") >= "2026-09-14" and h.get("value", 0) > 0]
            if live_entries:
                v_bt_last = df_apex["value"].iloc[-1]
                v_live_base = live_entries[0]["value"]
                for e in live_entries:
                    dt = pd.to_datetime(e["date"])
                    val_contiguous = v_bt_last * (e["value"] / v_live_base)
                    df_apex.loc[dt, "value"] = val_contiguous
                df_apex = df_apex.sort_index()
                df_apex["return"] = df_apex["value"].pct_change().fillna(df_apex["return"].iloc[0])
        except Exception:
            pass

    df_apex["roll_max"] = df_apex["value"].cummax()
    df_apex["drawdown"] = (df_apex["value"] - df_apex["roll_max"]) / df_apex["roll_max"] * 100.0
    return df_apex


def load_convex_contiguous_history() -> pd.DataFrame:
    """
    Carica la serie storica lorda di Convex Stack (465 mesi 1987-12 -> 2026-08)
    e raccorda in modo contiguo gli eventuali dati di operatività reale a partire dal
    14 settembre 2026.
    Restituisce un DataFrame con colonne ['return', 'value', 'roll_max', 'drawdown'].
    """
    base_dir = os.path.dirname(__file__)
    conv_file = os.path.join(base_dir, "convex_monthly_returns.csv")
    if not os.path.exists(conv_file):
        return pd.DataFrame()

    cx_ret = pd.read_csv(conv_file, index_col=0, parse_dates=True).iloc[:, 0]
    df_cx = pd.DataFrame({"return": cx_ret})
    df_cx["value"] = (1.0 + cx_ret).cumprod() * 100.0

    # Raccordo contiguo con l'operativita' reale dal 14 settembre 2026 in poi
    live_dt = pd.Timestamp("2026-09-14")
    if live_dt > df_cx.index[-1]:
        df_cx.loc[live_dt, "value"] = df_cx["value"].iloc[-1]
        df_cx.loc[live_dt, "return"] = 0.0
        df_cx = df_cx.sort_index()

    df_cx["roll_max"] = df_cx["value"].cummax()
    df_cx["drawdown"] = (df_cx["value"] - df_cx["roll_max"]) / df_cx["roll_max"] * 100.0
    return df_cx


def load_combined_monthly_history(target_apex: float = 0.50, target_convex: float = 0.50) -> pd.DataFrame:
    """
    Carica le serie storiche contigue di Apex Engine (471 mesi dal 1987-06 al 2026-08,
    estendibile con i dati live dal 2026-09-14) e di Convex Stack (465 mesi dal 1987-12
    al 2026-08), e genera la serie di rendimenti e NAV Base 100 del portafoglio combinato
    sull'intersezione delle due. Lettura da disco ad ogni chiamata, nessuna cache.
    """
    df_apex = load_apex_contiguous_history()
    df_cx = load_convex_contiguous_history()

    if df_apex.empty or df_cx.empty:
        return pd.DataFrame()

    common = df_apex.index.intersection(df_cx.index)
    if len(common) == 0:
        return pd.DataFrame()

    comb_ret = target_apex * df_apex["return"].loc[common] + target_convex * df_cx["return"].loc[common]
    df_comb = pd.DataFrame({"return": comb_ret})
    df_comb["value"] = (1.0 + comb_ret).cumprod() * 100.0
    df_comb["roll_max"] = df_comb["value"].cummax()
    df_comb["drawdown"] = (df_comb["value"] - df_comb["roll_max"]) / df_comb["roll_max"] * 100.0
    return df_comb


def load_monthly_benchmark_spy(start_date=None) -> pd.Series:
    """
    Carica lo storico mensile del benchmark SPY (1993–2026) da file locale statico.
    Garantisce allineamento temporale al 100%, zero latenza e zero chiamate di rete a runtime.
    """
    base_dir = os.path.dirname(__file__)
    path = os.path.join(base_dir, "spy_monthly_history.csv")
    if not os.path.exists(path):
        return pd.Series(dtype=float)
    try:
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        s = df["Close"].dropna()
        if start_date is not None:
            start_ts = pd.to_datetime(start_date)
            s = s[s.index >= start_ts]
        return s
    except Exception:
        return pd.Series(dtype=float)




if __name__ == "__main__":
    cfg = load_config()
    holdings = {
        "NTSG": 500, "AVWS": 300, "DBMFE": 1000, "PPFB": 150, "WBTC": 75
    }
    prices = {"NTSG": 100.0, "AVWS": 50.0, "DBMFE": 25.0, "PPFB": 50.0, "WBTC": 100.0}
    c_rep = convex_engine.evaluate_convex_stack(holdings, prices, monthly_pac_eur=cfg["monthly_pac_eur"])
    unified = compute_unified_portfolio(cfg["apex_capital_eur"], c_rep, cfg["monthly_pac_eur"], cfg["target_apex_ratio"])

    print("Test rapido portfolio_manager.py:")
    print(f"Patrimonio Totale Consolidato: € {unified['total_wealth_eur']:,.2f}")
    print(f"Allocazione Attuale: Apex {unified['apex_weight']*100:.1f}% | Convex {unified['convex_weight']*100:.1f}%")
    print("[OK] portfolio_manager.py operativo con successo!")


