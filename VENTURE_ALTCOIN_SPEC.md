# VENTURE_ALTCOIN_SPEC.md — Specifica del Sistema Venture Satellite Altcoin

---

## 1. Principi e Fondamenti Matematici

Il **Sistema Venture Satellite Altcoin** è un modulo quantitativo asimmetrico concepito per estrarre rendimento dalla legge di potenza (*power-law distribution*) del mercato delle criptovalute alternative. 

A differenza di **Apex Engine** (che ottimizza Sharpe e Calmar su orizzonti settimanali/trimestrali) e di **Convex Stack** (che genera protezione anti-fragile e carry decorrelato), il Venture Satellite persegue **convessita' pura a rischio delimitato**:
- **Asimmetria di rendimento**: perdita massima delimitata al capitale stanziato ($-100\%$), con guadagno potenziale moltiplicativo ($+300\%$, $+700\%$, $+1500\%$).
- **Ring-Fencing Patrimoniale**: il capitale del Satellite è rigidamente circoscritto a un budget compreso tra l'**1,5% e il 3,0% del Net Worth** complessivo (default: **2,0%** o valore nozionale prefissato es. 4.000 € su 200.000 €).
- **Indipendenza Operativa**: il motore di produzione di Apex Engine rimane al 100% investito in Solo BTC-USD per la componente macro. Il Venture Satellite opera su un conto/wallet disaccoppiato.

---

## 2. Architettura di Allocazione e Slot

Il budget totale ($B_{\text{venture}}$) viene suddiviso in un numero finito di slot equi-allocati:
- **Numero di Slot Massimi ($N$)**: da 8 a 12 (default: $N = 10$).
- **Allocazione per Posizione ($C_0$)**:
  $$C_0 = \frac{B_{\text{venture}}}{N}$$
  Per esempio, su un budget di 4.000 € suddiviso in 10 slot, ciascuna nuova posizione viene aperta con una quota fissa di **400 €**.
- **Vincolo di Concentrazione Tematica**: per evitare cluster di fallimento settoriale, non sono ammessi più di 2 token per lo stesso comparto narrativo (es. Layer 1, AI/Compute, DeFi 2.0, Real World Assets, DePIN).

---

## 3. Protocollo di Uscita e De-risking Asimmetrico

La gestione della posizione non si basa su stop percentuali simmetrici, ma su una scala a scaglioni (*asymmetric milestone ladder*):

### 3.1 Milestone 1: De-risking a Costo Zero (Free Ride) al +100% ($2\times$)
Appena il prezzo di mercato tocca il doppio del prezzo di carico ($P \ge 2,0 \cdot P_0$):
- **Azione**: Vendita automatica del **50% delle quote iniziali**.
- **Effetto Matematico**:
  $$\text{Capitale Recuperato} = (0,50 \cdot Q_0) \cdot (2,0 \cdot P_0) = Q_0 \cdot P_0 = C_0$$
- Il 100% del capitale iniziale investito rientra in cassa.
- Il token assume lo stato permanente di **Free Ride (Rischio Zero di Rovina)**. La restante quota (50%) costituisce una posizione a costo contabile nullo.

### 3.2 Milestone Successive: Ladder di Liquidazione dei Runner
Sulle quote residue della posizione Free Ride vengono applicate le seguenti soglie:
1. **Milestone 2 (+300% / 4x)**: Liquidazione del **20%** delle quote residue. Messa a profitto netta.
2. **Milestone 3 (+700% / 8x)**: Liquidazione del **25%** delle quote residue.
3. **Milestone 4 (+1500% / 16x)**: Liquidazione del **50%** delle quote residue.
4. **Runner Moonbag**: Sulla frazione rimanente (~15% delle quote iniziali), si attiva un **trailing stop dinamico del 30%** calcolato rispetto al massimo storico registrato dalla posizione, per accompagnare il ciclo espansivo fino all'esaurimento del trend.

### 3.3 Regole di Chiusura in Perdita (Capital Protection & Tax Loss Harvesting)
1. **Hard Stop Loss (-40%)**: se il token scende al di sotto del $-40\%$ rispetto al prezzo di acquisto prima di raggiungere la Milestone 1, la posizione viene liquidata integralmente per proteggere il 60% del capitale dello slot e generare minusvalenze fiscali compensabili.
2. **Time Stop / Invalidation (90 giorni)**: se trascorsi 90 giorni dall'ingresso il token non ha superato $+25\%$ e mostra un rendimento relativo inferiore a BTC di almeno $-30\%$, la posizione viene chiusa d'ufficio per liberare lo slot di capitale a favore di progetti con catalizzatori attivi.

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

## 5. Criteri di Selezione e Screening dei Candidati

I token ammissibili nel Venture Satellite devono superare i seguenti 4 filtri oggettivi:
1. **Filtro di Liquidità**: volume medio giornaliero a 30 giorni $> 5.000.000\ \$$ e quotazione su almeno due exchange Tier-1 (es. Binance, Coinbase, Bybit, Kraken).
2. **Filtro Tokenomics / Diluizione**: rapporto Market Cap / Fully Diluted Valuation ($\text{MC} / \text{FDV}$) $> 0,40$, per scongiurare massicci sblocchi di offerta da parte di venture capitalist.
3. **Filtro di Momentum Tecnico**: prezzo sopra la media mobile a 50 giorni e rottura recente del massimo a 20 giorni con espansione di volume.
4. **Filtro Fondamentale / Narrativa**: trazione reale documentata on-chain (crescita TVL, utenti attivi giornalieri, commissioni generate dal protocollo o catalizzatore imminente).

---

## 6. Struttura Dati e Persistenza

Lo stato del portafoglio satellite è serializzato in `venture_altcoin_portfolio.json`:
- `budget_total_eur`: ammontare totale destinato al satellite.
- `budget_available_eur`: liquidità disponibile per nuovi investimenti.
- `recycled_profits_eur`: totale profitti già estratti e inviati al portafoglio principale.
- `positions`: mappa dei token attualmente aperti con prezzi di carico, quote, storico milestone e prossimi target di vendita.
- `trade_history`: registro contabile di tutti gli ordini eseguiti, utili realizzati e minusvalenze generate.
