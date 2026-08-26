# Apex Multi-Asset Quantitative Engine 🦅

Sistema quantitativo autonomo multi-asset basato su Macro Allocation a cascata (Waterfall), Cross-Sectional Momentum su S&P 500 e Crypto, Trailing Stops ancorati alla volatilità (ATR), ribilanciamento periodico e notifiche automatiche via Telegram.

---

## 🏛️ Architettura del Sistema

```
                        ┌───────────────────────────────┐
                        │   Macro Waterfall Engine      │
                        │   (RSP, BTC, GC=F, IEF > MA200)│
                        └──────────────┬────────────────┘
                                       │
            ┌──────────────────────────┼──────────────────────────┐
            ▼                          ▼                          ▼
   ┌─────────────────┐        ┌─────────────────┐        ┌─────────────────┐
   │ Azioni (Max 70%)│        │ Crypto (Max 15%)│        │  Oro (Max 10%)  │
   │ S&P 500 Top 20  │        │ Spot / Perp Top3│        │ Copertura Macro │
   └─────────────────┘        └─────────────────┘        └─────────────────┘
                                       │
                                       ▼ (Capitale Residuo)
                              ┌─────────────────┐
                              │ Obbligazioni /  │
                              │ Liquidità (Resto│
                              └─────────────────┘
```

1. **Macro Waterfall Cockpit**:
   - **Azioni**: Fino al 70% se `RSP > 200 SMA`
   - **Crypto**: Fino al 15% se `BTC > 200 SMA`
   - **Oro**: Fino al 10% se `GC=F > 200 SMA`
   - **Obbligazioni**: Assorbe tutto il capitale residuo se `IEF > 200 SMA`
   - **Liquidità**: Rifugio monetario se nessun asset è in trend positivo
2. **Selezione Cross-Sectional Momentum**:
   - Classifica i titoli in base a $\text{Score} = \frac{\text{ROC}(130)}{\text{NATR}(60)}$
   - Filtro di ammissione: $\text{Prezzo} > \text{MA}(150)$, $\text{Score} > 0$, assenza di gap anomali
3. **Gestione del Rischio & Trailing Stops**:
   - Livello di protezione continuo a $\text{HH}(60) - 3.0 \times \text{ATR}(60)$
   - Esecuzione stop automatica giornaliera; aggiornamento trailing stop ogni venerdì
   - Rotazione mensile dell'azionario l'ultimo venerdì del mese

---

## 📂 Struttura del Progetto

```text
├── .github/workflows/
│   └── update_data.yml     # Cronjob GitHub Actions (giornaliero alle 23:00 UTC)
├── app.py                  # Dashboard Streamlit Web
├── backend.py              # Motore di calcolo quantitativo e pipeline ordini
├── apex_data.json          # Stato dei segnali e classifiche
├── portfolio.json          # Posizioni aperte, stop loss e storico trade
├── equity.json             # Serie storica Mark-to-Market dell'Equity Curve
├── requirements.txt        # Dipendenze Python
└── research/               # Suite di simulazione e backtest a 20 anni
```

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
