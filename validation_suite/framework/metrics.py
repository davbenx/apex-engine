"""
metrics.py — metriche di performance standard (CAGR, Sharpe, Max Drawdown,
Calmar) su serie di rendimenti MENSILI. Estratte da kelly_backtest.py
(dove erano nate come funzioni private `_cagr`/`_sharpe`/`_max_drawdown`)
perche' generiche — nessuna dipendenza da Kelly Stack — e riusate da tre
script indipendenti in validation_suite/comparative_studies/. Nessuna
logica cambiata nello spostamento: solo promosse da private a pubbliche.
"""
from __future__ import annotations
import numpy as np
import pandas as pd


def cagr(monthly_returns: pd.Series) -> float:
    total_growth = float((1 + monthly_returns).prod())
    years = len(monthly_returns) / 12
    if years <= 0 or total_growth <= 0:
        return float("nan")
    return total_growth ** (1 / years) - 1


def sharpe(monthly_returns: pd.Series, rf_annual: float = 0.0) -> float:
    excess = monthly_returns - rf_annual / 12
    if excess.std(ddof=1) < 1e-12:
        return 0.0
    return float(excess.mean() / excess.std(ddof=1) * np.sqrt(12))


def max_drawdown(monthly_returns: pd.Series) -> float:
    nav = (1 + monthly_returns).cumprod()
    peak = nav.cummax()
    dd = nav / peak - 1
    return float(dd.min())


def calmar(monthly_returns: pd.Series) -> float:
    """CAGR / |MaxDD|. NaN se il drawdown e' zero (serie senza mai una perdita) —
    evita una ZeroDivisionError silenziosa nei molti punti del progetto che
    finora calcolavano questo rapporto inline in modo incoerente."""
    dd = max_drawdown(monthly_returns)
    if abs(dd) < 1e-12:
        return float("nan")
    return cagr(monthly_returns) / abs(dd)
