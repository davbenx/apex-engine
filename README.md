# Apex Multi-Asset Quantitative Engine v2 🦅

Timing multi-asset (isteresi + vol-targeting di portafoglio) su SPY / IEF / GLD /
BTC-USD, con un basket di 15 titoli individuali a bassa volatilità al posto di un
ETF azionario (carattere fiscale "redditi diversi" in Italia). Ribilanciamento
mensile, notifiche Telegram, nessuno stop-loss per singola posizione.

**Specifica operativa completa, non ambigua: [`APEX_V2_SPEC.md`](APEX_V2_SPEC.md).**
Questo README è solo un orientamento rapido — per parametri, formule e
giustificazione di ogni scelta fai riferimento alla specifica.

v2 sostituisce il precedente motore a waterfall macro + selezione momentum Top-20:
un audit statistico indipendente ha dimostrato che quella selezione titoli aveva
expectancy negativa e statisticamente significativa (test a ingresso casuale,
Deflated Sharpe Ratio, PBO via CSCV). L'alpha di v2 viene dal *timing* tra classi
di attivo, verificato con regressione CAPM (alpha ~10-11%/anno, p<0.001, confermato
anche fuori-campione).

---

## 🏛️ Architettura del Sistema

```
        ┌──────────────────────────────────────────────────────────┐
        │  Segnale di timing (per classe, indipendente)              │
        │  prezzo vs MA(40w) + isteresi ±2% → attivo/inattivo         │
        └───────────────────────────┬──────────────────────────────┘
                                     │
                    ┌────────────────┴────────────────┐
                    │  Vol-targeting di portafoglio     │
                    │  scala l'esposizione totale verso  │
                    │  un target di volatilità (13%)     │
                    └────────────────┬────────────────┘
                                     │
      ┌───────────────┬─────────────┼─────────────┬───────────────┐
      ▼               ▼             ▼             ▼               ▼
┌───────────┐   ┌───────────┐ ┌───────────┐ ┌───────────┐  ┌───────────┐
│ Azionario │   │   Bond    │ │    Oro    │ │  Crypto   │  │   Cash    │
│ 15 titoli │   │    IEF    │ │    GLD    │ │  BTC-USD  │  │  residuo  │
│ bassa vol.│   │           │ │           │ │           │  │           │
│(rot. trim)│   │           │ │           │ │           │  │           │
└───────────┘   └───────────┘ └───────────┘ └───────────┘  └───────────┘
```

1. **Segnale di timing**: per ciascuna classe, isteresi ±2% attorno alla MA a 40
   settimane del proxy di segnale (SPY / IEF / GLD / BTC-USD).
2. **Vol-targeting**: scala l'intera esposizione (mai a leva) per centrare una
   volatilità di portafoglio del 13%, stimata sulle ultime 12 settimane.
3. **Basket azionario**: 15 titoli a **bassa volatilità realizzata** (non momentum)
   tra i membri storici dell'S&P 500, equal-weight, rotazione trimestrale della
   composizione. Nessuno stop-loss per singola posizione — l'uscita è solo per
   rotazione o disattivazione della classe.
4. **Crypto**: solo BTC-USD, nessuna rotazione verso altcoin (testata e respinta).

---

## 📂 Struttura del Progetto

```text
├── .github/workflows/
│   └── update_data.yml     # Cronjob GitHub Actions (giornaliero alle 23:00 UTC)
├── app.py                  # Dashboard Streamlit Web
├── backend.py              # Pipeline: segnale → ribilanciamento → notifiche
├── apex_v2_engine.py        # Motore isolato: segnale, vol-target, selezione basket
├── test_apex_v2_engine.py   # Test unitari su dati sintetici
├── APEX_V2_SPEC.md          # Specifica operativa completa (fonte di verità)
├── apex_data.json          # Stato dei segnali, basket e isteresi (v2_state)
├── portfolio.json          # Posizioni aperte, pesi e storico trade
├── equity.json             # Serie storica Mark-to-Market dell'Equity Curve
├── requirements.txt        # Dipendenze Python
└── research/               # Suite di simulazione e backtest storici

---

## 🚀 Avvio Locale

### 1. Prerequisiti e Installazione
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Esecuzione Pipeline Quantitativa (Backend)
```bash
python backend.py
```

### 3. Avvio Dashboard Streamlit (Frontend)
```bash
streamlit run app.py
```

---

## ⚙️ Variabili d'Ambiente (Opzionali)

Per abilitare le notifiche Telegram automatiche:
- `TELEGRAM_TOKEN`: Token del Bot Telegram
- `TELEGRAM_CHAT_ID`: ID del Canale/Chat Telegram di destinazione
