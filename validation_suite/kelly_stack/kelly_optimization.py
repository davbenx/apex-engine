"""
kelly_optimization.py — Solver esatto per il problema Kelly multi-asset
vincolato long-only, a sostituire l'approssimazione (clip a zero della
soluzione non vincolata) usata finora in kelly_engine.compute_kelly_weights
(KELLY_STACK_SPEC.md §2, §7.2 punto 4).

Problema:
    max_f   f^T mu - 0.5 f^T Sigma f      s.t.  f >= 0

Sigma e' semidefinita positiva (e' una covarianza) quindi l'obiettivo e'
CONCAVO — non serve un solver generico non lineare, basta un metodo del
gradiente proiettato (projected gradient ascent): ad ogni passo si sale nella
direzione del gradiente e si proietta sul vincolo f>=0 (qui banale: clip a
zero), garantito a convergere al vero massimo globale vincolato per un
obiettivo concavo con vincoli convessi (qui l'ortante positivo).

Perche' non il clip semplice della soluzione non vincolata: quando il
vincolo f>=0 e' attivo su una sleeve, la soluzione VINCOLATA ottimale sulle
altre sleeve in generale NON coincide con i loro valori non vincolati — il
clip lascia valore sul tavolo. La differenza e' verificata nei test (il clip
non e' MAI strettamente meglio della QP esatta, e su alcuni input e'
strettamente peggiore).

Nessuna dipendenza da scipy (stesso principio del resto del progetto:
niente nuove dipendenze quando basta la libreria standard/numpy).
"""

from __future__ import annotations
import numpy as np


def solve_kelly_qp_long_only(
    mu: np.ndarray,
    cov: np.ndarray,
    max_iter: int = 5000,
    tol: float = 1e-10,
) -> np.ndarray:
    """
    Risolve max_f f^T mu - 0.5 f^T Sigma f s.t. f>=0 via projected gradient
    ascent con step size garantito convergente (1/L, L = massimo autovalore
    di Sigma — passo standard per funzioni concave con gradiente Lipschitz).

    mu: vettore (n,) di rendimenti attesi in eccesso.
    cov: matrice (n,n) di covarianza, semidefinita positiva.
    Ritorna: vettore (n,) dei pesi ottimali, tutti >= 0.
    """
    n = len(mu)
    eigmax = float(np.linalg.eigvalsh(cov).max())
    step = 1.0 / eigmax if eigmax > 1e-10 else 1.0

    f = np.zeros(n)
    for _ in range(max_iter):
        grad = mu - cov @ f
        f_new = np.clip(f + step * grad, 0.0, None)
        if np.max(np.abs(f_new - f)) < tol:
            f = f_new
            break
        f = f_new
    return f


def kelly_objective(f: np.ndarray, mu: np.ndarray, cov: np.ndarray) -> float:
    """Valore dell'obiettivo Kelly (crescita geometrica approssimata) per un
    dato vettore di pesi — usato nei test per confrontare QP esatta vs clip."""
    return float(f @ mu - 0.5 * f @ cov @ f)
