"""
kelly_validation.py — Strumenti di validazione istituzionale per eliminare bias di
data-snooping/overfitting, richiesti esplicitamente per Kelly Stack e già citati
come standard in APEX_V2_SPEC.md per l'audit di Apex v1.

Implementa due strumenti standard della letteratura (Bailey & Lopez de Prado):

1. Deflated Sharpe Ratio (DSR) — corregge lo Sharpe Ratio osservato per il numero
   di varianti/strategie effettivamente provate (multiple testing). Con abbastanza
   tentativi, un backtest con Sharpe alto ma spurio è quasi garantito per puro
   caso — il DSR risponde alla domanda "quanto è probabile che questo Sharpe sia
   vero, dato quante volte ho cercato?"

2. Probability of Backtest Overfitting (PBO) via CSCV (Combinatorially Symmetric
   Cross-Validation) — risponde a una domanda diversa e complementare: "se avessi
   scelto la strategia migliore in-sample tra le N provate, quanto spesso quella
   scelta si sarebbe rivelata sotto la mediana fuori campione?" Un PBO vicino al
   50% significa che il processo di selezione non fa meglio del caso.

Nessuna dipendenza da scipy (non nei requirements di questo progetto, stesso
principio di fetch_sector in backend.py: "nessuna nuova dipendenza" quando la
libreria standard basta) — CDF normale via math.erf, inversa via l'approssimazione
razionale di Acklam (accurata a ~1.15e-9, standard nella pratica quantitativa).
"""

from __future__ import annotations
import itertools
import math
from typing import List

import numpy as np


def _norm_cdf(x: float) -> float:
    """CDF della normale standard, via math.erf (libreria standard, no scipy)."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_ppf(p: float) -> float:
    """Inversa della CDF normale standard — approssimazione razionale di Acklam
    (no scipy). Accurata a ~1.15e-9 su tutto il dominio (0,1)."""
    if p <= 0.0:
        return -np.inf
    if p >= 1.0:
        return np.inf
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    p_low, p_high = 0.02425, 1 - 0.02425
    if p < p_low:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
               ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p <= p_high:
        q = p - 0.5
        r = q * q
        return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / \
               (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)
    q = math.sqrt(-2 * math.log(1 - p))
    return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
            ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)


EULER_MASCHERONI = 0.5772156649015329


def deflated_sharpe_ratio(
    observed_sr: float,
    n_trials: int,
    n_obs: int,
    skew: float = 0.0,
    kurtosis: float = 3.0,
) -> float:
    """
    Deflated Sharpe Ratio (Bailey & Lopez de Prado, 2014). Ritorna la probabilita'
    che lo Sharpe osservato sia genuinamente positivo, corretta per il numero di
    varianti indipendenti effettivamente provate (n_trials) — non solo per la
    lunghezza campionaria come un t-test ordinario sullo Sharpe.

    observed_sr: Sharpe Ratio annualizzato della strategia scelta.
    n_trials: numero di varianti/strategie indipendenti confrontate prima di
        scegliere questa (deve includere anche i tentativi respinti, non solo
        quello vincente — omettere i tentativi falliti e' la forma piu' comune di
        bias di selezione, esattamente cio' che questo strumento serve a correggere).
    n_obs: numero di osservazioni (es. mesi) usate per stimare lo Sharpe.
    skew/kurtosis: della distribuzione dei rendimenti periodali usati per stimare
        lo Sharpe — default a normale (skew=0, kurtosis=3) se non forniti, ma
        andrebbero passati i valori reali quando disponibili (rendimenti con coda
        grassa o asimmetria negativa gonfiano la varianza dello stimatore di
        Sharpe, la formula qui sotto lo corregge esplicitamente).

    Ritorna un valore in (0,1): vicino a 1 = alta confidenza che l'edge sia reale
    anche dopo aver corretto per quanti tentativi sono stati fatti; vicino a 0.5 =
    indistinguibile dal rumore dato il numero di tentativi.
    """
    if n_obs < 2:
        raise ValueError("servono almeno 2 osservazioni per stimare la varianza dello Sharpe")

    # Varianza dello stimatore di Sharpe, corretta per skew/kurtosi (Bailey/Lopez de Prado eq. 2-3)
    sr_var = (1.0 - skew * observed_sr + ((kurtosis - 1.0) / 4.0) * observed_sr**2) / (n_obs - 1)
    sr_std = math.sqrt(max(sr_var, 1e-12))

    if n_trials <= 1:
        expected_max_sr_null = 0.0
    else:
        z1 = _norm_ppf(1.0 - 1.0 / n_trials)
        z2 = _norm_ppf(1.0 - 1.0 / (n_trials * math.e))
        expected_max_sr_null = sr_std * ((1 - EULER_MASCHERONI) * z1 + EULER_MASCHERONI * z2)

    dsr = _norm_cdf((observed_sr - expected_max_sr_null) / sr_std)
    return float(dsr)


def block_bootstrap_ci(
    monthly_returns: np.ndarray,
    metric_fn,
    n_bootstrap: int = 2000,
    block_size: int = 6,
    ci: float = 0.90,
    seed: int = 42,
) -> tuple:
    """
    Intervallo di confidenza per una metrica (CAGR, Sharpe, ecc.) via block
    bootstrap sui rendimenti mensili — non un singolo numero puntuale come
    tutti i risultati riportati finora in KELLY_STACK_SPEC.md, ma la sua
    incertezza campionaria. "Block" (non bootstrap i.i.d. mese-per-mese):
    i rendimenti mensili sono autocorrelati (momentum/vol clustering), un
    resampling i.i.d. distruggerebbe quella struttura e sottostimerebbe
    l'incertezza vera — si ricampionano blocchi contigui di `block_size` mesi
    per preservarla almeno in parte (stessa idea dei blocchi in pbo_cscv).

    metric_fn: funzione che prende un array di rendimenti mensili e ritorna
    un float (es. _cagr, _sharpe di kelly_backtest.py).

    Ritorna (lower, upper): l'intervallo di confidenza `ci` (default 90%,
    percentili 5%-95% della distribuzione bootstrap).
    """
    rng = np.random.default_rng(seed)
    n = len(monthly_returns)
    n_blocks = int(np.ceil(n / block_size))

    estimates = []
    for _ in range(n_bootstrap):
        block_starts = rng.integers(0, n - block_size + 1, size=n_blocks)
        sample = np.concatenate([monthly_returns[s:s + block_size] for s in block_starts])[:n]
        estimates.append(metric_fn(sample))

    alpha = (1 - ci) / 2
    lower = float(np.percentile(estimates, alpha * 100))
    upper = float(np.percentile(estimates, (1 - alpha) * 100))
    return lower, upper


def pbo_cscv(performance_matrix: np.ndarray, n_splits: int = 8) -> float:
    """
    Probability of Backtest Overfitting via Combinatorially Symmetric
    Cross-Validation (Bailey, Borwein, Lopez de Prado, Zhu 2015).

    performance_matrix: array (T periodi x N varianti) di rendimenti periodali
    per ciascuna variante di strategia confrontata (es. diverse combinazioni di
    universo/parametri). N deve essere >= 2 (altrimenti non c'e' nulla da
    confrontare) e T deve essere divisibile per n_splits.

    Procedura: divide i T periodi in n_splits blocchi contigui, per ogni modo di
    scegliere meta' dei blocchi come "in-sample" (il resto "out-of-sample") sceglie
    la variante con Sharpe migliore IN-SAMPLE, poi guarda che rank ha quella stessa
    variante OUT-OF-SAMPLE. Se il processo di selezione fosse puro rumore, il
    vincitore in-sample dovrebbe finire mediamente a meta' classifica fuori
    campione (PBO alto, vicino al 50%) — se invece l'edge e' reale, il vincitore
    in-sample tende a restare tra i migliori anche fuori campione (PBO basso).

    Ritorna PBO in [0,1]: quota di combinazioni in cui il vincitore in-sample e'
    finito SOTTO la mediana fuori campione.
    """
    T, N = performance_matrix.shape
    if N < 2:
        raise ValueError("servono almeno 2 varianti da confrontare per calcolare il PBO")
    if T % n_splits != 0:
        raise ValueError(f"T={T} periodi non divisibile per n_splits={n_splits}")

    block_size = T // n_splits
    blocks = [performance_matrix[i*block_size:(i+1)*block_size, :] for i in range(n_splits)]

    def sharpe(returns_2d: np.ndarray) -> np.ndarray:
        mu = returns_2d.mean(axis=0)
        sd = returns_2d.std(axis=0, ddof=1)
        sd = np.where(sd < 1e-12, 1e-12, sd)
        return mu / sd

    half = n_splits // 2
    below_median_count = 0
    total_combos = 0

    for is_idx in itertools.combinations(range(n_splits), half):
        oos_idx = [i for i in range(n_splits) if i not in is_idx]
        is_data = np.vstack([blocks[i] for i in is_idx])
        oos_data = np.vstack([blocks[i] for i in oos_idx])

        is_sharpe = sharpe(is_data)
        oos_sharpe = sharpe(oos_data)

        winner = int(np.argmax(is_sharpe))
        # rank relativo del vincitore in-sample nella distribuzione OOS (0=peggiore, 1=migliore)
        rank = float(np.mean(oos_sharpe <= oos_sharpe[winner]))
        if rank < 0.5:
            below_median_count += 1
        total_combos += 1

    return below_median_count / total_combos
