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
V2_SHORT_MA_WEEKS = 20  # conferma multi-timeframe — vedi APEX_V2_SPEC.md §8.9
V2_HYSTERESIS_K = 0.5   # banda adattiva = k * vol settimanale dell'asset, non piu' fissa al 2% per tutti — vedi §8.9
V2_HYSTERESIS_MIN = 0.005
V2_HYSTERESIS_MAX = 0.15
V2_VOL_TARGET = 0.13  # CANONICAL FROZEN (APEX v2.1-FROZEN): scelta conservativa su ampio plateau,
                      # MaxDD contenuto (8.8% OOS), benchmark ufficiale di produzione.
V2_VOL_WINDOW = 12
V2_EQUITY_TOP_N = 15
V2_EQUITY_VOL_LOOKBACK = 26
V2_EQUITY_BUFFER_RANK = 20  # vedi APEX_V2_SPEC.md §8.3: valore corretto dopo bug nel calendario del backtest (era 100)


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

    Due raffinamenti aggiunti dopo test dedicati (§8.9): banda di isteresi
    adattiva alla volatilita' di ciascun asset (invece di un 2% fisso uguale
    per SPY/IEF/GLD/BTC-USD, che ha volatilita' molto diverse), e conferma
    multi-timeframe (richiede accordo tra MA 40 settimane e MA 20 settimane,
    non solo la MA lunga).

    base_weight/V2_VOL_TARGET alzati a 0.50/0.22 (Percorso B, §8.25/§10.13):
    piu' CAGR/Calmar in cambio di un MaxDD piu' alto, confermato walk-forward
    su un plateau, non un punto isolato. Con questi valori la somma dei pesi
    non e' piu' garantita <=100% per costruzione algebrica come lo era con
    0.25/4 classi — da qui il limite esplicito di rinormalizzazione prima del
    return (vedi commento inline), che rende "mai a leva" un vincolo
    strutturale per qualunque valore di base_weight/vol-target.

    Ritorna: (allocations_pct 0-100 per classe + Cash, nuovo stato isteresi, debug per classe)
    """
    state = dict(prev_hysteresis_state) if prev_hysteresis_state else {}
    base_weight = {}
    debug = {}
    vols = {}

    for cls, ticker in V2_CLASS_TICKER.items():
        wc = _weekly_close(b_data.get(ticker))
        v = _realized_vol(wc, V2_VOL_WINDOW)
        if v is not None:
            vols[cls] = v

    for cls, ticker in V2_CLASS_TICKER.items():
        df = b_data.get(ticker)
        wc = _weekly_close(df)
        if len(wc) < V2_MA_WEEKS:
            base_weight[cls] = 0.0
            debug[cls] = {"note": "dati insufficienti"}
            continue

        ma_long = wc.rolling(V2_MA_WEEKS, min_periods=V2_MA_WEEKS).mean()
        ma_short = wc.rolling(V2_SHORT_MA_WEEKS, min_periods=V2_SHORT_MA_WEEKS).mean()
        price = float(wc.iloc[-1])
        ma_long_val = float(ma_long.iloc[-1])
        ma_short_val = float(ma_short.iloc[-1]) if not np.isnan(ma_short.iloc[-1]) else ma_long_val
        dist = (price / ma_long_val - 1.0) if ma_long_val > 0 else 0.0

        wk_vol = (vols[cls] / float(np.sqrt(52))) if cls in vols else 0.02
        band = float(max(V2_HYSTERESIS_MIN, min(V2_HYSTERESIS_MAX, V2_HYSTERESIS_K * wk_vol)))

        was_active = bool(state.get(cls, False))
        trend_long_on = (dist > -band) if was_active else (dist > band)
        trend_short_on = price > ma_short_val if ma_short_val > 0 else False
        is_active = trend_long_on and trend_short_on
        state[cls] = trend_long_on  # lo stato di isteresi segue solo il trend lungo; il breve e' un filtro extra

        base_weight[cls] = 0.50 if is_active else 0.0  # alzato da 0.25 — vedi §8.25/§10.13 (Percorso B)
        debug[cls] = {
            "price": price, "ma40w": ma_long_val, "ma20w": ma_short_val,
            "distanza_pct": round(dist * 100, 2), "banda_isteresi_pct": round(band * 100, 2), "attivo": is_active,
        }

    for cls in V2_CLASS_TICKER:
        debug.setdefault(cls, {})["vol_12w_ann_pct"] = round(vols[cls] * 100, 2) if cls in vols else None

    port_vol = sum(base_weight.get(cls, 0.0) * vols[cls] for cls in V2_CLASS_TICKER if cls in vols)
    scale = min(1.0, V2_VOL_TARGET / port_vol) if port_vol > 1e-6 else 1.0

    raw_weights = {cls: base_weight.get(cls, 0.0) * scale for cls in V2_CLASS_TICKER}
    # Limite esplicito di non-leva (vedi APEX_V2_SPEC.md §8.17/§8.20): con base_weight=0.25
    # (4 classi) la somma non puo' mai superare 100% per costruzione algebrica (25%x4=100%
    # esatto). Con base_weight=0.50 (§8.25/§10.13, Percorso B) questa garanzia sparisce —
    # con piu' classi attive e volatilita' realizzata moderata, scale puo' non ridurre
    # abbastanza da tenere la somma sotto 100%, introducendo leva non dichiarata (lo stesso
    # bug trovato e confermato negli script di ricerca prima di questa adozione). Questa
    # rinormalizzazione proporzionale rende il vincolo "mai a leva" strutturale per
    # qualunque valore di base_weight/vol-target, non solo per la combinazione 25%/13%.
    total_raw = sum(raw_weights.values())
    if total_raw > 1.0:
        raw_weights = {cls: w / total_raw for cls, w in raw_weights.items()}

    allocations = {}
    for cls in V2_CLASS_TICKER:
        allocations[cls] = round(raw_weights.get(cls, 0.0) * 100.0, 2)
    allocations["Cash"] = round(100.0 - sum(allocations.values()), 2)

    debug["_vol_target"] = {"vol_portafoglio_stimata_pct": round(port_vol * 100, 2), "fattore_scala": round(scale, 3)}
    return allocations, state, debug


V2_MAX_PER_SECTOR = 2  # vedi APEX_V2_SPEC.md §8.7: protegge l'alpha nei regimi sfavorevoli al settore concentrato


def select_low_vol_basket(
    eq_data: Dict[str, pd.DataFrame],
    top_n: int = V2_EQUITY_TOP_N,
    lookback_weeks: int = V2_EQUITY_VOL_LOOKBACK,
    prev_tickers: Optional[set] = None,
    buffer_rank: int = V2_EQUITY_BUFFER_RANK,
    sector_of: Optional[Dict[str, str]] = None,
    max_per_sector: int = V2_MAX_PER_SECTOR,
) -> List[dict]:
    """
    Seleziona i `top_n` titoli a volatilita' realizzata piu' bassa (§4 di APEX_V2_SPEC.md).
    NON e' selezione per generare alpha (l'audit ha dimostrato che il momentum non ne ha
    su questo universo) — e' solo un modo pratico e liquido di ottenere beta azionario
    con carattere fiscale "redditi diversi".

    Buffer di isteresi sulla rank (§8.3): un titolo gia' detenuto (`prev_tickers`) resta
    in basket se la sua posizione in classifica resta entro `buffer_rank`, anche se e'
    scesa fuori dal top-`top_n` esatto — senza buffer il rinnovo trimestrale era
    comunque sostanzioso (~60% dei nomi sostituiti ogni trimestre, rumore di stima
    della volatilita' vicino alla soglia).

    Vincolo di concentrazione settoriale (§8.7): la selezione per bassa volatilita', da
    sola, concentra sistematicamente in 1-2 settori difensivi (Utilities/Real Estate) —
    fino all'80% del basket in un solo settore in alcuni trimestri storici, un rischio
    confermato con dati reali (yfinance) e non solo teorico. `max_per_sector` limita
    quanti titoli dello stesso settore possono coesistere nel basket; se `sector_of` non
    e' disponibile per un titolo, non viene vincolato (fail-open, non blocca la
    selezione per un problema di dati sui settori). I NUOVI ingressi restano comunque
    scelti solo tra i migliori in assoluto — buffer e vincolo settoriale allentano solo
    la permanenza/composizione, mai l'ammissione di un titolo scarso.
    """
    scored = []
    for sym, df in eq_data.items():
        wc = _weekly_close(df)
        v = _realized_vol(wc, lookback_weeks)
        if v is not None and len(wc) > 0:
            scored.append((sym, v, float(wc.iloc[-1])))

    scored.sort(key=lambda t: t[1])  # bassa volatilita' prima
    info_by_sym = {sym: (vol, price) for sym, vol, price in scored}
    ranked_syms = [sym for sym, _, _ in scored]
    rank_of = {sym: i for i, sym in enumerate(ranked_syms)}
    sector_of = sector_of or {}

    sector_count: Dict[str, int] = {}
    result: List[str] = []

    def sector_ok(sym: str) -> bool:
        s = sector_of.get(sym)
        if s is None:
            return True
        return sector_count.get(s, 0) < max_per_sector

    def add(sym: str):
        result.append(sym)
        s = sector_of.get(sym)
        if s is not None:
            sector_count[s] = sector_count.get(s, 0) + 1

    prev_tickers = prev_tickers or set()
    incumbents_sorted = sorted(
        [s for s in prev_tickers if rank_of.get(s, 10**9) < buffer_rank],
        key=lambda s: rank_of.get(s, 10**9),
    )
    for sym in incumbents_sorted:
        if len(result) >= top_n:
            break
        if sector_ok(sym):
            add(sym)

    for sym in ranked_syms:
        if len(result) >= top_n:
            break
        if sym in result:
            continue
        if sector_ok(sym):
            add(sym)

    return [
        {"Ticker": sym, "Prezzo ($)": round(info_by_sym[sym][1], 2),
         "Volatilita' Ann. (%)": round(info_by_sym[sym][0] * 100, 2), "Stop Loss ($)": 0.0}
        for sym in result[:top_n]
    ]


def is_quarter_end_month(dt: Optional[datetime.datetime] = None) -> bool:
    if dt is None:
        dt = datetime.datetime.now()
    return dt.month in (3, 6, 9, 12)
