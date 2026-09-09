"""
test_kelly_engine.py — Test su dati sintetici a risultato noto per kelly_engine.py,
stessa disciplina di test_apex_v2_engine.py: verificare la logica prima di collegarla
a un backend con dati reali.
"""
import numpy as np

from kelly_engine import (
    compute_kelly_weights,
    evaluate_kelly_stack,
    KELLY_SLEEVES,
    MAX_GROSS_LEVERAGE,
    KELLY_DD_DERISK_TRIGGER,
    KELLY_DD_DERISK_FLOOR,
)


def test_gross_leverage_respects_static_cap():
    """Anche con mu molto ottimistici (che spingerebbero f* ben oltre il tetto),
    la leva lorda finale non deve mai superare MAX_GROSS_LEVERAGE (spec §3, Livello 1)."""
    optimistic_mu = {k: 0.30 for k in KELLY_SLEEVES}
    res = compute_kelly_weights(mu=optimistic_mu)
    assert res.gross_leverage_final <= MAX_GROSS_LEVERAGE + 1e-9


def test_concentration_cap_limits_single_sleeve_weight():
    """L'inversione della matrice di covarianza puo' amplificare in modo estremo
    l'effetto di una singola stima di correlazione (spec §3, Livello 1bis): con mu
    ottimistici uniformi, DBMFE (quasi scorrelato con le altre sleeve) riceverebbe
    un peso Kelly enorme se non ci fosse il cap di concentrazione per singola
    sleeve — verificato che nessuna sleeve puo' comunque superare MAX_SLEEVE_WEIGHT."""
    from kelly_engine import MAX_SLEEVE_WEIGHT
    optimistic_mu = {k: 0.30 for k in KELLY_SLEEVES}
    res = compute_kelly_weights(mu=optimistic_mu)
    assert res.fractional_weights["DBMFE"] > MAX_SLEEVE_WEIGHT, (
        "questo test presuppone che lo scenario ottimistico ecceda il cap prima di applicarlo"
    )
    for w in res.concentration_capped_weights.values():
        assert abs(w) <= MAX_SLEEVE_WEIGHT + 1e-9


def test_gross_cap_preserves_proportions_among_uncapped_sleeves():
    """Il tetto di leva LORDA (Livello 1) scala proporzionalmente, non
    arbitrariamente: tra due sleeve che il cap di concentrazione (Livello 1bis)
    NON ha gia' toccato, il rapporto tra i pesi deve restare invariato dopo lo
    scaling del tetto lordo (spec §3). Scenario sintetico (non i prior di
    default, per non dipendere da valori che potrebbero cambiare): correlazione
    nulla tra le sleeve, mu uguale per tutte, sigma leggermente diversa su AVWS
    cosi' da avere un peso Kelly distinto ma comunque sotto il cap individuale."""
    keys = list(KELLY_SLEEVES.keys())
    mu = {k: 0.044 for k in keys}
    sigma = {k: 0.20 for k in keys}
    sigma["AVWS"] = 0.25  # sigma diversa -> peso Kelly diverso, isolato dalle altre 4 sleeve identiche
    corr = np.eye(len(keys))

    res = compute_kelly_weights(mu=mu, sigma=sigma, corr=corr)
    for k in keys:
        assert abs(res.concentration_capped_weights[k]) < 0.60 - 1e-6, (
            "questo scenario presuppone che nessuna sleeve tocchi il cap di concentrazione"
        )
    assert res.gross_leverage_final == 1.50, "questo scenario deve far scattare il tetto di leva lorda"

    ratio_before = res.concentration_capped_weights["NTSG"] / res.concentration_capped_weights["AVWS"]
    ratio_after = res.capped_weights["NTSG"] / res.capped_weights["AVWS"]
    assert abs(ratio_before - ratio_after) < 1e-9


def test_drawdown_trigger_halves_exposure():
    """Superata la soglia di drawdown, il fattore di scala deve essere esattamente
    KELLY_DD_DERISK_FLOOR (spec §3, Livello 2)."""
    res_normal = compute_kelly_weights(drawdown_from_peak=0.10)
    res_derisked = compute_kelly_weights(drawdown_from_peak=KELLY_DD_DERISK_TRIGGER + 0.01)
    assert res_normal.dd_scale_applied == 1.0
    assert res_derisked.dd_scale_applied == KELLY_DD_DERISK_FLOOR
    assert res_derisked.gross_leverage_final < res_normal.gross_leverage_final


def test_high_realized_vol_scales_down_exposure():
    """Un vol-target di portafoglio superato dalla volatilita' realizzata deve ridurre
    l'esposizione finale rispetto a un regime di bassa volatilita' (stesso principio
    del vol-targeting gia' validato in apex_v2_engine.py)."""
    res_calm = compute_kelly_weights(realized_vol_12m=0.08)
    res_stormy = compute_kelly_weights(realized_vol_12m=0.40)
    assert res_calm.vol_scale_applied == 1.0
    assert res_stormy.vol_scale_applied < 1.0
    assert res_stormy.gross_leverage_final < res_calm.gross_leverage_final


def test_uncorrelated_diversifier_gets_nonzero_weight():
    """Una sleeve con rendimento atteso positivo modesto ma vera diversificazione
    (bassa correlazione con le altre) deve ricevere peso Kelly positivo — verifica
    che l'ottimizzatore non collassi tutto sulla sleeve a mu piu' alto ignorando la
    correlazione (il punto centrale della sezione 2 della spec)."""
    res = compute_kelly_weights()
    assert res.raw_kelly_weights["DBMFE"] > 0, (
        "DBMFE (bassa/negativa correlazione con equity) deve avere peso Kelly positivo "
        "anche con mu_prior piu' basso delle sleeve equity"
    )


def test_zero_expected_return_gives_zero_weight_direction():
    """Se una sleeg ha mu=0 e le altre sono scorrelate da essa, il suo peso Kelly
    isolato non deve essere spinto in una direzione arbitraria dal rumore numerico."""
    mu = {k: KELLY_SLEEVES[k]["mu_prior"] for k in KELLY_SLEEVES}
    mu["PPFB"] = 0.0
    corr = np.eye(len(KELLY_SLEEVES))  # tutte scorrelate: isola l'effetto di mu=0
    res = compute_kelly_weights(mu=mu, corr=corr)
    assert abs(res.raw_kelly_weights["PPFB"]) < 1e-9


def test_evaluate_kelly_stack_weights_sum_matches_holdings():
    weights = {"NTSG": 0.40, "AVWS": 0.15, "DBMFE": 0.25, "PPFB": 0.10, "WBTC": 0.10}
    holdings = {"NTSG": 100, "AVWS": 50, "DBMFE": 80, "PPFB": 30, "WBTC": 10}
    prices = {"NTSG": 100.0, "AVWS": 50.0, "DBMFE": 25.0, "PPFB": 50.0, "WBTC": 100.0}
    rep = evaluate_kelly_stack(holdings, prices, weights, monthly_pac_eur=500.0)
    assert abs(sum(s.current_weight for s in rep.sleeves.values()) - 1.0) < 1e-9
    assert rep.pac_action is not None


def test_trim_alert_only_on_reddito_diverso():
    """Stessa regola di Convex: il trim forzato scatta solo su WBTC/PPFB
    (reddito diverso), mai su NTSG/AVWS/DBMFE (reddito di capitale) — vedi
    convex_engine.py e KELLY_STACK_SPEC.md §5."""
    weights = {"NTSG": 0.10, "AVWS": 0.10, "DBMFE": 0.10, "PPFB": 0.10, "WBTC": 0.10}
    # NTSG e WBTC entrambi enormemente sovrappesati rispetto al target (66% e 30%
    # del totale contro un target del 10% ciascuno)
    holdings = {"NTSG": 200, "AVWS": 10, "DBMFE": 10, "PPFB": 10, "WBTC": 90}
    prices = {"NTSG": 100.0, "AVWS": 50.0, "DBMFE": 25.0, "PPFB": 50.0, "WBTC": 100.0}
    rep = evaluate_kelly_stack(holdings, prices, weights, monthly_pac_eur=0.0)
    flagged = {a["asset"] for a in rep.trim_alerts}
    assert "WBTC" in flagged
    assert "NTSG" not in flagged, "NTSG e' a reddito di capitale: non deve mai generare un trim forzato"


# ------------------------------------------------------------------------------
# Verifica Monte Carlo della proprieta' centrale della spec (§2): il Kelly
# frazionario deve ridurre drasticamente la probabilita' di rovina rispetto al
# Kelly pieno, sacrificando solo una frazione della crescita attesa. Non e' un
# test sull'implementazione ma sulla logica matematica che la giustifica —
# stesso principio delle verifiche di robustezza in APEX_V2_SPEC.md §8.2.
# ------------------------------------------------------------------------------

def _simulate_terminal_wealth(leverage_multiple: float, n_years: int = 30, n_sims: int = 2000, seed: int = 7):
    """Simula ricchezza terminale su n_years per una singola scommessa equa-Kelly
    (mu=8%, sigma=16%, lognormale) a un multiplo dato del Kelly pieno (f*=mu/sigma^2)."""
    rng = np.random.default_rng(seed)
    mu, sigma = 0.08, 0.16
    f_star = mu / sigma**2
    f = f_star * leverage_multiple
    # rendimento di portafoglio con leva f su un asset lognormale: approssimazione
    # standard log(1+R_p) ~ f*mu - 0.5*f^2*sigma^2 + f*sigma*Z per anno
    annual_log_growth = f * mu - 0.5 * (f**2) * sigma**2
    annual_vol = f * sigma
    log_returns = rng.normal(annual_log_growth, annual_vol, size=(n_sims, n_years))
    terminal_log_wealth = log_returns.sum(axis=1)
    return terminal_log_wealth


def test_half_kelly_beats_full_kelly_on_ruin_probability():
    """Verifica il fatto centrale di KELLY_STACK_SPEC.md §2: mezzo-Kelly deve avere
    una probabilita' di rovina (ricchezza terminale < 10% del capitale iniziale)
    marcatamente piu' bassa del Kelly pieno su 30 anni, sacrificando solo una parte
    della crescita mediana attesa — non un pareggio, la asimmetria dichiarata nella
    spec."""
    ruin_threshold_log = np.log(0.10)  # ricchezza scesa sotto il 10% del capitale iniziale

    full_kelly = _simulate_terminal_wealth(leverage_multiple=1.0)
    half_kelly = _simulate_terminal_wealth(leverage_multiple=0.5)

    ruin_prob_full = float(np.mean(full_kelly < ruin_threshold_log))
    ruin_prob_half = float(np.mean(half_kelly < ruin_threshold_log))

    assert ruin_prob_half < ruin_prob_full, (
        "mezzo-Kelly deve avere probabilita' di rovina inferiore al Kelly pieno su orizzonte lungo"
    )
    # mezzo-Kelly deve comunque mantenere una parte sostanziale della crescita mediana
    median_growth_full = float(np.median(full_kelly))
    median_growth_half = float(np.median(half_kelly))
    assert median_growth_half > 0.5 * median_growth_full, (
        "mezzo-Kelly non deve sacrificare piu' della meta' della crescita mediana del Kelly pieno"
    )


def test_overbetting_beyond_full_kelly_reduces_growth():
    """Verifica il 'fatto cruciale asimmetrico' della spec §2: scommettere PIU' del
    Kelly pieno (2x) deve avere crescita mediana attesa inferiore al Kelly pieno
    stesso — non solo piu' rischio, proprio meno crescita."""
    full_kelly = _simulate_terminal_wealth(leverage_multiple=1.0)
    over_kelly = _simulate_terminal_wealth(leverage_multiple=2.0)
    assert np.median(over_kelly) < np.median(full_kelly), (
        "2x Kelly deve avere crescita mediana attesa inferiore a Kelly pieno (il denominatore sigma^2 domina)"
    )
