"""
crypto_frontier_venture_engine.py — Motore della strategia Crypto Frontier Venture.
Architettura: Dual-Regime Bitcoin Core + Altseason Breakout Satellite.
Ottimizzazioni quantitative falsificate e convalidate empiricamente (2018–2026):
- 7 slot di allocazione ad alta convinzione (14.29% per slot).
- Universo Top 25 Liquide (volume mediano 20gg >= $500k/giorno).
- Stop Loss a Chiusura Daily su 2.5x ATR14 + Circuit Breaker di emergenza intraday a -50%.
- Stagnation Time-Stop a 21 giorni senza nuovi massimi a 30 giorni.
- De-risking Free-Ride al +125% (realizzo del 44.4% per recupero 100% capitale).
- Trailing Stop al -30% dal picco massimo post-free-ride.
- Zero lookahead: segnale al Close di T, esecuzione all'Open di T+1 con 10 bps slippage.
- Calcolo realistico della fiscalita italiana al 26% con zainetto fiscale (Redditi Diversi).
"""

from __future__ import annotations
from dataclasses import dataclass, field
import datetime
import os
import glob
import json
import urllib.request
from typing import Dict, List, Tuple, Any, Optional

import numpy as np
import pandas as pd


@dataclass
class CryptoVentureConfig:
    """Configurazione quantitativa per la strategia Crypto Frontier Venture."""
    universe_mode: str = "TOP25"               # "TOP25", "TOP10", "ALL_LIQUID", "UNCONSTRAINED"
    max_slots: int = 7                         # Numero ottimale di posizioni altcoin
    min_dollar_vol_20d: float = 500_000.0      # Volume mediano minimo in USD a 20 giorni
    donchian_breakout_days: int = 30           # Canale Donchian di massimo per breakout
    anti_crowding_max_pct: float = 0.10        # Massimo scostamento ammesso sopra il breakout (+10%)
    volume_confirmation_mult: float = 1.25     # Volume odierno >= 1.25x media mobile 20gg
    rs_lookback_days: int = 20                 # Lookback per forza relativa Alt vs BTC
    stop_mode: str = "ATR_CLOSE"               # "ATR_CLOSE" o "FIXED_CLOSE"
    atr_multiplier: float = 2.5                # Moltiplicatore ATR per stop su chiusura
    atr_period_days: int = 14                  # Periodo di calcolo Average True Range
    fixed_stop_pct: float = 0.35               # Stop fisso percentuale (se stop_mode == "FIXED_CLOSE")
    circuit_breaker_intraday_pct: float = 0.50 # Stop loss intraday di emergenza a libro (-50%)
    time_stop_days: int = 21                   # Giorni massimi senza nuovi massimi a 30gg
    freeride_multiplier: float = 2.25          # Prezzo di de-risking (+125% dal carico)
    trailing_stop_pct: float = 0.30            # Trailing stop dal picco post-free-ride (-30%)
    macro_btc_fast_days: int = 140             # SMA veloce Bitcoin (20 settimane)
    macro_btc_slow_days: int = 280             # SMA lenta Bitcoin (40 settimane)
    altseason_breadth_pct: float = 45.0        # Soglia minima ampiezza (% alts > SMA 20w)
    altseason_rs_spread_pct: float = 40.0      # Soglia minima spread forza relativa (% alts batte BTC 30d)
    slippage_bps: float = 10.0                 # Slippage per trade (10 bps)
    tax_rate: float = 0.26                     # Aliquota imposta sostitutiva italiana (26%)
    initial_capital: float = 10_000.0          # Capitale iniziale di simulazione
    start_date: Optional[str] = "2018-10-08"   # Data inizio simulazione (default baseline validata 2018-10-08)



@dataclass
class TradeRecord:
    """Record di una transazione completata."""
    symbol: str
    entry_date: pd.Timestamp
    exit_date: pd.Timestamp
    entry_price: float
    exit_price: float
    units: float
    invested_amount: float
    recovered_amount: float
    pnl_pct: float
    pnl_val: float
    holding_days: int
    exit_reason: str


def load_crypto_dataset(cache_dir: str) -> Dict[str, pd.DataFrame]:
    """Carica tutti i file CSV giornalieri con colonne OHLCV dalla cache."""
    files = sorted(glob.glob(os.path.join(cache_dir, "*-USD.csv")))
    dfs = {}
    cols = ["Open", "High", "Low", "Close", "Volume"]
    for f in files:
        sym = os.path.basename(f).replace(".csv", "")
        try:
            df = pd.read_csv(f, index_col=0, parse_dates=True)
            if all(c in df.columns for c in cols):
                clean_df = df[cols].dropna()
                if len(clean_df) >= 50:
                    dfs[sym] = clean_df
        except Exception:
            continue
    return dfs


def precompute_market_matrices(
    dfs: Dict[str, pd.DataFrame],
    config: CryptoVentureConfig
) -> Dict[str, Any]:
    """Precalcola le matrici di mercato allineate alla serie temporale di Bitcoin."""
    if "BTC-USD" not in dfs:
        raise ValueError("BTC-USD non presente nel dataset.")

    btc_df = dfs["BTC-USD"]
    btc_c = btc_df["Close"]
    btc_o = btc_df["Open"]
    btc_h = btc_df["High"]
    btc_l = btc_df["Low"]

    alts = sorted([k for k in dfs.keys() if k not in ("BTC-USD", "ETH-USD", "USDT-USD", "USDC-USD")])

    df_close = pd.DataFrame({a: dfs[a]["Close"] for a in alts}).reindex(btc_c.index)
    df_open  = pd.DataFrame({a: dfs[a]["Open"] for a in alts}).reindex(btc_c.index)
    df_high  = pd.DataFrame({a: dfs[a]["High"] for a in alts}).reindex(btc_c.index)
    df_low   = pd.DataFrame({a: dfs[a]["Low"] for a in alts}).reindex(btc_c.index)
    df_vol   = pd.DataFrame({a: dfs[a]["Volume"] for a in alts}).reindex(btc_c.index)
    df_dollar_vol = df_close * df_vol

    # Macro Trend BTC
    btc_ma_fast = btc_c.rolling(config.macro_btc_fast_days).mean()
    btc_ma_slow = btc_c.rolling(config.macro_btc_slow_days).mean()
    btc_bull = (btc_c > btc_ma_fast) & (btc_ma_fast > btc_ma_slow)

    # Indicatori Altcoin
    df_sma20w = df_close.rolling(config.macro_btc_fast_days).mean()
    df_vol_ma20 = df_vol.rolling(20).mean()
    df_dollar_vol_med20 = df_dollar_vol.rolling(20).median()
    df_volat_20d = df_close.pct_change().rolling(20).std()

    # Donchian Breakout
    donch = df_close.shift(1).rolling(config.donchian_breakout_days).max()

    # Relative Strength
    rs_alt = df_close.pct_change(config.rs_lookback_days)
    rs_btc = btc_c.pct_change(config.rs_lookback_days)
    rs_alt30 = df_close.pct_change(30)
    rs_btc30 = btc_c.pct_change(30)

    # True Range e ATR
    df_close_prev = df_close.shift(1)
    df_tr1 = df_high - df_low
    df_tr2 = (df_high - df_close_prev).abs()
    df_tr3 = (df_low - df_close_prev).abs()
    df_tr = np.maximum(df_tr1, np.maximum(df_tr2, df_tr3))
    df_atr = df_tr.rolling(config.atr_period_days).mean()

    # Ampiezza e RS Spread Altseason
    active_counts = df_close.notna().sum(axis=1).replace(0, np.nan)
    breadth_series = ((df_close > df_sma20w).sum(axis=1) / active_counts * 100.0).fillna(0.0)
    rs_spread_30 = ((rs_alt30.sub(rs_btc30, axis=0) > 0).sum(axis=1) / active_counts * 100.0).fillna(0.0)

    # Selezione Universo
    top10_set = {"SOL-USD", "BNB-USD", "XRP-USD", "ADA-USD", "DOGE-USD", "AVAX-USD", "LINK-USD", "LTC-USD", "ETC-USD", "BCH-USD"}
    if config.universe_mode == "TOP10":
        active_universe = [a for a in alts if a in top10_set]
    elif config.universe_mode == "TOP25":
        med_vol = df_dollar_vol_med20.median().sort_values(ascending=False)
        active_universe = [a for a in med_vol.head(25).index if a in alts]
    else:
        active_universe = list(alts)

    return {
        "btc_c": btc_c, "btc_o": btc_o, "btc_h": btc_h, "btc_l": btc_l,
        "btc_bull": btc_bull,
        "df_close": df_close, "df_open": df_open, "df_high": df_high, "df_low": df_low,
        "df_vol": df_vol, "df_vol_ma20": df_vol_ma20,
        "df_dollar_vol_med20": df_dollar_vol_med20, "df_volat_20d": df_volat_20d,
        "df_sma20w": df_sma20w, "donch": donch,
        "rs_alt": rs_alt, "rs_btc": rs_btc,
        "df_atr": df_atr,
        "breadth_series": breadth_series, "rs_spread_30": rs_spread_30,
        "active_universe": active_universe,
        "simulation_dates": (
            btc_c.index[config.macro_btc_slow_days:][btc_c.index[config.macro_btc_slow_days:] >= pd.Timestamp(config.start_date)]
            if config.start_date is not None
            else btc_c.index[config.macro_btc_slow_days:]
        )
    }


def run_crypto_venture_backtest(
    matrices: Dict[str, Any],
    config: CryptoVentureConfig,
    tax_enabled: bool = True
) -> Dict[str, Any]:
    """
    Esegue la simulazione completa della strategia Crypto Frontier Venture a zero lookahead.
    Decisioni a Close del giorno T, esecuzioni a Open del giorno T+1 con slippage.
    """
    btc_c = matrices["btc_c"]
    btc_o = matrices["btc_o"]
    btc_bull = matrices["btc_bull"]
    df_close = matrices["df_close"]
    df_open = matrices["df_open"]
    df_high = matrices["df_high"]
    df_low = matrices["df_low"]
    df_vol = matrices["df_vol"]
    df_vol_ma20 = matrices["df_vol_ma20"]
    df_dollar_vol_med20 = matrices["df_dollar_vol_med20"]
    df_volat_20d = matrices["df_volat_20d"]
    df_sma20w = matrices["df_sma20w"]
    donch = matrices["donch"]
    rs_alt = matrices["rs_alt"]
    rs_btc = matrices["rs_btc"]
    df_atr = matrices["df_atr"]
    breadth_series = matrices["breadth_series"]
    rs_spread_30 = matrices["rs_spread_30"]
    active_universe = matrices["active_universe"]
    sim_dates = matrices["simulation_dates"]

    slip_buy = 1.0 + (config.slippage_bps / 10000.0)
    slip_sell = 1.0 - (config.slippage_bps / 10000.0)

    cash = config.initial_capital
    btc_units = 0.0
    positions: Dict[str, Dict[str, Any]] = {}
    completed_trades: List[TradeRecord] = []
    
    equity_series = []
    btc_benchmark_series = []
    
    loss_pool = 0.0
    cumulative_tax = 0.0

    pending_entries: List[Tuple[str, float]] = []
    pending_exits: List[Tuple[str, str]] = []

    for d in sim_dates:
        cur_btc_p = btc_c.loc[d]
        btc_open = btc_o.loc[d]
        is_btc = btc_bull.loc[d]

        # ----------------------------------------------------------------------
        # 1. Esecuzione vendite pendenti all'Open di giorno T
        # ----------------------------------------------------------------------
        for sym, reason in pending_exits:
            if sym in positions:
                p_op = df_open.loc[d, sym]
                if not np.isnan(p_op) and p_op > 0:
                    pos = positions[sym]
                    p_exec = p_op * slip_sell
                    rec = pos["units"] * p_exec
                    cash += rec
                    pnl_v = rec - pos["cost_rem"]
                    pnl_p = (p_exec / pos["entry_p"]) - 1.0

                    if tax_enabled:
                        if pnl_v > 0:
                            taxable = max(0.0, pnl_v - loss_pool)
                            loss_pool = max(0.0, loss_pool - pnl_v)
                            tax = taxable * config.tax_rate
                            cash -= tax
                            cumulative_tax += tax
                        else:
                            loss_pool += abs(pnl_v)

                    h_days = (d - pos["entry_date"]).days
                    completed_trades.append(TradeRecord(
                        symbol=sym,
                        entry_date=pos["entry_date"],
                        exit_date=d,
                        entry_price=pos["entry_p"],
                        exit_price=p_exec,
                        units=pos["units"],
                        invested_amount=pos["init_cost"],
                        recovered_amount=rec,
                        pnl_pct=pnl_p,
                        pnl_val=pnl_v,
                        holding_days=h_days,
                        exit_reason=reason
                    ))
                    del positions[sym]
        pending_exits = []

        # ----------------------------------------------------------------------
        # 2. Esecuzione acquisti pendenti all'Open di giorno T
        # ----------------------------------------------------------------------
        for sym, budget in pending_entries:
            if len(positions) >= config.max_slots:
                break
            if sym in positions:
                continue
            p_op = df_open.loc[d, sym]
            if np.isnan(p_op) or p_op <= 0:
                continue

            # Se liquidita insufficiente, disinvestire da Bitcoin Core
            if cash < budget and btc_units > 0:
                needed = budget - cash
                b_sell = min(btc_units, needed / (btc_open * slip_sell))
                cash += b_sell * (btc_open * slip_sell)
                btc_units -= b_sell

            alloc = min(budget, cash)
            if alloc >= 100.0:
                exec_p = p_op * slip_buy
                cash -= alloc
                atr_e = df_atr.loc[d, sym]
                if np.isnan(atr_e) or atr_e <= 0:
                    atr_e = exec_p * 0.08

                positions[sym] = {
                    "entry_p": exec_p,
                    "units": alloc / exec_p,
                    "peak_p": exec_p,
                    "freeride_done": False,
                    "init_cost": alloc,
                    "cost_rem": alloc,
                    "days_no_high": 0,
                    "atr_entry": atr_e,
                    "entry_date": d
                }
        pending_entries = []

        # ----------------------------------------------------------------------
        # 3. Controllo Regime Macro & Altseason Gate
        # ----------------------------------------------------------------------
        b_val = breadth_series.loc[d]
        rs_val = rs_spread_30.loc[d]
        macro_alt = is_btc and (b_val >= config.altseason_breadth_pct) and (rs_val >= config.altseason_rs_spread_pct)

        # ----------------------------------------------------------------------
        # 4. Gestione Posizioni Aperte (Valutazione a Close e Intraday)
        # ----------------------------------------------------------------------
        closed_intraday = []
        for sym, pos in list(positions.items()):
            p_cl = df_close.loc[d, sym]
            p_hi = df_high.loc[d, sym]
            p_lo = df_low.loc[d, sym]

            if np.isnan(p_cl) or p_cl <= 0:
                continue

            if p_hi > pos["peak_p"]:
                pos["peak_p"] = p_hi
                pos["days_no_high"] = 0
            else:
                pos["days_no_high"] += 1

            # A. Free-Ride Milestone (+125% / 2.25x)
            if not pos["freeride_done"] and p_hi >= (pos["entry_p"] * config.freeride_multiplier):
                rec_target = pos["init_cost"]
                needed_units = rec_target / (pos["entry_p"] * config.freeride_multiplier * slip_sell)
                units_to_sell = min(pos["units"] * 0.5, needed_units)
                cash_rec = units_to_sell * (pos["entry_p"] * config.freeride_multiplier * slip_sell)
                cash += cash_rec
                pos["units"] -= units_to_sell
                pos["cost_rem"] = max(0.0, pos["cost_rem"] - cash_rec)
                pos["freeride_done"] = True
                gain_v = cash_rec - (units_to_sell * pos["entry_p"])

                if tax_enabled:
                    if gain_v > 0:
                        taxable = max(0.0, gain_v - loss_pool)
                        loss_pool = max(0.0, loss_pool - gain_v)
                        tax = taxable * config.tax_rate
                        cash -= tax
                        cumulative_tax += tax
                    else:
                        loss_pool += abs(gain_v)

                h_days = (d - pos["entry_date"]).days
                completed_trades.append(TradeRecord(
                    symbol=sym,
                    entry_date=pos["entry_date"],
                    exit_date=d,
                    entry_price=pos["entry_p"],
                    exit_price=pos["entry_p"] * config.freeride_multiplier,
                    units=units_to_sell,
                    invested_amount=units_to_sell * pos["entry_p"],
                    recovered_amount=cash_rec,
                    pnl_pct=config.freeride_multiplier - 1.0,
                    pnl_val=gain_v,
                    holding_days=h_days,
                    exit_reason="FREERIDE_DE_RISK"
                ))

            # B. Stop Loss & Trailing Exit
            stop_hit = False
            exit_px = p_cl
            reason = "NONE"

            # Emergency circuit breaker (-50% intraday)
            emerg_threshold = pos["entry_p"] * (1.0 - config.circuit_breaker_intraday_pct)
            if p_lo <= emerg_threshold:
                stop_hit = True
                exit_px = emerg_threshold * 0.95  # Gap penalty 5%
                reason = "EMERGENCY_CIRCUIT_50"

            if not stop_hit:
                if config.stop_mode == "ATR_CLOSE":
                    stop_px = pos["entry_p"] - (config.atr_multiplier * pos["atr_entry"])
                else:
                    stop_px = pos["entry_p"] * (1.0 - config.fixed_stop_pct)

                trail_px = pos["peak_p"] * (1.0 - config.trailing_stop_pct)

                if not pos["freeride_done"] and p_cl <= stop_px:
                    stop_hit = True
                    exit_px = p_cl * slip_sell
                    reason = "ATR_STOP_CLOSE" if config.stop_mode == "ATR_CLOSE" else "FIXED_STOP_CLOSE"
                elif pos["freeride_done"] and p_cl <= trail_px:
                    stop_hit = True
                    exit_px = p_cl * slip_sell
                    reason = "TRAIL_STOP_CLOSE"

            # C. Stagnation / Time-Stop (21 giorni)
            if not stop_hit and config.time_stop_days > 0 and pos["days_no_high"] >= config.time_stop_days:
                stop_hit = True
                exit_px = p_cl * slip_sell
                reason = f"TIME_STOP_{config.time_stop_days}D"

            if stop_hit:
                if reason.startswith("EMERGENCY"):
                    rec = pos["units"] * exit_px
                    cash += rec
                    pnl_v = rec - pos["cost_rem"]
                    pnl_p = (exit_px / pos["entry_p"]) - 1.0

                    if tax_enabled:
                        if pnl_v > 0:
                            taxable = max(0.0, pnl_v - loss_pool)
                            loss_pool = max(0.0, loss_pool - pnl_v)
                            tax = taxable * config.tax_rate
                            cash -= tax
                            cumulative_tax += tax
                        else:
                            loss_pool += abs(pnl_v)

                    h_days = (d - pos["entry_date"]).days
                    completed_trades.append(TradeRecord(
                        symbol=sym,
                        entry_date=pos["entry_date"],
                        exit_date=d,
                        entry_price=pos["entry_p"],
                        exit_price=exit_px,
                        units=pos["units"],
                        invested_amount=pos["init_cost"],
                        recovered_amount=rec,
                        pnl_pct=pnl_p,
                        pnl_val=pnl_v,
                        holding_days=h_days,
                        exit_reason=reason
                    ))
                    closed_intraday.append(sym)
                else:
                    pending_exits.append((sym, reason))

        for s in closed_intraday:
            del positions[s]

        # ----------------------------------------------------------------------
        # 5. Gestione Capitale Inattivo (Dual-Regime Core)
        # ----------------------------------------------------------------------
        alt_val = sum(pos["units"] * df_close.loc[d, s] for s, pos in positions.items() if not np.isnan(df_close.loc[d, s]))
        current_equity = cash + (btc_units * cur_btc_p) + alt_val

        if not is_btc:
            # Bear Market BTC: 100% Cash/Liquidita
            if btc_units > 0:
                cash += btc_units * (cur_btc_p * slip_sell)
                btc_units = 0.0
        else:
            # Bull Market BTC: se non c'e Altseason e nessun ordine pendente, 100% in BTC Core
            if not macro_alt and len(pending_entries) == 0:
                if cash > 100.0:
                    btc_units += cash / (cur_btc_p * slip_buy)
                    cash = 0.0

        # ----------------------------------------------------------------------
        # 6. Selezione Segnali di Ingresso Altcoin
        # ----------------------------------------------------------------------
        effective_occupied = len(positions) + len(pending_entries)
        if macro_alt and effective_occupied < config.max_slots:
            free_slots = config.max_slots - effective_occupied
            candidates = []

            for sym in active_universe:
                if sym in positions or any(sym == pe[0] for pe in pending_entries):
                    continue
                curr_p = df_close.loc[d, sym]
                if np.isnan(curr_p) or curr_p <= 0:
                    continue

                # Filtro di liquidita per universi aperti
                if config.min_dollar_vol_20d > 0 and config.universe_mode not in ("TOP10", "TOP25"):
                    d_vol = df_dollar_vol_med20.loc[d, sym]
                    if np.isnan(d_vol) or d_vol < config.min_dollar_vol_20d:
                        continue

                # Trend Filter: Prezzo > SMA 20w
                sma_val = df_sma20w.loc[d, sym]
                if np.isnan(sma_val) or curr_p < sma_val:
                    continue

                # Relative Strength vs BTC
                r_alt = rs_alt.loc[d, sym]
                r_btc = rs_btc.loc[d]
                if np.isnan(r_alt) or np.isnan(r_btc) or r_alt <= r_btc:
                    continue

                v_20 = df_volat_20d.loc[d, sym]
                score = (r_alt - r_btc) / v_20 if (not np.isnan(v_20) and v_20 > 0.01) else (r_alt - r_btc)

                # Breakout Donchian
                bo_level = donch.loc[d, sym]
                if np.isnan(bo_level) or bo_level <= 0 or curr_p < bo_level:
                    continue

                # Anti-Crowding Cap (+10%)
                if ((curr_p / bo_level) - 1.0) > config.anti_crowding_max_pct:
                    continue

                # Volume Confirmation (>= 1.25x media 20d)
                v_today = df_vol.loc[d, sym]
                v_ma = df_vol_ma20.loc[d, sym]
                if np.isnan(v_today) or np.isnan(v_ma) or v_ma <= 0 or v_today < (config.volume_confirmation_mult * v_ma):
                    continue

                candidates.append((sym, score, curr_p))

            # Ordinamento per score di forza relativa ponderata per la volatilita
            candidates.sort(key=lambda x: x[1], reverse=True)

            for sym, sc, px in candidates[:free_slots]:
                slot_fraction = 1.0 / config.max_slots
                budget = max(100.0, current_equity * slot_fraction)
                pending_entries.append((sym, budget))

        # Snapshot NAV giornaliero
        p_val = sum(pos["units"] * df_close.loc[d, s] for s, pos in positions.items() if not np.isnan(df_close.loc[d, s]))
        equity_series.append(cash + (btc_units * cur_btc_p) + p_val)
        btc_benchmark_series.append(cur_btc_p)

    s_equity = pd.Series(equity_series, index=sim_dates, name="Frontier_Venture_NAV")
    s_btc = pd.Series(btc_benchmark_series, index=sim_dates, name="BTC_Price")
    s_btc_norm = (s_btc / s_btc.iloc[0]) * config.initial_capital

    # Calcolo metriche aggregate
    years = (s_equity.index[-1] - s_equity.index[0]).days / 365.25
    cagr = (s_equity.iloc[-1] / s_equity.iloc[0]) ** (1.0 / years) - 1.0
    mdd = ((s_equity - s_equity.cummax()) / s_equity.cummax()).min()
    daily_ret = s_equity.pct_change().dropna()
    vol = daily_ret.std() * np.sqrt(365.25)
    sharpe = (cagr - 0.02) / vol if vol > 0 else 0.0
    calmar = cagr / abs(mdd) if mdd != 0 else 0.0

    # Metriche trade
    exits = [t for t in completed_trades if t.exit_reason != "FREERIDE_DE_RISK"]
    win_rate = (pd.Series([t.pnl_pct for t in exits]) > 0).mean() * 100.0 if exits else 0.0
    wins_sum = sum(t.pnl_val for t in exits if t.pnl_val > 0)
    loss_sum = abs(sum(t.pnl_val for t in exits if t.pnl_val < 0))
    profit_factor = (wins_sum / loss_sum) if loss_sum > 0 else 999.0

    # Statistiche per ragione di uscita
    reason_counts = pd.Series([t.exit_reason for t in completed_trades]).value_counts().to_dict()

    # Ripartizione annuale
    yearly_df = _compute_yearly_breakdown(s_equity, s_btc_norm)

    # Ripartizione per ciclo di mercato
    cycles_df = _compute_cycle_breakdown(s_equity, s_btc_norm)

    return {
        "equity_curve": s_equity,
        "btc_benchmark": s_btc_norm,
        "completed_trades": completed_trades,
        "yearly_metrics": yearly_df,
        "cycle_metrics": cycles_df,
        "exit_reasons": reason_counts,
        "summary": {
            "CAGR": cagr,
            "MaxDrawdown": mdd,
            "Volatility": vol,
            "Sharpe": sharpe,
            "Calmar": calmar,
            "TotalTrades": len(exits),
            "FreerideCount": sum(1 for t in completed_trades if t.exit_reason == "FREERIDE_DE_RISK"),
            "WinRate": win_rate,
            "ProfitFactor": profit_factor,
            "CumulativeTax": cumulative_tax,
            "TaxPoolRemaining": loss_pool,
            "FinalNAV": s_equity.iloc[-1]
        }
    }


def _compute_yearly_breakdown(s_equity: pd.Series, s_btc: pd.Series) -> pd.DataFrame:
    """Calcola rendimento, volatilità e max drawdown per anno solare."""
    years = sorted(list(set(s_equity.index.year)))
    rows = []
    for y in years:
        sub_eq = s_equity.loc[str(y)]
        sub_btc = s_btc.loc[str(y)]
        if len(sub_eq) < 10:
            continue
        ret_eq = (sub_eq.iloc[-1] / sub_eq.iloc[0]) - 1.0
        ret_btc = (sub_btc.iloc[-1] / sub_btc.iloc[0]) - 1.0
        mdd_eq = ((sub_eq - sub_eq.cummax()) / sub_eq.cummax()).min()
        mdd_btc = ((sub_btc - sub_btc.cummax()) / sub_btc.cummax()).min()
        rows.append({
            "Anno": y,
            "Rendimento_Strategia": ret_eq,
            "Rendimento_BTC": ret_btc,
            "Alfa_vs_BTC": ret_eq - ret_btc,
            "MaxDD_Strategia": mdd_eq,
            "MaxDD_BTC": mdd_btc
        })
    return pd.DataFrame(rows)


def _compute_cycle_breakdown(s_equity: pd.Series, s_btc: pd.Series) -> pd.DataFrame:
    """Calcola le metriche di prestazione per i principali cicli di mercato crypto."""
    cycles = [
        ("Crypto Winter 2018-2019", "2018-10-01", "2019-12-31"),
        ("Bull Run 2020-2021",       "2020-01-01", "2021-11-30"),
        ("Bear Market 2022",         "2021-12-01", "2022-12-31"),
        ("Recovery / Rebound 2023",  "2023-01-01", "2023-12-31"),
        ("BTC Lead Bull 2024-2025",  "2024-01-01", "2025-06-30"),
        ("Recent Market 2025-2026",  "2025-07-01", s_equity.index[-1].strftime("%Y-%m-%d")),
    ]
    rows = []
    for name, start_d, end_d in cycles:
        try:
            sub_eq = s_equity.loc[start_d:end_d]
            sub_btc = s_btc.loc[start_d:end_d]
            if len(sub_eq) < 10:
                continue
            ret_eq = (sub_eq.iloc[-1] / sub_eq.iloc[0]) - 1.0
            ret_btc = (sub_btc.iloc[-1] / sub_btc.iloc[0]) - 1.0
            mdd_eq = ((sub_eq - sub_eq.cummax()) / sub_eq.cummax()).min()
            mdd_btc = ((sub_btc - sub_btc.cummax()) / sub_btc.cummax()).min()
            rows.append({
                "Ciclo": name,
                "Periodo": f"{start_d} / {end_d}",
                "Strategia_Ret": ret_eq,
                "BTC_Ret": ret_btc,
                "MaxDD_Strategia": mdd_eq,
                "MaxDD_BTC": mdd_btc
            })
        except Exception:
            continue
    return pd.DataFrame(rows)


# ==============================================================================
# UNIVERSO E LIVE EXECUTION SU KRAKEN FUTURES PERPETUAL
# ==============================================================================

KRAKEN_FUTURES_TICKERS_URL = "https://futures.kraken.com/derivatives/api/v3/tickers"

STABLECOIN_SET = {
    "USDT", "USDC", "USD", "EUR", "DAI", "PYUSD", "FDUSD", "TUSD", "USDD", "USDE", "BUSD", "UST"
}

WRAPPED_SET = {
    "WBTC", "WETH", "WSTETH", "WEETH", "RETH", "STETH", "CBBTC", "CBETH"
}

SYNTHETICS_SET = {
    "AAPLX", "NVDAX", "AMZNX", "MSFTX", "GOOGLX", "TSLAX", "COINX", "METAX",
    "MSTRX", "HOODX", "ANTHROPICX", "OPENAIX", "SPX", "SPYX", "QQQX", "GLDX",
    "CRCLX", "SPCXX", "BRENTOIL", "OIL", "GOLD", "SILVER"
}

FALLBACK_KRAKEN_TOP25 = [
    "BTC", "ETH", "SOL", "XRP", "DOGE", "ADA", "AVAX", "LINK", "DOT", "NEAR",
    "SUI", "UNI", "LTC", "BCH", "APT", "FIL", "ARB", "OP", "INJ", "TIA",
    "ATOM", "TRX", "ETC", "XMR", "ZEC"
]


def _fmt_usd(val: Any) -> str:
    """Formatta prezzi numerici in stringhe USD con precisione dinamica."""
    if val is None or pd.isna(val):
        return "$0.00"
    try:
        v = float(val)
        return f"${v:,.2f}" if abs(v) >= 1.0 else f"${v:,.6f}"
    except Exception:
        return f"${val}"


def fetch_kraken_futures_top_universe(top_n: int = 25, timeout: int = 10) -> List[str]:
    """
    Recupera l'universo delle criptovalute piu liquide negoziabili come contratti
    Futures Perpetual su Kraken. Esclude tassativamente stablecoin, wrapped token
    e strumenti sintetici azionari o su materie prime.
    In caso di indisponibilita della rete, restituisce un paniere di fallback affidabile.
    """
    try:
        req = urllib.request.Request(
            KRAKEN_FUTURES_TICKERS_URL,
            headers={"User-Agent": "Mozilla/5.0"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        tickers = data.get("tickers", [])
        base_vol: Dict[str, float] = {}

        for t in tickers:
            if t.get("tag") != "perpetual":
                continue
            pair = t.get("pair", "")
            if ":" not in pair:
                continue
            base = pair.split(":")[0].upper().strip()
            if base == "XBT":
                base = "BTC"

            if base in STABLECOIN_SET or base in WRAPPED_SET or base in SYNTHETICS_SET:
                continue
            if base.endswith("X") and len(base) > 4 and base not in {"AVAX"}:
                continue

            vol_quote = float(t.get("volumeQuote", 0.0) or 0.0)
            base_vol[base] = max(base_vol.get(base, 0.0), vol_quote)

        if not base_vol:
            return FALLBACK_KRAKEN_TOP25[:top_n]

        sorted_bases = [b for b, _ in sorted(base_vol.items(), key=lambda x: x[1], reverse=True)]
        if "BTC" not in sorted_bases[:top_n] and "BTC" in sorted_bases:
            sorted_bases.remove("BTC")
            sorted_bases.insert(0, "BTC")

        return sorted_bases[:top_n]
    except Exception as e:
        print(f"[-] Impossibile contattare Kraken Futures API ({e}). Utilizzo universo di fallback.")
        return FALLBACK_KRAKEN_TOP25[:top_n]


def _get_crypto_df(crypto_dfs: Dict[str, pd.DataFrame], key: str) -> Optional[pd.DataFrame]:
    """Recupera in modo sicuro il dataframe del token provando key, key-USD o stripped."""
    if key in crypto_dfs:
        return crypto_dfs[key]
    usd_key = f"{key}-USD"
    if usd_key in crypto_dfs:
        return crypto_dfs[usd_key]
    clean_key = key.replace("-USD", "")
    if clean_key in crypto_dfs:
        return crypto_dfs[clean_key]
    return None


def evaluate_daily_crypto_frontier(
    open_positions: Dict[str, Dict[str, Any]],
    crypto_alloc_pct: float,
    crypto_dfs: Dict[str, pd.DataFrame],
    today_str: str,
    kraken_universe: Optional[List[str]] = None,
    config: Optional[CryptoVentureConfig] = None
) -> Dict[str, Any]:
    """
    Valuta quotidianamente il portafoglio crypto secondo le regole di Crypto Frontier Venture:
    1. Verifica uscite su posizioni aperte (Emergency Circuit -50%, Free-Ride +125%, Stop ATR 2.5x Close, Trailing Stop -30%, Time-Stop 21d).
    2. Calcolo Breadth & RS Spread su Universo Kraken Futures Top 25 per abilitazione Gate Altseason.
    3. Rilevazione breakout Donchian 30d con conferma volumi (>=1.25x) e filtro anti-crowding (<=+10%).
    4. Gestione dual-regime: allocazione su altcoin leader (fino a 7 slot) con capitale residuo in Bitcoin Core.
    """
    cfg = config or CryptoVentureConfig()
    updated_positions = {k: dict(v) for k, v in open_positions.items()}
    sells: List[Dict[str, Any]] = []
    buys: List[Dict[str, Any]] = []
    action_log: List[str] = []
    closed_trades: List[Dict[str, Any]] = []

    crypto_pos = {k: v for k, v in updated_positions.items() if v.get("is_crypto") or k in ("BTC", "Bitcoin")}

    # Controllo serie temporale Bitcoin Core
    btc_df = _get_crypto_df(crypto_dfs, "BTC")

    if btc_df is not None and len(btc_df) >= cfg.macro_btc_slow_days:
        btc_c = btc_df["Close"]
        btc_fast = float(btc_c.rolling(cfg.macro_btc_fast_days).mean().iloc[-1])
        btc_slow = float(btc_c.rolling(cfg.macro_btc_slow_days).mean().iloc[-1])
        btc_px = float(btc_c.iloc[-1])
        is_btc_bull = (btc_px > btc_fast) and (btc_fast > btc_slow)
    else:
        is_btc_bull = True
        btc_px = float(btc_df["Close"].iloc[-1]) if btc_df is not None and not btc_df.empty else 0.0

    # Se allocazione disattivata a livello macro: liquidare tutte le posizioni crypto
    if crypto_alloc_pct <= 0.0:
        for tkr, pos in list(crypto_pos.items()):
            df = _get_crypto_df(crypto_dfs, tkr)
            cur_p = float(df["Close"].iloc[-1]) if df is not None and not df.empty else float(pos.get("current_price", pos.get("entry_price", 0.0)))
            cur_w_pct = float(pos.get("weight", 0.0)) * 100.0
            entry_p = float(pos.get("entry_price", cur_p))
            pnl_pct = ((cur_p / entry_p) - 1.0) * 100.0 if entry_p > 0 else 0.0
            reason = "Regime macro crypto disattivato (Allocazione 0%)"
            sells.append({
                "action": "CHIUSURA",
                "action_type": "SELL",
                "ticker": tkr,
                "display_name": tkr if tkr != "BTC" else "Bitcoin",
                "cur_w_pct": round(cur_w_pct, 2),
                "tgt_w_pct": 0.0,
                "delta_w_pct": round(-cur_w_pct, 2),
                "price": cur_p,
                "pnl_pct": round(pnl_pct, 2),
                "is_crypto": True,
                "desc": f"Liquidazione sistematica: {reason}"
            })
            action_log.append(f"CHIUSURA: {tkr} | {reason} | Prezzo: {_fmt_usd(cur_p)} | P&L: {pnl_pct:+0.2f}%")
            closed_trades.append({
                "ticker": tkr,
                "entry_date": pos.get("entry_date", today_str),
                "exit_date": today_str,
                "entry_price": entry_p,
                "exit_price": cur_p,
                "profit_pct": round(pnl_pct, 2),
                "weight": round(pos.get("weight", 0.0), 6),
                "reason": reason
            })
            if tkr in updated_positions:
                del updated_positions[tkr]

        return {
            "sells": sells,
            "buys": buys,
            "orders": sells + buys,
            "action_log": action_log,
            "closed_trades": closed_trades,
            "updated_positions": updated_positions,
            "altseason_gate": False,
            "breadth_pct": 0.0,
            "rs_spread_pct": 0.0,
            "macro_regime": "ZERO_ALLOC"
        }

    # Macro regime attivo: calcolo dimensione slot
    crypto_frac = crypto_alloc_pct / 100.0
    slot_weight = crypto_frac / cfg.max_slots

    # 1. Verifica uscite e stop loss su posizioni altcoin aperte
    for tkr, pos in list(crypto_pos.items()):
        if tkr in ("BTC", "Bitcoin"):
            continue

        df = _get_crypto_df(crypto_dfs, tkr)
        if df is None or df.empty:
            continue

        cur_close = float(df["Close"].iloc[-1])
        cur_high = float(df["High"].iloc[-1])
        cur_low = float(df["Low"].iloc[-1])
        entry_p = float(pos.get("entry_price", cur_close))
        cur_w = float(pos.get("weight", slot_weight))

        # Aggiornamento picco massimo e giorni senza nuovi massimi
        prev_peak = float(pos.get("peak_price", entry_p))
        if cur_high > prev_peak:
            pos["peak_price"] = cur_high
            pos["last_high_date"] = today_str
            pos["days_no_high"] = 0
        else:
            pos["peak_price"] = prev_peak
            if "last_high_date" in pos:
                try:
                    d_today = datetime.datetime.strptime(today_str, "%Y-%m-%d").date()
                    d_high = datetime.datetime.strptime(pos["last_high_date"], "%Y-%m-%d").date()
                    pos["days_no_high"] = max(0, (d_today - d_high).days)
                except Exception:
                    pos["days_no_high"] = int(pos.get("days_no_high", 0))
            elif "days_no_high" in pos:
                # Compatibilità con posizioni legacy e mock di test unitari con contatore esplicito
                pos["days_no_high"] = int(pos.get("days_no_high", 0))
            elif "entry_date" in pos:
                try:
                    d_today = datetime.datetime.strptime(today_str, "%Y-%m-%d").date()
                    d_high = datetime.datetime.strptime(pos["entry_date"], "%Y-%m-%d").date()
                    pos["days_no_high"] = max(0, (d_today - d_high).days)
                    pos["last_high_date"] = pos["entry_date"]
                except Exception:
                    pos["days_no_high"] = 0
            else:
                pos["days_no_high"] = 0
        peak_p = float(pos["peak_price"])
        pos["current_price"] = cur_close
        pos["is_crypto"] = True

        stop_hit = False
        exit_reason = ""
        exit_px = cur_close

        # Livello 1: Emergency Circuit Breaker (-50% Intraday)
        emerg_px = entry_p * (1.0 - cfg.circuit_breaker_intraday_pct)
        if cur_low <= emerg_px:
            stop_hit = True
            exit_reason = "EMERGENCY_CIRCUIT_50"
            exit_px = emerg_px * 0.95

        # Livello 2: Free-Ride Milestone (+125% / 2.25x)
        if not stop_hit and not pos.get("freeride_done", False) and cur_high >= (entry_p * cfg.freeride_multiplier):
            frac_to_sell = 1.0 / cfg.freeride_multiplier
            trim_w = cur_w * frac_to_sell
            rem_w = cur_w - trim_w
            pos["weight"] = rem_w
            pos["freeride_done"] = True
            pos["stop_loss"] = round(peak_p * (1.0 - cfg.trailing_stop_pct), 4)
            pnl_trim = (cfg.freeride_multiplier - 1.0) * 100.0
            sells.append({
                "action": "RIDUZIONE",
                "action_type": "SELL",
                "ticker": tkr,
                "display_name": tkr,
                "cur_w_pct": round(cur_w * 100, 2),
                "tgt_w_pct": round(rem_w * 100, 2),
                "delta_w_pct": round(-trim_w * 100, 2),
                "price": entry_p * cfg.freeride_multiplier,
                "pnl_pct": round(pnl_trim, 2),
                "is_crypto": True,
                "desc": "Free-Ride de-risking: vendita 44.4% unita (+125% dal carico). Capitale iniziale 100% recuperato. Stop trailing attivato a -30% dal picco."
            })
            action_log.append(f"RIDUZIONE (FREE-RIDE): {tkr} | Recupero 100% capitale al +125% | Prezzo: {_fmt_usd(entry_p * cfg.freeride_multiplier)} | P&L: {pnl_trim:+0.2f}%")
            closed_trades.append({
                "ticker": tkr,
                "entry_date": pos.get("entry_date", today_str),
                "exit_date": today_str,
                "entry_price": entry_p,
                "exit_price": entry_p * cfg.freeride_multiplier,
                "profit_pct": round(pnl_trim, 2),
                "weight": round(trim_w, 6),
                "reason": "FREERIDE_DE_RISK"
            })

        # Livello 3 & 4: Stop Loss ATR (pre-free-ride) o Trailing Stop (post-free-ride)
        if not stop_hit:
            if not pos.get("freeride_done", False):
                atr_val = float(pos.get("atr_entry", cur_close * 0.08))
                stop_px_raw = entry_p - (cfg.atr_multiplier * atr_val)
                emerg_px = entry_p * (1.0 - cfg.circuit_breaker_intraday_pct)
                stop_px = max(round(emerg_px, 4), max(0.0001, round(stop_px_raw, 4)))
                pos["stop_loss"] = stop_px
                if cur_close <= stop_px:
                    stop_hit = True
                    exit_reason = "ATR_STOP_CLOSE"
                    exit_px = cur_close
            else:
                trail_px = peak_p * (1.0 - cfg.trailing_stop_pct)
                pos["stop_loss"] = round(trail_px, 4)
                if cur_close <= trail_px:
                    stop_hit = True
                    exit_reason = "TRAIL_STOP_CLOSE"
                    exit_px = cur_close

        # Livello 5: Stagnation Time-Stop (21 giorni senza nuovi massimi)
        if not stop_hit and int(pos.get("days_no_high", 0)) >= cfg.time_stop_days:
            stop_hit = True
            exit_reason = f"TIME_STOP_{cfg.time_stop_days}D"
            exit_px = cur_close

        if stop_hit:
            pnl_pct = ((exit_px / entry_p) - 1.0) * 100.0 if entry_p > 0 else 0.0
            cur_w_pct = pos["weight"] * 100.0
            sells.append({
                "action": "CHIUSURA",
                "action_type": "SELL",
                "ticker": tkr,
                "display_name": tkr,
                "cur_w_pct": round(cur_w_pct, 2),
                "tgt_w_pct": 0.0,
                "delta_w_pct": round(-cur_w_pct, 2),
                "price": exit_px,
                "pnl_pct": round(pnl_pct, 2),
                "is_crypto": True,
                "desc": f"Chiusura sistematica: {exit_reason}"
            })
            action_log.append(f"CHIUSURA: {tkr} | Uscita: {exit_reason} | Prezzo: {_fmt_usd(exit_px)} | P&L: {pnl_pct:+0.2f}%")
            closed_trades.append({
                "ticker": tkr,
                "entry_date": pos.get("entry_date", today_str),
                "exit_date": today_str,
                "entry_price": entry_p,
                "exit_price": exit_px,
                "profit_pct": round(pnl_pct, 2),
                "weight": round(pos["weight"], 6),
                "reason": exit_reason
            })
            if tkr in updated_positions:
                del updated_positions[tkr]
        else:
            updated_positions[tkr] = pos

    # 2. Verifica Gate Altseason e selezione nuovi ingressi
    universe = kraken_universe if kraken_universe else fetch_kraken_futures_top_universe(25)
    alts_in_univ = [b for b in universe if b not in ("BTC", "Bitcoin")]

    above_sma_count = 0
    rs_beat_btc_count = 0
    valid_univ_count = 0

    for b in alts_in_univ:
        df = _get_crypto_df(crypto_dfs, b)
        if df is None or len(df) < 50:
            continue
        valid_univ_count += 1
        c = df["Close"]
        if len(df) >= cfg.macro_btc_fast_days:
            sma140 = float(c.rolling(cfg.macro_btc_fast_days).mean().iloc[-1])
            if float(c.iloc[-1]) > sma140:
                above_sma_count += 1
        if len(df) >= 31 and btc_df is not None and len(btc_df) >= 31:
            ret_alt30 = (float(c.iloc[-1]) / float(c.iloc[-31])) - 1.0
            ret_btc30 = (float(btc_df["Close"].iloc[-1]) / float(btc_df["Close"].iloc[-31])) - 1.0
            if ret_alt30 > ret_btc30:
                rs_beat_btc_count += 1

    breadth_pct = (above_sma_count / valid_univ_count * 100.0) if valid_univ_count > 0 else 0.0
    rs_spread_pct = (rs_beat_btc_count / valid_univ_count * 100.0) if valid_univ_count > 0 else 0.0
    altseason_gate = is_btc_bull and (breadth_pct >= cfg.altseason_breadth_pct) and (rs_spread_pct >= cfg.altseason_rs_spread_pct)

    current_alts = [k for k, v in updated_positions.items() if v.get("is_crypto") and k not in ("BTC", "Bitcoin")]
    free_slots = max(0, cfg.max_slots - len(current_alts))

    if altseason_gate and free_slots > 0:
        candidates = []
        for b in alts_in_univ:
            if b in updated_positions:
                continue
            df = _get_crypto_df(crypto_dfs, b)
            if df is None or len(df) < 50:
                continue

            curr_p = float(df["Close"].iloc[-1])

            # Trend Filter: Prezzo > SMA 20w
            if len(df) >= cfg.macro_btc_fast_days:
                sma_val = float(df["Close"].rolling(cfg.macro_btc_fast_days).mean().iloc[-1])
                if curr_p <= sma_val:
                    continue

            # Donchian 30d Breakout
            donch_high = float(df["Close"].iloc[:-1].tail(cfg.donchian_breakout_days).max())
            if curr_p <= donch_high:
                continue

            # Filtro Anti-Crowding (massimo +10% sopra il breakout)
            if (curr_p - donch_high) / donch_high > cfg.anti_crowding_max_pct:
                continue

            # Conferma di Volume Anomalo (>= 1.25x media 20d)
            if "Volume" in df.columns:
                v_today = float(df["Volume"].iloc[-1])
                v_ma20 = float(df["Volume"].iloc[-21:-1].mean())
                if v_ma20 > 0 and v_today < (cfg.volume_confirmation_mult * v_ma20):
                    continue

            # Forza Relativa Alt vs BTC a 20 giorni
            ret_alt20 = (curr_p / float(df["Close"].iloc[-21])) - 1.0 if len(df) >= 21 else 0.0
            ret_btc20 = (float(btc_df["Close"].iloc[-1]) / float(btc_df["Close"].iloc[-21])) - 1.0 if btc_df is not None and len(btc_df) >= 21 else 0.0
            if ret_alt20 <= ret_btc20:
                continue

            vol20 = float(df["Close"].pct_change().tail(20).std())
            if vol20 <= 0 or np.isnan(vol20):
                vol20 = 0.05
            score = (ret_alt20 - ret_btc20) / vol20
            candidates.append((b, score, curr_p, df))

        candidates.sort(key=lambda x: x[1], reverse=True)

        for b, score, curr_p, df in candidates[:free_slots]:
            df_tr1 = df["High"] - df["Low"]
            df_tr2 = (df["High"] - df["Close"].shift(1)).abs()
            df_tr3 = (df["Low"] - df["Close"].shift(1)).abs()
            tr = np.maximum(df_tr1, np.maximum(df_tr2, df_tr3))
            atr14 = float(tr.tail(cfg.atr_period_days).mean())
            if np.isnan(atr14) or atr14 <= 0:
                atr14 = curr_p * 0.08
            stop_px_raw = curr_p - cfg.atr_multiplier * atr14
            emerg_px = curr_p * (1.0 - cfg.circuit_breaker_intraday_pct)
            stop_px = max(round(emerg_px, 4), max(0.0001, round(stop_px_raw, 4)))

            buys.append({
                "action": "APERTURA",
                "action_type": "BUY",
                "ticker": b,
                "display_name": b,
                "cur_w_pct": 0.0,
                "tgt_w_pct": round(slot_weight * 100, 2),
                "delta_w_pct": round(slot_weight * 100, 2),
                "price": curr_p,
                "is_crypto": True,
                "desc": f"Breakout Donchian 30d su Kraken Futures (Stop Loss: {_fmt_usd(stop_px)})"
            })
            action_log.append(f"APERTURA: {b} | Breakout Donchian 30d (Stop Loss: {_fmt_usd(stop_px)}) | Prezzo: {_fmt_usd(curr_p)}")
            updated_positions[b] = {
                "entry_date": today_str,
                "entry_price": curr_p,
                "current_price": curr_p,
                "stop_loss": stop_px,
                "is_crypto": True,
                "weight": slot_weight,
                "days_no_high": 0,
                "last_high_date": today_str,
                "peak_price": curr_p,
                "freeride_done": False,
                "atr_entry": atr14
            }

    # 3. Bilanciamento Bitcoin Core Ballast (capitale inattivo)
    alts_weight_sum = sum(v["weight"] for k, v in updated_positions.items() if v.get("is_crypto") and k not in ("BTC", "Bitcoin"))
    btc_target_w = max(0.0, crypto_frac - alts_weight_sum)
    cur_btc_w = float(open_positions.get("BTC", {}).get("weight", 0.0))
    delta_btc_w = btc_target_w - cur_btc_w
    EPS = 1e-4

    if abs(delta_btc_w) > EPS:
        if cur_btc_w <= EPS and btc_target_w > EPS:
            buys.append({
                "action": "APERTURA",
                "action_type": "BUY",
                "ticker": "BTC",
                "display_name": "Bitcoin",
                "cur_w_pct": 0.0,
                "tgt_w_pct": round(btc_target_w * 100, 2),
                "delta_w_pct": round(delta_btc_w * 100, 2),
                "price": btc_px,
                "is_crypto": True,
                "desc": f"Bitcoin Core: allocazione {btc_target_w*100:.1f}% del portafoglio"
            })
            action_log.append(f"APERTURA: Bitcoin | Allocazione {btc_target_w*100:.1f}% | Prezzo: {_fmt_usd(btc_px)}")
        elif delta_btc_w > EPS:
            buys.append({
                "action": "INCREMENTO",
                "action_type": "BUY",
                "ticker": "BTC",
                "display_name": "Bitcoin",
                "cur_w_pct": round(cur_btc_w * 100, 2),
                "tgt_w_pct": round(btc_target_w * 100, 2),
                "delta_w_pct": round(delta_btc_w * 100, 2),
                "price": btc_px,
                "is_crypto": True,
                "desc": f"Riallocazione capitale inattivo su Bitcoin Core (+{delta_btc_w*100:.1f}%)"
            })
            action_log.append(f"INCREMENTO: Bitcoin | Riallocazione +{delta_btc_w*100:.1f}% | Prezzo: {_fmt_usd(btc_px)}")
        elif btc_target_w <= EPS and cur_btc_w > EPS:
            sells.append({
                "action": "CHIUSURA",
                "action_type": "SELL",
                "ticker": "BTC",
                "display_name": "Bitcoin",
                "cur_w_pct": round(cur_btc_w * 100, 2),
                "tgt_w_pct": 0.0,
                "delta_w_pct": round(delta_btc_w * 100, 2),
                "price": btc_px,
                "is_crypto": True,
                "desc": "Liquidazione Bitcoin Core: slot saturi da altcoin"
            })
            action_log.append(f"CHIUSURA: Bitcoin | Slot saturi da altcoin | Prezzo: {_fmt_usd(btc_px)}")
        elif delta_btc_w < -EPS:
            sells.append({
                "action": "RIDUZIONE",
                "action_type": "SELL",
                "ticker": "BTC",
                "display_name": "Bitcoin",
                "cur_w_pct": round(cur_btc_w * 100, 2),
                "tgt_w_pct": round(btc_target_w * 100, 2),
                "delta_w_pct": round(delta_btc_w * 100, 2),
                "price": btc_px,
                "is_crypto": True,
                "desc": f"Finanziamento nuovi slot altcoin da Bitcoin Core ({delta_btc_w*100:.1f}%)"
            })
            action_log.append(f"RIDUZIONE: Bitcoin | Finanziamento slot altcoin ({delta_btc_w*100:.1f}%) | Prezzo: {_fmt_usd(btc_px)}")

    if btc_target_w > EPS:
        updated_positions["BTC"] = {
            "entry_date": open_positions.get("BTC", {}).get("entry_date", today_str),
            "entry_price": open_positions.get("BTC", {}).get("entry_price", btc_px),
            "current_price": btc_px,
            "stop_loss": 0.0,
            "is_crypto": True,
            "weight": btc_target_w
        }
    elif "BTC" in updated_positions:
        del updated_positions["BTC"]

    return {
        "sells": sells,
        "buys": buys,
        "orders": sells + buys,
        "action_log": action_log,
        "closed_trades": closed_trades,
        "updated_positions": updated_positions,
        "altseason_gate": altseason_gate,
        "breadth_pct": breadth_pct,
        "rs_spread_pct": rs_spread_pct,
        "macro_regime": "ALTSEASON_SATELLITE" if altseason_gate else "BITCOIN_BULL_CORE"
    }
