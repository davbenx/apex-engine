"""
apex_convex_regime_and_correlation_stress.py — Due test del protocollo di
robustezza/invalidazione istituzionale richiesto sull'intero sistema
Apex+Convex:

1. PERFORMANCE PER REGIME STORICO NOMINATO: l'edge aggregato (CAGR/Sharpe/
   MaxDD sull'intero storico) puo' nascondere un edge concentrato in un
   solo regime fortunato. Si spezza la serie in finestre di crisi/bull
   market standard e si guarda ciascuna singolarmente, per Apex, Convex e
   Combinato 70/30.

2. CORRELAZIONE CONDIZIONATA ALLO STRESS: la diversificazione dichiarata
   (correlazione ~0.3 sull'intero storico) e' il numero giusto da guardare
   solo se resta stabile anche nei momenti in cui serve davvero — molti
   "diversificatori" hanno una correlazione bassa in media ma che sale
   verso 1 esattamente nei mesi peggiori (il caso in cui servirebbe di
   piu'). Si calcola quindi la correlazione condizionata ai mesi peggiori
   di ciascuna gamba, non solo quella incondizionata.

Riusa le serie mensili gia' costruite in questa sessione — nessun nuovo
fetch di dati o backtest, solo analisi.
"""
from __future__ import annotations
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "validation_suite" / "framework"))

import portfolio_manager
from metrics import cagr as _cagr, sharpe as _sharpe, max_drawdown as _max_drawdown, calmar as _calmar

APEX_FILE = REPO_ROOT / "apex_monthly_returns_extended_gross.csv"
CONVEX_FILE = REPO_ROOT / "convex_monthly_returns.csv"

# (label, start, end) — finestre di crisi/regime standard, adattate alla
# storia effettivamente disponibile (Apex 1987-06+, Convex 1987-12+)
REGIMES = [
    ("Crollo 1987 (post Black Monday)", "1987-10-01", "1987-12-31"),
    ("Recessione 1990-91", "1990-07-01", "1991-03-31"),
    ("Crisi obbligazionaria 1994", "1994-01-01", "1994-12-31"),
    ("Crisi asiatica 1997-98", "1997-07-01", "1998-01-31"),
    ("LTCM/Russia 1998", "1998-07-01", "1998-10-31"),
    ("Bust dot-com 2000-2002", "2000-03-01", "2002-10-31"),
    ("Bull 2003-2007 (pre-GFC)", "2003-01-01", "2007-09-30"),
    ("Crisi finanziaria globale 2007-2009", "2007-10-01", "2009-03-31"),
    ("Ripresa 2009-2013", "2009-04-01", "2013-04-30"),
    ("Taper tantrum 2013", "2013-05-01", "2013-09-30"),
    ("Selloff Cina/petrolio 2015-16", "2015-08-01", "2016-02-29"),
    ("Selloff Q4 2018", "2018-10-01", "2018-12-31"),
    ("Crollo COVID 2020", "2020-02-01", "2020-03-31"),
    ("Ripresa/bull 2020-2021", "2020-04-01", "2021-12-31"),
    ("Shock tassi 2022", "2022-01-01", "2022-10-31"),
    ("Bull AI 2023-2026", "2023-01-01", "2026-08-31"),
]


def regime_stats(ret: pd.Series, label: str, start: str, end: str) -> dict | None:
    sub = ret.loc[start:end]
    if len(sub) < 2:
        return None
    return {
        "label": label, "n": len(sub),
        "cum_return": float((1 + sub).prod() - 1.0),
        "cagr_ann": _cagr(sub, 12) if len(sub) >= 6 else None,
        "sharpe": _sharpe(sub, periods_per_year=12) if len(sub) >= 6 else None,
        "max_drawdown": _max_drawdown(sub),
        "worst_month": float(sub.min()),
    }


def print_regime_table(name: str, ret: pd.Series):
    print(f"\n{'='*90}\n{name} — performance per regime storico\n{'='*90}")
    print(f"{'Regime':<38}{'Mesi':>5}{'Rend.Cum':>11}{'CAGR':>9}{'Sharpe':>8}{'MaxDD':>9}{'PeggiorMese':>12}")
    for label, start, end in REGIMES:
        s = regime_stats(ret, label, start, end)
        if s is None:
            print(f"{label:<38}{'—':>5}  (dati insufficienti)")
            continue
        cagr_str = f"{s['cagr_ann']*100:+.2f}%" if s['cagr_ann'] is not None else "n/a"
        sharpe_str = f"{s['sharpe']:.2f}" if s['sharpe'] is not None else "n/a"
        print(f"{label:<38}{s['n']:>5}{s['cum_return']*100:>+10.2f}%{cagr_str:>9}{sharpe_str:>8}"
              f"{s['max_drawdown']*100:>8.2f}%{s['worst_month']*100:>+11.2f}%")


def conditional_correlation(a: pd.Series, b: pd.Series, label_a: str, label_b: str):
    common = a.index.intersection(b.index)
    a_c, b_c = a.loc[common], b.loc[common]
    print(f"\n{'-'*90}\nCorrelazione {label_a} vs {label_b} — incondizionata vs condizionata allo stress ({len(common)} mesi comuni)\n{'-'*90}")
    print(f"  Incondizionata (intero storico comune):                    {a_c.corr(b_c):+.3f}")

    for pct in (0.10, 0.20):
        n = max(3, int(len(a_c) * pct))
        worst_a_idx = a_c.sort_values().index[:n]
        corr_when_a_bad = a_c.loc[worst_a_idx].corr(b_c.loc[worst_a_idx])
        print(f"  Condizionata al {int(pct*100)}% peggiore di {label_a} ({n} mesi):          {corr_when_a_bad:+.3f}"
              f"   [{label_b} media in quei mesi: {b_c.loc[worst_a_idx].mean()*100:+.2f}%]")

        worst_b_idx = b_c.sort_values().index[:n]
        corr_when_b_bad = a_c.loc[worst_b_idx].corr(b_c.loc[worst_b_idx])
        print(f"  Condizionata al {int(pct*100)}% peggiore di {label_b} ({n} mesi):          {corr_when_b_bad:+.3f}"
              f"   [{label_a} media in quei mesi: {a_c.loc[worst_b_idx].mean()*100:+.2f}%]")

    both_neg = a_c[(a_c < 0) & (b_c < 0)]
    both_neg_pct = len(both_neg) / len(a_c) * 100
    a_neg_pct = (a_c < 0).mean() * 100
    b_neg_pct = (b_c < 0).mean() * 100
    indep_expected_pct = (a_neg_pct / 100) * (b_neg_pct / 100) * 100
    verdict = "PIU' frequente del caso" if both_neg_pct > indep_expected_pct * 1.15 else "coerente con indipendenza/diversificazione reale"
    print(f"\n  Mesi con ENTRAMBI negativi: {len(both_neg)}/{len(a_c)} ({both_neg_pct:.1f}%) — "
          f"atteso sotto indipendenza: {indep_expected_pct:.1f}% ({verdict})")


def main():
    apex = pd.read_csv(APEX_FILE, index_col=0, parse_dates=True).iloc[:, 0]
    convex = pd.read_csv(CONVEX_FILE, index_col=0, parse_dates=True).iloc[:, 0]
    df_comb = portfolio_manager.load_combined_monthly_history(0.70, 0.30)
    combined = df_comb["return"]

    print_regime_table("APEX ENGINE (gross)", apex)
    print_regime_table("CONVEX STACK (gross)", convex)
    print_regime_table("COMBINATO 70/30", combined)

    conditional_correlation(apex, convex, "Apex", "Convex")


if __name__ == "__main__":
    main()
