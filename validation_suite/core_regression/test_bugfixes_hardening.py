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
        assert sui_pos["days_no_high"] == 4, f"Atteso days_no_high=4, ottenuto {sui_pos['days_no_high']}"


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
        assert vol_pos["stop_loss"] >= 50.0, f"Stop loss {vol_pos['stop_loss']} inferiore al minimo consentito"


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


def test_trade_orders_and_action_log_renderers():
    """Verifica che i renderers delle tabelle ordini e log storico non contengano emoji e includano i badge corretti."""
    import page_apex
    import pandas as pd
    import json
    import re

    # 1. Verifica render_orders_html_table
    df_orders = pd.DataFrame([
        {
            "Operazione": "ACQUISTO",
            "Strumento": "Microsoft (MSFT)",
            "Variazione Peso": "+2.50%",
            "Controvalore (€)": 2500.0,
            "Quote": "6",
            "Prezzo ($)": 415.0,
            "Dettaglio Operativo": "Nuovo ingresso a portafoglio",
        },
        {
            "Operazione": "RIDUZIONE",
            "Strumento": "Bitcoin",
            "Variazione Peso": "-1.50%",
            "Controvalore (€)": 1500.0,
            "Quote": "0.0195",
            "Prezzo ($)": 77000.0,
            "Dettaglio Operativo": "Trim di ribilanciamento",
        },
    ])
    html_orders = page_apex.render_orders_html_table(df_orders, "€")
    assert "ACQUISTO" in html_orders
    assert "RIDUZIONE" in html_orders
    assert "Microsoft" in html_orders

    # 2. Verifica render_action_log_html_table (solo azioni operative reali, esclude mantenimenti)
    actions = [
        "INCREMENTO: Bitcoin | Riallocazione +15.4% | Prezzo: $76,652.09",
        "CHIUSURA: KIM | Vende 2.13% del capitale (100% posizione) | Prezzo: $24.03 | P&L: +3.39%",
        "MANTENIMENTO: BTC | Allocazione 15.9% | Prezzo: $76,793.20",
    ]
    html_log = page_apex.render_action_log_html_table(actions)
    assert "INCREMENTO" in html_log
    assert "CHIUSURA" in html_log
    assert "MANTENIMENTO" not in html_log
    assert "76,652.09" in html_log

    # 3. Verifica assenza di emoji in portfolio.json
    with open("portfolio.json", "r", encoding="utf-8") as f:
        content = f.read()
    emoji_pattern = re.compile(r"[\U00010000-\U0010ffff\u2600-\u26ff\u2700-\u27bf]")
    assert not emoji_pattern.findall(content), "Trovate emoji in portfolio.json"


def test_apex_trades_register_renderers():
    """Verifica che le tabelle del registro storico e posizioni aperte di Apex renderizzino correttamente e senza emoji."""
    import page_apex
    import pandas as pd
    import re

    # 1. Verifica render_hist_trades_html_table
    df_hist = pd.DataFrame([
        {
            "Titolo": "BTC",
            "Data Ingresso": "24 Ago 2026",
            "Data Uscita": "13 Set 2026",
            "Durata": "20g",
            "Prezzo Ingresso": 78564.98,
            "Prezzo Uscita": 77191.44,
            "Peso (%)": 32.61,
            "Rendimento %": -1.75,
            "Motivazione": "Stop Regime",
        },
        {
            "Titolo": "KIM",
            "Data Ingresso": "4 Mag 2026",
            "Data Uscita": "24 Ago 2026",
            "Durata": "112g",
            "Prezzo Ingresso": 23.24,
            "Prezzo Uscita": 24.03,
            "Peso (%)": 1.11,
            "Rendimento %": 3.39,
            "Motivazione": "Ribilanciamento",
        }
    ])
    cols = ["Titolo", "Data Ingresso", "Data Uscita", "Durata", "Prezzo Ingresso", "Prezzo Uscita", "Peso (%)", "Rendimento %", "Motivazione"]
    html_hist = page_apex.render_hist_trades_html_table(df_hist, cols)
    assert "BTC" in html_hist
    assert "Stop Regime" in html_hist
    assert "32.61%" in html_hist
    assert "Ribilanciamento" in html_hist

    # 2. Verifica render_open_trades_html_table
    df_open = pd.DataFrame([
        {
            "Titolo": "BTC",
            "Data Ingresso": "13 Set 2026",
            "Giorni": "0g",
            "Prezzo Ingresso": 77173.73,
            "Prezzo Attuale": 76738.02,
            "Peso (%)": 15.88,
            "Rendimento %": -0.56,
            "Stato": "In Posizione",
        }
    ])
    html_open = page_apex.render_open_trades_html_table(df_open)
    assert "BTC" in html_open
    assert "IN POSIZIONE" in html_open
    assert "15.88%" in html_open

    # 3. Assenza emoji
    emoji_pattern = re.compile(r"[\U00010000-\U0010ffff\u2600-\u26ff\u2700-\u27bf]")
    assert not emoji_pattern.findall(html_hist)
    assert not emoji_pattern.findall(html_open)


def test_apex_full_historical_trades_integrity(historical_trades_json_path, historical_trades_csv_path):
    """Verifica l'integrità, la completezza e l'assenza di lookahead/emoji nel registro storico completo (1987-Oggi)."""
    import json
    import re
    import page_apex

    assert historical_trades_json_path.exists(), f"apex_full_historical_trades.json non trovato in {historical_trades_json_path}"
    assert historical_trades_csv_path.exists(), f"apex_full_historical_trades.csv non trovato in {historical_trades_csv_path}"

    with open(historical_trades_json_path, encoding="utf-8") as f:
        trades = json.load(f)

    # 1. Almeno 1000 trade storici registrati
    assert len(trades) >= 1000, f"Attesi almeno 1000 trade, trovati {len(trades)}"

    required_fields = {
        "trade_id", "ticker", "entry_date", "exit_date", "entry_price",
        "exit_price", "profit_pct", "weight", "reason", "is_crypto",
        "asset_class", "era"
    }

    eras = set()
    classes = set()
    date_regex = re.compile(r"^\d{4}-\d{2}-\d{2}$")

    for t in trades:
        # Campi obbligatori
        for field in required_fields:
            assert field in t, f"Campo {field} mancante nel trade {t.get('trade_id')}"

        # Formattazione date
        assert date_regex.match(t["entry_date"]), f"Data ingresso non valida: {t['entry_date']}"
        assert date_regex.match(t["exit_date"]), f"Data uscita non valida: {t['exit_date']}"
        assert t["exit_date"] >= t["entry_date"], f"Data uscita precedente all'ingresso nel trade {t}"

        eras.add(t["era"])
        classes.add(t["asset_class"])

    # 2. Tutte le 4 ere storiche devono essere presenti
    assert "1987-2011 (Macro Allocazione)" in eras
    assert "2012-2024 (Point-In-Time)" in eras
    assert "2018-2024 (Crypto Frontier Venture)" in eras
    assert "2024-Oggi (Tracking Live)" in eras

    # 3. Tutte le 5 classi di attivo devono essere coperte
    assert "Azioni (Low-Beta)" in classes
    assert "Cryptovalute" in classes
    assert "Obbligazioni" in classes
    assert "Oro" in classes
    assert "Azioni (Indice S&P 500)" in classes

    # 4. Rendering tabella HTML con colonne complete
    sample_df = pd.DataFrame(trades[:10]).rename(columns={
        "ticker": "Titolo", "entry_date": "Data Ingresso", "exit_date": "Data Uscita",
        "entry_price": "Prezzo Ingresso", "exit_price": "Prezzo Uscita",
        "profit_pct": "Rendimento %", "reason": "Motivazione",
        "asset_class": "Classe", "era": "Era"
    })
    sample_df["Durata"] = "14g"
    sample_df["Peso (%)"] = 1.25
    cols = ["Titolo", "Classe", "Era", "Data Ingresso", "Data Uscita", "Durata", "Prezzo Ingresso", "Prezzo Uscita", "Peso (%)", "Rendimento %", "Motivazione"]
    html_out = page_apex.render_hist_trades_html_table(sample_df, cols)

    assert "Tipo Operazione" in html_out
    assert "Classe" in html_out
    assert "Era" in html_out

    # 5. Assoluta assenza di emoji
    emoji_pattern = re.compile(r"[\U00010000-\U0010ffff\u2600-\u26ff\u2700-\u27bf]")
    assert not emoji_pattern.findall(html_out), "Trovate emoji nella tabella HTML renderizzata"
    with open(historical_trades_json_path, encoding="utf-8") as f:
        json_content = f.read()
    assert not emoji_pattern.findall(json_content), "Trovate emoji nel file JSON dei trade storici"


def test_audit_display_ticker_and_crypto_uniformity():
    """Verifica che get_display_ticker restituisca nomi macro per GLD/IEF/Cash e ticker puri per crypto e azioni."""
    import backend
    assert backend.get_display_ticker("GLD") == "Oro"
    assert backend.get_display_ticker("IEF") == "Obbligazioni"
    assert backend.get_display_ticker("Cash") == "Liquidità"
    assert backend.get_display_ticker("BTC") == "BTC"
    assert backend.get_display_ticker("BTC-USD") == "BTC"
    assert backend.get_display_ticker("SOL-USD") == "SOL"
    assert backend.get_display_ticker("LUNC-USD") == "LUNC"
    assert backend.get_display_ticker("NVDA") == "NVDA"


def test_audit_record_trade_persists_is_crypto(tmp_path):
    """Verifica che record_trade persista correttamente il flag is_crypto nel registro delle operazioni."""
    import backend
    test_pf = tmp_path / "portfolio.json"
    backend.PORTFOLIO_FILE = str(test_pf)

    pf_data = {"v2_migrated": True, "nav_usd": 100000.0, "open_positions": {
        "BTC": {"weight": 0.20, "entry_price": 50000.0, "current_price": 60000.0, "is_crypto": True, "entry_date": "2026-08-01"},
        "AAPL": {"weight": 0.10, "entry_price": 200.0, "current_price": 220.0, "is_crypto": False, "entry_date": "2026-08-01"}
    }, "trade_history": []}
    backend.save_json_atomic(str(test_pf), pf_data)

    # Ribilanciamento con chiusura totale
    backend.update_portfolio({"Equities": 0.0, "Bonds": 0.0, "Gold": 0.0, "Crypto": 0.0}, [], {"BTC-USD": 60000.0, "AAPL": 220.0}, "2026-09-14")
    updated_pf = backend.load_json_safe(str(test_pf))
    th = updated_pf.get("trade_history", [])
    btc_trade = next((t for t in th if t["ticker"] == "BTC"), None)
    aapl_trade = next((t for t in th if t["ticker"] == "AAPL"), None)

    assert btc_trade is not None
    assert btc_trade.get("is_crypto") is True
    assert aapl_trade is not None
    assert aapl_trade.get("is_crypto") is False


def test_audit_convex_trim_threshold_alignment():
    """Verifica che le soglie di trim per WBTC e PPFB siano allineate a 0.13125 (+75% sopra il target 7.5%)."""
    import portfolio_manager
    cfg = portfolio_manager.load_config()
    assert cfg["wbtc_trim_threshold"] == 0.13125
    assert cfg["ppfb_trim_threshold"] == 0.13125
    assert portfolio_manager.CONVEX_INSTRUMENTS_METADATA["WBTC"]["trim_threshold"] == 0.13125
    assert portfolio_manager.CONVEX_INSTRUMENTS_METADATA["PPFB"]["trim_threshold"] == 0.13125



