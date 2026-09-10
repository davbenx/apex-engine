"""
test_apex_v2_institutional_validation.py — chiude il gap piu' rilevante trovato
nell'audit di validation_suite/ (settembre 2026): il framework di invalidazione
istituzionale (Deflated Sharpe Ratio, block bootstrap — vedi
validation_suite/framework/statistical_validation.py) era stato applicato SOLO
a Kelly Stack (esplorato e scartato) e MAI alla strategia realmente in
produzione con soldi veri, Apex V2. Questo file applica lo stesso rigore alla
serie reale di rendimenti mensili di Apex V2 (apex_monthly_returns_extended.csv
/ _gross.csv, alla radice del repo — la stessa serie usata da
portfolio_manager.get_apex_metrics() per le cifre mostrate in dashboard).

Cosa NON fa: non ricalcola il backtest, non testa apex_v2_engine.py (quello e'
test_apex_v2_engine.py) — legge la serie di rendimenti gia' prodotta e ne
verifica la solidita' statistica con strumenti anti-overfitting standard.

Numero di trial per il DSR: la storia dei test documentati in
APEX_V2_SPEC.md §8 (28 sezioni "### 8.N", molte con piu' varianti testate
al loro interno — es. §8.9 "6 test", §8.27 "tre ipotesi" — e almeno 26 script
di ricerca distinti citati per nome) non da' un conteggio esatto e univoco.
Riportiamo il DSR a una GRIGLIA di N verosimili (20/50/100) invece di un
singolo numero taroccato di precisione — onesto sotto incertezza, invece di
fingere un conteggio esatto che non esiste.
"""
import os

import numpy as np
import pandas as pd
import pytest

from statistical_validation import deflated_sharpe_ratio, block_bootstrap_ci
from metrics import cagr, sharpe, max_drawdown

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TEST_PERIOD_START = "2020-09-30"  # split TRAIN/TEST documentato in portfolio_manager.py (72+72 mesi)

# Lower bound difendibile e non un numero esatto — vedi docstring sopra.
N_TRIALS_GRID = [20, 50, 100]


def _load_series(filename: str) -> pd.Series:
    path = os.path.join(REPO_ROOT, filename)
    return pd.read_csv(path, index_col=0, parse_dates=True).iloc[:, 0]


@pytest.fixture(scope="module")
def apex_net_full():
    return _load_series("apex_monthly_returns_extended.csv")


@pytest.fixture(scope="module")
def apex_gross_full():
    return _load_series("apex_monthly_returns_extended_gross.csv")


def test_track_record_files_match_documented_split():
    """Verifica che il file abbia davvero 471 mesi (1987-06 -> 2026-08, esteso
    con proxy VFINX/VUSTX/GC=F — vedi apex_dashboard_stat_regeneration.py) con
    72 mesi di TEST dal 2020-09-30 documentati in portfolio_manager.py — se
    questo file cambia forma (es. viene rigenerato con una finestra diversa)
    gli altri test qui dentro vanno riletti, non solo rieseguiti."""
    net = _load_series("apex_monthly_returns_extended.csv")
    assert len(net) == 471
    test_period = net.loc[TEST_PERIOD_START:]
    assert len(test_period) == 72, (
        "lo split TEST documentato (72 mesi, dal 2020-09-30) non corrisponde piu' al file reale — "
        "aggiorna TEST_PERIOD_START o la documentazione in portfolio_manager.py, non solo questo test"
    )


def test_dsr_full_sample_stays_meaningfully_positive_across_plausible_trial_counts(apex_net_full):
    """Il DSR (probabilita' che lo Sharpe osservato sia genuinamente positivo,
    corretto per il numero di varianti effettivamente provate) sul campione
    pieno (471 mesi) deve restare sostanzialmente sopra 0.5 anche assumendo un
    numero di tentativi alto (100) — altrimenti l'alpha di Apex V2 sarebbe
    difendibile solo per un numero di trial implausibilmente basso, un segnale
    di overfitting che varrebbe la pena approfondire."""
    sr = sharpe(apex_net_full)
    for n_trials in N_TRIALS_GRID:
        dsr = deflated_sharpe_ratio(sr, n_trials=n_trials, n_obs=len(apex_net_full))
        assert dsr > 0.5, (
            f"DSR campione pieno con {n_trials} trial = {dsr:.3f} (Sharpe osservato {sr:.2f}) — "
            "sotto 0.5 indicherebbe che l'edge apparente potrebbe essere un artefatto di selezione"
        )


def test_dsr_out_of_sample_test_period_stays_meaningfully_positive(apex_net_full):
    """Stesso controllo ma SOLO sul periodo TEST (72 mesi, 2020-09-30 in poi) —
    la prova piu' onesta perche' quei mesi non sono mai stati usati per
    scegliere i parametri della strategia (vedi nota in portfolio_manager.py)."""
    test_series = apex_net_full.loc[TEST_PERIOD_START:]
    sr = sharpe(test_series)
    for n_trials in N_TRIALS_GRID:
        dsr = deflated_sharpe_ratio(sr, n_trials=n_trials, n_obs=len(test_series))
        assert dsr > 0.5, (
            f"DSR periodo TEST (fuori campione) con {n_trials} trial = {dsr:.3f} (Sharpe {sr:.2f}) — "
            "sotto 0.5 sul periodo mai usato per scegliere i parametri sarebbe un segnale serio"
        )


def test_bootstrap_ci_sharpe_excludes_zero_on_test_period(apex_net_full):
    """Intervallo di confidenza al 90% (block bootstrap, blocchi di 6 mesi per
    preservare l'autocorrelazione) sullo Sharpe del periodo TEST: deve escludere
    zero. Se lo zero cade dentro l'intervallo, l'apparente edge fuori campione
    non e' distinguibile dal rumore campionario a questo livello di confidenza."""
    test_series = apex_net_full.loc[TEST_PERIOD_START:]
    lo, hi = block_bootstrap_ci(test_series.values, sharpe, block_size=6, ci=0.90, seed=42)
    assert lo > 0.0, (
        f"CI 90% sullo Sharpe TEST = [{lo:.2f}, {hi:.2f}] — "
        "include lo zero: l'edge fuori campione non e' statisticamente distinguibile dal rumore a questo livello"
    )


def test_net_series_never_produces_impossible_drawdown(apex_net_full, apex_gross_full):
    """Difesa contro un file corrotto/rigenerato male: un drawdown mensile
    composto sotto -100% (NAV negativo) e' matematicamente impossibile e
    indicherebbe un bug nella serie stessa, non un evento di mercato."""
    for series, label in [(apex_net_full, "netto"), (apex_gross_full, "lordo")]:
        dd = max_drawdown(series)
        assert -1.0 < dd <= 0.0, f"drawdown {label} impossibile ({dd:.2%}): la serie e' probabilmente corrotta"


def test_net_cagr_is_never_higher_than_gross_cagr(apex_net_full, apex_gross_full):
    """Le tasse riducono la ricchezza, non la aumentano — stessa invariante
    verificata su Kelly Stack (framework/test_tax_engine.py), qui applicata
    alla serie reale invece che a uno scenario sintetico."""
    assert cagr(apex_net_full) <= cagr(apex_gross_full) + 1e-9, (
        "il CAGR netto non deve mai superare il lordo sulla stessa strategia"
    )
