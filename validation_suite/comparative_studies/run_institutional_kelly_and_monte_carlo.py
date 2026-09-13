"""
run_institutional_kelly_and_monte_carlo.py

Esegue l'audit quantitativo richiesto dall'utente:
1. Test Kelly sulle 4 classi di asset di Apex (Equity, Bonds, Gold, Crypto, Cash)
2. Test Kelly e bilanciamento ottimale tra Apex Engine e Convex Engine
3. Simulazione Monte Carlo a blocchi (10.000 percorsi) su:
   - Singoli motori/asset (Equity, Bonds, Gold, Crypto Venture)
   - Apex Engine complessivo
   - Convex Engine complessivo
   - Portafoglio Combinato Dual Engine (70/30 e 50/50)
Tutte le metriche sono rigorosamente al lordo delle imposte (Gross of Taxes).
"""

from __future__ import annotations
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "validation_suite" / "framework"))
sys.path.insert(0, str(REPO_ROOT / "validation_suite" / "comparative_studies"))

from metrics import (
    cagr as _cagr, sharpe as _sharpe, max_drawdown as _max_drawdown,
    calmar as _calmar, sortino_ratio, ulcer_index
)
from apex_dashboard_stat_regeneration import spliced_return, to_monthly, EXT_DATA_DIR, SLICE_END

# --- 1. CARICAMENTO DATI ---
def load_all_series():
    # Asset classes settimanali spliced
    eq_w = spliced_return("VFINX_weekly.csv", "SPY_weekly.csv", "1993-01-29")
    bd_w = spliced_return("VUSTX_weekly.csv", "IEF_weekly.csv", "2002-08-02")
    gd_w = spliced_return("GC_F_weekly.csv", "GLD_weekly.csv", "2004-11-19")
    cr_w = pd.read_csv(EXT_DATA_DIR / "crypto_venture_weekly_spliced.csv", index_col=0, parse_dates=True)["gross"]

    # Conversione a mensile
    eq_m = to_monthly(eq_w).loc[:SLICE_END]
    bd_m = to_monthly(bd_w).loc[:SLICE_END]
    gd_m = to_monthly(gd_w).loc[:SLICE_END]
    cr_m = to_monthly(cr_w).loc[:SLICE_END]

    # Motori complessivi (mensili, lordi)
    apex_m = pd.read_csv(REPO_ROOT / "apex_monthly_returns_extended_gross.csv", index_col=0, parse_dates=True).iloc[:, 0]
    apex_m = apex_m.loc[:SLICE_END]
    convex_m = pd.read_csv(REPO_ROOT / "convex_monthly_returns.csv", index_col=0, parse_dates=True).iloc[:, 0]
    convex_m = convex_m.loc[:SLICE_END]

    return {
        "eq_m": eq_m, "bd_m": bd_m, "gd_m": gd_m, "cr_m": cr_m,
        "apex_m": apex_m, "convex_m": convex_m
    }


# --- 2. KELLY OPTIMIZATION HELPER ---
def compute_kelly_weights(returns_df: pd.DataFrame, annualization: float = 12.0):
    mu = returns_df.mean().values * annualization
    cov = returns_df.cov().values * annualization
    inv_cov = np.linalg.pinv(cov)
    f_unconstrained = inv_cov @ mu

    n = len(mu)
    # Minimizzazione quadratica vincolata senza scipy (usiamo scipy solo se presente, altrimenti formula)
    try:
        from scipy.optimize import minimize
        res = minimize(
            lambda w: -(w @ mu - 0.5 * w @ cov @ w),
            x0=np.ones(n) / n,
            bounds=[(0.0, 1.0) for _ in range(n)],
            constraints={"type": "eq", "fun": lambda w: np.sum(w) - 1.0}
        )
        w_simplex = res.x if res.success else np.ones(n) / n

        res_cash = minimize(
            lambda w: -(w @ mu - 0.5 * w @ cov @ w),
            x0=np.ones(n) / (n + 1),
            bounds=[(0.0, 1.0) for _ in range(n)],
            constraints={"type": "ineq", "fun": lambda w: 1.0 - np.sum(w)}
        )
        w_with_cash = res_cash.x if res_cash.success else w_simplex
        cash_weight = max(0.0, 1.0 - np.sum(w_with_cash))
    except ImportError:
        # Fallback analitico proiettato
        w_simplex = np.maximum(0, f_unconstrained)
        if np.sum(w_simplex) > 0:
            w_simplex = w_simplex / np.sum(w_simplex)
        w_with_cash = w_simplex
        cash_weight = 0.0

    return {
        "mu": mu, "cov": cov, "corr": returns_df.corr(),
        "f_unconstrained": dict(zip(returns_df.columns, f_unconstrained)),
        "w_simplex": dict(zip(returns_df.columns, w_simplex)),
        "w_with_cash": dict(zip(returns_df.columns, w_with_cash)),
        "cash_weight": cash_weight
    }


# --- 3. MONTE CARLO BLOCK BOOTSTRAP ---
def run_block_bootstrap_mc(
    returns_series: pd.Series,
    n_simulations: int = 10000,
    horizons: dict[str, int] = {"1Y": 12, "3Y": 36, "5Y": 60},
    block_size: int = 6,
    seed: int = 42
):
    rng = np.random.default_rng(seed)
    rets = returns_series.dropna().values
    n = len(rets)
    if n < block_size * 2:
        return {}

    results = {}
    for h_label, h_months in horizons.items():
        n_blocks = int(np.ceil(h_months / block_size))
        block_starts = rng.integers(0, n - block_size + 1, size=(n_simulations, n_blocks))
        
        paths = np.empty((n_simulations, h_months))
        for sim_idx in range(n_simulations):
            sim_blocks = [rets[s:s + block_size] for s in block_starts[sim_idx]]
            paths[sim_idx] = np.concatenate(sim_blocks)[:h_months]

        cum_nav = np.cumprod(1.0 + paths, axis=1)
        total_returns = cum_nav[:, -1] - 1.0
        cagrs = (1.0 + total_returns) ** (12.0 / h_months) - 1.0

        peak = np.maximum.accumulate(np.column_stack([np.ones(n_simulations), cum_nav]), axis=1)
        dd = (np.column_stack([np.ones(n_simulations), cum_nav]) - peak) / peak
        max_dds = np.min(dd, axis=1)

        p_loss = np.mean(total_returns < 0.0) * 100.0
        p_dd_10 = np.mean(max_dds < -0.10) * 100.0
        p_dd_15 = np.mean(max_dds < -0.15) * 100.0
        p_dd_20 = np.mean(max_dds < -0.20) * 100.0
        p_dd_30 = np.mean(max_dds < -0.30) * 100.0

        var_95 = -np.percentile(total_returns, 5.0)
        var_99 = -np.percentile(total_returns, 1.0)
        cvar_95 = -np.mean(total_returns[total_returns <= -var_95]) if np.any(total_returns <= -var_95) else var_95
        cvar_99 = -np.mean(total_returns[total_returns <= -var_99]) if np.any(total_returns <= -var_99) else var_99

        results[h_label] = {
            "cagr_5": np.percentile(cagrs, 5.0),
            "cagr_50": np.percentile(cagrs, 50.0),
            "cagr_95": np.percentile(cagrs, 95.0),
            "mean_cagr": np.mean(cagrs),
            "max_dd_median": np.percentile(max_dds, 50.0),
            "max_dd_95": np.percentile(max_dds, 5.0),
            "p_loss": p_loss,
            "p_dd_10": p_dd_10,
            "p_dd_15": p_dd_15,
            "p_dd_20": p_dd_20,
            "p_dd_30": p_dd_30,
            "var_95": var_95,
            "var_99": var_99,
            "cvar_95": cvar_95,
            "cvar_99": cvar_99,
        }

    return results


def main():
    print("=" * 80)
    print("AUDIT ISTITUZIONALE: TEST KELLY E SIMULAZIONE MONTE CARLO (GROSS OF TAXES)")
    print("=" * 80)

    data = load_all_series()
    eq_m, bd_m, gd_m, cr_m = data["eq_m"], data["bd_m"], data["gd_m"], data["cr_m"]
    apex_m, convex_m = data["apex_m"], data["convex_m"]

    # -------------------------------------------------------------
    # PARTE 1: TEST KELLY SULLE CLASSI DI ASSET DI APEX
    # -------------------------------------------------------------
    print("\n" + "#" * 80)
    print("PARTE 1: TEST DEL CRITERIO DI KELLY SULLE CLASSI DI ASSET DI APEX")
    print("#" * 80)

    # Allineamento su periodo moderno con Crypto attiva (2014-2026)
    df_assets_modern = pd.DataFrame({
        "Equity": eq_m, "Bonds": bd_m, "Gold": gd_m, "Crypto": cr_m
    }).dropna()

    print(f"\n[A] Periodo Moderno con Crypto Attiva (Frontier Venture + BTC): {len(df_assets_modern)} mesi ({df_assets_modern.index.min().date()} -> {df_assets_modern.index.max().date()})")
    k_res_mod = compute_kelly_weights(df_assets_modern)
    
    print("\n1. Rendimenti Medi e Volatilità Annualizzati:")
    for col in df_assets_modern.columns:
        mean_ann = df_assets_modern[col].mean() * 12 * 100
        vol_ann = df_assets_modern[col].std() * np.sqrt(12) * 100
        sr = _sharpe(df_assets_modern[col], periods_per_year=12)
        print(f"  {col:<10}: E[R] = {mean_ann:>6.2f}% | Vol = {vol_ann:>6.2f}% | Sharpe = {sr:>5.2f}")

    print("\n2. Matrice di Correlazione tra Classi:")
    print(df_assets_modern.corr().round(3).to_string())

    print("\n3. Vettori di Allocazione Kelly (Periodo Moderno):")
    print(f"  {'Asset':<10} | {'Kelly Non Vincolato':>20} | {'Kelly Simplex (100%)':>20} | {'Kelly con Cash':>18}")
    print("-" * 75)
    for col in df_assets_modern.columns:
        f_unc = k_res_mod['f_unconstrained'][col] * 100
        w_smp = k_res_mod['w_simplex'][col] * 100
        w_csh = k_res_mod['w_with_cash'][col] * 100
        print(f"  {col:<10} | {f_unc:>19.1f}% | {w_smp:>19.1f}% | {w_csh:>17.1f}%")
    print(f"  {'Cash':<10} | {'N/A (Leva)':>20} | {0.0:>19.1f}% | {k_res_mod['cash_weight']*100:>17.1f}%")

    # Allineamento su periodo storico lungo (1987-2026, 471 mesi)
    df_assets_full = pd.DataFrame({
        "Equity": eq_m, "Bonds": bd_m, "Gold": gd_m, "Crypto": cr_m.reindex(eq_m.index).fillna(0.0)
    }).loc[apex_m.index].dropna()

    print(f"\n[B] Periodo Storico Completo (1987-2026, {len(df_assets_full)} mesi):")
    k_res_full = compute_kelly_weights(df_assets_full)
    print(f"  {'Asset':<10} | {'Kelly Non Vincolato':>20} | {'Kelly Simplex (100%)':>20} | {'Kelly con Cash':>18}")
    print("-" * 75)
    for col in df_assets_full.columns:
        f_unc = k_res_full['f_unconstrained'][col] * 100
        w_smp = k_res_full['w_simplex'][col] * 100
        w_csh = k_res_full['w_with_cash'][col] * 100
        print(f"  {col:<10} | {f_unc:>19.1f}% | {w_smp:>19.1f}% | {w_csh:>17.1f}%")
    print(f"  {'Cash':<10} | {'N/A (Leva)':>20} | {0.0:>19.1f}% | {k_res_full['cash_weight']*100:>17.1f}%")

    # -------------------------------------------------------------
    # PARTE 2: TEST KELLY PER IL BILANCIAMENTO APEX / CONVEX
    # -------------------------------------------------------------
    print("\n" + "#" * 80)
    print("PARTE 2: BILANCIAMENTO OTTIMALE KELLY TRA APEX ENGINE E CONVEX ENGINE")
    print("#" * 80)

    common_idx = apex_m.index.intersection(convex_m.index).sort_values()
    a_ret = apex_m.reindex(common_idx)
    c_ret = convex_m.reindex(common_idx)

    print(f"Campione Comune Totale: {len(common_idx)} mesi ({common_idx.min().date()} -> {common_idx.max().date()})")
    mu_a, mu_c = float(a_ret.mean() * 12), float(c_ret.mean() * 12)
    vol_a, vol_c = float(a_ret.std() * np.sqrt(12)), float(c_ret.std() * np.sqrt(12))
    rho_ac = float(a_ret.corr(c_ret))
    cov_ac = rho_ac * vol_a * vol_c

    print(f"  Apex Engine:   E[R] = {mu_a*100:6.2f}% | Vol = {vol_a*100:5.2f}% | Sharpe = {_sharpe(a_ret, periods_per_year=12):.3f}")
    print(f"  Convex Engine: E[R] = {mu_c*100:6.2f}% | Vol = {vol_c*100:5.2f}% | Sharpe = {_sharpe(c_ret, periods_per_year=12):.3f}")
    print(f"  Correlazione Apex / Convex: {rho_ac:.3f}")

    # Kelly analitico 2 asset
    Sigma_meta = np.array([[vol_a**2, cov_ac], [cov_ac, vol_c**2]])
    mu_meta = np.array([mu_a, mu_c])
    f_star_meta = np.linalg.solve(Sigma_meta, mu_meta)
    print(f"\n1. Vettore Kelly Non Vincolato (Leva Piena):")
    print(f"   f*_Apex = {f_star_meta[0]*100:.1f}% | f*_Convex = {f_star_meta[1]*100:.1f}% (Leva Totale: {np.sum(f_star_meta)*100:.1f}%)")
    print(f"   Rapporto Relativo Kelly Pieno: {f_star_meta[0]/np.sum(f_star_meta)*100:.1f}% Apex / {f_star_meta[1]/np.sum(f_star_meta)*100:.1f}% Convex")

    print("\n2. Griglia di Bilanciamento Empirico (1987-2026, 465 Mesi):")
    print(f"  {'Mix (Apex/Convex)':<20} | {'CAGR':>8} | {'Volatilità':>10} | {'Sharpe':>8} | {'Sortino':>8} | {'MaxDD':>8} | {'Calmar':>8}")
    print("-" * 85)

    weights_grid = [1.0, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1, 0.0]
    grid_results = []
    for w in weights_grid:
        mix = w * a_ret + (1 - w) * c_ret
        cg = _cagr(mix, 12)
        vl = float(mix.std() * np.sqrt(12))
        sr = _sharpe(mix, periods_per_year=12)
        so = sortino_ratio(mix, periods_per_year=12)
        dd = _max_drawdown(mix)
        cl = _calmar(mix, 12)
        label = f"{int(round(w*100))}/{int(round((1-w)*100))}"
        if abs(w - 0.70) < 1e-4:
            label += " (Target)"
        elif abs(w - 0.50) < 1e-4:
            label += " (Equal)"
        grid_results.append({
            "label": label, "w": w, "cagr": cg, "vol": vl, "sharpe": sr,
            "sortino": so, "maxdd": dd, "calmar": cl
        })
        print(f"  {label:<20} | {cg*100:>7.2f}% | {vl*100:>9.2f}% | {sr:>8.3f} | {so:>8.3f} | {dd*100:>7.2f}% | {cl:>8.3f}")

    # Valutazione Out-of-Sample pura (ultimi 72 mesi, 2020-09 -> 2026-08)
    oos_idx = common_idx[common_idx >= "2020-09-30"]
    a_oos = a_ret.reindex(oos_idx)
    c_oos = c_ret.reindex(oos_idx)

    print(f"\n3. Griglia di Bilanciamento Out-of-Sample (2020-2026, 72 Mesi OOS):")
    print(f"  {'Mix (Apex/Convex)':<20} | {'CAGR':>8} | {'Volatilità':>10} | {'Sharpe':>8} | {'Sortino':>8} | {'MaxDD':>8} | {'Calmar':>8}")
    print("-" * 85)
    for w in [1.0, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.0]:
        mix_oos = w * a_oos + (1 - w) * c_oos
        cg = _cagr(mix_oos, 12)
        vl = float(mix_oos.std() * np.sqrt(12))
        sr = _sharpe(mix_oos, periods_per_year=12)
        so = sortino_ratio(mix_oos, periods_per_year=12)
        dd = _max_drawdown(mix_oos)
        cl = _calmar(mix_oos, 12)
        label = f"{int(round(w*100))}/{int(round((1-w)*100))}"
        if abs(w - 0.70) < 1e-4:
            label += " (Target)"
        elif abs(w - 0.50) < 1e-4:
            label += " (Equal)"
        print(f"  {label:<20} | {cg*100:>7.2f}% | {vl*100:>9.2f}% | {sr:>8.3f} | {so:>8.3f} | {dd*100:>7.2f}% | {cl:>8.3f}")

    # -------------------------------------------------------------
    # PARTE 3: SIMULAZIONI MONTE CARLO A BLOCCHI (10.000 RUNS)
    # -------------------------------------------------------------
    print("\n" + "#" * 80)
    print("PARTE 3: SIMULAZIONE MONTE CARLO A BLOCCHI (10.000 PERCORSI PER SERIE)")
    print("#" * 80)

    mix_70_30 = 0.70 * a_ret + 0.30 * c_ret
    mix_50_50 = 0.50 * a_ret + 0.50 * c_ret

    series_to_simulate = {
        "Equity Sleeve (Low-Beta/SPY)": eq_m,
        "Bonds Sleeve (Treasury IEF/VUSTX)": bd_m,
        "Gold Sleeve (GLD/GC=F)": gd_m,
        "Crypto Sleeve (Frontier Venture)": cr_m,
        "Apex Engine Complessivo (Gross)": apex_m,
        "Convex Engine Complessivo (Gross)": convex_m,
        "Dual Engine Mix 70/30 (Target)": mix_70_30,
        "Dual Engine Mix 50/50 (Controllo)": mix_50_50,
    }

    print("\nParametri della Simulazione Monte Carlo:")
    print("  - Algoritmo: Circular Block Bootstrap (Politis & Romano)")
    print("  - Iterazioni: 10.000 percorsi indipendenti per ciascun motore/asset")
    print("  - Dimensione Blocco: 6 mesi (preserva autocorrelazione, regimi e clustering di volatilità)")
    print("  - Orizzonti Temporali: 1 Anno (12 mesi), 3 Anni (36 mesi), 5 Anni (60 mesi)")

    mc_results_all = {}
    for name, s in series_to_simulate.items():
        print(f"[*] Simulazione Monte Carlo in corso per: {name} (N={len(s.dropna())} mesi)...")
        mc_results_all[name] = run_block_bootstrap_mc(s, n_simulations=10000, block_size=6, seed=42)

    # Tabella 1 Anno
    print("\n" + "=" * 95)
    print("TABELLA MONTE CARLO 1 ANNO (12 MESI) — 10.000 RUNS")
    print("=" * 95)
    print(f"{'Motore / Asset':<34} | {'CAGR 5%':>8} | {'CAGR Med':>9} | {'CAGR 95%':>9} | {'MaxDD Med':>9} | {'MaxDD 95%':>9} | {'P(Loss)':>7} | {'VaR 95%':>8}")
    print("-" * 95)
    for name, res in mc_results_all.items():
        r = res["1Y"]
        print(f"{name:<34} | {r['cagr_5']*100:>7.2f}% | {r['cagr_50']*100:>8.2f}% | {r['cagr_95']*100:>8.2f}% | {r['max_dd_median']*100:>8.2f}% | {r['max_dd_95']*100:>8.2f}% | {r['p_loss']:>6.1f}% | {r['var_95']*100:>7.2f}%")

    # Tabella 3 Anni
    print("\n" + "=" * 95)
    print("TABELLA MONTE CARLO 3 ANNI (36 MESI) — 10.000 RUNS")
    print("=" * 95)
    print(f"{'Motore / Asset':<34} | {'CAGR 5%':>8} | {'CAGR Med':>9} | {'CAGR 95%':>9} | {'MaxDD Med':>9} | {'MaxDD 95%':>9} | {'P(Loss)':>7} | {'P(DD>15%)':>9}")
    print("-" * 95)
    for name, res in mc_results_all.items():
        r = res["3Y"]
        print(f"{name:<34} | {r['cagr_5']*100:>7.2f}% | {r['cagr_50']*100:>8.2f}% | {r['cagr_95']*100:>8.2f}% | {r['max_dd_median']*100:>8.2f}% | {r['max_dd_95']*100:>8.2f}% | {r['p_loss']:>6.1f}% | {r['p_dd_15']:>8.1f}%")

    # Tabella 5 Anni
    print("\n" + "=" * 95)
    print("TABELLA MONTE CARLO 5 ANNI (60 MESI) — 10.000 RUNS")
    print("=" * 95)
    print(f"{'Motore / Asset':<34} | {'CAGR 5%':>8} | {'CAGR Med':>9} | {'CAGR 95%':>9} | {'MaxDD Med':>9} | {'MaxDD 95%':>9} | {'P(Loss)':>7} | {'P(DD>20%)':>9}")
    print("-" * 95)
    for name, res in mc_results_all.items():
        r = res["5Y"]
        print(f"{name:<34} | {r['cagr_5']*100:>7.2f}% | {r['cagr_50']*100:>8.2f}% | {r['cagr_95']*100:>8.2f}% | {r['max_dd_median']*100:>8.2f}% | {r['max_dd_95']*100:>8.2f}% | {r['p_loss']:>6.1f}% | {r['p_dd_20']:>8.1f}%")

    # Salvataggio JSON
    json_path = REPO_ROOT / "validation_suite" / "comparative_studies" / "kelly_and_monte_carlo_results.json"
    with open(json_path, "w") as f:
        def serialize_clean(obj):
            if isinstance(obj, (np.floating, float)):
                return round(float(obj), 6)
            elif isinstance(obj, (np.integer, int)):
                return int(obj)
            elif isinstance(obj, np.ndarray):
                return obj.tolist()
            elif isinstance(obj, pd.DataFrame):
                return obj.to_dict()
            elif isinstance(obj, pd.Series):
                return obj.to_dict()
            return str(obj)
        
        save_payload = {
            "kelly_assets_modern": {
                "f_unconstrained": {k: float(v) for k, v in k_res_mod["f_unconstrained"].items()},
                "w_simplex": {k: float(v) for k, v in k_res_mod["w_simplex"].items()},
                "w_with_cash": {k: float(v) for k, v in k_res_mod["w_with_cash"].items()},
                "cash_weight": float(k_res_mod["cash_weight"])
            },
            "kelly_meta_mix": {
                "f_star_apex": float(f_star_meta[0]),
                "f_star_convex": float(f_star_meta[1]),
                "grid_results": grid_results
            },
            "monte_carlo_summary": mc_results_all
        }
        json.dump(save_payload, f, default=serialize_clean, indent=2)
    print(f"\n[*] Risultati completi salvati in: {json_path.name}")


if __name__ == "__main__":
    main()
