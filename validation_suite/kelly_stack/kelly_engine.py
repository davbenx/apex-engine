"""
kelly_engine.py — Motore Quantitativo Kelly Stack (Terzo Pilastro: Ricchezza Generazionale)
=============================================================================================
Vedi KELLY_STACK_SPEC.md per la specifica completa e la giustificazione di ogni parametro.

Obiettivo: massimizzare E[log(ricchezza terminale)] (crescita geometrica composta,
non rendimento atteso semplice) soggetto a un vincolo esplicito di rischio di rovina —
il problema che il criterio di Kelly risolve per costruzione. Leva ammessa, ma solo
nella misura in cui la diversificazione stimata la giustifica, con un tetto statico
indipendente dalla matematica (governatore Livello 1) e uno dinamico legato a
volatilità/drawdown realizzati (governatore Livello 2) — vedi §3 della spec.

Modulo isolato apposta, stesso principio di apex_v2_engine.py: non tocca file su
disco, riceve dati e stato in input, restituisce risultati in output.

STATO: design non ancora backtestato (KELLY_STACK_SPEC.md §7) — i prior di
mu/sigma/corr sono di letteratura, non calibrati su dati storici point-in-time
di questi strumenti specifici. Non trattare l'output come segnale pronto per
capitale reale finché §7 non è completato.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Optional, Any
import numpy as np

from kelly_optimization import solve_kelly_qp_long_only

# ==============================================================================
# PARAMETRI STRUTTURALI KELLY STACK (vedi KELLY_STACK_SPEC.md per la giustificazione)
# ==============================================================================

# Riusa gli stessi 5 strumenti UCITS/ETC gia' verificati in convex_engine.py
# (stessi ISIN/ticker, stessa cronologia di bug di identificazione prodotto gia'
# corretti la') — la differenza di Kelly Stack e' come vengono pesati, non quali
# strumenti si usano (KELLY_STACK_SPEC.md §4).
KELLY_SLEEVES = {
    "NTSG": {
        "name": "WisdomTree Global Efficient Core",
        "role": "Equity core (leva implicita)",
        "tax_type": "REDDITO_CAPITALE",
        "mu_prior": 0.055,   # eccesso atteso su cash, annuo — prior di letteratura, non calibrato (spec §4)
        "sigma_prior": 0.16,
        "tolerance_band": 0.20,  # banda simmetrica di trim, frazione del peso target (piu' larga di Convex: orizzonte piu' lungo)
    },
    "AVWS": {
        "name": "Avantis World Small Cap Value",
        "role": "Diversificazione fattoriale equity",
        "tax_type": "REDDITO_CAPITALE",
        "mu_prior": 0.065,
        "sigma_prior": 0.20,
        "tolerance_band": 0.20,
    },
    "DBMFE": {
        "name": "iMGP DBi Managed Futures",
        "role": "Crisis alpha / trend-following",
        "tax_type": "REDDITO_CAPITALE",
        "mu_prior": 0.035,
        "sigma_prior": 0.10,
        "tolerance_band": 0.20,
    },
    "PPFB": {
        "name": "iShares Physical Gold ETC",
        "role": "Hedge di coda / inflazione",
        "tax_type": "REDDITO_DIVERSO",
        "mu_prior": 0.010,
        "sigma_prior": 0.15,
        "tolerance_band": 0.50,  # come Convex: banda piu' larga sugli asset a reddito diverso (compensa minusvalenze)
    },
    "WBTC": {
        "name": "WisdomTree Physical Bitcoin",
        "role": "Convessita' asimmetrica (bet piccolo)",
        "tax_type": "REDDITO_DIVERSO",
        "mu_prior": 0.150,
        "sigma_prior": 0.60,
        "tolerance_band": 0.50,
    },
    "JELS": {
        "name": "JPMorgan Equity Long-Short UCITS ETF",
        "role": "Alpha long/short market-neutral-ish (spec §4.1)",
        "tax_type": "REDDITO_CAPITALE",
        "mu_prior": 0.030,   # letteratura hedge fund equity market-neutral: tipicamente 2-4%/anno (spec §4.1)
        "sigma_prior": 0.08,
        "tolerance_band": 0.20,
        # AUM ~10M EUR rilevato in ricerca (settembre 2026) — fondo piccolo, rischio di
        # chiusura concreto (visto realizzarsi per un prodotto concorrente nella stessa
        # famiglia di strategia). Verificare liquidita'/AUM aggiornati prima di allocare
        # capitale reale (spec §7, punto 6). Gestisce lo short internamente (derivati a
        # livello di fondo) — nessuna posizione a margine sul conto dell'investitore.
    },
}

# Correlazioni prior (letteratura: equity/small-value alta corr, trend-following
# vicino a zero o negativo con equity in coda, oro/BTC scarsamente correlati col
# resto, JELS a bassa correlazione "tranquilla" ma non nulla per il rischio di
# deleveraging dei fattori quant — spec §4.1) — NON calibrate sui dati storici
# di questi strumenti (spec §4, §7). Ordine righe/colonne: NTSG, AVWS, DBMFE,
# PPFB, WBTC, JELS
KELLY_CORR_PRIOR = np.array([
    [1.00, 0.85, -0.10, 0.05, 0.15, 0.20],
    [0.85, 1.00, -0.05, 0.05, 0.15, 0.20],
    [-0.10, -0.05, 1.00, 0.10, 0.05, 0.00],
    [0.05, 0.05, 0.10, 1.00, 0.10, 0.00],
    [0.15, 0.15, 0.05, 0.10, 1.00, 0.10],
    [0.20, 0.20, 0.00, 0.00, 0.10, 1.00],
])

KELLY_FRACTION = 0.5          # mezzo-Kelly: ~75% della crescita di Kelly pieno, molta meno varianza (spec §2)
MAX_GROSS_LEVERAGE = 1.50     # tetto statico Livello 1 — solo leggermente sopra i 122.5% gia' validati da Convex (spec §3)
MAX_SLEEVE_WEIGHT = 0.60      # tetto di concentrazione per singola sleeve, Livello 1bis (spec §3) — l'inversione della
                              # matrice di covarianza puo' amplificare in modo estremo l'effetto di una singola stima di
                              # correlazione (una sleeve quasi scorrelata puo' arrivare a dominare oltre il 90% del
                              # budget di leva lorda su mu ottimistici, verificato con lo smoke test di questo file):
                              # un singolo punto di errore di stima non deve poter monopolizzare il portafoglio.
KELLY_VOL_TARGET = 0.15       # governatore dinamico Livello 2, vol-target di portafoglio annualizzata (spec §3)
KELLY_DD_DERISK_TRIGGER = 0.25  # drawdown da picco oltre il quale scatta la deleva forzata (spec §3)
KELLY_DD_DERISK_FLOOR = 0.50    # fattore di scala applicato quando il trigger scatta (dimezza l'esposizione lorda)


@dataclass
class KellyWeightsResult:
    raw_kelly_weights: Dict[str, float]         # f* pieno, prima della frazione
    fractional_weights: Dict[str, float]        # dopo KELLY_FRACTION, prima di ogni cap/governatore
    concentration_capped_weights: Dict[str, float]  # dopo il cap per singola sleeve (Livello 1bis)
    capped_weights: Dict[str, float]            # dopo anche il tetto di leva lorda (Livello 1)
    final_weights: Dict[str, float]             # dopo il governatore dinamico (Livello 2) — output da usare
    gross_leverage_raw: float
    gross_leverage_final: float
    vol_scale_applied: float
    dd_scale_applied: float


def compute_kelly_weights(
    mu: Optional[Dict[str, float]] = None,
    sigma: Optional[Dict[str, float]] = None,
    corr: Optional[np.ndarray] = None,
    sleeves: Optional[Dict[str, Any]] = None,
    kelly_fraction: float = KELLY_FRACTION,
    max_gross_leverage: float = MAX_GROSS_LEVERAGE,
    max_sleeve_weight: float = MAX_SLEEVE_WEIGHT,
    realized_vol_12m: Optional[float] = None,
    drawdown_from_peak: float = 0.0,
) -> KellyWeightsResult:
    """
    Calcola i pesi Kelly frazionari per le sleeve, applica il tetto statico di leva
    (Livello 1) e il governatore dinamico vol/drawdown (Livello 2). Vedi
    KELLY_STACK_SPEC.md §2-3 per la derivazione matematica e la giustificazione di
    ogni passaggio.

    Tutti i parametri stimati (mu/sigma/corr) sono opzionali con default ai prior
    di letteratura in KELLY_SLEEVES/KELLY_CORR_PRIOR — permette di sostituirli con
    stime calibrate (backtest point-in-time, spec §7) senza toccare questa funzione,
    stesso principio di `evaluate_convex_stack` che riceve prezzi dall'esterno.

    realized_vol_12m: volatilita' annualizzata realizzata di portafoglio (ai pesi
    correnti) sulle ultime 12 settimane — se None, il governatore vol-target non
    scala nulla (fattore 1.0), coerente con "fail-open, mai bloccare per dati
    mancanti" gia' usato in apex_v2_engine.select_low_vol_basket per i settori.
    """
    sleeves = sleeves if sleeves is not None else KELLY_SLEEVES
    keys = list(sleeves.keys())
    mu_vec = np.array([
        (mu.get(k, sleeves[k]["mu_prior"]) if mu else sleeves[k]["mu_prior"]) for k in keys
    ])
    sigma_vec = np.array([
        (sigma.get(k, sleeves[k]["sigma_prior"]) if sigma else sleeves[k]["sigma_prior"]) for k in keys
    ])
    corr_mat = corr if corr is not None else KELLY_CORR_PRIOR

    cov = np.outer(sigma_vec, sigma_vec) * corr_mat

    # Kelly pieno multi-asset: f* = Sigma^-1 * mu (Merton, utilita' logaritmica —
    # spec §2). pinv invece di inv: robusto se la matrice di covarianza e' quasi
    # singolare (sleeve altamente correlate, es. NTSG/AVWS a 0.85) — un'inversione
    # diretta potrebbe esplodere in pesi enormi e instabili proprio nel caso in cui
    # la diversificazione reale e' minore di quanto sembri dal conteggio delle sleeve.
    # Vincolo long-only: l'universo di Kelly Stack e' ETC/ETF (spec §6, stesso
    # principio di Convex — nessun margine di broker personale, nessuna posizione
    # corta disponibile). Risolto ESATTAMENTE via QP (kelly_optimization.py,
    # projected gradient ascent — l'obiettivo Kelly e' concavo dato che Sigma e'
    # semidefinita positiva, quindi converge al vero massimo vincolato), non piu'
    # approssimato con un clip a zero della soluzione non vincolata: il clip
    # lascia valore sul tavolo sulle sleeve NON vincolate quando il vincolo e'
    # attivo su almeno una — verificato nei test di kelly_optimization.py
    # (la QP ottiene un valore dell'obiettivo sempre >= al clip, spesso
    # strettamente maggiore). Vedi KELLY_STACK_SPEC.md §7.2 punto 4.
    f_star = solve_kelly_qp_long_only(mu_vec, cov)
    raw_kelly = {k: float(v) for k, v in zip(keys, f_star)}

    fractional = {k: v * kelly_fraction for k, v in raw_kelly.items()}
    gross_raw = float(sum(abs(v) for v in fractional.values()))

    # Livello 1bis — cap di concentrazione per singola sleeve, PRIMA del tetto di
    # leva lorda: applicato per primo cosi' che nessuna singola sleeve possa
    # consumare da sola gran parte del budget di leva lorda quando il tetto
    # aggregato (Livello 1) scala tutto proporzionalmente.
    concentration_capped = {
        k: float(np.clip(v, -max_sleeve_weight, max_sleeve_weight)) for k, v in fractional.items()
    }
    gross_after_concentration = float(sum(abs(v) for v in concentration_capped.values()))

    # Livello 1 — tetto statico di leva lorda, indipendente dalla matematica Kelly
    # (spec §3): se la leva supera il tetto, scala proporzionalmente tutte le
    # sleeve (non solo quella piu' grande) per preservare le proporzioni relative
    # rimaste dopo il cap di concentrazione.
    if gross_after_concentration > max_gross_leverage and gross_after_concentration > 1e-9:
        cap_scale = max_gross_leverage / gross_after_concentration
    else:
        cap_scale = 1.0
    capped = {k: v * cap_scale for k, v in concentration_capped.items()}

    # Livello 2 — governatore dinamico vol-target + drawdown (spec §3). I due
    # fattori si applicano al minimo (non si sommano/moltiplicano): la deleva da
    # drawdown e' un intervento discreto piu' severo, non deve essere annacquata
    # da una vol-scale che nel frattempo dice "va tutto bene".
    if realized_vol_12m is not None and realized_vol_12m > 1e-6:
        vol_scale = min(1.0, KELLY_VOL_TARGET / realized_vol_12m)
    else:
        vol_scale = 1.0

    dd_scale = KELLY_DD_DERISK_FLOOR if drawdown_from_peak > KELLY_DD_DERISK_TRIGGER else 1.0

    final_scale = min(vol_scale, dd_scale)
    final = {k: v * final_scale for k, v in capped.items()}
    gross_final = float(sum(abs(v) for v in final.values()))

    return KellyWeightsResult(
        raw_kelly_weights=raw_kelly,
        fractional_weights=fractional,
        concentration_capped_weights=concentration_capped,
        capped_weights=capped,
        final_weights=final,
        gross_leverage_raw=gross_raw,
        gross_leverage_final=gross_final,
        vol_scale_applied=vol_scale,
        dd_scale_applied=dd_scale,
    )


@dataclass
class KellySleeveStatus:
    key: str
    name: str
    target_weight: float
    current_shares: float
    current_price: float
    current_value: float
    current_weight: float
    weight_diff: float
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
class KellyPortfolioReport:
    total_value: float
    sleeves: Dict[str, KellySleeveStatus]
    pac_action: Optional[PACAction]
    trim_alerts: List[Dict[str, Any]]
    gross_leverage: float
    kelly_result: KellyWeightsResult


def evaluate_kelly_stack(
    current_holdings: Dict[str, float],
    market_prices: Dict[str, float],
    target_weights: Dict[str, float],
    monthly_pac_eur: float = 500.0,
    cash_balance: float = 0.0,
    sleeves: Optional[Dict[str, Any]] = None,
    kelly_result: Optional[KellyWeightsResult] = None,
) -> KellyPortfolioReport:
    """
    Valuta lo stato di Kelly Stack contro pesi target gia' calcolati da
    compute_kelly_weights, genera la raccomandazione PAC (stesso algoritmo
    "water-filling" di evaluate_convex_stack — riusato, non reinventato) e gli
    alert di trim.

    target_weights e' un parametro esplicito (non ricalcolato qui) perche' il
    calcolo dei pesi Kelly (compute_kelly_weights) e la valutazione del
    portafoglio contro quei pesi sono responsabilita' distinte e testabili
    separatamente — stessa separazione gia' presente tra
    apex_v2_engine.compute_v2_macro_signal e backend.py.update_portfolio.
    """
    sleeves = sleeves if sleeves is not None else KELLY_SLEEVES
    total_val = cash_balance
    values = {}

    for k in sleeves:
        shares = max(0.0, float(current_holdings.get(k, 0.0)))
        px = max(0.0, float(market_prices.get(k, 1.0)))
        val = shares * px
        values[k] = val
        total_val += val

    if total_val <= 0:
        total_val = 1.0

    sleeve_status = {}
    trim_alerts = []
    deficits = {}

    for k, info in sleeves.items():
        shares = max(0.0, float(current_holdings.get(k, 0.0)))
        px = max(0.0, float(market_prices.get(k, 1.0)))
        val = values[k]
        w_cur = val / total_val
        w_tgt = max(0.0, target_weights.get(k, 0.0))
        diff = w_tgt - w_cur
        deficits[k] = diff

        band = w_tgt * info["tolerance_band"]
        tol_min = max(0.0, w_tgt - band)
        tol_max = w_tgt + band
        is_under = w_cur < tol_min
        is_over = w_cur > tol_max
        req_trim = False
        trim_eur = 0.0

        # Stesso vincolo di Convex (convex_engine.py): il trim forzato scatta solo
        # sugli strumenti a "reddito diverso" (minusvalenza compensabile) — mai su
        # quelli a "reddito di capitale", dove venderebbe realizzando una
        # plusvalenza non compensabile senza un motivo di rischio urgente.
        if is_over and info["tax_type"] == "REDDITO_DIVERSO":
            req_trim = True
            trim_eur = max(0.0, (w_cur - w_tgt) * total_val)
            trim_alerts.append({
                "asset": k,
                "name": info["name"],
                "current_weight": w_cur,
                "threshold_max": tol_max,
                "excess_eur": trim_eur,
                "shares_to_sell": int(trim_eur / px) if px > 0 else 0,
                "tax_note": "Plusvalenza COMPENSABILE con minusvalenze pregresse (Reddito Diverso ETC/ETP).",
            })

        sleeve_status[k] = KellySleeveStatus(
            key=k, name=info["name"], target_weight=w_tgt,
            current_shares=shares, current_price=px, current_value=val,
            current_weight=w_cur, weight_diff=diff,
            is_underweight=is_under, is_overweight=is_over,
            requires_trim=req_trim, trim_amount_eur=trim_eur,
            tax_type=info["tax_type"],
        )

    pac_action = None
    if monthly_pac_eur > 0 and deficits:
        target_asset = max(deficits.items(), key=lambda x: x[1])[0]
        t_info = sleeves[target_asset]
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
                f"Sleeve più sottopesata rispetto al target Kelly corrente "
                f"(peso attuale {sleeve_status[target_asset].current_weight*100:.1f}% "
                f"vs target {target_weights.get(target_asset, 0.0)*100:.1f}%)."
            ),
        )

    gross_leverage = sum(s.current_weight for s in sleeve_status.values())

    return KellyPortfolioReport(
        total_value=total_val,
        sleeves=sleeve_status,
        pac_action=pac_action,
        trim_alerts=trim_alerts,
        gross_leverage=gross_leverage,
        kelly_result=kelly_result,
    )


# ==============================================================================
# TEST RAPIDO DI INTEGRITÀ UNITARIA
# ==============================================================================
if __name__ == "__main__":
    print("Test rapido kelly_engine.py:")
    res = compute_kelly_weights()
    print(f"Pesi Kelly pieni: { {k: round(v, 3) for k, v in res.raw_kelly_weights.items()} }")
    print(f"Pesi frazionari (k={KELLY_FRACTION}): { {k: round(v, 3) for k, v in res.fractional_weights.items()} }")
    print(f"Leva lorda grezza: {res.gross_leverage_raw*100:.1f}% -> dopo tetto/governatori: {res.gross_leverage_final*100:.1f}%")

    holdings_example = {"NTSG": 500, "AVWS": 200, "DBMFE": 300, "PPFB": 100, "WBTC": 50, "JELS": 150}
    prices_example = {"NTSG": 100.0, "AVWS": 50.0, "DBMFE": 25.0, "PPFB": 50.0, "WBTC": 100.0, "JELS": 100.0}
    rep = evaluate_kelly_stack(holdings_example, prices_example, res.final_weights, monthly_pac_eur=500.0, kelly_result=res)
    print(f"Valore Totale Kelly Stack: € {rep.total_value:,.2f}")
    print(f"Leva lorda corrente (da holding): {rep.gross_leverage*100:.1f}%")
    if rep.pac_action:
        print(f"Azione PAC Consigliata: Compra {rep.pac_action.recommended_asset} ({rep.pac_action.estimated_shares} quote)")
    print("kelly_engine.py operativo con successo!")
