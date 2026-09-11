"""
apex_momentum_crash_stress_test.py — Teoria accademica #6 da sondare/stress
test: "Momentum Crashes" (Daniel & Moskowitz 2016) — i trend-follower
soffrono tipicamente di forti perdite quando un mercato in caduta inverte
a V, perche' il segnale continua a dire "fuori" (o "corto") proprio mentre
il rimbalzo comincia. Apex e' long-only (mai short in produzione — l'idea
long/short e' stata gia' testata e falsificata, vedi
apex_equity_long_short_overlay_test.py), quindi il meccanismo esatto del
paper (corto sui perdenti che rimbalzano) non si applica identico — ma
l'analogo diretto esiste: USCIRE (andare a Cash) subito prima di un forte
rally perde quel rally per intero, un costo reale di whipsaw.

Questo NON e' un confronto baseline-vs-candidato come gli altri test — e'
un DIAGNOSTICO sul segnale di produzione INVARIATO: per ciascuna classe
macro, si isolano tutte le transizioni ATTIVO->CASH (uscite) nello storico
walk-forward reale di Apex, e si misura il rendimento dell'asset sottostante
nelle K settimane SUCCESSIVE a ciascuna uscita (il "costo di opportunita'"
di essere fuori) — confrontato con il rendimento K-settimane medio
INCONDIZIONATO dello stesso asset sull'intero campione. Se il rendimento
post-uscita e' sistematicamente PIU' ALTO della media incondizionata,
l'isteresi attuale e' vulnerabile al pattern "momentum crash" (esce
proprio prima dei rimbalzi forti). Se non lo e', il rischio non e'
confermato su questo campione.

Nessuna riga di apex_v2_engine.py modificata — usa compute_v2_macro_signal
di produzione COSI' COM'E', nessuna variante testata.
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
from apex_v2_engine import compute_v2_macro_signal, V2_CLASS_TICKER
from apex_stocks_vs_etf_backtest import load_weekly_macro, build_ohlc_like

FORWARD_WINDOWS = [4, 8, 12]  # settimane dopo l'uscita su cui misurare il rendimento perso


def main():
    macro_prices = {V2_CLASS_TICKER[c]: load_weekly_macro(V2_CLASS_TICKER[c]) for c in V2_CLASS_TICKER}
    common_index = macro_prices["SPY"].index
    for s in macro_prices.values():
        common_index = common_index.intersection(s.index)
    weeks = list(common_index)
    n = len(weeks)

    hysteresis_state = None
    active_history = {c: [] for c in V2_CLASS_TICKER}

    MIN_HISTORY = 40
    for i, wk in enumerate(weeks):
        if i < MIN_HISTORY:
            for c in V2_CLASS_TICKER:
                active_history[c].append(None)
            continue
        b_data = {V2_CLASS_TICKER[c]: build_ohlc_like(macro_prices[V2_CLASS_TICKER[c]].loc[:wk]) for c in V2_CLASS_TICKER}
        _alloc, hysteresis_state, debug = compute_v2_macro_signal(b_data, prev_hysteresis_state=hysteresis_state)
        for c in V2_CLASS_TICKER:
            active_history[c].append(bool(debug.get(c, {}).get("attivo", False)))

    print(f"Campione: {n} settimane, {weeks[MIN_HISTORY].date()} -> {weeks[-1].date()}\n")
    print(f"{'Classe':<10}{'Uscite':>8}{'Rendim. K-sett. incond. (media)':>36}{'Rendim. K-sett. post-uscita (media)':>38}{'Differenza':>13}")

    for c in V2_CLASS_TICKER:
        ticker = V2_CLASS_TICKER[c]
        price = macro_prices[ticker].reindex(weeks)
        active = pd.Series(active_history[c], index=weeks)

        exit_weeks = []
        for i in range(MIN_HISTORY + 1, n):
            if active.iloc[i - 1] is True and active.iloc[i] is False:
                exit_weeks.append(i)

        for K in FORWARD_WINDOWS:
            unconditional_fwd = []
            for i in range(MIN_HISTORY, n - K):
                unconditional_fwd.append(price.iloc[i + K] / price.iloc[i] - 1.0)
            unconditional_mean = float(np.mean(unconditional_fwd)) if unconditional_fwd else float("nan")

            post_exit_fwd = []
            for i in exit_weeks:
                if i + K < n:
                    post_exit_fwd.append(price.iloc[i + K] / price.iloc[i] - 1.0)
            post_exit_mean = float(np.mean(post_exit_fwd)) if post_exit_fwd else float("nan")

            diff = post_exit_mean - unconditional_mean if post_exit_fwd else float("nan")
            label = f"{c} (K={K}sett.)"
            print(f"{label:<10}{len(exit_weeks):>8}{unconditional_mean*100:>35.2f}%{post_exit_mean*100:>37.2f}%{diff*100:>12.2f}pp")
        print()

    print("Interpretazione: differenza POSITIVA e ampia = l'uscita e' sistematicamente seguita da un\n"
          "rendimento sopra la media (rimbalzo perso, vulnerabilita' al pattern 'momentum crash').\n"
          "Differenza vicina a zero o negativa = l'uscita non e' seguita da rimbalzi anomali su questo\n"
          "campione, il rischio non e' confermato.")


if __name__ == "__main__":
    main()
