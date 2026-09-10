"""
test_metrics.py — verifica su scenari sintetici a risultato noto di
cagr/sharpe/max_drawdown/calmar (framework/metrics.py). Estratti da
test_kelly_backtest.py: queste funzioni sono generiche, non specifiche a
Kelly Stack, ora vivono e si testano nel framework condiviso.
"""
import pandas as pd

from metrics import cagr, sharpe, max_drawdown, calmar, sortino_ratio, ulcer_index


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


def test_sharpe_daily_annualization_differs_from_monthly_default():
    """Bug latente reale: usare il default mensile (periods_per_year=12) su
    una serie daily annualizzerebbe con sqrt(12) invece di sqrt(365) — uno
    Sharpe sbagliato per un fattore ~5.5x, silenziosamente. periods_per_year
    deve cambiare il risultato in modo prevedibile (stesso rapporto delle
    radici)."""
    daily = pd.Series([0.001] * 100 + [-0.0005] * 50)  # vol non nulla, valore arbitrario
    sr_monthly_default = sharpe(daily)
    sr_daily = sharpe(daily, periods_per_year=365)
    ratio = sr_daily / sr_monthly_default
    expected_ratio = (365 ** 0.5) / (12 ** 0.5)
    assert abs(ratio - expected_ratio) < 1e-9


def test_cagr_daily_periods_per_year_gives_lower_implied_years_than_monthly_default():
    """252 giorni ~ 1 anno di trading, ma con periods_per_year=365 (crypto
    24/7, non 252 come le borse azionarie) lo stesso conteggio di
    osservazioni implica MENO anni che con il default mensile (12) — cioe'
    un CAGR piu' alto in valore assoluto per un rendimento totale identico."""
    returns = pd.Series([0.0005] * 365)  # esattamente 1 "anno crypto" di osservazioni
    g = cagr(returns, periods_per_year=365)
    total_growth = (1 + returns).prod()
    assert abs(g - (total_growth - 1)) < 1e-6, "con esattamente 365 osservazioni e periods_per_year=365, CAGR == crescita totale (1 anno)"


def test_calmar_is_nan_when_no_drawdown_ever_occurs():
    """Una serie sempre in crescita non ha mai un drawdown: dividere per zero
    deve dare NaN esplicito, non una ZeroDivisionError o un numero fittizio —
    diversi script del progetto calcolavano questo rapporto inline senza
    questa protezione."""
    monthly = pd.Series([0.01] * 12)
    result = calmar(monthly)
    assert result != result  # NaN != NaN e' l'unico modo standard di verificarlo senza math.isnan


def test_sortino_ignores_upside_volatility():
    """Rendimenti con molta piu' variabilita' sull'upside che sul downside: lo
    Sharpe penalizza anche gli sbalzi positivi (volatilita' totale), il
    Sortino solo la deviazione dei rendimenti negativi (piu' piccola qui) —
    deve quindi risultare piu' alto."""
    mixed = pd.Series([0.09, -0.01, 0.02, -0.012, 0.12, -0.008, 0.03, -0.011])
    assert sortino_ratio(mixed) > sharpe(mixed)


def test_sortino_is_nan_with_no_downside_observations():
    monthly = pd.Series([0.01] * 12)  # mai un mese negativo
    result = sortino_ratio(monthly)
    assert result != result


def test_ulcer_index_zero_when_never_drawdown():
    monthly = pd.Series([0.01] * 12)
    assert ulcer_index(monthly) == 0.0


def test_ulcer_index_matches_known_drawdown_path():
    # NAV: 1.0 -> 1.2 -> 0.9 -> 1.1 (stesso percorso di test_max_drawdown_known_path).
    # Drawdown dal picco (1.2) in ciascun periodo: 0%, -25%, -8.33% (a t=2 il
    # NAV recupera a 1.1 ma il picco resta 1.2, quindi non e' tornato a 0%).
    monthly = pd.Series([0.20, -0.25, 0.2222222222])
    dd_t2_pct = (1.1 / 1.2 - 1) * 100  # NAV recupera a 1.1, il picco resta 1.2 -> -8.33%
    expected = (((0.0 ** 2) + (25.0 ** 2) + (dd_t2_pct ** 2)) / 3) ** 0.5
    assert abs(ulcer_index(monthly) - expected) < 1e-3
