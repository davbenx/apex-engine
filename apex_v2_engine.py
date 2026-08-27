"""
apex_v2_engine.py — Motore Apex v2: timing multi-asset (isteresi + vol-targeting) +
basket azionario a bassa volatilita'. Vedi APEX_V2_SPEC.md per la specifica completa
e la giustificazione di ogni parametro.

Modulo isolato apposta: non tocca file su disco, riceve dati e stato in input,
restituisce risultati in output. Testabile senza il resto di backend.py.
"""

from __future__ import annotations
import datetime
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

# --- Parametri (vedi APEX_V2_SPEC.md per la giustificazione di ciascuno) ---
V2_CLASS_TICKER = {"Equities": "SPY", "Bonds": "IEF", "Gold": "GLD", "Crypto": "BTC-USD"}
V2_MA_WEEKS = 40
V2_HYSTERESIS = 0.02
V2_VOL_TARGET = 0.13
V2_VOL_WINDOW = 12
V2_EQUITY_TOP_N = 15
V2_EQUITY_VOL_LOOKBACK = 26


def _weekly_close(df: pd.DataFrame) -> pd.Series:
    """Chiusura settimanale (venerdi'), coerente con la convenzione usata altrove nel progetto."""
    if df is None or df.empty:
        return pd.Series(dtype=float)
    return df["Close"].resample("W-FRI").last().dropna()


def _realized_vol(weekly_close: pd.Series, window: int) -> Optional[float]:
    if len(weekly_close) < window + 1:
        return None
    r = weekly_close.pct_change().dropna().iloc[-window:]
    v = float(r.std() * np.sqrt(52))
    return v if v > 1e-6 else None


def compute_v2_macro_signal(
    b_data: Dict[str, pd.DataFrame],
    prev_hysteresis_state: Optional[Dict[str, bool]] = None,
) -> Tuple[Dict[str, float], Dict[str, bool], Dict[str, dict]]:
    """
    Calcola i pesi target per le 4 classi + cash (§2-3 di APEX_V2_SPEC.md).

    Ritorna: (allocations_pct 0-100 per classe + Cash, nuovo stato isteresi, debug per classe)
    """
    state = dict(prev_hysteresis_state) if prev_hysteresis_state else {}
    base_weight = {}
    debug = {}

    for cls, ticker in V2_CLASS_TICKER.items():
        df = b_data.get(ticker)
        wc = _weekly_close(df)
        if len(wc) < V2_MA_WEEKS:
            base_weight[cls] = 0.0
            debug[cls] = {"note": "dati insufficienti"}
            continue

        ma = wc.rolling(V2_MA_WEEKS, min_periods=V2_MA_WEEKS).mean()
        price = float(wc.iloc[-1])
        ma_val = float(ma.iloc[-1])
        dist = (price / ma_val - 1.0) if ma_val > 0 else 0.0

        was_active = bool(state.get(cls, False))
        if was_active:
            is_active = dist > -V2_HYSTERESIS
        else:
            is_active = dist > V2_HYSTERESIS
        state[cls] = is_active

        base_weight[cls] = 0.25 if is_active else 0.0
        debug[cls] = {"price": price, "ma40w": ma_val, "distanza_pct": round(dist * 100, 2), "attivo": is_active}

    vols = {}
    for cls, ticker in V2_CLASS_TICKER.items():
        wc = _weekly_close(b_data.get(ticker))
        v = _realized_vol(wc, V2_VOL_WINDOW)
        if v is not None:
            vols[cls] = v
        debug.setdefault(cls, {})["vol_12w_ann_pct"] = round(v * 100, 2) if v is not None else None

    port_vol = sum(base_weight.get(cls, 0.0) * vols[cls] for cls in V2_CLASS_TICKER if cls in vols)
    scale = min(1.0, V2_VOL_TARGET / port_vol) if port_vol > 1e-6 else 1.0

    allocations = {}
    for cls in V2_CLASS_TICKER:
        allocations[cls] = round(base_weight.get(cls, 0.0) * scale * 100.0, 2)
    allocations["Cash"] = round(100.0 - sum(allocations.values()), 2)

    debug["_vol_target"] = {"vol_portafoglio_stimata_pct": round(port_vol * 100, 2), "fattore_scala": round(scale, 3)}
    return allocations, state, debug


def select_low_vol_basket(
    eq_data: Dict[str, pd.DataFrame],
    top_n: int = V2_EQUITY_TOP_N,
    lookback_weeks: int = V2_EQUITY_VOL_LOOKBACK,
) -> List[dict]:
    """
    Seleziona i `top_n` titoli a volatilita' realizzata piu' bassa (§4 di APEX_V2_SPEC.md).
    NON e' selezione per generare alpha (l'audit ha dimostrato che il momentum non ne ha
    su questo universo) — e' solo un modo pratico e liquido di ottenere beta azionario
    con carattere fiscale "redditi diversi".
    """
    scored = []
    for sym, df in eq_data.items():
        wc = _weekly_close(df)
        v = _realized_vol(wc, lookback_weeks)
        if v is not None and len(wc) > 0:
            scored.append((sym, v, float(wc.iloc[-1])))

    scored.sort(key=lambda t: t[1])  # bassa volatilita' prima
    top = scored[:top_n]
    return [
        {"Ticker": sym, "Prezzo ($)": round(price, 2), "Volatilita' Ann. (%)": round(vol * 100, 2), "Stop Loss ($)": 0.0}
        for sym, vol, price in top
    ]


def is_quarter_end_month(dt: Optional[datetime.datetime] = None) -> bool:
    if dt is None:
        dt = datetime.datetime.now()
    return dt.month in (3, 6, 9, 12)
