#!/usr/bin/env python3
"""
apex_historical_trades_generator.py
Generatore del registro storico completo delle operazioni di Apex (1987-Oggi).

Genera il ledger trade-by-trade unificato:
1. 1987-2011: Macro Allocazione Sistematica (SPY/VFINX, IEF/VUSTX, GLD/GC=F)
2. 2012-2024: Point-In-Time Low-Beta Equity Basket (15 titoli trimestrali) + Macro (IEF, GLD, BTC)
3. 2018-2024: Crypto Frontier Venture (Altcoin Top 25 con regole Donchian, Freeride, Trailing)
4. 2024-Oggi: Portafoglio Tracciato Live (da portfolio.json)
"""

import sys
import os
import time
import json
from pathlib import Path
from typing import Dict, Any, List
import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "validation_suite" / "comparative_studies"))
sys.path.insert(0, str(REPO_ROOT / "validation_suite" / "framework"))

from apex_dashboard_stat_regeneration import (
    SPLICE_SPEC, spliced_price_index, spliced_return, _load_ext,
    BASKET_SELECTION_FROM_YEAR,
)
from apex_v2_engine import (
    compute_v2_macro_signal, select_low_beta_basket, V2_CLASS_TICKER
)
from apex_stocks_vs_etf_backtest import (
    load_pointintime_snapshots, eligible_universe_for_year, build_ohlc_like, load_weekly_sp500
)
from sector_cap_grid_test import SECTOR_MAP_FILE
from crypto_frontier_venture_engine import (
    CryptoVentureConfig,
    load_crypto_dataset,
    precompute_market_matrices,
    run_crypto_venture_backtest,
)

CRYPTO_REASON_MAP = {
    "FREERIDE_DE_RISK": "Freeride De-risk (recupero 100% capitale)",
    "TRAIL_STOP_CLOSE": "Trailing Stop (30% dal picco)",
    "ATR_STOP_CLOSE": "ATR Stop Loss (2.5x ATR)",
    "FIXED_STOP_CLOSE": "Stop Loss Fisso",
    "TIME_STOP_21D": "Time-Stop Stagnazione (21gg)",
    "EMERGENCY_CIRCUIT_50": "Circuit Breaker Emergenza (-50%)",
    "END_OF_DATA": "Chiusura fine simulazione",
}

def determine_asset_class(ticker: str, is_crypto: bool) -> str:
    tkr_u = str(ticker).upper()
    if is_crypto or tkr_u.endswith("-USD") or tkr_u in ("BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "DOGE", "AVAX", "LINK", "DOT", "NEAR", "MATIC", "POL", "LTC"):
        return "Cryptovalute"
    if tkr_u in ("IEF", "TLT", "BND", "VUSTX", "AGG"):
        return "Obbligazioni"
    if tkr_u in ("GLD", "IAU", "GC=F", "GC_F"):
        return "Oro"
    if tkr_u in ("SPY", "VFINX", "VOO", "IVV"):
        return "Azioni (Indice S&P 500)"
    return "Azioni (Low-Beta)"

def generate_full_historical_trades():
    print("[1/5] Caricamento universo point-in-time e serie storiche...")
    with open(SECTOR_MAP_FILE) as f:
        sector_of = json.load(f)

    snapshots = load_pointintime_snapshots()

    macro_prices = {ticker: spliced_price_index(*SPLICE_SPEC[ticker]) for ticker in V2_CLASS_TICKER.values()}
    btc_raw_series = _load_ext("BTC_USD_weekly.csv")
    common_index = macro_prices["SPY"].index.intersection(macro_prices["IEF"].index)
    weeks = list(common_index.sort_values())
    n = len(weeks)

    all_needed = set()
    for y, tkrs in snapshots.items():
        all_needed.update(t.replace(".", "-") for t in tkrs)

    stock_prices = {}
    for t in all_needed:
        try:
            stock_prices[t] = load_weekly_sp500(t)
        except Exception:
            pass
    print(f"      Caricati {len(stock_prices)} titoli S&P 500 point-in-time.")

    print("[2/5] Simulazione Era Macro (1987-2011) e Point-In-Time Low-Beta (2012-2024)...")
    MIN_HISTORY = 40
    closed_trades: List[Dict[str, Any]] = []
    open_sim_positions: Dict[str, Dict[str, Any]] = {}

    hysteresis_state = None
    locked_alloc = None
    current_basket: List[str] = []
    prev_basket_tickers = None

    t0 = time.time()

    for i, wk in enumerate(weeks):
        if i < MIN_HISTORY:
            continue

        wk_str = str(wk.date())

        # Calcolo segnale macro
        b_data = {}
        for c, ticker in V2_CLASS_TICKER.items():
            px = macro_prices[ticker]
            px_upto = px.loc[:wk]
            b_data[ticker] = build_ohlc_like(px_upto) if len(px_upto) > 0 else pd.DataFrame()

        alloc, hysteresis_state, _debug = compute_v2_macro_signal(b_data, prev_hysteresis_state=hysteresis_state)
        is_month_end = (i + 1 >= n) or (weeks[i + 1].month != wk.month)

        if locked_alloc is None:
            locked_alloc = alloc

        current_alloc = locked_alloc
        if is_month_end:
            locked_alloc = alloc

        macro_era = (wk.year < BASKET_SELECTION_FROM_YEAR)
        stock_selection_era = (wk.year >= BASKET_SELECTION_FROM_YEAR) and (wk < pd.Timestamp("2024-03-04"))
        live_era = (wk >= pd.Timestamp("2024-03-04"))

        if live_era:
            break

        # A. Macro Era (1987 - 2011)
        if macro_era:
            for cls_name, tkr_key, is_cr in [("Equities", "SPY", False), ("Bonds", "IEF", False), ("Gold", "GLD", False), ("Crypto", "BTC-USD", True)]:
                target_w = current_alloc.get(cls_name, 0.0) / 100.0
                tkr_display = "BTC" if tkr_key == "BTC-USD" else tkr_key
                cur_pos = open_sim_positions.get(tkr_display)
                if tkr_key not in macro_prices or wk not in macro_prices[tkr_key].index:
                    continue
                if is_cr and wk in btc_raw_series.index:
                    cur_p = float(btc_raw_series.loc[wk])
                else:
                    cur_p = float(macro_prices[tkr_key].loc[wk])

                if cur_pos is None and target_w > 0.001:
                    open_sim_positions[tkr_display] = {
                        "ticker": tkr_display,
                        "entry_date": wk_str,
                        "entry_price": cur_p,
                        "weight": target_w,
                        "is_crypto": is_cr,
                        "asset_class": determine_asset_class(tkr_display, is_cr),
                    }
                elif cur_pos is not None and target_w <= 0.001:
                    entry_p = cur_pos["entry_price"]
                    pnl = (cur_p / entry_p - 1.0) * 100.0 if entry_p > 0 else 0.0
                    reason_txt = "Disattivazione regime macro crypto" if is_cr else "Disattivazione regime macro"
                    closed_trades.append({
                        "ticker": tkr_display,
                        "entry_date": cur_pos["entry_date"],
                        "exit_date": wk_str,
                        "entry_price": round(entry_p, 4 if is_cr else 2),
                        "exit_price": round(cur_p, 4 if is_cr else 2),
                        "profit_pct": round(pnl, 2),
                        "weight": round(cur_pos["weight"], 6),
                        "reason": reason_txt,
                        "is_crypto": is_cr,
                        "asset_class": cur_pos["asset_class"],
                        "era": "1987-2011 (Macro Allocazione)",
                    })
                    del open_sim_positions[tkr_display]
                elif cur_pos is not None and target_w > 0.001 and is_month_end:
                    if target_w < cur_pos["weight"] - 0.005:
                        trim_w = cur_pos["weight"] - target_w
                        entry_p = cur_pos["entry_price"]
                        pnl = (cur_p / entry_p - 1.0) * 100.0 if entry_p > 0 else 0.0
                        closed_trades.append({
                            "ticker": tkr_display,
                            "entry_date": cur_pos["entry_date"],
                            "exit_date": wk_str,
                            "entry_price": round(entry_p, 4 if is_cr else 2),
                            "exit_price": round(cur_p, 4 if is_cr else 2),
                            "profit_pct": round(pnl, 2),
                            "weight": round(trim_w, 6),
                            "reason": "Ribilanciamento mensile (trim parziale)",
                            "is_crypto": is_cr,
                            "asset_class": cur_pos["asset_class"],
                            "era": "1987-2011 (Macro Allocazione)",
                        })
                        cur_pos["weight"] = target_w
                    elif target_w > cur_pos["weight"] + 0.005:
                        added_w = target_w - cur_pos["weight"]
                        cur_pos["entry_price"] = (cur_pos["entry_price"] * cur_pos["weight"] + cur_p * added_w) / target_w
                        cur_pos["weight"] = target_w

        # B. Point-In-Time Low-Beta Basket Era (2012 - 2024)
        elif stock_selection_era:
            # Asset macro: IEF, GLD, BTC
            for cls_name, tkr_key, is_cr in [("Bonds", "IEF", False), ("Gold", "GLD", False), ("Crypto", "BTC-USD", True)]:
                target_w = current_alloc.get(cls_name, 0.0) / 100.0
                tkr_display = "BTC" if tkr_key == "BTC-USD" else tkr_key
                cur_pos = open_sim_positions.get(tkr_display)
                if tkr_key not in macro_prices or wk not in macro_prices[tkr_key].index:
                    continue
                if is_cr and wk in btc_raw_series.index:
                    cur_p = float(btc_raw_series.loc[wk])
                else:
                    cur_p = float(macro_prices[tkr_key].loc[wk])

                if cur_pos is None and target_w > 0.001:
                    open_sim_positions[tkr_display] = {
                        "ticker": tkr_display,
                        "entry_date": wk_str,
                        "entry_price": cur_p,
                        "weight": target_w,
                        "is_crypto": is_cr,
                        "asset_class": determine_asset_class(tkr_display, is_cr),
                    }
                elif cur_pos is not None and target_w <= 0.001:
                    entry_p = cur_pos["entry_price"]
                    pnl = (cur_p / entry_p - 1.0) * 100.0 if entry_p > 0 else 0.0
                    reason_txt = "Disattivazione regime macro crypto" if is_cr else "Disattivazione regime macro"
                    closed_trades.append({
                        "ticker": tkr_display,
                        "entry_date": cur_pos["entry_date"],
                        "exit_date": wk_str,
                        "entry_price": round(entry_p, 4 if is_cr else 2),
                        "exit_price": round(cur_p, 4 if is_cr else 2),
                        "profit_pct": round(pnl, 2),
                        "weight": round(cur_pos["weight"], 6),
                        "reason": reason_txt,
                        "is_crypto": is_cr,
                        "asset_class": cur_pos["asset_class"],
                        "era": "2012-2024 (Point-In-Time)",
                    })
                    del open_sim_positions[tkr_display]
                elif cur_pos is not None and target_w > 0.001 and is_month_end:
                    if target_w < cur_pos["weight"] - 0.005:
                        trim_w = cur_pos["weight"] - target_w
                        entry_p = cur_pos["entry_price"]
                        pnl = (cur_p / entry_p - 1.0) * 100.0 if entry_p > 0 else 0.0
                        closed_trades.append({
                            "ticker": tkr_display,
                            "entry_date": cur_pos["entry_date"],
                            "exit_date": wk_str,
                            "entry_price": round(entry_p, 4 if is_cr else 2),
                            "exit_price": round(cur_p, 4 if is_cr else 2),
                            "profit_pct": round(pnl, 2),
                            "weight": round(trim_w, 6),
                            "reason": "Ribilanciamento mensile (trim parziale)",
                            "is_crypto": is_cr,
                            "asset_class": cur_pos["asset_class"],
                            "era": "2012-2024 (Point-In-Time)",
                        })
                        cur_pos["weight"] = target_w
                    elif target_w > cur_pos["weight"] + 0.005:
                        added_w = target_w - cur_pos["weight"]
                        cur_pos["entry_price"] = (cur_pos["entry_price"] * cur_pos["weight"] + cur_p * added_w) / target_w
                        cur_pos["weight"] = target_w

            # Gestione Titoli Low-Beta
            eq_alloc = current_alloc.get("Equities", 0.0) / 100.0

            def rebuild_basket():
                eligible = eligible_universe_for_year(snapshots, wk.year)
                eq_data = {t: build_ohlc_like(p.loc[:wk]) for t, p in stock_prices.items() if t in eligible}
                spy_data_upto = build_ohlc_like(macro_prices["SPY"].loc[:wk])
                basket = select_low_beta_basket(eq_data, spy_data_upto, prev_tickers=prev_basket_tickers, sector_of=sector_of)
                return [b["Ticker"] for b in basket]

            is_quarter_rebalance = is_month_end and (wk.month in (3, 6, 9, 12))

            if eq_alloc <= 0.001:
                for tkr in list(open_sim_positions.keys()):
                    pos = open_sim_positions[tkr]
                    if pos.get("asset_class") == "Azioni (Low-Beta)":
                        cur_p = float(stock_prices[tkr].loc[wk]) if tkr in stock_prices and wk in stock_prices[tkr].index else pos["entry_price"]
                        entry_p = pos["entry_price"]
                        pnl = (cur_p / entry_p - 1.0) * 100.0 if entry_p > 0 else 0.0
                        closed_trades.append({
                            "ticker": tkr,
                            "entry_date": pos["entry_date"],
                            "exit_date": wk_str,
                            "entry_price": round(entry_p, 2),
                            "exit_price": round(cur_p, 2),
                            "profit_pct": round(pnl, 2),
                            "weight": round(pos["weight"], 6),
                            "reason": "Disattivazione regime macro equity",
                            "is_crypto": False,
                            "asset_class": "Azioni (Low-Beta)",
                            "era": "2012-2024 (Point-In-Time)",
                        })
                        del open_sim_positions[tkr]
                current_basket = []
                prev_basket_tickers = None

            elif not current_basket:
                current_basket = rebuild_basket()
                prev_basket_tickers = set(current_basket)
                stock_w = eq_alloc / max(1, len(current_basket))
                for tkr in current_basket:
                    cur_p = float(stock_prices[tkr].loc[wk]) if tkr in stock_prices and wk in stock_prices[tkr].index else 100.0
                    open_sim_positions[tkr] = {
                        "ticker": tkr,
                        "entry_date": wk_str,
                        "entry_price": cur_p,
                        "weight": stock_w,
                        "is_crypto": False,
                        "asset_class": "Azioni (Low-Beta)",
                    }

            elif is_quarter_rebalance:
                new_basket = rebuild_basket()
                dropped_tickers = set(current_basket) - set(new_basket)
                added_tickers = set(new_basket) - set(current_basket)
                stock_w = eq_alloc / max(1, len(new_basket))

                for tkr in dropped_tickers:
                    if tkr in open_sim_positions:
                        pos = open_sim_positions[tkr]
                        cur_p = float(stock_prices[tkr].loc[wk]) if tkr in stock_prices and wk in stock_prices[tkr].index else pos["entry_price"]
                        entry_p = pos["entry_price"]
                        pnl = (cur_p / entry_p - 1.0) * 100.0 if entry_p > 0 else 0.0
                        closed_trades.append({
                            "ticker": tkr,
                            "entry_date": pos["entry_date"],
                            "exit_date": wk_str,
                            "entry_price": round(entry_p, 2),
                            "exit_price": round(cur_p, 2),
                            "profit_pct": round(pnl, 2),
                            "weight": round(pos["weight"], 6),
                            "reason": "Rotazione trimestrale",
                            "is_crypto": False,
                            "asset_class": "Azioni (Low-Beta)",
                            "era": "2012-2024 (Point-In-Time)",
                        })
                        del open_sim_positions[tkr]

                for tkr in added_tickers:
                    cur_p = float(stock_prices[tkr].loc[wk]) if tkr in stock_prices and wk in stock_prices[tkr].index else 100.0
                    open_sim_positions[tkr] = {
                        "ticker": tkr,
                        "entry_date": wk_str,
                        "entry_price": cur_p,
                        "weight": stock_w,
                        "is_crypto": False,
                        "asset_class": "Azioni (Low-Beta)",
                    }

                for tkr in (set(current_basket) & set(new_basket)):
                    if tkr in open_sim_positions:
                        open_sim_positions[tkr]["weight"] = stock_w

                current_basket = new_basket
                prev_basket_tickers = set(current_basket)

    print(f"      Simulazione completata in {time.time() - t0:.1f}s. Generati {len(closed_trades)} trade.")

    print("[3/5] Esecuzione Crypto Frontier Venture Backtest (2018-2024)...")
    crypto_cache = REPO_ROOT / "research" / "crypto_ohlcv_extended_cache"
    crypto_dfs = load_crypto_dataset(str(crypto_cache))
    cfg = CryptoVentureConfig(
        universe_mode="ALL",
        max_slots=7,
        stop_mode="ATR_CLOSE",
        atr_multiplier=2.5,
        time_stop_days=21,
        freeride_multiplier=2.25,
        trailing_stop_pct=0.30,
        slippage_bps=10.0,
    )
    matrices = precompute_market_matrices(crypto_dfs, cfg)
    res_crypto = run_crypto_venture_backtest(matrices, cfg, tax_enabled=False)
    crypto_trades = res_crypto["completed_trades"]

    crypto_closed_trades: List[Dict[str, Any]] = []
    for ct in crypto_trades:
        reason_label = CRYPTO_REASON_MAP.get(ct.exit_reason, ct.exit_reason)
        crypto_closed_trades.append({
            "ticker": ct.symbol,
            "entry_date": str(ct.entry_date.date()),
            "exit_date": str(ct.exit_date.date()),
            "entry_price": round(float(ct.entry_price), 4),
            "exit_price": round(float(ct.exit_price), 4),
            "profit_pct": round(float(ct.pnl_pct * 100.0), 2),
            "weight": round(0.08 / 7.0, 6),  # 8% crypto bucket diviso 7 slot = ~1.14% nominale per slot
            "reason": reason_label,
            "is_crypto": True,
            "asset_class": "Cryptovalute",
            "era": "2018-2024 (Crypto Frontier Venture)",
        })
    print(f"      Generati {len(crypto_closed_trades)} trade da Crypto Frontier Venture.")

    print("[4/5] Caricamento trade reali dal Portafoglio Tracciato Live (2024-Oggi)...")
    portfolio_file = REPO_ROOT / "portfolio.json"
    live_trades: List[Dict[str, Any]] = []
    if portfolio_file.exists():
        with open(portfolio_file) as f:
            p_data = json.load(f)
        for lt in p_data.get("trade_history", []):
            is_cr = lt.get("is_crypto", False)
            tkr = lt.get("ticker", "")
            ac = lt.get("asset_class") or determine_asset_class(tkr, is_cr)
            live_trades.append({
                "ticker": tkr,
                "entry_date": lt.get("entry_date", ""),
                "exit_date": lt.get("exit_date", ""),
                "entry_price": round(float(lt.get("entry_price", 0.0)), 4 if is_cr else 2),
                "exit_price": round(float(lt.get("exit_price", 0.0)), 4 if is_cr else 2),
                "profit_pct": round(float(lt.get("profit_pct", 0.0)), 2),
                "weight": round(float(lt.get("weight", 0.0)), 6),
                "reason": lt.get("reason", "Operativita Live"),
                "is_crypto": is_cr,
                "asset_class": ac,
                "era": "2024-Oggi (Tracking Live)",
            })
    print(f"      Caricati {len(live_trades)} trade live.")

    print("[5/5] Unificazione, ordinamento e persistenza su disco...")
    all_trades = closed_trades + crypto_closed_trades + live_trades

    # Ordiniamo cronologicamente decrescente per exit_date (dal piu recente al piu vecchio)
    all_trades.sort(key=lambda t: (t.get("exit_date", ""), t.get("entry_date", "")), reverse=True)

    # Aggiungi un id progressivo
    for idx, t in enumerate(all_trades, 1):
        t["trade_id"] = idx

    json_path = REPO_ROOT / "apex_full_historical_trades.json"
    csv_path = REPO_ROOT / "apex_full_historical_trades.csv"

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(all_trades, f, indent=2, ensure_ascii=False)

    df_trades = pd.DataFrame(all_trades)
    df_trades.to_csv(csv_path, index=False)

    print(f"[OK] Salvati con successo {len(all_trades)} trade in:")
    print(f"     - {json_path}")
    print(f"     - {csv_path}")

    # Statistiche riassuntive
    era_counts = df_trades["era"].value_counts().to_dict()
    class_counts = df_trades["asset_class"].value_counts().to_dict()
    win_rate = (df_trades["profit_pct"] > 0).mean() * 100.0
    wins_sum = df_trades.loc[df_trades["profit_pct"] > 0, "profit_pct"].sum()
    loss_sum = abs(df_trades.loc[df_trades["profit_pct"] < 0, "profit_pct"].sum())
    pf = (wins_sum / loss_sum) if loss_sum > 0 else 999.0

    print("\n--- Riepilogo Registro Operazioni Apex (1987-Oggi) ---")
    print(f"Totale Operazioni Chiuse: {len(all_trades)}")
    print(f"Win Rate Complessivo: {win_rate:.1f}%")
    print(f"Profit Factor Complessivo: {pf:.2f}")
    print("\nDistribuzione per Era:")
    for era, count in era_counts.items():
        print(f"  - {era}: {count} trade")
    print("\nDistribuzione per Classe di Attivo:")
    for cls, count in class_counts.items():
        print(f"  - {cls}: {count} trade")

if __name__ == "__main__":
    generate_full_historical_trades()
