"""
test_apex_v2_engine.py — Test su dati sintetici a risultato noto per apex_v2_engine.py,
prima di collegarlo a backend.py (stessa disciplina usata in trading/tests/test_quantlab.py).
"""
import datetime
import numpy as np
import pandas as pd

from apex_v2_engine import compute_v2_macro_signal, select_low_vol_basket, is_quarter_end_month


def make_trend_df(n_days=400, daily_drift=0.002, daily_vol=0.01, start=100.0, seed=1):
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2024-01-01", periods=n_days, freq="D")
    close = start * np.exp(np.cumsum(rng.normal(daily_drift, daily_vol, n_days)))
    df = pd.DataFrame({
        "Open": close, "High": close * 1.005, "Low": close * 0.995, "Close": close
    }, index=dates)
    return df


def make_flat_df(n_days=400, level=100.0):
    dates = pd.date_range("2024-01-01", periods=n_days, freq="D")
    close = np.full(n_days, level)
    return pd.DataFrame({"Open": close, "High": close, "Low": close, "Close": close}, index=dates)


def test_uptrend_asset_becomes_active():
    b_data = {
        "SPY": make_trend_df(daily_drift=0.003, seed=1),
        "IEF": make_flat_df(),
        "GLD": make_flat_df(),
        "BTC-USD": make_flat_df(),
    }
    alloc, state, debug = compute_v2_macro_signal(b_data, prev_hysteresis_state=None)
    assert state["Equities"] is True, "un asset in trend rialzista netto deve risultare attivo"
    assert alloc["Equities"] > 0
    assert abs(sum(alloc.values()) - 100.0) < 0.01, "i pesi devono sommare a 100%"


def test_flat_asset_stays_inactive_without_prior_state():
    b_data = {
        "SPY": make_flat_df(),
        "IEF": make_flat_df(),
        "GLD": make_flat_df(),
        "BTC-USD": make_flat_df(),
    }
    alloc, state, debug = compute_v2_macro_signal(b_data, prev_hysteresis_state=None)
    # prezzo esattamente sulla MA (distanza=0): con isteresi, un asset MAI attivo prima
    # richiede distanza > +2% per attivarsi, quindi resta inattivo
    assert state["Equities"] is False
    assert alloc["Cash"] == 100.0


def test_hysteresis_keeps_previously_active_asset_on_small_dip():
    # Asset in forte salita, poi leggero calo (distanza tra -2% e 0) — deve restare attivo
    # se era già attivo, grazie all'isteresi
    dates = pd.date_range("2024-01-01", periods=400, freq="D")
    rng = np.random.default_rng(2)
    base = 100.0 * np.exp(np.cumsum(rng.normal(0.003, 0.01, 380)))
    tail = base[-1] * np.array([0.995] * 20)  # piccolo calo finale, dentro la banda di isteresi
    close = np.concatenate([base, tail])
    df = pd.DataFrame({"Open": close, "High": close, "Low": close, "Close": close}, index=dates)
    b_data = {"SPY": df, "IEF": make_flat_df(), "GLD": make_flat_df(), "BTC-USD": make_flat_df()}

    alloc1, state1, _ = compute_v2_macro_signal(b_data, prev_hysteresis_state=None)
    assert state1["Equities"] is True

    alloc2, state2, _ = compute_v2_macro_signal(b_data, prev_hysteresis_state=state1)
    assert state2["Equities"] is True, "isteresi: non deve disattivarsi per un calo minore del 2%"


def test_vol_target_scales_down_high_vol_portfolio():
    high_vol = make_trend_df(daily_drift=0.004, daily_vol=0.04, seed=3)  # asset molto volatile e in trend
    b_data = {"SPY": high_vol, "IEF": make_flat_df(), "GLD": make_flat_df(), "BTC-USD": make_flat_df()}
    alloc, state, debug = compute_v2_macro_signal(b_data, prev_hysteresis_state=None)
    assert debug["_vol_target"]["fattore_scala"] < 1.0, "un portafoglio ad alta volatilita' deve essere scalato verso il basso"
    assert alloc["Cash"] > 0.0


def test_select_low_vol_basket_ranks_correctly():
    eq_data = {
        "LOWVOL": make_trend_df(daily_drift=0.0005, daily_vol=0.002, seed=10),
        "HIGHVOL": make_trend_df(daily_drift=0.0005, daily_vol=0.05, seed=11),
        "MIDVOL": make_trend_df(daily_drift=0.0005, daily_vol=0.015, seed=12),
    }
    basket = select_low_vol_basket(eq_data, top_n=2, lookback_weeks=26)
    tickers = [b["Ticker"] for b in basket]
    assert tickers[0] == "LOWVOL"
    assert "HIGHVOL" not in tickers
    assert len(basket) == 2


def _weekly_close_df(amplitude, n_weeks=60, base=100.0):
    dates = pd.date_range("2024-01-05", periods=n_weeks, freq="W-FRI")
    close = base * (1.0 + amplitude * np.sin(np.arange(n_weeks) * 1.3))
    return pd.DataFrame({"Open": close, "High": close, "Low": close, "Close": close}, index=dates)


def test_select_low_vol_basket_buffer_retains_incumbent_within_rank_window():
    """
    Senza buffer, un titolo gia' detenuto ma sceso al 3 posto (su top_n=2) verrebbe
    sostituito dal nuovo 2 in classifica — con buffer_rank=3 resta, perche' la sua
    rank (2, 0-indexed) e' ancora entro la soglia. Vedi APEX_V2_SPEC.md §8.3: senza
    questo buffer il basket si rinnovava quasi per intero ogni trimestre in backtest.
    """
    eq_data = {
        "LOWVOL": _weekly_close_df(amplitude=0.001),
        "MIDVOL2": _weekly_close_df(amplitude=0.006),
        "MIDVOL": _weekly_close_df(amplitude=0.010),
        "HIGHVOL": _weekly_close_df(amplitude=0.05),
    }
    no_buffer = select_low_vol_basket(eq_data, top_n=2, lookback_weeks=26)
    assert [b["Ticker"] for b in no_buffer] == ["LOWVOL", "MIDVOL2"], "senza buffer, MIDVOL (rank 3) deve uscire"

    buffered = select_low_vol_basket(
        eq_data, top_n=2, lookback_weeks=26,
        prev_tickers={"LOWVOL", "MIDVOL"}, buffer_rank=3,
    )
    tickers = [b["Ticker"] for b in buffered]
    assert "MIDVOL" in tickers, "MIDVOL (rank 3, 0-indexed 2 < buffer_rank 3) deve restare grazie al buffer"
    assert "MIDVOL2" not in tickers, "il buffer allenta solo la PERMANENZA, non fa entrare candidati fuori dal top_n se non c'e' posto"


def test_select_low_vol_basket_buffer_never_relaxes_new_entrants():
    """Un titolo MAI detenuto prima deve comunque essere tra i migliori assoluti, buffer o no."""
    eq_data = {
        "LOWVOL": _weekly_close_df(amplitude=0.001),
        "MIDVOL": _weekly_close_df(amplitude=0.010),
        "HIGHVOL": _weekly_close_df(amplitude=0.05),
    }
    buffered = select_low_vol_basket(
        eq_data, top_n=1, lookback_weeks=26,
        prev_tickers=set(), buffer_rank=100,
    )
    assert [b["Ticker"] for b in buffered] == ["LOWVOL"]


def test_quarter_end_month():
    assert is_quarter_end_month(datetime.datetime(2026, 3, 15)) is True
    assert is_quarter_end_month(datetime.datetime(2026, 6, 15)) is True
    assert is_quarter_end_month(datetime.datetime(2026, 7, 15)) is False


if __name__ == "__main__":
    import sys
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"OK   {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {t.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} test passati")
    sys.exit(1 if failed else 0)
