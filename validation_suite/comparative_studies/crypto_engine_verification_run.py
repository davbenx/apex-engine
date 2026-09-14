"""
crypto_engine_verification_run.py — Esegue il motore Crypto Frontier Venture (versione
corrente, post-fix dei 3 bug corretti nel commit a12382b) su crypto_verification_data/
(40 large-cap, universo statico — vedi README nella stessa cartella per i limiti
metodologici) e stampa il riepilogo lordo e netto da tasse italiane.

Finding di riferimento (audit di questa sessione, stesso dataset, pre-fix vs post-fix):

                    CAGR      Sharpe    MaxDD     CumulativeTax   FinalNAV
  Lordo  pre-fix   46.59%     0.997    -56.71%         -              207,898
  Lordo  post-fix  46.48%     0.995    -56.91%         -              206,715
  Netto  pre-fix   35.79%     0.751    -58.55%      49,311            113,279
  Netto  post-fix  40.05%     0.849    -57.97%      29,322            144,727

Il lordo e' pressoche' invariato (i 2 bug di lookahead/execution price hanno impatto
marginale su questo dataset/periodo); il netto migliora nettamente (CAGR +4.3pp,
Sharpe +0.10, tasse pagate -40%) perche' il bug del cost-basis nel free-ride
sovrastimava sistematicamente il guadagno tassabile. Conferma diretta, su dati di
mercato reali, che il fix e' un beneficio netto per l'obiettivo "CAGR netto tasse
italiane" del progetto.
"""
from __future__ import annotations
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from crypto_frontier_venture_engine import load_crypto_dataset, precompute_market_matrices, run_crypto_venture_backtest, CryptoVentureConfig

CACHE_DIR = Path(__file__).resolve().parent / "crypto_verification_data"


def print_summary(label: str, summary: dict):
    print(f"\n=== {label} ===")
    for k, v in summary.items():
        print(f"  {k}: {v}")


def main():
    dfs = load_crypto_dataset(str(CACHE_DIR))
    print(f"Universo caricato: {len(dfs)} asset")
    cfg = CryptoVentureConfig(universe_mode="TOP25", max_slots=7)
    matrices = precompute_market_matrices(dfs, cfg)
    print(f"Simulazione: {matrices['simulation_dates'][0].date()} -> {matrices['simulation_dates'][-1].date()} "
          f"({len(matrices['simulation_dates'])} giorni)")

    res_gross = run_crypto_venture_backtest(matrices, cfg, tax_enabled=False)
    print_summary("LORDO", res_gross["summary"])

    res_net = run_crypto_venture_backtest(matrices, cfg, tax_enabled=True)
    print_summary("NETTO TASSE ITALIANE 26%", res_net["summary"])


if __name__ == "__main__":
    main()
