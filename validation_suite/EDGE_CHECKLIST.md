# Checklist Edge/Apex/Convex — materiale di riferimento fornito dall'utente

**Stato: NON verificato contro il codice reale. Da usare come lista di controllo per
approfondimenti futuri, non come descrizione di cosa Apex/Convex fanno oggi.**

Questo documento è stato fornito dall'utente come framework generico
accademico/practitioner per costruire sistemi "momentum/breakout" e
"mean-reversion/value" — riprodotto qui integralmente per non perderlo, con
alcune annotazioni esplicite dove entra in tensione con ciò che questa
sessione ha già validato empiricamente sul codice reale di questo repository.

## Avvertenza importante, prima di usarlo per qualunque decisione

Il framework qui sotto descrive un **archetipo generico** di sistema momentum
(sezione 3) e mean-reversion (sezione 4) — **non descrive Apex V2 o Convex
Stack come sono realmente implementati in questo repository**. Differenze
materiali note, già validate in questa sessione (vedi `README.md`,
"Storia delle scoperte rilevanti", e `APEX_V2_SPEC.md`):

- **Apex V2 non ha stop-loss individuali.** La sezione 3 qui sotto prescrive
  stop su ATR e trailing stop — Apex ha esplicitamente testato e SCARTATO
  ogni meccanismo di stop-loss sul basket azionario (`philosophy` in
  `portfolio_manager.get_apex_metrics()`: "Nessuno stop-loss (validato: ogni
  meccanismo di stop testato peggiora Sharpe/MaxDD sotto esecuzione
  settimanale reale)"). L'uscita reale di Apex è il segnale di trend macro
  (isteresi su MA 40/20 settimane), non uno stop per-titolo.
- **Convex Stack non è un sistema mean-reversion attivo con segnali
  RSI/Z-score e stop-loss.** È un veicolo di accumulo PASSIVO a pesi target
  fissi (45/15/25/7.5/7.5), rifinanziato solo tramite nuovi versamenti PAC
  (water-filling verso il sottopeso) — **nessun segnale di entrata/uscita
  attivo**, nessuno stop-loss, nessun ribilanciamento mensile generalizzato.
  L'unico intervento attivo è un trim su Oro/WBTC quando superano +50% del
  target (soglia fiscale, non un segnale di mean-reversion in senso tecnico).
  Vedi `convex_engine.py` e la discussione in
  `validation_suite/README.md` sulla proposta "Kelly + trim selettivo".
- **Low Vol/BAB (edge #5, sezione 1) non regge a livello di paese.** Questa
  sessione ha validato BAB a livello di singolo titolo USA (Teoria #5,
  adottata in produzione) MA lo ha testato e **falsificato/invertito** a
  livello di paese (`apex_international_bab_country_etf_test.py`) — il
  meccanismo non è un principio universale "beta basso vince sempre",
  è specifico al rischio idiosincratico di singoli titoli.

Trattare questo documento come una lista di **domande da porsi** ("stiamo
catturando questo edge? con quale meccanismo? è stato validato sui NOSTRI
dati?"), non come una specifica da implementare alla lettera.

---

## Sezione 1 — Mappa degli Edge (fonte → meccanismo → veicolo → trade-off)

| # | Edge | Fonte | Meccanismo | Veicolo concreto | Trade-off / rischio |
|---|---|---|---|---|---|
| 1 | **Momentum cross-section** | Comportamentale | Underreaction → herding ritardato | Long top 10-20% RS126, short bottom 10-20% | Drawdown 5-10 anni; crowding |
| 2 | **Time-Series Momentum (Trend)** | Comportamentale + strutturale | Stop-loss cascades, margin call, ribilanciamenti forzati | Long se P_t > P_t-k, short se opposto | Whipsaw in mercati laterali |
| 3 | **Value** | Risk + behavioral | Distress risk, duration, mispricing | Long low B/M, EV/EBIT, P/S | In erosione strutturale post-1992 |
| 4 | **Quality / Profitability** | Risk + mispricing | ROIC/ROE alti, margini stabili, bilancio sano | Long high gross profitability, low accruals | Overlap con momentum |
| 5 | **Low Volatility / BAB** | Strutturale (vincoli di leva) | Investor leverage-constrained → overprice high-beta | Long low-beta, short high-beta | Underperformance in bull market forti |
| 6 | **Carry** | Risk premium | Differenziale tassi/rendimenti | Long high carry (FX, bond, comm), short low carry | Crash risk (coda negativa grassa) |
| 7 | **52-week high / RS** | Comportamentale | Ancoraggio → prezzo vicino a max = leadership | Long price / 52W high > 0.9 | Fragile in reversal bruschi |
| 8 | **PEAD** | Comportamentale | Underreaction a earnings surprise | Long post-positive surprise, short post-negative | Decaduto post-2002, affollato |
| 9 | **Roll yield** | Matematico | Backwardation → guadagno da roll futures | Long futures in backwardation | Dipende da struttura a termine |
| 10 | **Volatility Drag + Ribilanciamento** | Matematico (ergodicità) | CAGR ≈ μ - σ²/2; diversificazione abbassa σ | Portafoglio multi-asset ribilanciato | Richiede correlazioni basse |
| 11 | **Kelly / Optimal Sizing** | Matematico | f* = edge/odds; massimizza crescita geometrica | Position sizing dinamico | Overbetting → rovina certa |
| 12 | **Liquidity premium** | Risk premium | Compenso per illiquidità, market impact | Long small-cap illiquide | Costi di transazione elevati |
| 13 | **VRP (Variance Risk Premium)** | Risk premium | IV > RV; premio assicurativo | Short OTM puts, short vol ETP | Perdite catastrofiche in crash |
| 14 | **Merger Arb** | Event risk premium | Spread deal completion | Long target, short acquirer | Risk deal failure |
| 15 | **Seasonality** | Flow istituzionali | Turn-of-month, January effect | Long in window calendariali | Fragile, cambia nel tempo |
| 16 | **Accrual anomaly** | Mispricing contabile | High accruals → earnings meno persistenti | Short high accruals | Affollato, decaduto |
| 17 | **Long-term reversal** | Overreaction | Mean-reversion 3-5 anni | Long 3-5y losers, short winners | Lento, turnover basso |
| 18 | **Short-term reversal** | Microstruttura | Bid-ask bounce, order imbalance | Long 1-4w losers | Costi > edge per retail |
| 19 | **Market making** | Strutturale | Bid-ask spread - adverse selection | Quoting bid/ask | Competitivo, capital-intensive |

---

## Sezione 2 — Principi opposti: archetipo "Apex" (breakout/rialzi) vs "Convex" (ribassi/mean-reversion)

*(Nome delle colonne ripreso dal materiale originale — vedi avvertenza sopra: non coincide con l'implementazione reale)*

| Dimensione | **Apex** (acquisto su rialzi) | **Convex** (acquisto su ribassi) |
|---|---|---|
| **Filosofia** | Momentum + Trend + Leadership | Value + Mean-reversion + Carry |
| **Edge primari** | Momentum, TSMOM, 52W high, Quality | Value, Low-vol, Carry, Roll yield, Ribilanciamento |
| **Segnale di ingresso** | Rottura resistenze, RS126 alto, P/52W high > 0.9 | Prezzo < media mobile lunga, B/M alto, carry alto |
| **Segnale di uscita** | Trend break (P < MA50/200), RS crolla | Prezzo > fair value, carry si annulla, roll yield negativo |
| **Orizzonte** | Settimanale (hold 1-6 mesi) | Settimanale/mensile (hold 3-12 mesi) |
| **Risk management** | Volatility targeting, stop su trend break | Position sizing fisso, stop su fundamental deterioration |
| **Correlazione attesa** | Alta con equity bull market | Bassa/negativa con equity (difensivo) |
| **Drawdown tipico** | 20-30% in reversal bruschi | 10-15% in value trap / carry crash |
| **Skewness** | Positiva (performa in crisi di trend) | Negativa (carry/VRP) o neutra (value) |

---

## Sezione 3 — Checklist di costruzione: archetipo "Apex" (breakout/rialzi)

**Step 1 — Universo**
- [ ] Azioni liquide (volume medio > 500k gg)
- [ ] Mercato sviluppato (USA, EU, JP) o ETF settoriali
- [ ] Escludere penny stock, biotech pre-revenue

**Step 2 — Filtri di qualità (pre-screen)**
- [ ] ROIC > 10% o gross profitability > 30%
- [ ] Accruals < 10% degli utili
- [ ] Debt/Equity < 1.5

**Step 3 — Segnale Momentum/RS**
- [ ] Calcola RS126 (rendimento 6 mesi, skip 1 mese)
- [ ] Calcola Price / 52W High
- [ ] Rank: top 20% per RS + P/52W > 0.85

**Step 4 — Conferma Trend**
- [ ] Prezzo > MA50 e MA200
- [ ] MA50 > MA200 (trend confermato)
- [ ] Volume breakout > 1.5x volume medio 20gg

**Step 5 — Entry**
- [ ] Acquisto su chiusura sopra resistenza o breakout di canale
- [ ] Position sizing: 1-2% rischio per trade (stop = 2x ATR)

**Step 6 — Risk Management**
- [ ] Volatility targeting: peso posizione ∝ 1/σ_60gg
- [ ] Stop-loss: -10% o rottura MA50
- [ ] Take-profit: trailing stop 3x ATR o RS crollo sotto top 40%

**Step 7 — Uscita**
- [ ] Trend break: P < MA50 per 3 gg consecutivi
- [ ] RS126 scende sotto mediana universo
- [ ] Earnings miss o downgrade analisti

**Edge catturati**: Momentum, TSMOM, Quality, 52W high, Volatility targeting.

---

## Sezione 4 — Checklist di costruzione: archetipo "Convex" (ribassi/mean-reversion)

**Step 1 — Universo**
- [ ] Asset class multiple: equity value, bond, FX, commodities
- [ ] ETF o futures liquidi
- [ ] Escludere strumenti con backwardation cronica (per commodities)

**Step 2 — Filtri Value/Carry**
- [ ] Equity: B/M > mediana, EV/EBIT < settore, FCF yield > 5%
- [ ] Bond: yield-to-worst > benchmark + 200bp
- [ ] FX: differenziale tassi > 3% (carry)
- [ ] Commodities: backwardation (roll yield positivo)

**Step 3 — Segnale Mean-Reversion**
- [ ] Prezzo < MA200 da > 3 mesi
- [ ] RSI < 40 o Z-score prezzo < -1.5
- [ ] Volume di vendita in esaurimento (volume spike + reversal candle)

**Step 4 — Entry**
- [ ] Acquisto su primo rimbalzo confermato (chiusura > high giorno precedente)
- [ ] Position sizing: 2-3% per trade (stop = 1.5x ATR)

**Step 5 — Risk Management**
- [ ] Diversificazione cross-asset (max 20% per asset class)
- [ ] Stop-loss: -15% o fundamental deterioration (es. downgrade rating bond)
- [ ] Ribilanciamento mensile: restore pesi target

**Step 6 — Uscita**
- [ ] Prezzo > MA50 e MA200 incrociate al rialzo
- [ ] Carry si annulla (differenziale tassi < 1%)
- [ ] Roll yield diventa negativo (contango)

**Edge catturati**: Value, Low-vol, Carry, Roll yield, Ribilanciamento, Mean-reversion.

---

## Sezione 5 — Checklist di portafoglio (combinazione Apex + Convex)

**Allocazione**
- [ ] 50-70% Apex, 30-50% Convex (in base a regime di mercato)
- [ ] Correlazione target < 0.3 (verifica rolling 60gg)

**Sizing globale**
- [ ] Kelly frazionale: f = 0.25-0.5 × Kelly pieno (per margine di sicurezza)
- [ ] Max drawdown tollerato: 20% → stop trading se breach

**Ribilanciamento**
- [ ] Mensile: restore pesi target
- [ ] Trimestrale: ricalcola ranking Edge (RS, B/M, carry)

**Monitoraggio**
- [ ] Sharpe ratio rolling 12 mesi > 0.8 per entrambe le strategie
- [ ] Max drawdown < 25%
- [ ] Correlazione Apex-Convex < 0.4

**Costi**
- [ ] Commissioni < 5bp per trade
- [ ] Slippage stimato < 10bp
- [ ] Turnover annuo < 300% (per evitare alpha decay da costi)

---

## Sezione 6 — Principi matematici trasversali

- **Kelly**: f* = (p·b - q) / b → usa half-Kelly per safety margin.
- **Volatility targeting**: w_t ∝ 1/σ_60gg → stabilizza rischio.
- **Shannon's Demon**: CAGR ≈ μ - σ²/2 → diversificazione abbassa σ → aumenta CAGR geometrico.
- **Roll yield**: Backwardation → guadagno da roll futures indipendente da spot.

---

## Sezione 7 — Red flag (quando un edge è morto)

- [ ] Sharpe ratio < 0.3 per 3 anni consecutivi
- [ ] Drawdown > 40% senza recovery in 18 mesi
- [ ] Correlazione con benchmark > 0.9 (edge dissolto in beta)
- [ ] Crowding: > 50% fondi quantitativi usano stesso segnale (verifica report AQR/Quantpedia)
- [ ] Costi > 30% del gross edge (backtest vs live)

---

## Sezione 8 — Backtest e validazione

- [ ] Dataset: minimo 30 anni (o dal 1880 per TSMOM)
- [ ] Out-of-sample: split 70/30 o walk-forward
- [ ] Costi inclusi: commissioni, slippage, tasse
- [ ] Stress test: crisi 2000, 2008, 2020
- [ ] Sensitivity analysis: varia parametri ±20%

---

## Bottom line (materiale originale)

Apex cattura momentum/trend/quality (rialzi), Convex cattura
value/carry/mean-reversion (ribassi). La combinazione ortogonale, con
sizing prudente e costi minimizzati, è l'approccio con evidenza accademica
di generare Sharpe > 1 e drawdown < 25% nel lungo periodo.

**Nota di chiusura per questo repository**: il principio di fondo
(due motori a strategie decorrelate, ciascuno robusto anche da solo) è
condiviso e già guida le decisioni di design di questa sessione — ma la
Sezione 2 in poi descrive un'implementazione generica che NON è quella
reale di Apex/Convex qui (vedi avvertenza in testa al documento). Da usare
come stimolo per porsi domande mirate (es. "il nostro TSMOM su Apex cattura
davvero l'edge #2, o solo una sua approssimazione grezza?"), non come
gap-list da colmare automaticamente.
