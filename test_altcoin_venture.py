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

    res = screen_venture_candidates(crypto_dict, btc_series, cross_kraken_futures=False)
    assert "altcoin_breadth_pct" in res
    assert "altcoin_breadth_regime" in res
    assert res["altcoin_breadth_pct"] == 100.0
    assert "IPERESTENSO" in res["altcoin_breadth_regime"]

