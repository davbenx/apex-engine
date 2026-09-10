"""
apex_equity_long_short_overlay_test.py — Idea diretta dell'utente: Apex oggi
e' long/flat (Equity ON con peso positivo, o Cash quando il trend e'
sfavorevole) — andare anche SHORT quando il trend e' chiaramente ribassista
("avere sempre qualcosa da cui guadagnare in qualunque situazione") puo'
migliorare la strategia? Testato con dati REALI di ProShares Short S&P500
(SH, -1x) — non un proxy sintetico "rendimento SPY negato", che ignorerebbe
il decadimento da ribilanciamento giornaliero (reale, non trascurabile nei
mercati laterali/volatili) e le fee reali dell'ETF.

Segnale long/short simmetrico costruito SOLO in questo script (nessuna
modifica a compute_v2_macro_signal, che resta long/flat in produzione):
mirror simmetrico della stessa logica di isteresi + conferma multi-timeframe
gia' in produzione, applicata SOLO alla classe Equities (le altre 3 classi
restano long/flat esattamente come oggi). Stati {LONG, SHORT, CASH} invece
di {ON, OFF}:
  - da LONG: resta LONG se dist > -banda, altrimenti passa a SHORT se
    dist < -banda, altrimenti CASH (zona morta simmetrica)
  - da SHORT: resta SHORT se dist < +banda, altrimenti passa a LONG se
    dist > +banda, altrimenti CASH
  - da CASH: entra LONG se dist > banda, SHORT se dist < -banda
  - conferma multi-timeframe simmetrica: LONG richiede prezzo > MA20w
    (come in produzione), SHORT richiede prezzo < MA20w (nuovo, mirror)

Dimensione della posizione SHORT: stesso |base_weight_per_class| e stesso
vol-target della gamba LONG (usa la volatilita' realizzata di SPY, che SH
replica quasi esattamente in valore assoluto essendo un -1x giornaliero).

Rendimento SHORT realizzato: rendimento REALE di SH (non -1 x rendimento SPY)
— incorpora fee reali (~0.89% annuo) e decadimento da ribilanciamento
giornaliero, dichiarato non nascosto.
"""

from __future__ import annotations
import json
import sys
from pathlib import Path
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "validation_suite" / "framework"))
from apex_v2_engine import (
    select_low_vol_basket, V2_MAX_PER_SECTOR, V2_CLASS_TICKER, V2_MA_WEEKS, V2_SHORT_MA_WEEKS,
    V2_HYSTERESIS_K, V2_HYSTERESIS_MIN, V2_HYSTERESIS_MAX, V2_VOL_WINDOW, V2_VOL_TARGET,
    _weekly_close, _realized_vol,
)
from metrics import cagr as _cagr, sharpe as _sharpe, max_drawdown as _max_drawdown
from tax_engine import apply_italian_tax as _apply_italian_tax
from statistical_validation import deflated_sharpe_ratio, block_bootstrap_ci
from apex_stocks_vs_etf_backtest import (
    DATA_DIR, PERIODS_PER_YEAR, load_weekly_macro, load_weekly_sp500, load_pointintime_snapshots,
    eligible_universe_for_year, build_ohlc_like, _fetch_weekly_adj,
)
from sector_cap_grid_test import SECTOR_MAP_FILE


def fetch_sh() -> None:
    _fetch_weekly_adj("SH", "15y").to_csv(DATA_DIR / "SH_weekly.csv")


def compute_signal_long_short(
    b_data: Dict[str, pd.DataFrame],
    prev_state: Optional[Dict[str, str]] = None,
    long_short_classes: Optional[set] = None,
    base_weight_per_class: float = 0.50,
    vol_target: float = V2_VOL_TARGET,
) -> Tuple[Dict[str, float], Dict[str, str], Dict[str, dict]]:
    """Mirror simmetrico di compute_v2_macro_signal: le classi in long_short_classes
    possono assumere peso NEGATIVO (short) invece di solo 0/positivo. Le altre
    classi restano long/flat identiche alla produzione. Non tocca apex_v2_engine.py."""
    long_short_classes = long_short_classes or set()
    state: Dict[str, str] = dict(prev_state) if prev_state else {}
    signed_weight: Dict[str, float] = {}
    debug: Dict[str, dict] = {}
    vols: Dict[str, float] = {}

    for cls, ticker in V2_CLASS_TICKER.items():
        wc = _weekly_close(b_data.get(ticker))
        v = _realized_vol(wc, V2_VOL_WINDOW)
        if v is not None:
            vols[cls] = v

    for cls, ticker in V2_CLASS_TICKER.items():
        df = b_data.get(ticker)
        wc = _weekly_close(df)
        if len(wc) < V2_MA_WEEKS:
            signed_weight[cls] = 0.0
            debug[cls] = {"note": "dati insufficienti"}
            continue

        ma_long = wc.rolling(V2_MA_WEEKS, min_periods=V2_MA_WEEKS).mean()
        ma_short = wc.rolling(V2_SHORT_MA_WEEKS, min_periods=V2_SHORT_MA_WEEKS).mean()
        price = float(wc.iloc[-1])
        ma_long_val = float(ma_long.iloc[-1])
        ma_short_val = float(ma_short.iloc[-1]) if not np.isnan(ma_short.iloc[-1]) else ma_long_val
        dist = (price / ma_long_val - 1.0) if ma_long_val > 0 else 0.0

        wk_vol = (vols[cls] / float(np.sqrt(52))) if cls in vols else 0.02
        band = float(max(V2_HYSTERESIS_MIN, min(V2_HYSTERESIS_MAX, V2_HYSTERESIS_K * wk_vol)))

        if cls not in long_short_classes:
            was_active = bool(state.get(cls) == "LONG")
            trend_long_on = (dist > -band) if was_active else (dist > band)
            trend_short_confirm = price > ma_short_val if ma_short_val > 0 else False
            new_state = "LONG" if (trend_long_on and trend_short_confirm) else "CASH"
            state[cls] = "LONG" if trend_long_on else "CASH"
        else:
            was_state = state.get(cls, "CASH")
            if was_state == "LONG":
                new_state = "LONG" if dist > -band else ("SHORT" if dist < -band else "CASH")
            elif was_state == "SHORT":
                new_state = "SHORT" if dist < band else ("LONG" if dist > band else "CASH")
            else:
                new_state = "LONG" if dist > band else ("SHORT" if dist < -band else "CASH")

            if new_state == "LONG" and not (price > ma_short_val > 0):
                new_state = "CASH"
            if new_state == "SHORT" and not (0 < price < ma_short_val):
                new_state = "CASH"
            state[cls] = new_state

        signed_weight[cls] = base_weight_per_class if new_state == "LONG" else (
            -base_weight_per_class if new_state == "SHORT" else 0.0)
        debug[cls] = {"price": price, "ma40w": ma_long_val, "ma20w": ma_short_val,
                       "distanza_pct": round(dist * 100, 2), "stato": new_state}

    port_vol = sum(abs(signed_weight.get(cls, 0.0)) * vols[cls] for cls in V2_CLASS_TICKER if cls in vols)
    scale = min(1.0, vol_target / port_vol) if port_vol > 1e-6 else 1.0
    raw_weights = {cls: signed_weight.get(cls, 0.0) * scale for cls in V2_CLASS_TICKER}
    total_raw_abs = sum(abs(w) for w in raw_weights.values())
    if total_raw_abs > 1.0:
        raw_weights = {cls: w / total_raw_abs for cls, w in raw_weights.items()}

    allocations = {cls: round(raw_weights.get(cls, 0.0) * 100.0, 2) for cls in V2_CLASS_TICKER}
    return allocations, state, debug


def run_backtest(long_short_classes: set, sector_of: dict, base_weight: float = 0.50, vol_target: float = 0.22):
    snapshots = load_pointintime_snapshots()
    with open(DATA_DIR / "sp500_tickers.json") as f:
        all_tickers = json.load(f)
    stock_prices = {}
    for t in all_tickers:
        try:
            stock_prices[t] = load_weekly_sp500(t)
        except FileNotFoundError:
            continue
    stock_rets = {t: p.pct_change() for t, p in stock_prices.items()}

    macro_prices = {V2_CLASS_TICKER[c]: load_weekly_macro(V2_CLASS_TICKER[c]) for c in V2_CLASS_TICKER}
    sh_price = load_weekly_macro("SH")
    common_index = macro_prices["SPY"].index.intersection(sh_price.index)
    for s in macro_prices.values():
        common_index = common_index.intersection(s.index)
    weeks = list(common_index)
    n = len(weeks)

    ief_ret = macro_prices["IEF"].pct_change()
    gld_ret = macro_prices["GLD"].pct_change()
    btc_ret = macro_prices["BTC-USD"].pct_change()
    spy_ret = macro_prices["SPY"].pct_change()
    sh_ret = sh_price.pct_change()

    state, prev_basket_tickers, current_basket = None, None, []
    locked_alloc = None
    macro_alloc_history, equity_basket_ret_hist = [], []

    MIN_HISTORY = 40
    for i, wk in enumerate(weeks):
        if i < MIN_HISTORY:
            macro_alloc_history.append(None)
            equity_basket_ret_hist.append(0.0)
            continue

        b_data = {V2_CLASS_TICKER[c]: build_ohlc_like(macro_prices[V2_CLASS_TICKER[c]].loc[:wk]) for c in V2_CLASS_TICKER}
        alloc, state, _debug = compute_signal_long_short(
            b_data, prev_state=state, long_short_classes=long_short_classes,
            base_weight_per_class=base_weight, vol_target=vol_target,
        )
        is_month_end = (i + 1 >= n) or (weeks[i + 1].month != wk.month)
        if locked_alloc is None:
            locked_alloc = alloc
        macro_alloc_history.append(dict(locked_alloc))
        if is_month_end:
            locked_alloc = alloc

        def rebuild_basket():
            eligible = eligible_universe_for_year(snapshots, wk.year)
            eq_data = {t: build_ohlc_like(p.loc[:wk]) for t, p in stock_prices.items() if t in eligible}
            basket = select_low_vol_basket(eq_data, prev_tickers=prev_basket_tickers, sector_of=sector_of, max_per_sector=V2_MAX_PER_SECTOR)
            return [b["Ticker"] for b in basket]

        if not current_basket:
            current_basket = rebuild_basket()
            prev_basket_tickers = set(current_basket)
        elif is_month_end and wk.month in (3, 6, 9, 12):
            current_basket = rebuild_basket()
            prev_basket_tickers = set(current_basket)

        basket_ret = float(np.mean([stock_rets[t].loc[wk] for t in current_basket if t in stock_rets])) if current_basket else 0.0
        equity_basket_ret_hist.append(basket_ret)

    valid_from = MIN_HISTORY
    idx = weeks[valid_from:]

    def alloc_signed_frac(cls):
        return pd.Series([macro_alloc_history[i].get(cls, 0.0) / 100.0 for i in range(valid_from, n)], index=idx)

    w_equity = alloc_signed_frac("Equities")
    # Quando la classe Equities e' LONG (peso positivo) realizza il basket low-vol
    # REALE come in produzione; quando e' SHORT (peso negativo) realizza il
    # rendimento REALE di SH — mai un -1x sintetico del basket o di SPY.
    equity_ret = pd.Series(
        np.where(w_equity.values >= 0, np.array(equity_basket_ret_hist[valid_from:]), sh_ret.reindex(idx).fillna(0.0).values),
        index=idx,
    )
    # Il contributo al portafoglio e' |peso| x rendimento del veicolo effettivamente
    # detenuto (basket se long, SH se short) — il segno di w_equity indica giu' SOLO
    # la direzione della scommessa, l'esposizione economica e' sempre |peso|.
    weights_df = pd.DataFrame({
        "Equity": w_equity.abs(), "Bonds": alloc_signed_frac("Bonds"),
        "Gold": alloc_signed_frac("Gold"), "Crypto": alloc_signed_frac("Crypto"),
    })
    returns_df = pd.DataFrame({
        "Equity": equity_ret, "Bonds": ief_ret.reindex(idx).fillna(0.0),
        "Gold": gld_ret.reindex(idx).fillna(0.0), "Crypto": btc_ret.reindex(idx).fillna(0.0),
    })
    tax_types = {"Equity": "REDDITO_DIVERSO", "Bonds": "REDDITO_CAPITALE", "Gold": "REDDITO_DIVERSO", "Crypto": "REDDITO_DIVERSO"}

    weight_change = weights_df.diff().abs().sum(axis=1).fillna(0.0)
    # side-switch (LONG->SHORT o viceversa) e' un turnover ADDIZIONALE (si chiude e riapre la
    # posizione, costo doppio) non catturato da |peso| se il modulo resta simile — aggiunto esplicitamente
    side_flip = (np.sign(w_equity).diff().abs() > 1).astype(float).reindex(idx).fillna(0.0)
    cost_bps_map = {"Equity": 0.0010, "Bonds": 0.0008, "Gold": 0.0010, "Crypto": 0.0010}
    cost_drag = weight_change * np.mean(list(cost_bps_map.values())) + side_flip * w_equity.abs() * 0.0010
    port_net = _apply_italian_tax(returns_df, weights_df, tax_types=tax_types)
    port_net_after_costs = port_net - cost_drag

    return {
        "net": port_net_after_costs,
        "cagr_netto": _cagr(port_net_after_costs, PERIODS_PER_YEAR),
        "sharpe_netto": _sharpe(port_net_after_costs, periods_per_year=PERIODS_PER_YEAR),
        "maxdd_netto": _max_drawdown(port_net_after_costs),
        "w_equity": w_equity,
    }


def main():
    if not (DATA_DIR / "SH_weekly.csv").exists():
        print("[*] Scarico SH (ProShares Short S&P500) da Yahoo Finance...")
        fetch_sh()

    sector_of = json.load(open(SECTOR_MAP_FILE))

    print(f"{'Variante':<55}{'CAGR netto':>12}{'Sharpe netto':>14}{'MaxDD netto':>13}{'Calmar':>9}")
    baseline = run_backtest(long_short_classes=set(), sector_of=sector_of)
    calmar_b = baseline["cagr_netto"] / abs(baseline["maxdd_netto"])
    print(f"{'Baseline long/flat (produzione)':<55}{baseline['cagr_netto']*100:>11.2f}%{baseline['sharpe_netto']:>14.2f}"
          f"{baseline['maxdd_netto']*100:>12.2f}%{calmar_b:>9.2f}")

    candidate = run_backtest(long_short_classes={"Equities"}, sector_of=sector_of)
    calmar_c = candidate["cagr_netto"] / abs(candidate["maxdd_netto"])
    print(f"{'Long/short su Equities (SH reale quando short)':<55}{candidate['cagr_netto']*100:>11.2f}%{candidate['sharpe_netto']:>14.2f}"
          f"{candidate['maxdd_netto']*100:>12.2f}%{calmar_c:>9.2f}")

    w = candidate["w_equity"]
    n_long = int((w > 1e-9).sum())
    n_short = int((w < -1e-9).sum())
    n_cash = int((w.abs() <= 1e-9).sum())
    side_flips = int((np.sign(w).diff().abs() > 1).sum())
    print(f"\nEquities: LONG {n_long}/{len(w)} settimane ({n_long/len(w)*100:.1f}%), "
          f"SHORT {n_short}/{len(w)} ({n_short/len(w)*100:.1f}%), CASH {n_cash}/{len(w)} ({n_cash/len(w)*100:.1f}%)")
    print(f"Cambi di lato diretti (LONG->SHORT o SHORT->LONG senza passare da CASH): {side_flips}")

    diff = (candidate["net"] - baseline["net"]).dropna()
    mean_diff = diff.mean() * PERIODS_PER_YEAR * 100
    lo, hi = block_bootstrap_ci(diff.values, lambda r: pd.Series(r).mean() * PERIODS_PER_YEAR * 100,
                                 block_size=12, ci=0.90, seed=42)
    n_better = int((diff > 0).sum())
    print(f"\nConfronto accoppiato diretto (long/short meno baseline long/flat):")
    print(f"  Overperformance media: {mean_diff:+.2f}pp/anno, CI 90% [{lo:+.2f}, {hi:+.2f}]pp/anno "
          f"({'ESCLUDE' if lo * hi > 0 else 'INCLUDE'} lo zero)")
    print(f"  Settimane in cui long/short ha fatto meglio: {n_better}/{len(diff)} ({n_better/len(diff)*100:.0f}%)")

    dsr = deflated_sharpe_ratio(candidate["sharpe_netto"], n_trials=2, n_obs=len(candidate["net"]))
    print(f"  DSR long/short (n_trials=2): {dsr:.4f}")


if __name__ == "__main__":
    main()
