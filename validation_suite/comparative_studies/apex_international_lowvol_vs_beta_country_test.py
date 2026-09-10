"""
apex_international_lowvol_vs_beta_country_test.py — Approfondimento
richiesto dall'utente dopo il risultato di
apex_international_bab_country_etf_test.py (BAB per BETA a livello di
paese si e' invertito: high-beta ha battuto low-beta in ogni sotto-
periodo 1996-2026).

Domanda dell'utente: la beta (misura di rischio SISTEMATICO, covarianza
col benchmark) e la volatilita' assoluta (rischio TOTALE, sistematico +
idiosincratico) sono misure diverse — a livello di singolo titolo USA la
beta ha battuto la volatilita' (Teoria #5, motivo per cui la produzione
seleziona oggi per beta e non piu' per vol), ma a livello di PAESE la
gerarchia potrebbe essere diversa: un paese ad alta beta puo' esserlo
perche' e' strutturalmente piu' legato al ciclo growth/tech globale (alta
beta, non necessariamente alta volatilita' assoluta), mentre un paese ad
alta volatilita' assoluta puo' esserlo per ragioni idiosincratiche (mono-
mercato, piccola capitalizzazione, instabilita' politica/valutaria) che
la beta da sola non cattura. Le due classifiche non sono garantite
coincidere.

Design: stesso universo, stessa finestra (26 settimane), stesso
ribilanciamento trimestrale, stesso benchmark equal-weight di
apex_international_bab_country_etf_test.py (riusa fetch/cache, nessun
nuovo download) — ma ora si confrontano ENTRAMBE le classifiche fianco a
fianco: low-beta, high-beta, low-vol (volatilita' realizzata assoluta,
non contro un benchmark), high-vol, equal-weight. Riporta anche la
sovrapposizione (quanti paesi in comune) tra il basket low-beta e il
basket low-vol in ciascun trimestre, per capire se le due classifiche
selezionano paesi diversi o gli stessi.
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

from metrics import cagr as _cagr, sharpe as _sharpe, max_drawdown as _max_drawdown
from statistical_validation import pbo_cscv, block_bootstrap_ci
from apex_stocks_vs_etf_backtest import PERIODS_PER_YEAR
from apex_international_bab_country_etf_test import (
    UNIVERSE, BETA_WINDOW, N_LOW, N_HIGH, MIN_HISTORY, load_weekly_returns, build_benchmark, trailing_beta,
)

VOL_WINDOW = BETA_WINDOW  # stessa finestra della beta, per confronto a parita' di condizioni


def trailing_vol(asset_ret: pd.Series, upto_idx: int, window: int) -> float | None:
    r = asset_ret.iloc[max(0, upto_idx - window):upto_idx]
    if len(r) < window:
        return None
    v = float(r.std() * np.sqrt(52))
    return v if v > 1e-9 else None


def run_backtest(rets: dict[str, pd.Series], bench: pd.Series, weeks: list) -> dict:
    n = len(weeks)
    baskets = {"low_beta": [], "high_beta": [], "low_vol": [], "high_vol": []}
    ret_hist = {k: [] for k in ("low_beta", "high_beta", "low_vol", "high_vol", "equal_weight")}
    overlap_hist = []

    for i, wk in enumerate(weeks):
        if i < MIN_HISTORY:
            for k in ret_hist:
                ret_hist[k].append(0.0)
            continue

        is_month_end = (i + 1 >= n) or (weeks[i + 1].month != wk.month)
        need_reform = (not baskets["low_beta"]) or (is_month_end and wk.month in (3, 6, 9, 12))
        if need_reform:
            betas = {t: trailing_beta(rets[t], bench, i, BETA_WINDOW) for t in UNIVERSE}
            betas = {t: v for t, v in betas.items() if v is not None}
            vols = {t: trailing_vol(rets[t], i, VOL_WINDOW) for t in UNIVERSE}
            vols = {t: v for t, v in vols.items() if v is not None}
            if len(betas) >= N_LOW + N_HIGH and len(vols) >= N_LOW + N_HIGH:
                ranked_beta = sorted(betas, key=betas.get)
                ranked_vol = sorted(vols, key=vols.get)
                baskets["low_beta"] = ranked_beta[:N_LOW]
                baskets["high_beta"] = ranked_beta[-N_HIGH:]
                baskets["low_vol"] = ranked_vol[:N_LOW]
                baskets["high_vol"] = ranked_vol[-N_HIGH:]
                overlap_hist.append(len(set(baskets["low_beta"]) & set(baskets["low_vol"])))

        for k in ("low_beta", "high_beta", "low_vol", "high_vol"):
            basket = baskets[k]
            ret_hist[k].append(float(np.mean([rets[t].iloc[i] for t in basket if i < len(rets[t])])) if basket else 0.0)
        ret_hist["equal_weight"].append(float(np.mean([rets[t].iloc[i] for t in UNIVERSE if i < len(rets[t])])))

    idx = pd.DatetimeIndex(weeks)
    result = {k: pd.Series(v, index=idx).iloc[MIN_HISTORY:] for k, v in ret_hist.items()}
    result["_overlap_hist"] = overlap_hist
    return result


def main():
    print(f"[*] Riuso cache locale prezzi per {len(UNIVERSE)} ETF Paese (nessun nuovo download)...")
    rets = load_weekly_returns()

    common_index = None
    for t, r in rets.items():
        common_index = r.index if common_index is None else common_index.intersection(r.index)
    weeks = list(common_index.sort_values())
    print(f"[*] Campione comune: {len(weeks)} settimane, {weeks[0].date()} -> {weeks[-1].date()}")

    rets = {t: r.reindex(weeks).fillna(0.0) for t, r in rets.items()}
    bench = build_benchmark(rets, pd.DatetimeIndex(weeks))

    print("[*] Backtest: low-beta / high-beta / low-vol / high-vol / equal-weight, ribilanciamento trimestrale...")
    result = main_result = run_backtest(rets, bench, weeks)
    overlap_hist = result.pop("_overlap_hist")

    print(f"\n{'Variante':<22}{'CAGR':>10}{'Sharpe':>10}{'MaxDD':>10}")
    labels = [("Low-beta (7/15)", "low_beta"), ("High-beta (7/15)", "high_beta"),
              ("Low-vol (7/15)", "low_vol"), ("High-vol (7/15)", "high_vol"),
              ("Equal-weight (15)", "equal_weight")]
    for label, key in labels:
        net = result[key]
        c, s, dd = _cagr(net, PERIODS_PER_YEAR), _sharpe(net, periods_per_year=PERIODS_PER_YEAR), _max_drawdown(net)
        print(f"{label:<22}{c*100:>9.2f}%{s:>10.2f}{dd*100:>9.2f}%")

    print(f"\nSovrapposizione media basket low-beta / low-vol: {np.mean(overlap_hist):.1f}/7 paesi in comune "
          f"({len(overlap_hist)} ribilanciamenti trimestrali)")

    for name_a, key_a, name_b, key_b in [
        ("low-vol", "low_vol", "equal-weight", "equal_weight"),
        ("low-vol", "low_vol", "high-vol", "high_vol"),
        ("low-vol", "low_vol", "low-beta", "low_beta"),
    ]:
        diff = (result[key_a] - result[key_b]).dropna()
        mean_diff = diff.mean() * PERIODS_PER_YEAR * 100
        lo, hi = block_bootstrap_ci(diff.values, lambda r: pd.Series(r).mean() * PERIODS_PER_YEAR * 100, block_size=26, ci=0.90, seed=42)
        n_better = int((diff > 0).sum())
        print(f"\nConfronto accoppiato ({name_a} meno {name_b}):")
        print(f"  Overperformance media: {mean_diff:+.2f}pp/anno, CI 90% [{lo:+.2f}, {hi:+.2f}]pp/anno "
              f"({'ESCLUDE' if lo * hi > 0 else 'include'} lo zero)")
        print(f"  Settimane in cui {name_a} ha fatto meglio: {n_better}/{len(diff)} ({n_better/len(diff)*100:.0f}%)")

    perf_matrix = np.column_stack([result[k].values for _, k in labels])
    n_splits = 8
    usable_len = (len(perf_matrix) // n_splits) * n_splits
    pbo = pbo_cscv(perf_matrix[-usable_len:], n_splits=n_splits)
    print(f"\nPBO-CSCV su 5 varianti (low/high-beta, low/high-vol, equal-weight): {pbo*100:.1f}%")

    print("\n--- Robustezza per sotto-periodo ---")
    n_sub = 4
    idx_all = result["low_beta"].index
    sub_len = len(idx_all) // n_sub
    for i in range(n_sub):
        sub_idx = idx_all[i * sub_len: (i + 1) * sub_len] if i < n_sub - 1 else idx_all[i * sub_len:]
        if len(sub_idx) < 20:
            continue
        row = "  " + f"{sub_idx.min().date()} -> {sub_idx.max().date()} ({len(sub_idx)} sett.): "
        for label, key in labels:
            s = _sharpe(result[key].reindex(sub_idx), periods_per_year=PERIODS_PER_YEAR)
            row += f"{label.split(' ')[0]} {s:5.2f}  "
        print(row)


if __name__ == "__main__":
    main()
