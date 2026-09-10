"""
test_apex_v2_engine.py — Test su dati sintetici a risultato noto per apex_v2_engine.py,
prima di collegarlo a backend.py (stessa disciplina usata in trading/tests/test_quantlab.py).
"""
import datetime
import numpy as np
import pandas as pd

from apex_v2_engine import compute_v2_macro_signal, select_low_vol_basket, select_low_beta_basket, is_quarter_end_month


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


def test_multi_timeframe_blocks_when_short_ma_disagrees():
    """
    Trend di lungo periodo ancora sopra la MA40w (isteresi attiva), ma un crollo
    recente ha portato il prezzo sotto la MA20w — la conferma multi-timeframe deve
    tenere la classe INATTIVA (attivo=False) anche se lo stato di isteresi (basato
    solo sulla MA lunga) resta True. Vedi APEX_V2_SPEC.md §8.9.
    """
    dates = pd.date_range("2024-01-01", periods=400, freq="D")
    rng = np.random.default_rng(5)
    base = 100.0 * np.exp(np.cumsum(rng.normal(0.004, 0.01, 350)))
    crash = base[-1] * np.exp(np.cumsum(np.full(50, -0.02)))  # crollo ripido recente
    close = np.concatenate([base, crash])
    df = pd.DataFrame({"Open": close, "High": close, "Low": close, "Close": close}, index=dates)
    b_data = {"SPY": df, "IEF": make_flat_df(), "GLD": make_flat_df(), "BTC-USD": make_flat_df()}

    alloc, state, debug = compute_v2_macro_signal(b_data, prev_hysteresis_state=None)
    assert debug["Equities"]["attivo"] is False, "MA20w sotto prezzo deve bloccare l'attivazione anche con MA40w ancora favorevole"


def test_adaptive_hysteresis_band_widens_with_higher_volatility():
    """Un asset molto volatile deve ricevere una banda di isteresi piu' larga di uno stabile."""
    b_data = {
        "SPY": make_trend_df(daily_drift=0.001, daily_vol=0.002, seed=7),   # bassa vol
        "IEF": make_trend_df(daily_drift=0.001, daily_vol=0.05, seed=8),    # alta vol
        "GLD": make_flat_df(),
        "BTC-USD": make_flat_df(),
    }
    _, _, debug = compute_v2_macro_signal(b_data, prev_hysteresis_state=None)
    assert debug["Bonds"]["banda_isteresi_pct"] > debug["Equities"]["banda_isteresi_pct"], \
        "l'asset piu' volatile (IEF qui) deve avere una banda di isteresi piu' larga"


def test_vol_target_scales_down_high_vol_portfolio():
    high_vol = make_trend_df(daily_drift=0.004, daily_vol=0.04, seed=3)  # asset molto volatile e in trend
    b_data = {"SPY": high_vol, "IEF": make_flat_df(), "GLD": make_flat_df(), "BTC-USD": make_flat_df()}
    alloc, state, debug = compute_v2_macro_signal(b_data, prev_hysteresis_state=None)
    assert debug["_vol_target"]["fattore_scala"] < 1.0, "un portafoglio ad alta volatilita' deve essere scalato verso il basso"
    assert alloc["Cash"] > 0.0


def test_allocations_never_exceed_100_percent_even_with_base_weight_50():
    # Bug reale trovato negli script di ricerca prima dell'adozione del Percorso B
    # (base_weight 0.50, vol-target 0.22 — vedi APEX_V2_SPEC.md §8.25/§10.13): con 4
    # classi attive e volatilita' realizzata moderata (non abbastanza alta da far
    # scattare abbastanza il vol-target), la somma dei pesi puo' superare 100% per
    # costruzione algebrica — a differenza di base_weight=0.25 (4x25%=100% esatto,
    # mai di piu'). Il limite esplicito di rinormalizzazione deve impedirlo sempre.
    import apex_v2_engine as engine
    b_data = {
        "SPY": make_trend_df(daily_drift=0.002, daily_vol=0.012, seed=20),
        "IEF": make_trend_df(daily_drift=0.002, daily_vol=0.012, seed=21),
        "GLD": make_trend_df(daily_drift=0.002, daily_vol=0.012, seed=22),
        "BTC-USD": make_trend_df(daily_drift=0.002, daily_vol=0.012, seed=23),
    }
    alloc, state, debug = compute_v2_macro_signal(b_data, prev_hysteresis_state=None)
    assert all(state.values()), "il test presuppone tutte e 4 le classi attive"
    total = sum(alloc[cls] for cls in engine.V2_CLASS_TICKER)
    assert total <= 100.0 + 1e-6, f"la somma dei pesi non deve mai superare 100% (leva non dichiarata), trovato {total}"


def test_base_weight_and_vol_target_default_to_current_production_values():
    """base_weight_per_class/vol_target sono stati aggiunti come parametri
    opzionali (per permettere una grid search indipendente sulla dimensione
    delle posizioni per classe in validation_suite/) — non chiamarli non deve
    cambiare il risultato di una virgola rispetto a prima dell'aggiunta."""
    b_data = {
        "SPY": make_trend_df(daily_drift=0.002, daily_vol=0.012, seed=20),
        "IEF": make_trend_df(daily_drift=0.002, daily_vol=0.012, seed=21),
        "GLD": make_trend_df(daily_drift=0.002, daily_vol=0.012, seed=22),
        "BTC-USD": make_trend_df(daily_drift=0.002, daily_vol=0.012, seed=23),
    }
    alloc_default, _, _ = compute_v2_macro_signal(b_data, prev_hysteresis_state=None)
    alloc_explicit, _, _ = compute_v2_macro_signal(b_data, prev_hysteresis_state=None, base_weight_per_class=0.50, vol_target=0.22)
    for cls in alloc_default:
        assert abs(alloc_default[cls] - alloc_explicit[cls]) < 1e-9


def test_base_weight_per_class_scales_allocation_proportionally():
    """Un base_weight_per_class piu' basso deve produrre pesi finali piu' bassi
    (a parita' di tutto il resto) — verifica che il parametro sia davvero
    collegato, non solo accettato e ignorato."""
    b_data = {
        "SPY": make_trend_df(daily_drift=0.002, daily_vol=0.012, seed=20),
        "IEF": make_flat_df(), "GLD": make_flat_df(), "BTC-USD": make_flat_df(),
    }
    alloc_50, _, _ = compute_v2_macro_signal(b_data, prev_hysteresis_state=None, base_weight_per_class=0.50)
    alloc_25, _, _ = compute_v2_macro_signal(b_data, prev_hysteresis_state=None, base_weight_per_class=0.25)
    assert alloc_25["Equities"] < alloc_50["Equities"]


def test_vol_target_parameter_changes_scale_factor():
    """Un vol_target piu' basso deve scalare piu' aggressivamente verso il
    basso un portafoglio ad alta volatilita' rispetto a un vol_target piu'
    alto — stessa proprieta' di V2_VOL_TARGET, ora parametrizzabile."""
    high_vol = make_trend_df(daily_drift=0.004, daily_vol=0.04, seed=3)
    b_data = {"SPY": high_vol, "IEF": make_flat_df(), "GLD": make_flat_df(), "BTC-USD": make_flat_df()}
    _, _, debug_low_target = compute_v2_macro_signal(b_data, prev_hysteresis_state=None, vol_target=0.10)
    _, _, debug_high_target = compute_v2_macro_signal(b_data, prev_hysteresis_state=None, vol_target=0.30)
    assert debug_low_target["_vol_target"]["fattore_scala"] < debug_high_target["_vol_target"]["fattore_scala"]


def make_multivariate_weekly_df(n_weeks, mu_annual, vol_annual, seed=42):
    """4 serie di prezzo settimanali INDIPENDENTI (Sigma diagonale nota) con mu/vol
    annualizzati noti, ordine [SPY, IEF, GLD, BTC-USD] — per testare
    _kelly_class_weights su dati con struttura nota (Sigma diagonale rende
    f*=mu/vol^2 elemento per elemento, facile da verificare a mano)."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2015-01-02", periods=n_weeks, freq="W-FRI")
    dfs = {}
    weekly_mu = np.array(mu_annual) / 52.0
    weekly_vol = np.array(vol_annual) / np.sqrt(52.0)
    for i, cls in enumerate(["SPY", "IEF", "GLD", "BTC-USD"]):
        rets = rng.normal(weekly_mu[i], weekly_vol[i], size=n_weeks)
        prices = 100.0 * np.cumprod(1 + rets)
        dfs[cls] = pd.DataFrame({"Open": prices, "High": prices, "Low": prices, "Close": prices}, index=dates)
    return dfs


def test_kelly_class_weights_matches_hand_computed_f_star_on_known_data():
    import apex_v2_engine as engine
    n_weeks = engine.V2_KELLY_MU_SIGMA_WINDOW + 20
    mu_annual = [0.15, 0.05, 0.03, 0.40]   # SPY, IEF, GLD, BTC-USD (ordine di V2_CLASS_TICKER)
    vol_annual = [0.15, 0.06, 0.15, 0.60]
    b_data = make_multivariate_weekly_df(n_weeks, mu_annual, vol_annual, seed=3)

    f_star = engine._kelly_class_weights(b_data, engine.V2_KELLY_MU_SIGMA_WINDOW)
    assert f_star is not None

    # Ricalcolo indipendente con lo STESSO metodo (mean/cov empirici sulla finestra,
    # non i parametri "veri" della generazione, che un campione finito non replica
    # esattamente) — verifica che _kelly_class_weights faccia davvero questo calcolo,
    # non un'approssimazione o un bug di indicizzazione tra classi.
    closes = {cls: b_data[ticker]["Close"].resample("W-FRI").last().dropna()
              for cls, ticker in engine.V2_CLASS_TICKER.items()}
    rets = pd.DataFrame({cls: c.pct_change() for cls, c in closes.items()}).dropna()
    window_rets = rets.iloc[-engine.V2_KELLY_MU_SIGMA_WINDOW:]
    mu = window_rets.mean().to_numpy() * 52.0
    Sigma = window_rets.cov().to_numpy() * 52.0
    expected = dict(zip(rets.columns, np.linalg.solve(Sigma, mu)))
    for cls in engine.V2_CLASS_TICKER:
        assert abs(f_star[cls] - expected[cls]) < 1e-9

    # Proprieta' qualitativa attesa (non un numero esatto, dipende dal campione): BTC
    # ha mu annuo molto piu' alto di SPY (40% contro 15%, ~2.7x) ma vol molto piu'
    # alta (60% contro 15%, quindi vol^2 ~16x) — Kelly deve dargli un peso f*
    # PROPORZIONALMENTE minore rispetto a SPY di quanto farebbe un ranking puro per
    # rendimento atteso, la proprieta' chiave che distingue Kelly da un ranking
    # ingenuo per mu (vedi validation_suite/README.md, sezione Kelly sulle classi).
    assert f_star["Crypto"] / f_star["Equities"] < mu_annual[3] / mu_annual[0]


def test_kelly_class_weights_none_with_insufficient_history():
    import apex_v2_engine as engine
    short = make_trend_df(n_days=200, seed=1)  # troppo corto per V2_KELLY_MU_SIGMA_WINDOW settimane
    b_data = {"SPY": short, "IEF": short, "GLD": short, "BTC-USD": short}
    assert engine._kelly_class_weights(b_data, engine.V2_KELLY_MU_SIGMA_WINDOW) is None


def test_kelly_class_weights_none_with_singular_sigma():
    import apex_v2_engine as engine
    n_weeks = engine.V2_KELLY_MU_SIGMA_WINDOW + 10
    dates = pd.date_range("2015-01-02", periods=n_weeks, freq="W-FRI")
    rng = np.random.default_rng(1)
    rets = rng.normal(0.001, 0.01, size=n_weeks)
    prices = 100.0 * np.cumprod(1 + rets)
    df = pd.DataFrame({"Open": prices, "High": prices, "Low": prices, "Close": prices}, index=dates)
    b_data = {"SPY": df, "IEF": df, "GLD": df, "BTC-USD": df}  # stessa identica serie -> covarianza singolare
    assert engine._kelly_class_weights(b_data, engine.V2_KELLY_MU_SIGMA_WINDOW) is None


def test_compute_v2_macro_signal_kelly_disabled_matches_flat_weight():
    """kelly_fraction=0.0 deve riprodurre ESATTAMENTE il comportamento pre-Kelly,
    anche con storico lungo a sufficienza per calcolarlo — prova che il parametro
    disattiva davvero il meccanismo, non solo quando i dati sono insufficienti."""
    import apex_v2_engine as engine
    n_weeks = engine.V2_KELLY_MU_SIGMA_WINDOW + 60
    b_data = make_multivariate_weekly_df(n_weeks, [0.15, 0.05, 0.03, 0.40], [0.15, 0.06, 0.15, 0.60], seed=3)
    alloc_kelly_off, _, debug_off = compute_v2_macro_signal(b_data, prev_hysteresis_state=None, kelly_fraction=0.0)
    alloc_flat, _, _ = compute_v2_macro_signal(b_data, prev_hysteresis_state=None, kelly_fraction=0.0, base_weight_per_class=0.50)
    for cls in alloc_kelly_off:
        assert abs(alloc_kelly_off[cls] - alloc_flat[cls]) < 1e-9
    assert "kelly_f_star" not in debug_off["Equities"]


def test_compute_v2_macro_signal_kelly_enabled_diverges_from_flat_weight_with_long_history():
    """Con storico sufficiente (kelly_fraction di default > 0, comportamento di
    produzione) l'allocazione deve differire da quella a peso fisso uguale — prova
    che il meccanismo Kelly viene davvero applicato quando i dati lo consentono,
    non solo accettato e ignorato (stesso principio di
    test_base_weight_per_class_scales_allocation_proportionally per il parametro
    precedente)."""
    import apex_v2_engine as engine
    n_weeks = engine.V2_KELLY_MU_SIGMA_WINDOW + 60
    b_data = make_multivariate_weekly_df(n_weeks, [0.15, 0.05, 0.03, 0.40], [0.15, 0.06, 0.15, 0.60], seed=3)
    alloc_kelly, _, debug_kelly = compute_v2_macro_signal(b_data, prev_hysteresis_state=None)  # default: Kelly abilitato
    alloc_flat, _, _ = compute_v2_macro_signal(b_data, prev_hysteresis_state=None, kelly_fraction=0.0)

    active = [cls for cls in engine.V2_CLASS_TICKER if debug_kelly[cls].get("attivo")]
    assert active, "il test presuppone almeno una classe attiva per trend con questo seed"
    assert any(abs(alloc_kelly[cls] - alloc_flat[cls]) > 1e-6 for cls in engine.V2_CLASS_TICKER)
    assert all("kelly_f_star" in debug_kelly[cls] for cls in active)


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


def test_select_low_vol_basket_respects_sector_cap():
    """
    Senza vincolo, i due titoli meno volatili in assoluto (entrambi settore A)
    riempirebbero 2 dei 3 posti. Con max_per_sector=1, il secondo titolo del
    settore A viene saltato in favore del migliore candidato di un altro settore
    — vedi APEX_V2_SPEC.md §8.7 (concentrazione fino all'80% in un solo settore
    misurata in backtest, senza vincolo).
    """
    eq_data = {
        "A1": _weekly_close_df(amplitude=0.001),   # settore A, rank 1
        "A2": _weekly_close_df(amplitude=0.003),   # settore A, rank 2
        "B1": _weekly_close_df(amplitude=0.006),   # settore B, rank 3
        "C1": _weekly_close_df(amplitude=0.010),   # settore C, rank 4
    }
    sector_of = {"A1": "A", "A2": "A", "B1": "B", "C1": "C"}

    no_cap = select_low_vol_basket(eq_data, top_n=3, lookback_weeks=26, sector_of=sector_of, max_per_sector=99)
    assert [b["Ticker"] for b in no_cap] == ["A1", "A2", "B1"], "senza vincolo il settore A prende 2 posti su 3"

    capped = select_low_vol_basket(eq_data, top_n=3, lookback_weeks=26, sector_of=sector_of, max_per_sector=1)
    tickers = [b["Ticker"] for b in capped]
    assert tickers == ["A1", "B1", "C1"], "con max 1/settore, A2 viene saltato a favore del miglior candidato di un altro settore"


def test_select_low_vol_basket_sector_cap_fails_open_on_missing_data():
    """Un titolo senza settore noto non deve mai essere bloccato dal vincolo."""
    eq_data = {
        "KNOWN": _weekly_close_df(amplitude=0.001),
        "UNKNOWN": _weekly_close_df(amplitude=0.003),
    }
    basket = select_low_vol_basket(eq_data, top_n=2, lookback_weeks=26, sector_of={"KNOWN": "A"}, max_per_sector=1)
    assert {b["Ticker"] for b in basket} == {"KNOWN", "UNKNOWN"}


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


def _spy_ref_df(n_weeks=60, seed=99, vol=0.02, base=100.0):
    """Serie SPY di riferimento a rendimenti settimanali casuali ma riproducibili
    (seed fisso) — usata come base per costruire titoli a BETA controllato."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2024-01-05", periods=n_weeks, freq="W-FRI")
    rets = rng.normal(0.001, vol, n_weeks)
    close = base * np.cumprod(1 + rets)
    return pd.DataFrame({"Open": close, "High": close, "Low": close, "Close": close}, index=dates)


def _beta_controlled_df(spy_df, beta, noise_std=0.0005, seed=0, base=100.0):
    """Costruisce una serie prezzi con BETA CONTROLLATO rispetto a spy_df: rendimento
    settimanale = beta * rendimento_SPY + rumore idiosincratico indipendente (piccolo,
    cosi' il beta stimato dal test resta vicino al beta vero usato per costruirla)."""
    spy_ret = spy_df["Close"].pct_change().fillna(0.0).values
    rng = np.random.default_rng(seed)
    noise = rng.normal(0, noise_std, len(spy_ret))
    stock_ret = beta * spy_ret + noise
    close = base * np.cumprod(1 + stock_ret)
    return pd.DataFrame({"Open": close, "High": close, "Low": close, "Close": close}, index=spy_df.index)


def test_select_low_beta_basket_ranks_correctly():
    """Ordinamento per beta CRESCENTE (non valore assoluto): un beta molto negativo
    e' preferito a uno leggermente positivo, coerente con la letteratura BAB — vedi
    APEX_V2_SPEC.md §8.29."""
    spy = _spy_ref_df()
    eq_data = {
        "NEGBETA": _beta_controlled_df(spy, beta=-0.3, seed=1),
        "LOWBETA": _beta_controlled_df(spy, beta=0.1, seed=2),
        "HIGHBETA": _beta_controlled_df(spy, beta=1.5, seed=3),
    }
    basket = select_low_beta_basket(eq_data, spy, top_n=2, lookback_weeks=26)
    tickers = [b["Ticker"] for b in basket]
    assert tickers == ["NEGBETA", "LOWBETA"], "beta negativo preferito a beta positivo basso, entrambi preferiti al beta alto"
    assert "HIGHBETA" not in tickers
    assert len(basket) == 2


def test_select_low_beta_basket_reports_beta_not_volatility():
    """Il dict risultante deve esporre il beta (chiave 'Beta (vs SPY)'), non piu' la
    volatilita' assoluta — un titolo ad alta volatilita' ma basso beta (poco in
    sintonia col mercato) deve poter essere selezionato, a differenza di
    select_low_vol_basket."""
    spy = _spy_ref_df()
    eq_data = {
        "LOWBETA_HIGHVOL": _beta_controlled_df(spy, beta=0.05, noise_std=0.05, seed=1),
        "HIGHBETA_LOWVOL": _beta_controlled_df(spy, beta=1.2, noise_std=0.0002, seed=2),
    }
    basket = select_low_beta_basket(eq_data, spy, top_n=1, lookback_weeks=26)
    assert basket[0]["Ticker"] == "LOWBETA_HIGHVOL", "basso beta vince anche se la volatilita' assoluta e' piu' alta"
    assert "Beta (vs SPY)" in basket[0]
    assert "Volatilita' Ann. (%)" not in basket[0]


def test_select_low_beta_basket_buffer_retains_incumbent_within_rank_window():
    spy = _spy_ref_df()
    eq_data = {
        "LOWBETA": _beta_controlled_df(spy, beta=-0.2, seed=1),
        "MIDBETA2": _beta_controlled_df(spy, beta=0.3, seed=2),
        "MIDBETA": _beta_controlled_df(spy, beta=0.6, seed=3),
        "HIGHBETA": _beta_controlled_df(spy, beta=1.8, seed=4),
    }
    no_buffer = select_low_beta_basket(eq_data, spy, top_n=2, lookback_weeks=26)
    assert [b["Ticker"] for b in no_buffer] == ["LOWBETA", "MIDBETA2"], "senza buffer, MIDBETA (rank 3) deve uscire"

    buffered = select_low_beta_basket(
        eq_data, spy, top_n=2, lookback_weeks=26,
        prev_tickers={"LOWBETA", "MIDBETA"}, buffer_rank=3,
    )
    tickers = [b["Ticker"] for b in buffered]
    assert "MIDBETA" in tickers, "MIDBETA (rank 3, 0-indexed 2 < buffer_rank 3) deve restare grazie al buffer"
    assert "MIDBETA2" not in tickers


def test_select_low_beta_basket_respects_sector_cap():
    spy = _spy_ref_df()
    eq_data = {
        "A1": _beta_controlled_df(spy, beta=-0.2, seed=1),   # settore A, rank 1
        "A2": _beta_controlled_df(spy, beta=0.1, seed=2),    # settore A, rank 2
        "B1": _beta_controlled_df(spy, beta=0.5, seed=3),    # settore B, rank 3
        "C1": _beta_controlled_df(spy, beta=1.0, seed=4),    # settore C, rank 4
    }
    sector_of = {"A1": "A", "A2": "A", "B1": "B", "C1": "C"}

    no_cap = select_low_beta_basket(eq_data, spy, top_n=3, lookback_weeks=26, sector_of=sector_of, max_per_sector=99)
    assert [b["Ticker"] for b in no_cap] == ["A1", "A2", "B1"]

    capped = select_low_beta_basket(eq_data, spy, top_n=3, lookback_weeks=26, sector_of=sector_of, max_per_sector=1)
    assert [b["Ticker"] for b in capped] == ["A1", "B1", "C1"]


def test_select_low_beta_basket_sector_cap_fails_open_on_missing_data():
    spy = _spy_ref_df()
    eq_data = {
        "KNOWN": _beta_controlled_df(spy, beta=-0.2, seed=1),
        "UNKNOWN": _beta_controlled_df(spy, beta=0.1, seed=2),
    }
    basket = select_low_beta_basket(eq_data, spy, top_n=2, lookback_weeks=26, sector_of={"KNOWN": "A"}, max_per_sector=1)
    assert {b["Ticker"] for b in basket} == {"KNOWN", "UNKNOWN"}


def test_select_low_beta_basket_insufficient_history_excluded():
    """Un titolo con meno di lookback_weeks+1 settimane di storico comune con SPY
    non deve poter essere scelto (beta non stimabile in modo affidabile)."""
    spy = _spy_ref_df(n_weeks=60)
    short_df = _beta_controlled_df(spy, beta=-0.5, seed=1).iloc[-10:]  # solo 10 settimane
    eq_data = {
        "TOOSHORT": short_df,
        "ENOUGH": _beta_controlled_df(spy, beta=0.8, seed=2),
    }
    basket = select_low_beta_basket(eq_data, spy, top_n=2, lookback_weeks=26)
    tickers = [b["Ticker"] for b in basket]
    assert "TOOSHORT" not in tickers
    assert tickers == ["ENOUGH"]


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
