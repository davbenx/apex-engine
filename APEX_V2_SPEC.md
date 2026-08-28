# Apex v2 — Specifica Operativa

Documento di riferimento non ambiguo per il motore Apex v2, sostituto del waterfall
macro + selezione momentum Top-20 descritto in `README.md` (v1). Sostituisce quella
logica sulla base dei risultati in `research/` e dell'audit indipendente del
2026-08-27 (vedi report "Apex Audit" e "Apex Allocation").

**Perché questa versione esiste:** un audit statistico rigoroso (test a ingresso
casuale, Deflated Sharpe Ratio, Probability of Backtest Overfitting via CSCV) ha
dimostrato che la selezione di singoli titoli per momentum del motore v1 ha
**expectancy negativa e statisticamente significativa** su universo point-in-time
corretto (E(R) = -0.063R, IC 95% [-0.081,-0.044]). Il motore v2 descritto qui **non
seleziona titoli per generare alpha di selezione** — usa titoli individuali solo come
veicolo fiscalmente efficiente per un'esposizione azionaria a bassa volatilità.
L'alpha reale del sistema viene dal *timing* tra classi di attivo (trend-following
multi-asset), verificato con regressione CAPM: alpha annualizzato 10.6-11.1%,
p<0.001, confermato anche su split temporale in-sample/out-of-sample.

---

## 1. Universo e strumenti

| Ruolo | Strumento/i | Note |
|---|---|---|
| Segnale di timing azionario | SPY | Solo per il segnale — non è la posizione detenuta |
| Posizione azionaria reale | Basket di 15 titoli individuali | Selezionati per bassa volatilità tra i membri storici (point-in-time) dell'S&P 500 |
| Obbligazionario | IEF (ETF Treasury 7-10y) | Sia segnale sia posizione |
| Oro | GLD (ETF oro fisico) | Sia segnale sia posizione |
| Crypto | BTC-USD | Sia segnale sia posizione. **Nessuna rotazione verso altcoin** — testata e respinta (peggiora Sharpe/Calmar senza guadagno di rendimento) |
| Porto sicuro / cash-equivalent | Cash residuo (non investito) | Nella versione di ricerca era SHY; in produzione, se SHY non è tradabile facilmente, tenere cash puro — l'impatto misurato è marginale |

**Perché titoli individuali e non un ETF azionario:** un ETF UCITS genera "redditi di
capitale" in Italia (imponibili, non compensabili con minusvalenze). Titoli
individuali generano "redditi diversi" (compensabili, riporto 4 anni) — la stessa
logica già presente in `Apex_Test_Plan.md` §6-8 per l'integrazione fiscale con Convex.
**Verificare con un commercialista prima di operare** — non è un parere fiscale.

---

## 2. Segnale di timing (per ciascuna delle 4 classi, indipendente)

Calcolato a **fine mese** (ultima barra settimanale del mese), su barre **settimanali**.

```
MA(classe)        = media mobile semplice a 40 settimane del prezzo del proxy di segnale
distanza(classe)  = prezzo_oggi / MA(classe) - 1
```

**Isteresi (elimina i falsi segnali):**
```
se la classe era GIA' attiva:   resta attiva se distanza > -2%
se la classe era GIA' inattiva: diventa attiva se distanza > +2%
```
Lo stato (attiva/inattiva) di ciascuna classe si porta avanti da un mese al successivo.
Non esiste una soglia neutra unica: la banda -2%/+2% è intenzionale (isteresi).

**Peso di base:** ciascuna classe attiva riceve 1/4 del capitale nozionale (25%);
ciascuna classe inattiva riceve 0% (quel 25% va a cash/porto sicuro).

---

## 3. Vol-targeting di portafoglio (scala l'esposizione totale)

Dopo aver calcolato i pesi di base (§2), si scala l'intera esposizione per centrare
una volatilità di portafoglio dichiarata — **mai a leva**, solo riducendo verso cash.

```
vol(classe, 12w)  = deviazione standard dei rendimenti settimanali delle ultime 12
                    settimane del proxy di segnale, annualizzata (× sqrt(52))
vol_portafoglio   = somma pesata: Σ peso_base(classe) × vol(classe, 12w)
                    (stima grezza, non usa la matrice di covarianza — se erra, erra
                    per eccesso di cautela, non per difetto)

fattore_scala     = min(1.0, target_vol / vol_portafoglio)     [target_vol = 13%]

peso_finale(classe) = peso_base(classe) × fattore_scala
peso_cash            = 1 - Σ peso_finale(classe)
```

**Perché 13%:** centro del plateau 12-15% testato (Sharpe 1.37-1.42, Calmar 0.91-0.98
su questo intervallo). Non è il valore che massimizza un singolo backtest — è stato
scelto perché qualunque valore nell'intervallo 8-25% batte nettamente la versione
senza vol-targeting, e 12-15% è vicino alla convenzione istituzionale comune (10-15%)
per questo tipo di overlay.

**Perché funziona (e quando NON funziona):** il beneficio viene specificamente dal
contenere i picchi di volatilità di BTC quando occupa il suo slot. Sullo stesso
disegno senza crypto (2004-2026), il vol-targeting è stato testato e **non aiuta**
(Calmar 0.40-0.55 contro 0.55 senza) — è un risultato atteso e coerente, non un
difetto: se avesse aiutato ugualmente anche senza la fonte di volatilità che dovrebbe
contenere, sarebbe stato un segnale di overfitting, non di robustezza.

---

## 4. Selezione del basket azionario (quando la classe Equity è attiva)

**Universo ammissibile:** titoli storicamente membri dell'S&P 500 alla data (non la
composizione odierna applicata retroattivamente — vedi audit, finding critico #1).

**Criterio di selezione:** volatilità realizzata a 26 settimane, **crescente**
(si preferiscono i titoli a bassa volatilità, non quelli a momentum più alto — il
momentum come criterio di selezione è stato falsificato dall'audit).

**Numero di posizioni:** 15, equal-weight all'interno dello slot azionario.

**Frequenza di rotazione della composizione:** trimestrale (fine marzo, giugno,
settembre, dicembre). Nei mesi intermedi il paniere resta invariato nella
composizione — solo la taglia complessiva dello slot si aggiorna mensilmente (§3).

**Buffer di isteresi sulla permanenza (rank < 100, aggiunto dopo il finding di
turnover del backtest storico — vedi §8.3):** un titolo già in basket resta se la
sua posizione in classifica di volatilità resta entro il rank 100 (su ~600 titoli
tracciati storicamente), anche se è scesa fuori dal top-15 esatto. I nuovi ingressi
restano sempre selezionati solo tra i migliori in assoluto — il buffer allenta solo
l'uscita, mai l'entrata. Implementato in `apex_v2_engine.select_low_vol_basket`
(parametro `buffer_rank`, default `V2_EQUITY_BUFFER_RANK = 100`).

**Nessuno stop-loss per singola posizione — ora testato, non solo assunto.**
L'uscita da una posizione avviene solo (a) quando esce dal paniere alla rotazione
trimestrale, o (b) quando l'intera classe Equity si disattiva (§2). Aggiungere un
trailing stop settimanale per posizione (HH(12w) - k×ATR(12w), k testato tra 2.0 e
3.5 sul segnale campione SPY/IEF/GLD/BTC-USD) è stato verificato esplicitamente e
**peggiora sia l'edge sia l'alpha CAPM** su ogni valore di k testato:

| | CAGR | Sharpe | Sortino | Calmar | Alpha CAPM |
|---|---|---|---|---|---|
| Nessuno stop (disegno validato) | 14.9% | **1.39** | **2.29** | **0.94** | **10.6%** (p=0.0002) |
| Stop 2.5x ATR (il migliore dei 4 testati) | 12.8% | 1.30 | 2.14 | 0.92 | 9.4% (p=0.0005) |

Il vol-targeting mensile (§3) già assorbe il controllo del rischio a livello di
portafoglio; uno stop settimanale per posizione taglia fuori posizioni durante
normali ritracciamenti che il ribilanciamento di fine mese avrebbe comunque gestito
— genera whipsaw, non protezione aggiuntiva. La non-presenza di uno stop per
posizione è quindi una scelta misurata, non solo un'omissione.

---

## 5. Gamba crypto, obbligazionaria, oro

- **BTC-USD**: nessuna selezione, nessuna rotazione verso altcoin. Peso = peso
  finale della classe Crypto (§3).
- **IEF**: nessuna selezione, peso = peso finale della classe Bonds (§3).
- **GLD**: nessuna selezione, peso = peso finale della classe Gold (§3).

---

## 6. Calendario operativo

| Quando | Cosa |
|---|---|
| Ultima barra settimanale di ogni mese | Calcolo segnali (§2), vol-target (§3); se fine trimestre, ricalcolo basket azionario (§4) |
| Settimana successiva (T+1) | Esecuzione degli ordini per portare il portafoglio ai pesi target |
| Ogni esecuzione del motore (giornaliera, per monitoraggio) | Nessuna azione salvo alla data di decisione/esecuzione — questo motore non richiede interventi infrasettimanali |

Compatibile con l'esplicito requisito di intervento "solo settimanale o mensile,
niente daily".

---

## 7. Modello fiscale (Italia) — due scenari, da validare con un commercialista

| Categoria | Strumenti | Trattamento assunto |
|---|---|---|
| Redditi diversi (compensabili, riporto 4 anni) | I 15 titoli individuali, BTC-USD | Plus e minus si compensano nello stesso "calderone" |
| Redditi di capitale (non compensabili) | IEF, GLD (ETF UCITS) | Il guadagno è tassato; la perdita non compensa nulla, si perde |

Costo basis: **prezzo medio ponderato (PMC)** per strumento, prassi italiana standard
per titoli fungibili dello stesso ISIN — non FIFO.

**Turnover atteso:** ~109 eventi tassabili l'anno (dominato dai ribilanciamenti
mensili di taglia sui 15 titoli, non dalla rotazione trimestrale della composizione
— un ETF costerebbe ~23 eventi/anno per lo stesso segnale, un solo ordine invece di
fino a 15 per ogni ricalibrazione).

---

## 8. Cosa NON è stato ancora validato (limiti dichiarati)

- Nessun test di falsificazione tipo "ingresso casuale" applicato a questo segnale di
  timing specifico (fatto invece sul motore di selezione titoli v1).
- Un solo proxy di segnale per classe (SPY, IEF, GLD, BTC-USD) — testato un segnale
  multi-proxy in alternativa (§8.2, test 4): **peggiora** i risultati, quindi il
  proxy singolo resta la scelta migliore trovata finora, non solo la più semplice.
- Il vantaggio fiscale della gamba azionaria non è stato verificato da un
  commercialista.
- Costi di transazione stimati (8bps ETF, 10bps titoli/crypto) — stress-testati fino
  a 5x (§8.2, test 3): l'edge regge, ma restano stime, non i costi reali del broker
  in uso.
- Nessuna interazione modellata con Convex o con eventuali flussi PAC.
- **La maggior parte dell'alpha misurato (10.64%/anno) viene dal campione breve
  2014-2026 con BTC incluso, durante un periodo di bull secolare per BTC stesso — vedi
  §8.2 test 2: su un campione più lungo e duro (2004-2026, senza crypto, GFC inclusa)
  l'alpha strutturale è più realisticamente ~2.9%/anno.** Non è un limite nel senso di
  "non testato", ma un ridimensionamento dell'aspettativa di rendimento da tenere
  esplicito.

### 8.1 Registro dei test aggiuntivi respinti (dopo il deploy)

In conformità allo stesso principio anti-overfitting di `BRIEF_AGENTE.md` (§3.7:
"si riportano tutti i test eseguiti, inclusi quelli negativi"), oltre ai sei
tentativi di miglioramento già respinti prima del deploy (titoli individuali con
rotazione mensile, diversificazione a 9 mercati, rotazione altcoin, pesatura per
forza del trend, doppia conferma trend+momentum, stop-loss per posizione — vedi
Apex Allocation §7/§7-bis e la sezione stop sopra), sono stati testati altri due
candidati dopo il deploy, entrambi respinti:

- **Banda di non-negoziazione** (non ribilanciare se il peso target cambia di poco):
  riduce il turnover (23→11-18 eventi/anno a seconda dell'ampiezza) ma peggiora
  Sharpe e Calmar a ogni ampiezza testata (1-5 punti percentuali) — perché impedisce
  al vol-targeting di essere preciso, che è il meccanismo che rende il disegno
  valido. Scartata.
- **Kill-switch di portafoglio su drawdown** (riduce l'esposizione se il DD supera
  una soglia): alle soglie 20-25% non scatta mai in 12 anni (il vol-targeting tiene
  già il MaxDD sotto soglia); alla soglia 15% scatta ma non migliora nulla — segnale
  reattivo, arriva quando il danno è già fatto. Scartata.
- **Trend-following simmetrico via ETF inversi** (SH/TBF/DGZ al posto della cash
  quando Equity/Bond/Gold sono "inattivi", stesso vol-target; crypto esclusa per
  storico dati insufficiente su BITI): migliora Calmar (0.94→1.06) e MaxDD
  (15.9%→11.7%) e risolve il punto debole del 2022 (-7.9%→+0.5%), ma **CAGR netto
  di tasse peggiora di 2.4-2.8 punti percentuali l'anno** (Scenario A: 12.61%→10.16%;
  Scenario B: 12.42%→9.62%, quest'ultimo dopo aver corretto la classificazione
  fiscale di SH/TBF/DGZ come "redditi di capitale" non compensabili, stesso
  involucro ETF di SPY/IEF/GLD) — su $100k in 12 anni, ~$94.300 di ricchezza netta
  finale in meno (Scenario A). Il gap di alpha CAPM isolato è invece piccolo
  (10.64%→9.57%, -1.07pp, entrambi p<0.05) — l'alpha da solo sottostima il vero
  costo, che si vede sul CAGR netto per via del turnover più alto (23.4→30.1
  eventi/anno). Scartata: il trade-off (drawdown più contenuto) non compensa il
  costo fiscale/di rendimento composto rispetto agli obiettivi dichiarati
  (alpha + efficienza fiscale).

- **Segnale multi-proxy per classe** (media di più ticker invece di un singolo
  proxy: SPY+QQQ+IWM per Equity, IEF+TLT per Bond, BTC+ETH per Crypto): peggiora
  Sharpe (1.39→1.29), Calmar (0.94→0.77) e MaxDD (15.9%→17.9%) — diluire il segnale
  con proxy meno puri aggiunge rumore/ritardo invece di ridurlo. Scartato.
- **Pesatura inverse-vol nel basket azionario** (invece di equal-weight, sul
  basket isolato — vedi §8.3 per la nota metodologica sull'isolamento): CAGR
  10.14%→9.01%, Sharpe 0.75→0.65, Calmar 0.38→0.35 — peggiora su ogni metrica,
  probabilmente perché sovrappesa proprio i nomi con volatilità misurata più
  bassa, i più esposti al rumore di stima. Scartata.
- **Espansione dell'universo crypto oltre BTC-USD** (due varianti, script
  `trend_ts_short_and_crypto_variants.py`): (a) mix statico 70/30 BTC/ETH senza
  rotazione, (b) basket a bassa volatilità (top-2 di 5: BTC/ETH/SOL/ADA/XRP,
  rotazione trimestrale, stessa logica del basket azionario). Entrambe
  peggiorano ogni metrica rispetto a BTC-only: Sharpe 1.39→1.36/1.26, Calmar
  0.94→0.85/0.90, alpha CAPM 10.64%→9.35%/10.02% (entrambi comunque
  significativi), eventi tassabili/anno 23.4→27.9/26.3. Nessun compenso nei
  regimi difficili (Bear 2022: -7.9% baseline vs -8.4%/-8.7% con più crypto).
  BTC-only domina su tutta la linea. Scartate entrambe.

**Nota metodologica:** dopo 13 tentativi di miglioramento testati sullo stesso
campione di 12 anni, tutti respinti o neutri, ulteriori tentativi vanno pesati
contro il rischio di data-snooping crescente (lo stesso principio che ha già
smascherato il motore di selezione titoli v1). Il disegno deployato resta quello
raccomandato finché non emerge un'ipotesi con una giustificazione a priori più
forte di "vediamo se funziona".

### 8.2 Test di robustezza (non cercano nuovo alpha, verificano quello già trovato)

A differenza di §8.1 (nuove logiche, testate e respinte), questi quattro test non
modificano il disegno: verificano se i parametri già scelti sono un plateau solido
o un picco isolato, e se l'alpha misurato regge su un campione più severo.

1. **Griglia MA (30-50 settimane) × isteresi (1-5%), 20 combinazioni, tutte con
   vol-target 13%:** Sharpe varia da 1.24 a 1.47, il punto deployato (40w/2%,
   Sharpe 1.39) è nella parte alta del range senza esserne il massimo (1.47 a
   35w/5%) e nessuna combinazione crolla. Non è un picco da overfitting: è un
   plateau.
2. **Stress-test dei costi di transazione** (8→16→24→40bps, cioè fino a 5x
   l'assunzione attuale): Sharpe scende solo da 1.39 a 1.30, CAGR da 14.92% a
   13.86%. L'edge non è fragile ai costi.
3. **Segnale multi-proxy per classe:** vedi §8.1 — testato e respinto, il proxy
   singolo resta superiore.
4. **Campione lungo senza crypto (2004-2026, 22 anni, GFC inclusa) vs campione
   deployato (2014-2026, 12 anni, con BTC):** l'alpha CAPM scende da 10.64%/anno
   (t=3.75, p=0.0002) a **2.93%/anno** (t=2.52, p=0.012) — resta statisticamente
   significativo, quindi la logica di fondo (trend + isteresi + vol-target su
   azioni/obbligazioni/oro) è reale e non un artefatto del campione breve. Ma la
   maggior parte del rendimento spettacolare misurato sul campione deployato
   (CAGR 14.92%, Sharpe 1.39) viene dall'aver incluso BTC durante un periodo in
   cui BTC stesso era in un bull secolare, non dalla bontà del meccanismo di
   timing in sé. Il vero motore strutturale, isolato da quell'effetto, vale più
   realisticamente ~3 punti di alpha/anno. **Non cambia la decisione di tenere
   BTC nell'universo** (è legittimo, e il segnale lo gestisce con la stessa
   logica delle altre classi), ma ridimensiona l'aspettativa di rendimento da
   comunicare: il 10%+ di alpha annuo storico non va trattato come "normale".

### 8.3 Costruzione del basket azionario: turnover storico e correzione applicata

Backtest storico reale (non un solo punto nel tempo) della selezione per bassa
volatilità sull'universo S&P 500 point-in-time, 2014-2026, 49 trimestri, verificato
sui ~600 titoli con dati sufficienti in cache.

**Bug trovato e corretto durante questa stessa sessione di test — dichiarato per
trasparenza:** la prima versione di questo paragrafo riportava un turnover del
~93% (1,4/15 titoli sopravvissuti a trimestre) e raccomandava `buffer_rank = 100`,
già implementato in produzione. Costruendo il test di validazione end-to-end
(sotto) è emerso un bug nel calendario dei prezzi: `pd.DataFrame` su 600+ titoli
con calendari di trading leggermente disallineati (fonte dati gratuita) produce
l'*unione* di tutte le date viste, non un calendario settimanale pulito —
verificato che 26 righe indietro nell'indice corrispondevano a soli 59 giorni
reali invece dei ~182 attesi per 26 settimane. La finestra di volatilità usata per
selezionare il basket era quindi ~3 volte più corta del dichiarato. Corretto
riallineando ogni titolo sul calendario canonico di SPY (reindex + ffill) in
`basket_construction_tests.build_universe_frame`. Tutti i numeri sotto sono
ricalcolati con il fix.

**Scoperta confermata (ridimensionata dal fix, ma reale) — turnover del basket più
alto dell'assunto:** in media 5,8 titoli su 15 sopravvivono da un trimestre al
successivo (~61% di rinnovo, non ~93% come nella prima misura errata).
Verificato non essere un artefatto di dati scadenti (le composizioni storiche
sono titoli liquidi e noti — MCD, PG, IBM, DUK, AON, ecc.) ma un effetto
strutturale: centinaia di titoli hanno volatilità realizzata simile vicino alla
soglia dei 15, e il rumore di stima settimana-per-settimana rimescola la
classifica esatta. **Nessun backtest precedente in questo documento — inclusa la
decisione originale di deploy — aveva mai simulato questo turnover**: tutti usano
SPY come proxy della gamba azionaria a livello di segnale macro.

**Correzione applicata — buffer di isteresi sulla rank (stessa idea dell'isteresi
già validata sul segnale macro, e della buffer rule usata dagli indici MSCI
Minimum Volatility per lo stesso problema), numeri corretti:**

| Buffer di permanenza | CAGR | Sharpe | Calmar | MaxDD | Turnover/trimestre |
|---|---|---|---|---|---|
| Nessuno | 9.30% | 0.75 | 0.40 | 23.5% | 121.0% |
| top-16 | 9.44% | 0.76 | 0.40 | 23.5% | 117.1% |
| top-18 | 9.47% | 0.78 | 0.44 | 21.6% | 112.6% |
| **top-20 (adottato)** | **9.52%** | **0.79** | **0.44** | **21.6%** | 107.4% |
| top-22 → top-150 | 7.81% – 9.01% | 0.65 – 0.77 | 0.33 – 0.43 | 20.3% – 23.7% | 96.5% → 19.0% |
| Illimitato (mai esce se non per rimozione da S&P 500) | 13.15% | 0.97 | 0.62 | 21.1% | 2.1% |

*(Nota: questi Sharpe/Calmar sono del basket azionario isolato, sempre investito
al 100%, senza l'overlay di timing/vol-target di portafoglio — non sono
confrontabili con lo Sharpe della strategia intera. Vedi il test end-to-end sotto
per il confronto valido.)*

**Adottato: buffer_rank = 20**, non 100. La zona 22-150 è **rumorosa e non
monotona** (Sharpe oscilla tra 0.65 e 0.77 senza un pattern chiaro) — prendere
alla lettera il singolo punto migliore in quella zona sarebbe stato lo stesso
errore di data-snooping che questo documento cerca di evitare altrove. La zona
16-20 invece è consistentemente migliore del nessun-buffer su ogni metrica, con
un allentamento piccolo e facilmente giustificabile (poco oltre il top-15
esatto). Scelto il punto migliore di quella zona stretta e coerente, non il
singolo massimo assoluto del grid intero.

**Scartato: buffer illimitato**, pur avendo ancora i numeri migliori in tabella
dopo la correzione. Senza soglia di uscita per volatilità, il basket smette di
fare sorveglianza continua e degenera in "compra i titoli selezionati nel 2014 e
non toccarli più" — il risultato rischia di riflettere che quella selezione
iniziale si è rivelata buona col senno di poi, non un edge sistematico di
rotazione per bassa volatilità.

**Validazione end-to-end (il test più importante di questa sessione):** tutti i
backtest precedenti in questo documento — inclusa la decisione di deploy —
usavano SPY come proxy della gamba azionaria nel segnale di timing. Con il fix
del calendario, è stato simulato per la prima volta il sistema VERO (segnale
macro + basket azionario reale con rotazione trimestrale e buffer-20), script
`full_strategy_backtest.py`:

| | CAGR | netA | Sharpe | Calmar | MaxDD | Alpha CAPM |
|---|---|---|---|---|---|---|
| **Sistema reale (basket top-15, buffer-20)** | 15.01% | 12.63% | 1.41 | **1.13** | **13.3%** | **11.31%** (t=3.96, p=0.0001) |
| Proxy SPY (usato in tutti i test precedenti) | 14.92% | 12.61% | 1.39 | 0.94 | 15.9% | 10.64% (t=3.75, p=0.0002) |

Il sistema reale **eguaglia o supera** l'approssimazione SPY su ogni metrica —
Calmar e MaxDD sono nettamente migliori, l'alpha è leggermente più alto e più
significativo. Il turnover reale del basket (che aveva sollevato il dubbio)
**non fa un buco nel rendimento netto**: la decisione di deploy, presa sul proxy
SPY, resta valida. Confrontati anche basket top-10 (CAGR 14.64%, Calmar 1.06) e
top-20 (CAGR 14.87%, Calmar 1.11): il top-15 deployato resta il migliore o
sostanzialmente alla pari — nessuna ragione per cambiare dimensione del basket.

### 8.4 To-do — decisioni aperte e miglioramenti non ancora testati

**Risolti in questo giro di test (vedi dettagli sopra):**
- ~~Dimensione del basket in combinazione con l'overlay completo~~ — fatto
  (§8.3, test end-to-end): top-15 resta il migliore o alla pari con top-10/20,
  nessuna ragione per cambiare.
- ~~Walk-forward vero~~ — fatto (script `walk_forward_test.py`): parametri scelti
  massimizzando lo Sharpe SOLO sulla prima metà campione (2014-2020) vs la
  scelta a-priori (40w/2%), confrontati fuori campione sulla seconda metà
  (2020-2026). Risultato: **sostanzialmente pari** (Sharpe 1.35 vs 1.35, CAGR
  14.66% vs 14.08%) — l'ottimizzazione cieca non batte in modo significativo la
  scelta teorica, nessun segno del classico decadimento da overfitting.
  Conferma che i parametri deployati non lasciano edge sul tavolo.
- ~~Costi di transazione reali del broker~~ — verificato con dati reali del
  conto IBKR collegato (205 trade azionari, gennaio-agosto 2026): commissione
  media ponderata per valore **~1,18 bps**, molto sotto l'8-10bps assunto in
  ogni backtest di questo documento. Le stime usate finora sono quindi
  **conservative** (sovrastimano il costo reale), non ottimistiche. Non
  verificato: costi su crypto/obbligazioni (nessun trade di quel tipo nel
  campione), e lo spread bid-ask/slippage non è visibile nel dato di
  commissione puro — la cifra reale copre solo la commissione del broker, non
  il costo di esecuzione totale.

**Risolto (vedi §8.7):**
- ~~Concentrazione settoriale nel basket~~ — confermata reale con dati Yahoo su
  tutto l'universo point-in-time (fino all'80% in un solo settore in alcuni
  trimestri), e collegata direttamente alla perdita di significatività
  dell'alpha nella finestra Feb 2024-oggi (§8.6/8.7). Vincolo max 2/settore
  adottato e implementato in produzione.

**Decise (non adottate, con motivazione):**
- **Decisione di ribilanciamento trimestrale invece di mensile** (§8.2 extra,
  script `quarterly_decision_test.py`): taglia gli eventi tassabili del segnale
  macro del 65% (23.4→8.2/anno) e migliora leggermente il CAGR netto (12.61%→
  13.36% Scenario A), ma MaxDD peggiora (15.9%→20.8%) e Calmar peggiora
  (0.94→0.75) per reazione più lenta nei mercati "in stillicidio" tipo 2022
  (-7.9%→-13.0%). **Non adottata**: il meccanismo che rompe è lo stesso già
  respinto con la "banda di non-negoziazione" (§8.1) — ridurre la frequenza
  della decisione impedisce al vol-targeting di essere preciso, che è il motivo
  per cui il disegno funziona. La cadenza mensile già rispetta ampiamente il
  vincolo "mai infragiornaliero/daily"; il guadagno fiscale marginale (+0.7pp
  di CAGR netto) non giustifica accettare un controllo del rischio
  sistematicamente peggiore.
- **Sleeve Commodity aggiuntiva (DBC)** (script `reit_commodity_sleeve_test.py`):
  sul campione deployato (12 anni) migliora tutto (Sharpe 1.39→1.46, Calmar
  0.94→1.35, MaxDD 15.9%→10.9%, alpha invariato) e risolve il 2022. Ma sul
  campione lungo 2006-2026 (GFC inclusa) è sostanzialmente neutro o peggiore
  (Sharpe 0.97→0.92, alpha 2.93%→2.68%, GFC MaxDD 8.0%→12.1%) perché le
  commodity sono crollate insieme alle azioni nel 2008 — protegge da uno shock
  da rialzo tassi (2022-style) ma non da uno shock di domanda (2008-style), anzi
  peggiora quest'ultimo. **Non adottata**: stesso principio che ha già
  respinto il "buffer illimitato" (§8.3) e la diversificazione a 9 mercati
  (§8.1) — un miglioramento che appare forte solo sul campione breve e
  regredisce (o peggiora) sul campione lungo e severo non è un edge robusto,
  è un artefatto del periodo testato. Aggiungerebbe anche complessità e
  turnover (ev/yr 23.4→26.9) senza un beneficio che regga fuori campione.

### 8.5 Bug di produzione trovato e corretto — il NAV non era composto

Il giorno stesso della prima esecuzione live dopo il deploy (27→28 agosto 2026,
migrazione v1→v2 forzata via `workflow_dispatch`), il grafico equity della
dashboard ha mostrato un crollo del NAV da $243.770 a $160.436 (-34%) in un solo
giorno — nessun evento di mercato reale lo giustificava.

**Causa:** `update_equity_curve` ricalcolava ogni notte il NAV da zero come
"capitale iniziale ($100k) + somma di tutto il P&L storico, con ogni trade
dimensionato come `$100k × peso`" — questa base di capitale FISSA ignora
completamente la crescita composta: dopo che il NAV reale è cresciuto ben oltre
i $100k iniziali, ogni posizione avrebbe dovuto essere dimensionata come
`NAV_corrente × peso`, non `$100k × peso`. Il giorno della migrazione, che ha
chiuso ~24 posizioni v1 in blocco (facendole passare da "P&L aperto" a "P&L
storico" nella stessa formula), ha reso visibile di colpo questo
sottodimensionamento cronico, causando il crollo.

**Correzione:** nuova funzione `mark_to_market_and_compound_nav` — il NAV è ora
un valore persistito (`portfolio.json["nav_usd"]`) che si compone giorno per
giorno (`nav_oggi = nav_ieri × (1 + rendimento pesato del giorno)`), esattamente
come in tutti gli script di backtest di questo progetto. `update_equity_curve`
si limita ora a registrarlo, senza più ricalcolarlo da zero. Aggiunta anche, per
coerenza con i backtest (mai modellata prima nel tracking live), una deduzione
del costo di transazione dal NAV ad ogni ribilanciamento (8bps ETF, 10bps
titoli/crypto — stessa convenzione di `APEX_V2_SPEC.md` §8.2 test 2). Test in
`test_backend.py` (4/4 passano).

**Correzione del dato live:** usando lo snapshot del portafoglio v1 salvato
poco prima della migrazione (prezzi "di ieri" per ciascuna posizione), è stato
ricostruito il vero rendimento pesato del giorno (+2,20%) e applicato al NAV
di chiusura del giorno prima ($243.770,52) invece di lasciare il valore
corrotto o inventarne uno arbitrario: **NAV corretto = $249.125,46**, in
continuità piena con la curva storica precedente. Nessun altro punto della
curva storica risultava affetto (il bug si manifesta solo quando la base di
capitale fissa diverge abbastanza dal NAV reale, cosa emersa con evidenza solo
nel giorno di migrazione).

### 8.6 Sostituzione del track record — da simulazione v1 a simulazione v2

Su richiesta esplicita dell'utente, l'intero "backtest out-of-sample" mostrato in
dashboard (storico operazioni chiuse + curva equity, finestra Feb 2024 - oggi,
etichettato in app.py come "SIMULAZIONE QUANTITATIVA & TRACK RECORD") è stato
rigenerato usando il motore v2 al posto del v1 — non più solo una migrazione
delle posizioni, ma un'unica simulazione continua e coerente dall'inizio della
finestra a oggi.

**Metodo:** replay mese per mese (script `generate_v2_track_record.py`) della
stessa identica logica di `backend.py.update_portfolio` — stesso segnale macro
(isteresi + vol-target), stessa selezione basket (top-15, buffer-rank 20, **poi
aggiornato con il vincolo max 2/settore — vedi §8.7**), stessi costi (8bps ETF,
10bps titoli/crypto) — usando dati di mercato reali sull'intera finestra Feb
2024-oggi. Risultato finale (dopo §8.7): 363 eventi di chiusura (tutti con
motivazioni v2 reali, nessuna traccia del motore v1), NAV finale $122.761,10
(da $100.000 iniziali), 14 posizioni aperte finali (12 titoli del basket + IEF
+ BTC, diversificati su 8 settori diversi) diventate il portafoglio "live"
attuale — l'ultima decisione della simulazione stessa, non più una migrazione
ad-hoc.

**Cosa NON cambia:** la struttura del file (`open_positions`, `trade_history`,
`nav_usd`, `equity.json`) resta identica; il forward-tracking notturno
(`backend.py`) continua a comporre il NAV da questo punto in poi esattamente
come già descritto in §8.5.

**Limite dichiarato:** questa simulazione, come ogni backtest in questo
documento, resta soggetta agli stessi limiti di §8 (nessuna verifica dei costi
reali del broker su questa specifica finestra breve, nessun test di
falsificazione dedicato) — è una ri-esecuzione a regole fisse su dati storici,
non un track record di trading realmente eseguito con il motore v2 (quello
comincia da oggi in avanti).

### 8.7 Vincolo di concentrazione settoriale — adottato (max 2 titoli/settore)

Innescato da un caso reale: la prima versione del track record v2 (§8.6) ha
mostrato un rendimento di +23,9% sulla finestra Feb 2024-oggi contro +52,8% di
SPY nello stesso periodo, con **alpha CAPM non significativo** (1,70%/anno,
t=0,34, p=0,73 — indistinguibile da zero, contro il 10,64%/p=0,0002 del
campione pieno di 12 anni). Causa identificata: il basket finale era
concentrato al 77% in soli due settori (Utilities 46%, Real Estate 31%) —
esattamente i settori che soffrono di più in un bull market guidato da
tech/AI con tassi elevati, il regime di questi due anni e mezzo.

**Test del vincolo (script `sector_cap_test.py` isolato, poi
`sector_cap_full_test.py` con overlay macro completo, dati settore reali via
Yahoo Finance su tutto l'universo point-in-time):**

| | Isolato (solo basket, 12 anni) | Con overlay macro completo (12 anni) |
|---|---|---|
| Nessun vincolo | CAGR 9,52% Sharpe 0,79 Calmar 0,44, concentrazione peggiore 80% | CAGR 15,01% Sharpe 1,41 Calmar 1,13 alpha 11,31% (p=0,0001) |
| Max 2/settore | CAGR 10,95% Sharpe 0,84 Calmar 0,53, concentrazione peggiore 13,3% | CAGR 14,65% Sharpe 1,39 Calmar 1,03 alpha 10,92% (p=0,0001) |

**Risultato non pulito, deciso comunque:** isolato sul solo basket il vincolo è
un miglioramento netto; con l'overlay macro completo (il sistema vero) è un
piccolo costo medio sui 12 anni (Sharpe -0,02, Calmar -0,10) — la
concentrazione naturale in settori difensivi tende a complementare bene il
vol-targeting nella media storica, inclusi periodi come il 2022 dove quei
settori hanno retto meglio. **Adottato comunque** (`V2_MAX_PER_SECTOR = 2` in
`apex_v2_engine.py`) su richiesta esplicita dell'utente ("voglio alpha rispetto
al benchmark"): il costo medio storico è piccolo e l'alpha sui 12 anni resta
fortemente significativo con o senza vincolo, mentre la concentrazione
protegge proprio contro il tipo di rischio che ha appena eroso la
significatività dell'alpha nella finestra recente — un rischio asimmetrico che
una media di 12 anni non rappresenta bene.

**Implementazione:** `select_low_vol_basket` (in `apex_v2_engine.py`) accetta
ora `sector_of`/`max_per_sector`; il vincolo allenta solo la *composizione*
(quali titoli, a parità di rank, entrano), mai l'ammissione di un titolo
scarso — un titolo senza settore noto non viene mai bloccato (fail-open). I
settori sono recuperati da `backend.py.fetch_sector_map` (endpoint Yahoo
quoteSummary/assetProfile, stesso stile HTTP diretto di `fetch_yahoo_history`,
nessuna nuova dipendenza) solo alla rotazione trimestrale del basket. 4 nuovi
test in `test_apex_v2_engine.py` (14/14 test totali passano). Il track record
Feb 2024-oggi (§8.6) è stato rigenerato con il vincolo attivo per coerenza
piena.

---

## 9. Differenze dal motore v1 (cosa cambia per l'utente)

| Aspetto | v1 (attuale) | v2 (questo documento) |
|---|---|---|
| Segnale macro | RSP/SPY/BTC/GC=F/IEF vs MA40w, cascata fissa | SPY/IEF/GLD/BTC-USD vs MA40w, isteresi ±2%, indipendenti per classe |
| Scala esposizione | Nessuna — 100% del peso allocato se il segnale è positivo | Vol-targeting di portafoglio al 13% — riduce l'esposizione quando il rischio realizzato sale |
| Selezione azionaria | Top-20 per momentum (ROC/ATR), Darvas-style | Top-15 per **bassa volatilità**, tra titoli point-in-time eligible |
| Rotazione azionaria | Mensile, intera composizione | Trimestrale la composizione, mensile solo la taglia |
| Stop-loss per posizione | Trailing ATR × 3, aggiornato ogni venerdì | Nessuno — uscita solo per rotazione o disattivazione classe |
| Crypto | BTC + fino a 2 altcoin (Top-3 per momentum) | Solo BTC-USD, nessuna rotazione |
| Cap per asset class | Percentuali fisse (70/15/10/resto) | Nessun cap fisso — il peso è determinato dal segnale + vol-target |

**Migrazione dal portafoglio attuale:** le 23 posizioni aperte e i pesi del motore v1
non sono compatibili one-to-one con il disegno v2 (basket diverso, nessuno
stop-loss). Serve una decisione esplicita su come gestire la transizione — non
implicita nel codice.
