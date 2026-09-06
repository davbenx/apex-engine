"""
test_altcoin_venture.py — Test Unitari del Sistema Venture Satellite Altcoin
================================================================================
Verifica rigorosa di tutte le regole asimmetriche e dei vincoli matematici:
1. Apertura posizione e dimensionamento dello slot
2. Protocollo Free-Ride al +100% (2x): recupero integrale del capitale iniziale
3. Milestone progressive (+300%, +700%) e accumulo profitti riciclati
4. Trailing stop post-milestone e Hard stop loss (-40%)
5. Simulazione caso studio asimmetrico reale (10x run seguito da crollo -95%)
================================================================================
"""

import os
import json
import pytest
from altcoin_venture_engine import (
    VentureAltcoinEngine,
    simulate_asymmetric_lifecycle,
    DEFAULT_BUDGET_EUR,
    DEFAULT_MAX_SLOTS,
    HARD_STOP_LOSS_PCT,
    FREE_RIDE_MULTIPLIER,
    FREE_RIDE_SELL_FRACTION
)

TEMP_PORTFOLIO_PATH = "/tmp/test_venture_portfolio.json"


@pytest.fixture(autouse=True)
def cleanup_temp_file():
    if os.path.exists(TEMP_PORTFOLIO_PATH):
        os.remove(TEMP_PORTFOLIO_PATH)
    yield
    if os.path.exists(TEMP_PORTFOLIO_PATH):
        os.remove(TEMP_PORTFOLIO_PATH)


def test_engine_initialization():
    engine = VentureAltcoinEngine(portfolio_path=TEMP_PORTFOLIO_PATH)
    summary = engine.get_portfolio_summary()
    assert summary["budget_total_eur"] == DEFAULT_BUDGET_EUR
    assert summary["cash_available_eur"] == DEFAULT_BUDGET_EUR
    assert summary["open_positions_count"] == 0
    assert summary["free_rides_count"] == 0
    assert summary["recycled_profits_eur"] == 0.0


def test_open_position():
    engine = VentureAltcoinEngine(portfolio_path=TEMP_PORTFOLIO_PATH)
    slot_size = engine.get_slot_size_eur()
    expected_slot = DEFAULT_BUDGET_EUR / DEFAULT_MAX_SLOTS
    assert slot_size == expected_slot

    pos = engine.open_position(
        ticker="SOL",
        name="Solana",
        entry_price_usd=100.0,
        sector="Layer 1",
        eur_usd_rate=1.0850
    )

    assert pos["ticker"] == "SOL"
    assert pos["initial_cost_eur"] == expected_slot
    assert pos["entry_price_usd"] == 100.0
    assert pos["current_shares"] == pytest.approx((expected_slot * 1.0850) / 100.0, rel=1e-3)
    assert not pos["is_free_ride"]
    assert pos["next_target_usd"] == round(100.0 * FREE_RIDE_MULTIPLIER, 4)

    summary = engine.get_portfolio_summary()
    assert summary["cash_available_eur"] == pytest.approx(DEFAULT_BUDGET_EUR - expected_slot, rel=1e-2)
    assert summary["open_positions_count"] == 1


def test_milestone_1_free_ride():
    engine = VentureAltcoinEngine(portfolio_path=TEMP_PORTFOLIO_PATH)
    expected_slot = DEFAULT_BUDGET_EUR / DEFAULT_MAX_SLOTS
    engine.open_position("AVAX", "Avalanche", entry_price_usd=20.0, eur_usd_rate=1.0)
    initial_shares = engine.state["positions"]["AVAX"]["initial_shares"]

    # Prezzo raggiunge il target Free-Ride (20 * 2.25 = 45$)
    target_p1 = 20.0 * FREE_RIDE_MULTIPLIER
    engine.update_price("AVAX", target_p1)
    signals = engine.evaluate_signals(eur_usd_rate=1.0)
    assert len(signals) == 1
    assert signals[0]["type"] == "MILESTONE_1_FREE_RIDE"
    assert signals[0]["shares_to_sell"] == pytest.approx(initial_shares * FREE_RIDE_SELL_FRACTION)

    # Esegui vendita Milestone 1
    res = engine.execute_sell_signal(signals[0], exec_price_usd=target_p1, eur_usd_rate=1.0)
    assert res["status"] == "SUCCESS"

    pos = engine.state["positions"]["AVAX"]
    assert pos["is_free_ride"] is True
    # Capitale recuperato esattamente pari al costo iniziale dello slot
    assert pos["capital_recovered_eur"] == pytest.approx(expected_slot, rel=1e-2)
    # Quote rimanenti (55.6% nel caso di 2.25x)
    assert pos["current_shares"] == pytest.approx(initial_shares * (1.0 - FREE_RIDE_SELL_FRACTION), rel=1e-3)
    # Cassa tornata a DEFAULT_BUDGET_EUR
    assert engine.state["cash_available_eur"] == pytest.approx(DEFAULT_BUDGET_EUR, rel=1e-2)


def test_milestone_2_and_profit_recycling():
    engine = VentureAltcoinEngine(portfolio_path=TEMP_PORTFOLIO_PATH)
    engine.open_position("NEAR", "Near Protocol", entry_price_usd=5.0, eur_usd_rate=1.0)
    
    # 1. Trigger e vendita Free Ride a 5 * 2.25 = 11.25$
    target_p1 = 5.0 * FREE_RIDE_MULTIPLIER
    engine.update_price("NEAR", target_p1)
    sig1 = engine.evaluate_signals(eur_usd_rate=1.0)[0]
    engine.execute_sell_signal(sig1, exec_price_usd=target_p1, eur_usd_rate=1.0)

    # 2. Prezzo sale a 20$ (+300% / 4x rispetto a 5$)
    engine.update_price("NEAR", 20.0)
    sig2 = engine.evaluate_signals(eur_usd_rate=1.0)
    assert len(sig2) == 1
    assert sig2[0]["type"] == "MILESTONE_2"

    shares_before = engine.state["positions"]["NEAR"]["current_shares"]
    res2 = engine.execute_sell_signal(sig2[0], exec_price_usd=20.0, eur_usd_rate=1.0)
    assert res2["status"] == "SUCCESS"

    # Verifico che il ricavato vada nei profitti riciclati
    expected_profit = (shares_before * 0.20) * 20.0
    assert engine.state["recycled_profits_eur"] == pytest.approx(expected_profit, rel=1e-2)


def test_hard_stop_loss():
    engine = VentureAltcoinEngine(portfolio_path=TEMP_PORTFOLIO_PATH)
    expected_slot = DEFAULT_BUDGET_EUR / DEFAULT_MAX_SLOTS
    engine.open_position("DOT", "Polkadot", entry_price_usd=10.0, eur_usd_rate=1.0)

    # Prezzo scende a 5.5$ (-45%, sotto la soglia di -40%)
    engine.update_price("DOT", 5.5)
    signals = engine.evaluate_signals(eur_usd_rate=1.0)
    assert len(signals) == 1
    assert signals[0]["type"] == "STOP_LOSS"

    engine.execute_sell_signal(signals[0], exec_price_usd=5.5, eur_usd_rate=1.0)
    # Posizione chiusa
    assert "DOT" not in engine.state["positions"]
    # Capitale parziale recuperato in cassa (55% di slot)
    recovered = expected_slot * 0.55
    assert engine.state["cash_available_eur"] == pytest.approx(DEFAULT_BUDGET_EUR - expected_slot + recovered, rel=1e-2)


def test_asymmetric_lifecycle_simulation_sol_style():
    """
    Testa la matematica del modello su un token che fa un run da 10x (10$ -> 100$)
    e poi subisce un crash del -95% tornando a 5$.
    Dimostra che il protocollo Free-Ride + Milestone estrae forte profitto netto
    anche se il token crolla completamente.
    """
    price_trajectory = [
        ("2024-01-01", 10.0),                     # Ingresso
        ("2024-02-01", 10.0 * FREE_RIDE_MULTIPLIER),  # Milestone 1: Free-Ride -> Recupero 400 EUR
        ("2024-03-01", 40.0),                     # Milestone 2: 4x (+300%) -> Take profit 20%
        ("2024-04-01", 80.0),                     # Milestone 3: 8x (+700%) -> Take profit 25%
        ("2024-05-01", 100.0),                    # Massimo storico
        ("2024-06-01", 65.0),                     # Trailing stop -30% dal max (100 -> 70 -> exit a 65)
        ("2024-07-01", 5.0),                      # Crash finale a 5$ (-95% dal top)
    ]

    sim = simulate_asymmetric_lifecycle(
        ticker="SOL_CASE",
        price_series=price_trajectory,
        initial_capital_eur=400.0,
        eur_usd_rate=1.0
    )

    assert sim["is_free_ride"] is True
    assert sim["recovered_capital_eur"] == pytest.approx(400.0, rel=1e-1)
    # Il profitto netto estratto è largamente positivo
    assert sim["recycled_profits_eur"] > 1000.0
    assert sim["net_pnl_eur"] > 1000.0
    assert sim["roi_pct"] > 250.0


def test_kill_switch_and_budget_scaling():
    engine = VentureAltcoinEngine(portfolio_path=TEMP_PORTFOLIO_PATH)
    engine.set_satellite_budget(15000.0, max_slots=15)
    assert engine.state["budget_total_eur"] == 15000.0
    assert engine.state["max_slots"] == 15
    assert engine.get_slot_size_eur() == 1000.0

    # Test Kill-Switch Normale
    ks1 = engine.check_kill_switch(eur_usd_rate=1.0)
    assert ks1["triggered"] is False
    assert ks1["status"] == "NORMALE"

    # Simulo drawdown pesante (-50% del budget)
    engine.state["cash_available_eur"] = 7000.0
    ks2 = engine.check_kill_switch(eur_usd_rate=1.0)
    assert ks2["triggered"] is True
    assert ks2["status"] == "TRIGGERED_DRAWDOWN"


def test_altcoin_breadth_in_screener():
    import pandas as pd
    import numpy as np
    from altcoin_venture_engine import screen_venture_candidates

    dates = pd.date_range("2024-01-01", periods=160, freq="D")
    btc_series = pd.Series(np.linspace(40000, 65000, 160), index=dates)

    crypto_dict = {
        "SOL-USD": pd.Series(np.linspace(50, 150, 160), index=dates),
        "AVAX-USD": pd.Series(np.linspace(20, 45, 160), index=dates),
        "NEAR-USD": pd.Series(np.linspace(2, 6, 160), index=dates),
    }

    res = screen_venture_candidates(crypto_dict, btc_series, cross_kraken_futures=False, fundamentals_map={})
    assert "altcoin_breadth_pct" in res
    assert "altcoin_breadth_regime" in res
    assert res["altcoin_breadth_pct"] == 100.0
    assert "IPERESTENSO" in res["altcoin_breadth_regime"]
    assert "ranked_universe" in res
    assert len(res["ranked_universe"]) == 3


def test_load_crypto_universe_data_bundle():
    from altcoin_venture_engine import load_crypto_universe_data
    dfs, btc = load_crypto_universe_data(force_live=False)
    assert btc is not None
    assert len(btc) >= 100
    assert "SOL" in dfs or "SOL-USD" in dfs
    assert len(dfs) >= 15


def test_get_telegram_credentials_resolution(monkeypatch):
    from altcoin_venture_engine import get_telegram_credentials
    # Test explicit args
    t, c = get_telegram_credentials("custom_tok", "custom_chat")
    assert t == "custom_tok"
    assert c == "custom_chat"

    # Test environment fallback
    monkeypatch.setenv("TELEGRAM_TOKEN", "env_tok_123")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "env_chat_456")
    t2, c2 = get_telegram_credentials()
    assert t2 == "env_tok_123"
    assert c2 == "env_chat_456"


def test_venture_telegram_alert_dry_run_formatting(monkeypatch):
    import altcoin_venture_engine as ave
    # Evita chiamate live a CoinGecko/DefiLlama in un test che deve restare
    # offline e veloce -- il fetch reale e' gia' coperto dai test dedicati sopra.
    monkeypatch.setattr(ave, "fetch_fundamentals_map", lambda tickers, **kw: {})

    ok, msg = ave.send_venture_telegram_alert(dry_run=True)
    assert ok is True
    assert "FRONTIER VENTURE" in msg
    assert "MACRO GATE BITCOIN" in msg
    assert "KRAKEN FUTURES" in msg


# ==============================================================================
# TEST FILTRI TOKENOMICS (MC/FDV) E FONDAMENTALE (TVL) — Criteri 2 e 4 §5
# ==============================================================================

class _FakeHTTPResponse:
    """Contesto minimale che imita urllib.request.urlopen(...) per i test offline."""
    def __init__(self, payload):
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._body


def _make_fake_urlopen(url_to_payload):
    """
    url_to_payload: lista di (substringa_url, payload) valutata in ordine —
    la prima substringa contenuta nell'URL della richiesta vince.
    """
    def _fake_urlopen(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        for substr, payload in url_to_payload:
            if substr in url:
                return _FakeHTTPResponse(payload)
        raise AssertionError(f"URL non atteso nel test: {url}")
    return _fake_urlopen


def test_tokenomics_mc_fdv_qualifies_and_fails_safe(monkeypatch):
    import altcoin_venture_engine as ave

    coins_list = [
        {"id": "solana", "symbol": "sol", "name": "Solana"},
        {"id": "some-low-quality-sol-fork", "symbol": "sol", "name": "Sol Fork"},
        {"id": "low-float-coin", "symbol": "lowfloat", "name": "Low Float Coin"},
    ]
    markets = [
        {"id": "solana", "market_cap": 60_000_000_000, "fully_diluted_valuation": 67_000_000_000},   # MC/FDV ~0.90 -> qualificato
        {"id": "some-low-quality-sol-fork", "market_cap": 100, "fully_diluted_valuation": 100_000},    # MC piu' basso, scartato in favore di solana
        {"id": "low-float-coin", "market_cap": 10_000_000, "fully_diluted_valuation": 100_000_000},    # MC/FDV 0.10 -> NON qualificato
    ]

    fake = _make_fake_urlopen([
        ("coins/list", coins_list),
        ("coins/markets", markets),
    ])
    import urllib.request as real_urllib_request
    monkeypatch.setattr(real_urllib_request, "urlopen", fake)

    result = ave.get_tokenomics_mc_fdv(["SOL", "LOWFLOAT", "NEVERLISTED"])
    assert result["SOL"] == pytest.approx(60_000_000_000 / 67_000_000_000, rel=1e-3)
    assert result["LOWFLOAT"] == pytest.approx(0.10, rel=1e-3)
    # Ticker mai visto su CoinGecko -> fail-safe, mai un valore inventato
    assert result["NEVERLISTED"] is None


def test_tvl_trend_qualifies_and_fails_safe(monkeypatch):
    import altcoin_venture_engine as ave
    import urllib.request as real_urllib_request

    n = 100
    chain_series_growing = [{"date": 1_600_000_000 + i * 86400, "tvl": 1_000_000.0 * (1.0 + i * 0.01)} for i in range(n)]

    fake = _make_fake_urlopen([
        ("historicalChainTvl/Solana", chain_series_growing),
    ])
    monkeypatch.setattr(real_urllib_request, "urlopen", fake)

    result = ave.get_tvl_trend_90d(["SOL"])
    assert result["SOL"] is not None
    assert result["SOL"] > 0  # serie in crescita costante -> trend 90d positivo, qualificato

    # Nessuna chain/protocollo noto per un ticker inventato -> fail-safe None
    def _fake_urlopen_protocols_empty(req, timeout=None):
        return _FakeHTTPResponse([])
    monkeypatch.setattr(real_urllib_request, "urlopen", _fake_urlopen_protocols_empty)
    result2 = ave.get_tvl_trend_90d(["NEVERTRACKEDTOKEN"])
    assert result2["NEVERTRACKEDTOKEN"] is None


def test_screen_venture_candidates_gates_on_fundamentals():
    """
    Un token che supera il filtro tecnico ma fallisce tokenomics o fondamentale
    NON deve mai comparire tra i candidati qualificati (a differenza del vecchio
    controllo volume, che era calcolato ma mai collegato alla decisione).
    """
    import pandas as pd
    import numpy as np
    from altcoin_venture_engine import screen_venture_candidates

    dates = pd.date_range("2024-01-01", periods=160, freq="D")
    btc_series = pd.Series(np.linspace(40000, 45000, 160), index=dates)

    crypto_dict = {
        "GOODTOKEN-USD": pd.Series(np.linspace(10, 30, 160), index=dates),
        "BADTOKEN-USD": pd.Series(np.linspace(10, 30, 160), index=dates),
    }

    fundamentals_map = {
        "GOODTOKEN": {"mc_fdv_ratio": 0.75, "tvl_trend_90d_pct": 15.0,
                      "tokenomics_qualified": True, "fundamental_qualified": True},
        "BADTOKEN": {"mc_fdv_ratio": 0.05, "tvl_trend_90d_pct": -60.0,
                     "tokenomics_qualified": False, "fundamental_qualified": False},
    }

    res = screen_venture_candidates(
        crypto_dict, btc_series, cross_kraken_futures=False, fundamentals_map=fundamentals_map
    )
    qualified_tickers = {c["ticker"] for c in res["candidates"]}
    assert "GOODTOKEN" in qualified_tickers
    assert "BADTOKEN" not in qualified_tickers

    bad_row = next(t for t in res["ranked_universe"] if t["ticker"] == "BADTOKEN")
    assert bad_row["passes_technical"] is True
    assert bad_row["tokenomics_qualified"] is False
    assert bad_row["fundamental_qualified"] is False
    assert "SCARTATO" in bad_row["status"]


def test_evaluate_signals_time_stop_triggers_after_30_days_when_lagging_btc():
    """
    Se dopo 30 giorni la posizione non e' in Free Ride e il rendimento del token
    meno quello di BTC nello stesso periodo e' sotto -20%, scatta TIME_STOP.
    """
    from altcoin_venture_engine import VentureAltcoinEngine

    engine = VentureAltcoinEngine(portfolio_path=TEMP_PORTFOLIO_PATH)

    pos = engine.open_position(
        ticker="LAGGER",
        name="Lagger Token",
        entry_price_usd=100.0,
        custom_capital_eur=1000.0,
        entry_date="2024-01-01",
        eur_usd_rate=1.0,
        entry_btc_price_usd=50000.0
    )

    # A 35 giorni (2024-02-05): Token a 90$ (-10%), BTC a 60.000$ (+20%)
    # Alpha relativo = -10% - (+20%) = -30% < -20%
    # Hard stop (-40% = 60$) non e' ancora toccato
    engine.state["positions"]["LAGGER"]["current_price_usd"] = 90.0

    signals = engine.evaluate_signals(
        eur_usd_rate=1.0,
        btc_current_price_usd=60000.0,
        today_date="2024-02-05"
    )

    assert len(signals) == 1
    sig = signals[0]
    assert sig["ticker"] == "LAGGER"
    assert sig["type"] == "TIME_STOP"
    assert sig["action"] == "SELL_ALL"
    assert "Time-Stop scattato" in sig["reason"]

    # Esecuzione del segnale TIME_STOP
    res = engine.execute_sell_signal(sig, eur_usd_rate=1.0, date_str="2024-02-05")
    assert res["status"] == "SUCCESS"
    assert "LAGGER" not in engine.state["positions"]
    assert engine.state["cash_available_eur"] == 9900.0  # 10000 - 1000 + 900


def test_evaluate_signals_time_stop_does_not_trigger_before_30_days():
    """
    Prima di 30 giorni (es. 20 giorni), il Time-Stop NON deve scattare
    anche se il token sta sottoperformando BTC.
    """
    from altcoin_venture_engine import VentureAltcoinEngine

    engine = VentureAltcoinEngine(portfolio_path=TEMP_PORTFOLIO_PATH)

    engine.open_position(
        ticker="YOUNG",
        name="Young Token",
        entry_price_usd=100.0,
        custom_capital_eur=1000.0,
        entry_date="2024-01-01",
        eur_usd_rate=1.0,
        entry_btc_price_usd=50000.0
    )

    # A 20 giorni (2024-01-21): Token a 85$ (-15%), BTC a 55.000$ (+10%) -> Alpha -25%
    engine.state["positions"]["YOUNG"]["current_price_usd"] = 85.0

    signals = engine.evaluate_signals(
        eur_usd_rate=1.0,
        btc_current_price_usd=55000.0,
        today_date="2024-01-21"
    )

    # Nessun segnale: non ha toccato l'hard stop (-40%) e non sono passati 30gg
    assert len(signals) == 0


def test_evaluate_signals_time_stop_does_not_trigger_if_beating_btc():
    """
    Dopo 30 giorni, se il token non sottoperforma BTC di almeno -20%,
    il Time-Stop NON deve scattare.
    """
    from altcoin_venture_engine import VentureAltcoinEngine

    engine = VentureAltcoinEngine(portfolio_path=TEMP_PORTFOLIO_PATH)

    engine.open_position(
        ticker="HEALTHY",
        name="Healthy Token",
        entry_price_usd=100.0,
        custom_capital_eur=1000.0,
        entry_date="2024-01-01",
        eur_usd_rate=1.0,
        entry_btc_price_usd=50000.0
    )

    # A 35 giorni (2024-02-05): Token a 110$ (+10%), BTC a 55.000$ (+10%) -> Alpha 0%
    engine.state["positions"]["HEALTHY"]["current_price_usd"] = 110.0

    signals = engine.evaluate_signals(
        eur_usd_rate=1.0,
        btc_current_price_usd=55000.0,
        today_date="2024-02-05"
    )

    assert len(signals) == 0


def test_evaluate_signals_time_stop_does_not_trigger_if_free_ride():
    """
    Una posizione in Free Ride e' a capitale zero e non deve essere
    tagliata dal Time-Stop (segue la ladder di liquidazione / trailing stop).
    """
    from altcoin_venture_engine import VentureAltcoinEngine

    engine = VentureAltcoinEngine(portfolio_path=TEMP_PORTFOLIO_PATH)

    engine.open_position(
        ticker="FREERUNNER",
        name="Free Runner",
        entry_price_usd=100.0,
        custom_capital_eur=1000.0,
        entry_date="2024-01-01",
        eur_usd_rate=1.0,
        entry_btc_price_usd=50000.0
    )

    # Posizione raggiunge Free Ride
    engine.state["positions"]["FREERUNNER"]["is_free_ride"] = True
    engine.state["positions"]["FREERUNNER"]["current_price_usd"] = 90.0

    signals = engine.evaluate_signals(
        eur_usd_rate=1.0,
        btc_current_price_usd=70000.0,
        today_date="2024-02-05"
    )

    # Nessun time stop su Free Ride
    assert not any(s["type"] == "TIME_STOP" for s in signals)


def test_update_bar_triggers_milestone_1_free_ride_on_intraday_high():
    """
    Verifica che se il massimo intraday tocca la soglia 2.25x (Free Ride)
    ma la chiusura della barra ritraccia al di sotto, la Milestone 1
    scatta regolarmente al prezzo limite (GTC order su exchange).
    """
    from altcoin_venture_engine import VentureAltcoinEngine

    engine = VentureAltcoinEngine(portfolio_path=TEMP_PORTFOLIO_PATH)
    engine.open_position(
        ticker="WICKUP",
        name="Wick Up Token",
        entry_price_usd=100.0,
        custom_capital_eur=1000.0,
        entry_date="2024-01-01",
        eur_usd_rate=1.0
    )

    # Barra con High = 230$ (>= 225$), Low = 98$, Close = 210$ (< 225$)
    engine.update_bar(
        ticker="WICKUP",
        high_usd=230.0,
        low_usd=98.0,
        close_usd=210.0,
        open_usd=100.0
    )

    signals = engine.evaluate_signals(eur_usd_rate=1.0, today_date="2024-01-05")
    assert len(signals) == 1
    sig = signals[0]
    assert sig["ticker"] == "WICKUP"
    assert sig["type"] == "MILESTONE_1_FREE_RIDE"
    assert sig["action"] == "SELL_FREE_RIDE"
    assert sig["price_usd"] == 225.0  # Prezzo limite di esecuzione


def test_update_bar_triggers_hard_stop_on_intraday_low():
    """
    Verifica che se il minimo intraday tocca lo stop secco -40% (60$)
    ma la chiusura rimbalza al di sopra (es. 65$), l'Hard Stop Loss
    scatta regolarmente al prezzo di stop (GTC stop order su exchange).
    """
    from altcoin_venture_engine import VentureAltcoinEngine

    engine = VentureAltcoinEngine(portfolio_path=TEMP_PORTFOLIO_PATH)
    engine.open_position(
        ticker="WICKDOWN",
        name="Wick Down Token",
        entry_price_usd=100.0,
        custom_capital_eur=1000.0,
        entry_date="2024-01-01",
        eur_usd_rate=1.0
    )

    # Barra con High = 102$, Low = 55$ (<= 60$), Close = 65$ (> 60$)
    engine.update_bar(
        ticker="WICKDOWN",
        high_usd=102.0,
        low_usd=55.0,
        close_usd=65.0,
        open_usd=100.0
    )

    signals = engine.evaluate_signals(eur_usd_rate=1.0, today_date="2024-01-05")
    assert len(signals) == 1
    sig = signals[0]
    assert sig["ticker"] == "WICKDOWN"
    assert sig["type"] == "STOP_LOSS"
    assert sig["action"] == "SELL_ALL"
    assert sig["price_usd"] == 60.0  # Stop price riempito


def test_update_bar_time_stop_triggers_on_close_after_30_days():
    """
    Verifica che il Time-Stop valuti il prezzo di Close dopo 30 giorni
    se ne' l'Hard Stop ne' la Milestone 1 sono stati toccati intraday.
    """
    from altcoin_venture_engine import VentureAltcoinEngine

    engine = VentureAltcoinEngine(portfolio_path=TEMP_PORTFOLIO_PATH)
    engine.open_position(
        ticker="SLOWBLEED",
        name="Slow Bleed Token",
        entry_price_usd=100.0,
        custom_capital_eur=1000.0,
        entry_date="2024-01-01",
        eur_usd_rate=1.0,
        entry_btc_price_usd=50000.0
    )

    # Giorno 35: Low = 80$ (> 60$), High = 92$ (< 225$), Close = 85$ (-15%)
    # BTC = 60.000$ (+20%). Alpha = -15% - 20% = -35% < -20%
    engine.update_bar(
        ticker="SLOWBLEED",
        high_usd=92.0,
        low_usd=80.0,
        close_usd=85.0,
        open_usd=88.0
    )

    signals = engine.evaluate_signals(
        eur_usd_rate=1.0,
        btc_current_price_usd=60000.0,
        today_date="2024-02-05"
    )

    assert len(signals) == 1
    sig = signals[0]
    assert sig["ticker"] == "SLOWBLEED"
    assert sig["type"] == "TIME_STOP"
    assert sig["price_usd"] == 85.0  # Esecuzione al Close


def test_process_daily_bar_auto_execute():
    """
    Verifica che process_daily_bar esegua atomicaente aggiornamento barra,
    valutazione segnale ed esecuzione automatica con riaccredito capitale.
    """
    from altcoin_venture_engine import VentureAltcoinEngine

    engine = VentureAltcoinEngine(portfolio_path=TEMP_PORTFOLIO_PATH)
    engine.open_position(
        ticker="ATOMIC",
        name="Atomic Token",
        entry_price_usd=10.0,
        custom_capital_eur=1000.0,
        entry_date="2024-01-01",
        eur_usd_rate=1.0
    )

    # Esegui barra con auto_execute = True
    executed_signals = engine.process_daily_bar(
        ticker="ATOMIC",
        high_usd=25.0,
        low_usd=9.5,
        close_usd=23.0,
        open_usd=10.0,
        today_date="2024-01-10",
        eur_usd_rate=1.0,
        auto_execute=True
    )

    assert len(executed_signals) == 1
    assert executed_signals[0]["type"] == "MILESTONE_1_FREE_RIDE"

    pos = engine.state["positions"]["ATOMIC"]
    assert pos["is_free_ride"] is True
    # Capitale iniziale interamente recuperato in cassa
    assert engine.state["cash_available_eur"] == 10000.0

