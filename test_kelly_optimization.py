"""
test_kelly_optimization.py — Verifica del solver QP Kelly long-only su casi
con soluzione nota, prima di sostituirlo al clip approssimato in
kelly_engine.py.
"""
import numpy as np

from kelly_optimization import solve_kelly_qp_long_only, kelly_objective


def test_qp_matches_unconstrained_when_all_positive():
    """Se la soluzione non vincolata e' gia' tutta non-negativa (asset scorrelati,
    mu tutti positivi), la QP vincolata deve coincidere con quella semplice
    f*=mu/sigma^2 elemento per elemento — il vincolo non deve fare nulla quando
    non e' attivo."""
    mu = np.array([0.05, 0.08, 0.03])
    sigma = np.array([0.15, 0.20, 0.10])
    cov = np.diag(sigma ** 2)
    f = solve_kelly_qp_long_only(mu, cov)
    expected = mu / sigma ** 2
    assert np.allclose(f, expected, atol=1e-4)


def test_qp_zeros_out_asset_with_negative_unconstrained_weight():
    """Un asset con mu tale che la soluzione non vincolata sarebbe negativa
    deve finire a peso ESATTAMENTE zero (vincolo attivo) nella QP."""
    mu = np.array([0.05, -0.02])
    corr = np.array([[1.0, 0.5], [0.5, 1.0]])
    sigma = np.array([0.15, 0.15])
    cov = np.outer(sigma, sigma) * corr
    f_unconstrained = np.linalg.solve(cov, mu)
    assert f_unconstrained[1] < 0, "il test presuppone che l'asset 2 abbia peso non vincolato negativo"

    f_qp = solve_kelly_qp_long_only(mu, cov)
    assert f_qp[1] == 0.0 or abs(f_qp[1]) < 1e-6


def test_qp_beats_or_matches_naive_clip_objective():
    """La QP esatta non deve MAI ottenere un valore dell'obiettivo peggiore del
    clip a zero della soluzione non vincolata — e su un caso con vincolo
    attivo e correlazione, deve fare STRETTAMENTE meglio (il punto centrale
    per cui il clip e' solo un'approssimazione, non la soluzione vera)."""
    mu = np.array([0.05, -0.01, 0.06])
    corr = np.array([
        [1.0, 0.6, 0.2],
        [0.6, 1.0, 0.3],
        [0.2, 0.3, 1.0],
    ])
    sigma = np.array([0.15, 0.20, 0.18])
    cov = np.outer(sigma, sigma) * corr

    f_unconstrained = np.linalg.solve(cov, mu)
    f_clip = np.clip(f_unconstrained, 0.0, None)
    f_qp = solve_kelly_qp_long_only(mu, cov)

    obj_clip = kelly_objective(f_clip, mu, cov)
    obj_qp = kelly_objective(f_qp, mu, cov)

    assert obj_qp >= obj_clip - 1e-9
    assert obj_qp > obj_clip + 1e-6, (
        "su questo input con vincolo attivo e correlazione, la QP deve fare "
        "strettamente meglio del clip — altrimenti il clip non sarebbe "
        "un'approssimazione, sarebbe gia' la soluzione esatta"
    )


def test_qp_all_zero_when_all_mu_nonpositive():
    """Se nessun asset ha rendimento atteso positivo, la soluzione ottima
    vincolata e' non investire in nulla (tutti pesi zero) — Kelly non
    scommette mai su un'attesa non positiva."""
    mu = np.array([-0.01, -0.02, 0.0])
    cov = np.diag([0.04, 0.09, 0.01])
    f = solve_kelly_qp_long_only(mu, cov)
    assert np.allclose(f, 0.0, atol=1e-6)


def test_qp_weights_are_never_negative():
    rng = np.random.default_rng(3)
    for _ in range(20):
        n = rng.integers(2, 6)
        mu = rng.normal(0.02, 0.08, n)
        A = rng.normal(0, 0.2, (n, n))
        cov = A @ A.T + np.eye(n) * 0.01  # garantita PSD
        f = solve_kelly_qp_long_only(mu, cov)
        assert (f >= -1e-8).all()
