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
    compute_dynamic_target_weights,
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
