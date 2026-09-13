"""
test_bugfixes_hardening.py — Test di regressione forense per i bug corretti e l'hardening sistemico
"""

import calendar
import datetime
import numpy as np
import pandas as pd
import pytest

from apex_v2_engine import _weekly_close, _realized_vol, compute_v2_macro_signal, V2_CLASS_TICKER
from backend import compute_should_decide, mark_to_market_and_compound_nav
from crypto_frontier_venture_engine import evaluate_daily_crypto_frontier, CryptoVentureConfig
import convex_engine


def test_crypto_returns_compounding_in_nav():
    """Verifica che i rendimenti crypto vengano effettivamente capitalizzati nel NAV."""
    initial_nav = 100_000.0
    pf = {
        "nav_usd": initial_nav,
        "open_positions": {
            "BTC": {
                "entry_date": "2026-09-01",
                "entry_price": 60_000.0,
                "current_price": 60_000.0,
                "weight": 0.20,
                "is_crypto": True
            },
            "SOL": {
                "entry_date": "2026-09-01",
                "entry_price": 100.0,
                "current_price": 100.0,
                "weight": 0.10,
                "is_crypto": True
            },
            "AAPL": {
                "entry_date": "2026-09-01",
                "entry_price": 200.0,
                "current_price": 200.0,
                "weight": 0.30,
                "is_crypto": False
            }
        }
    }

    # BTC sale da 60k a 66k (+10%), SOL sale da 100 a 120 (+20%), AAPL invariato a 200
    # Rendimento portafoglio atteso: 0.20 * 0.10 + 0.10 * 0.20 + 0.30 * 0.0 = +0.04 (+4%)
    prices_by_ticker = {
        "BTC-USD": 66_000.0,
        "BTC": 66_000.0,
        "SOL-USD": 120.0,
        "SOL": 120.0,
        "AAPL": 200.0
    }

    nav_usd = mark_to_market_and_compound_nav(pf, prices_by_ticker)
    expected_nav = initial_nav * 1.04
    assert abs(nav_usd - expected_nav) < 1e-2, f"Expected {expected_nav}, got {nav_usd}"
    assert pf["open_positions"]["BTC"]["current_price"] == 66_000.0
    assert pf["open_positions"]["SOL"]["current_price"] == 120.0


def test_compute_should_decide_last_friday_all_months():
    """Verifica che compute_should_decide scatti esattamente all'ultimo venerdì di tutti i 48 mesi (2024-2027)."""
    for year in range(2024, 2028):
        for month in range(1, 13):
            days_in_month = calendar.monthrange(year, month)[1]
            decision_day = None
            prev_state = {"last_decision_month": None}

            for day in range(1, days_in_month + 1):
                dt = datetime.datetime(year, month, day)
                if compute_should_decide(dt, prev_state, just_migrating=False):
                    assert decision_day is None, f"Decisione scattata più volte nel mese {year}-{month} (giorno {day})"
                    decision_day = day
                    prev_state["last_decision_month"] = dt.strftime("%Y-%m")

            cal = calendar.monthcalendar(year, month)
            fridays = [week[4] for week in cal if week[4] != 0]
            last_friday = fridays[-1]
            assert decision_day == last_friday, f"Mese {year}-{month:02d}: atteso giorno {last_friday}, ottenuto {decision_day}"


def test_compute_should_decide_weekend_grace_window():
    """Verifica che un run slittato a sabato o domenica dell'ultimo weekend catturi la decisione."""
    # Sabato 26 Settembre 2026 (il giorno dopo l'ultimo venerdì 25 Settembre 2026)
    dt_sat = datetime.datetime(2026, 9, 26)
    prev_state = {"last_decision_month": "2026-08"}
    assert compute_should_decide(dt_sat, prev_state, just_migrating=False) is True

    # Domenica 27 Settembre 2026
    dt_sun = datetime.datetime(2026, 9, 27)
    assert compute_should_decide(dt_sun, prev_state, just_migrating=False) is True

    # Se già eseguito a settembre, non deve scattare
    prev_state_done = {"last_decision_month": "2026-09"}
    assert compute_should_decide(dt_sat, prev_state_done, just_migrating=False) is False


def test_days_no_high_invariance_to_same_day_runs():
    """Verifica che esecuzioni multiple nello stesso giorno non accelerino days_no_high."""
    cfg = CryptoVentureConfig()
    dates = pd.date_range("2026-08-01", periods=60, freq="D")
    df_sui = pd.DataFrame({
        "Open": [10.0] * 60,
        "High": [10.0] * 60,
        "Low": [9.0] * 60,
        "Close": [9.5] * 60,
        "Volume": [1_000_000.0] * 60
    }, index=dates)

    crypto_dfs = {"SUI-USD": df_sui, "SUI": df_sui}

    open_pos = {
        "SUI": {
            "entry_date": "2026-09-01",
            "entry_price": 10.0,
            "current_price": 9.5,
            "peak_price": 10.0,
            "last_high_date": "2026-09-01",
            "days_no_high": 0,
            "weight": 0.05,
            "is_crypto": True,
            "freeride_done": False,
            "atr_entry": 0.5
        }
    }

    # Esegui 5 volte lo stesso giorno (2026-09-05, ovvero 4 giorni dopo il massimo)
    for _ in range(5):
        res = evaluate_daily_crypto_frontier(
            open_positions=open_pos,
            crypto_alloc_pct=15.0,
            crypto_dfs=crypto_dfs,
            today_str="2026-09-05",
            config=cfg
        )
        sui_pos = res["updated_positions"]["SUI"]
        assert sui_pos["days_no_high"] == 4, f"Atteso days_no_high=4, ottenuto {sui_pos["days_no_high"]}"


def test_atr_stop_floor_bound():
    """Verifica che con ATR anomalo (es. 60% del prezzo), lo stop ATR sia limitato e mai <= 0."""
    cfg = CryptoVentureConfig(atr_multiplier=2.5, circuit_breaker_intraday_pct=0.50)
    dates = pd.date_range("2026-08-01", periods=60, freq="D")
    df_vol = pd.DataFrame({
        "Open": [100.0] * 60,
        "High": [110.0] * 60,
        "Low": [70.0] * 60,
        "Close": [80.0] * 60,
        "Volume": [1_000_000.0] * 60
    }, index=dates)
    crypto_dfs = {"VOL-USD": df_vol, "VOL": df_vol}

    open_pos = {
        "VOL": {
            "entry_date": "2026-09-01",
            "entry_price": 100.0,
            "current_price": 80.0,
            "peak_price": 100.0,
            "last_high_date": "2026-09-01",
            "days_no_high": 1,
            "weight": 0.05,
            "is_crypto": True,
            "freeride_done": False,
            "atr_entry": 60.0
        }
    }

    res = evaluate_daily_crypto_frontier(
        open_positions=open_pos,
        crypto_alloc_pct=15.0,
        crypto_dfs=crypto_dfs,
        today_str="2026-09-02",
        config=cfg
    )
    vol_pos = res["updated_positions"].get("VOL")
    if vol_pos:
        assert vol_pos["stop_loss"] >= 50.0, f"Stop loss {vol_pos["stop_loss"]} inferiore al minimo consentito"


def test_weekly_close_dataframe_robustness():
    """Verifica che _weekly_close gestisca sia Series 1D sia DataFrame 2D senza TypeError."""
    dates = pd.date_range("2025-01-01", periods=200, freq="D")
    df_normal = pd.DataFrame({"Close": np.linspace(100, 150, 200)}, index=dates)
    wc_normal = _weekly_close(df_normal)
    assert isinstance(wc_normal, pd.Series)
    vol_normal = _realized_vol(wc_normal, 12)
    assert vol_normal is not None and vol_normal > 0

    df_yfin = pd.concat({"SPY": df_normal}, axis=1)
    wc_2d = _weekly_close(df_yfin)
    assert isinstance(wc_2d, pd.Series)
    vol_2d = _realized_vol(wc_2d, 12)
    assert vol_2d is not None and vol_2d > 0


def test_cash_allocation_rounding_non_negative():
    """Verifica che i pesi macro sommino esattamente al 100% e che Cash sia sempre >= 0.0."""
    dates = pd.date_range("2020-01-01", periods=300, freq="W-FRI")
    b_data = {}
    for cls, ticker in V2_CLASS_TICKER.items():
        b_data[ticker] = pd.DataFrame({"Close": np.linspace(100, 200, 300) * (1 + np.random.normal(0, 0.01, 300))}, index=dates)

    alloc, hyst, dbg = compute_v2_macro_signal(b_data)
    assert alloc["Cash"] >= 0.0
    total_alloc = round(sum(alloc.values()), 2)
    assert total_alloc == 100.0, f"Atteso 100.0%, ottenuto {total_alloc}%: {alloc}"


def test_convex_cash_allocation_bar():
    """Verifica che la barra di composizione di Convex gestisca correttamente la liquidità."""
    report = convex_engine.evaluate_convex_stack(
        current_holdings={"NTSG": 100.0},
        market_prices={"NTSG": 28.0},
        monthly_pac_eur=500.0,
        cash_balance=200.0
    )
    total_val = report.total_value
    assert total_val == (100.0 * 28.0) + 200.0
    cash_val = total_val - sum(report.assets[k].current_value for k in convex_engine.CONVEX_INSTRUMENTS)
    cash_pct = (cash_val / total_val) * 100.0
    assert abs(cash_pct - (200.0 / 3000.0 * 100.0)) < 1e-4
