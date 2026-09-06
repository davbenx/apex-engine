# VENTURE_ALTCOIN_SPEC.md — Specifica del Sistema Venture Satellite Altcoin

---

## 1. Principi e Fondamenti Matematici

Il **Sistema Venture Satellite Altcoin** è un modulo quantitativo asimmetrico concepito per estrarre rendimento dalla legge di potenza (*power-law distribution*) del mercato delle criptovalute alternative. 

A differenza di **Apex Engine** (che ottimizza Sharpe e Calmar su orizzonti settimanali/trimestrali) e di **Convex Stack** (che genera protezione anti-fragile e carry decorrelato), il Venture Satellite persegue **convessita' pura a rischio delimitato**:
- **Asimmetria di rendimento**: perdita massima delimitata al capitale stanziato ($-100\%$), con guadagno potenziale moltiplicativo ($+300\%$, $+700\%$, $+1500\%$).
- **Ring-Fencing Patrimoniale**: il capitale del Satellite è rigidamente circoscritto a un budget scalabile tra il **2,5% e il 12,5% del Net Worth** complessivo, selezionabile dall'utente (default: **5,0%**, pari a 10.000 € su un Net Worth di 200.000 €, suddivisi in 10 slot da 1.000 €).
- **Indipendenza Operativa**: il motore di produzione di Apex Engine rimane al 100% investito in Solo BTC-USD per la componente macro. Il Venture Satellite opera su un conto/wallet disaccoppiato.

---

## 2. Architettura di Allocazione, Slot e Dual-Regime

Il budget totale ($B_{\text{venture}}$) viene gestito secondo un'architettura **Dual-Regime** a tre macro-stati, che risolve il costo di opportunita' del capitale e protegge da prolungate fasi laterali/ribassiste:

### 2.1 La Macchina a Stati Dual-Regime
1. **Regime 1: Macro Bear Sistemico** ($P_{\text{BTC}} \le \text{SMA}_{20w} \lor \text{SMA}_{20w} \le \text{SMA}_{40w}$):
   - Allocazione: **100% Cassa EUR**.
   - Qualsiasi riserva BTC residua viene liquidata in contanti EUR.
   - Nessun nuovo slot altcoin puo' essere aperto. Massima protezione del capitale (0% perdite nel 2018 e 2022).
2. **Regime 2: Bitcoin Dominance (Idle Sleeve)**:
   - Condizione: BTC Bull confermato, ma Altcoin Gate spento ($\text{Breadth} < 45\%$ o $\text{RS Spread} < 40\%$).
   - Allocazione: **Riserva Bitcoin (BTC)**.
   - La liquidita' non impegnata in slot altcoin risiede interamente in Bitcoin (`btc_reserve_units`). In questo modo il satellite beneficia dei bull market di Bitcoin (es. +24,5% nel 2024) invece di subire il deprezzamento e i falsi breakout delle altcoin.
3. **Regime 3: Altcoin Expansion (Altseason Gate ON)**:
   - Condizione: BTC Bull AND $\text{Breadth} \ge 45\%$ AND $\text{RS Spread} \ge 40\%$.
   - Allocazione: **Fino a 10 Slot Altcoin** da 1.000 € ciascuno (o quota prefissata).
   - Quando scatta un segnale su un token qualificato, il capitale viene prelevato dalla cassa o, se insufficiente, disinvestito parzialmente dalla Riserva BTC.
   - All'uscita della posizione altcoin (o realizzo Milestone 1 Free-Ride), il capitale rimborsato ritorna nella Riserva BTC (se BTC Bull) o in Cassa (se Bear).

### 2.2 Dimensionamento degli Slot e Vincoli
- **Numero di Slot Massimi ($N$)**: da 8 a 12 (default: $N = 10$).
- **Allocazione per Posizione ($C_0$)**:
  $$C_0 = \frac{B_{\text{venture}}}{N}$$
  Su un budget standard di 10.000 € suddiviso in 10 slot, ciascuna nuova posizione viene aperta con una quota fissa di **1.000 €**.
- **Vincolo di Concentrazione Tematica**: per evitare cluster di fallimento settoriale, non sono ammessi piu' di 2 token per lo stesso comparto narrativo (es. Layer 1, AI/Compute, DeFi 2.0, Real World Assets, DePIN).

---

## 3. Protocollo di Uscita e De-risking Asimmetrico

La gestione della posizione non si basa su stop percentuali simmetrici, ma su una scala a scaglioni (*asymmetric milestone ladder*):

### 3.1 Milestone 1: De-risking a Costo Zero (Free Ride) al +125% ($2,25\times$)
Appena il prezzo di mercato tocca 2,25 volte il prezzo di carico ($P \ge 2,25 \cdot P_0$):
- **Azione**: Vendita automatica del **44,4% delle quote iniziali** ($1/2,25$) tramite ordine limite GTC residente su exchange (eseguito su massimo intraday $High \ge 2,25 \cdot P_0$).
- **Effetto Matematico**:
  $$\text{Capitale Recuperato} = (0,444 \cdot Q_0) \cdot (2,25 \cdot P_0) = Q_0 \cdot P_0 = C_0$$
- Il 100% del capitale iniziale investito rientra in cassa.
- Il token assume lo stato permanente di **Free Ride (Rischio Zero di Rovina)**. La restante quota (~55,6%) costituisce una posizione a costo contabile nullo.

### 3.2 Milestone Successive: Ladder di Liquidazione dei Runner
Sulle quote residue della posizione Free Ride vengono applicate le seguenti soglie:
1. **Milestone 2 (+300% / 4x)**: Liquidazione del **20%** delle quote residue su $High \ge 4,0 \cdot P_0$. Messa a profitto netta.
2. **Milestone 3 (+700% / 8x)**: Liquidazione del **25%** delle quote residue su $High \ge 8,0 \cdot P_0$.
3. **Milestone 4 (+1500% / 16x)**: Liquidazione del **50%** delle quote residue su $High \ge 16,0 \cdot P_0$.
4. **Runner Moonbag**: Sulla frazione rimanente (~15% delle quote iniziali), si attiva un **trailing stop dinamico del 30%** calcolato rispetto al massimo storico registrato dalla posizione, eseguito su minimo intraday ($Low \le P_{\text{peak}} \times 0,70$).

### 3.3 Architettura di Uscita a Due Livelli (Exchange GTC vs Supervisione Giornaliera)

L'operativita' di Frontier Venture e' formalmente strutturata su due layer complementari che eliminano qualsiasi discrepanza tra simulazione e realta' di mercato:

1. **Layer 1: Ordini Residenti su Exchange (Esecuzione Continua su Intraday High/Low)**:
   - **Take-Profit Milestone 1 (+125%)**: ordine limite pendente inserito all'apertura dello slot su Kraken Futures a $P_0 \times 2,25$ per il 44,4% delle quote. Viene eseguito tempestivamente sui picchi di volatilita' intraday ($High$).
   - **Hard Stop Loss (-40%)**: ordine stop condizionato (`stop-loss-market`) inserito all'apertura a $P_0 \times 0,60$. Viene eseguito immediatamente se il minimo intraday batte la soglia ($Low \le P_0 \times 0,60$), proteggendo il capitale da crolli a cascata.
   - **Risoluzione di Conflitto (stessa barra)**: se una barra anomala tocca sia lo stop che il target, se $Open \le P_{\text{stop}}$ scatta lo stop in apertura; se $Open \ge P_{\text{target}}$ scatta il target in apertura; altrimenti si applica il principio conservativo di priorita' dello Stop Loss.
2. **Layer 2: Supervisione Algoritmica Discreta (Valutazione su Daily Close)**:
   - **Time-Stop / Relative Invalidation (30 giorni, Priorità di Supervisione)**: se dopo **30 giorni** dall'ingresso la posizione non ha ancora raggiunto la Milestone 1 (Free Ride) e a chiusura di barra giornaliera registra una sottoperformance vs Bitcoin inferiore a **$-20\%$** ($\Delta R = R_{\text{token}} - R_{\text{BTC}} < -0,20$), la posizione viene chiusa a mercato per `TIME_STOP`. Questa regola taglia in anticipo i falsi breakout e le posizioni in stallo prima che raggiungano lo stop secco, riducendo le perdite medie dal $-40\%$ a circa il $-15\%/-20\%$.

---

## 4. Profit Recycling Loop (Riciclo Sistematico degli Utili)

Uno dei fattori primari di perdita nei mercati crypto è il "round-trip" degli utili cartacei (guadagni non realizzati durante la bull run che si dissolvono nel successivo bear market).

Il Venture Satellite Altcoin adotta la regola del **travaso patrimoniale unidirezionale**:
- **Capitale Iniziale Recuperato ($C_0$)**: rimane nel saldo di cassa del Satellite Venture per finanziare un nuovo slot di investimento quando si presenta un'opportunità qualificata.
- **Tutti i Profitti Netti Realizzati**: vengono sistematicamente **estratti dal comparto altcoin** e bonificati verso il portafoglio istituzionale principale:
  1. $50\%$ convertito in **Bitcoin in Cold Storage** (accumulo strategico di riserva di valore).
  2. $50\%$ indirizzato al portafoglio unificato **Apex + Convex** o liquidità protetta XEON.
- È formalmente vietato aumentare il budget complessivo del Satellite Venture oltre il tetto prefissato del 3,0% del Net Worth.

---

## 5. Criteri di Selezione, Screening dei Candidati e Altcoin Gate

### 5.1 Altcoin Expansion Gate (Semaforo Macro di Ingresso)
Prima ancora di valutare i singoli token, l'apertura di nuovi slot altcoin e' condizionata dal superamento di due metriche aggregate di mercato:
1. **Ampiezza di Mercato Altcoin ($\text{Breadth} \ge 45,0\%$)**: almeno il 45% dei contratti perpetual attivi su Kraken Futures deve scambiare al di sopra della rispettiva media mobile a 20 settimane (140 giorni). Questo impedisce acquisti spuri quando l'80% del mercato altcoin e' in downtrend secolare.
2. **Forza Relativa Aggregata vs BTC ($\text{RS Spread} \ge 40,0\%$)**: almeno il 40% dell'universo altcoin deve aver sovraperformato Bitcoin negli ultimi 30 giorni.

Se il Gate non e' soddisfatto, il sistema permane in **Regime 2 (BTC Dominance)**: il capitale libero non compra altcoin ma risiede nella Riserva Bitcoin.

### 5.2 Filtri di Ammissibilita' del Singolo Token
Quando il Gate e' attivo, un token diventa candidato ammissibile SOLO se supera TUTTI e 4 i filtri seguenti (implementazione reale in `altcoin_venture_engine.py::screen_venture_candidates`):
1. **Filtro di Liquidità**: quotazione come contratto perpetual attivo su Kraken Futures (interrogazione live dell'API pubblica `futures.kraken.com`), con esclusione tassativa di token wrapped, liquid-staking e stablecoin (`EXCLUDED_CRYPTO_SYMBOLS`).
2. **Filtro Tokenomics / Diluizione**: rapporto Market Cap / Fully Diluted Valuation ($\text{MC} / \text{FDV}$) $> 0,40$, calcolato in tempo reale via l'API pubblica CoinGecko (`get_tokenomics_mc_fdv`). **Fail-safe**: se il dato non è verificabile per il token, il filtro NON è superato — non viene mai assunto un valore per difetto.
3. **Filtro di Momentum Tecnico**: rottura del massimo a 30 giorni, forza relativa positiva vs BTC a 20 giorni, prezzo sopra la media mobile a 140 giorni (20 settimane), non esteso oltre il 10% dal livello di rottura (anti-crowding).
4. **Filtro Fondamentale (trazione on-chain verificabile)**: variazione del TVL (Total Value Locked) a 90 giorni non inferiore a $-20\%$, calcolata via l'API pubblica DefiLlama (`get_tvl_trend_90d`) — a livello di chain per le Layer 1/L2 note, a livello di protocollo per gli altri token con presenza su DefiLlama. **Fail-safe**: nessuna presenza tracciata su DefiLlama (es. puro gas token o meme coin) → filtro non superato.

---

## 6. Struttura Dati e Persistenza

Lo stato del portafoglio satellite è serializzato in `venture_altcoin_portfolio.json`:
- `budget_total_eur`: ammontare totale destinato al satellite (default 10.000 €).
- `cash_available_eur`: liquidità disponibile in euro per nuovi investimenti.
- `btc_reserve_units`: quota di Bitcoin detenuta come riserva durante la fase di BTC Dominance.
- `btc_reserve_avg_entry_usd`: prezzo medio di carico della riserva BTC.
- `regime_mode`: stato operativo corrente (`REGIME_BEAR_CASH`, `REGIME_BTC_DOMINANCE`, `REGIME_ALT_EXPANSION`).
- `recycled_profits_eur`: totale profitti già estratti e inviati al portafoglio principale.
- `positions`: mappa dei token attualmente aperti con prezzi di carico, quote, storico milestone e prossimi target di vendita.
- `trade_history`: registro contabile di tutti gli ordini eseguiti, utili realizzati, minusvalenze e ribilanciamenti riserva.
