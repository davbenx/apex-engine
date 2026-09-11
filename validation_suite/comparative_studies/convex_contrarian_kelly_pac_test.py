"""
convex_contrarian_kelly_pac_test.py — Idea #15 della coda ("Kelly al
contrario su Convex"), richiesta diretta dell'utente: Convex e' di fatto
un veicolo di accumulo anticiclico (compra il sottopeso ogni mese) — un
Kelly "invertito" dovrebbe sfruttare questo esplicitamente, invece di
limitarsi a colmare il deficit come oggi.

Interpretazione operativa (dichiarata prima di guardare i risultati):
Convex oggi alloca il PAC mensile con una regola WINNER-TAKE-ALL — tutto
il nuovo capitale va alla sleeve col deficit piu' grande rispetto al
target (`convex_engine.py`: `target_asset = max(deficits.items(), ...)`).
I pesi TARGET strutturali (45/15/25/7.5/7.5) restano invariati — questa
idea non li tocca (distinta da `convex_kelly_selective_trim_test.py`,
che invece li ricalcola con Kelly pro-trend). Qui cambia SOLO come si
ripartisce il nuovo capitale TRA le sleeve gia' sottopesate in un dato
mese: invece di tutto a una sola, una ripartizione pesata con Kelly
frazionario ma su un segnale CONTRARIAN (mu tanto piu' alto quanto piu'
una sleeve e' scesa di recente, l'opposto del mu pro-trend usato su
Apex) — f* = Sigma^-1 mu_contrarian, clippato a >=0, applicato pero'
SOLO alle sleeve con deficit positivo quel mese (mai "compra" una sleeve
gia' sovrapesata, coerente col water-filling reale).

mu_contrarian_i(t) = -zscore trasversale del rendimento trailing 12 mesi
tra le 5 sleeve al tempo t (rolling, nessun lookahead) — una sleeve
scesa piu' delle altre nell'ultimo anno ottiene un mu_contrarian piu'
alto. Sigma stimata una sola volta sul TRAIN (stesso principio walk-
forward di kelly_backtest.py/convex_kelly_selective_trim_test.py: mai
ri-ottimizzata sul TEST).

Tre varianti confrontate, PAC mensile modellato esplicitamente (a
differenza degli altri test Convex di questa sessione, che testano
solo il drift senza nuovi versamenti — qui il PAC E' il meccanismo sotto
test, serve simularlo):
  - "Winner-take-all (oggi)": tutto il PAC alla sleeve piu' sottopesata.
  - "Deficit-proporzionale": PAC diviso proporzionalmente al deficit tra
    le sleeve sottopesate (nessun segnale contrarian — isola il
    contributo del solo "non-winner-take-all" da quello del Kelly
    contrarian).
  - "Kelly contrarian": PAC diviso per f*_contrarian tra le sleeve
    sottopesate.
Il trim su Oro/WBTC (+50% soglia, nessun cancello) resta IDENTICO e
attivo in tutte e 3 le varianti — isola l'effetto della sola regola di
allocazione del PAC, non re-introduce la domanda gia' testata sul trim.
"""
from __future__ import annotations
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "validation_suite" / "framework"))
sys.path.insert(0, str(REPO_ROOT / "validation_suite" / "kelly_stack"))

from metrics import cagr as _cagr, sharpe as _sharpe, max_drawdown as _max_drawdown, calmar as _calmar
from statistical_validation import pbo_cscv, block_bootstrap_ci
from kelly_backtest import fetch_universe, load_monthly_series, build_sleeve_returns, BACKTEST_TICKERS, _calibrate_mu_sigma_corr
from convex_never_sell_cost_test import CURRENT_WEIGHTS, TER, TAX_TYPE, DATA_DIR

TRIM_SLEEVES = ("PPFB_proxy", "WBTC_proxy")
TOLERANCE_MULT = 1.5
TAX_RATE = 0.26
MOMENTUM_WINDOW = 12  # mesi, coerente con la cadenza trimestrale/annuale gia' usata altrove in questa sessione
MONTHLY_CONTRIBUTION = 0.01  # frazione del NAV iniziale versata ogni mese (dimensione arbitraria ma
                             # irrilevante per il confronto TRA regole, che e' relativo)


def compute_sigma(calib: pd.DataFrame, keys: list[str]) -> np.ndarray:
    _mu, sigma, corr = _calibrate_mu_sigma_corr(calib, keys, use_shrinkage=True)
    sigma_arr = np.array([sigma[k] for k in keys])
    return corr * np.outer(sigma_arr, sigma_arr)


def contrarian_mu_series(returns: pd.DataFrame, keys: list[str], window: int) -> pd.DataFrame:
    """Per ogni mese t: z-score trasversale (tra le 5 sleeve) del rendimento
    trailing `window` mesi, NEGATO — una sleeve scesa piu' delle altre ottiene
    un mu_contrarian piu' alto. Solo dati fino a t incluso (rolling, no lookahead)."""
    trailing = (1 + returns[keys]).rolling(window).apply(lambda x: x.prod() - 1.0, raw=True)
    z = trailing.sub(trailing.mean(axis=1), axis=0).div(trailing.std(axis=1, ddof=0).replace(0, np.nan), axis=0)
    return (-z).fillna(0.0)


def simulate(sleeve_returns: pd.DataFrame, mu_contrarian: pd.DataFrame, Sigma: np.ndarray, keys: list[str],
             allocation_rule: str, monthly_contribution: float = MONTHLY_CONTRIBUTION) -> pd.Series:
    values = {k: CURRENT_WEIGHTS[k] for k in keys}
    cost_basis = dict(values)
    loss_pool = 0.0

    net_returns = []
    nav_prev = sum(values.values())
    for i, (dt, row) in enumerate(sleeve_returns.iterrows()):
        for k in keys:
            values[k] *= (1.0 + row[k] - TER[k] / 12.0)
        nav_now = sum(values.values())

        # --- Trim Oro/WBTC (identico in tutte le varianti, nessun cancello) ---
        for k in TRIM_SLEEVES:
            w = values[k] / nav_now
            tgt = CURRENT_WEIGHTS[k]
            if w <= tgt * TOLERANCE_MULT:
                continue
            new_value = tgt * nav_now
            sold_gross = values[k] - new_value
            basis_sold = cost_basis[k] * (sold_gross / values[k])
            gain = sold_gross - basis_sold
            if gain > 0:
                usable_loss = min(gain, loss_pool)
                loss_pool -= usable_loss
                tax = (gain - usable_loss) * TAX_RATE
            else:
                loss_pool += -gain
                tax = 0.0
            net_proceeds = sold_gross - tax
            cost_basis[k] -= basis_sold
            values[k] = new_value
            other_keys = [o for o in keys if o != k]
            other_total = sum(values[o] for o in other_keys)
            for o in other_keys:
                share = values[o] / other_total if other_total > 1e-12 else 1.0 / len(other_keys)
                values[o] += net_proceeds * share
                cost_basis[o] += net_proceeds * share
            nav_now = sum(values.values())

        # --- PAC mensile: dove va il nuovo capitale ---
        deficits = {k: max(0.0, CURRENT_WEIGHTS[k] - values[k] / nav_now) for k in keys}
        underweight = {k: d for k, d in deficits.items() if d > 1e-9}
        contribution = monthly_contribution * 1.0  # frazione del NAV iniziale (NAV iniziale=1.0)

        if underweight:
            if allocation_rule == "winner_take_all":
                target = max(underweight, key=underweight.get)
                alloc = {target: contribution}
            elif allocation_rule == "deficit_proportional":
                total_deficit = sum(underweight.values())
                alloc = {k: contribution * d / total_deficit for k, d in underweight.items()}
            elif allocation_rule == "kelly_contrarian":
                mu_vec = np.array([mu_contrarian.iloc[i][k] if k in underweight else -1e6 for k in keys])
                try:
                    f_star = np.linalg.solve(Sigma, np.clip(mu_vec, -1e6, None))
                except np.linalg.LinAlgError:
                    f_star = np.zeros(len(keys))
                f_star = {k: max(0.0, f_star[j]) for j, k in enumerate(keys) if k in underweight}
                total_f = sum(f_star.values())
                if total_f > 1e-9:
                    alloc = {k: contribution * v / total_f for k, v in f_star.items()}
                else:  # nessun edge stimabile -> fallback deficit-proporzionale
                    total_deficit = sum(underweight.values())
                    alloc = {k: contribution * d / total_deficit for k, d in underweight.items()}
            else:
                raise ValueError(allocation_rule)
            for k, amt in alloc.items():
                values[k] += amt
                cost_basis[k] += amt
            nav_now = sum(values.values())

        net_returns.append((nav_now - contribution) / nav_prev - 1.0)  # rendimento al netto del nuovo capitale versato
        nav_prev = nav_now

    return pd.Series(net_returns, index=sleeve_returns.index)


def main():
    if not DATA_DIR.exists() or not any(DATA_DIR.glob("*_monthly.csv")):
        fetch_universe(str(DATA_DIR), BACKTEST_TICKERS)
    if not (DATA_DIR / "EURUSD=X_monthly.csv").exists():
        fetch_universe(str(DATA_DIR), ["EURUSD=X"])

    prices = load_monthly_series(str(DATA_DIR), BACKTEST_TICKERS)
    eurusd = load_monthly_series(str(DATA_DIR), ["EURUSD=X"])["EURUSD=X"]
    prices_eur = {}
    for ticker, series in prices.items():
        idx = series.index.intersection(eurusd.index)
        prices_eur[ticker] = (series.reindex(idx) / eurusd.reindex(idx)).dropna()
    sleeve_returns = build_sleeve_returns(prices_eur)
    keys = list(sleeve_returns.columns)
    print(f"Campione: {len(sleeve_returns)} mesi, {sleeve_returns.index[0].date()} -> {sleeve_returns.index[-1].date()}")

    split = len(sleeve_returns) // 2
    calib, oos = sleeve_returns.iloc[:split], sleeve_returns.iloc[split:]
    print(f"TRAIN (calibrazione Sigma): {len(calib)} mesi | TEST (OOS): {len(oos)} mesi ({oos.index[0].date()}->{oos.index[-1].date()})")

    Sigma = compute_sigma(calib, keys)
    mu_contrarian = contrarian_mu_series(sleeve_returns, keys, MOMENTUM_WINDOW)

    variants = {}
    for label, rule in [("Winner-take-all (oggi)", "winner_take_all"),
                         ("Deficit-proporzionale", "deficit_proportional"),
                         ("Kelly contrarian", "kelly_contrarian")]:
        variants[label] = simulate(sleeve_returns, mu_contrarian, Sigma, keys, rule)

    print(f"\n{'Variante':<26}{'CAGR':>9}{'Sharpe':>9}{'MaxDD':>9}{'Calmar':>9}")
    for label, net in variants.items():
        c, s, dd, cal = _cagr(net, 12), _sharpe(net, periods_per_year=12), _max_drawdown(net), _calmar(net, 12)
        print(f"{label:<26}{c*100:>8.2f}%{s:>9.2f}{dd*100:>8.2f}%{cal:>9.2f}")

    oos_idx = oos.index
    print(f"\n{'Variante (solo OOS)':<26}{'CAGR':>9}{'Sharpe':>9}{'MaxDD':>9}{'Calmar':>9}")
    for label, net in variants.items():
        sub = net.reindex(oos_idx).dropna()
        c, s, dd, cal = _cagr(sub, 12), _sharpe(sub, periods_per_year=12), _max_drawdown(sub), _calmar(sub, 12)
        print(f"{label:<26}{c*100:>8.2f}%{s:>9.2f}{dd*100:>8.2f}%{cal:>9.2f}")

    baseline_label = "Winner-take-all (oggi)"
    baseline_oos = variants[baseline_label].reindex(oos_idx)
    print(f"\nConfronto accoppiato diretto vs baseline attuale, solo OOS:")
    for label, net in variants.items():
        if label == baseline_label:
            continue
        diff = (net.reindex(oos_idx) - baseline_oos).dropna()
        mean_diff = diff.mean() * 12 * 100
        lo, hi = block_bootstrap_ci(diff.values, lambda r: pd.Series(r).mean() * 12 * 100, block_size=6, ci=0.90, seed=42)
        n_better = int((diff > 0).sum())
        print(f"  {label:<26}{mean_diff:+7.2f}pp/anno  CI90 [{lo:+.2f}, {hi:+.2f}] "
              f"({'ESCLUDE' if lo * hi > 0 else 'include'} lo zero)  settimane/mesi migliori {n_better}/{len(diff)}")

    perf_matrix = np.column_stack([variants[k].reindex(oos_idx).values for k in variants])
    n_splits = 6
    usable_len = (len(perf_matrix) // n_splits) * n_splits
    if usable_len >= n_splits * 2:
        pbo = pbo_cscv(perf_matrix[-usable_len:], n_splits=n_splits)
        print(f"\nPBO-CSCV su {len(variants)} varianti, periodo OOS: {pbo*100:.1f}%")


if __name__ == "__main__":
    main()
