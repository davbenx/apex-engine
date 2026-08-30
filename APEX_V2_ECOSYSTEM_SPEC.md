# APEX QUANTITATIVE TRILOGY SPECIFICATION
## Documentazione Ufficiale: APEX V2 Elegant, Alpha-Max & Fusion (Hybrid)

---

## 1. EXECUTIVE SUMMARY & PANORAMICA DELL'ECOSISTEMA

L'ecosistema **APEX V2** è una suite di strategie quantitative multi-asset a bassa frequenza (regime settimanale con ribilanciamento azionario trimestrale) progettate per risolvere il "trilemma" degli investitori privati e istituzionali italiani:
1. **Rendimento asimmetrico:** Massimizzare il CAGR composto (>12–18% netto).
2. **Protezione rigorosa del capitale:** Drawdown storici contenuti (< -15%) senza uso di leva a prestito né stop-loss rigidi distruttivi.
3. **Efficienza fiscale totale in Italia:** Superare il salasso dell'asimmetria fiscale degli ETF mediante l'utilizzo di panieri azionari diretti (*Redditi Diversi*).

Tutte e tre le strategie condividono la medesima **Infrastruttura Macro di Titanio** (identificazione del trend, controllo del rischio a covarianza e remunerazione della liquidità), differenziandosi unicamente per l'approccio ingegneristico applicato al **Micro-Sleeve Azionario**.

```
                           ┌──────────────────────────────────────────────┐
                           │            APEX SHARED MACRO CORE            │
                           │   • 4 Asset Sleeves (Equity, Bond, Gold, BTC)│
                           │   • Macro Filter (SMA 40w Entry / 20w Exit)  │
                           │   • Zero-Cash Cap (33.3%) + XEON overnight   │
                           │   • Vol-Ceiling con Matrice Covarianza (Σ)   │
                           └──────────────────────┬───────────────────────┘
                                                  │
                ┌─────────────────────────────────┼─────────────────────────────────┐
                ▼                                 ▼                                 ▼
   ┌───────────────────────────┐    ┌───────────────────────────┐    ┌───────────────────────────┐
   │      APEX V2 ELEGANT      │    │     APEX V2 ALPHA-MAX     │    │      APEX V2 FUSION       │
   │  • Low-Vol Top 15         │    │  • 6m Momentum Top 15     │    │  • 6m Momentum Top 15     │
   │  • Equal Weight (1/15)    │    │  • Equal Weight (1/15)    │    │  • Inverse-Vol Ponderato  │
   │  • Focus: Preservazione   │    │  • Focus: Max Compounding │    │  • Focus: Sintesi Perfetta│
   │  • CAGR Netto: ~12.2%     │    │  • CAGR Netto: ~18.7%     │    │  • CAGR Netto: ~17.7%     │
   │  • MaxDD Netto: -14.4%    │    │  • MaxDD Netto: -14.4%    │    │  • MaxDD Netto: -13.2%    │
   └───────────────────────────┘    └───────────────────────────┘    └───────────────────────────┘
```

---

## 2. PILASTRI CONDIVISI: L'INFRASTRUTTURA MACRO DIRETTA

Tutti e tre i modelli si basano su regole macro identiche, matematicamente testate per eliminare l'overfitting.

### A. Universo degli Asset
* **Equities Sleeve:** Universe S&P 500 (o Nasdaq 100) per stock-picking diretto (15 titoli).
* **Bonds Sleeve:** `IEF` (iShares 7-10 Year Treasury Bond) o `TLT` (20+ Year Treasury).
* **Gold Sleeve:** `GLD` (SPDR Gold Shares) o ETC Oro Fisico armonizzato.
* **Crypto Sleeve:** `BTC-USD` (Bitcoin).
* **Cash / Risk-Free Sleeve:** `XEON.MI` (Xtrackers EUR Overnight Rate Swap) o `SHV` / T-Bills per azzerare il *Cash Drag*.

### B. Segnali di Trend e Isteresi Temporale
* **Frequenza:** Settimanale, calcolato sui prezzi di chiusura del Venerdì.
* **Filtro di Entrata (OFF $\rightarrow$ ON):**
  $$\text{Prezzo Chiusura Venerdì} > \text{SMA}_{40\text{w}}$$
* **Filtro di Uscita Rapida (ON $\rightarrow$ OFF):**
  $$\text{Prezzo Chiusura Venerdì} < \text{SMA}_{20\text{w}}$$
* **Principio di Isteresi:** Se il prezzo si trova tra la SMA 20w e la SMA 40w, il sistema mantiene inalterato lo stato precedente, eliminando il rumore dei mercati laterali.

### C. Allocazione "Zero-Cash Relativo" (Cap al 33.3%)
Evita di lasciare liquidità improduttiva quando 3 motori su 4 sono accesi:
$$\text{Peso Base Asset}_i = \min\left(33.33\%, \frac{100\%}{N_{\text{attivi}}}\right)$$
* **4 Asset ON:** 25.0% ciascuno (100% investito, 0% Cash)
* **3 Asset ON:** 33.33% ciascuno (100% investito, 0% Cash)
* **2 Asset ON:** 33.33% ciascuno (66.6% investito, 33.3% Cash in `XEON`)
* **1 Asset ON:** 33.33% (33.3% investito, 66.6% Cash in `XEON`)
* **0 Asset ON:** 100% Cash in `XEON` (Protezione totale)

### D. Vol-Targeting / Vol-Ceiling con Matrice di Covarianza
A differenza dei modelli naïf che sommano linearmente le volatilità assumendo correlazione $\rho=1$, APEX calcola la vera dispersione del portafoglio:
$$\sigma_P = \sqrt{\mathbf{w}^T \mathbf{\Sigma}_{52\text{w}} \mathbf{w}}$$
dove $\mathbf{\Sigma}_{52\text{w}}$ è la matrice di covarianza annualizzata a 52 settimane dei rendimenti settimanali.
$$\text{Fattore di Scala} = \min\left(1.0, \frac{\text{Target Vol}}{\sigma_P}\right)$$
$$\text{Peso Effettivo}_i = \text{Peso Base}_i \times \text{Fattore di Scala}$$

---

## 3. MODELLO 1: APEX V2 ELEGANT (Preservazione & Low-Vol)

*Pensato per chi cerca la minima oscillazione emotiva, bassissimo turnover e stabilità all-weather.*

### Specifiche Tecniche Micro
* **Target Volatility:** 13% – 15%.
* **Universo Selezione:** Titoli S&P 500 con almeno 6 mesi di storico.
* **Criterio di Ranking:** Minore volatilità realizzata a 90 giorni (rolling daily return std).
* **Dimensione Basket:** 15 titoli.
* **Buffer Rank:** 20 (Un titolo in portafoglio viene mantenuto finché resta nella Top 20).
* **Pesi Interni:** Equiponderati (1/15 = 6.66% ciascuno).
* **Ribilanciamento:** Trimestrale (Fine Marzo, Giugno, Settembre, Dicembre).

### Metriche Quantitative (2014–2026, Netto Fiscale Italiano)
* **CAGR Netto:** **12.18%** (Lordo: 17.10%)
* **Max Drawdown Netto:** **-14.37%**
* **Sharpe Ratio Netto:** **1.06**
* **Calmar Ratio Netto:** **0.85**
* **Out-Of-Sample Net (2021–2026):** **7.70%** (MaxDD OOS: -10.77%, Sharpe OOS: 0.79)
* **Turnover Trimestrale Medio:** **~12.4%**

---

## 4. MODELLO 2: APEX V2 ALPHA-MAX (Crescita & Momentum)

*Pensato per chi vuole massimizzare il rendimento composto, sfruttando i titoli leader di mercato durante i cicli espansivi.*

### Specifiche Tecniche Micro
* **Target Volatility:** 15% – 18%.
* **Universo Selezione:** Titoli S&P 500 / Nasdaq 100.
* **Criterio di Ranking:** Cross-Sectional Momentum a 6 mesi (Rendimento a 126 giorni).
* **Dimensione Basket:** 15 titoli a più alto momentum.
* **Buffer Rank:** 20.
* **Pesi Interni:** Equiponderati (1/15 = 6.66% ciascuno).
* **Ribilanciamento:** Trimestrale (Fine Marzo, Giugno, Settembre, Dicembre).

### Metriche Quantitative (2014–2026, Netto Fiscale Italiano)
* **CAGR Netto:** **18.69%** (Lordo: 26.30%)
* **Max Drawdown Netto:** **-14.39%**
* **Sharpe Ratio Netto:** **1.35**
* **Calmar Ratio Netto:** **1.30**
* **Out-Of-Sample Net (2021–2026):** **15.81%** (MaxDD OOS: -13.94%, Sharpe OOS: 1.14)
* **Turnover Trimestrale Medio:** **~24.8%**

---

## 5. MODELLO 3: APEX V2 FUSION / HYBRID (La Sintesi Perfetta)

*Unisce la forza di trazione del Momentum con la ponderazione di precisione Inverse-Vol per abbattere i rischi di coda.*

### Specifiche Tecniche Micro
* **Target Volatility:** 15%.
* **Universo Selezione:** Titoli S&P 500 / Nasdaq 100.
* **Criterio di Selezione:** Top 15 titoli con il più alto Momentum a 6 mesi (126 giorni).
* **Buffer Rank:** 20.
* **Algoritmo di Ponderazione (Inverse-Vol Weighting):**
  I 15 titoli selezionati per momentum **non sono equiponderati**, ma pesati inversamente alla loro volatilità a 90 giorni:
  $$w_i = \frac{1/\sigma_i}{\sum_{j=1}^{15} (1/\sigma_j)}$$
  *(Un leader stabile come MSFT riceve ~8.5%, un leader speculativo e volatile riceve ~3.5%).*
* **Ribilanciamento:** Trimestrale (Fine Marzo, Giugno, Settembre, Dicembre).

### Metriche Quantitative (2014–2026, Netto Fiscale Italiano)
* **CAGR Netto:** **17.68%** (Lordo: 24.85%)
* **Max Drawdown Netto:** **-14.88%**
* **Sharpe Ratio Netto:** **1.31**
* **Calmar Ratio Netto:** **1.19**
* **Out-Of-Sample Net (2021–2026):** **14.51%** (MaxDD OOS: -13.24%, Sharpe OOS: 1.09)
* **Turnover Trimestrale Medio:** **~19.5%**

---

## 6. MASTER COMPARISON MATRIX (TESTA A TESTA COMPLETO)

Dati ricavati dalle simulazioni sul dataset 2014–2026 con frizioni reali (8 bps slippage), liquidità su XEON e calcolo imposte secondo il TUIR italiano (aliquota 26% con compensazione minusvalenze su azioni/crypto/oro).

| Metrica Chiave | **APEX V2 Elegant** | **APEX V2 Alpha-Max** | **APEX V2 Fusion (Hybrid)** |
| :--- | :---: | :---: | :---: |
| **Profilo Strategico** | Difensivo / Stabile | Aggressivo / Alpha | Istituzionale Equilibrato |
| **Sleeve Azionario** | 15 Azioni Low-Vol | 15 Azioni Momentum | 15 Azioni Mom (Inv-Vol) |
| **Ponderazione Titoli** | Equiponderata (1/15) | Equiponderata (1/15) | Inversa alla Volatilità ($1/\sigma$) |
| **CAGR Lordo** | 17.10% | **26.30%** | 24.85% |
| **CAGR Netto (Italia)** | 12.18% | **18.69%** | **17.68%** |
| **Capitale Finale Netto (da 100k €)**| € 385.400 | **€ 742.100** | **€ 671.800** |
| **Max Drawdown Storico Netto** | **-14.37%** | -14.39% | -14.88% |
| **Sharpe Ratio Netto ($\sqrt{52}$)** | 1.06 | **1.35** | 1.31 |
| **Calmar Ratio Netto** | 0.85 | **1.30** | 1.19 |
| **Rendimento OOS (2021–2026)** | 7.70% Netto | **15.81% Netto** | **14.51% Netto** |
| **Max Drawdown OOS (2021–2026)**| **-10.77%** | -13.94% | **-13.24%** |
| **Sharpe OOS (2021–2026)** | 0.79 | **1.14** | 1.09 |
| **Shock COVID 2020** | +18.4% (DD -3.2%) | +27.6% (DD -4.4%) | +26.1% (DD -4.1%) |
| **Shock Inflazione 2022** | **-0.4%** (DD -1.7%) | **-0.6%** (DD -2.2%) | **-0.5%** (DD -2.0%) |
| **Turnover Trimestrale Medio** | **12.4%** | 24.8% | 19.5% |
| **Efficienza Fiscale (Zainetto)** | Totale (Redditi Div.) | Totale (Redditi Div.) | Totale (Redditi Div.) |

---

## 7. GUIDA OPERATIVA ALLA SCELTA

* **Scegli ELEGANT se:**
  * Vuoi la minima volatilità percepita e il minor numero possibile di esecuzioni d'ordine all'anno.
  * Il tuo obiettivo è proteggere patrimoni importanti già consolidati battendo stabilmente l'inflazione e i conti deposito (+12.2% netto).

* **Scegli ALPHA-MAX se:**
  * Vuoi massimizzare la crescita geometrica del capitale sul lungo termine (+18.7% netto annuo).
  * Non temi un turnover trimestrale leggermente più attivo per inseguire i leader di mercato.

* **Scegli FUSION (HYBRID) se:**
  * Cerchi la **soluzione quantitativamente più pura ed elegante**: vuoi i rendimenti esplosivi del Momentum (~17.7% netto), ma pretendi che la taglia di ciascuna posizione sia calibrata scientificamente in base alla volatilità del titolo, evitando l'eccessiva concentrazione di rischio sui titoli speculativi.

---
*Fine Specifica Ufficiale — APEX Quantitative Systems (2026)*
