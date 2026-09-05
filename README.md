# Apex Engine + Convex Stack 🦅🛡️

Due motori quantitativi, un'unica dashboard.

**Apex Engine** — timing multi-asset (isteresi + vol-targeting di portafoglio) su
SPY / IEF / GLD / BTC-USD, con un basket di 15 titoli individuali a bassa
volatilità al posto di un ETF azionario (carattere fiscale "redditi diversi"
in Italia). Ribilanciamento settimanale (decisione venerdì, esecuzione
lunedì), notifiche Telegram, nessuno stop-loss per singola posizione —
validato: ogni meccanismo di stop testato peggiora Sharpe e/o MaxDD sotto
esecuzione settimanale realistica. Motore a simulazione automatica: calcola
segnali e ordini su capitale virtuale, nessun conto broker reale collegato.

**Convex Stack** — portafoglio multi-asset a leva sistematica (122.5%
nozionale via leva implicita 1.5x su NTSG), alimentato da un PAC mensile.
Nessuna vendita salvo rari ribilanciamenti (trim) quando un asset supera la
propria banda di tolleranza. Richiede l'inserimento manuale delle quote
possedute: la dashboard calcola dove indirizzare il prossimo versamento e
se serve un ribilanciamento.

**Specifica operativa completa di Apex Engine, non ambigua:
[`APEX_V2_SPEC.md`](APEX_V2_SPEC.md).**
Questo README è solo un orientamento rapido.

---

## 🏛️ Architettura del Sistema — Apex Engine

```
        ┌──────────────────────────────────────────────────────────┐
        │  Segnale di timing (per classe, indipendente)              │
        │  prezzo vs MA(40w) + isteresi ±2% → attivo/inattivo         │
        └───────────────────────────┬──────────────────────────────┘
                                     │
                    ┌────────────────┴────────────────┐
                    │  Vol-targeting di portafoglio     │
                    │  scala l'esposizione totale verso  │
                    │  un target di volatilità (22%)     │
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

## 🛡️ Architettura del Sistema — Convex Stack

5 strumenti UCITS/ETC (versione Completa), 4 (versione Semplice, senza
AVWS): NTSG (equity core a leva) · AVWS (small cap value, solo Completa) ·
DBMFE (managed futures / crisis alpha) · PPFB (oro fisico) · WBTC (Bitcoin).
Deposito PAC diretto all'asset più sottopesato; trim solo se un asset
supera la propria banda di tolleranza (11.25% per PPFB/WBTC).

---

## 📂 Struttura del Progetto

```text
├── .github/workflows/
│   ├── update_data.yml        # Cronjob Apex Engine (giornaliero, 23:00 UTC)
│   └── convex_reminder.yml    # Promemoria PAC mensile (inattivo finché non
│                               #   configuri i secret Telegram)
├── main.py                    # Punto d'ingresso — avvia qui: streamlit run main.py
├── home_app.py                # Pagina Home — visione d'insieme combinata
├── page_apex.py                # Pagina Apex Engine
├── page_convex.py              # Pagina Convex Stack
├── backend.py                  # Pipeline Apex: segnale → ribilanciamento → notifiche
├── apex_v2_engine.py           # Motore isolato Apex: segnale, vol-target, basket
├── convex_engine.py            # Motore Convex: pesi, PAC, trim, tasse
├── portfolio_manager.py        # Sintesi combinata Apex + Convex
├── convex_telegram_reminder.py # Promemoria PAC mensile via Telegram (opzionale)
├── test_apex_v2_engine.py      # Test unitari Apex su dati sintetici
├── test_backend.py             # Test unitari backend Apex
├── test_apex_convex.py         # Test unitari integrazione Apex+Convex
├── APEX_V2_SPEC.md             # Specifica operativa completa Apex (fonte di verità)
├── config.json                  # Parametri utente (capitali, soglie, rapporto target)
├── convex_portfolio.json       # Le tue quote Convex reali (vuoto finché non le inserisci)
├── apex_data.json / portfolio.json / equity.json  # Stato live Apex (aggiornato dal cron)
└── requirements.txt             # Dipendenze Python
```

---

## 🚀 Avvio Locale

### 1. Prerequisiti e Installazione
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Esecuzione Pipeline Quantitativa Apex (Backend)
```bash
python backend.py
```

### 3. Avvio Dashboard (Frontend)
```bash
streamlit run main.py
```

---

## ⚙️ Variabili d'Ambiente (Opzionali)

Per abilitare le notifiche Telegram automatiche di Apex Engine:
- `TELEGRAM_TOKEN`: Token del Bot Telegram
- `TELEGRAM_CHAT_ID`: ID del Canale/Chat Telegram di destinazione

Lo stesso bot/canale può essere riusato per il promemoria PAC mensile di
Convex Stack (`convex_telegram_reminder.py` + `convex_reminder.yml`) — non
si attiva automaticamente, va collegato esplicitamente aggiungendo gli
stessi due secret al repository.
