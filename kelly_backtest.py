"""
kelly_backtest.py — Backtest walk-forward, con tassazione italiana netta, per
validare (o falsificare) il disegno di Kelly Stack su dati storici reali.

Metodologia (stessa disciplina di APEX_V2_SPEC.md §8.4 "Walk-forward vero"):
i pesi Kelly si calibrano SOLO sulla prima meta' del campione disponibile
(mu/sigma/correlazione stimati sui dati storici reali, non sui prior di
letteratura di kelly_engine.py) e si APPLICANO SENZA RI-OTTIMIZZARE sulla
seconda meta' — questo e' l'unico modo onesto di sapere se il disegno regge
fuori campione o se i numeri validi solo sul periodo su cui sono stati scelti.

Le sleeve UCITS reali (NTSG/AVWS/DBMFE/PPFB/WBTC) hanno storico troppo corto
o non tradabile per un backtest robusto: si usano PROXY con storico lungo,
esattamente come Apex usa SPY come proxy di segnale per il basket azionario
reale (APEX_V2_SPEC.md §1). JELS non ha uno storico Yahoo disponibile ed e'
escluso dal backtest (limite dichiarato, non nascosto — vedi report finale).

Tassazione italiana: reddito di capitale (NTSG/AVWS/DBMFE proxy — ETF) tassato
al 26% flat SOLO sui guadagni realizzati ad ogni ribilanciamento, senza
compensazione di minusvalenze; reddito diverso (PPFB/WBTC proxy — ETC/ETP)
compensa le minusvalenze in un pool cumulativo (stessa idea del TaxLedger di
Apex, APEX_V2_SPEC.md §8.9-bis, semplificato senza il limite FIFO a 4 anni —
Apex ha gia' verificato che quel limite quasi mai vincola per disegni con
turnover simile a questo, §8.9 punto 3).
"""

from __future__ import annotations
import json
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from kelly_engine import compute_kelly_weights

TAX_RATE = 0.26

# Universo di ticker fetchabili usati come proxy a storico lungo delle sleeve
# reali (vedi build_sleeve_returns per la mappatura esatta).
BACKTEST_TICKERS = ["SPY", "IEF", "VBR", "DBMF", "GLD", "BTC-USD"]


def fetch_universe(data_dir: str, tickers: Optional[List[str]] = None) -> None:
    """
    Scarica e cachea su disco (CSV, un file per ticker) i prezzi mensili
    aggiustati per dividendi, via l'endpoint Yahoo Chart API — stesso stile
    HTTP diretto di backend.py.fetch_yahoo_history (nessuna nuova dipendenza,
    es. yfinance), con due correzioni rispetto a quella funzione (necessarie
    per questo uso, non per il segnale di timing di Apex):

    1. Cattura il campo 'adjclose' (rendimento totale, dividendi inclusi) e non
       solo 'close' — un backtest di CAGR su azionario/bond/credito con prezzo
       non aggiustato sottostimerebbe sistematicamente il rendimento reale
       rispetto a oro/crypto (che non pagano dividendi). Per un segnale di
       trend (Apex) il prezzo grezzo va bene; per stimare mu atteso no.
    2. Ri-campiona esplicitamente a fine mese dopo il fetch, invece di fidarsi
       del parametro 'interval' richiesto: verificato che Yahoo lo onora in
       modo incoerente a seconda della lunghezza dello storico disponibile per
       ciascun ticker (es. DBMF, storico piu' corto, torna dati settimanali
       anche chiedendo '1mo').
    """
    tickers = tickers if tickers is not None else BACKTEST_TICKERS
    Path(data_dir).mkdir(parents=True, exist_ok=True)
    for t in tickers:
        url = f"https://query2.finance.yahoo.com/v8/finance/chart/{t}?range=max&interval=1wk"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        res = json.loads(urllib.request.urlopen(req, timeout=15).read().decode())
        result = res["chart"]["result"][0]
        ts = pd.to_datetime(result["timestamp"], unit="s")
        adj = result["indicators"]["adjclose"][0]["adjclose"]
        monthly = pd.Series(adj, index=ts).dropna().resample("ME").last().dropna()
        monthly.to_csv(Path(data_dir) / f"{t.replace('-', '_')}_monthly.csv")
        time.sleep(0.3)


def load_monthly_series(data_dir: str, tickers: List[str]) -> Dict[str, pd.Series]:
    """Carica le serie mensili (AdjClose) gia' scaricate da kelly_backtest_fetch.
    Ogni serie e' un pd.Series indicizzato per fine mese."""
    out = {}
    for t in tickers:
        path = Path(data_dir) / f"{t.replace('-', '_')}_monthly.csv"
        s = pd.read_csv(path, index_col=0, parse_dates=True).iloc[:, 0]
        s.index = s.index.to_period("M").to_timestamp("M")
        out[t] = s
    return out


def build_sleeve_returns(prices: Dict[str, pd.Series]) -> pd.DataFrame:
    """
    Costruisce i rendimenti mensili delle 5 sleeve backtestabili (JELS escluso,
    nessuno storico disponibile) usando PROXY a storico lungo:

      NTSG_proxy  = 0.9 * rendimento(SPY) + 0.6 * rendimento(IEF)   (stessa
                    decomposizione di leva implicita gia' documentata in
                    convex_engine.py: equity_leg=0.90, bond_leg=0.60)
      AVWS_proxy  = rendimento(VBR)   — Vanguard Small-Cap Value, storico dal 2004
      DBMFE_proxy = rendimento(DBMF)  — sorella USA di DBMFE, storico dal 2019 (CORTO)
      PPFB_proxy  = rendimento(GLD)
      WBTC_proxy  = rendimento(BTC-USD)

    Allinea tutte le serie sullo stesso calendario mensile con un inner join
    (nessun forward-fill tra serie a calendari diversi — evita esattamente il
    bug di calendario gia' trovato e corretto in apex_v2_engine.py, APEX_V2_SPEC.md §8.3).
    """
    rets = {k: v.pct_change().dropna() for k, v in prices.items()}
    df = pd.DataFrame(rets).dropna(how="any")  # inner join implicito: solo mesi comuni a TUTTE le serie passate
    out = pd.DataFrame(index=df.index)
    out["NTSG_proxy"] = 0.90 * df["SPY"] + 0.60 * df["IEF"]
    out["AVWS_proxy"] = df["VBR"]
    if "DBMF" in df.columns:
        out["DBMFE_proxy"] = df["DBMF"]
    out["PPFB_proxy"] = df["GLD"]
    if "BTC-USD" in df.columns:
        out["WBTC_proxy"] = df["BTC-USD"]
    return out


SLEEVE_TAX_TYPE = {
    "NTSG_proxy": "REDDITO_CAPITALE",
    "AVWS_proxy": "REDDITO_CAPITALE",
    "DBMFE_proxy": "REDDITO_CAPITALE",
    "PPFB_proxy": "REDDITO_DIVERSO",
    "WBTC_proxy": "REDDITO_DIVERSO",
}


@dataclass
class BacktestResult:
    label: str
    n_months_calibration: int
    n_months_oos: int
    weights_used: Dict[str, float]
    gross_leverage: float
    monthly_returns_gross: pd.Series
    monthly_returns_net: pd.Series
    cagr_gross: float
    cagr_net: float
    sharpe_gross: float
    sharpe_net: float
    max_drawdown_gross: float
    max_drawdown_net: float
    total_tax_paid_fraction: float  # tasse totali pagate / NAV iniziale, sull'intero periodo OOS


def _annualize_mean(monthly_returns: pd.Series) -> float:
    return float(monthly_returns.mean() * 12)


def _annualize_vol(monthly_returns: pd.Series) -> float:
    return float(monthly_returns.std(ddof=1) * np.sqrt(12))


def _cagr(monthly_returns: pd.Series) -> float:
    total_growth = float((1 + monthly_returns).prod())
    years = len(monthly_returns) / 12
    if years <= 0 or total_growth <= 0:
        return float("nan")
    return total_growth ** (1 / years) - 1


def _sharpe(monthly_returns: pd.Series, rf_annual: float = 0.0) -> float:
    excess = monthly_returns - rf_annual / 12
    if excess.std(ddof=1) < 1e-12:
        return 0.0
    return float(excess.mean() / excess.std(ddof=1) * np.sqrt(12))


def _max_drawdown(monthly_returns: pd.Series) -> float:
    nav = (1 + monthly_returns).cumprod()
    peak = nav.cummax()
    dd = nav / peak - 1
    return float(dd.min())


def _apply_italian_tax(
    sleeve_returns: pd.DataFrame,
    target_weights: Dict[str, float],
    tax_types: Optional[Dict[str, str]] = None,
    rebalance_every: int = 1,
) -> pd.Series:
    """
    Simula un portafoglio a pesi target fissi con ribilanciamento mensile
    (rebalance_every=1) verso quei pesi, tassando SOLO la porzione
    effettivamente venduta ad ogni ribilanciamento (stesso principio del bug
    corretto in backend.py, APEX_V2_SPEC.md §8.8: mai tassare l'intera
    posizione per un aggiustamento parziale di peso).

    Semplificazione dichiarata: costo medio ponderato (PMC) senza il limite
    FIFO a 4 anni sul riporto minusvalenze (Apex ha gia' verificato che quel
    limite quasi mai vincola su un orizzonte di questa lunghezza, §8.9 punto 3)
    e senza costi di transazione (separati dalla tassazione, non modellati qui
    per isolare l'effetto fiscale — i costi di transazione sono gia' stress-
    testati altrove nel progetto, APEX_V2_SPEC.md §8.2 test 2).

    Ritorna la serie dei rendimenti mensili NETTI di tassazione.

    NAV (capitale proprio) e valore nozionale delle posizioni sono tenuti
    ESPLICITAMENTE separati: con leva (somma dei pesi target > 100%, come nel
    disegno deployato), il valore nozionale delle posizioni supera il NAV per
    costruzione — sommare i valori nozionali e trattarli come se fossero il NAV
    porterebbe a un errore di scala che si COMPONE ogni mese (bug trovato e
    corretto durante lo sviluppo di questo backtest: un CAGR netto assurdo,
    >10.000%, causato esattamente da questa confusione).
    """
    tax_types = tax_types if tax_types is not None else SLEEVE_TAX_TYPE
    keys = list(target_weights.keys())
    nav = 1.0  # capitale proprio — MAI ricavato sommando i valori nozionali delle posizioni
    value = {k: target_weights[k] * nav for k in keys}  # valori nozionali, la somma puo' superare nav (leva)
    cost_basis = dict(value)
    loss_pool_diverso = 0.0  # minusvalenze REDDITO_DIVERSO non ancora compensate

    net_returns = []
    for _, row in sleeve_returns.iterrows():
        # 1. rendimento lordo di portafoglio del mese dai pesi CORRENTI (rispetto al nav
        #    pre-rivalutazione) — stessa convenzione lineare gia' usata per port_gross
        weights_now = {k: value[k] / nav for k in keys}
        gross_port_return = sum(weights_now[k] * row[k] for k in keys)
        nav_after_market = nav * (1 + gross_port_return)

        # 2. rivaluta ciascuna posizione al proprio rendimento
        for k in keys:
            value[k] *= (1 + row[k])

        # 3. ribilancia le posizioni verso i pesi target rispetto al NUOVO nav (pre-tasse),
        #    tassando solo il delta venduto (mai l'intera posizione — stesso principio del
        #    bug corretto in backend.py, APEX_V2_SPEC.md §8.8)
        tax_due = 0.0
        for k in keys:
            target_val = target_weights[k] * nav_after_market
            delta = target_val - value[k]
            if delta < 0:
                sold_fraction = min(1.0, (-delta) / value[k]) if value[k] > 1e-12 else 0.0
                cost_sold = cost_basis[k] * sold_fraction
                proceeds_sold = value[k] * sold_fraction
                gain = proceeds_sold - cost_sold
                tax_type = tax_types[k]
                if tax_type == "REDDITO_CAPITALE":
                    if gain > 0:
                        tax_due += gain * TAX_RATE
                    # minusvalenza REDDITO_CAPITALE: persa, non compensabile (stessa regola di Convex/Apex)
                else:  # REDDITO_DIVERSO
                    if gain > 0:
                        offset = min(gain, loss_pool_diverso)
                        loss_pool_diverso -= offset
                        tax_due += (gain - offset) * TAX_RATE
                    else:
                        loss_pool_diverso += -gain
                cost_basis[k] -= cost_sold
            else:
                cost_basis[k] += delta  # acquisto: aggiorna il costo base (media ponderata, PMC)
            value[k] = target_val

        nav_after_tax = nav_after_market - tax_due
        # la tassa riduce il capitale proprio: scala tutte le posizioni proporzionalmente
        # per mantenere la leva target costante dopo il prelievo fiscale
        if nav_after_market > 1e-12 and tax_due > 0:
            scale = nav_after_tax / nav_after_market
            for k in keys:
                value[k] *= scale
                cost_basis[k] *= scale

        net_returns.append(nav_after_tax / nav - 1)
        nav = nav_after_tax

    return pd.Series(net_returns, index=sleeve_returns.index)


def walk_forward_backtest(
    sleeve_returns: pd.DataFrame,
    label: str,
    kelly_fraction: float = 0.5,
    max_gross_leverage: float = 1.5,
    max_sleeve_weight: float = 0.6,
) -> BacktestResult:
    """
    Split a meta': calibra mu/sigma/corr SOLO sulla prima meta', applica i pesi
    risultanti SENZA ri-ottimizzare sulla seconda meta' (out-of-sample).
    """
    n = len(sleeve_returns)
    split = n // 2
    calib = sleeve_returns.iloc[:split]
    oos = sleeve_returns.iloc[split:]

    keys = list(sleeve_returns.columns)
    mu = {k: _annualize_mean(calib[k]) for k in keys}
    sigma = {k: _annualize_vol(calib[k]) for k in keys}
    corr = calib.corr().loc[keys, keys].values

    dummy_sleeves = {k: {"mu_prior": mu[k], "sigma_prior": sigma[k]} for k in keys}
    res = compute_kelly_weights(
        mu=mu, sigma=sigma, corr=corr, sleeves=dummy_sleeves,
        kelly_fraction=kelly_fraction, max_gross_leverage=max_gross_leverage,
        max_sleeve_weight=max_sleeve_weight,
    )
    weights = res.final_weights

    port_gross = (oos * pd.Series(weights)).sum(axis=1)
    port_net = _apply_italian_tax(oos, weights)

    total_tax_fraction = float((1 + port_gross).prod() - (1 + port_net).prod())

    return BacktestResult(
        label=label,
        n_months_calibration=len(calib),
        n_months_oos=len(oos),
        weights_used=weights,
        gross_leverage=res.gross_leverage_final,
        monthly_returns_gross=port_gross,
        monthly_returns_net=port_net,
        cagr_gross=_cagr(port_gross),
        cagr_net=_cagr(port_net),
        sharpe_gross=_sharpe(port_gross),
        sharpe_net=_sharpe(port_net),
        max_drawdown_gross=_max_drawdown(port_gross),
        max_drawdown_net=_max_drawdown(port_net),
        total_tax_paid_fraction=total_tax_fraction,
    )


def rolling_walk_forward(
    sleeve_returns: pd.DataFrame,
    label: str,
    n_folds: int = 4,
    kelly_fraction: float = 0.5,
    max_gross_leverage: float = 1.5,
    max_sleeve_weight: float = 0.6,
) -> List[BacktestResult]:
    """
    Walk-forward a finestra espansiva su n_folds fold, invece di un singolo split
    a meta'. Un solo split (walk_forward_backtest) puo' essere fortunato o
    sfortunato per puro caso campionario — piu' finestre out-of-sample
    indipendenti danno una DISTRIBUZIONE di risultati, non un singolo punto, ed
    e' l'unico modo onesto di distinguere un edge robusto da un singolo periodo
    favorevole (esattamente il dubbio sollevato dal confronto campione
    corto/lungo in questo stesso modulo).

    Fold i (i=1..n_folds): calibra su tutti i dati fino al punto i/(n_folds+1)
    del campione, testa sul blocco successivo 1/(n_folds+1). Ogni fold usa PIU'
    dati di calibrazione del precedente (finestra espansiva, non fissa).
    """
    n = len(sleeve_returns)
    block = n // (n_folds + 1)
    results = []
    for i in range(1, n_folds + 1):
        calib_end = i * block
        oos_end = (i + 1) * block if i < n_folds else n
        calib = sleeve_returns.iloc[:calib_end]
        oos = sleeve_returns.iloc[calib_end:oos_end]
        if len(oos) < 3:
            continue

        keys = list(sleeve_returns.columns)
        mu = {k: _annualize_mean(calib[k]) for k in keys}
        sigma = {k: _annualize_vol(calib[k]) for k in keys}
        corr = calib.corr().loc[keys, keys].values
        dummy_sleeves = {k: {"mu_prior": mu[k], "sigma_prior": sigma[k]} for k in keys}
        res = compute_kelly_weights(
            mu=mu, sigma=sigma, corr=corr, sleeves=dummy_sleeves,
            kelly_fraction=kelly_fraction, max_gross_leverage=max_gross_leverage,
            max_sleeve_weight=max_sleeve_weight,
        )
        weights = res.final_weights
        port_gross = (oos * pd.Series(weights)).sum(axis=1)
        port_net = _apply_italian_tax(oos, weights)

        results.append(BacktestResult(
            label=f"{label} — fold {i}/{n_folds} ({oos.index[0].date()} -> {oos.index[-1].date()})",
            n_months_calibration=len(calib), n_months_oos=len(oos),
            weights_used=weights, gross_leverage=res.gross_leverage_final,
            monthly_returns_gross=port_gross, monthly_returns_net=port_net,
            cagr_gross=_cagr(port_gross), cagr_net=_cagr(port_net),
            sharpe_gross=_sharpe(port_gross), sharpe_net=_sharpe(port_net),
            max_drawdown_gross=_max_drawdown(port_gross), max_drawdown_net=_max_drawdown(port_net),
            total_tax_paid_fraction=float((1+port_gross).prod() - (1+port_net).prod()),
        ))
    return results


def print_result(r: BacktestResult) -> None:
    print(f"\n=== {r.label} ===")
    print(f"Calibrazione: {r.n_months_calibration} mesi | Out-of-sample: {r.n_months_oos} mesi")
    print(f"Pesi (leva lorda {r.gross_leverage*100:.0f}%): "
          + ", ".join(f"{k}={v*100:.1f}%" for k, v in r.weights_used.items()))
    print(f"CAGR lordo: {r.cagr_gross*100:6.2f}%   | CAGR netto IT: {r.cagr_net*100:6.2f}%")
    print(f"Sharpe lordo: {r.sharpe_gross:5.2f}    | Sharpe netto: {r.sharpe_net:5.2f}")
    print(f"MaxDD lordo: {r.max_drawdown_gross*100:6.2f}%  | MaxDD netto: {r.max_drawdown_net*100:6.2f}%")


if __name__ == "__main__":
    import sys
    from kelly_validation import deflated_sharpe_ratio

    data_dir = sys.argv[1] if len(sys.argv) > 1 else "./kelly_backtest_data"
    if not Path(data_dir).exists() or not any(Path(data_dir).glob("*_monthly.csv")):
        print(f"[*] Nessun dato in cache in {data_dir}, scarico da Yahoo Finance...")
        fetch_universe(data_dir)

    prices_full = load_monthly_series(data_dir, BACKTEST_TICKERS)
    sleeve_full = build_sleeve_returns(prices_full)
    print(f"\nCampione COMPLETO (con DBMFE+WBTC): {len(sleeve_full)} mesi, "
          f"{sleeve_full.index.min().date()} -> {sleeve_full.index.max().date()}")
    for r in rolling_walk_forward(sleeve_full, "Full", n_folds=4):
        print_result(r)

    sleeve_long = build_sleeve_returns({k: v for k, v in prices_full.items() if k in ("SPY", "IEF", "VBR", "GLD")})
    print(f"\nCampione LUNGO (senza DBMFE/WBTC): {len(sleeve_long)} mesi, "
          f"{sleeve_long.index.min().date()} -> {sleeve_long.index.max().date()}")
    for r in rolling_walk_forward(sleeve_long, "Long", n_folds=5):
        print_result(r)

    single_split = walk_forward_backtest(sleeve_full, "Full — singolo split 50/50 (per confronto col multi-fold sopra)")
    print_result(single_split)
    dsr = deflated_sharpe_ratio(single_split.sharpe_net, n_trials=3, n_obs=single_split.n_months_oos)
    print(f"\nDSR (singolo split, 3 varianti di universo provate): {dsr:.3f}")
    print("\nVedi KELLY_STACK_SPEC.md §7.1 per l'interpretazione di questi numeri "
          "(in particolare: perche' il singolo split sopra e' fuorviante rispetto al multi-fold).")
