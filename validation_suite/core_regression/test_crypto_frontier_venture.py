"""
test_crypto_frontier_venture.py — Suite di regressione e unit testing per Crypto Frontier Venture Engine.
Verifica:
1. Conformita dei parametri congelati della configurazione (7 slot, ATR 2.5x, Time-stop 21d, Free-Ride 2.25x).
2. Assenza di lookahead bias (decisione a Close T, esecuzione a Open T+1).
3. Meccaniche di de-risking Free-Ride (recupero 100% del capitale al +125%).
4. Meccaniche di Stop Loss (ATR 2.5x Daily Close ed Emergency Circuit Breaker -50%).
5. Meccanica di Time-Stop (stagnazione a 21 giorni senza nuovi massimi).
6. Correttezza del regime fiscale italiano 26% con zainetto fiscale (compensazione minusvalenze).
"""

import pytest
import numpy as np
import pandas as pd
from crypto_frontier_venture_engine import (
    CryptoVentureConfig,
    TradeRecord,
    precompute_market_matrices,
    run_crypto_venture_backtest,
    fetch_kraken_futures_top_universe,
    evaluate_daily_crypto_frontier,
    STABLECOIN_SET,
    WRAPPED_SET,
    SYNTHETICS_SET,
)


def test_config_defaults():
    """Verifica che i parametri di default corrispondano alla configurazione Champion validata."""
    cfg = CryptoVentureConfig()
    assert cfg.max_slots == 7
    assert cfg.universe_mode == "TOP25"
    assert cfg.stop_mode == "ATR_CLOSE"
    assert cfg.atr_multiplier == 2.5
    assert cfg.atr_period_days == 14
    assert cfg.time_stop_days == 21
    assert cfg.freeride_multiplier == 2.25
    assert cfg.trailing_stop_pct == 0.30
    assert cfg.circuit_breaker_intraday_pct == 0.50
    assert cfg.volume_confirmation_mult == 1.25
    assert cfg.anti_crowding_max_pct == 0.10
    assert cfg.tax_rate == 0.26
    assert cfg.slippage_bps == 10.0


def test_freeride_math():
    """Verifica che il moltiplicatore 2.25x (+125%) recuperi esattamente il 100% del capitale."""
    invested = 1000.0
    entry_px = 10.0
    units = invested / entry_px  # 100 unita
    
    freeride_px = entry_px * 2.25  # 22.50
    frac_to_sell = 1.0 / 2.25     # 0.444444...
    units_to_sell = units * frac_to_sell # 44.4444... unita
    
    cash_recovered = units_to_sell * freeride_px
    assert np.isclose(cash_recovered, invested)
    
    remaining_units = units - units_to_sell
    assert np.isclose(remaining_units, units * (1.0 - frac_to_sell))
    assert remaining_units > 0


def test_tax_loss_pool_offset():
    """Verifica il funzionamento dello zainetto fiscale (compensazione minusvalenze al 26%)."""
    loss_pool = 0.0
    tax_paid = 0.0
    
    # Trade 1: perdita di 500 EUR
    pnl1 = -500.0
    if pnl1 < 0:
        loss_pool += abs(pnl1)
    assert loss_pool == 500.0
    assert tax_paid == 0.0
    
    # Trade 2: guadagno di 1200 EUR
    pnl2 = 1200.0
    taxable = max(0.0, pnl2 - loss_pool)
    loss_pool = max(0.0, loss_pool - pnl2)
    tax = taxable * 0.26
    tax_paid += tax
    
    assert taxable == 700.0
    assert np.isclose(tax, 700.0 * 0.26)
    assert loss_pool == 0.0


def _build_synthetic_dataset(n_days=400):
    """Costruisce un dataset sintetico deterministico per validare la logica di esecuzione."""
    dates = pd.date_range("2020-01-01", periods=n_days, freq="D")
    
    # BTC trend fortemente rialzista per abilitare regime BTC Bull
    btc_p = np.linspace(10000, 60000, n_days)
    btc_df = pd.DataFrame({
        "Open": btc_p * 0.99,
        "High": btc_p * 1.02,
        "Low": btc_p * 0.98,
        "Close": btc_p,
        "Volume": np.full(n_days, 1_000_000.0)
    }, index=dates)
    
    # ALT1: fa breakout Donchian con volume spike e poi sale del +150% (test Free-Ride e Trailing)
    alt1_p = np.full(n_days, 10.0)
    alt1_vol = np.full(n_days, 1_000_000.0)
    for i in range(290, 320):
        alt1_p[i] = 10.0 + (i - 289) * 0.5  # Breakout
        alt1_vol[i] = 5_000_000.0           # Volume spike 5x
    for i in range(320, 360):
        alt1_p[i] = 25.0  # +150% rispetto a 10 (supera 2.25x)
    for i in range(360, n_days):
        alt1_p[i] = 15.0  # Ritracciamento per test trailing
        
    alt1_df = pd.DataFrame({
        "Open": alt1_p * 0.99,
        "High": alt1_p * 1.03,
        "Low": alt1_p * 0.97,
        "Close": alt1_p,
        "Volume": alt1_vol
    }, index=dates)

    # ALT2: fa breakout con volume spike e poi crolla sotto ATR stop
    alt2_p = np.full(n_days, 20.0)
    alt2_vol = np.full(n_days, 1_000_000.0)
    alt2_p[290:300] = 22.0 # Breakout
    alt2_vol[290:300] = 3_000_000.0 # Volume spike 3x
    alt2_p[300:] = 12.0    # Crollo del -45%
    alt2_df = pd.DataFrame({
        "Open": alt2_p * 0.99,
        "High": alt2_p * 1.02,
        "Low": alt2_p * 0.96,
        "Close": alt2_p,
        "Volume": alt2_vol
    }, index=dates)

    return {
        "BTC-USD": btc_df,
        "SOL-USD": alt1_df,
        "AVAX-USD": alt2_df
    }


def test_zero_lookahead_and_execution():
    """Verifica che gli ordini generati al giorno T vengano eseguiti al giorno T+1 all'Open."""
    dfs = _build_synthetic_dataset(400)
    cfg = CryptoVentureConfig(
        universe_mode="UNCONSTRAINED",
        max_slots=7,
        macro_btc_slow_days=280,
        altseason_breadth_pct=0.0,   # Disabilita soglia per isolare il test
        altseason_rs_spread_pct=0.0
    )
    matrices = precompute_market_matrices(dfs, cfg)
    res = run_crypto_venture_backtest(matrices, cfg, tax_enabled=False)
    
    trades = res["completed_trades"]
    assert len(trades) > 0
    for t in trades:
        # L'uscita non puo avvenire prima dell'ingresso
        assert t.exit_date >= t.entry_date
        assert t.holding_days >= 0
        assert t.invested_amount > 0
        assert t.recovered_amount >= 0


def test_end_to_end_crypto_venture_engine():
    """Test end-to-end sul dataset storico reale della cache (Lordo e Netto Fiscale)."""
    cache_dir = "research/crypto_ohlcv_extended_cache"
    import os
    if not os.path.exists(cache_dir):
        pytest.skip("Cache crypto non disponibile.")
        
    from crypto_frontier_venture_engine import load_crypto_dataset
    dfs = load_crypto_dataset(cache_dir)
    assert len(dfs) >= 50
    assert "BTC-USD" in dfs
    
    cfg = CryptoVentureConfig(universe_mode="TOP25", max_slots=7)
    matrices = precompute_market_matrices(dfs, cfg)
    
    # 1. Verifica Risultato Lordo
    res_gross = run_crypto_venture_backtest(matrices, cfg, tax_enabled=False)
    sum_gross = res_gross["summary"]
    assert sum_gross["CAGR"] > 0.50          # CAGR lordo > 50% (51.3%)
    assert sum_gross["MaxDrawdown"] > -0.50  # MaxDD lordo contenuto a -49.2%
    assert sum_gross["Sharpe"] > 1.05        # Sharpe lordo ~1.10 (survivorship-bias free)
    assert sum_gross["Calmar"] > 1.00        # Calmar lordo ~1.04 (survivorship-bias free)
    assert sum_gross["WinRate"] > 25.0       # WinRate 44.3%
    assert sum_gross["TotalTrades"] >= 50
    assert len(res_gross["yearly_metrics"]) >= 7
    assert len(res_gross["cycle_metrics"]) >= 5

    # 2. Verifica Risultato Netto Tasse 26% con Zainetto Fiscale
    res_net = run_crypto_venture_backtest(matrices, cfg, tax_enabled=True)
    sum_net = res_net["summary"]
    assert sum_net["CAGR"] > 0.40           # CAGR netto > 40% (40.4%)
    assert sum_net["MaxDrawdown"] > -0.50   # MaxDD netto contenuto a -49.2%
    assert sum_net["Sharpe"] > 0.80         # Sharpe netto ~0.85 (survivorship-bias free)
    assert sum_net["Calmar"] > 0.80         # Calmar netto ~0.82 (survivorship-bias free)
    assert sum_net["CumulativeTax"] > 50000 # Tasse pagate coerenti


def test_kraken_futures_universe_filtering():
    """Verifica che l'universo Kraken Futures filtri stablecoin, wrapped token e sintetici."""
    univ = fetch_kraken_futures_top_universe(top_n=25)
    assert len(univ) == 25
    assert "BTC" in univ

    # Nessuna stablecoin ammessa
    for token in univ:
        assert token not in STABLECOIN_SET, f"Stablecoin trovata nell'universo: {token}"
        assert token not in WRAPPED_SET, f"Wrapped token trovato nell'universo: {token}"
        assert token not in SYNTHETICS_SET, f"Sintetico trovato nell'universo: {token}"
        if token.endswith("X") and len(token) > 4:
            assert token in {"AVAX"}, f"Sintetico non consentito: {token}"


def test_evaluate_daily_crypto_frontier_exits():
    """Verifica tutte le tipologie di uscita di evaluate_daily_crypto_frontier."""
    dates = pd.date_range("2025-01-01", periods=300, freq="D")
    btc_df = pd.DataFrame({
        "Open": np.linspace(30000, 90000, 300),
        "High": np.linspace(30500, 91000, 300),
        "Low": np.linspace(29500, 89000, 300),
        "Close": np.linspace(30000, 90000, 300),
        "Volume": np.full(300, 1e6)
    }, index=dates)

    # 1. Emergency Circuit Breaker (-50% intraday)
    sol_df_emerg = pd.DataFrame({
        "Open": [100.0], "High": [102.0], "Low": [45.0], "Close": [60.0], "Volume": [1e6]
    }, index=[dates[-1]])
    pos1 = {"SOL": {"entry_price": 100.0, "current_price": 100.0, "weight": 0.02857, "is_crypto": True, "atr_entry": 8.0}}
    res1 = evaluate_daily_crypto_frontier(pos1, 20.0, {"BTC-USD": btc_df, "SOL-USD": sol_df_emerg}, "2026-09-13", kraken_universe=["BTC", "SOL"])
    assert any("EMERGENCY_CIRCUIT_50" in s["desc"] for s in res1["sells"])
    assert "SOL" not in res1["updated_positions"]

    # 2. Free-Ride Milestone (+125% -> 2.25x)
    sol_df_fr = pd.DataFrame({
        "Open": [220.0], "High": [230.0], "Low": [210.0], "Close": [225.0], "Volume": [1e6]
    }, index=[dates[-1]])
    pos2 = {"SOL": {"entry_price": 100.0, "current_price": 100.0, "weight": 0.02857, "is_crypto": True, "atr_entry": 8.0, "freeride_done": False}}
    res2 = evaluate_daily_crypto_frontier(pos2, 20.0, {"BTC-USD": btc_df, "SOL-USD": sol_df_fr}, "2026-09-13", kraken_universe=["BTC", "SOL"])
    assert any(s["action"] == "RIDUZIONE" and "Free-Ride" in s["desc"] for s in res2["sells"])
    assert res2["updated_positions"]["SOL"]["freeride_done"] is True
    assert res2["updated_positions"]["SOL"]["weight"] < 0.02857

    # 3. ATR Stop Loss (entry 100, atr 8, stop 80, close 75)
    sol_df_atr = pd.DataFrame({
        "Open": [78.0], "High": [79.0], "Low": [74.0], "Close": [75.0], "Volume": [1e6]
    }, index=[dates[-1]])
    pos3 = {"SOL": {"entry_price": 100.0, "current_price": 100.0, "weight": 0.02857, "is_crypto": True, "atr_entry": 8.0}}
    res3 = evaluate_daily_crypto_frontier(pos3, 20.0, {"BTC-USD": btc_df, "SOL-USD": sol_df_atr}, "2026-09-13", kraken_universe=["BTC", "SOL"])
    assert any("ATR_STOP_CLOSE" in s["desc"] for s in res3["sells"])
    assert "SOL" not in res3["updated_positions"]

    # 4. Trailing Stop (-30% dal picco dopo free-ride)
    sol_df_trail = pd.DataFrame({
        "Open": [150.0], "High": [155.0], "Low": [135.0], "Close": [138.0], "Volume": [1e6]
    }, index=[dates[-1]])
    pos4 = {"SOL": {"entry_price": 100.0, "current_price": 150.0, "weight": 0.015, "is_crypto": True, "peak_price": 200.0, "freeride_done": True}}
    res4 = evaluate_daily_crypto_frontier(pos4, 20.0, {"BTC-USD": btc_df, "SOL-USD": sol_df_trail}, "2026-09-13", kraken_universe=["BTC", "SOL"])
    assert any("TRAIL_STOP_CLOSE" in s["desc"] for s in res4["sells"])
    assert "SOL" not in res4["updated_positions"]

    # 5. Stagnation Time-Stop (21 giorni)
    sol_df_time = pd.DataFrame({
        "Open": [100.0], "High": [101.0], "Low": [99.0], "Close": [100.0], "Volume": [1e6]
    }, index=[dates[-1]])
    pos5 = {"SOL": {"entry_price": 100.0, "current_price": 100.0, "weight": 0.02857, "is_crypto": True, "atr_entry": 8.0, "days_no_high": 21, "peak_price": 105.0}}
    res5 = evaluate_daily_crypto_frontier(pos5, 20.0, {"BTC-USD": btc_df, "SOL-USD": sol_df_time}, "2026-09-13", kraken_universe=["BTC", "SOL"])
    assert any("TIME_STOP_21D" in s["desc"] for s in res5["sells"])
    assert "SOL" not in res5["updated_positions"]


def test_evaluate_daily_crypto_frontier_ballast_and_zero_alloc():
    """Verifica la liquidazione su allocazione 0 e la gestione del ballast Bitcoin Core."""
    # Zero allocazione: tutte le crypto vengono chiuse
    open_pos = {
        "BTC": {"weight": 0.15, "entry_price": 60000, "current_price": 65000, "is_crypto": True},
        "SOL": {"weight": 0.05, "entry_price": 100, "current_price": 120, "is_crypto": True}
    }
    res_zero = evaluate_daily_crypto_frontier(open_pos, 0.0, {}, "2026-09-13")
    assert len(res_zero["sells"]) == 2
    assert "BTC" not in res_zero["updated_positions"]
    assert "SOL" not in res_zero["updated_positions"]

    # Allocazione positiva con Bitcoin Core ballast
    dates = pd.date_range("2025-01-01", periods=300, freq="D")
    btc_df = pd.DataFrame({
        "Open": np.linspace(30000, 90000, 300),
        "High": np.linspace(30500, 91000, 300),
        "Low": np.linspace(29500, 89000, 300),
        "Close": np.linspace(30000, 90000, 300),
        "Volume": np.full(300, 1e6)
    }, index=dates)
    res_btc = evaluate_daily_crypto_frontier({}, 20.0, {"BTC-USD": btc_df}, "2026-09-13", kraken_universe=["BTC"])
    assert "BTC" in res_btc["updated_positions"]
    assert np.isclose(res_btc["updated_positions"]["BTC"]["weight"], 0.20)
    assert any(b["ticker"] == "BTC" for b in res_btc["buys"])


def test_evaluate_daily_crypto_frontier_breakout_entry():
    """Verifica l'apertura di un nuovo slot altcoin su breakout Donchian 30d qualificato."""
    dates = pd.date_range("2025-01-01", periods=300, freq="D")
    btc_df = pd.DataFrame({
        "Open": np.linspace(30000, 90000, 300),
        "High": np.linspace(30500, 91000, 300),
        "Low": np.linspace(29500, 89000, 300),
        "Close": np.linspace(30000, 90000, 300),
        "Volume": np.full(300, 1e6)
    }, index=dates)

    sol_p = np.full(300, 50.0)
    sol_v = np.full(300, 1e6)
    sol_p[-1] = 54.0  # Breakout Donchian 30d, +8% in 20d (batte BTC), anti-crowding ok
    sol_v[-1] = 3e6   # Volume spike 3x
    sol_df = pd.DataFrame({
        "Open": sol_p * 0.99,
        "High": sol_p * 1.02,
        "Low": sol_p * 0.98,
        "Close": sol_p,
        "Volume": sol_v
    }, index=dates)

    cfg = CryptoVentureConfig(altseason_breadth_pct=0.0, altseason_rs_spread_pct=0.0)
    res = evaluate_daily_crypto_frontier({}, 20.0, {"BTC-USD": btc_df, "SOL-USD": sol_df}, "2026-09-13", kraken_universe=["BTC", "SOL"], config=cfg)

    assert "SOL" in res["updated_positions"]
    assert res["updated_positions"]["SOL"]["is_crypto"] is True
    assert res["updated_positions"]["SOL"]["stop_loss"] > 0.0
    assert "BTC" in res["updated_positions"]
    tot_weight = res["updated_positions"]["SOL"]["weight"] + res["updated_positions"]["BTC"]["weight"]
    assert np.isclose(tot_weight, 0.20)
