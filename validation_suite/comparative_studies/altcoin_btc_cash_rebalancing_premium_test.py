"""
altcoin_btc_cash_rebalancing_premium_test.py — "Rebalancing premium" /
volatility harvesting (Shannon's Demon: Fernholz & Shay 1982, Willenbrock
2011) su un mix fisso BTC/cash, richiesto esplicitamente dall'utente come
strategia accademica non ancora provata sull'universo crypto.

Idea accademica: ribilanciare periodicamente un mix di un asset volatile
(BTC) e un asset piatto (cash, rendimento 0) verso pesi fissi (qui 50/50)
puo' aggiungere rendimento "comprando basso, vendendo alto" in automatico —
l'effetto e' piu' forte quanto piu' alta e' la vol dell'asset rischioso,
quindi BTC (vol annualizzata storica ~55-70%) e' un candidato quasi ideale
per isolare l'effetto.

In Italia ogni ribilanciamento verso BTC (vendere cash, comprare BTC: nessun
evento fiscale, il cash non genera plusvalenze) o vendere BTC (evento
fiscale, 26% su reddito diverso) e' asimmetrico — il costo fiscale del
"vendi alto" puo' erodere il premio. Confronto NETTO di tasse, non lordo.

Usa tax_engine.apply_italian_tax direttamente (target fisso 50/50, non un
DataFrame dinamico) con rebalance_every (calendario) e rebalance_threshold
(soglia di tolleranza, stesso meccanismo gia' validato su Convex in
convex_threshold_vs_calendar_rebalance_test.py) — stesso BTC daily
2019-10+ usato in altcoin_btc_vol_targeting_test.py, nessuna leva.
"""
from __future__ import annotations
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "framework"))
from metrics import cagr, sharpe, max_drawdown, calmar
from tax_engine import apply_italian_tax
from statistical_validation import pbo_cscv, block_bootstrap_ci
from altcoin_vs_btc_daily_backtest import DATA_DIR, PERIODS_PER_YEAR, fetch_all_price_data, load_daily

TARGET_WEIGHTS = {"BTC-USD": 0.5, "CASH": 0.5}
TAX_TYPES = {"BTC-USD": "REDDITO_DIVERSO", "CASH": "REDDITO_DIVERSO"}

CALENDAR_VARIANTS = [
    ("Mai (buy&hold 50/50 iniziale)", {"rebalance_every": None}),
    ("Giornaliero (calendario)", {"rebalance_every": 1}),
    ("Settimanale (calendario)", {"rebalance_every": 7}),
    ("Mensile equiv. (calendario, 30gg)", {"rebalance_every": 30}),
]
THRESHOLD_VARIANTS = [
    ("Soglia 3 punti peso", {"rebalance_threshold": 0.03}),
    ("Soglia 5 punti peso", {"rebalance_threshold": 0.05}),
    ("Soglia 10 punti peso", {"rebalance_threshold": 0.10}),
    ("Soglia 15 punti peso", {"rebalance_threshold": 0.15}),
    ("Soglia 20 punti peso", {"rebalance_threshold": 0.20}),
]
ALL_VARIANTS = CALENDAR_VARIANTS + THRESHOLD_VARIANTS


def main():
    if not (DATA_DIR / "BTC_USD_daily.csv").exists():
        print(f"[*] Nessun dato in cache in {DATA_DIR}, scarico da Yahoo Finance...")
        fetch_all_price_data()

    px = load_daily("BTC-USD")
    btc_ret = px.pct_change().dropna()
    btc_ret = btc_ret.loc[btc_ret.index >= pd.Timestamp("2019-10-01")]
    returns_df = pd.DataFrame({"BTC-USD": btc_ret, "CASH": 0.0})
    print(f"Simulazione daily BTC/cash 50/50: {len(returns_df)} giorni, "
          f"{returns_df.index[0].date()} -> {returns_df.index[-1].date()}")

    results = {}
    for label, kwargs in ALL_VARIANTS:
        net = apply_italian_tax(returns_df, TARGET_WEIGHTS, tax_types=TAX_TYPES, **kwargs)
        results[label] = {
            "net": net, "cagr": cagr(net, PERIODS_PER_YEAR), "sharpe": sharpe(net, periods_per_year=PERIODS_PER_YEAR),
            "maxdd": max_drawdown(net), "calmar": calmar(net, PERIODS_PER_YEAR),
        }

    print(f"\n{'Variante':<36}{'CAGR netto':>12}{'Sharpe netto':>14}{'MaxDD netto':>13}{'Calmar netto':>14}")
    for label, r in results.items():
        print(f"{label:<36}{r['cagr']*100:>11.2f}%{r['sharpe']:>14.3f}{r['maxdd']*100:>12.2f}%{r['calmar']:>14.3f}")

    never_label = CALENDAR_VARIANTS[0][0]
    best_label = max(results, key=lambda k: results[k]["sharpe"])
    print(f"\nMigliore per Sharpe netto: {best_label} (Sharpe {results[best_label]['sharpe']:.3f} "
          f"contro {results[never_label]['sharpe']:.3f} del mai-ribilanciare)")

    diff = (results[best_label]["net"] - results[never_label]["net"]).dropna()
    mean_diff = diff.mean() * PERIODS_PER_YEAR * 100
    lo, hi = block_bootstrap_ci(diff.values, lambda r: pd.Series(r).mean() * PERIODS_PER_YEAR * 100,
                                 block_size=30, ci=0.90, seed=42)
    print(f"{best_label} meno Mai: {mean_diff:+.2f}pp/anno, CI90 [{lo:+.2f}, {hi:+.2f}] "
          f"({'ESCLUDE' if lo * hi > 0 else 'include'} lo zero)")

    perf_matrix = np.column_stack([results[label]["net"].values for label, _ in ALL_VARIANTS])
    n_splits = 8
    usable_len = (len(perf_matrix) // n_splits) * n_splits
    pbo = pbo_cscv(perf_matrix[-usable_len:], n_splits=n_splits)
    print(f"\nPBO-CSCV su {len(ALL_VARIANTS)} varianti (calendario + soglia): {pbo*100:.1f}%")


if __name__ == "__main__":
    main()
