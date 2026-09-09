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

from kelly_engine import (
    compute_kelly_weights,
    KELLY_VOL_TARGET,
    KELLY_DD_DERISK_TRIGGER,
    KELLY_DD_DERISK_FLOOR,
)

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


def compute_tsmom_sleeve_returns(
    prices: Dict[str, pd.Series],
    lookback_months: int = 12,
    vol_target_per_market: float = 0.10,
    vol_window: int = 12,
    short_lookback_months: Optional[int] = None,
) -> pd.Series:
    """
    Sleeve di trend-following sistematico MULTI-MERCATO — non un gate
    acceso/spento su sleeve gia' esistenti (gia' testato e limitato dalle
    tasse, KELLY_STACK_SPEC.md §7.1 Risultato 7), ma una sleeve INDIPENDENTE
    che applica il time-series momentum (Moskowitz/Ooi/Pedersen 2012,
    "Time Series Momentum") su piu' mercati scorrelati — la stessa logica
    usata dai CTA sistematici (Winton, Dunn Capital, AHL): ogni mercato viene
    tradato long o flat in base al segno del proprio rendimento cumulato a
    `lookback_months`, scalato a un vol-target comune (altrimenti il mercato
    piu' volatile domina — stesso principio della risk parity, qui applicato
    correttamente DENTRO una singola sleeve di trend, non tra classi di
    rischio eterogenee dove Apex l'ha gia' vista fallire, §8.1).

    `short_lookback_months`: se impostato, richiede che il momentum a breve
    concordi in segno con quello a `lookback_months` (altrimenti flat quel
    mese) — stessa idea della conferma multi-timeframe di Apex
    (`V2_SHORT_MA_WEEKS`, APEX_V2_SPEC.md §8.9), qui su un segnale di
    momentum invece che su un incrocio di medie mobili. Filtra i whipsaw in
    cui il trend di lungo periodo si e' appena invertito ma quello breve non
    lo confirma ancora. None (default) = nessuna conferma, comportamento
    originale (KELLY_STACK_SPEC.md §7.1 Risultato 8).

    Nessun lookahead: il segnale e il vol-scale del mese t usano solo prezzi
    fino al mese t-1 (shift(1) esplicito prima di applicarli al rendimento
    realizzato nel mese t).
    """
    rets = {k: v.pct_change().dropna() for k, v in prices.items()}
    df = pd.DataFrame(rets).dropna(how="any")
    keys = list(df.columns)
    price_index = (1 + df).cumprod()

    position_returns = pd.DataFrame(index=df.index, columns=keys, dtype=float)
    for k in keys:
        trailing_vol = df[k].rolling(vol_window).std() * np.sqrt(12)
        trailing_mom_long = price_index[k].pct_change(lookback_months)
        signal_long = np.sign(trailing_mom_long.shift(1))

        if short_lookback_months is not None:
            trailing_mom_short = price_index[k].pct_change(short_lookback_months)
            signal_short = np.sign(trailing_mom_short.shift(1))
            signal = signal_long.where(signal_long == signal_short, 0.0)
        else:
            signal = signal_long

        vol_scale = (vol_target_per_market / trailing_vol.shift(1)).clip(upper=2.0)
        position_returns[k] = signal * vol_scale * df[k]

    return position_returns.mean(axis=1).dropna()


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


def compute_trend_gate(
    calib_returns: pd.DataFrame,
    oos_returns: pd.DataFrame,
    ma_window: int = 10,
    hysteresis_band: float = 0.02,
) -> pd.DataFrame:
    """
    Stato di trend (1.0 attivo / 0.0 inattivo) PER SLEEVE, mese per mese, con
    isteresi — stesso meccanismo di apex_v2_engine.compute_v2_macro_signal
    (APEX_V2_SPEC.md §2), qui a cadenza mensile invece che settimanale e su un
    indice di prezzo sintetico per ciascuna sleeve (costruito componendo i suoi
    stessi rendimenti) invece che su un ticker di mercato dedicato — necessario
    perche' alcune sleeve (es. NTSG_proxy) sono gia' un blend, non un singolo
    strumento tradabile.

    Motivazione: kelly_engine.py aveva finora SOLO un governatore reattivo a
    livello di PORTAFOGLIO (vol-target + drawdown, compute_dynamic_target_weights)
    — mai un segnale di trend per singola sleeve. E' proprio quel segnale (uscire
    da un downtrend PRIMA che danneggi il portafoglio, non scalare l'esposizione
    DOPO che il danno e' gia' visibile nella volatilita'/drawdown realizzati) a
    dare ad Apex il suo Sharpe/Calmar superiori — vedi confronto in
    KELLY_STACK_SPEC.md §7.1 Risultato 7.

    Stato riportato avanti dalla calibrazione all'OOS (nessun reset artificiale
    al bordo del walk-forward — lo stato di isteresi del motore live non si
    resetta il giorno dello split di un test). Nessun lookahead: ogni mese usa
    solo prezzi fino a quel mese incluso.
    """
    keys = list(calib_returns.columns)
    all_returns = pd.concat([calib_returns, oos_returns])
    price_index = (1 + all_returns).cumprod()
    start_idx = len(calib_returns)

    state = {k: True for k in keys}  # fail-open: attivo finche' non emerge un segnale contrario
    gate_rows = []
    for pos in range(len(all_returns)):
        row_gate = {}
        for k in keys:
            hist = price_index[k].iloc[:pos + 1]
            if len(hist) < ma_window + 1:
                row_gate[k] = 1.0  # dati insufficienti per una MA piena: fail-open, resta attivo
                continue
            ma = hist.iloc[-ma_window:].mean()
            price = float(hist.iloc[-1])
            dist = price / ma - 1.0 if ma > 0 else 0.0
            was_active = state[k]
            is_active = (dist > -hysteresis_band) if was_active else (dist > hysteresis_band)
            state[k] = is_active
            row_gate[k] = 1.0 if is_active else 0.0
        if pos >= start_idx:
            gate_rows.append(row_gate)

    return pd.DataFrame(gate_rows, index=oos_returns.index)


def compute_trend_gated_weights(
    calib_returns: pd.DataFrame,
    oos_returns: pd.DataFrame,
    base_weights: Dict[str, float],
    ma_window: int = 10,
    hysteresis_band: float = 0.02,
    vol_target: float = KELLY_VOL_TARGET,
    dd_trigger: float = KELLY_DD_DERISK_TRIGGER,
    dd_floor: float = KELLY_DD_DERISK_FLOOR,
    vol_window: int = 12,
) -> pd.DataFrame:
    """
    Combina il filtro di trend per sleeve (compute_trend_gate) con il
    governatore dinamico di portafoglio gia' validato
    (compute_dynamic_target_weights): una sleeve fuori trend viene spenta
    (peso 0, capitale implicitamente in cash) PRIMA che il governatore di
    volatilita'/drawdown—che guarda il portafoglio nel suo complesso, non le
    singole sleeve—abbia modo di reagire.
    """
    keys = list(base_weights.keys())
    w = pd.Series(base_weights)
    trend_gate = compute_trend_gate(calib_returns[keys], oos_returns[keys], ma_window, hysteresis_band)
    gated_weights = trend_gate.mul(w, axis=1)

    warmup_port_returns = list((calib_returns[keys] * w).sum(axis=1).iloc[-vol_window:])
    governed_port_returns: List[float] = []
    scales: List[float] = []
    nav, peak = 1.0, 1.0

    for i in range(len(oos_returns)):
        trailing = (warmup_port_returns + governed_port_returns)[-vol_window:]
        realized_vol = float(np.std(trailing, ddof=1) * np.sqrt(12)) if len(trailing) >= vol_window else None
        vol_scale = min(1.0, vol_target / realized_vol) if realized_vol and realized_vol > 1e-6 else 1.0

        drawdown = nav / peak - 1.0
        dd_scale = dd_floor if drawdown < -dd_trigger else 1.0
        scale = min(vol_scale, dd_scale)
        scales.append(scale)

        r_base = float((oos_returns.iloc[i][keys] * gated_weights.iloc[i]).sum())
        r_governed = r_base * scale
        governed_port_returns.append(r_governed)
        nav *= (1 + r_governed)
        peak = max(peak, nav)

    scale_series = pd.Series(scales, index=oos_returns.index)
    return gated_weights.mul(scale_series, axis=0)


def apply_per_sleeve_stop_loss(
    oos_returns: pd.DataFrame,
    weights: pd.DataFrame,
    stop_threshold: float = -0.15,
    recovery_buffer: float = 0.05,
) -> pd.DataFrame:
    """
    Stop-loss PER SLEEVE (non per singola posizione dentro una sleeve, e non
    il governatore di PORTAFOGLIO gia' validato): se il rendimento cumulato
    di una sleeve dal proprio ultimo picco scende sotto `stop_threshold`,
    quella sleeve viene azzerata (capitale implicito in cash) finche' il
    prezzo non recupera a `recovery_buffer` sopra il minimo toccato.

    Testato indipendentemente da quanto gia' trovato in Apex per gli stop su
    singola posizione (APEX_V2_SPEC.md §4: "peggiora sia l'edge sia l'alpha
    CAPM... genera whipsaw, non protezione aggiuntiva") — il contesto e'
    diverso (sleeve diversificate multi-asset, non singoli titoli), quindi
    non si eredita quella conclusione senza riverificarla qui (stesso
    principio di onesta' intellettuale gia' applicato al governatore
    drawdown, KELLY_STACK_SPEC.md §3).

    Riceve pesi (fissi o gia' governati) e applica lo stop SOPRA di essi —
    componibile con compute_dynamic_target_weights/compute_trend_gated_weights.
    """
    keys = list(weights.columns)
    price_index = (1 + oos_returns[keys]).cumprod()

    peak = {k: 1.0 for k in keys}
    trough = {k: None for k in keys}
    stopped_out = {k: False for k in keys}

    rows = []
    for i in range(len(oos_returns)):
        row_weight = {}
        for k in keys:
            price = float(price_index[k].iloc[i])
            peak[k] = max(peak[k], price)
            drawdown = price / peak[k] - 1.0

            if stopped_out[k]:
                trough[k] = min(trough[k], price) if trough[k] is not None else price
                if price >= trough[k] * (1 + recovery_buffer):
                    stopped_out[k] = False
                    peak[k] = price  # ripartenza: il nuovo picco e' il punto di rientro
                    trough[k] = None
            elif drawdown < stop_threshold:
                stopped_out[k] = True
                trough[k] = price

            row_weight[k] = 0.0 if stopped_out[k] else weights[k].iloc[i]
        rows.append(row_weight)

    return pd.DataFrame(rows, index=oos_returns.index)


def compute_dynamic_target_weights(
    calib_returns: pd.DataFrame,
    oos_returns: pd.DataFrame,
    base_weights: Dict[str, float],
    vol_target: float = KELLY_VOL_TARGET,
    dd_trigger: float = KELLY_DD_DERISK_TRIGGER,
    dd_floor: float = KELLY_DD_DERISK_FLOOR,
    vol_window: int = 12,
    ewma_lambda: Optional[float] = None,
) -> pd.DataFrame:
    """
    Applica mese per mese, SENZA guardare avanti, il governatore dinamico
    (Livello 2 di kelly_engine.py: vol-target + deleva su drawdown) ai pesi
    base fissi calcolati dal walk-forward. Nessuna sleeve viene mai
    ri-ottimizzata: il governatore scala l'ESPOSIZIONE TOTALE verso cash
    (`compute_kelly_weights` fa esattamente questo, qui lo si applica passo
    passo invece che una volta sola — spec §3).

    I segnali di vol/drawdown usano la storia REALIZZATA (governata) del
    portafoglio, non quella ai pesi base non scalati — coerente con come si
    comporterebbe il motore live (guarda il proprio NAV reale, non un NAV
    ipotetico senza governatore). La finestra di warm-up per la vol (prima che
    esistano `vol_window` mesi di storia governata) usa gli ultimi mesi della
    CALIBRAZIONE ai pesi base — dati noti prima dell'inizio dell'OOS, nessun
    lookahead.

    ewma_lambda: se impostato (es. 0.94, la convenzione RiskMetrics per dati
    mensili/giornalieri), la volatilità realizzata usa una media mobile
    esponenziale della varianza (piu' peso ai mesi recenti, decadimento
    geometrico) invece della finestra piatta a `vol_window` mesi — reagisce
    piu' in fretta a un cambio di regime (un singolo mese di vol alta pesa
    subito, non solo "un dodicesimo" come nella finestra piatta). None
    (default) = finestra piatta, comportamento originale.

    Ritorna un DataFrame (stesso indice di oos_returns, una colonna per
    sleeve) di pesi effettivi mese per mese, da passare a walk_forward_backtest
    style functions o direttamente a _apply_italian_tax.
    """
    keys = list(base_weights.keys())
    w = pd.Series(base_weights)
    warmup_port_returns = list((calib_returns[keys] * w).sum(axis=1).iloc[-vol_window:])

    governed_port_returns: List[float] = []
    scales: List[float] = []
    nav, peak = 1.0, 1.0

    ewma_var = float(np.var(warmup_port_returns, ddof=1)) if (ewma_lambda is not None and len(warmup_port_returns) >= 2) else None
    last_return = warmup_port_returns[-1] if warmup_port_returns else None

    for _, row in oos_returns.iterrows():
        if ewma_lambda is not None:
            if ewma_var is not None and last_return is not None:
                ewma_var = ewma_lambda * ewma_var + (1 - ewma_lambda) * last_return ** 2
                realized_vol = float(np.sqrt(ewma_var) * np.sqrt(12))
            else:
                realized_vol = None
        else:
            trailing = (warmup_port_returns + governed_port_returns)[-vol_window:]
            realized_vol = float(np.std(trailing, ddof=1) * np.sqrt(12)) if len(trailing) >= vol_window else None

        vol_scale = min(1.0, vol_target / realized_vol) if realized_vol and realized_vol > 1e-6 else 1.0

        drawdown = nav / peak - 1.0
        dd_scale = dd_floor if drawdown < -dd_trigger else 1.0
        scale = min(vol_scale, dd_scale)
        scales.append(scale)

        r_base = float((row[keys] * w).sum())
        r_governed = r_base * scale
        governed_port_returns.append(r_governed)
        last_return = r_governed
        nav *= (1 + r_governed)
        peak = max(peak, nav)

    return pd.DataFrame(
        [{k: base_weights[k] * s for k in keys} for s in scales],
        index=oos_returns.index,
    )


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


def shrink_covariance_ledoit_wolf(monthly_returns: pd.DataFrame) -> tuple:
    """
    Shrinkage di Ledoit-Wolf (2004, "Honey, I Shrunk the Sample Covariance
    Matrix") verso il target diagonale — riduce l'instabilita' della matrice
    di covarianza campionaria su finestre di calibrazione corte, lo stesso
    problema gia' segnalato in kelly_engine.py (pinv invece di inv proprio
    perche' l'inversione diretta di una covarianza quasi singolare produce
    pesi enormi e instabili). La covarianza campionaria pura e' uno stimatore
    non biased ma ad ALTA VARIANZA quando il numero di osservazioni T non e'
    molto piu' grande del numero di asset N (qui T~40-200, N~5-7 — non un
    campione enorme); la shrinkage introduce un piccolo bias per una
    riduzione di varianza molto maggiore, un trade-off documentato in
    letteratura, non un aggiustamento ad-hoc.

    Target F = matrice diagonale con le stesse varianze campionarie (le
    correlazioni vengono ridotte verso zero, le varianze restano esatte).
    Intensita' di shrinkage δ* stimata dai dati stessi (formula Ledoit-Wolf,
    non fissata a mano) — nessun parametro libero da scegliere/tunare.

    Ritorna (covarianza_shrunk_annualizzata, delta) — delta in [0,1]: 0 =
    nessuna correzione (covarianza campionaria pura), 1 = solo il target
    diagonale (correlazioni azzerate).
    """
    X = monthly_returns.values
    T, N = X.shape
    X = X - X.mean(axis=0, keepdims=True)

    S = (X.T @ X) / T  # covarianza campionaria (popolazione, mensile)
    F = np.diag(np.diag(S))  # target: stesse varianze, correlazioni a zero

    # Stima dell'intensita' di shrinkage ottimale (Ledoit-Wolf 2004, eq. 2-5):
    # pi_hat = somma delle varianze asintotiche stimate di ciascuna entrata di S,
    # rho_hat = la parte di pi_hat che il target F "assorbe gratis" (qui solo la
    # diagonale, dove F coincide esattamente con S), gamma_hat = distanza al
    # quadrato tra S e il target (solo le entrate fuori diagonale, dove F=0).
    pi_mat = np.zeros((N, N))
    for t in range(T):
        outer_t = np.outer(X[t], X[t])
        pi_mat += (outer_t - S) ** 2
    pi_mat /= T
    pi_hat = pi_mat.sum()
    rho_hat = np.diag(pi_mat).sum()  # solo le entrate diagonali: il target coincide con S li'
    gamma_hat = ((S - F) ** 2).sum()  # F ha zero sulle non-diagonali, quindi qui sono i quadrati di S fuori diagonale

    if gamma_hat < 1e-12:
        delta = 0.0
    else:
        kappa_hat = (pi_hat - rho_hat) / gamma_hat
        delta = float(np.clip(kappa_hat / T, 0.0, 1.0))

    S_shrunk = delta * F + (1 - delta) * S
    return S_shrunk * 12, delta  # annualizzata (rendimenti mensili -> varianza annua = mensile * 12)


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
    target_weights,  # Dict[str, float] (fisso) oppure pd.DataFrame (un peso per mese, stesso indice di sleeve_returns)
    tax_types: Optional[Dict[str, str]] = None,
    rebalance_every: int = 1,
) -> pd.Series:
    """
    Simula un portafoglio a pesi target verso cui si ribilancia ogni mese
    (rebalance_every=1), tassando SOLO la porzione effettivamente venduta ad
    ogni ribilanciamento (stesso principio del bug corretto in backend.py,
    APEX_V2_SPEC.md §8.8: mai tassare l'intera posizione per un aggiustamento
    parziale di peso).

    target_weights puo' essere un dict a pesi FISSI (come nel walk-forward
    "statico" di walk_forward_backtest) oppure un pd.DataFrame con un peso per
    ciascuna sleeve per ciascun mese (come nel governatore dinamico di
    compute_dynamic_target_weights) — stesso ciclo di ribilanciamento/tassazione
    in entrambi i casi, cambia solo il target verso cui ribilanciare ogni mese.
    Un peso implicito su una sleeve non elencata quel mese vale 0 (cash, mai
    tassato).

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
    is_dynamic = isinstance(target_weights, pd.DataFrame)
    first_weights = target_weights.iloc[0].to_dict() if is_dynamic else target_weights
    keys = list(first_weights.keys())
    nav = 1.0  # capitale proprio — MAI ricavato sommando i valori nozionali delle posizioni
    value = {k: first_weights[k] * nav for k in keys}  # valori nozionali, la somma puo' superare nav (leva)
    cost_basis = dict(value)
    loss_pool_diverso = 0.0  # minusvalenze REDDITO_DIVERSO non ancora compensate

    net_returns = []
    for i, (_, row) in enumerate(sleeve_returns.iterrows()):
        target_weights_t = target_weights.iloc[i].to_dict() if is_dynamic else target_weights

        # 1. rendimento lordo di portafoglio del mese dai pesi CORRENTI (rispetto al nav
        #    pre-rivalutazione) — stessa convenzione lineare gia' usata per port_gross
        weights_now = {k: value[k] / nav for k in keys}
        gross_port_return = sum(weights_now[k] * row[k] for k in keys)
        nav_after_market = nav * (1 + gross_port_return)

        # 2. rivaluta ciascuna posizione al proprio rendimento
        for k in keys:
            value[k] *= (1 + row[k])

        # 3. ribilancia le posizioni verso i pesi target (del mese corrente) rispetto al
        #    NUOVO nav (pre-tasse), tassando solo il delta venduto (mai l'intera posizione
        #    — stesso principio del bug corretto in backend.py, APEX_V2_SPEC.md §8.8)
        tax_due = 0.0
        for k in keys:
            target_val = target_weights_t.get(k, 0.0) * nav_after_market
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


def _calibrate_mu_sigma_corr(calib: pd.DataFrame, keys: List[str], use_shrinkage: bool = True):
    """
    Calibra mu/sigma/corr sulla finestra di calibrazione. Con use_shrinkage=True
    (default) la covarianza usa lo shrinkage di Ledoit-Wolf
    (shrink_covariance_ledoit_wolf) invece della covarianza campionaria grezza
    — riduce l'instabilita' della stima su finestre corte, lo stesso motivo
    per cui compute_kelly_weights usa pinv invece di inv. use_shrinkage=False
    e' mantenuto solo per confronto A/B diretto negli esperimenti di
    validazione (KELLY_STACK_SPEC.md §7.1).
    """
    mu = {k: _annualize_mean(calib[k]) for k in keys}
    if use_shrinkage:
        cov_shrunk, _delta = shrink_covariance_ledoit_wolf(calib[keys])
        sigma_arr = np.sqrt(np.diag(cov_shrunk))
        sigma = {k: float(s) for k, s in zip(keys, sigma_arr)}
        corr = cov_shrunk / np.outer(sigma_arr, sigma_arr)
    else:
        sigma = {k: _annualize_vol(calib[k]) for k in keys}
        corr = calib[keys].corr().values
    return mu, sigma, corr


def walk_forward_backtest(
    sleeve_returns: pd.DataFrame,
    label: str,
    kelly_fraction: float = 0.5,
    max_gross_leverage: float = 1.5,
    max_sleeve_weight: float = 0.6,
    tax_types: Optional[Dict[str, str]] = None,
    use_shrinkage: bool = True,
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
    mu, sigma, corr = _calibrate_mu_sigma_corr(calib, keys, use_shrinkage=use_shrinkage)

    dummy_sleeves = {k: {"mu_prior": mu[k], "sigma_prior": sigma[k]} for k in keys}
    res = compute_kelly_weights(
        mu=mu, sigma=sigma, corr=corr, sleeves=dummy_sleeves,
        kelly_fraction=kelly_fraction, max_gross_leverage=max_gross_leverage,
        max_sleeve_weight=max_sleeve_weight,
    )
    weights = res.final_weights

    port_gross = (oos * pd.Series(weights)).sum(axis=1)
    port_net = _apply_italian_tax(oos, weights, tax_types=tax_types)

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
    use_dynamic_governor: bool = False,
    use_trend_gate: bool = False,
    trend_hysteresis_band: float = 0.02,
    tax_types: Optional[Dict[str, str]] = None,
    use_shrinkage: bool = True,
    ewma_lambda: Optional[float] = None,
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
        mu, sigma, corr = _calibrate_mu_sigma_corr(calib, keys, use_shrinkage=use_shrinkage)
        dummy_sleeves = {k: {"mu_prior": mu[k], "sigma_prior": sigma[k]} for k in keys}
        res = compute_kelly_weights(
            mu=mu, sigma=sigma, corr=corr, sleeves=dummy_sleeves,
            kelly_fraction=kelly_fraction, max_gross_leverage=max_gross_leverage,
            max_sleeve_weight=max_sleeve_weight,
        )
        weights = res.final_weights
        governor_suffix = ""
        if use_trend_gate:
            dynamic_weights = compute_trend_gated_weights(calib, oos, weights, hysteresis_band=trend_hysteresis_band)
            port_gross = (oos * dynamic_weights).sum(axis=1)
            port_net = _apply_italian_tax(oos, dynamic_weights, tax_types=tax_types)
            avg_leverage = float(dynamic_weights.sum(axis=1).mean())
            governor_suffix = f" [trend-gate+governatore ON, leva media {avg_leverage*100:.0f}%]"
        elif use_dynamic_governor:
            dynamic_weights = compute_dynamic_target_weights(calib, oos, weights, ewma_lambda=ewma_lambda)
            port_gross = (oos * dynamic_weights).sum(axis=1)
            port_net = _apply_italian_tax(oos, dynamic_weights, tax_types=tax_types)
            avg_leverage = float(dynamic_weights.sum(axis=1).mean())
            governor_suffix = f" [governatore ON, leva media {avg_leverage*100:.0f}%]"
        else:
            port_gross = (oos * pd.Series(weights)).sum(axis=1)
            port_net = _apply_italian_tax(oos, weights, tax_types=tax_types)
            avg_leverage = res.gross_leverage_final

        results.append(BacktestResult(
            label=f"{label} — fold {i}/{n_folds} ({oos.index[0].date()} -> {oos.index[-1].date()}){governor_suffix}",
            n_months_calibration=len(calib), n_months_oos=len(oos),
            weights_used=weights, gross_leverage=avg_leverage,
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
