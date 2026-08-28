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
- **Risk parity tra classi** (peso base inversamente proporzionale alla
  volatilità di ciascuna classe — Equity/Bonds/Gold/Crypto — invece di peso
  uguale tra le classi attive, prima dell'overlay di vol-target di portafoglio;
  script `class_risk_parity_test.py`): motivata dall'osservazione che BTC
  (18% su una sola posizione) e i singoli titoli del basket (1,2% ciascuno)
  hanno taglie molto diverse. Risultato negativo su ogni fronte: CAGR
  14,92%→9,15%, Sharpe 1,39→1,02, Calmar 0,94→0,40, **MaxDD peggiora**
  (15,9%→22,8%, il contrario di quanto la risk parity dovrebbe fare), alpha
  10,64%→4,90% (resta significativo ma molto più debole). Causa: la risk
  parity ha spostato il peso medio di IEF dal 12,3% al 36,4% proprio perché le
  obbligazioni avevano bassa volatilità storica — subito prima del 2022, dove
  il rialzo dei tassi le ha colpite duramente (Bear 2022: -17,9% vs il -7,9%
  del disegno deployato). Fallimento classico della risk parity ingenua: pesa
  per la calma recente, non per il rischio futuro. Scartata — l'asimmetria di
  taglia tra posizioni (classi a peso uguale, poi diversificazione solo dentro
  lo slot Equity) è per costruzione, non un problema da correggere.

**Nota metodologica:** dopo 14 tentativi di miglioramento testati sullo stesso
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

### 8.8 Bug di produzione trovato e corretto — ribilanciamento senza trim parziale

Innescato da una domanda diretta dell'utente sul perché le posizioni in
portafoglio mostrassero sempre "0 giorni" di detenzione, nonostante il track
record fosse presentato come continuo dal 2024. La causa era un bug reale, non
solo un problema di visualizzazione.

**Causa:** `update_portfolio` chiudeva e riapriva l'INTERA posizione ad ogni
cambio di peso target — anche un titolo detenuto ininterrottamente per mesi,
al primo ritocco del vol-targeting mensile (che cambia quasi ogni mese),
veniva formalmente "venduto" per intero e "ricomprato" per intero alla nuova
taglia. Due conseguenze reali, non solo estetiche:
- **Costi di transazione sovrastimati**: il costo veniva applicato sull'intera
  posizione chiusa PIÙ sull'intera posizione riaperta, invece che solo sulla
  differenza (delta) effettivamente negoziata — per un ritocco minimo del peso
  (es. 1,67%→1,22%) il costo veniva calcolato su ~2,89% di NAV invece che sullo
  0,45% realmente scambiato.
- **Tassazione anticipata rispetto al necessario**: chiudere per intero
  realizza la plusvalenza sull'intera posizione ogni mese, invece di
  realizzarla solo sulla quota effettivamente venduta in un trim parziale,
  lasciando il resto con costo e data di acquisto originali (rinvio della
  tassazione, il cuore dell'efficienza fiscale che questo intero documento
  persegue). **Era esattamente l'opposto dell'obiettivo dichiarato del
  progetto.**

Importante per la fiducia nei test precedenti: gli script di validazione
(`full_strategy_backtest.py` e derivati, usati per tutte le decisioni di
questa sessione — buffer, vincolo settoriale, dimensione basket) calcolavano
il costo correttamente **solo sul delta**, quindi le metriche di CAGR/Sharpe/
alpha già riportate in questo documento restano valide. Il bug era isolato al
codice di produzione (`backend.py.update_portfolio`) e allo script che
replica la stessa logica per il track record (`generate_v2_track_record.py`)
— cioè proprio nel codice che determina cosa succede ai tuoi soldi, non nei
test che hanno guidato le decisioni.

**Correzione:** il ribilanciamento ora negozia solo il delta tra peso attuale
e peso target:
- **Incremento di peso**: compra solo la quota aggiuntiva; il costo medio
  della posizione si aggiorna con la media ponderata classica (PMC) tra le
  azioni già detenute e quelle nuove — nessun evento tassabile (non è una
  vendita). `entry_date` resta quella originale.
- **Riduzione di peso**: vende solo la quota in eccesso; la plusvalenza si
  realizza SOLO su quella quota (`weight` nello storico = la parte venduta,
  non l'intera posizione); il resto mantiene costo e data d'ingresso
  originali — la tassazione sulla parte non venduta viene rinviata, non
  anticipata.
- **Uscita totale** (il titolo esce dal basket o la classe si disattiva):
  invariato, chiusura piena corretta perché è una vera liquidazione totale.

Verificato con un esempio a mano nei test (`test_backend.py`, 4 nuovi test,
18/18 totali passano): 500 azioni a costo $100 + acquisto di altre 250 a $120
→ costo medio corretto $106,67 (matematicamente identico al calcolo per
azioni reali).

**Effetto sul track record** (rigenerato una terza volta per coerenza):
eventi tassabili scesi da 363 a 229 nella finestra Feb 2024-oggi; NAV lordo
finale $122.761 → **$125.308**; le date di ingresso ora riflettono la
detenzione reale (es. IEF detenuto ininterrottamente dal 2024-08-05, non più
resettato ogni mese). L'alpha CAPM sulla stessa finestra breve resta non
significativo (2,07% vs 1,27% prima, p=0,67) — la correzione ha migliorato
l'efficienza fiscale e la precisione dei costi, non il problema strutturale
di beta basso in un bull market discusso in §8.7.

### 8.9 Giro di ottimizzazione "santo graal" — 6 test, 2 adottati

Su richiesta esplicita dell'utente ("ottimizza per alpha, NAV, CAGR, expectancy
a un rischio inferiore al benchmark, al netto della tassazione italiana"), un
brainstorm strutturato per categoria (n° posizioni, size, logiche, stop,
rotazioni, tempi, indicatori) seguito da 6 test validati con l'overlay macro
completo. Le categorie già coperte da test precedenti (n° posizioni, size,
stop, rotazioni) non sono state ripetute — vedi §8.1-8.8.

**Adottati:**

1. **Banda di isteresi adattiva alla volatilità** (`V2_HYSTERESIS_K = 0.5`,
   sostituisce il 2% fisso uguale per tutte le classi): BTC-USD e IEF hanno
   volatilità settimanale profondamente diverse — una banda unica scattava
   troppo spesso per IEF e troppo raramente per BTC. Banda = `k × volatilità
   settimanale realizzata (12w)` dell'asset, clippata tra 0,5% e 15%. Grid
   test su k da 0,15 a 2,0: plateau stabile da k=0,5 a k=2,0 (non un picco
   isolato). A k=0,5: Sharpe 1,39→1,45, Calmar 0,94→1,10, MaxDD 15,9%→14,0%,
   alpha CAPM 10,64%→11,17% (p=0,0001), meglio anche nel Bear 2022 (-5,6% vs
   -7,9%).
2. **Conferma multi-timeframe** (`V2_SHORT_MA_WEEKS = 20`): oltre alla MA 40
   settimane (isteresi), richiede che il prezzo sia anche sopra una MA più
   corta (20 settimane) — diverso dalla "doppia conferma trend+momentum" già
   respinta (quella univa due segnali diversi; qui sono due orizzonti dello
   stesso trend). Plateau reale tra 12 e 24 settimane, degrada oltre le 28
   quando le due medie convergono (comportamento sensato). A 20w: Sharpe
   1,39→1,49, Calmar 0,94→1,31, MaxDD 15,9%→12,3%, CAGR 14,92%→16,04%, e
   **meno** eventi/anno (23,4→21,4).

**Bug trovato durante l'implementazione:** la banda adattiva produceva un
`np.float64` invece di un float Python, con lo stato di isteresi che diventava
`np.bool_` — non un problema funzionale, ma avrebbe rotto la serializzazione
JSON dello stato in produzione (`json.dump` non serializza tipi numpy).
Corretto con cast espliciti; il bug è stato scoperto dai test automatici
(2 test falliti su un controllo di identità `is True`), non in produzione.

**Non adottati (con motivazione):**

3. **Tax-loss harvesting a fine dicembre**: vendita e riacquisto immediato dei
   titoli del basket in perdita non realizzata, per compensare l'anno fiscale
   corrente. Effetto nullo, verificato **sia prima che dopo** la correzione
   del riporto minusvalenze a 4 anni (§8.9-bis sotto): netA 12,34%→12,33%,
   differenza di $16 su $109k di tasse pagate. Il turnover naturale della
   strategia (108-114 eventi/anno sul basket) è già così alto che le
   minusvalenze si realizzano quasi sempre entro l'anno fiscale corrente —
   non c'è quasi nulla da "raccogliere" in più forzando la vendita a
   dicembre. Confermato con un controllo diretto: **zero minusvalenze sono
   mai scadute inutilizzate** sui 12 anni testati (né sul segnale macro né
   sul basket completo) — il limite dei 4 anni (art. 68 TUIR) non è mai
   vincolante per questo disegno, quindi non ha senso nemmeno ridurre
   ulteriormente il turnover per "rientrare" in quella finestra: è già
   ampiamente rispettata.
4. **Fattore Qualità** (filtro ROE minimo sopra la selezione per bassa
   volatilità): segnale positivo ma modesto con l'overlay completo (CAGR
   15,01%→15,19%, netA 12,67%→12,88%, Sharpe 1,41→1,44) — molto più
   contenuto del test isolato (CAGR 9,52%→11,14%). **Limite dichiarato non
   risolto**: usa il ROE ATTUALE applicato retroattivamente alle date
   storiche di selezione (nessuna fonte gratuita di fondamentali
   point-in-time in questo repository) — bias di look-ahead, il risultato è
   un limite superiore ottimistico, non una stima realistica. Non adottato:
   il segnale non è abbastanza forte da giustificare l'uso di dati che non
   erano disponibili alle date storiche.
5. **Momentum cross-sectional** (26 settimane, con lo stesso buffer-rank e
   vincolo settoriale del disegno deployato — un'implementazione più moderna
   di quanto l'audit originale v1 avesse mai testato): isolato mostra un
   drawdown quasi doppio (39,9% contro 21-27% del basket low-vol) — il
   classico "momentum crash" della letteratura. Con l'overlay macro completo
   il vol-targeting doma parte del rischio (MaxDD scende a 16,2%), e l'alpha
   non è più nullo come nell'audit v1 (11,04%, p=0,0002, comparabile
   all'11,31% del disegno deployato) — ma Calmar resta peggiore (0,95 vs
   1,13) e MaxDD resta peggiore (16,2% vs 13,3%). Non adottato: va contro il
   vincolo esplicito dell'utente di volatilità inferiore al benchmark; un
   rendimento netto marginalmente migliore (+0,41pp) non compensa un profilo
   di rischio peggiore quando il rischio più basso è un requisito, non solo
   una preferenza.

**Bug fiscale trovato e corretto (§8.9-bis):** durante la verifica del punto
3, un dubbio dell'utente sul limite dei 4-5 anni ha fatto emergere che il
`TaxLedger` (usato in *tutti* gli script di backtest di questo progetto)
resettava il pool minusvalenze a zero ogni fine anno **indipendentemente dal
segno** — scartando per sempre le perdite non compensate nello stesso anno,
invece di riportarle fino a 4 anni come previsto dall'art. 68 TUIR. Era una
semplificazione dichiarata nel codice ("compensabili nello stesso anno", non
un bug nascosto), ma **sottostimava** il rendimento netto (non lo
sovrastimava): l'utente aveva più occasioni reali di compensare di quante il
modello gliene concedesse. Corretto con una coda FIFO che scade dopo 4 anni
(`multi_asset_lab.TaxLedger`, 3 nuovi test in `tests/test_tax_carryforward.py`,
tutti passano). Effetto sul disegno deployato: netA 12,61%→12,64% (piccolo,
la strategia macro ha poche annate in perdita netta).

Track record Feb 2024-oggi (§8.6) rigenerato una quarta volta con entrambi i
miglioramenti adottati attivi, per coerenza piena: NAV finale $125.308 →
**$127.112**, eventi tassabili 229 → **193**.

### 8.10 Bug di produzione trovato e corretto — il peso non seguiva la deriva di prezzo

Innescato da una domanda diretta dell'utente ("questi ribilanciamenti non
tagliano la coda grassa dei guadagni?"). Risposta in due parti, una
rassicurante e una no.

**Parte rassicurante:** il meccanismo di trim confronta il nuovo peso target
con il vecchio peso target — non con il vero peso attuale — quindi un titolo
che sale non viene tagliato per pura rivalutazione di prezzo tra un
ribilanciamento e l'altro. La "coda grassa" non viene sistematicamente
recisa.

**Parte non rassicurante, un bug reale:** `pos["weight"]` restava congelato
al valore impostato all'ultimo ribilanciamento, **mai aggiornato per
riflettere la deriva di prezzo** nel frattempo. Due conseguenze concrete:
1. Il compounding del NAV (`mark_to_market_and_compound_nav`) pesava OGNI
   posizione al suo peso congelato per l'intero periodo fino al ribilanciamento
   successivo, invece che al suo peso vero (crescente per un vincitore,
   calante per un perdente) — sottostimava sistematicamente il contributo dei
   vincitori al NAV composto, l'esatto contrario della paura dell'utente ma
   comunque un errore reale. Verificato a mano: due posizioni al 50%, una
   guadagna il 10% per 2 giorni consecutivi, l'altra piatta → NAV vero
   $110,50, NAV con il bug $110,25.
2. Il "Peso (%)" mostrato in dashboard era il target dell'ultimo
   ribilanciamento, non il peso vero attuale — poteva discostarsi in modo
   crescente dalla realtà quanto più tempo passava dall'ultimo
   ribilanciamento.

**Correzione:** `mark_to_market_and_compound_nav` ora aggiorna `weight` insieme
al NAV, con la stessa formula usata per il NAV stesso (nuovo peso = vecchio
peso × rendimento della posizione / rendimento del portafoglio) —
matematicamente equivalente al tracking per azioni reali (verificato nei
test), senza bisogno di introdurre un nuovo campo "shares". Come effetto
collaterale, questo rende anche `update_portfolio` (che legge `weight` per
decidere trim/incrementi) piu' preciso, perche' ora confronta il target nuovo
con il peso VERO attuale, non con un target congelato. 2 nuovi test in
`test_backend.py` (21/21 totali passano). Track record (§8.6) rigenerato una
quinta volta: NAV $127.112 → **$127.479**.

### 8.11 Gap di chiarezza operativa in dashboard — corretto

Prima parte della stessa domanda dell'utente: non era chiaro in dashboard
come gestire i ribilanciamenti mensili. Verificato: il messaggio Telegram
aveva gia' una sezione "🚀 Ordini da eseguire oggi" con il dettaglio delle
operazioni, ma quella lista non veniva mai salvata su disco — se l'utente
perdeva la notifica, non c'era modo di recuperarla dalla dashboard senza
scorrere l'intero storico operazioni. Corretto: `backend.py` ora persiste
`last_action_log`/`last_action_date` in `portfolio.json` ad ogni decisione,
e `app.py` mostra un riquadro dedicato in cima al Tab Portafoglio ("Ultimo
ribilanciamento — operazioni da replicare sul tuo broker") quando presente.

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

---

## 10. TODO — proposte UI/UX e ricerca strategia

Aggiornato 2026-08-28. Tutti i punti "[UX]" e la correzione "[Correttezza]"
sono stati **implementati** nella stessa sessione in cui erano stati
proposti (vedi §11 per il dettaglio delle modifiche). Resta aperto solo il
punto di ricerca strategica.

1. ~~**[Correttezza] Etichetta "Rendimento Netto" fuorviante.**~~ **FATTO** —
   vedi §11.
2. **[Ricerca strategia — APERTO] Universo azionario europeo aggiuntivo.**
   Testare se un basket low-vol europeo (stesso disegno di quello USA,
   rotazione trimestrale) migliora Sharpe/alpha. L'ipotesi è che il
   beneficio non stia tanto nella diversificazione di stock-picking (basket
   low-vol EU/USA storicamente correlati ~0.8+) quanto nella possibilità che
   il **segnale di timing per regione diverga** (es. EU "spenta" mentre USA
   è "accesa" o viceversa — 2022 crisi energetica EU, 2011 crisi debito
   sovrano EU). Fiscalmente neutro (azioni EU singole restano "redditi
   diversi" come quelle USA). Costo: raddoppia il sourcing dati
   (fondamentali/settori EU più difficili da reperire gratis via Yahoo) e
   consuma un altro test del "budget di prove" anti-overfitting.
   Aspettativa realistica: miglioramento modesto, non trasformativo, perché
   la decorrelazione principale la fa già l'overlay multi-asset
   (SPY/IEF/GLD/BTC). Da validare con un backtest dedicato prima di
   decidere se implementare.
3. ~~**[UX] Callout azioni fuori dalle tab.**~~ **FATTO** — vedi §11.
4. ~~**[UX] Capitale/valuta non persistenti.**~~ **FATTO** — vedi §11.
5. ~~**[UX] Radar isolato in tab separata.**~~ **FATTO** — vedi §11.
6. ~~**[UX] Tabelle Azioni/Crypto troppo dense.**~~ **FATTO** — vedi §11.
7. ~~**[UX] Card macro-engine ridondanti.**~~ **FATTO** — vedi §11.
8. ~~**[UX] Copia ordini manuale.**~~ **FATTO** — vedi §11.
9. ~~**[Nice-to-have] CAGR mancante.**~~ **FATTO** — vedi §11.

## 11. Implementazione revisione UI/UX (2026-08-28)

Implementati tutti gli 8 punti UI/UX di §10 in `app.py` (il punto 2, ricerca
di strategia, resta escluso di proposito — non è una modifica UI):

- **Etichetta corretta**: la card KPI in Tab Metriche ora si chiama
  "Rendimento Lordo" e riporta in sottotitolo una stima netto-teorica
  (26% solo sulla quota di guadagno, se realizzato oggi — stima
  semplificata, non modella il riporto perdite a 4 anni di §8.9).
- **Callout ribilanciamento** spostato sopra le tab (visibile sempre) e reso
  copiabile con `st.code(...)` (icona copia nativa Streamlit, nessun
  componente custom).
- **Capitale/valuta persistenti** via `st.query_params` — sopravvivono al
  reload della pagina (URL bookmarkabile).
- **Radar** non è più una tab separata: è un expander collassato in fondo
  al Tab Portafoglio ("📡 Radar Rotazione — basket in arrivo"). Le tab sono
  ora 3 (Portafoglio, Metriche, Guida) invece di 4.
- **Tabelle Azioni/Crypto**: vista compatta di default (Titolo, Peso %,
  Rendimento %, Valore) con toggle "🔍 Mostra dettagli esecuzione" per le
  colonne di dettaglio (Quote, Data Ingresso, prezzi ingresso/uscita) —
  nessuna colonna è stata eliminata, solo nascosta dietro un controllo.
- **Card macro-engine**: le 5 card bordate sostituite da una "pill bar"
  compatta; l'informazione "attiva dal ..." è stata spostata nel tooltip
  (`title=`) di ogni pill. **Rivisto in §12: un tooltip via `title=` non è
  raggiungibile su dispositivi touch (niente hover) — per chi usa la
  dashboard da mobile l'informazione è di fatto persa, non solo
  nascosta.** Correzione proposta in §12.1.
- **CAGR annualizzato** aggiunto come nuova card KPI in Tab Metriche,
  accanto al rendimento cumulato (non lo sostituisce).

**Verifica**: sintassi validata (`py_compile`), rendering testato via
`streamlit.testing.v1.AppTest` in bare mode con `urllib.request.urlopen`
mockato per forzare il fallback ai file JSON locali (stesso pattern usato
nel resto della sessione) — nessuna eccezione su run pulito, 3 tab
rilevate, toggle/expander presenti, `st.code` presente quando
`last_action_log` è popolato (verificato iniettando temporaneamente il
campo in una copia di `portfolio.json`, poi ripristinato il file originale
intatto). La logica di filtro colonne compatta/estesa è stata verificata
anche fuori da Streamlit, direttamente su pandas con le 16 posizioni reali
di `portfolio.json`, per entrambi i rami (compatto ed esteso) — nessun
`KeyError`.

## 12. TODO — seconda ondata (IMPLEMENTATO, vedi §14)

Dalla discussione su come mostrare le 5 classi di asset (Monetario,
Obbligazioni, Azionario, Bitcoin, Oro) dopo la rimozione del basket crypto
multi-asset (v2 usa solo BTC-USD, nessuna rotazione). Ordine di importanza:

1. **[Correzione — regressione] Data "attiva dal" invisibile su mobile.**
   La pill bar di §11 mette la data del segnale (`title=` HTML) in un
   tooltip raggiungibile solo con l'hover del mouse — su touch/mobile non
   esiste hover, quindi l'informazione non è "nascosta ma recuperabile", è
   di fatto irraggiungibile per chi apre la dashboard da telefono. Da
   correggere mostrando la data in modo sempre visibile (es. testo
   compatto dentro la pill, non più solo nel tooltip) invece di affidarsi a
   un'interazione hover-only.
2. **Bitcoin da tabella a card.** La sezione "Crypto in Portafoglio" è oggi
   una tabella con una riga sola (residuo del vecchio basket multi-crypto
   v1) — va convertita in una card come Oro/Obbligazioni/Monetario, dato
   che BTC non ruota mai (nessuna vera "lista" da tabellare).
3. **Parità informativa nelle card asset singoli.** Le card di
   Oro/Obbligazioni/Bitcoin oggi mostrano solo importo e rendimento %/$.
   Vanno arricchite con Peso % esplicito, Data Ingresso (gg) e Prezzo
   Ingresso → Attuale — le stesse informazioni già disponibili per le
   azioni in tabella, così nessuna asset class perde dettaglio rispetto
   alle altre.
4. **Radar: solo Azionario, niente Bitcoin.** Il Radar esiste per mostrare
   candidati di rotazione trimestrale — per Bitcoin non esiste candidacy
   (asset singolo, mai sostituito, solo on/off per segnale macro, già
   coperto da pill bar + card portafoglio). Va tolto dal Radar, che resta
   solo la tabella Azionario (⭐ in portafoglio / 🆕 candidati) — stessa
   tabella oggi duplicata, stesso principio "tabella solo per basket con
   vera rotazione" applicato in modo coerente sia a Portafoglio sia a
   Radar.
5. **Treemap come visual primario in Tab Portafoglio.** `go.Treemap`
   (Plotly, già in uso in app.py — nessuna nuova dipendenza): blocco
   esterno = classe di asset, dimensione = peso, colore = rendimento
   (verde/rosso); il blocco Azionario si apre mostrando i singoli titoli
   del basket con la stessa logica dimensione/colore. Preferito a un
   grafico a torta perché mostra allocazione E performance insieme (la
   torta mostra solo l'allocazione statica). Da posizionare in cima al Tab
   Portafoglio come vista d'insieme, con card/tabella sotto per il
   dettaglio numerico esatto.
6. **Cockpit: anello di progresso + durata segnale.** Ogni pill della
   macro-engine status bar guadagna un anello di progresso attorno
   all'icona (riempimento = peso % della classe, colore = stato); la data
   "attivo dal ..." diventa testo sempre visibile (non più solo tooltip,
   corregge il punto 1). Opzionale: una barra di durata sottile sotto la
   pill (scala 0-26 settimane) per un colpo d'occhio su "flip fresco vs
   stato consolidato".
7. **Metriche: grafico underwater (drawdown nel tempo).** Il Max Drawdown
   oggi è solo un numero in una card KPI — aggiungere un'area rossa sotto
   la curva equity principale che mostra lo scostamento % dal massimo
   storico nel tempo (standard nei tearsheet istituzionali): quando è
   successo, quanto in profondità, quanto per recuperare. Opzionale/da
   valutare: sostituire le candele giapponesi settimanali della curva
   equity con un'area/linea (più convenzionale per un NAV multi-asset
   ribilanciato, le candele sono più adatte a uno strumento tradabile con
   OHLC reale).

## 13. Direzione visiva istituzionale ("Instrument Panel") — proposta (IMPLEMENTATA, vedi §14)

Valutazione richiesta esplicitamente dall'utente: la UI attuale, per quanto
già rivista per leanness (§10-§12), ha ancora una "veste grafica" da app
fintech consumer, non da terminale istituzionale. Cinque problemi concreti,
individuabili nel codice attuale di `app.py`:

1. **Emoji come iconografia funzionale.** 📈🪙🥇🛡️💵🔔📡📖🎯⚖️💎🏆🛑⏱️💡⚙️ compaiono
   ovunque — su ogni card, ogni intestazione, ogni badge. È il singolo
   segnale più forte che allontana il prodotto da un terminale
   istituzionale (Bloomberg, FactSet, Addepar, strumenti interni hedge
   fund non usano MAI emoji come iconografia): comunicano "app consumer
   amichevole", non "strumento professionale".
2. **Colore usato per decorare, non per significare.** Ogni asset class ha
   oggi un proprio colore identitario fisso (Azioni verde/rosso per stato,
   Obbligazioni viola, Oro ambra, Monetario blu) — il colore identifica la
   *categoria* invece di essere riservato al *significato* (positivo/
   negativo, attivo/attenzione). Un terminale istituzionale usa quasi
   sempre una palette neutra (grafite/carbone) con un solo accento di
   marca, e riserva verde/rosso esclusivamente al segno del P&L.
3. **Chrome eccessivo — box dentro box.** Praticamente ogni elemento (pill
   macro, card asset, card KPI, mini-stat, box disclaimer) è un riquadro
   con bordo + ombra + angoli arrotondati proprio. Impilati, creano
   affaticamento visivo anche quando i contenuti sono già leggibili — va
   contro l'obiettivo "basso carico mentale" già perseguito in §10.
4. **Ridondanza di stato.** Un singolo stato (es. "classe attiva") viene
   comunicato tre volte insieme: pallino verde + bordo verde + badge
   testuale "🟢 ATTIVO". Un solo segnale, ben scelto, basta.
5. **Buona base tipografica da preservare.** La coppia Inter/JetBrains Mono
   con tabular-nums per le cifre è già corretta e coerente con lo standard
   istituzionale — nessuna modifica necessaria qui, va solo sfruttata
   meglio (più aria intorno ai numeri-chiave, gerarchia di peso più
   marcata).

**Proposta di direzione — "Instrument Panel":**

- **Palette**: base quasi monocromatica (grafite/carbone, leggero bias
  freddo) + un solo accento di marca riservato a elementi interattivi/di
  brand (tab attiva, link); verde/rosso riservati ESCLUSIVAMENTE al segno
  del P&L, mai per identificare una categoria. Le classi di asset si
  distinguono per etichetta + posizione, non per un colore-bordo dedicato
  a testa.
- **Iconografia**: sostituire le emoji con un piccolo set di glifi lineari
  minimali (SVG inline, nessuna nuova dipendenza) solo dove l'icona aiuta
  davvero la scansione (le 5 classi nel cockpit); ovunque altro (card KPI,
  intestazioni tabella, badge) l'etichetta tipografica sostituisce
  l'icona — molti terminali istituzionali (Bloomberg, FactSet, Addepar)
  non usano icone decorative nelle tabelle/card dati, l'etichetta stessa
  è sufficiente.
- **Chrome**: passare da "ogni elemento è una card con bordo+ombra" a
  sezioni piatte separate da hairline (1px) e spazio bianco; riservare il
  trattamento a card solo al raggruppamento più esterno (es. l'intera riga
  KPI come un'unica striscia con divisori interni, non 6 box separati con
  ombra propria).
- **Ridondanza**: un solo segnale di stato per fatto (colore O etichetta,
  non entrambi più un pallino) — libera spazio e riduce il rumore.
- **Grafici**: disciplina data-ink (Tufte) — griglie sottili o assenti,
  legenda solo se non ridondante, palette desaturata per il treemap
  (niente colori neon), linea benchmark grigio tratteggiato quieto contro
  un solo accento per la curva strategia (schema già vicino a questo
  nell'equity chart attuale, da estendere a treemap e underwater chart).

Questa direzione non sostituisce i contenuti/le informazioni proposte in
§10-§12 (treemap, card arricchite, anello di progresso, underwater chart):
li reinterpreta nel nuovo linguaggio visivo — es. l'anello di progresso del
punto 12.6 va colorato secondo la nuova regola (verde/rosso solo per
P&L, non un colore identitario per classe), le card diventano più piatte,
le emoji nei loro contenuti vanno sostituite dai glifi lineari.

## 14. Implementazione — ondata 2 + direzione visiva istituzionale (2026-08-28)

`app.py` riscritto per intero secondo §12 e §13. Scelte concrete:

- **Design tokens centralizzati** in cima al file: `POS`/`NEG` (verde/rosso,
  usati SOLO per il segno del P&L), `ACCENT` (blu, solo elementi
  interattivi/di marca), `SURFACE`/`BORDER` (superficie e bordo neutri
  unici, riusati ovunque al posto dei colori per-categoria). Helper
  riutilizzabili: `flat_card()`, `monogram()`, `ring_svg()`.
- **Emoji rimosse** da ogni elemento funzionale (header, cockpit, card,
  tabelle, KPI, Guida). Le uniche eccezioni: il colore di marca reale di
  Telegram sul link esterno (#0088cc, non è un'emoji ma un colore di
  marca legittimo di terze parti) e la favicon di fallback del browser
  (`st.set_page_config(page_icon=...)`, fuori dalla superficie applicativa).
- **Iconografia sostituita da monogrammi tipografici**: EQ (Azioni), ₿
  (Bitcoin — carattere Unicode reale, non emoji), AU (Oro, simbolo
  chimico), FI (Obbligazioni), $ (Monetario), AE (logo di fallback). Nessuna
  nuova dipendenza, nessun set di icone SVG da mantenere.
- **Cockpit**: pill sostituite da anelli di progresso (`ring_svg`) — il
  riempimento è il peso %, il colore è lo stato (verde=attiva, grigio
  neutro=in pausa — **non rosso**: una classe in pausa è il sistema che
  evita correttamente un downtrend, non una notizia negativa, quindi il
  rosso resta riservato esclusivamente a P&L negativo reale). La data
  "attiva dal ..." è ora testo sempre visibile, non più solo in tooltip
  (corregge la regressione di §12.1).
- **Bitcoin**: da tabella a card (`instrument_card`), arricchita con
  Peso %, Data Ingresso, Prezzo Ingresso → Attuale — stessa funzione
  riusata anche per Oro e Obbligazioni, garantendo parità informativa
  reale (stesso codice, non solo stesso aspetto).
- **Radar**: ridotto alla sola tabella Azionario. Bitcoin rimosso (nessuna
  candidacy di rotazione per un asset singolo). Badge ⭐/🆕 sostituiti da
  una colonna "Stato" testuale (NUOVO in accento blu, altrimenti vuota) —
  un solo segnale per fatto invece di pallino+bordo+badge ridondanti.
- **Treemap** in cima al Tab Portafoglio (`go.Treemap`): dimensione = peso
  di strategia (indipendente dal capitale inserito, quindi visibile prima
  ancora di quel campo), colore = rendimento su scala rosso-grigio-verde
  desaturata (`#7F1D1D`/`#374151`/`#065F46`, non i colori neon di default
  di Plotly), drill-down nativo sul basket azionario.
- **Curva equity**: da candela giapponese settimanale ad area/linea
  (decisione presa in sede di implementazione, era segnata come
  "opzionale/da valutare" in §12.7) — una candela OHLC comunica un range
  intra-periodo che per un NAV multi-asset ribilanciato è sintetico, non
  un vero prezzo tradabile; area/linea è lo standard nei tearsheet
  istituzionali ed è più leggibile a confronto con il benchmark.
- **Underwater chart** (drawdown nel tempo) aggiunto sotto la curva
  equity, risoluzione giornaliera (non settimanale, per non attenuare la
  vera profondità intra-settimanale del drawdown) filtrata sullo stesso
  intervallo del periodo selezionato.
- **KPI cards**: superficie neutra uniforme per tutte e 6 (era: bordo
  colorato diverso per ciascuna, puramente decorativo). Rimossi i badge
  "🟢 POSITIVO"/"🔴 NEGATIVO" su Rendimento Lordo e CAGR perché
  ridondanti col colore già presente sul valore; mantenuti i badge
  qualitativi (ECCELLENTE/STABILE, PROTETTO/ATTENZIONE, ecc.) perché
  aggiungono un giudizio soglia, non ripetono il segno.
- **Guida**: card uniformate alla stessa superficie neutra, badge
  per-classe (era colore diverso per categoria) ora un unico grigio
  neutro con testo maiuscolo.

**Verifica**: `py_compile` pulito; `streamlit.testing.v1.AppTest` in bare
mode (stesso mock di `urllib.request.urlopen` usato nel resto della
sessione) eseguito in tre scenari — (1) dati reali di produzione (16
azioni, Oro/Obbligazioni/Bitcoin in pausa — esercita i rami "non
allocato" delle card e l'assenza dei relativi nodi nel treemap), (2) uno
scenario sintetico con Oro/Obbligazioni/Bitcoin iniettati attivi in copie
temporanee di `portfolio.json`/`apex_data.json` (poi ripristinati e
verificati byte-identici all'originale) per esercitare i rami "attivo"
delle card e del treemap, (3) `last_action_log` popolato per verificare
`st.code` — nessuna eccezione in nessuno dei tre scenari. Suite
`test_backend.py`/`test_apex_v2_engine.py` rieseguita: 21/21 verdi (non
toccata da questa modifica, solo verifica di non regressione). La
logica di filtro colonne compatta/estesa della tabella Azionario è stata
inoltre validata direttamente su pandas con i dati reali di
`portfolio.json`, per entrambi i rami — nessun `KeyError`.

## 15. Due bug di leggibilità in §14 — corretti (2026-08-28)

Segnalati dall'utente osservando la dashboard reale (dati live del giorno:
Azioni 19.29% attiva, Bitcoin 19.29% attivo, Monetario 61.41%, Oro e
Obbligazioni 0% in pausa).

**1. Anello del cockpit — verde invisibile.** Il riempimento dell'anello era
proporzionale al peso % (via `stroke-dasharray`/`stroke-dashoffset`). Con un
peso del 19% l'arco verde copriva solo ~19% della circonferenza — troppo
sottile su un anello da 30px per essere notato a colpo d'occhio,
specialmente su sfondo scuro. La dimostrazione confermava il calcolo
corretto (`stroke-dashoffset` giusto, colore `#10B981` giusto), ma il
risultato percettivo falliva l'unico scopo del cockpit: far vedere subito
se una classe è attiva. **Corretto**: `ring_svg()` ora disegna sempre un
cerchio intero (nessun `stroke-dasharray`), il colore da solo è il segnale
di stato — il peso % resta leggibile, ma come cifra accanto all'anello, non
codificato nel disegno. Rimossa anche la dipendenza da `math` (non più
necessaria).

**2. Treemap — "nessun dato su Azioni", "0% su Bitcoin".** Due problemi
distinti, stessa causa: il treemap aveva un drill-down per singolo titolo
(`AZ::<ticker>`, 15 figli sotto il nodo Azionario), e mostrava solo il
rendimento % come testo di ogni riquadro (mai il peso %). Con Azionario e
Bitcoin allo stesso peso complessivo (19.29% ciascuno) ma Azionario diviso
in 15 sotto-celle da ~1.3% l'una, quelle sotto-celle erano troppo piccole
per mostrare testo leggibile — Plotly nasconde automaticamente le etichette
che non entrano nel riquadro, quindi il blocco Azionario appariva vuoto.
Bitcoin, appena entrato in portafoglio con `entry_price == current_price`,
mostrava "+0.00%" (il suo rendimento, correttamente zero) ma essendo
l'unico numero visibile nel riquadro poteva essere letto come "0% di
peso" invece che "0% di rendimento". **Corretto**: rimosso il drill-down
per titolo (il dettaglio per titolo è già nella tabella Azionario subito
sotto, non serve duplicarlo in un treemap troppo affollato per mostrarlo
bene); ogni riquadro ora mostra esplicitamente "peso% · rendimento%"
(es. "19.3% · +0.00%"), eliminando l'ambiguità.

Verificato con `py_compile`, `AppTest` sui dati reali di produzione, e
ispezione diretta dell'HTML/dati generati (SVG dell'anello, valori/testi
del treemap) per i valori attuali (Azioni 19.29%, Bitcoin 19.29%,
Monetario 61.41%). 21/21 test engine invariati. Aggiornato anche l'artifact
di spiegazione del cockpit pubblicato in chat, che nel frattempo usava
`stroke="var(--pos)"` dentro un attributo SVG — non un bug della dashboard
reale (che usa colori esadecimali letterali, non variabili CSS), ma un
rischio di affidabilità cross-browser evitabile, sistemato per coerenza.

## 16. Audit completo testi + coerenza dati col motore reale (2026-08-28)

Su richiesta esplicita dell'utente: rilettura di ogni stringa visibile in
`app.py` verificata contro il comportamento REALE di `backend.py` e
`apex_v2_engine.py` (non contro quello che si presumeva fosse), più
eliminazione di ridondanze e testo obsoleto.

**Errori fattuali trovati e corretti (i più rilevanti):**

1. **Cadenza operativa completamente sbagliata in Guida.** Il testo
   descriveva un "controllo settimanale" con aggiornamento di "livelli di
   protezione" (stop-loss) ogni venerdì. Verificato in `backend.py`
   (`is_rebalancing_schedule()`, `should_decide`): non esiste alcun
   controllo settimanale distinto — le uniche decisioni di trading
   avvengono **una volta al mese**, l'ultimo venerdì (`is_rotation`), con
   la rotazione del basket azionario come sottoinsieme di quei giorni
   quando cade anche a fine trimestre. Il resto della settimana (Lun-Ven)
   il motore aggiorna solo prezzi/NAV (`mark_to_market_and_compound_nav`),
   nessun trade. E lo stop-loss per singola posizione **non esiste in v2**
   — la card "Vol-Targeting" nella stessa tab lo dichiarava già
   correttamente ("non esiste uno stop-loss per singola posizione: testato
   esplicitamente e respinto"), quindi il vecchio testo "Regole Operative"
   si contraddiceva con un'altra card della stessa pagina. Riscritto come
   "Cadenza Operativa" con 3 voci verificate contro il codice: giornaliero
   (prezzi/NAV, nessuna decisione), ultimo venerdì del mese (segnale +
   vol-target), ultimo venerdì del trimestre (rotazione basket).
2. **Riferimento a sezione sbagliata**: la card Vol-Targeting rimandava a
   "APEX_V2_SPEC.md §4" (che è in realtà "Selezione del basket azionario")
   invece di §3 ("Vol-targeting di portafoglio"). Corretto.
3. **Descrizione del segnale incompleta**: il testo diceva "media mobile a
   40 settimane" senza menzionare che dal §8.9 il segnale richiede la
   CONFERMA di MA40w **e** MA20w insieme (multi-timeframe, verificato in
   `apex_v2_engine.py` — `V2_SHORT_MA_WEEKS=20`). Corretto.
4. **Cap settore mancante**: `V2_MAX_PER_SECTOR=2` è una regola reale di
   costruzione del basket (mai più di 2 titoli per settore) non
   menzionata da nessuna parte in Guida. Aggiunta alla card "Selezione del
   Basket Azionario".
5. **Data del track record in testo fisso**: "(Feb 2024 – Ago 2026)" era
   una stringa statica nel banner di Tab Metriche — sarebbe rimasta
   scorretta a ogni mese che passa. Ora calcolata dinamicamente dal primo/
   ultimo giorno reale di `equity.json`.
6. **Timestamp di sync in inglese in una UI italiana**: il backend genera
   `"27 Aug 2026, 23:42 (UTC)"` (mese in inglese, locale del server) e
   veniva mostrato cosi' com'era nell'header. Aggiunto
   `format_sync_timestamp_italian()` per convertirlo coerentemente col
   resto della UI ("27 Ago 2026, 23:42 UTC").
7. **"Motore Attivo" era decorazione statica, sempre verde**, senza alcun
   controllo reale dietro. Ora calcolato dall'età del timestamp di sync:
   oltre 4 giorni senza aggiornamento (copre un weekend + un giorno di
   margine) mostra "Ricalcolo in ritardo (Ng)" invece di affermare uno
   stato che nessuno stava verificando.
8. **Testo Telegram e card fallback** ripulite dallo stesso riferimento a
   "livelli di protezione" inesistenti.

**Ridondanze valutate e non rimosse (motivate):** il peso % di ogni classe
compare sia nel cockpit (sopra le tab, sempre visibile) sia nel treemap
(dentro Tab Portafoglio) — non unificato perché il cockpit ha uno scopo
diverso (stato visibile da qualsiasi tab, senza dover entrare in
Portafoglio) rispetto al treemap (composizione + performance quando sei
già in quella tab); è la stessa cifra vista da due schermate diverse, non
un doppione nello stesso schermo. La card "Rendimento Galleggiante"
(aggregato) e le card per singolo asset (dettaglio) restano entrambe per
lo stesso motivo — sintesi vs dettaglio, non lo stesso livello di
informazione ripetuto due volte.

**Codice**: rimossa una chiamata duplicata a `load_equity()` (stessa
funzione invocata due volte nello stesso run di `tab_perf`, innocua per la
cache ma inutile). Sostituito `datetime.datetime.utcnow()` (deprecato) con
l'equivalente timezone-aware.

**Verifica**: `py_compile` pulito, nessun warning di deprecazione residuo,
`AppTest` su dati reali senza eccezioni, timestamp/date-range verificati
con un piccolo script standalone contro `apex_data.json`/`equity.json`
reali (formattazione italiana corretta, 0 giorni di ritardo rilevati
correttamente su dato fresco). 21/21 test engine invariati.

## 17. Anello cockpit ancora invisibile dopo §15 + heatmap per titolo (2026-08-28)

**Anello ancora non visibile.** Dopo la correzione di §15 (cerchio SVG
pieno invece di arco parziale), l'utente ha segnalato che l'anello
continuava a non vedersi. Il markup generato era corretto (verificato
stampando l'HTML: `stroke="#10B981"` su un cerchio completo), ma restava
un SVG con un elemento di testo sovrapposto in posizione assoluta
(`position:absolute; inset:0`) dentro un contenitore `position:relative` —
una struttura più fragile del necessario e più difficile da diagnosticare
senza poter vedere il rendering effettivo. **Sostituito con l'implementazione
più semplice possibile**: un singolo `<div>` con bordo circolare via CSS
(`border-radius:50%; border:3px solid <colore>`), sigla centrata dentro con
flexbox — nessun SVG, nessun overlay assoluto, un solo elemento invece di
due sovrapposti. `ring_svg()` rinominata `ring_badge()` per riflettere che
ora produce l'intera pillola (bordo colorato + sigla), non solo l'anello.
Stesso identico principio (colore = stato, non riempimento = peso%), solo
implementazione più robusta. Aggiornato anche l'artifact di spiegazione in
chat con lo stesso markup, in caso l'utente stesse guardando quello.

**Heatmap per titolo eliminata in §15 — spiegazione e correzione.** In §15
il drill-down per singolo titolo era stato tolto dal treemap principale
perché i 15 titoli, come sotto-celle di un unico riquadro "Azionario"
grande quanto Bitcoin da solo (~19% del portafoglio ciascuno), diventavano
troppo piccoli per un'etichetta leggibile — non un problema di dati, ma di
spazio: 15 fette dentro il 19% dell'area totale sono per forza minuscole.
L'utente ha chiesto di riavere la vista per titolo. **Corretto senza
reintrodurre il bug**: aggiunto un secondo treemap, dedicato, subito sopra
la tabella "Basket Azionario" — le stesse 15 posizioni, ma come UNICO
contenuto del proprio grafico invece che sotto-celle di un riquadro
condiviso con altre 4 classi. Occupando tutta l'area disponibile invece di
un ritaglio, ogni titolo torna leggibile. Il treemap in cima alla pagina
resta a 5 riquadri (una per classe, senza drill-down) per la vista
d'insieme; questo nuovo treemap è il dettaglio, esattamente dove serve
(accanto alla tabella che già mostra gli stessi 15 titoli in forma
numerica).

**Verifica**: `py_compile` pulito, `AppTest` su dati reali (15 posizioni
azionarie) senza eccezioni — esercita sia il nuovo `ring_badge()` sia il
nuovo treemap per titolo. 21/21 test engine invariati.
