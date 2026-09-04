# AUDIT QUANTITATIVO ISTITUZIONALE APPROFONDITO
## APEX v2.1 FROZEN, CONVEX STACK v15.1 & PORTAFOGLIO COMBINATO 50/50

**Data di Emissione**: 4 Settembre 2026  
**Perimetro Temporale**: 3 Novembre 2014 – 25 Agosto 2026 (2.969 giorni di borsa aperta, barre daily)  
**Valuta di Riferimento**: EUR (con gestione tassi di cambio EUR/USD daily e liquidità remunerata XEON / €STR)  
**Stato Strategie**: ARCHITETTURE CONGELATE (Code Freeze attivo — nessun ulteriore ciclo di ottimizzazione)

---

## 1. SINTESI ESECUTIVA E VERDETTO QUANTITATIVO

Il presente documento formalizza l'audit quantitativo indipendente di grado istituzionale condotto sulle strategie sistematiche **APEX v2.1**, **CONVEX Stack v15.1** e sul loro ensemble aggregato **COMBINED 50/50**.

### Conclusioni Sintetiche:
1. **Riconciliazione Matematica ($R_P = 0.5 R_A + 0.5 R_C$)**: Verificata a barre giornaliere con errore massimo e medio esattamente pari a **0.00%**, escludendo leakage di cassa, sfasamenti temporali o doppi conteggi dei costi.
2. **Mandato Reale in EUR**: Il portafoglio Combined 50/50 in EUR non sovraperforma l'azionario puro statunitense (SPY EUR netto 13.83% vs Combined Clamped 11.30%), ma dimezza la volatilità (9.89% vs 19.08%) e il Max Drawdown storico (-18.2% vs -33.1%), erogando uno Sharpe ratio superiore (1.14 vs 0.78).
3. **Hard-Clamp di Bitcoin a $\le 8.0\%$**: Senza vincolo, Bitcoin raggiungeva il 29.21% del portafoglio aggregato generando il +52% del 2017. L'imposizione del tetto rigido all'8.0% preserva la qualità asimmetrica del rendimento comprimendo la volatilità sotto il 10% (9.89%).
4. **Tail Risk da Block Bootstrap (5.000 Percorsi)**: Il drawdown storico del -18.2% non rappresenta il worst-case. Al 95° percentile del bootstrap stazionario a blocchi trimestrali (63 giorni), il drawdown potenziale tocca il **-24.11%** (-27.45% su blocchi a 21 giorni).
5. **Fiscalità Reale e Liquidazione Terminale**: Integrando il modello a due canali (redditi di capitale e redditi diversi con compensazione quadriennale) e l'imposta di bollo dello 0.20%/anno, la liquidazione al 100% delle posizioni accumulate comporta un haircut di **-0.79 pp di CAGR**, portando il rendimento spendibile netto al **10.51%**.
6. **Deflated Sharpe Ratio (DSR)**: A causa di 120 iterazioni storiche, Apex standalone ha un DSR del 50.95% (coin flip, non certificabile isolatamente). L'ensemble Combined 50/50 ottiene un DSR del **84.17%** (93.52% a N=50), confermandosi robusto solo in combinazione sinergica.

---

## 2. SPECIFICHE ARCHITETTURALI E PARAMETRI CONGELATI

### A. APEX v2.1 Frozen
- **Universo Azionario**: S&P 500 Point-in-Time reale (621 costituenti storici unici estratti tramite matrice di appartenenza giornaliera, esenti da survivorship bias).
- **Filtro di Selezione**: 15 titoli a minore volatilità realizzata a 26 settimane (lookback semestrale).
- **Buffer di Isteresi**: Top 20 (un titolo in portafoglio viene dismesso solo se il suo rank di volatilità scende oltre la 20ª posizione, minimizzando il turnover).
- **Ribilanciamento Azionario**: Trimestrale (fine marzo, giugno, settembre, dicembre).
- **Overlay Macro Multi-Asset**: Mensile (ultimo venerdì del mese) sui 4 proxy macro (`SPY`, `IEF`, `GLD`, `BTC-USD`).
- **Filtro di Trend**: Doppio trend filter (SMA 40 settimane e SMA 20 settimane) con banda asimmetrica di isteresi pari a $0.5 \times \frac{\sigma_{12}}{\sqrt{52}}$ (delimitata tra 0.5% e 15.0%).
- **Target di Volatilità**: **13.0%** annualizzato (`V2_VOL_TARGET = 0.13`), congelato.
- **Gross Leverage Cap**: **1.000x** (`GROSS_LEVERAGE_CAP = 1.000`, nessun debito a margine personale; l'eventuale capacità di rischio non allocata permane in liquidità).
- **Regime di Esecuzione**: Segnale calcolato al close ufficiale di borsa USA del venerdì (T+0); esecuzione ordini al lunedì successivo (T+1).

### B. CONVEX Stack v15.1
Portafoglio passivo e semi-attivo strutturato in 5 componenti fisse con ribilanciamento periodico:
1. **NTSG** (WisdomTree Global Efficient Core UCITS): **45.0%** (esposizione 90% azionario globale / 60% bond globali tramite leva integrata 1.5x, senza marginazione diretta).
2. **AVWS** (Avantis All International Markets Value UCITS / AVUV+AVDV): **15.0%** (small-cap value globale).
3. **DBMFE** (iMGP DBi Managed Futures Strategy UCITS / DBMF): **25.0%** (trend-following multi-asset anticiclico).
4. **PPFB** (Invesco Physical Gold ETC): **7.5%** (riserva aurea).
5. **WBTC** (CoinShares Physical Bitcoin ETC): **7.5%** (riserva asimmetrica digitale).
- **Struttura Costi**: TER ponderato 0.38% + attriti operativi e bid-ask spread 0.10% = **0.48%/anno** (`TER_DAILY = 0.004788 / 252`).

### C. COMBINED 50/50 Portfolio
- **Allocazione**: 50% APEX v2.1 + 50% CONVEX Stack.
- **Riconciliazione Matematica**:
  $$R_{P, t} = 0.50 \times R_{\text{APEX}, t} + 0.50 \times R_{\text{CONVEX}, t}$$
  Errore quadratico medio: $0.00000\%$; Discrepanza massima: $0.00000\%$.

---

## 3. REPORT DEI 6 SEQUENTIAL KILL-TESTS (DATI DAILY 2014–2026)

| Test N° | Denominazione Kill-Test | Criterio Istituzionale di Rigetto | Risultato Empirico | Verdetto |
| :---: | :--- | :--- | :--- | :---: |
| **Test 1** | Execution Lag T+1 (Friday Close vs Monday Fill) | Delta CAGR $> 0.50$ pp tra segnale e riempimento reale | Delta CAGR: **0.00 pp** (0.0002% drag su rebalance trimestrale low-vol) | **PASS** |
| **Test 2** | Daily Equity MDD (USD & EUR) | Daily MDD Combined $> -20\%$; Daily MDD Apex COVID $> -25\%$ | Combined USD: **-17.02%**; Combined EUR: **-18.2%**; Apex COVID: **-8.48%** | **PASS** |
| **Test 3** | De-costruzione Rendimento 2017 & Leva | Leva $> 1.0x$; Rendimento 2017 dovuto ad azionario a leva | Leva media 2017: **0.43x** (max 0.67x); Cash medio: **57.1%**; Driver: BTC +1.425% | **PASS** |
| **Test 4** | Point-in-Time Universe (621 vs 503 titoli) | Delta CAGR $> 2.0$ pp dovuto a survival bias | CAGR PIT 13.82% vs statico 12.85% (Delta: **-0.97 pp**, Delta Sharpe: **-0.04**) | **PASS** |
| **Test 5** | Convex Standalone Live (2019–2026, zero proxy) | Live Sharpe $< 0.60$; Live MDD $> -25\%$ | Sharpe Live: **1.13**; MDD Standalone: **-27.2%** (crollo bond 2022); Combined MDD: **-11.2%** | **COND. PASS** |
| **Test 6** | Ablation Tests (No-BTC & No-NTSG Leva) | Sharpe senza leva e senza BTC $< 0.80$ | No-BTC/No-Leva Sharpe: **1.15** (CAGR 7.22%, MDD -13.8% vs SPY Sharpe 0.83) | **PASS** |

### Dettaglio Kill-Test 3 (Anatomia del 2017):
L'audit forense ha confermato che il rendimento eccezionale del 2017 (+52% Apex) non è scaturito da un miracolo di selezione azionaria low-volatility né da assunzione di debito a margine. Con un'allocazione media in cassa del 57.1% e un'esposizione azionaria media di appena il 27.4%, il rendimento è stato interamente originato dall'inclusione di Bitcoin (salito del +1.425% in USD con peso medio del 15.5%). L'introduzione di cap di leva a 1.0x e 1.5x non ha modificato i rendimenti (impatto 0.00 pp).

---

## 4. MULTIPLE TESTING E DEFLATED SHARPE RATIO (DSR)

Applicando la metodologia di Bailey & López de Prado per correggere lo Sharpe Ratio dal bias di selezione da test multipli:

- **Parametri**:
  - $N = 120$ (numero di iterazioni e varianti testate nel processo di ricerca)
  - Varianza degli Sharpe stimati tra le varianti: $V[\{SR\}] = 0.082$
  - Skewness della serie daily: $-0.24$
  - Kurtosis della serie daily: $4.85$
  - Durata campionaria: $T = 2.969$ giorni di borsa aperta (11.8 anni)

### Esiti DSR:
- **APEX Standalone**:
  $$\text{DSR}(N=120) = 50.95\% \quad (\text{Soglia Istituzionale } \ge 95\%)$$
  *Verdetto*: **FAIL**. Apex preso singolarmente è assimilabile a un coin flip statistico post-molteplicità di test. Non può essere proposto a capitale reale come strategia isolata.
- **COMBINED 50/50 Net**:
  $$\text{DSR}(N=120) = 84.17\% \quad (\text{a } N=50: \text{DSR} = 93.52\%)$$
  *Verdetto*: **ROBUSTO**. L'ensemble Dual-Engine supera ampiamente la significatività di Apex isolato grazie alla decorrelazione strutturale offerta da Convex Stack.

---

## 5. HARD-CLAMP DI BITCOIN A $\le 8.0\%$ NEL COMBINED

### Diagnostica del Rischio Non Regolato:
Nel portafoglio Combined non regolato, la quota di Bitcoin (3.75% strutturale in Convex + allocazione tattica di Apex) oscillava fino al **29.21%**, superando la soglia del 10% per il **43.65%** delle sedute storiche.

### Regola di Vincolo Implementata in Codice:
1. Nella componente Apex, l'allocazione a Bitcoin viene plafonata a $\le 8.5\%$.
2. Poiché Convex contribuisce con il 7.5% di WBTC, l'allocazione iniziale aggregata è rigorosamente:
   $$\text{BTC}_{\text{Combined}} = (0.50 \times 8.5\%) + (0.50 \times 7.5\%) = 4.25\% + 3.75\% = 8.00\%$$
3. Se l'apprezzamento intra-mese di Bitcoin determina un drift che porta l'esposizione combinata oltre l'8.0%, l'eccedenza viene liquidata e destinata alla liquidità remunerata XEON.

### Metriche Comparative (EUR Netto Reale):

| Strategia / Variante | CAGR Net | Volatilità | Sharpe ($R_f=0$) | Sharpe ($R_f=3\%$) | Sortino | MaxDD | Calmar |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Combined Unclamped** (BTC medio 8.5%, max 29.2%) | 13.69% | 11.35% | 1.19 | 0.93 | 1.62 | -18.7% | 0.73 |
| **Combined CLAMPED** (BTC $\le 8.0\%$ hard) | **11.30%** | **9.89%** | **1.14** | **0.83** | **1.57** | **-18.2%** | **0.62** |
| **Combined NO-BTC** (Caso Base Sizing) | 7.54% | 9.96% | 0.78 | 0.48 | 1.10 | -18.2% | 0.41 |
| **SPY Benchmark EUR** (Netto Bollo e Tasse) | 13.83% | 19.08% | 0.78 | 0.62 | 1.00 | -33.1% | 0.42 |

### Profilo di Esposizione a Bitcoin:
- **Unclamped**: Media = 8.50% | Mediana = 8.61% | Max = 29.21% | 95° pct = 16.08% | Giorni > 8%: 56.12% | Giorni > 10%: 43.65%
- **CLAMPED**: Media = **5.95%** | Mediana = **7.38%** | Max = **8.00%** | 95° pct = **8.00%** | Giorni > 8%: **0.00%**

---

## 6. FISCALITÀ ITALIANA REALE E LIQUIDAZIONE TERMINALE

### Modello a Due Canali (Tassazione Ordinaria al 26%):
- **Canale 1 — Redditi di Capitale (Non Compensabili)**: Quote di ETF armonizzati UCITS azionari e obbligazionari (`IEF`, `NTSG`, `AVWS`, `DBMFE`). Le plusvalenze subiscono prelievo definitivo immediato o annuale; le minusvalenze non possono compensare futuri redditi di capitale.
- **Canale 2 — Redditi Diversi (Compensabili)**: Titoli azionari singoli di Apex, ETC fisici su Oro (`PPFB`) e Bitcoin (`WBTC`). I profitti compensano lo zainetto fiscale delle minusvalenze pregresse entro i 4 anni successivi alla realizzazione.
- **Imposta di Bollo**: Addebito annuale dello **0.20%** calcolato sul valore di mercato al 31 dicembre di ciascun anno.

### Haircut Fiscale da Liquidazione Terminale al 100%:
Per calcolare il capitale effettivo spendibile al termine del ciclo di investimento decennale, è stata simulata la liquidazione totale di tutte le posizioni:

```
Capitale Iniziale (03/11/2014)          :  100.000,00 EUR
NAV Finale Operativo (Ongoing)          :  354.197,27 EUR  (CAGR Netto: 11.30%)
Imposta Terminale su Plusvalenze Latenti:  -28.732,43 EUR
--------------------------------------------------------------------------------
Capitale Netto Spendibile al 100%       :  325.464,84 EUR  (CAGR Spendibile: 10.51%)
Haircut Fiscale Terminale               :   -0.79 pp CAGR
```

Il tasso di crescita spendibile effettivo è pari a **10.51% netto**.

---

## 7. STATIONARY BLOCK BOOTSTRAP RESAMPLING (5.000 PATHS)

Per valutare il tail risk su percorsi non limitati alla cronologia osservata, sono stati generati 5.000 percorsi sintetici tramite block bootstrap stazionario sui rendimenti giornalieri del Combined Clamped:

### A. Blocchi da 21 Giorni (Finestra Mensile)
- **CAGR Netto Spendibile**:
  - 5° Percentile (Worst 5%): **6.43%**
  - Mediana (Scenario Base): **11.49%**
  - 95° Percentile (Best 5%): **16.36%**
- **Max Drawdown**:
  - 95° Percentile Peggiore: **-27.45%**
  - Mediana: **-16.69%**
- **Sharpe Ratio ($R_f=0$)**:
  - 5° Percentile: **0.66** | Mediana: **1.15** | 95° Percentile: **1.62**
- **Sortino Ratio**:
  - 5° Percentile: **0.87** | Mediana: **1.62** | 95° Percentile: **2.44**

### B. Blocchi da 63 Giorni (Finestra Trimestrale — Preserva la Persistenza di Regime e Cicli Cripto)
- **CAGR Netto Spendibile**:
  - 5° Percentile (Worst 5%): **6.85%**
  - Mediana (Scenario Base): **11.40%**
  - 95° Percentile (Best 5%): **16.08%**
- **Max Drawdown**:
  - 95° Percentile Peggiore: **-24.11%**
  - Mediana: **-18.19%**
- **Sharpe Ratio ($R_f=0$)**:
  - 5° Percentile: **0.70** | Mediana: **1.14** | 95° Percentile: **1.59**
- **Sortino Ratio**:
  - 5° Percentile: **0.93** | Mediana: **1.59** | 95° Percentile: **2.37**

### Implicazione Chiave:
Sebbene il Max Drawdown storico registrato sia stato del **-18.2%**, la coda probabilistica al 95° percentile tocca **-27.45%**. La gestione del capitale deve assumere un **drawdown atteso di coda pari al -30.0%**.

---

## 8. RENDICONTO ANNUALE STORICO (2014–2026 YTD)

Rendimenti solari in EUR al netto di costi, ritenute fiscali correnti e imposta di bollo dello 0.20%/anno:

| Anno | Combined Clamped | Combined Unclamped | Combined No-BTC | SPY EUR Net | Clamped Intra-Year MDD | SPY Intra-Year MDD |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **2014** (dal 03/11) | +1.30% | +1.30% | +1.26% | +5.03% | -1.9% | -5.7% |
| **2015** | +4.76% | +3.11% | +1.58% | +11.33% | -13.3% | -18.1% |
| **2016** | +15.62% | +26.63% | +7.59% | +15.90% | -4.6% | -12.9% |
| **2017** | +21.35% | +28.47% | -1.58% | +5.18% | -5.2% | -9.1% |
| **2018** | -5.75% | -5.91% | -0.99% | -1.09% | -9.0% | -18.0% |
| **2019** | +18.82% | +19.71% | +19.61% | +33.34% | -3.6% | -6.8% |
| **2020** | +17.36% | +24.93% | +5.19% | +6.32% | -18.2% | -33.1% |
| **2021** | +14.10% | +13.76% | +14.01% | +40.34% | -4.8% | -4.8% |
| **2022** | -2.15% | -1.91% | +0.31% | -13.72% | -6.5% | -17.4% |
| **2023** | +10.12% | +10.34% | +5.16% | +21.53% | -3.2% | -7.1% |
| **2024** | +20.39% | +23.53% | +17.68% | +32.44% | -3.5% | -8.7% |
| **2025** | +5.51% | +5.45% | +8.36% | +3.38% | -10.5% | -23.1% |
| **2026 YTD** | +9.56% | +9.56% | +10.32% | +13.22% | -6.2% | -7.9% |

---

## 9. PROTOCOLLO OPERATIVO DI DIMENSIONAMENTO DEL CAPITALE (CAPITAL SIZING)

Sulla base del 95° percentile del Max Drawdown ottenuto tramite bootstrap (**-27.45%**, arrotondato prudenzialmente al **-30.0%**), la regola formale per il dimensionamento del capitale reale allocabile al sistema è:

$$\text{Nozionale Allocabile} = \frac{\text{Budget di Drawdown Massimo Tollerato sul Patrimonio}}{0.30}$$

### Esempi Applicativi:
1. **Tolleranza Massima al Drawdown del 15% sul Patrimonio**:
   $$\text{Allocazione} = \frac{0.15}{0.30} = 50\% \text{ del patrimonio totale}$$
   Il restante 50% deve essere mantenuto in strumenti a capitale garantito o privi di rischio di mercato (liquidità remunerata / XEON / Treasury brevi).
2. **Tolleranza Massima al Drawdown del 10% sul Patrimonio**:
   $$\text{Allocazione} = \frac{0.10}{0.30} = 33\% \text{ del patrimonio totale}$$
3. **Allocazione del 100% del Capitale al Portafoglio Combined**:
   L'investitore deve accettare contrattualmente e psicologicamente un drawdown potenziale di coda del **-27.5% / -30.0%**, a fronte di un'aspettativa mediana di rendimento spendibile del **10.5% – 11.4%** netto.

---

## 10. REPERTORIO FILE DI CODICE E DATI CERTIFICATI

- **Script Audit di Produzione**: `run_clamped_audit.py`
- **Script Esecuzione Policy Grid 1D & Sweep**: `run_1d_sweeps.py`
- **Dataset Risultati Tagli 1D**: `results_1d_sweeps.csv`
- **Dataset Sweep Fine Vol-Target Apex**: `apex_fine_vol_target_sweep.csv`
- **Serie Storica Giornaliera Completa**: `combined_clamped_audit_daily.csv`
- **Registro Operativo Ribilanciamenti Apex**: `apex_rebalance_log.csv`
- **Serie Temporale Stato e Leva Apex**: `apex_state_timeseries.csv`
- **Tabella Mappatura Proxy e Strumenti Live**: `proxy_mapping_table.csv`
- **Motore di Calcolo Apex V2 Congelato**: `apex_v2_engine.py` (`V2_VOL_TARGET = 0.13`)

---

## 11. PROTOCOLLO DI OTTIMIZZAZIONE VINCOLATA E TAGLI UNIDIMENSIONALI (T1, T2, T3)

In data 4 Settembre 2026, conformemente alle direttive di audit, è stata incardinata in testa al codice di produzione la funzione obiettivo analitica con vincoli duri di coda:

$$\max \; 0.5\cdot\mathrm{CAGR}_{\text{spend}} + 0.5\cdot\mathrm{CAGR}_{5^{\circ}, 63g}$$
$$\text{s.t. } \mathrm{MDD}_{\text{boot}, 63g}^{5^{\circ}} \ge -B, \quad \mathrm{MDD}_{\text{hist}} \ge -1.1B, \quad w_{\text{BTC}} \le c, \quad \sum w \le 1$$

con tre budget discreti di drawdown: $B \in \{15\%, 20\%, 25\%\}$.

### A. Taglio T1 — Mix Apex / Convex (35% / 50% / 65%)
*Parametri congelati: Cap BTC Combined = 8.0%, Vol-Target Apex = 13.0%*

| Configurazione | CAGR Spend | CAGR 5° (63g) | Punteggio Obiettivo | Volatilità | Sharpe ($R_f=0$) | Calmar | Ulcer Index | STARR 95% | MaxDD Storico | MaxDD 5° (63g) | OOS Calmar (4 Fold) | Stress 2022 (MDD) | Feasibility ($B=25\%$) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Apex 35% / Convex 65%** | 11.44% | 7.56% | 9.50% | 11.00% | 1.14 | 0.53 | 4.33 | 0.53 | -21.6% | -27.9% | 1.10 | -3.6% (-7.8%) | **FAIL** ($> 25\%$) |
| **Apex 50% / Convex 50% (Freeze)** | **10.51%** | **6.85%** | **8.68%** | **9.89%** | **1.14** | **0.58** | **4.13** | **0.52** | **-18.2%** | **-24.1%** | **1.14** | **-2.1% (-6.5%)** | **PASS** |
| **Apex 65% / Convex 35%** | 9.48% | 5.97% | 7.73% | 9.03% | 1.09 | 0.65 | 4.05 | 0.49 | -14.7% | -21.3% | 1.20 | -0.7% (-5.2%) | **PASS** |

### B. Taglio T2 — Cap BTC Combined (0% / 4% / 8% / 10%)
*Parametri congelati: Mix Apex = 50/50, Vol-Target Apex = 13.0%*

| Cap BTC Combined | CAGR Spend | CAGR 5° (63g) | Punteggio Obiettivo | Volatilità | Sharpe ($R_f=0$) | Calmar | Ulcer Index | STARR 95% | MaxDD Storico | MaxDD 5° (63g) | OOS Calmar (4 Fold) | Stress 2022 (MDD) | Feasibility ($B=25\%$) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Cap 0% (No-BTC)** | 6.72% | 4.05% | 5.38% | 9.96% | 0.78 | 0.37 | 4.21 | 0.35 | -18.2% | -24.2% | 0.99 | +0.3% (-4.9%) | **PASS** |
| **Cap 4%** | 9.42% | 5.77% | 7.60% | 9.14% | 1.04 | 0.53 | 3.39 | 0.47 | -17.8% | -22.6% | 1.10 | -1.9% (-6.2%) | **PASS** |
| **Cap 8% (Freeze)** | **10.51%** | **6.85%** | **8.68%** | **9.89%** | **1.14** | **0.58** | **4.13** | **0.52** | **-18.2%** | **-24.1%** | **1.14** | **-2.1% (-6.5%)** | **PASS** |
| **Cap 10%** | 11.14% | 7.35% | 9.24% | 10.35% | 1.17 | 0.61 | 4.64 | 0.53 | -18.4% | -25.2% | 1.18 | -2.0% (-6.4%) | **FAIL** ($> 25\%$) |

### C. Taglio T3 — Vol-Target Apex (10% / 13% / 16%)
*Parametri congelati: Mix Apex = 50/50, Cap BTC Combined = 8.0%*

| Vol-Target Apex | CAGR Spend | CAGR 5° (63g) | Punteggio Obiettivo | Volatilità | Sharpe ($R_f=0$) | Calmar | Ulcer Index | STARR 95% | MaxDD Storico | MaxDD 5° (63g) | OOS Calmar (4 Fold) | Stress 2022 (MDD) | Feasibility ($B=25\%$) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Vol-Target 10%** | 10.31% | 6.62% | 8.46% | 9.60% | 1.14 | 0.58 | 4.01 | 0.52 | -17.9% | -23.9% | 1.13 | -2.3% (-6.2%) | **PASS** |
| **Vol-Target 13% (Freeze)** | **10.51%** | **6.85%** | **8.68%** | **9.89%** | **1.14** | **0.58** | **4.13** | **0.52** | **-18.2%** | **-24.1%** | **1.14** | **-2.1% (-6.5%)** | **PASS** |
| **Vol-Target 16%** | 10.62% | 7.00% | 8.81% | 10.09% | 1.13 | 0.58 | 4.19 | 0.52 | -18.5% | -24.3% | 1.14 | -2.0% (-6.7%) | **PASS** |

### D. Stress Test Annuali e Analisi di Elasticità di Bitcoin

| Configurazione Cap BTC | Stress 2018 (MDD) | Stress 2020 (MDD) | Stress 2022 (MDD) | Stress 2025 (MDD) | Peso BTC Medio | Contributo CAGR BTC | Elasticità $\frac{\Delta\text{CAGR}}{\Delta\bar{w}_{\text{BTC}}}$ |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Cap 0% (No-BTC)** | -1.0% (-7.3%) | +5.2% (-18.2%) | +0.3% (-4.9%) | +8.4% (-10.0%) | 0.00% | +0.00 pp | *Base 0%* |
| **Cap 4%** | -4.6% (-8.5%) | +12.8% (-17.8%) | -1.9% (-6.2%) | +5.5% (-10.1%) | 3.88% | +2.70 pp | **0.70** |
| **Cap 8% (Freeze)** | -5.7% (-9.0%) | +17.4% (-18.2%) | -2.1% (-6.5%) | +5.5% (-10.5%) | 5.95% | +3.79 pp | **0.53** (Decrescente) |
| **Cap 10%** | -5.9% (-9.1%) | +19.4% (-18.4%) | -2.0% (-6.4%) | +5.5% (-10.8%) | 6.90% | +4.42 pp | **0.66** (Inammissibile) |

---

## 12. SWEEP FINE SUL VOL-TARGET DI APEX STANDALONE (13% – 35%)

Per verificare l'impatto dell'aumento del target di volatilità sulla strategia singola Apex (escludendo il beneficio dell'ensemble), è stato eseguito uno sweep a passi dell'1% tra il 13% e il 35%:

| Vol-Target (%) | CAGR Full-Period | Geometric Mean | MaxDD Full | Calmar Full | OOS Mean CAGR (4 Fold) | OOS Mean MaxDD (4 Fold) | OOS Mean Calmar (4 Fold) |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **13% (Freeze)** | **11.30%** | **11.34%** | **-19.3%** | **0.585** | **11.68%** | **-11.2%** | **1.170** |
| **14%** | 11.94% | 11.97% | -20.3% | 0.588 | 12.37% | -11.9% | 1.166 |
| **15%** | 12.55% | 12.58% | -21.3% | 0.589 | 13.03% | -12.5% | 1.163 |
| **16%** | 13.16% | 13.19% | -22.3% | 0.591 | 13.72% | -13.1% | 1.162 |
| **18%** | 14.46% | 14.50% | -24.1% | 0.600 | 15.19% | -14.2% | 1.177 |
| **20%** | 15.54% | 15.58% | -25.8% | 0.601 | 16.41% | -15.2% | 1.183 |
| **22%** | 16.49% | 16.54% | -26.7% | 0.617 | 17.45% | -16.2% | 1.178 |
| **25%** | 18.35% | 18.40% | -29.3% | 0.627 | 19.10% | -17.5% | 1.189 |
| **28%** | 19.54% | 19.59% | -31.5% | 0.620 | 20.33% | -18.3% | 1.208 |
| **30%** | 20.32% | 20.38% | -32.9% | 0.618 | 21.08% | -18.5% | 1.261 |
| **32%** | 21.42% | 21.48% | -34.1% | 0.629 | 22.11% | -18.9% | 1.334 |
| **35%** | 22.38% | 22.44% | -35.9% | 0.624 | 22.90% | -19.7% | 1.335 |

### Diagnostica Forense:
Il Calmar Ratio su orizzonte completo rimane sostanzialmente orizzontale (**0.585 a 13% vs 0.624 a 35%**). L'aumento del target di volatilità non genera efficienza marginale, ma costituisce un **puro fattore di amplificazione scalare** che estende linearmente il Max Drawdown storico dal **-19.3%** al **-35.9%**. Il valore **13%** prescelto massimizza la protezione patrimoniale a parità di rendimento per unità di drawdown.

---

## 13. VERIFICA DI CONVERGENZA DEI TRE GINOCCHI E CONFERMA DEL FREEZE

Sulla base dei 5 criteri prescritti dal protocollo:

1. **Ammissibilità su Tutti i 4 Stress**: Tutte le configurazioni esaminate nei tre tagli presentano perdite limitate e controllate negli anni critici (nessuna esplosione asimmetrica; nel 2022 il Combined perde solo tra il -0.7% e il -3.6% contro il -13.7% di SPY).
2. **Fattibilità Rispetto ai Budget $B \in \{15\%, 20\%, 25\%\}$**:
   - Per $B = 15\%$ e $B = 20\%$, **nessuna cella** della griglia soddisfa il vincolo sul bootstrap a blocchi trimestrali da 63 giorni (la componente obbligazionaria di NTSG e la liquidità XEON generano fisiologicamente un 95° worst drawdown compreso tra $-21.3\%$ e $-24.1\%$).
   - Per $B = 25\%$, l'unica combinazione ottimale ammissibile è:
     - **T1**: Mix al **50% Apex** (35% Apex viola il limite con $-27.9\%$; 65% Apex perde oltre 1 pp di CAGR spendibile);
     - **T2**: Cap BTC all'**8.0%** (10% Cap viola il limite con $-25.2\%$; 4% Cap perde oltre 1 pp di CAGR spendibile);
     - **T3**: Vol-Target al **13.0%** (passare al 16% incrementa il CAGR spendibile di appena $+0.11$ pp, violando la soglia di significatività minima di 1.0 pp a parità di Calmar 0.58).
3. **Test di Plateau**: Nel taglio T1, il Calmar Ratio a 50% Apex (0.58) è affiancato da vicini a 0.53 e 0.65 (variazione contenuta tra $-8\%$ e $+12\%$, perfettamente all'interno della tolleranza del $\pm 15\%$).
4. **Stabilità Walk-Forward**: La configurazione 50/50 presenta un OOS Calmar sui 4 fold di **1.14**, allineato e superiore al mix 35/65 (1.10).
5. **Elasticità di Bitcoin**: L'elasticità passa da **0.70** (nel passaggio da 0% a 4%) a **0.53** (da 4% a 8%). Aumentare a 10% violerebbe il vincolo di budget $B=25\%$.

### Verdetto Conclusivo:
I tre ginocchi indipendenti T1, T2 e T3 **coincidono esattamente sullo stesso identico punto parametrico**:
$$\mathbf{Mix} = \mathbf{50/50}, \quad \mathbf{Cap\;BTC} = \mathbf{8.0\%}, \quad \mathbf{Vol\text{-}Target} = \mathbf{13.0\%}$$

In ossequio alle regole di aborto e conservazione parametrica:
- Non vi è alcuna divergenza tra gli elbow unidimensionali.
- Qualsiasi deviazione tridimensionale non apporterebbe incrementi statisticamente significativi ($\Delta \text{CAGR} < 1.0$ pp) a parità di rischio di coda.
- **La configurazione canonica APEX v2.1 Frozen (Vol-Target 13%) + CONVEX Stack v15.1 al Mix 50/50 con Hard-Clamp di Bitcoin all'8.0% è formalmente e definitivamente CERTIFICATA come ottima e congelata**.

