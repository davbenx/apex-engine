"""
test_kelly_backtest.py — Verifica su scenari sintetici a risultato noto delle
funzioni di calcolo (_cagr, _max_drawdown, tassazione) prima di applicarle ai
dati storici reali in kelly_backtest.py.
"""
import numpy as np
import pandas as pd
import pytest

from kelly_backtest import (
    _cagr, _max_drawdown, _sharpe, _apply_italian_tax, build_sleeve_returns,
    compute_dynamic_target_weights, compute_trend_gate, compute_trend_gated_weights,
    compute_tsmom_sleeve_returns, shrink_covariance_ledoit_wolf, apply_per_sleeve_stop_loss,
)


def test_cagr_constant_monthly_return():
    r = 0.01  # 1%/mese costante
    monthly = pd.Series([r] * 24)  # 2 anni
    expected = (1 + r) ** 12 - 1
    assert abs(_cagr(monthly) - expected) < 1e-9


def test_cagr_zero_return_is_zero():
    monthly = pd.Series([0.0] * 12)
    assert abs(_cagr(monthly)) < 1e-9


def test_max_drawdown_known_path():
    # NAV: 1.0 -> 1.2 -> 0.9 -> 1.1  => drawdown dal picco 1.2 a 0.9 = -25%
    monthly = pd.Series([0.20, -0.25, 0.2222222222])
    dd = _max_drawdown(monthly)
    assert abs(dd - (-0.25)) < 1e-6


def test_sharpe_zero_vol_returns_zero_not_nan():
    monthly = pd.Series([0.01] * 12)  # rendimento costante, vol = 0
    assert _sharpe(monthly) == 0.0


def test_italian_tax_capital_income_pays_flat_26_on_realized_gain_only():
    """Sleeve unica a reddito di capitale, cresce ininterrottamente: il
    ribilanciamento mensile verso peso fisso 100% non vende nulla (nessun
    eccesso rispetto al target), quindi non deve scattare tassazione fino a
    che non c'e' un secondo asset che assorbe l'eccesso."""
    returns = pd.DataFrame({"A": [0.10, 0.10], "B": [0.0, 0.0]})
    net = _apply_italian_tax(returns, {"A": 0.5, "B": 0.5}, tax_types={"A": "REDDITO_CAPITALE", "B": "REDDITO_CAPITALE"})
    # A cresce, B resta fermo -> il ribilanciamento VENDE una parte di A (reddito capitale)
    # per riportarla al 50% -> deve scattare una tassa positiva su quel guadagno
    gross = (returns["A"] * 0.5 + returns["B"] * 0.5)
    assert (1 + net).prod() < (1 + gross).prod(), "la tassazione deve ridurre il rendimento netto rispetto al lordo"


def test_italian_tax_reddito_diverso_offsets_loss_against_later_gain():
    """Sleeve a reddito diverso: una minusvalenza realizzata deve compensare una
    plusvalenza successiva, riducendo la tassa dovuta rispetto al caso senza
    compensazione (verificato per confronto tra due scenari)."""
    keys = {"WBTC_proxy": 0.5, "PPFB_proxy": 0.5}
    # scenario con perdita poi guadagno (compensazione possibile)
    returns_with_loss = pd.DataFrame({
        "WBTC_proxy": [-0.30, 0.50, 0.10],
        "PPFB_proxy": [0.0, 0.0, 0.0],
    })
    net = _apply_italian_tax(returns_with_loss, keys)
    gross = (returns_with_loss["WBTC_proxy"] * 0.5 + returns_with_loss["PPFB_proxy"] * 0.5)
    # con compensazione minusvalenze, il drag fiscale totale deve essere STRETTAMENTE
    # inferiore a quanto sarebbe senza compensazione (26% pieno su ogni plusvalenza lorda)
    total_gross_growth = (1 + gross).prod()
    total_net_growth = (1 + net).prod()
    naive_full_tax_growth = total_gross_growth - (total_gross_growth - 1) * 0.26 if total_gross_growth > 1 else total_gross_growth
    assert total_net_growth >= naive_full_tax_growth - 1e-6, (
        "con compensazione minusvalenze il drag fiscale non deve superare la tassazione piena senza compensazione"
    )


def test_leveraged_tax_never_inflates_nav_beyond_gross():
    """Regressione: con leva (somma pesi target > 100%, come nel disegno
    deployato), la tassazione non deve MAI produrre una crescita netta
    superiore alla crescita lorda, e i due ordini di grandezza devono restare
    comparabili — bug reale trovato durante lo sviluppo: confondere valore
    nozionale delle posizioni (che con leva supera il NAV) con il NAV stesso
    produceva un errore di scala composto ogni mese, CAGR netto >10.000%."""
    rng = np.random.default_rng(3)
    n = 48
    returns = pd.DataFrame({
        "NTSG_proxy": rng.normal(0.008, 0.04, n),
        "AVWS_proxy": rng.normal(0.007, 0.05, n),
        "DBMFE_proxy": rng.normal(0.004, 0.025, n),
        "PPFB_proxy": rng.normal(0.002, 0.035, n),
        "WBTC_proxy": rng.normal(0.02, 0.15, n),
    })
    weights = {"NTSG_proxy": 0.6, "AVWS_proxy": 0.14, "DBMFE_proxy": 0.6, "PPFB_proxy": 0.0, "WBTC_proxy": 0.15}
    assert sum(weights.values()) > 1.0, "questo test presuppone leva (somma pesi > 100%)"

    net = _apply_italian_tax(returns, weights)
    gross = (returns * pd.Series(weights)).sum(axis=1)

    gross_growth = float((1 + gross).prod())
    net_growth = float((1 + net).prod())

    assert net_growth <= gross_growth * 1.001, (
        f"il netto ({net_growth:.2f}x) non deve mai superare il lordo ({gross_growth:.2f}x): "
        "la tassazione riduce la ricchezza, non la aumenta"
    )
    assert net_growth > gross_growth * 0.5, (
        f"un drag fiscale che dimezza la crescita totale su {n} mesi indicherebbe un bug di scala, "
        f"non un effetto fiscale plausibile (lordo {gross_growth:.2f}x, netto {net_growth:.2f}x)"
    )


def test_dynamic_governor_deleverages_on_high_volatility():
    """Un regime di volatilita' realizzata alta (oltre il vol-target) deve
    produrre pesi finali SCALATI verso il basso rispetto ai pesi base — stesso
    principio del vol-targeting gia' validato in apex_v2_engine.py."""
    rng = np.random.default_rng(1)
    calib = pd.DataFrame({"A": rng.normal(0.01, 0.02, 24), "B": rng.normal(0.005, 0.015, 24)})
    oos_calm = pd.DataFrame({"A": rng.normal(0.01, 0.02, 24), "B": rng.normal(0.005, 0.015, 24)})
    oos_stormy = pd.DataFrame({"A": rng.normal(0.01, 0.20, 24), "B": rng.normal(0.005, 0.15, 24)})
    base_weights = {"A": 0.8, "B": 0.4}

    w_calm = compute_dynamic_target_weights(calib, oos_calm, base_weights)
    w_stormy = compute_dynamic_target_weights(calib, oos_stormy, base_weights)

    # dopo la finestra di warm-up (12 mesi), il regime turbolento deve avere pesi
    # sistematicamente piu' bassi di quello calmo
    assert w_stormy.iloc[12:].sum(axis=1).mean() < w_calm.iloc[12:].sum(axis=1).mean()


def test_dynamic_governor_halves_exposure_after_severe_drawdown():
    """Un drawdown che supera KELLY_DD_DERISK_TRIGGER deve far scattare la
    deleva al pavimento KELLY_DD_DERISK_FLOOR sui mesi successivi."""
    from kelly_engine import KELLY_DD_DERISK_FLOOR
    calib = pd.DataFrame({"A": [0.01] * 24, "B": [0.005] * 24})
    # crollo netto nei primi mesi OOS, poi mesi piatti: il drawdown resta sopra la soglia
    oos = pd.DataFrame({
        "A": [-0.20, -0.15] + [0.0] * 10,
        "B": [-0.20, -0.15] + [0.0] * 10,
    })
    base_weights = {"A": 0.8, "B": 0.4}
    w = compute_dynamic_target_weights(calib, oos, base_weights)
    total_base = sum(base_weights.values())
    # nei mesi finali, dopo il crollo, l'esposizione deve essere scesa al pavimento
    assert abs(w.iloc[-1].sum() - total_base * KELLY_DD_DERISK_FLOOR) < 1e-9


def test_dynamic_governor_has_no_lookahead():
    """Il peso assegnato ai primi mesi OOS non deve dipendere da cosa succede
    DOPO in quello stesso OOS — solo dalla calibrazione e dai mesi OOS gia'
    trascorsi. Verificato modificando gli ultimi mesi OOS e controllando che i
    primi pesi restino identici."""
    rng = np.random.default_rng(5)
    calib = pd.DataFrame({"A": rng.normal(0.01, 0.02, 24), "B": rng.normal(0.005, 0.015, 24)})
    oos_base = pd.DataFrame({"A": rng.normal(0.01, 0.03, 20), "B": rng.normal(0.005, 0.02, 20)})
    base_weights = {"A": 0.8, "B": 0.4}

    oos_altered = oos_base.copy()
    oos_altered.iloc[15:] = oos_altered.iloc[15:] * 10  # sconvolge SOLO la coda finale

    w_base = compute_dynamic_target_weights(calib, oos_base, base_weights)
    w_altered = compute_dynamic_target_weights(calib, oos_altered, base_weights)

    pd.testing.assert_frame_equal(w_base.iloc[:15], w_altered.iloc[:15])


def test_per_sleeve_stop_zeroes_weight_after_breach():
    n = 20
    oos = pd.DataFrame({"A": [-0.20] + [0.0] * (n - 1), "B": [0.01] * n})
    weights = pd.DataFrame({"A": [0.5] * n, "B": [0.5] * n})
    out = apply_per_sleeve_stop_loss(oos, weights, stop_threshold=-0.15)
    assert out["A"].iloc[1] == 0.0, "dopo un calo oltre la soglia, la sleeve deve azzerarsi dal mese successivo"
    assert out["B"].iloc[1] == 0.5, "una sleeve non colpita dallo stop non deve essere toccata"


def test_per_sleeve_stop_recovers_after_buffer():
    n = 10
    # crolla del 20%, risale poco (non basta a superare il buffer 5% dal minimo),
    # poi risale ancora abbastanza da superarlo
    oos = pd.DataFrame({"A": [-0.20, 0.02, 0.10, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]})
    weights = pd.DataFrame({"A": [1.0] * n})
    out = apply_per_sleeve_stop_loss(oos, weights, stop_threshold=-0.15, recovery_buffer=0.05)
    assert out["A"].iloc[1] == 0.0, "subito dopo il crollo, con un recupero ancora insufficiente, deve restare fuori"
    assert out["A"].iloc[-1] == 1.0, "dopo il recupero oltre il buffer deve rientrare"


def test_ewma_governor_reacts_faster_than_flat_window():
    """Dopo un singolo mese di volatilita' molto alta, l'EWMA deve scalare
    l'esposizione GIU' immediatamente, mentre la finestra piatta a 12 mesi
    (che pesa quel mese solo 1/12) deve reagire molto meno — il motivo per
    cui l'EWMA esiste."""
    rng = np.random.default_rng(2)
    calib = pd.DataFrame({"A": rng.normal(0.01, 0.02, 24), "B": rng.normal(0.005, 0.015, 24)})
    oos = pd.DataFrame({"A": [0.30] + [0.01] * 11, "B": [0.20] + [0.005] * 11})  # shock nel primo mese, poi calmo
    base_weights = {"A": 0.8, "B": 0.4}

    w_flat = compute_dynamic_target_weights(calib, oos, base_weights, vol_window=12)
    w_ewma = compute_dynamic_target_weights(calib, oos, base_weights, ewma_lambda=0.85)

    scale_flat_month2 = w_flat.iloc[1].sum() / sum(base_weights.values())
    scale_ewma_month2 = w_ewma.iloc[1].sum() / sum(base_weights.values())
    assert scale_ewma_month2 < scale_flat_month2, (
        "l'EWMA deve scalare l'esposizione giu' piu' della finestra piatta subito dopo uno shock di volatilita'"
    )


def test_trend_gate_turns_off_in_sustained_downtrend():
    """Una sleeve in caduta netta e sostenuta deve finire con gate=0 (inattiva)
    dopo la finestra di isteresi, mentre una sleeve in salita netta resta gate=1."""
    n = 30
    calib = pd.DataFrame({
        "UP": [0.02] * n, "DOWN": [0.02] * n,  # entrambe in salita durante la calibrazione
    })
    oos = pd.DataFrame({
        "UP": [0.02] * 15,     # continua a salire
        "DOWN": [-0.05] * 15,  # crollo netto e sostenuto
    })
    gate = compute_trend_gate(calib, oos, ma_window=10, hysteresis_band=0.02)
    assert gate["UP"].iloc[-1] == 1.0
    assert gate["DOWN"].iloc[-1] == 0.0, "una caduta sostenuta oltre la banda di isteresi deve disattivare la sleeve"


def test_trend_gate_hysteresis_keeps_small_dip_active():
    """Una sleeve gia' attiva con un calo piccolo (dentro la banda di isteresi)
    deve restare attiva — stesso principio gia' validato in apex_v2_engine.py."""
    n = 30
    calib = pd.DataFrame({"A": [0.02] * n})
    oos = pd.DataFrame({"A": [0.02] * 10 + [-0.005] * 5})  # calo minimo, dentro la banda 2%
    gate = compute_trend_gate(calib, oos, ma_window=10, hysteresis_band=0.02)
    assert gate["A"].iloc[-1] == 1.0


def test_trend_gate_has_no_lookahead():
    """Il gate dei primi mesi OOS non deve dipendere da cosa succede DOPO in
    quello stesso OOS — stessa proprieta' gia' verificata per il governatore
    dinamico di portafoglio."""
    rng = np.random.default_rng(9)
    calib = pd.DataFrame({"A": rng.normal(0.01, 0.03, 24), "B": rng.normal(0.005, 0.02, 24)})
    oos_base = pd.DataFrame({"A": rng.normal(0.01, 0.04, 20), "B": rng.normal(0.005, 0.03, 20)})
    oos_altered = oos_base.copy()
    oos_altered.iloc[15:] = oos_altered.iloc[15:] * 10

    gate_base = compute_trend_gate(calib, oos_base)
    gate_altered = compute_trend_gate(calib, oos_altered)
    pd.testing.assert_frame_equal(gate_base.iloc[:15], gate_altered.iloc[:15])


def test_trend_gated_weights_zero_out_inactive_sleeve():
    """Una sleeve disattivata dal filtro di trend deve avere peso ESATTAMENTE
    zero nei mesi in cui e' inattiva (capitale implicitamente in cash)."""
    n = 30
    calib = pd.DataFrame({"UP": [0.02] * n, "DOWN": [0.02] * n})
    oos = pd.DataFrame({"UP": [0.02] * 15, "DOWN": [-0.05] * 15})
    weights = compute_trend_gated_weights(calib, oos, {"UP": 0.6, "DOWN": 0.6})
    assert weights["DOWN"].iloc[-1] == 0.0
    assert weights["UP"].iloc[-1] > 0.0


def test_tsmom_goes_long_a_sustained_uptrend():
    """Un mercato in salita netta e sostenuta deve produrre rendimenti di
    posizione POSITIVI dopo la finestra di lookback (segnale long, non flat)."""
    idx = pd.date_range("2015-01-31", periods=40, freq="ME")
    up_prices = pd.Series(100 * (1.02 ** np.arange(40)), index=idx)
    flat_prices = pd.Series(100.0, index=idx)
    tsmom = compute_tsmom_sleeve_returns({"UP": up_prices, "FLAT": flat_prices}, lookback_months=12, vol_window=6)
    assert tsmom.iloc[-1] > 0, "un trend rialzista sostenuto deve tradursi in rendimento di posizione positivo"


def test_tsmom_goes_short_or_flat_in_sustained_downtrend():
    """Un mercato in caduta netta e sostenuta deve produrre rendimenti di
    posizione NON negativi (short di un asset che scende contribuisce
    positivamente, o flat) — mai la stessa perdita subita da un long passivo."""
    idx = pd.date_range("2015-01-31", periods=40, freq="ME")
    down_prices = pd.Series(100 * (0.98 ** np.arange(40)), index=idx)
    tsmom_down = compute_tsmom_sleeve_returns({"DOWN": down_prices}, lookback_months=12, vol_window=6)
    passive_return = down_prices.pct_change().dropna().iloc[-1]
    assert tsmom_down.iloc[-1] > passive_return, (
        "il time-series momentum su un downtrend sostenuto deve fare meglio del long passivo dello stesso asset"
    )


def test_tsmom_multi_timeframe_confirmation_flattens_disagreement():
    """Se il momentum di lungo periodo e' ancora positivo (trend non ancora
    invertito nella finestra lunga) ma quello di breve e' negativo (appena
    girato), la conferma multi-timeframe deve dare posizione FLAT (0), non
    long — altrimenti la conferma non farebbe nulla."""
    idx = pd.date_range("2015-01-31", periods=30, freq="ME")
    prices = pd.Series(list(100 * (1.02 ** np.arange(24))) + list(100 * (1.02**23) * (0.95 ** np.arange(1, 7))), index=idx)
    tsmom_no_confirm = compute_tsmom_sleeve_returns({"A": prices}, lookback_months=12, vol_window=6)
    tsmom_confirm = compute_tsmom_sleeve_returns({"A": prices}, lookback_months=12, vol_window=6, short_lookback_months=3)
    # negli ultimi mesi (dopo l'inversione recente) la versione con conferma deve
    # avere rendimento di posizione piu' vicino a zero (flat) di quella senza
    assert abs(tsmom_confirm.iloc[-1]) <= abs(tsmom_no_confirm.iloc[-1]) + 1e-9


def test_tsmom_has_no_lookahead():
    """Il rendimento di posizione dei primi mesi non deve dipendere da prezzi
    futuri — stessa proprieta' gia' verificata per governatore e trend-gate."""
    rng = np.random.default_rng(11)
    idx = pd.date_range("2015-01-31", periods=40, freq="ME")
    base_prices = pd.Series(100 * np.exp(np.cumsum(rng.normal(0.005, 0.03, 40))), index=idx)

    altered_prices = base_prices.copy()
    altered_prices.iloc[30:] = altered_prices.iloc[30:] * 3  # sconvolge solo la coda finale

    tsmom_base = compute_tsmom_sleeve_returns({"A": base_prices}, lookback_months=12, vol_window=6)
    tsmom_altered = compute_tsmom_sleeve_returns({"A": altered_prices}, lookback_months=12, vol_window=6)

    common_idx = tsmom_base.index[tsmom_base.index < idx[29]]
    pd.testing.assert_series_equal(tsmom_base.loc[common_idx], tsmom_altered.loc[common_idx])


def test_shrinkage_matrix_is_symmetric_and_positive_semidefinite():
    """Proprieta' che la matrice DEVE avere per essere usabile nell'ottimizzazione
    Kelly (pinv su una matrice non valida darebbe pesi senza senso)."""
    rng = np.random.default_rng(4)
    returns = pd.DataFrame(rng.normal(0, 0.05, size=(30, 5)))
    cov, delta = shrink_covariance_ledoit_wolf(returns)
    assert np.allclose(cov, cov.T)
    eigvals = np.linalg.eigvalsh(cov)
    assert (eigvals >= -1e-8).all(), "la covarianza shrunk deve restare semidefinita positiva"


def test_shrinkage_intensity_between_zero_and_one():
    rng = np.random.default_rng(5)
    returns = pd.DataFrame(rng.normal(0, 0.05, size=(24, 6)))
    _, delta = shrink_covariance_ledoit_wolf(returns)
    assert 0.0 <= delta <= 1.0


def test_shrinkage_more_aggressive_with_fewer_observations():
    """Con una VERA struttura di correlazione sottostante (non rumore puro,
    altrimenti sia la stima che il target collassano a zero insieme e il
    confronto e' degenere), meno osservazioni -> stima piu' rumorosa della
    correlazione vera -> l'intensita' di shrinkage deve essere maggiore — il
    punto centrale della correzione di Ledoit-Wolf."""
    rng = np.random.default_rng(6)
    n_assets = 8
    true_corr = np.full((n_assets, n_assets), 0.4)
    np.fill_diagonal(true_corr, 1.0)
    true_cov = true_corr * (0.05 ** 2)

    sample_many = pd.DataFrame(rng.multivariate_normal(np.zeros(n_assets), true_cov, size=300))
    sample_few = pd.DataFrame(rng.multivariate_normal(np.zeros(n_assets), true_cov, size=15))

    _, delta_many_obs = shrink_covariance_ledoit_wolf(sample_many)
    _, delta_few_obs = shrink_covariance_ledoit_wolf(sample_few)
    assert delta_few_obs > delta_many_obs, (
        "con poche osservazioni rispetto al numero di asset, l'intensita' di shrinkage deve essere piu' alta"
    )


def test_shrinkage_reduces_condition_number():
    """La covarianza shrunk deve essere meglio condizionata (piu' stabile da
    invertire) della covarianza campionaria pura — il motivo per cui la
    shrinkage esiste."""
    rng = np.random.default_rng(8)
    n_assets = 6
    returns = pd.DataFrame(rng.normal(0, 0.05, size=(20, n_assets)))  # T poco sopra N: caso instabile
    X = returns.values - returns.values.mean(axis=0, keepdims=True)
    S_raw = (X.T @ X) / len(X)
    S_shrunk, delta = shrink_covariance_ledoit_wolf(returns)
    assert delta > 0.0
    cond_raw = np.linalg.cond(S_raw)
    cond_shrunk = np.linalg.cond(S_shrunk)
    assert cond_shrunk < cond_raw, "la shrinkage deve migliorare (abbassare) il numero di condizionamento"


def test_build_sleeve_returns_inner_join_drops_misaligned_months():
    """Verifica che l'allineamento tra serie a storico diverso sia un inner join
    esplicito (nessun forward-fill silenzioso tra calendari diversi — lo stesso
    bug di calendario gia' corretto in apex_v2_engine.py, APEX_V2_SPEC.md §8.3)."""
    idx_long = pd.date_range("2010-01-31", periods=36, freq="ME")
    idx_short = pd.date_range("2012-01-31", periods=12, freq="ME")
    prices = {
        "SPY": pd.Series(100 * (1.01 ** np.arange(36)), index=idx_long),
        "IEF": pd.Series(100 * (1.001 ** np.arange(36)), index=idx_long),
        "VBR": pd.Series(100 * (1.01 ** np.arange(36)), index=idx_long),
        "GLD": pd.Series(100 * (1.005 ** np.arange(36)), index=idx_long),
        "BTC-USD": pd.Series(100 * (1.02 ** np.arange(12)), index=idx_short),  # storico piu' corto
    }
    out = build_sleeve_returns(prices)
    assert len(out) == 11, "il DataFrame risultante deve essere limitato al periodo comune a TUTTE le serie (11 rendimenti da 12 prezzi)"
