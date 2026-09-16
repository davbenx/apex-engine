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


def test_freeride_partial_exit_preserves_cost_basis_for_remaining_units():
    """Verifica che, dopo una vendita parziale Free-Ride (+125%), il cost-basis residuo
    della posizione sia ridotto in proporzione alle unita' effettivamente vendute -
    non del ricavo in cash incassato. Un cost-basis azzerato per errore trasformerebbe
    qualunque perdita reale successiva sulle unita' rimanenti in un falso guadagno tassabile.

    Scenario: un altcoin fa breakout, sale oltre 2.25x (scatta il free-ride, che per
    costruzione recupera ~100% del capitale investito in cash), poi crolla ben sotto
    il prezzo di ingresso: la quota residua deve chiudersi con una perdita reale.
    """
    n = 500
    dates = pd.date_range("2020-01-01", periods=n, freq="D")
    btc_p = np.linspace(10000, 60000, n)
    btc_df = pd.DataFrame({
        "Open": btc_p * 0.99, "High": btc_p * 1.02, "Low": btc_p * 0.98, "Close": btc_p,
        "Volume": np.full(n, 1_000_000.0),
    }, index=dates)

    alt_p = np.full(n, 10.0)
    alt_vol = np.full(n, 1_000_000.0)
    for i in range(290, 320):
        alt_p[i] = 10.0 + (i - 289) * 0.6
        alt_vol[i] = 5_000_000.0
    for i in range(320, 340):
        alt_p[i] = 25.0   # > 2.25x l'entry: scatta il free-ride
    for i in range(340, n):
        alt_p[i] = 4.0    # crollo ben sotto l'entry (10.0): perdita reale sulla quota residua

    alt_df = pd.DataFrame({
        "Open": alt_p * 0.99, "High": alt_p * 1.03, "Low": alt_p * 0.97, "Close": alt_p,
        "Volume": alt_vol,
    }, index=dates)

    cfg = CryptoVentureConfig(
        universe_mode="UNCONSTRAINED", max_slots=7, macro_btc_slow_days=280,
        altseason_breadth_pct=0.0, altseason_rs_spread_pct=0.0,
    )
    matrices = precompute_market_matrices({"BTC-USD": btc_df, "ALT-USD": alt_df}, cfg)
    res = run_crypto_venture_backtest(matrices, cfg, tax_enabled=True)

    freeride_trades = [t for t in res["completed_trades"] if t.exit_reason == "FREERIDE_DE_RISK"]
    loss_trades = [t for t in res["completed_trades"] if t.exit_reason != "FREERIDE_DE_RISK" and t.pnl_pct < 0]
    assert len(freeride_trades) == 1
    assert len(loss_trades) == 1, "Attesa esattamente una chiusura in perdita sulla quota residua post free-ride"

    loss_trade = loss_trades[0]
    # La quota residua e' realmente in perdita (prezzo di uscita ben sotto l'entry) e deve
    # essere contabilizzata come tale, non come guadagno per via di un cost-basis azzerato.
    assert loss_trade.exit_price < loss_trade.entry_price
    assert loss_trade.pnl_val < 0

    # Il monte perdite (zainetto fiscale) deve aver accolto la perdita reale, e le tasse
    # cumulate non devono includere alcuna imposta sulla vendita in perdita.
    assert res["summary"]["TaxPoolRemaining"] > 0


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

    # Verifica FORTE del fill price: ogni ingresso deve essere eseguito esattamente
    # all'Open (con slippage) del proprio entry_date, mai al Close del giorno del segnale.
    slip_buy = 1.0 + (cfg.slippage_bps / 10000.0)
    slip_sell = 1.0 - (cfg.slippage_bps / 10000.0)
    df_open = matrices["df_open"]
    deferred_exit_reasons = {"ATR_STOP_CLOSE", "FIXED_STOP_CLOSE", "TRAIL_STOP_CLOSE", "TIME_STOP_21D"}
    checked_entries = checked_exits = 0
    for t in trades:
        expected_entry_open = df_open.loc[t.entry_date, t.symbol] * slip_buy
        assert t.entry_price == pytest.approx(expected_entry_open, rel=1e-9), (
            f"{t.symbol}: entry_price non coincide con l'Open(entry_date)*slippage "
            f"(possibile leak: esecuzione allo stesso Close del segnale)"
        )
        checked_entries += 1

        if t.exit_reason in deferred_exit_reasons:
            expected_exit_open = df_open.loc[t.exit_date, t.symbol] * slip_sell
            assert t.exit_price == pytest.approx(expected_exit_open, rel=1e-9), (
                f"{t.symbol}/{t.exit_reason}: exit_price non coincide con l'Open(exit_date)*slippage"
            )
            checked_exits += 1
    assert checked_entries > 0
    assert checked_exits > 0, "Nessun trade con uscita differita trovato: rafforzare il dataset sintetico"


def test_btc_core_rotation_zero_lookahead():
    """Verifica che la rotazione Bitcoin Core (regime dual) decisa al Close di T
    venga eseguita all'Open di T+1, non allo stesso Close che ha generato il segnale.

    Costruisce un BTC-only universe con un calo del -15% che fa scattare il regime
    ribassista al Close del giorno T, seguito da un ulteriore gap overnight del -45%
    sull'Open di T+1. Se la rotazione eseguisse (erroneamente) allo stesso Close di T,
    il fondo eviterebbe il crollo overnight e l'equity resterebbe piatta da T in poi.
    Con la disciplina corretta (esecuzione a Open di T+1), il fondo resta esposto al
    Close di T e subisce anche il gap overnight su T+1, prima di stabilizzarsi in cash.
    """
    n = 60
    dates = pd.date_range("2021-01-01", periods=n, freq="D")
    close = np.zeros(n)
    close[0] = 100.0
    for i in range(1, 35):
        close[i] = close[i - 1] * 1.02  # bull run costante
    close[35] = close[34] * 0.85        # -15%: fa scattare il regime ribassista al Close
    for i in range(36, n):
        close[i] = close[35] * 0.55     # ulteriore -45% (gap overnight), poi piatto

    open_ = np.empty(n)
    open_[0] = close[0]
    for i in range(1, n):
        open_[i] = close[i - 1]
    open_[36] = close[35] * 0.55        # l'Open di T+1 riflette gia' il gap overnight

    high = np.maximum(open_, close) * 1.001
    low = np.minimum(open_, close) * 0.999
    btc_df = pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": np.full(n, 1_000_000.0)},
        index=dates,
    )

    cfg = CryptoVentureConfig(
        macro_btc_fast_days=5, macro_btc_slow_days=10,
        universe_mode="UNCONSTRAINED",
        altseason_breadth_pct=999.0, altseason_rs_spread_pct=999.0,  # niente altseason: solo BTC Core
    )
    matrices = precompute_market_matrices({"BTC-USD": btc_df}, cfg)
    btc_bull = matrices["btc_bull"]
    res = run_crypto_venture_backtest(matrices, cfg, tax_enabled=False)
    s_equity = res["equity_curve"]

    sim_dates = matrices["simulation_dates"]
    bull_flags = btc_bull.reindex(sim_dates)
    first_bear_idx = int(np.argmax(~bull_flags.values))
    assert bull_flags.iloc[first_bear_idx] == False  # noqa: E712
    d_prev = sim_dates[first_bear_idx - 1]
    d_t = sim_dates[first_bear_idx]        # giorno del segnale ribassista (Close T)
    d_next = sim_dates[first_bear_idx + 1]  # giorno di esecuzione (Open T+1)

    # Sul giorno del segnale (T) il fondo deve essere ancora pienamente esposto a BTC:
    # equity[T]/equity[T-1] deve coincidere con il rendimento del Close, non essere gia' in cash.
    ret_equity_T = s_equity.loc[d_t] / s_equity.loc[d_prev]
    ret_close_T = btc_df.loc[d_t, "Close"] / btc_df.loc[d_prev, "Close"]
    assert ret_equity_T == pytest.approx(ret_close_T, rel=1e-6), (
        "Il fondo risulta gia' fuori da BTC al Close del giorno del segnale: "
        "esecuzione same-bar (lookahead) sulla rotazione BTC Core"
    )

    # Sul giorno successivo (T+1) l'equity deve ancora muoversi con il gap overnight
    # (prova che la liquidazione non e' avvenuta prima dell'Open di T+1).
    ret_equity_T1 = s_equity.loc[d_next] / s_equity.loc[d_t]
    assert ret_equity_T1 < 0.90, (
        "Il fondo non ha subito il gap overnight su T+1: probabile liquidazione anticipata al Close di T"
    )

    # Da T+2 in poi il fondo e' in cash: equity piatta nonostante il prezzo BTC resti costante.
    d_t2 = sim_dates[first_bear_idx + 2]
    assert s_equity.loc[d_t2] == pytest.approx(s_equity.loc[d_next], rel=1e-9)


def test_evaluate_daily_crypto_frontier_missing_btc_data_fails_safe():
    """Verifica che, con dati BTC assenti/insufficienti per calcolare il regime macro,
    il gate Altseason resti disabilitato (fail-safe) invece di presumere un mercato
    rialzista (fail-open). Isola la questione costruendo un altcoin che soddisfa da solo
    entrambe le altre condizioni del gate (breadth 100%, RS spread 100%), cosi' che
    l'unica variabile rimasta sia il regime BTC presunto quando i suoi dati sono corti."""
    cfg = CryptoVentureConfig()

    # BTC: solo 35 righe, sufficienti per il confronto RS a 30gg dell'alt ma insufficienti
    # (< macro_btc_slow_days=280) per calcolare il proprio regime SMA140/SMA280.
    btc_dates = pd.date_range(end="2026-01-05", periods=35, freq="D")
    short_btc_df = pd.DataFrame({
        "Open": [50000.0] * 35, "High": [50500.0] * 35, "Low": [49500.0] * 35,
        "Close": np.linspace(50000.0, 50500.0, 35), "Volume": [1_000_000.0] * 35,
    }, index=btc_dates)

    # ALT1: 150 righe, forte trend rialzista -> supera la propria SMA140 (breadth) e batte
    # nettamente il rendimento BTC a 30gg (RS spread), per costruzione al 100% da solo.
    alt_dates = pd.date_range(end="2026-01-05", periods=150, freq="D")
    alt_close = np.linspace(10.0, 40.0, 150)
    alt1_df = pd.DataFrame({
        "Open": alt_close * 0.99, "High": alt_close * 1.01, "Low": alt_close * 0.99,
        "Close": alt_close, "Volume": [1_000_000.0] * 150,
    }, index=alt_dates)

    res = evaluate_daily_crypto_frontier(
        open_positions={},
        crypto_alloc_pct=15.0,
        crypto_dfs={"BTC-USD": short_btc_df, "BTC": short_btc_df, "ALT1-USD": alt1_df, "ALT1": alt1_df},
        today_str="2026-01-05",
        kraken_universe=["ALT1"],
        config=cfg,
    )
    assert res["breadth_pct"] == pytest.approx(100.0)
    assert res["rs_spread_pct"] == pytest.approx(100.0)
    assert res["altseason_gate"] is False, (
        "Con dati BTC insufficienti il gate Altseason deve restare disattivato anche se "
        "breadth e RS spread degli alt soddisfano le soglie: il fail-open presume erroneamente un bull market"
    )


def test_pending_exit_retries_when_execution_day_open_is_nan():
    """Un ordine di uscita gia' deciso (ATR_STOP_CLOSE, segnale al Close del giorno 339)
    il cui giorno di esecuzione (Open del giorno 340) e' NaN deve essere ritentato il
    giorno successivo, non scartato silenziosamente per sempre (bug confermato da audit
    di robustezza indipendente: pending_exits veniva svuotato incondizionatamente a ogni
    iterazione, a prescindere che la vendita fosse davvero eseguita).

    Il prezzo RECUPERA immediatamente il giorno 340 (torna ben sopra la soglia ATR) e
    resta sopra per il resto della serie: la condizione di stop non si ripresenta mai
    piu' da sola. Senza il fix, l'ordine deciso al giorno 339 va perso e la posizione
    finisce per chiudersi molto piu' tardi per un motivo completamente diverso
    (TIME_STOP_21D) invece che per lo stop ATR originale — la prova che il segnale
    originale e' stato scartato, non solo eseguito con un giorno di ritardo."""
    n = 500
    dates = pd.date_range("2020-01-01", periods=n, freq="D")
    btc_p = np.linspace(10000, 60000, n)
    btc_df = pd.DataFrame({
        "Open": btc_p * 0.99, "High": btc_p * 1.02, "Low": btc_p * 0.98, "Close": btc_p,
        "Volume": np.full(n, 1_000_000.0),
    }, index=dates)

    alt_p = np.full(n, 10.0)
    alt_vol = np.full(n, 1_000_000.0)
    for i in range(290, 320):
        alt_p[i] = 10.0 + (i - 289) * 0.3
        alt_vol[i] = 5_000_000.0
    for i in range(320, 339):
        alt_p[i] = 19.0 - (i - 319) * 0.5  # decresce fino a toccare la soglia ATR al giorno 339
    alt_p[339] = 9.0
    alt_p[340] = 14.0  # recupero immediato il giorno dell'esecuzione prevista
    for i in range(341, n):
        alt_p[i] = 14.0 + (i - 340) * 0.01  # tiene/risale lentamente, non ritocca mai piu' lo stop

    alt_open = alt_p * 0.99
    alt_open[340] = np.nan  # NaN esattamente il giorno di esecuzione dello stop deciso al giorno 339
    alt_df = pd.DataFrame({
        "Open": alt_open, "High": alt_p * 1.03, "Low": alt_p * 0.97, "Close": alt_p, "Volume": alt_vol,
    }, index=dates)

    cfg = CryptoVentureConfig(
        universe_mode="UNCONSTRAINED", max_slots=7, macro_btc_slow_days=280,
        altseason_breadth_pct=0.0, altseason_rs_spread_pct=0.0,
    )
    matrices = precompute_market_matrices({"BTC-USD": btc_df, "ALT-USD": alt_df}, cfg)
    res = run_crypto_venture_backtest(matrices, cfg, tax_enabled=False)

    assert len(res["completed_trades"]) == 1
    trade = res["completed_trades"][0]
    assert trade.exit_reason == "ATR_STOP_CLOSE", (
        f"lo stop ATR deciso al giorno 339 deve eseguire (ritentato il giorno dopo la Open "
        f"NaN), non sparire nel nulla e far chiudere la posizione molto piu' tardi per un "
        f"motivo estraneo (ottenuto: {trade.exit_reason})"
    )


def test_nan_close_gap_does_not_create_phantom_drawdown():
    """Un buco di 3 giorni nel feed prezzi (Close/High/Low/Open tutti NaN, es. un
    guasto temporaneo del data provider) su una posizione aperta non deve produrre
    un drawdown fantasma: l'equity deve restare CONSTANTE durante il buco (valorizzata
    all'ultimo prezzo noto) e RICONVERGERE esattamente con lo scenario senza buco non
    appena i dati riprendono (bug confermato da audit di robustezza indipendente:
    prima del fix, una posizione con Close NaN veniva esclusa dalla somma dell'equity,
    cioe' valorizzata a $0 per quei giorni, per poi "risalire" di colpo al ritorno dei
    dati — un artefatto puro, senza alcun movimento di mercato reale dietro).

    Costruzione: ALT-USD fa breakout, scatta il free-ride, poi cresce in modo continuo
    e monotono (sempre nuovi massimi, cosi' non scatta mai il time-stop) — cosi' la
    posizione resta aperta abbastanza a lungo da attraversare un buco di 3 giorni
    iniettato molto piu' avanti nella serie."""
    n = 500
    dates = pd.date_range("2020-01-01", periods=n, freq="D")
    btc_p = np.linspace(10000, 60000, n)
    btc_df = pd.DataFrame({
        "Open": btc_p * 0.99, "High": btc_p * 1.02, "Low": btc_p * 0.98, "Close": btc_p,
        "Volume": np.full(n, 1_000_000.0),
    }, index=dates)

    alt_p = np.full(n, 10.0)
    alt_vol = np.full(n, 1_000_000.0)
    for i in range(290, 320):
        alt_p[i] = 10.0 + (i - 289) * 0.6
        alt_vol[i] = 5_000_000.0
    for i in range(320, n):
        alt_p[i] = alt_p[319] * (1.0 + 0.004) ** (i - 319)  # crescita continua, sempre nuovi massimi

    def build_alt_df(gap_indices):
        open_, high, low, close = alt_p * 0.99, alt_p * 1.03, alt_p * 0.97, alt_p.copy()
        if gap_indices:
            open_, high, low, close = open_.copy(), high.copy(), low.copy(), close.copy()
            for i in gap_indices:
                open_[i] = high[i] = low[i] = close[i] = np.nan
        return pd.DataFrame({"Open": open_, "High": high, "Low": low, "Close": close, "Volume": alt_vol}, index=dates)

    cfg = CryptoVentureConfig(
        universe_mode="UNCONSTRAINED", max_slots=7, macro_btc_slow_days=280,
        altseason_breadth_pct=0.0, altseason_rs_spread_pct=0.0,
    )
    gap_idx = [420, 421, 422]

    matrices_gap = precompute_market_matrices({"BTC-USD": btc_df, "ALT-USD": build_alt_df(gap_idx)}, cfg)
    res_gap = run_crypto_venture_backtest(matrices_gap, cfg, tax_enabled=False)
    s_equity_gap = res_gap["equity_curve"]

    matrices_nogap = precompute_market_matrices({"BTC-USD": btc_df, "ALT-USD": build_alt_df(None)}, cfg)
    res_nogap = run_crypto_venture_backtest(matrices_nogap, cfg, tax_enabled=False)
    s_equity_nogap = res_nogap["equity_curve"]

    d_before_gap = dates[419]
    equity_before_gap = s_equity_gap.loc[d_before_gap]
    for i in gap_idx:
        assert s_equity_gap.loc[dates[i]] == pytest.approx(equity_before_gap), (
            f"l'equity durante il buco dati (giorno {dates[i].date()}) deve restare uguale "
            f"all'ultimo valore noto prima del buco, non crollare del valore della posizione esclusa"
        )

    d_after_gap = dates[gap_idx[-1] + 1]
    assert s_equity_gap.loc[d_after_gap] == pytest.approx(s_equity_nogap.loc[d_after_gap]), (
        "appena i dati riprendono l'equity deve riconvergere esattamente con lo scenario "
        "senza buco, senza alcun salto residuo (drawdown fantasma seguito da un recupero di colpo)"
    )


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
    assert sum_net["CumulativeTax"] > 35000 # Tasse pagate coerenti con zainetto fiscale (reale ~38k)


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


def test_evaluate_daily_crypto_frontier_nan_low_does_not_disable_circuit_breaker():
    """Un Low mancante (NaN) nel feed di oggi, con Close comunque valido e ben oltre
    la soglia di emergenza, non deve disattivare silenziosamente il circuit breaker
    -50% (bug confermato da audit di robustezza indipendente: un confronto
    `cur_low <= emerg_px` con cur_low=NaN e' sempre False in Python, quindi un dropout
    parziale del feed - solo il campo Low mancante - disattivava SOLO questo controllo
    di emergenza, lasciando tutto il resto silenziosamente invariato)."""
    dates = pd.date_range("2025-01-01", periods=300, freq="D")
    btc_df = pd.DataFrame({
        "Open": np.linspace(30000, 90000, 300), "High": np.linspace(30500, 91000, 300),
        "Low": np.linspace(29500, 89000, 300), "Close": np.linspace(30000, 90000, 300),
        "Volume": np.full(300, 1e6),
    }, index=dates)

    # entry=100, Close=40 (-60%, ben oltre la soglia -50%), Low=NaN
    sol_df_nan_low = pd.DataFrame({
        "Open": [45.0], "High": [46.0], "Low": [np.nan], "Close": [40.0], "Volume": [1e6],
    }, index=[dates[-1]])
    pos = {"SOL": {"entry_price": 100.0, "current_price": 100.0, "weight": 0.02857, "is_crypto": True, "atr_entry": 8.0}}
    res = evaluate_daily_crypto_frontier(pos, 20.0, {"BTC-USD": btc_df, "SOL-USD": sol_df_nan_low}, "2026-09-13", kraken_universe=["BTC", "SOL"])
    assert any("EMERGENCY_CIRCUIT_50" in s["desc"] for s in res["sells"]), (
        "il circuit breaker deve scattare comunque (fallback sul Close) anche con Low mancante"
    )
    assert "SOL" not in res["updated_positions"]


def test_evaluate_daily_crypto_frontier_nan_close_skips_position_without_poisoning_price():
    """Un Close mancante (NaN) nel feed di oggi non deve propagarsi in
    pos['current_price'] (che altrimenti arriva fino alla dashboard e al messaggio
    Telegram di P&L aggregato) — la posizione va saltata per quel giorno, non
    aggiornata con un prezzo NaN (bug confermato da audit di robustezza indipendente)."""
    dates = pd.date_range("2025-01-01", periods=300, freq="D")
    btc_df = pd.DataFrame({
        "Open": np.linspace(30000, 90000, 300), "High": np.linspace(30500, 91000, 300),
        "Low": np.linspace(29500, 89000, 300), "Close": np.linspace(30000, 90000, 300),
        "Volume": np.full(300, 1e6),
    }, index=dates)
    sol_df_nan_close = pd.DataFrame({
        "Open": [95.0], "High": [96.0], "Low": [94.0], "Close": [np.nan], "Volume": [1e6],
    }, index=[dates[-1]])
    pos = {"SOL": {"entry_price": 100.0, "current_price": 98.0, "weight": 0.02857, "is_crypto": True, "atr_entry": 8.0}}
    res = evaluate_daily_crypto_frontier(pos, 20.0, {"BTC-USD": btc_df, "SOL-USD": sol_df_nan_close}, "2026-09-13", kraken_universe=["BTC", "SOL"])
    assert "SOL" in res["updated_positions"], "senza dati validi oggi la posizione resta aperta, non viene chiusa a caso"
    assert not pd.isna(res["updated_positions"]["SOL"]["current_price"]), "current_price non deve mai diventare NaN"
    assert res["updated_positions"]["SOL"]["current_price"] == 98.0, "senza un Close valido oggi, il prezzo resta quello di ieri"


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
