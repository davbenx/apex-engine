"""
test_tax_engine.py — verifica su scenari sintetici a comportamento noto di
apply_italian_tax (framework/tax_engine.py). Estratti da test_kelly_backtest.py:
questa funzione e' generica, non specifica a Kelly Stack, ora vive e si testa
nel framework condiviso. Unica differenza rispetto all'originale: tax_types
qui e' sempre passato esplicitamente (la funzione generica non ha un fallback
implicito ai nomi delle sleeve di Kelly Stack).
"""
import numpy as np
import pandas as pd

from tax_engine import apply_italian_tax, liquidation_tax_adjusted_nav, TAX_RATE_ITALY_FLAT


def test_italian_tax_capital_income_pays_flat_26_on_realized_gain_only():
    """Sleeve unica a reddito di capitale, cresce ininterrottamente: il
    ribilanciamento mensile verso peso fisso 100% non vende nulla (nessun
    eccesso rispetto al target), quindi non deve scattare tassazione fino a
    che non c'e' un secondo asset che assorbe l'eccesso."""
    returns = pd.DataFrame({"A": [0.10, 0.10], "B": [0.0, 0.0]})
    net = apply_italian_tax(returns, {"A": 0.5, "B": 0.5}, tax_types={"A": "REDDITO_CAPITALE", "B": "REDDITO_CAPITALE"})
    # A cresce, B resta fermo -> il ribilanciamento VENDE una parte di A (reddito capitale)
    # per riportarla al 50% -> deve scattare una tassa positiva su quel guadagno
    gross = (returns["A"] * 0.5 + returns["B"] * 0.5)
    assert (1 + net).prod() < (1 + gross).prod(), "la tassazione deve ridurre il rendimento netto rispetto al lordo"


def test_italian_tax_reddito_diverso_offsets_loss_against_later_gain():
    """Sleeve a reddito diverso: una minusvalenza realizzata deve compensare una
    plusvalenza successiva, riducendo la tassa dovuta rispetto al caso senza
    compensazione (verificato per confronto tra due scenari)."""
    keys = {"WBTC_proxy": 0.5, "PPFB_proxy": 0.5}
    tax_types = {"WBTC_proxy": "REDDITO_DIVERSO", "PPFB_proxy": "REDDITO_DIVERSO"}
    # scenario con perdita poi guadagno (compensazione possibile)
    returns_with_loss = pd.DataFrame({
        "WBTC_proxy": [-0.30, 0.50, 0.10],
        "PPFB_proxy": [0.0, 0.0, 0.0],
    })
    net = apply_italian_tax(returns_with_loss, keys, tax_types=tax_types)
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
    deployato da Kelly Stack), la tassazione non deve MAI produrre una crescita
    netta superiore alla crescita lorda, e i due ordini di grandezza devono
    restare comparabili — bug reale trovato durante lo sviluppo: confondere
    valore nozionale delle posizioni (che con leva supera il NAV) con il NAV
    stesso produceva un errore di scala composto ogni mese, CAGR netto >10.000%."""
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
    tax_types = {
        "NTSG_proxy": "REDDITO_CAPITALE", "AVWS_proxy": "REDDITO_CAPITALE", "DBMFE_proxy": "REDDITO_CAPITALE",
        "PPFB_proxy": "REDDITO_DIVERSO", "WBTC_proxy": "REDDITO_DIVERSO",
    }
    assert sum(weights.values()) > 1.0, "questo test presuppone leva (somma pesi > 100%)"

    net = apply_italian_tax(returns, weights, tax_types=tax_types)
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


def test_rebalance_every_none_never_taxes_and_matches_gross_drift():
    """rebalance_every=None: mai ribilanciare dopo l'allocazione iniziale —
    nessuna vendita, quindi nessuna tassa MAI, a prescindere da quanto le
    posizioni divergano dal peso iniziale. Il netto deve combaciare col
    lordo a pesi FISSI iniziali (nessun drift di peso modellato nel
    confronto lordo qui sotto, quindi la crescita netta risultante deve
    essere quella di un vero buy-and-hold, non quella di un portafoglio
    ribilanciato)."""
    returns = pd.DataFrame({"A": [0.20, 0.20, 0.20], "B": [0.0, 0.0, 0.0]})
    weights = {"A": 0.5, "B": 0.5}
    tax_types = {"A": "REDDITO_CAPITALE", "B": "REDDITO_CAPITALE"}
    net = apply_italian_tax(returns, weights, tax_types=tax_types, rebalance_every=None)
    # Buy-and-hold vero: 0.5 unita' di A cresce (1.2)^3, 0.5 di B resta ferma.
    expected_final_nav = 0.5 * (1.2 ** 3) + 0.5 * 1.0
    assert abs(float((1 + net).prod()) - expected_final_nav) < 1e-9


def test_rebalance_every_n_only_taxes_on_scheduled_periods():
    """rebalance_every=3: nessun evento fiscale nei periodi 1-2 (nessuna
    vendita), un solo evento al periodo 3 — il netto deve combaciare col
    lordo nei primi due periodi (nessuna tassa ancora prelevata) e scendere
    sotto il lordo cumulato solo a partire dal terzo."""
    returns = pd.DataFrame({"A": [0.10, 0.10, 0.10], "B": [0.0, 0.0, 0.0]})
    weights = {"A": 0.5, "B": 0.5}
    tax_types = {"A": "REDDITO_CAPITALE", "B": "REDDITO_CAPITALE"}
    net = apply_italian_tax(returns, weights, tax_types=tax_types, rebalance_every=3)
    # Senza ribilanciamento (periodi 1-2) il rendimento e' quello di un vero
    # buy-and-hold col DRIFT dei pesi (A pesa via via di piu' perche' cresce e
    # B no) — non il rendimento a pesi fissi ricalcolato ogni periodo, che e'
    # una cifra diversa e piu' bassa.
    true_bh_growth_2p = 0.5 * (1.10 ** 2) + 0.5 * 1.0
    assert abs(float((1 + net.iloc[:2]).prod()) - true_bh_growth_2p) < 1e-9, (
        "nei periodi prima del ribilanciamento programmato non deve scattare alcuna tassa "
        "(il rendimento deve essere quello del drift, non quello a pesi fissi ricalcolati)"
    )
    true_bh_growth_3p_notax = 0.5 * (1.10 ** 3) + 0.5 * 1.0  # drift puro, IPOTETICO senza tassa al ribilanciamento
    assert float((1 + net).prod()) < true_bh_growth_3p_notax, (
        "al terzo periodo (ribilanciamento programmato) la tassa sul guadagno di A realizzato "
        "deve far scendere il netto sotto il drift puro senza tassa"
    )


def test_rebalance_threshold_never_triggers_when_drift_stays_inside_band():
    """Soglia molto larga (50 punti di peso): il drift realistico di un
    portafoglio A/B non la raggiunge mai -> nessun ribilanciamento, stesso
    risultato di rebalance_every=None (mai ribilanciare)."""
    returns = pd.DataFrame({"A": [0.10, 0.10, 0.10], "B": [0.0, 0.0, 0.0]})
    weights = {"A": 0.5, "B": 0.5}
    tax_types = {"A": "REDDITO_CAPITALE", "B": "REDDITO_CAPITALE"}
    net_threshold = apply_italian_tax(returns, weights, tax_types=tax_types, rebalance_threshold=0.50)
    net_never = apply_italian_tax(returns, weights, tax_types=tax_types, rebalance_every=None)
    pd.testing.assert_series_equal(net_threshold, net_never)


def test_rebalance_threshold_triggers_as_soon_as_drift_exceeds_band():
    """Soglia stretta (2 punti di peso): A si allontana dal 50% target gia'
    al primo periodo (cresce del 10%, B resta fermo) -> deve scattare un
    ribilanciamento (quindi una tassa) al primo periodo stesso, non dopo."""
    returns = pd.DataFrame({"A": [0.10, 0.0], "B": [0.0, 0.0]})
    weights = {"A": 0.5, "B": 0.5}
    tax_types = {"A": "REDDITO_CAPITALE", "B": "REDDITO_CAPITALE"}
    net = apply_italian_tax(returns, weights, tax_types=tax_types, rebalance_threshold=0.02)
    true_bh_growth_1p_notax = 0.5 * 1.10 + 0.5 * 1.0
    assert float(1 + net.iloc[0]) < true_bh_growth_1p_notax, (
        "con una soglia stretta gia' superata al primo periodo, la tassa sul ribilanciamento "
        "deve far scendere il netto sotto il drift puro senza tassa"
    )


def test_rebalance_threshold_takes_precedence_over_rebalance_every():
    """Se entrambi sono passati, rebalance_threshold vince — rebalance_every
    deve essere ignorato, non combinato."""
    returns = pd.DataFrame({"A": [0.10, 0.0, 0.0], "B": [0.0, 0.0, 0.0]})
    weights = {"A": 0.5, "B": 0.5}
    tax_types = {"A": "REDDITO_CAPITALE", "B": "REDDITO_CAPITALE"}
    net_both = apply_italian_tax(returns, weights, tax_types=tax_types, rebalance_every=1, rebalance_threshold=0.50)
    net_threshold_only = apply_italian_tax(returns, weights, tax_types=tax_types, rebalance_threshold=0.50)
    pd.testing.assert_series_equal(net_both, net_threshold_only)


def test_return_final_state_default_off_keeps_original_return_type():
    """return_final_state=False (default): deve restituire ESATTAMENTE una
    pd.Series come prima di questo fix, non una tupla — nessuna regressione
    per i chiamanti esistenti che non passano questo argomento."""
    returns = pd.DataFrame({"A": [0.10, 0.10], "B": [0.0, 0.0]})
    net = apply_italian_tax(returns, {"A": 0.5, "B": 0.5}, tax_types={"A": "REDDITO_CAPITALE", "B": "REDDITO_CAPITALE"})
    assert isinstance(net, pd.Series)


def test_liquidation_tax_adjusted_nav_matches_zero_gain_case():
    """Nessuna plusvalenza mai maturata (rendimento sempre zero): il NAV
    liquidato deve combaciare col NAV grezzo, nessuna tassa dovuta."""
    returns = pd.DataFrame({"A": [0.0, 0.0], "B": [0.0, 0.0]})
    weights = {"A": 0.5, "B": 0.5}
    tax_types = {"A": "REDDITO_CAPITALE", "B": "REDDITO_CAPITALE"}
    net, final_state = apply_italian_tax(returns, weights, tax_types=tax_types, rebalance_every=None, return_final_state=True)
    liquidated = liquidation_tax_adjusted_nav(final_state, tax_types)
    assert abs(liquidated - final_state["nav"]) < 1e-9


def test_liquidation_tax_adjusted_nav_taxes_the_latent_gain_never_sold():
    """rebalance_every=None su una sleeve REDDITO_CAPITALE che cresce senza
    mai vendere: apply_italian_tax non tassa MAI (verificato altrove), ma
    liquidation_tax_adjusted_nav deve rendere esplicita la tassa LATENTE —
    il NAV liquidato deve essere STRETTAMENTE inferiore al NAV grezzo
    (drift puro) di un importo pari al 26% della plusvalenza non realizzata."""
    returns = pd.DataFrame({"A": [0.20, 0.20, 0.20]})
    weights = {"A": 1.0}
    tax_types = {"A": "REDDITO_CAPITALE"}
    net, final_state = apply_italian_tax(returns, weights, tax_types=tax_types, rebalance_every=None, return_final_state=True)
    drift_nav = float((1 + net).prod())  # nessuna tassa mai realizzata, quindi = drift puro
    liquidated = liquidation_tax_adjusted_nav(final_state, tax_types)
    expected_gain = final_state["value"]["A"] - final_state["cost_basis"]["A"]
    expected_liquidated = drift_nav - expected_gain * TAX_RATE_ITALY_FLAT
    assert liquidated < drift_nav - 1e-9
    assert abs(liquidated - expected_liquidated) < 1e-9


def test_liquidation_tax_adjusted_nav_offsets_diverso_gain_with_loss_pool():
    """Una minusvalenza REDDITO_DIVERSO gia' accumulata nel loss_pool deve
    compensare la plusvalenza latente alla liquidazione finale, esattamente
    come farebbe una compensazione realizzata durante il percorso."""
    keys = {"BTC_proxy": 0.5, "ALT_proxy": 0.5}
    tax_types = {"BTC_proxy": "REDDITO_DIVERSO", "ALT_proxy": "REDDITO_DIVERSO"}
    # ALT_proxy realizza una minusvalenza al mese 1 (ribilanciamento mensile normale),
    # poi entrambe crescono senza piu' vendite (rebalance_every=2 = un solo evento).
    returns = pd.DataFrame({
        "BTC_proxy": [0.0, 0.30],
        "ALT_proxy": [-0.40, 0.10],
    })
    net, final_state = apply_italian_tax(returns, keys, tax_types=tax_types, rebalance_every=2, return_final_state=True)
    liquidated_with_pool = liquidation_tax_adjusted_nav(final_state, tax_types)
    # Confronto: stesso stato finale ma SENZA loss_pool accumulato -> tassa piena sul gain
    final_state_no_pool = dict(final_state)
    final_state_no_pool["loss_pool_diverso"] = 0.0
    liquidated_without_pool = liquidation_tax_adjusted_nav(final_state_no_pool, tax_types)
    assert liquidated_with_pool >= liquidated_without_pool - 1e-9, (
        "con un loss_pool disponibile la tassa alla liquidazione non deve mai essere superiore "
        "a quella senza pool di compensazione"
    )


def test_rebalance_every_default_matches_historical_every_period_behavior():
    """Il default (rebalance_every=1) deve produrre ESATTAMENTE lo stesso
    risultato di prima di questo fix (la funzione ribilanciava ogni periodo
    incondizionatamente, il parametro esisteva nella firma ma non veniva mai
    letto) — nessuna regressione per i chiamanti esistenti che non passano
    questo argomento."""
    returns = pd.DataFrame({"A": [0.10, -0.05, 0.08], "B": [0.0, 0.02, -0.01]})
    weights = {"A": 0.5, "B": 0.5}
    tax_types = {"A": "REDDITO_CAPITALE", "B": "REDDITO_DIVERSO"}
    net_default = apply_italian_tax(returns, weights, tax_types=tax_types)
    net_explicit = apply_italian_tax(returns, weights, tax_types=tax_types, rebalance_every=1)
    pd.testing.assert_series_equal(net_default, net_explicit)
