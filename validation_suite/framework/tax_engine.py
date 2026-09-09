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
    rebalance_every: int = 1,
) -> pd.Series:
    """
    target_weights puo' essere un dict a pesi FISSI oppure un pd.DataFrame con
    un peso per ciascun asset per ciascun mese — stesso ciclo di
    ribilanciamento/tassazione in entrambi i casi, cambia solo il target verso
    cui ribilanciare ogni mese. Un peso implicito su un asset non elencato quel
    mese vale 0 (cash, mai tassato).

    tax_types[asset] deve essere "REDDITO_CAPITALE" (minusvalenze perse, non
    compensabili — ETF/fondi) o "REDDITO_DIVERSO" (minusvalenze compensabili
    con plusvalenze successive dello stesso pool — titoli/ETC/ETP/crypto).

    Semplificazione dichiarata: costo medio ponderato (PMC) senza il limite
    FIFO a 4 anni sul riporto minusvalenze (verificato altrove nel progetto
    che quel limite quasi mai vincola su un orizzonte di questa lunghezza) e
    senza costi di transazione (separati dalla tassazione, non modellati qui
    per isolare l'effetto fiscale).

    Ritorna la serie dei rendimenti periodici NETTI di tassazione.

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

        # 3. ribilancia le posizioni verso i pesi target (del periodo corrente) rispetto al
        #    NUOVO nav (pre-tasse), tassando solo il delta venduto (mai l'intera posizione)
        tax_due = 0.0
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

    return pd.Series(net_returns, index=sleeve_returns.index)
