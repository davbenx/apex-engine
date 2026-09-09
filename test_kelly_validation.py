"""
test_kelly_validation.py — Verifica su dati sintetici a comportamento noto che DSR
e PBO si comportino come la teoria prevede, prima di applicarli ai dati reali di
kelly_backtest.py. Stessa disciplina di test_apex_v2_engine.py.
"""
import numpy as np

from kelly_validation import deflated_sharpe_ratio, pbo_cscv, _norm_cdf, _norm_ppf


def test_norm_cdf_ppf_are_inverses():
    """Verifica di correttezza delle approssimazioni numeriche (no scipy): CDF e PPF
    devono essere l'una l'inversa dell'altra su un range di valori ragionevoli."""
    for p in [0.001, 0.01, 0.05, 0.1, 0.5, 0.9, 0.95, 0.99, 0.999]:
        x = _norm_ppf(p)
        assert abs(_norm_cdf(x) - p) < 1e-6, f"norm_cdf(norm_ppf({p})) deve tornare {p}"


def test_norm_cdf_known_values():
    """Valori noti della normale standard (tabulati)."""
    assert abs(_norm_cdf(0.0) - 0.5) < 1e-9
    assert abs(_norm_cdf(1.96) - 0.975) < 1e-3
    assert abs(_norm_cdf(-1.96) - 0.025) < 1e-3


def test_dsr_decreases_with_more_trials():
    """Piu' varianti si provano prima di scegliere la vincente, meno e' credibile
    lo stesso Sharpe osservato — il fatto centrale che il DSR e' costruito per
    correggere (data-snooping)."""
    sr = 1.2
    n_obs = 60
    dsr_few = deflated_sharpe_ratio(sr, n_trials=1, n_obs=n_obs)
    dsr_many = deflated_sharpe_ratio(sr, n_trials=100, n_obs=n_obs)
    assert dsr_many < dsr_few, "con piu' tentativi, lo stesso Sharpe osservato deve valere meno"


def test_dsr_high_with_single_trial_and_strong_sharpe():
    """Con un solo tentativo (nessun multiple-testing) e uno Sharpe alto su un
    campione lungo, il DSR deve essere vicino a 1 (alta confidenza)."""
    dsr = deflated_sharpe_ratio(observed_sr=1.5, n_trials=1, n_obs=120)
    assert dsr > 0.95


def test_dsr_low_with_many_trials_and_weak_sharpe():
    """Con uno Sharpe modesto e centinaia di tentativi, il DSR deve segnalare che
    il risultato e' plausibilmente rumore (vicino o sotto 0.5)."""
    dsr = deflated_sharpe_ratio(observed_sr=0.3, n_trials=500, n_obs=60)
    assert dsr < 0.5


def test_pbo_near_half_on_pure_noise():
    """Su varianti che sono TUTTE puro rumore (stessa distribuzione, nessun edge
    vero in nessuna), il processo "scegli la migliore in-sample" non deve fare
    meglio del caso fuori campione — PBO atteso vicino al 50%."""
    rng = np.random.default_rng(42)
    T, N, n_splits = 96, 10, 8
    perf = rng.normal(0.0, 0.05, size=(T, N))  # tutte iid, nessuna variante ha edge vero
    pbo = pbo_cscv(perf, n_splits=n_splits)
    assert 0.25 < pbo < 0.75, f"PBO su puro rumore deve essere vicino al 50%, ottenuto {pbo:.2f}"


def test_pbo_low_when_one_variant_has_persistent_edge():
    """Se UNA variante ha davvero un rendimento medio piu' alto delle altre in OGNI
    periodo (non solo per caso in-sample), il vincitore in-sample deve restare
    vincente anche fuori campione quasi sempre — PBO atteso basso."""
    rng = np.random.default_rng(7)
    T, N, n_splits = 96, 10, 8
    perf = rng.normal(0.0, 0.05, size=(T, N))
    perf[:, 0] += 0.03  # variante 0 ha un vero edge persistente, non rumore
    pbo = pbo_cscv(perf, n_splits=n_splits)
    assert pbo < 0.25, f"PBO con un edge vero e persistente deve essere basso, ottenuto {pbo:.2f}"


def test_pbo_requires_at_least_two_variants():
    import pytest
    with pytest.raises(ValueError):
        pbo_cscv(np.zeros((96, 1)), n_splits=8)
