"""
test_metrics.py — verifica su scenari sintetici a risultato noto di
cagr/sharpe/max_drawdown/calmar (framework/metrics.py). Estratti da
test_kelly_backtest.py: queste funzioni sono generiche, non specifiche a
Kelly Stack, ora vivono e si testano nel framework condiviso.
"""
import pandas as pd

from metrics import cagr, sharpe, max_drawdown, calmar


def test_cagr_constant_monthly_return():
    r = 0.01  # 1%/mese costante
    monthly = pd.Series([r] * 24)  # 2 anni
    expected = (1 + r) ** 12 - 1
    assert abs(cagr(monthly) - expected) < 1e-9


def test_cagr_zero_return_is_zero():
    monthly = pd.Series([0.0] * 12)
    assert abs(cagr(monthly)) < 1e-9


def test_max_drawdown_known_path():
    # NAV: 1.0 -> 1.2 -> 0.9 -> 1.1  => drawdown dal picco 1.2 a 0.9 = -25%
    monthly = pd.Series([0.20, -0.25, 0.2222222222])
    dd = max_drawdown(monthly)
    assert abs(dd - (-0.25)) < 1e-6


def test_sharpe_zero_vol_returns_zero_not_nan():
    monthly = pd.Series([0.01] * 12)  # rendimento costante, vol = 0
    assert sharpe(monthly) == 0.0


def test_calmar_matches_cagr_over_abs_maxdd():
    monthly = pd.Series([0.20, -0.25, 0.2222222222])
    expected = cagr(monthly) / abs(max_drawdown(monthly))
    assert abs(calmar(monthly) - expected) < 1e-9


def test_calmar_is_nan_when_no_drawdown_ever_occurs():
    """Una serie sempre in crescita non ha mai un drawdown: dividere per zero
    deve dare NaN esplicito, non una ZeroDivisionError o un numero fittizio —
    diversi script del progetto calcolavano questo rapporto inline senza
    questa protezione."""
    monthly = pd.Series([0.01] * 12)
    result = calmar(monthly)
    assert result != result  # NaN != NaN e' l'unico modo standard di verificarlo senza math.isnan
