"""
portfolio_manager.py — Modulo di Sintesi e Integrazione Dual-Engine (APEX CONVEX)
==================================================================================
Principi Guida: Lean, Frictionless, Robusto.
Combina il motore tattico attivo (Apex Engine) con il motore strategico passivo (Convex Stack).
Consente l'aggiornamento dei parametri utente (campi compilabili salvati in config.json).
"""

from __future__ import annotations
import json
import os
from typing import Dict, Any, Tuple
import pandas as pd
import numpy as np

import convex_engine

CONFIG_FILE = os.path.join(os.path.dirname(__file__), "config.json")
CONVEX_FILE = os.path.join(os.path.dirname(__file__), "convex_portfolio.json")


ASSET_CLASSES_INFO = {
    "Azionario Globale & USA": {
        "color": "#3DDC97",
        "short_name": "Azionario",
        "svg": '<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="{style}"><polyline points="22 7 13.5 15.5 8.5 10.5 2 17"></polyline><polyline points="16 7 22 7 22 13"></polyline></svg>',
    },
    "Obbligazionario Governativo": {
        "color": "#8B7FC7",
        "short_name": "Obbligazioni",
        "svg": '<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="{style}"><line x1="3" y1="21" x2="21" y2="21"></line><line x1="3" y1="10" x2="21" y2="10"></line><polyline points="5 6 12 3 19 6"></polyline><line x1="6" y1="10" x2="6" y2="21"></line><line x1="10" y1="10" x2="10" y2="21"></line><line x1="14" y1="10" x2="14" y2="21"></line><line x1="18" y1="10" x2="18" y2="21"></line></svg>',
    },
    "Managed Futures (CTA)": {
        "color": "#E0A96D",
        "short_name": "Managed Futures",
        "svg": '<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="{style}"><circle cx="12" cy="12" r="10"></circle><polygon points="16.24 7.76 14.12 14.12 7.76 16.24 9.88 9.88 16.24 7.76"></polygon></svg>',
    },
    "Oro Fisico": {
        "color": "#C9A44C",
        "short_name": "Oro",
        "svg": '<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="{style}"><polygon points="8.5 6 15.5 6 17 12 7 12" /><polygon points="2.5 13 9.5 13 11 19 1 19" /><polygon points="14.5 13 21.5 13 23 19 13 19" /></svg>',
    },
    "Bitcoin": {
        "color": "#F7931A",
        "short_name": "Bitcoin",
        "svg": '<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="{style}"><path d="M7 6h6a3 3 0 0 1 0 6H7zm0 6h7a3 3 0 0 1 0 6H7z"></path><line x1="10" y1="3" x2="10" y2="6"></line><line x1="14" y1="3" x2="14" y2="6"></line><line x1="10" y1="18" x2="10" y2="21"></line><line x1="14" y1="18" x2="14" y2="21"></line><line x1="7" y1="6" x2="7" y2="18"></line></svg>',
    },
    "Liquidità": {
        "color": "#7A7266",
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
        "trim_threshold": 0.1125,
        "role": "Riserva di valore reale tangibile contro svalutazione monetaria e shock geopolitici sistemici",
        "driver": "Safe-haven reale senza rischio di credito. Vendita parziale disciplinata solo sopra l'11.25% (+50% target).",
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
        "trim_threshold": 0.1125,
        "role": "Convessità asimmetrica monetaria digitale e riserva antifragile a scarsità assoluta",
        "driver": "Rendimenti asimmetrici esponenziali. Trim automatico all'11.25% per monetizzare i run rialzisti e riallocare a costo zero.",
    },
}

def get_macro_class_svg(classe: str, size: int = 15, color: str = None, style: str = "") -> str:
    """Restituisce l'icona SVG vettoriale ufficiale e univoca per la classe di attivo."""
    inline_style = f"display:inline-block; vertical-align:middle; flex-shrink:0; {style}"
    c = str(classe).lower()
    for name, info in ASSET_CLASSES_INFO.items():
        if name.lower() in c or info["short_name"].lower() in c or (c.startswith("azion") and "azionar" in name.lower()):
            use_color = color if color is not None else info["color"]
            return info["svg"].format(size=size, color=use_color, style=inline_style)
    fallback_color = color if color is not None else "#7A7266"
    return ASSET_CLASSES_INFO["Liquidità"]["svg"].format(size=size, color=fallback_color, style=inline_style)


def get_default_convex_holdings_100k(prices: Dict[str, float] = None) -> Dict[str, Any]:
    """
    Calcola le quote di default per un capitale standard di 100.000 € in Convex Stack
    perfettamente allineato ai pesi target (NTSG 45%, AVWS 15%, DBMFE 25%, PPFB 7.5%, WBTC 7.5%).
    """
    base_prices = {"NTSG": 28.69, "AVWS": 25.64, "DBMFE": 123.50, "PPFB": 75.15, "WBTC": 16.60}
    p = {**base_prices, **(prices or {})}
    
    total_target = 100000.0
    shares = {
        "NTSG": int(round((total_target * 0.45) / p["NTSG"])),
        "AVWS": int(round((total_target * 0.15) / p["AVWS"])),
        "DBMFE": int(round((total_target * 0.25) / p["DBMFE"])),
        "PPFB": int(round((total_target * 0.075) / p["PPFB"])),
        "WBTC": int(round((total_target * 0.075) / p["WBTC"])),
    }
    invested = sum(shares[k] * p[k] for k in shares)
    cash = max(0.0, total_target - invested)
    return {
        "cash_eur": round(cash, 2),
        "holdings": {k: {"shares": float(shares[k]), "last_price": p[k]} for k in shares},
        "last_updated": "2026-09-01"
    }


def load_config() -> Dict[str, Any]:
    """Carica la configurazione utente persistita o restituisce i valori standard."""
    defaults = {
        "apex_capital_eur": 100000.0,
        "convex_capital_eur": 100000.0,
        "monthly_pac_eur": 500.0,
        "pac_annual_growth": 0.04,
        "target_apex_ratio": 0.50,
        "target_convex_ratio": 0.50,
        "wbtc_trim_threshold": 0.1125,
        "ppfb_trim_threshold": 0.1125,
        "last_updated": "2026-09-01"
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


def load_convex_portfolio() -> Dict[str, Any]:
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
    return get_default_convex_holdings_100k()


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
#   - Apex: split a meta' campione per numero di decisioni mensili (72+72).
#     TRAIN 2014-11-30 -> 2020-08-31, TEST 2020-09-30 -> 2026-08-31 (72 mesi).
#     Ricalcolato da research/convex/apex_monthly_returns_extended.csv (netto)
#     e _gross.csv, stessa metodologia che produce esattamente i numeri prima
#     deployati per la finestra piena (verificato a 4 decimali) — non stimato.
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
# ==============================================================================

def get_apex_metrics() -> Dict[str, Any]:
    """Metriche reali di Apex Engine sul solo periodo di validazione fuori
    campione (TEST 2020-09-30 -> 2026-08-31, 72 mesi mai usati per scegliere
    i parametri della strategia) — vedi nota sopra per la metodologia.
    Le metriche di rischio (sharpe/sortino/max_drawdown/calmar/volatility)
    sono calcolate sulla serie LORDA (apex_monthly_returns_extended_gross.csv,
    stesso TEST period) -- coerenti con equity.json/il grafico, che non
    modella alcuna tassa. I campi *_netto_stimato usano invece la serie netta
    (apex_monthly_returns_extended.csv, tasse italiane reali modellate anno
    per anno) -- una stima più rigorosa dell'haircut fisso usato per Convex,
    ma pur sempre calcolata su un backtest di ricerca separato dalla curva
    live, non identica ad essa."""
    return {
        "name": "Apex Engine (Tattico Alpha)",
        "cagr_net": 0.1230,
        "cagr_gross": 0.1416,
        "volatility": 0.1303,
        "sharpe": 1.084,
        "sortino": 2.456,
        "max_drawdown": -0.1012,
        "calmar": 1.399,
        "ulcer_index": 5.61,
        "volatility_netto_stimato": 0.1617,
        "sharpe_netto_stimato": 0.799,
        "sortino_netto_stimato": 1.409,
        "max_drawdown_netto_stimato": -0.1598,
        "calmar_netto_stimato": 0.770,
        "test_period": "2020-09-30 → 2026-08-31 (72 mesi, fuori campione)",
        "cash_drag_protection": "100% Cash nei bear market macro",
        "philosophy": "Rotazione trimestrale 15 titoli S&P 500 Low-Vol (Buffer Rank 20) + Trend Macro 40w/20w con isteresi. Nessuno stop-loss (validato: ogni meccanismo di stop testato peggiora Sharpe/MaxDD sotto esecuzione settimanale reale)."
    }


def get_convex_metrics() -> Dict[str, Any]:
    """Metriche reali di Convex Stack sul periodo di validazione fuori campione.
    BUG corretto: usava un TEST period proprio (2013-10/2026-08, 155 mesi) diverso
    da quello di get_apex_metrics()/get_combined_dual_engine_metrics() (2020-09/
    2026-08, 72 mesi) — tre finestre diverse per tre numeri mostrati fianco a
    fianco, che lasciava il combinato apparentemente piu' alto di ENTRAMBE le
    componenti anche dopo il primo fix (era stato allineato solo ad Apex, non
    a Convex — segnalato di nuovo dall'utente). Ora usa la STESSA finestra di
    Apex e del combinato (2020-09-30 -> 2026-08-31, 72 mesi — l'intersezione
    dei due periodi TEST, quindi fuori campione per entrambe le strategie):
    su questa finestra Convex fa 16.88% lordo (non piu' 15.26%), e il combinato
    (15.91%) torna a stare correttamente in mezzo ai due componenti su OGNI
    confronto, non solo contro Apex. cagr_gross e' la performance reale della
    curva (Convex non vende se non per rari trim: le tasse sono dovute solo
    alla realizzazione, non sul non realizzato). cagr_net è un'approssimazione
    (haircut 26% sulla plusvalenza cumulata del periodo), non una simulazione
    fiscale posizione-per-posizione."""
    return {
        "name": "Convex Stack (Strategico PAC)",
        "cagr_net": 0.1356,
        "cagr_gross": 0.1688,
        "volatility": 0.1304,
        "sharpe": 1.252,
        "sortino": 1.519,
        "max_drawdown": -0.1576,
        "calmar": 1.071,
        "ulcer_index": 3.79,
        "test_period": "2020-09-30 → 2026-08-31 (72 mesi, fuori campione — stessa finestra di Apex e del combinato)",
        "embedded_leverage": "1.225x Nozionale senza debito a margine personale",
        "philosophy": "Leva istituzionale NTSG (45% capitale) + valore su piccola capitalizzazione AVWS (15%) + protezione attiva nelle crisi DBMFE (25%) + riserve reali PPFB e WBTC (7.5% ciascuno)."
    }


def get_combined_dual_engine_metrics() -> Dict[str, Any]:
    """Metriche reali della combinazione APEX+CONVEX al mix target standard 50/50.
    BUG corretto: prima usava la finestra 2014-11/2026-08 (142 mesi) mentre
    get_apex_metrics()/get_convex_metrics() erano gia' state corrette al solo
    periodo TEST di ciascuna (72 e 155 mesi) -- tre finestre diverse per tre
    numeri mostrati fianco a fianco, che produceva un CAGR combinato
    apparentemente piu' alto di ENTRAMBE le componenti (un'impossibilita'
    matematica per una media pesata, segnalata dall'utente). Causa: la
    finestra vecchia includeva 2014-2020, il periodo TRAIN di Apex con un
    rendimento eccezionalmente forte che la casella Apex non mostra piu'.
    Ora usa l'intersezione dei due periodi TEST (2020-09-30 -> 2026-08-31,
    72 mesi) -- fuori campione per ENTRAMBE le strategie, la stessa identica
    finestra della casella Apex, cosi' le tre cifre sono confrontabili.
    Su questa finestra il CAGR combinato torna correttamente IN MEZZO ai due
    componenti (15.91% tra 14.38% Apex e 16.88% Convex, tutti lordi) -- il
    beneficio di diversificazione reale si vede nel MaxDD (-7.80%, inferiore
    a entrambe le componenti), non nel CAGR. Sharpe/Sortino/MaxDD/Calmar
    calcolati sulle due serie LORDE (apex_monthly_returns_extended_gross.csv
    + convex_monthly_returns.csv); cagr_net e' la media pesata delle stime
    nette dei due componenti sulla stessa finestra, non una combinazione
    fiscale rigorosa posizione-per-posizione.
    Correzione ulteriore (verifica incrociata successiva): volatility e
    sortino erano rimasti stale da una versione precedente del calcolo (0.1149
    e 2.267, incoerenti con lo sharpe=1.384 gia' corretto, che implicava una
    volatility di 0.1100 -- ricalcolato a mano dai CSV, confermato: volatility
    0.1100, sortino 3.306)."""
    return {
        "name": "APEX CONVEX (Dual-Engine)",
        "cagr_net": 0.1303,
        "cagr_gross": 0.1591,
        "volatility": 0.1100,
        "sharpe": 1.384,
        "sortino": 3.306,
        "max_drawdown": -0.0780,
        "calmar": 2.040,
        "ulcer_index": 2.62,
        "correlation": 0.424,
        "test_period": "2020-09-30 → 2026-08-31 (72 mesi, fuori campione per entrambe le strategie)",
        "synergy_summary": (
            "Mix 50% Apex / 50% Convex (lordo, stessa finestra 2020-09/2026-08 di entrambe le componenti): "
            "CAGR 15.91% (netto stimato 13.03%), correttamente tra il 14.38% di Apex e il 16.88% di Convex "
            "isolatamente. Il beneficio di diversificazione si vede nel MaxDD -7.80% — inferiore a entrambe "
            "le componenti singole (-10.12% Apex, -15.76% Convex) — non nel CAGR: una miscela pesata non può "
            "mai battere entrambi i componenti sul rendimento, solo sul rischio. Correlazione reale: 0.424."
        )
    }


def compute_unified_portfolio(
    apex_val: float,
    convex_report: convex_engine.ConvexPortfolioReport,
    monthly_pac: float = 600.0,
    target_apex_ratio: float = 0.50,
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
            f"per riequilibrare senza vendere nulla, quindi senza tasse."
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
    conv_cr  = convex_val * convex_report.macro_exposure["Bitcoin (Convessità Asimmetrica)"]
    conv_cash = convex_val * convex_report.macro_exposure.get("Liquidità Cassa", 0.0)

    macro_breakdown = {
        "Azionario Globale & USA": (apex_eq + conv_eq) / tot_wealth,
        "Obbligazionario Governativo": (apex_bd + conv_bd) / tot_wealth,
        "Managed Futures (CTA)": conv_cta / tot_wealth,
        "Oro Fisico": (apex_gld + conv_gld) / tot_wealth,
        "Bitcoin": (apex_cr + conv_cr) / tot_wealth,
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


def load_combined_monthly_history(target_apex: float = 0.50, target_convex: float = 0.50) -> pd.DataFrame:
    """
    Carica le serie mensili storiche di Apex Engine (142 mesi dal 2014-11 al 2026-08)
    e di Convex Stack, e genera la serie di rendimenti e NAV Base 100 del portafoglio combinato.
    """
    base_dir = os.path.dirname(__file__)
    # BUG corretto: prima combinava la serie NETTA di Apex con quella LORDA di
    # Convex nella stessa somma pesata -- due basi fiscali diverse sommate come
    # se fossero comparabili. Ora usa la versione lorda di Apex (Convex è già
    # lorda per costruzione, IPS no-sell), coerente con la convenzione
    # lordo-primario/netto-stimato-secondario del resto della dashboard.
    apex_file = os.path.join(base_dir, "apex_monthly_returns_extended_gross.csv")
    conv_file = os.path.join(base_dir, "convex_monthly_returns.csv")

    if not os.path.exists(apex_file) or not os.path.exists(conv_file):
        return pd.DataFrame()
    apex_ret = pd.read_csv(apex_file, index_col=0, parse_dates=True).iloc[:, 0]
    cx_ret = pd.read_csv(conv_file, index_col=0, parse_dates=True).iloc[:, 0]

    common = apex_ret.index.intersection(cx_ret.index)
    if len(common) == 0:
        return pd.DataFrame()

    comb_ret = target_apex * apex_ret.loc[common] + target_convex * cx_ret.loc[common]
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


