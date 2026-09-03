"""
convex_engine.py — Motore Quantitativo Istituzionale Convex Stack (Versione UCITS)
===================================================================================
Principi Guida: Lean, Frictionless, Robusto.
Unione tra rigore matematico istituzionale e massima semplicità operativa retail.

Specifiche Strutturali:
  - 100% Capitale Versato (Zero debito a margine personale).
  - 5 Strumenti UCITS/ETC armonizzati con ISIN verificati.
  - Leva implicita istituzionale: NTSG (1.5x su 60% equity + 40% bond futures).
  - Esposizione Nozionale Totale = 122.5% del capitale.
  - Ribilanciamento a costo fiscale zero tramite PAC mensile ("Water-Filling").
  - Monitoraggio delle soglie di Trim asimmetriche con compensazione minusvalenze (ETC).
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any
import numpy as np
import pandas as pd

# ==============================================================================
# PARAMETRI STRUTTURALI CONVEX STACK (5 ASSET UCITS)
# ==============================================================================

CONVEX_INSTRUMENTS = {
    "NTSG": {
        "name": "WisdomTree Global Efficient Core",
        "ticker": "NTSG.MI",
        "isin": "IE00BLRPQM83",
        "target_weight": 0.45,       # 45% del capitale in cassa
        "tolerance_min": 0.40,       # Banda min: 40%
        "tolerance_max": 0.50,       # Banda max: 50%
        "ter": 0.0025,               # 0.25% annuo
        "tax_type": "REDDITO_CAPITALE", # ETF: minus non compensabili
        "asset_class": "Azionario Globale + Obbligazionario a Leva",
        "equity_leg": 0.90,          # 45% * 0.90 = 40.5% esposizione azionaria
        "bond_leg": 0.60,            # 45% * 0.60 = 27.0% esposizione obbligazionaria
    },
    "AVWS": {
        "name": "Avantis World Small Cap Value",
        "ticker": "AVWS.DE",
        "isin": "IE000OETMVR4",
        "target_weight": 0.15,       # 15% del capitale
        "tolerance_min": 0.10,
        "tolerance_max": 0.20,
        "ter": 0.0039,               # 0.39% annuo
        "tax_type": "REDDITO_CAPITALE", # ETF
        "asset_class": "Small Cap Value Equity",
        "equity_leg": 1.00,
        "bond_leg": 0.00,
    },
    "DBMFE": {
        "name": "iMGP DBi Managed Futures",
        "ticker": "DBMF",            # Proxy US / UCITS LU2951555403
        "isin": "LU2951555403",
        "target_weight": 0.25,       # 25% del capitale
        "tolerance_min": 0.20,
        "tolerance_max": 0.30,
        "ter": 0.0075,               # 0.75% annuo
        "tax_type": "REDDITO_CAPITALE", # Fondo/ETF UCITS
        "asset_class": "Protezione Attiva nelle Crisi (Trend Following)",
        "equity_leg": 0.00,
        "bond_leg": 0.00,
    },
    "PPFB": {
        "name": "Invesco Physical Gold ETC",
        "ticker": "PPFB.MI",         # Alt: SGLD.L / 4GLD.DE
        "isin": "IE00B579F325",
        "target_weight": 0.075,      # 7.5% del capitale
        "tolerance_min": 0.045,      # 4.5%
        "tolerance_max": 0.1125,     # 11.25% = target x1.5 (regola simmetrica ETC/ETP con WBTC)
        "ter": 0.0012,               # 0.12% annuo
        "tax_type": "REDDITO_DIVERSO", # ETC: COMPENSA MINUSVALENZE!
        "asset_class": "Oro Fisico (Riserva Reale)",
        "equity_leg": 0.00,
        "bond_leg": 0.00,
    },
    "WBTC": {
        "name": "WisdomTree Physical Bitcoin",
        "ticker": "BTC-USD",         # Alt ETP: GB00BJYDH287 / IB1T.DE
        "isin": "GB00BJYDH287",
        "target_weight": 0.075,      # 7.5% del capitale
        "tolerance_min": 0.035,      # 3.5%
        "tolerance_max": 0.1125,     # 11.25% = target x1.5 (validato su dati reali: la vecchia
                                      # soglia 15% perdeva contro 11.25% sia su TRAIN che su TEST
                                      # nel backtest walk-forward, research/convex/)
        "ter": 0.0015,               # 0.15% annuo
        "tax_type": "REDDITO_DIVERSO", # ETP: COMPENSA MINUSVALENZE!
        "asset_class": "Bitcoin (Crescita Asimmetrica)",
        "equity_leg": 0.00,
        "bond_leg": 0.00,
    }
}

# ==============================================================================
# VERSIONE SEMPLICE (4 STRUMENTI, SENZA AVWS)
# ==============================================================================
# AVWS rimossa, 15% di capitale redistribuito proporzionalmente sugli altri 4
# (validato: research/convex/test_convex_ntsg_grid_extended.py — nessuna altra
# redistribuzione ha mai battuto quella proporzionale fuori campione). Bande
# di tolleranza scalate con la stessa convenzione degli originali: ±5pp per
# NTSG/DBMFE, target x1.5 (max) e target-3pp (min) per PPFB/WBTC.
# Calcolati per divisione (non arrotondati a mano) così i 4 pesi sommano
# esattamente a 1.0 in virgola mobile, non a 0.999 come una versione precedente
# con letterali troncati a 3 decimali.
_SIMPLE_BASE = 45.0 + 25.0 + 7.5 + 7.5  # = 85.0 (capitale residuo dopo AVWS)
_W_NTSG  = 45.0 / _SIMPLE_BASE
_W_DBMFE = 25.0 / _SIMPLE_BASE
_W_PPFB  = 7.5  / _SIMPLE_BASE
_W_WBTC  = 7.5  / _SIMPLE_BASE

CONVEX_INSTRUMENTS_SIMPLE = {
    "NTSG": {**CONVEX_INSTRUMENTS["NTSG"], "target_weight": _W_NTSG,
             "tolerance_min": _W_NTSG - 0.05, "tolerance_max": _W_NTSG + 0.05},
    "DBMFE": {**CONVEX_INSTRUMENTS["DBMFE"], "target_weight": _W_DBMFE,
              "tolerance_min": _W_DBMFE - 0.05, "tolerance_max": _W_DBMFE + 0.05},
    "PPFB": {**CONVEX_INSTRUMENTS["PPFB"], "target_weight": _W_PPFB,
             "tolerance_min": _W_PPFB - 0.03, "tolerance_max": _W_PPFB * 1.5},
    "WBTC": {**CONVEX_INSTRUMENTS["WBTC"], "target_weight": _W_WBTC,
             "tolerance_min": _W_WBTC - 0.03, "tolerance_max": _W_WBTC * 1.5},
}


@dataclass
class ConvexAssetStatus:
    key: str
    name: str
    isin: str
    target_weight: float
    current_shares: float
    current_price: float
    current_value: float
    current_weight: float
    weight_diff: float              # target_weight - current_weight (positivo = sottopesato)
    tolerance_min: float
    tolerance_max: float
    is_underweight: bool
    is_overweight: bool
    requires_trim: bool
    trim_amount_eur: float
    tax_type: str


@dataclass
class PACAction:
    recommended_asset: str
    asset_name: str
    deposit_amount_eur: float
    estimated_price: float
    estimated_shares: int
    remaining_cash: float
    reason: str


@dataclass
class ConvexPortfolioReport:
    total_value: float
    assets: Dict[str, ConvexAssetStatus]
    pac_action: Optional[PACAction]
    trim_alerts: List[Dict[str, Any]]
    macro_exposure: Dict[str, float]
    ter_weighted: float


def evaluate_convex_stack(
    current_holdings: Dict[str, float],      # {sym: shares}
    market_prices: Dict[str, float],         # {sym: price_in_eur}
    monthly_pac_eur: float = 600.0,
    cash_balance: float = 0.0,
    instruments: Optional[Dict[str, Any]] = None
) -> ConvexPortfolioReport:
    """
    Valuta lo stato di Convex Stack, calcola i pesi, genera la raccomandazione PAC
    e identifica eventuali alert di Trim/Ribilanciamento.

    instruments: set di strumenti da usare al posto di CONVEX_INSTRUMENTS (5
    strumenti, versione Completa). Passare CONVEX_INSTRUMENTS_SIMPLE per la
    versione Semplice a 4 strumenti (senza AVWS) — stessa logica, nessuna
    duplicazione.
    """
    instruments = instruments if instruments is not None else CONVEX_INSTRUMENTS
    total_val = cash_balance
    values = {}

    for k in instruments:
        # max(0.0, ...) come difesa: quote/prezzi negativi (input malformato o
        # una fonte prezzi futura non passata dalla UI, che già vieta i negativi
        # con min_value=0.0) non devono produrre pesi/valori negativi a valle.
        shares = max(0.0, float(current_holdings.get(k, 0.0)))
        px = max(0.0, float(market_prices.get(k, 1.0)))
        val = shares * px
        values[k] = val
        total_val += val

    if total_val <= 0:
        total_val = 1.0  # Safe guard division by zero

    asset_status = {}
    trim_alerts = []
    deficits = {}

    for k, info in instruments.items():
        # max(0.0, ...) come difesa: quote/prezzi negativi (input malformato o
        # una fonte prezzi futura non passata dalla UI, che già vieta i negativi
        # con min_value=0.0) non devono produrre pesi/valori negativi a valle.
        shares = max(0.0, float(current_holdings.get(k, 0.0)))
        px = max(0.0, float(market_prices.get(k, 1.0)))
        val = values[k]
        w_cur = val / total_val
        w_tgt = info["target_weight"]
        diff = w_tgt - w_cur  # Positivo = sottopesato (deficit)
        deficits[k] = diff

        is_under = w_cur < info["tolerance_min"]
        is_over = w_cur > info["tolerance_max"]
        req_trim = False
        trim_eur = 0.0

        if is_over:
            req_trim = True
            excess_eur = (w_cur - w_tgt) * total_val
            trim_eur = max(0.0, excess_eur)

            tax_note = (
                "Plusvalenza COMPENSABILE con minusvalenze pregresse (Reddito Diverso ETC/ETP)."
                if info["tax_type"] == "REDDITO_DIVERSO"
                else "Vendita ETF UCITS (Reddito di Capitale: ritenuta 26% non compensabile)."
            )

            trim_alerts.append({
                "asset": k,
                "name": info["name"],
                "current_weight": w_cur,
                "threshold_max": info["tolerance_max"],
                "excess_eur": trim_eur,
                "shares_to_sell": int(trim_eur / px) if px > 0 else 0,
                "tax_note": tax_note,
                "urgency": "ALTA" if k == "WBTC" and w_cur > info["tolerance_max"] else "MEDIA"
            })

        asset_status[k] = ConvexAssetStatus(
            key=k,
            name=info["name"],
            isin=info["isin"],
            target_weight=w_tgt,
            current_shares=shares,
            current_price=px,
            current_value=val,
            current_weight=w_cur,
            weight_diff=diff,
            tolerance_min=info["tolerance_min"],
            tolerance_max=info["tolerance_max"],
            is_underweight=is_under,
            is_overweight=is_over,
            requires_trim=req_trim,
            trim_amount_eur=trim_eur,
            tax_type=info["tax_type"]
        )

    # --------------------------------------------------------------------------
    # ALGORITMO PAC WATER-FILLING: Zero calcoli manuali per l'investitore
    # --------------------------------------------------------------------------
    # Individua l'asset con il maggior deficit relativo (il più sottopesato)
    pac_action = None
    if monthly_pac_eur > 0:
        target_asset = max(deficits.items(), key=lambda x: x[1])[0]
        t_info = instruments[target_asset]
        px_target = market_prices.get(target_asset, 1.0)
        est_shares = int(monthly_pac_eur // px_target) if px_target > 0 else 0
        rem_cash = monthly_pac_eur - (est_shares * px_target) if px_target > 0 else 0.0

        pac_action = PACAction(
            recommended_asset=target_asset,
            asset_name=t_info["name"],
            deposit_amount_eur=monthly_pac_eur,
            estimated_price=px_target,
            estimated_shares=est_shares,
            remaining_cash=rem_cash,
            reason=(
                f"Asset più sottopesato nel portafoglio (peso attuale {asset_status[target_asset].current_weight*100:.1f}% "
                f"vs target {t_info['target_weight']*100:.1f}%). "
                f"Il versamento su questo strumento riequilibra il portafoglio a costo fiscale zero."
            )
        )

    # --------------------------------------------------------------------------
    # SCOMPOSIZIONE RAGGI X DELL'ESPOSIZIONE MACRO AGGREGATA
    # --------------------------------------------------------------------------
    # NTSG: 90% Equity + 60% Treasuries
    ntsg_val = values.get("NTSG", 0.0)
    avws_val = values.get("AVWS", 0.0)
    dbmf_val = values.get("DBMFE", 0.0)
    gold_val = values.get("PPFB", 0.0)
    btc_val  = values.get("WBTC", 0.0)

    equity_tot = (ntsg_val * 0.90) + avws_val
    bonds_tot  = (ntsg_val * 0.60)
    cta_tot    = dbmf_val
    gld_tot    = gold_val
    cr_tot     = btc_val
    cash_tot   = cash_balance

    macro_exposure = {
        "Azionario Globale (Large/Mid + Small SCV)": equity_tot / total_val,
        "Obbligazionario Governativo (Treasury Futures)": bonds_tot / total_val,
        "Managed Futures (Crisis Alpha CTA)": cta_tot / total_val,
        "Oro Fisico (Riserva Reale)": gld_tot / total_val,
        "Bitcoin (Convessità Asimmetrica)": cr_tot / total_val,
        "Liquidità Cassa": cash_tot / total_val,
        "Esposizione Nozionale Totale": (equity_tot + bonds_tot + cta_tot + gld_tot + cr_tot + cash_tot) / total_val
    }

    # TER ponderato reale
    ter_weighted = sum(asset_status[k].current_weight * instruments[k]["ter"] for k in asset_status)

    return ConvexPortfolioReport(
        total_value=total_val,
        assets=asset_status,
        pac_action=pac_action,
        trim_alerts=trim_alerts,
        macro_exposure=macro_exposure,
        ter_weighted=ter_weighted
    )


# ==============================================================================
# TEST RAPIDO DI INTEGRITÀ UNITARIA
# ==============================================================================
if __name__ == "__main__":
    print("Test rapido convex_engine.py:")
    holdings_example = {
        "NTSG": 585,    # es. a 100€ = 58.500€
        "AVWS": 390,    # es. a 50€  = 19.500€
        "DBMFE": 1300,  # es. a 25€  = 32.500€
        "PPFB": 195,    # es. a 50€  =  9.750€
        "WBTC": 97.5    # es. a 100€ =  9.750€
    }
    prices_example = {
        "NTSG": 100.0, "AVWS": 50.0, "DBMFE": 25.0, "PPFB": 50.0, "WBTC": 100.0
    }

    rep = evaluate_convex_stack(holdings_example, prices_example, monthly_pac_eur=600.0)
    print(f"Valore Totale Convex: € {rep.total_value:,.2f}")
    print(f"TER Ponderato: {rep.ter_weighted*100:.3f}%")
    print(f"Esposizione Nozionale Totale: {rep.macro_exposure['Esposizione Nozionale Totale']*100:.1f}%")
    print(f"Azione PAC Consigliata: Compra {rep.pac_action.recommended_asset} ({rep.pac_action.estimated_shares} quote)")
    print("✓ convex_engine.py operativo con successo!")
