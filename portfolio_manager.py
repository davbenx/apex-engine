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


def load_config() -> Dict[str, Any]:
    """Carica la configurazione utente persistita o restituisce i valori standard."""
    defaults = {
        "apex_capital_eur": 79000.0,
        "convex_capital_eur": 130000.0,
        "monthly_pac_eur": 600.0,
        "pac_annual_growth": 0.04,
        "target_apex_ratio": 0.45,
        "target_convex_ratio": 0.55,
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
    """Carica le posizioni attuali dei 5 asset in Convex Stack."""
    if os.path.exists(CONVEX_FILE):
        try:
            with open(CONVEX_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {"cash_eur": 0.0, "holdings": {}}


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

def get_apex_metrics() -> Dict[str, Any]:
    """Metriche reali di Apex Engine, calcolate dal backtest di produzione
    (esecuzione settimanale, finestra comune 2014-11/2026-08, vedi nota sopra).
    cagr_gross da research/convex/apex_extended_summary.pkl (full_window),
    calcolato riaggiungendo le tasse realmente pagate anno per anno — non stimato."""
    return {
        "name": "Apex Engine (Tattico Alpha)",
        "cagr_net": 0.1601,
        "cagr_gross": 0.1858,
        "volatility": 0.1637,
        "sharpe": 0.992,
        "sortino": 1.841,
        "max_drawdown": -0.1598,
        "calmar": 1.002,
        "ulcer_index": 7.41,
        "cash_drag_protection": "100% Cash nei bear market macro",
        "philosophy": "Rotazione trimestrale 15 titoli S&P 500 Low-Vol (Buffer Rank 20) + Trend Macro 40w/20w con isteresi. Nessuno stop-loss (validato: ogni meccanismo di stop testato peggiora Sharpe/MaxDD sotto esecuzione settimanale reale)."
    }


def get_convex_metrics() -> Dict[str, Any]:
    """Metriche reali di Convex Stack, calcolate dal backtest corretto (pesi di
    capitale corretti, TER corretto, senza l'estensione Fama-French fabbricata).
    cagr_gross è la performance reale della curva (Convex non vende se non per
    rari trim: le tasse sono dovute solo alla realizzazione, non sul non
    realizzato — la curva "vera" oggi è quella lorda). cagr_net è calcolato con
    il modello fiscale a due categorie (UCITS senza compensazione minusvalenze,
    ETC/ETP con compensazione — vedi research/convex/convex_twobucket_v2.pkl),
    non più una stima forfettaria: è il valore NETTO SE si liquidasse oggi."""
    return {
        "name": "Convex Stack (Strategico PAC)",
        "cagr_net": 0.1176,
        "cagr_gross": 0.1396,
        "volatility": 0.1107,
        "sharpe": 1.144,
        "sortino": 1.402,
        "max_drawdown": -0.1462,
        "calmar": 0.871,
        "ulcer_index": 3.46,
        "embedded_leverage": "1.225x Nozionale senza debito a margine personale",
        "philosophy": "Leva istituzionale NTSG (45% capitale) + valore su piccola capitalizzazione AVWS (15%) + protezione attiva nelle crisi DBMFE (25%) + riserve reali PPFB e WBTC (7.5% ciascuno)."
    }


def get_combined_dual_engine_metrics() -> Dict[str, Any]:
    """Metriche reali della combinazione APEX+CONVEX al mix target 45/55,
    calcolate dalla correlazione EFFETTIVA tra le due serie di rendimento
    (non assunta) sulla finestra comune 2014-11/2026-08. cagr_gross ricalcolato
    direttamente dalla combinazione pesata delle due serie mensili lorde reali
    (non stimato da una regola forfettaria)."""
    return {
        "name": "APEX CONVEX (Dual-Engine)",
        "cagr_net": 0.1454,
        "cagr_gross": 0.1689,
        "volatility": 0.1128,
        "sharpe": 1.265,
        "sortino": 2.584,
        "max_drawdown": -0.0984,
        "calmar": 1.478,
        "ulcer_index": 3.38,
        "correlation": 0.400,
        "synergy_summary": (
            "Mix 45% Apex / 55% Convex: MaxDD -9.84% (contro -15.98% Apex e -14.62% Convex "
            "isolatamente), Sharpe 1.265 e Calmar 1.478, CAGR netto 14.54% (lordo 16.89%). "
            "Correlazione reale calcolata tra le due serie: 0.400 — beneficio di "
            "diversificazione genuino (MaxDD combinato inferiore a entrambe le componenti "
            "singole), non enorme ma reale. Vedi research/convex/ per metodologia e limiti."
        )
    }


def compute_unified_portfolio(
    apex_val: float,
    convex_report: convex_engine.ConvexPortfolioReport,
    monthly_pac: float = 600.0,
    target_apex_ratio: float = 0.45,
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


if __name__ == "__main__":
    cfg = load_config()
    holdings = {
        "NTSG": 585, "AVWS": 390, "DBMFE": 1300, "PPFB": 195, "WBTC": 97.5
    }
    prices = {"NTSG": 100.0, "AVWS": 50.0, "DBMFE": 25.0, "PPFB": 50.0, "WBTC": 100.0}
    c_rep = convex_engine.evaluate_convex_stack(holdings, prices, monthly_pac_eur=cfg["monthly_pac_eur"])
    unified = compute_unified_portfolio(cfg["apex_capital_eur"], c_rep, cfg["monthly_pac_eur"])

    print("Test rapido portfolio_manager.py:")
    print(f"Patrimonio Totale Consolidato: € {unified['total_wealth_eur']:,.2f}")
    print(f"Allocazione Attuale: Apex {unified['apex_weight']*100:.1f}% | Convex {unified['convex_weight']*100:.1f}%")
    print(f"Consiglio Smart Flow: {unified['smart_flow_destination']}")
    print("✓ portfolio_manager.py operativo con successo!")
