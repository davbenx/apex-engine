# Checklist Edge/Apex/Convex — materiale di riferimento fornito dall'utente

**Stato: incrociata sistematicamente voce-per-voce contro il codice reale
(`apex_v2_engine.py`, `convex_engine.py`, `backend.py`) — vedi
"Cross-check sistematico" in fondo al documento. Resta un elenco di
DOMANDE/confronti, non una gap-list da colmare: nessuna modifica al codice
di produzione è stata fatta come conseguenza di questo cross-check.**

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

---

## Cross-check sistematico contro il codice reale (richiesto dall'utente)

Letto integralmente `apex_v2_engine.py`, `convex_engine.py`, `backend.py`.
Per ogni voce: **[CATTURATO]** (il meccanismo reale produce l'edge, anche
se diverso nell'implementazione), **[DIVERGE]** (il meccanismo reale è
sostanzialmente diverso da quanto descritto/atteso), **[ASSENTE]** (non
implementato, nessun equivalente). Nessuna azione correttiva presa — sono
osservazioni, non bug: Apex/Convex non hanno mai promesso di implementare
questo archetipo alla lettera.

### Sezione 1 — quali edge sono davvero catturati

| # | Edge | Stato reale |
|---|---|---|
| 1 | Momentum cross-section (stock-picking) | **[ASSENTE]** — il basket azionario è selezionato per BETA basso (`select_low_beta_basket`), non per momentum/RS. Nessun ranking per rendimento relativo tra titoli. |
| 2 | TSMOM (trend macro) | **[CATTURATO]** — isteresi su MA 40/20 settimane per classe (`compute_v2_macro_signal`), il meccanismo centrale di Apex. |
| 3 | Value | **[ASSENTE]** — nessuno screening B/M, EV/EBIT, FCF yield in nessuno dei due motori. |
| 4 | Quality/Profitability | **[ASSENTE]** — nessun filtro ROIC/accruals/leva nella selezione titoli. |
| 5 | Low-Vol/BAB | **[CATTURATO a livello di singolo titolo USA]** — già annotato sopra: NON regge a livello di paese (falsificato). |
| 6 | Carry | **[ASSENTE]** — DBMFE (Convex) è managed futures/trend-following, non un carry trade esplicito; nessun carry FX/bond/commodity modellato. |
| 7 | 52-week high/RS | **[ASSENTE]**. |
| 8 | PEAD | **[ASSENTE]** — nessun dato di earnings surprise usato. |
| 9 | Roll yield | **[ASSENTE]** a livello di Apex/Convex (interno ai fondi sottostanti tipo DBMFE, non gestito da questo codice). |
| 10 | Volatility Drag + Ribilanciamento | **[DIVERGE, il più netto]** — vedi sotto, sezione 2. |
| 11 | Kelly/Optimal Sizing | **[CATTURATO, ma solo dentro Apex]** — Kelly frazionario (0.25) pesa le classi macro ATTIVE di Apex; il mix Apex/Convex stesso è un peso FISSO 70/30 (scelto per Sharpe su una griglia, non da un calcolo Kelly diretto sul mix — vedi Sezione 5). |
| 12-19 | Liquidity premium, VRP, Merger Arb, Seasonality, Accrual, Reversal, Market making | **[ASSENTI]** — nessuno di questi meccanismi è implementato o testato in produzione. |

### Sezione 2 — la divergenza più concreta: "Convex = ribilanciamento/mean-reversion"

L'archetipo (Sezione 2, colonna "Convex") elenca **Ribilanciamento** come
edge primario e **Correlazione bassa/negativa con equity (difensivo)**
come proprietà attesa. Entrambe le affermazioni sono **contraddette da
dati reali già raccolti in questa sessione**, non da una lettura teorica:

- **Ribilanciamento**: la policy REALE di Convex è "mai vendere"
  (`convex_engine.py`, PAC water-filling — versa solo sull'asset più
  sottopesato, nessuna vendita salvo trim fiscale raro sopra +50% su
  WBTC/PPFB). Non solo Convex non ribilancia mensilmente come prescrive
  l'archetipo — quando questa sessione ha TESTATO se un ribilanciamento a
  soglia catturerebbe il "rebalancing premium" atteso
  (`convex_threshold_vs_calendar_rebalance_test.py`), il risultato è
  stato che una soglia stretta batte il "mai" su Sharpe/MaxDD ma non è
  stata adottata (campione troppo corto per provarlo con confidenza) — il
  vantaggio teorico dell'edge #10 esiste probabilmente, ma Convex, per
  design, non lo cattura.
- **Correlazione difensiva**: l'analisi per regime storico
  (`apex_convex_regime_and_correlation_stress.py`, già nel report di
  robustezza) ha misurato Convex **NEGATIVO in entrambe le crisi maggiori
  del suo backtest** (dot-com -3,05% CAGR, GFC -9,16% CAGR) — l'opposto
  di "difensivo/bassa-negativa correlazione con equity". Convex è un
  veicolo di accumulo passivo A LEVA: in una crisi azionaria/obbligazionaria
  perde, non protegge. La diversificazione reale nel sistema viene dal
  MIX con Apex (che invece va in cash nei bear market), non da Convex
  preso da solo — questo è già scritto nel verdetto del report di
  robustezza, ma non era mai stato messo in relazione esplicita con
  questa specifica affermazione della checklist.

### Sezione 3 — checklist "Apex": cosa manca davvero

- **Nessun filtro di qualità/fondamentali** (Step 2: ROIC, accruals,
  debt/equity) — `select_low_beta_basket` usa solo beta storico + settore,
  zero dati di bilancio.
- **Nessuna conferma di trend PER TITOLO** (Step 4: prezzo>MA50/200 del
  singolo titolo) — il trend/timing di Apex è applicato SOLO al livello
  macro (classe "Equities" tramite SPY), mai al singolo titolo nel
  basket: un titolo individualmente in downtrend resta nel basket se il
  suo beta è ancora tra i più bassi.
- **Nessun entry/exit tecnico per posizione** (Step 5/7: breakout,
  stop=2xATR, trailing stop) — coerente con quanto già annotato (nessuno
  stop-loss), ma vale la pena essere espliciti: non c'è NESSUN segnale di
  ingresso/uscita per singolo titolo, solo ribasket trimestrale
  meccanico verso il nuovo ranking.
- **Volatility targeting è a livello di PORTAFOGLIO/classe, non di
  singola posizione** (Step 6: "peso posizione ∝ 1/σ" per titolo) — Apex
  scala l'esposizione aggregata della classe "Equities" per la vol
  target del portafoglio (`vol_target=0.22`); dentro il basket i 15
  titoli restano equal-weight, nessun sizing per volatilità individuale.

### Sezione 4 — checklist "Convex": la più distante dall'archetipo

Quasi ogni step della Sezione 4 non ha equivalente reale: nessuno
screening value/carry (Step 2), nessun segnale tecnico di mean-reversion
RSI/Z-score (Step 3), nessun trigger di entry su rimbalzo confermato
(Step 4), nessuno stop-loss (Step 5), nessun ribilanciamento mensile
verso i pesi target (Step 5 — vedi sopra, è "mai vendere" per design),
nessun segnale di uscita tecnico (Step 6). Convex è, per intero, un
allocatore PASSIVO a pesi strutturali fissi con un solo meccanismo attivo
(trim fiscale sopra soglia su 2 dei 5 strumenti) — l'intera Sezione 4
descrive un sistema diverso, non una versione semplificata di Convex.

### Sezione 5 — checklist di portafoglio

- **Allocazione "50-70% Apex, 30-50% Convex in base a regime di mercato"**:
  la produzione usa un peso **FISSO 70/30**, mai regime-dependent —
  nessun meccanismo sposta dinamicamente il mix in base al regime.
- **Correlazione target <0.3**: coerente — correlazione reale misurata
  ~0.30-0.31 (`get_combined_dual_engine_metrics()`), monitorata e
  mostrata in dashboard, anche se non con un controllo automatico che
  agisce se la soglia viene sforata.
- **"Max drawdown tollerato 20% → stop trading se breach"**: **[ASSENTE]**
  — verificato con grep su `backend.py`/`app.py`, nessun meccanismo di
  kill-switch/circuit-breaker legato al drawdown esiste nel codice. Se il
  sistema subisse un drawdown del 30%, continuerebbe a operare
  esattamente come prima — nessun freno automatico.
- **Monitoraggio (Sharpe rolling/MaxDD/correlazione con soglie)**:
  **[ASSENTE come automazione]** — le metriche sono calcolate e mostrate
  in dashboard, ma nessun alert o azione automatica scatta se Sharpe
  scende sotto 0.8 o la correlazione sale sopra 0.4. Puramente
  informativo, non un controllo di rischio attivo.

### Sezione 7 — red flag ("quando un edge è morto")

**[ASSENTE come automazione]** per tutti e 5 i punti — nessuno di questi
criteri (Sharpe<0.3 per 3 anni, drawdown>40% senza recovery, correlazione
con benchmark >0.9, crowding, costi>30% del gross edge) è monitorato o
verificato automaticamente dal codice. Sono, ad oggi, criteri per una
revisione manuale periodica (prossima sessione o checklist annuale
dell'utente), non un processo del sistema.

### Sezione 8 — backtest e validazione: qui l'archetipo è SODDISFATTO

A differenza delle sezioni precedenti, la Sezione 8 descrive esattamente
cosa questa sessione (e le precedenti) hanno già fatto: **[CATTURATO]**
su tutti e 5 i punti — dataset 39 anni di storico (471 mesi, proxy+reale,
supera il minimo di 30), walk-forward OOS reale (72 mesi TEST mai
usati per calibrare), stress test sui regimi storici nominati (dot-com,
GFC, COVID — `apex_convex_regime_and_correlation_stress.py`), costi/tasse
inclusi (`tax_engine.py`, stress test dedicati), sensitivity analysis
(`apex_v2_sensitivity_grid.py`, ±3-6pp su kelly/vol-target/base-weight,
non ±20% esatto ma lo stesso principio). L'UNICA sezione della checklist
dove il rigore richiesto dall'archetipo è già pienamente rispettato.

### Verdetto del cross-check

Il principio di fondo (due motori decorrelati) regge. L'implementazione
concreta diverge dall'archetipo quasi ovunque nei meccanismi (nessun
value/quality/carry/momentum-di-titolo, nessuno stop-loss, nessun
circuit-breaker di drawdown, nessuna automazione dei red-flag) — la
maggior parte per scelta deliberata e validata (stop-loss testato e
scartato, mix fisso preferito a dinamico dopo verifica Sharpe), non per
omissione. **Le due divergenze più rilevanti per una decisione futura**
sono quelle della Sezione 2: (1) Convex non cattura il rebalancing
premium che l'archetipo gli attribuisce — testato, non adottato per
campione insufficiente, non per assenza dell'effetto; (2) Convex non è
difensivo in crisi come l'archetipo suggerisce — è un moltiplicatore di
beta a leva, la protezione del sistema viene interamente da Apex e dal
mix, non da Convex isolato. Nessuna delle due richiede un'azione
immediata; entrambe meritano di restare esplicite per chi legge questo
documento aspettandosi che "Convex" si comporti come l'archetipo descrive.
