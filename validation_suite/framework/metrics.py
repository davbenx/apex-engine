"""
metrics.py — metriche di performance standard (CAGR, Sharpe, Max Drawdown,
Calmar) su una serie di rendimenti PERIODICI qualsiasi. Estratte da
kelly_backtest.py (dove erano nate come funzioni private
`_cagr`/`_sharpe`/`_max_drawdown`, sempre e solo su rendimenti mensili)
perche' generiche — nessuna dipendenza da Kelly Stack — e riusate da script
indipendenti in validation_suite/comparative_studies/.

`periods_per_year` (default 12, mensile — comportamento IDENTICO
all'originale per ogni chiamante esistente) permette di usare le stesse
funzioni su rendimenti settimanali (52) o giornalieri (365, crypto 24/7 —
non 252 come le borse azionarie) senza reimplementarle: usarle su una serie
daily con il default 12 sarebbe un bug silenzioso (annualizzazione sbagliata
di un fattore ~5.5x sullo Sharpe), non un'approssimazione accettabile.
"""
from __future__ import annotations
import numpy as np
import pandas as pd


def cagr(returns: pd.Series, periods_per_year: int = 12) -> float:
    total_growth = float((1 + returns).prod())
    years = len(returns) / periods_per_year
    if years <= 0 or total_growth <= 0:
        return float("nan")
    return total_growth ** (1 / years) - 1


def sharpe(returns: pd.Series, rf_annual: float = 0.0, periods_per_year: int = 12) -> float:
    excess = returns - rf_annual / periods_per_year
    if excess.std(ddof=1) < 1e-12:
        return 0.0
    return float(excess.mean() / excess.std(ddof=1) * np.sqrt(periods_per_year))


def max_drawdown(returns: pd.Series) -> float:
    nav = (1 + returns).cumprod()
    peak = nav.cummax()
    dd = nav / peak - 1
    return float(dd.min())


def calmar(returns: pd.Series, periods_per_year: int = 12) -> float:
    """CAGR / |MaxDD|. NaN se il drawdown e' zero (serie senza mai una perdita) —
    evita una ZeroDivisionError silenziosa nei molti punti del progetto che
    finora calcolavano questo rapporto inline in modo incoerente."""
    dd = max_drawdown(returns)
    if abs(dd) < 1e-12:
        return float("nan")
    return cagr(returns, periods_per_year=periods_per_year) / abs(dd)


def sortino_ratio(returns: pd.Series, rf_annual: float = 0.0, periods_per_year: int = 12) -> float:
    """Come sharpe() ma il denominatore usa solo la deviazione standard dei
    rendimenti SOTTO la soglia (downside deviation), non la volatilita' totale —
    non penalizza l'upside come fa lo Sharpe. NaN se meno di 2 osservazioni
    negative (deviazione standard non definita)."""
    excess = returns - rf_annual / periods_per_year
    downside = excess[excess < 0]
    if len(downside) < 2 or downside.std(ddof=1) < 1e-12:
        return float("nan")
    return float(excess.mean() / downside.std(ddof=1) * np.sqrt(periods_per_year))


def ulcer_index(returns: pd.Series) -> float:
    """Radice quadrata della media dei drawdown percentuali al quadrato —
    penalizza profondita' E durata dei drawdown nel tempo, non solo il picco
    peggiore come max_drawdown()."""
    nav = (1 + returns).cumprod()
    dd_pct = (nav / nav.cummax() - 1.0) * 100.0
    return float(np.sqrt((dd_pct ** 2).mean()))
