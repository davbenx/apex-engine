"""
tax_engine.py — simulazione della tassazione italiana su un portafoglio a
pesi target verso cui si ribilancia periodicamente, tassando SOLO la
porzione effettivamente venduta ad ogni ribilanciamento (mai l'intera
posizione per un aggiustamento parziale di peso — stesso principio del bug
di produzione corretto in backend.py, APEX_V2_SPEC.md §8.8).

Estratta da kelly_backtest.py (`_apply_italian_tax`) perche' generica —
nessuna dipendenza da Kelly Stack — e riusata da tre script indipendenti in
validation_suite/comparative_studies/. Unica differenza rispetto
all'originale: `tax_types` qui e' obbligatorio (l'originale aveva un
fallback implicito ai nomi delle sleeve di Kelly Stack, che non ha senso
per un modulo generico — kelly_backtest.py mantiene quel fallback nel
proprio wrapper `_apply_italian_tax`, per compatibilita' con le proprie
chiamate interne).
"""
from __future__ import annotations
from typing import Dict, Optional

import pandas as pd

TAX_RATE_ITALY_FLAT = 0.26  # aliquota unica su redditi di capitale e redditi diversi


def apply_italian_tax(
    sleeve_returns: pd.DataFrame,
    target_weights,  # Dict[str, float] (fisso) oppure pd.DataFrame (un peso per mese, stesso indice di sleeve_returns)
    tax_types: Dict[str, str],
    rebalance_every: Optional[int] = 1,
    rebalance_threshold: Optional[float] = None,
    return_final_state: bool = False,
):
    """
    target_weights puo' essere un dict a pesi FISSI oppure un pd.DataFrame con
    un peso per ciascun asset per ciascun mese — stesso ciclo di
    ribilanciamento/tassazione in entrambi i casi, cambia solo il target verso
    cui ribilanciare ogni mese. Un peso implicito su un asset non elencato quel
    mese vale 0 (cash, mai tassato).

    rebalance_every: ogni quanti periodi eseguire l'aggiustamento verso il
    target (con relativo evento fiscale) — default 1 = ogni periodo
    (comportamento storico di questa funzione, invariato). None = MAI
    ribilanciare dopo l'allocazione iniziale (le posizioni derivano libere
    col proprio rendimento, nessuna vendita, nessuna tassa fino alla fine
    della serie) — la policy reale di Convex Stack ("mai vendere", vedi
    convex_engine.py), non modellabile prima di questo fix (il parametro
    esisteva nella firma ma non veniva mai letto nel corpo della funzione —
    bug trovato mentre si costruiva il test sul costo del never-sell,
    richiesto direttamente dall'utente). Con target_weights dinamico
    (DataFrame) rebalance_every si applica comunque: un target che CAMBIA
    da un periodo all'altro forza un evento anche in un periodo "silenzioso"
    solo se rebalance_every=1 lo raggiunge; con rebalance_every>1 o None il
    target intermedio viene ignorato fino al prossimo evento programmato —
    va usato con target dinamico solo se questo comportamento e' voluto.

    rebalance_threshold: alternativa a rebalance_every, per il ribilanciamento
    "a soglia di tolleranza" (Daryanani 2008, Masters 2003) — invece di
    ribilanciare a calendario, si ribilancia SOLO quando almeno una sleeve si
    e' allontanata dal proprio peso target (in punti di peso assoluti, dopo la
    rivalutazione di mercato del periodo, prima del ribilanciamento) di piu' di
    questa soglia (es. 0.05 = 5 punti percentuali). Se impostato, ha la
    PRECEDENZA su rebalance_every (che viene ignorato) — i due meccanismi non
    si combinano, sono due policy alternative. None (default) mantiene il
    comportamento a calendario invariato per tutti i chiamanti esistenti.

    tax_types[asset] deve essere "REDDITO_CAPITALE" (minusvalenze perse, non
    compensabili — ETF/fondi) o "REDDITO_DIVERSO" (minusvalenze compensabili
    con plusvalenze successive dello stesso pool — titoli/ETC/ETP/crypto).

    Semplificazione dichiarata: costo medio ponderato (PMC) senza il limite
    FIFO a 4 anni sul riporto minusvalenze (verificato altrove nel progetto
    che quel limite quasi mai vincola su un orizzonte di questa lunghezza) e
    senza costi di transazione (separati dalla tassazione, non modellati qui
    per isolare l'effetto fiscale).

    Ritorna la serie dei rendimenti periodici NETTI di tassazione — oppure,
    se return_final_state=True, la tupla (serie, final_state) dove
    final_state = {"value", "cost_basis", "loss_pool_diverso", "nav"} e'
    lo stato di posizione all'ULTIMO periodo simulato, da passare a
    liquidation_tax_adjusted_nav() per calcolare la passivita' fiscale
    LATENTE su posizioni mai vendute (rilevante soprattutto con
    rebalance_every=None/rebalance_threshold molto larga: senza mai un
    ribilanciamento, questa funzione non tassa MAI, nemmeno alla fine della
    serie — la tassa non e' azzerata, e' solo posticipata oltre l'orizzonte
    simulato, e un confronto "a chi va meglio" contro una policy che paga le
    tasse lungo il percorso e' fuorviante senza rendere esplicita questa
    passivita' latente — concern d'audit, vedi README). Default False,
    nessuna regressione per i chiamanti esistenti.

    NAV (capitale proprio) e valore nozionale delle posizioni sono tenuti
    ESPLICITAMENTE separati: con leva (somma dei pesi target > 100%), il
    valore nozionale delle posizioni supera il NAV per costruzione — sommare
    i valori nozionali e trattarli come se fossero il NAV produce un errore
    di scala che si COMPONE ogni periodo (bug reale trovato e corretto
    durante lo sviluppo di questa funzione: un CAGR netto assurdo, >10.000%,
    causato esattamente da questa confusione).
    """
    is_dynamic = isinstance(target_weights, pd.DataFrame)
    first_weights = target_weights.iloc[0].to_dict() if is_dynamic else target_weights
    keys = list(first_weights.keys())
    nav = 1.0  # capitale proprio — MAI ricavato sommando i valori nozionali delle posizioni
    value = {k: first_weights[k] * nav for k in keys}  # valori nozionali, la somma puo' superare nav (leva)
    cost_basis = dict(value)
    loss_pool_diverso = 0.0  # minusvalenze REDDITO_DIVERSO non ancora compensate

    net_returns = []
    for i, (_, row) in enumerate(sleeve_returns.iterrows()):
        target_weights_t = target_weights.iloc[i].to_dict() if is_dynamic else target_weights

        # 1. rendimento lordo di portafoglio del periodo dai pesi CORRENTI (rispetto al nav
        #    pre-rivalutazione) — stessa convenzione lineare gia' usata per port_gross
        weights_now = {k: value[k] / nav for k in keys}
        gross_port_return = sum(weights_now[k] * row[k] for k in keys)
        nav_after_market = nav * (1 + gross_port_return)

        # 2. rivaluta ciascuna posizione al proprio rendimento
        for k in keys:
            value[k] *= (1 + row[k])

        # 3. ribilancia le posizioni verso i pesi target SOLO nei periodi di
        #    ribilanciamento programmati (rebalance_every) — negli altri periodi
        #    le posizioni restano quelle appena rivalutate (nessuna vendita,
        #    nessun evento fiscale, esattamente la policy "mai vendere" di
        #    Convex Stack quando rebalance_every=None). Quando si ribilancia,
        #    la tassa colpisce solo il delta effettivamente venduto (mai
        #    l'intera posizione per un aggiustamento parziale di peso).
        if rebalance_threshold is not None:
            weights_after_market = {k: value[k] / nav_after_market for k in keys} if nav_after_market > 1e-12 else {k: 0.0 for k in keys}
            max_drift = max(abs(weights_after_market[k] - target_weights_t.get(k, 0.0)) for k in keys)
            should_rebalance = max_drift > rebalance_threshold
        else:
            should_rebalance = rebalance_every is not None and (i + 1) % rebalance_every == 0
        tax_due = 0.0
        if should_rebalance:
            for k in keys:
                target_val = target_weights_t.get(k, 0.0) * nav_after_market
                delta = target_val - value[k]
                if delta < 0:
                    sold_fraction = min(1.0, (-delta) / value[k]) if value[k] > 1e-12 else 0.0
                    cost_sold = cost_basis[k] * sold_fraction
                    proceeds_sold = value[k] * sold_fraction
                    gain = proceeds_sold - cost_sold
                    tax_type = tax_types[k]
                    if tax_type == "REDDITO_CAPITALE":
                        if gain > 0:
                            tax_due += gain * TAX_RATE_ITALY_FLAT
                        # minusvalenza REDDITO_CAPITALE: persa, non compensabile
                    else:  # REDDITO_DIVERSO
                        if gain > 0:
                            offset = min(gain, loss_pool_diverso)
                            loss_pool_diverso -= offset
                            tax_due += (gain - offset) * TAX_RATE_ITALY_FLAT
                        else:
                            loss_pool_diverso += -gain
                    cost_basis[k] -= cost_sold
                else:
                    cost_basis[k] += delta  # acquisto: aggiorna il costo base (media ponderata, PMC)
                value[k] = target_val

        nav_after_tax = nav_after_market - tax_due
        # la tassa riduce il capitale proprio: scala tutte le posizioni proporzionalmente
        # per mantenere la leva target costante dopo il prelievo fiscale
        if nav_after_market > 1e-12 and tax_due > 0:
            scale = nav_after_tax / nav_after_market
            for k in keys:
                value[k] *= scale
                cost_basis[k] *= scale

        net_returns.append(nav_after_tax / nav - 1)
        nav = nav_after_tax

    net_series = pd.Series(net_returns, index=sleeve_returns.index)
    if return_final_state:
        return net_series, {"value": value, "cost_basis": cost_basis, "loss_pool_diverso": loss_pool_diverso, "nav": nav}
    return net_series


def liquidation_tax_adjusted_nav(final_state: Dict, tax_types: Dict[str, str]) -> float:
    """NAV se si liquidasse TUTTA la posizione subito dopo l'ultimo periodo
    simulato da apply_italian_tax(..., return_final_state=True) — rende
    esplicita la passivita' fiscale LATENTE su posizioni mai vendute (mai
    zero, solo posticipata oltre l'orizzonte simulato con
    rebalance_every=None o una soglia mai raggiunta), per un confronto equo
    con varianti che pagano le tasse lungo il percorso (concern d'audit,
    vedi README — "Convex mai vendere non tassa mai, nemmeno a fine serie").

    Semplificazione dichiarata: tutte le posizioni REDDITO_DIVERSO sono
    liquidate INSIEME in un unico evento — guadagni e perdite tra loro (piu'
    l'eventuale loss_pool_diverso gia' accumulato) si compensano PRIMA di
    applicare l'aliquota, indipendentemente dall'ordine con cui i singoli
    asset sarebbero venduti nella realta' (l'ordine non dovrebbe contare per
    vendite simultanee, a differenza del ciclo per-periodo di
    apply_italian_tax, dove l'ordine di iterazione sugli asset puo' influire
    lievemente se piu' vendite avvengono nello stesso periodo — un limite
    preesistente di quella funzione, non introdotto qui)."""
    value, cost_basis, loss_pool = final_state["value"], final_state["cost_basis"], final_state["loss_pool_diverso"]
    # NAV di partenza dallo stato tracciato (mai la somma dei valori nozionali: con leva
    # quella somma supera il NAV per costruzione — stesso principio gia' documentato in
    # apply_italian_tax, l'errore di scala che aveva causato il bug del CAGR >10.000%).
    tax_due = 0.0
    diverso_gain_total = 0.0
    for k in value:
        gain = value[k] - cost_basis[k]
        if tax_types[k] == "REDDITO_CAPITALE":
            if gain > 0:
                tax_due += gain * TAX_RATE_ITALY_FLAT
            # minusvalenza REDDITO_CAPITALE: persa, non compensabile (come nel ciclo principale)
        else:
            diverso_gain_total += gain
    if diverso_gain_total > 0:
        offset = min(diverso_gain_total, loss_pool)
        tax_due += (diverso_gain_total - offset) * TAX_RATE_ITALY_FLAT
    return final_state["nav"] - tax_due
