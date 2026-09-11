"""
altcoin_carry_market_neutral_test.py — Vero carry MARKET-NEUTRAL (long spot
+ short perpetual, incassa/paga SOLO il funding rate, nessuna esposizione
direzionale al prezzo) — l'estensione esplicitamente segnalata come "non
testata" in altcoin_carry_funding_rate_test.py (che testa invece un TILT
direzionale long-only verso l'asset col funding piu' favorevole, sommando
funding e rendimento spot sulla stessa posizione).

Qui la gamba short e' modellata nel modo piu' semplice possibile: si
assume che comprare 1 unita' di spot e vendere 1 unita' di perpetual
elimini (a meno di basis risk, dichiarato sotto come limite) l'esposizione
al prezzo — il rendimento della posizione combinata e' quindi SOLO il
funding incassato dal lato short (+relativeFundingRate quando il tasso e'
positivo, i long pagano gli short), non spot+funding come nel tilt.

LIMITI DICHIARATI (stessi dello script precedente, piu' uno nuovo):
  1. Storico funding reale via Kraken Futures: SOLO ~1 anno (limite
     dell'API pubblica, non di questo script) — un DSR/PBO qui e' MOLTO
     meno affidabile che sui ~6-7 anni degli altri test.
  2. Basis risk NON modellato: si assume prezzo spot = prezzo perpetual in
     ogni istante (nessun dato di prezzo perpetual separato disponibile in
     questo framework) — nella realta' un piccolo basis residuo esiste e
     puo' erodere/gonfiare leggermente il rendimento realizzato.
  3. Costo di capitale/opportunita' della gamba spot (il capitale
     impiegato per comprare spot potrebbe rendere un tasso privo di
     rischio altrove, es. ~4-5%/anno) NON sottratto — il rendimento qui
     e' il funding LORDO di quel costo-opportunita', quindi un limite
     superiore ottimistico del vero rendimento incrementale.
  4. Costi di transazione per aprire/chiudere le due gambe (spot + short
     perpetual) non modellati per la posizione statica (assunti
     trascurabili su una posizione tenuta ferma per l'intero campione,
     un'unica apertura) — irrilevanti per il confronto qui sotto perche'
     identici su tutte le varianti.
"""
from __future__ import annotations
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "framework"))
from metrics import cagr, sharpe, max_drawdown, calmar
from statistical_validation import deflated_sharpe_ratio
from altcoin_vs_btc_daily_backtest import load_daily, DATA_DIR as DAILY_PRICE_DIR
from altcoin_carry_funding_rate_test import FUNDING_DATA_DIR, SYMBOLS, PERIODS_PER_YEAR, fetch_all_funding_data


def load_daily_short_side_yield(ticker: str) -> pd.Series:
    """Rendimento di funding GIORNALIERO per chi e' SHORT il perpetual —
    segno opposto a load_daily_funding_yield (quella e' per il LONG).
    Convenzione: relativeFundingRate positivo = i long pagano gli short."""
    path = FUNDING_DATA_DIR / f"{ticker.replace('-', '_')}_funding_hourly.csv"
    hourly = pd.read_csv(path, index_col=0, parse_dates=True).iloc[:, 0]
    hourly.index = hourly.index.tz_localize(None)
    return hourly.resample("D").sum()


def main():
    if not FUNDING_DATA_DIR.exists() or not any(FUNDING_DATA_DIR.glob("*_funding_hourly.csv")):
        print(f"[*] Nessun dato di funding in cache in {FUNDING_DATA_DIR}, scarico da Kraken Futures...")
        fetch_all_funding_data()

    short_yield = {t: load_daily_short_side_yield(t) for t in SYMBOLS}
    common = short_yield["BTC-USD"].index
    for s in short_yield.values():
        common = common.intersection(s.index)
    print(f"Campione carry market-neutral (Kraken Futures funding): {len(common)} giorni, "
          f"{common.min().date()} -> {common.max().date()} — SOLO ~1 anno, limite dell'API.")

    mn_returns = pd.DataFrame({t: short_yield[t].reindex(common) for t in SYMBOLS})
    btc_spot_ret = load_daily("BTC-USD").pct_change().reindex(common).fillna(0.0)

    print(f"\n{'Asset (market-neutral, solo funding)':<40}{'Yield annualizzato':>20}{'Vol annualizzata':>18}"
          f"{'Sharpe':>9}{'MaxDD':>9}{'Corr. vs BTC spot':>20}")
    for t in SYMBOLS:
        s = mn_returns[t]
        ann_yield = s.mean() * PERIODS_PER_YEAR * 100
        ann_vol = s.std() * np.sqrt(PERIODS_PER_YEAR) * 100
        sr = sharpe(s, periods_per_year=PERIODS_PER_YEAR)
        mdd = max_drawdown(s) * 100
        corr = s.corr(btc_spot_ret)
        print(f"{t:<40}{ann_yield:>19.2f}%{ann_vol:>17.2f}%{sr:>9.2f}{mdd:>8.2f}%{corr:>20.3f}")

    blend = mn_returns.mean(axis=1)  # equal-weight sui 6 asset, diversifica il rischio idiosincratico di funding
    ann_yield_blend = blend.mean() * PERIODS_PER_YEAR * 100
    ann_vol_blend = blend.std() * np.sqrt(PERIODS_PER_YEAR) * 100
    sr_blend = sharpe(blend, periods_per_year=PERIODS_PER_YEAR)
    mdd_blend = max_drawdown(blend) * 100
    corr_blend = blend.corr(btc_spot_ret)
    print(f"\n{'Blend equal-weight (6 asset)':<40}{ann_yield_blend:>19.2f}%{ann_vol_blend:>17.2f}%"
          f"{sr_blend:>9.2f}{mdd_blend:>8.2f}%{corr_blend:>20.3f}")

    print(f"\nConfronto — BTC spot (direzionale, per contesto): CAGR {cagr(btc_spot_ret, PERIODS_PER_YEAR)*100:.1f}%  "
          f"Sharpe {sharpe(btc_spot_ret, periods_per_year=PERIODS_PER_YEAR):.2f}  MaxDD {max_drawdown(btc_spot_ret)*100:.1f}%")

    dsr_blend = deflated_sharpe_ratio(sr_blend, n_trials=7, n_obs=len(blend))  # 6 singoli + 1 blend
    print(f"\nDSR del blend (n_trials=7, n_obs={len(blend)} — CAMPIONE CORTO, DSR poco informativo qui): {dsr_blend:.4f}")
    print("\nAvvertenza: ~1 anno di dati non e' sufficiente per un verdetto istituzionale robusto — "
          "questi numeri sono indicativi, non allo stesso livello di rigore degli altri test in questa cartella. "
          "Il rendimento e' inoltre LORDO del costo-opportunita' del capitale nella gamba spot (limite 3 sopra).")


if __name__ == "__main__":
    main()
