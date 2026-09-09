# Kelly Stack — Specifica Operativa (Terzo Pilastro: Ricchezza Generazionale)

Documento di riferimento per **Kelly Stack**, terzo motore quantitativo del progetto,
indipendente da Apex Engine (timing tattico, leva zero) e Convex Stack (accumulo
sistematico a leva fissa 122.5%). Segue la stessa disciplina di `APEX_V2_SPEC.md`:
ogni parametro ha una giustificazione esplicita, i limiti dichiarati sono onesti, e
niente viene presentato come "pronto per capitale reale" finché non è validato con
backtest point-in-time e test di robustezza — esattamente lo standard che ha già
prodotto due bug di produzione corretti in Apex (§8.5, §8.8 di `APEX_V2_SPEC.md`).

**Stato di questo documento: DESIGN, parzialmente validato con dati reali.** Vedi §7.

**Obiettivo numerico riconciliato (dopo la validazione di §7.1):** l'obiettivo
iniziale ("100k→2M in 10 anni, CAGR 30-35%") non è sostenuto da nessun
walk-forward reale a nessuna combinazione di parametri provata — vedi §7.1.
Con un versamento mensile reale di 600€ e i CAGR netti onesti osservati
(12.9%-17.1% a seconda del campione storico usato), la proiezione a 10 anni è
**~476k-659k**, non 2M. Su richiesta esplicita dell'utente, che ha scelto il
percorso a rischio controllato (non alzare i governatori oltre quanto validato
in §3) invece di inseguire il target originale con più leva, l'obiettivo
numerico è riconciliato così: **~2M resta un traguardo plausibile su un
orizzonte di ~18-22 anni** (899k-2.45M a 18 anni, a seconda del campione,
secondo lo stesso calcolo), oppure **~500-700k rimane il traguardo realistico
a 10 anni** mantenendo la stessa disciplina di rischio. Nessuna modifica ai
parametri di rischio (`KELLY_FRACTION`, `MAX_GROSS_LEVERAGE`,
`MAX_SLEEVE_WEIGHT`) è stata fatta per inseguire il numero originale — sarebbe
stato l'errore di data-snooping che questo intero documento esiste per evitare.

**Revisione del mandato (dopo la prima stesura):** su richiesta esplicita
dell'utente, l'universo di strumenti non è più vincolato ai 5 asset di Convex
(§4) e sono ammesse strategie diverse dalla pura allocazione beta, incluso
long/short — ciò che conta è CAGR/alpha/expectancy. Restano non negoziabili i
due vincoli architetturali che servono a mantenere sotto controllo il rischio
di rovina anche con un universo più ampio (§4): mai margine personale, mai ETP
a leva/inversi a reset giornaliero come posizione di lungo periodo.

---

## 0. Obiettivo (definizione del problema, non solo il nome)

L'obiettivo dichiarato — "ricchezza estrema, con la probabilità più alta possibile,
tenendo sotto controllo il rischio di rovina" — è precisamente il problema che il
**criterio di Kelly** (Kelly, 1956; formalizzato per portafogli multi-asset da
Merton nel problema di allocazione a utilità logaritmica) risolve, e nessun altro
criterio comune (max Sharpe, max rendimento atteso, risk parity) risolve
correttamente:

- **Max rendimento atteso semplice** ignora la varianza: su orizzonte lungo, quello
  che compone è la crescita **geometrica**, non l'attesa aritmetica. Una scommessa
  con rendimento atteso positivo ma varianza sufficiente può avere crescita
  geometrica attesa **negativa** (drag da volatilità) — rovina quasi certa a
  ripetizione, nonostante l'attesa per singolo periodo sia positiva. Esempio
  canonico: leva 2x su una scommessa equa ±50% ha E[R]=0% ma E[log(1+R)] < 0.
- **Max Sharpe** massimizza rendimento per unità di rischio a QUALSIASI livello di
  leva — non dice quanta leva applicare. Applicato senza un vincolo di crescita
  geometrica, porta a sovra-levereggiare fino alla rovina.
- **Risk parity ingenua** pesa per la volatilità recente, non per il rischio
  futuro — Apex l'ha già testata e respinta per lo stesso motivo strutturale
  (`APEX_V2_SPEC.md` §8.1, test "Risk parity tra classi": ha sovrappesato IEF
  proprio prima del rialzo tassi 2022).

Il criterio di Kelly massimizza **E[log(ricchezza terminale)]**, equivalente a
massimizzare la mediana della ricchezza terminale su orizzonte lungo — la
definizione operativa più corretta di "ricchezza estrema con probabilità più alta
possibile". Il vincolo di "rischio di rovina sotto controllo" non è un extra: è
**intrinseco** alla matematica di Kelly, che è definita esattamente come il punto
oltre il quale la leva **riduce** la crescita attesa (non solo aumenta il rischio) —
vedi §2.

---

## 1. Perché non uno dei due motori esistenti

| | Apex Engine | Convex Stack | Kelly Stack |
|---|---|---|---|
| Leva | Zero (mai) | Fissa, 122.5% nozionale | Dinamica, vincolata da crescita geometrica + governatore di rischio |
| Logica di sizing | Segnale di timing (isteresi + vol-target) | Pesi target fissi (45/15/25/7.5/7.5) | Ottimizzazione Kelly frazionaria su μ/σ/correlazione stimati |
| Cosa la fa scendere in cash/deleva | Segnale di timing disattiva una classe | Nessun meccanismo — mai in leva oltre 122.5% per costruzione | Overlay di vol-target/drawdown a livello di portafoglio (governatore di leva) |
| Turnover | Mensile (segnale) + trimestrale (basket) | Solo PAC + trim raro | Solo PAC + trim raro (stesso principio Convex, orizzonte generazionale) |
| Obiettivo dichiarato | Alpha da timing multi-asset | Accumulo efficiente a leva istituzionale fissa | Crescita geometrica massima soggetta a rischio di rovina vincolato |

Kelly Stack non sostituisce Convex: **la generalizza**. Convex usa una leva fissa
scelta a priori (122.5%, dal design NTSG); Kelly Stack calcola quanta leva è
giustificata dalla combinazione stimata di rendimento/rischio/correlazione tra le
sleeve, e — punto critico — **la riduce automaticamente quando la stima non è più
affidabile o il regime di mercato è ostile**, invece di tenerla fissa sempre.

---

## 2. La matematica (multi-asset Kelly, in breve)

Per N sleeve con rendimenti in eccesso attesi (annualizzati) `μ` (vettore) e
matrice di covarianza `Σ`, il vettore di pesi che massimizza la crescita
geometrica attesa in tempo continuo (risultato standard, problema di Merton a
utilità logaritmica) è:

```
f* = Σ⁻¹ μ                    (pesi Kelly pieni, possono superare 100% = leva)
```

**Vincolo long-only:** l'universo di Kelly Stack è ETC/ETF (§4) — nessun margine
di broker personale, nessuna posizione corta disponibile (stesso principio di
Convex, §6). La soluzione non vincolata può assegnare peso negativo a una sleeve
a basso rendimento atteso ma positivamente correlata con le altre (es. l'oro nei
prior di default assegnati in `kelly_engine.py`) — matematicamente "ottimale" nel
problema non vincolato, ma non implementabile con questi strumenti. Il motore
applica un clip a zero sui pesi negativi: un'approssimazione della vera
ottimizzazione vincolata (che richiederebbe una programmazione quadratica con
`f≥0`, non solo l'inversione di matrice) — conservativa nella direzione giusta
(non suggerisce mai una posizione non apribile), ma non ridistribuisce
esattamente il peso "risparmiato" sulle altre sleeve come farebbe la soluzione
QP esatta. Correggere con un vero solver vincolato è nella lista di §7.

**Fatto cruciale, asimmetrico, che guida tutto il design:** scommettere PIÙ di
`f*` non è solo "più rischioso" — **riduce la crescita attesa stessa**. Scommettere
2×Kelly su una singola scommessa a crescita ottima annulla la crescita attesa a
zero. Questo è il motivo per cui il vincolo di leva qui sotto non è arbitrario:
sovrastimare la leva ottimale è un errore che si autopunisce nella metrica stessa
che si sta cercando di massimizzare, non solo nel rischio.

**Kelly frazionario (obbligatorio, non opzionale):**

```
f_kelly = k × f*              k ∈ [0.25, 0.5] tipico (vedi KELLY_FRACTION sotto)
```

Perché frazionario: `μ` è stimato con errore enorme — decenni di dati storici
pinnano il premio azionario a malapena a ±3-4%/anno di intervallo di confidenza
al 95%. Kelly pieno è una scommessa sul fatto che le stime puntuali siano esatte;
in pratica non lo sono mai. La letteratura (Thorp; MacLean/Ziemba, *The Kelly
Capital Growth Investment Criterion*) e la pratica istituzionale convergono su
**mezzo-Kelly**: mantiene ~75% della crescita attesa di Kelly pieno con una
frazione molto più piccola della sua volatilità/drawdown — un compromesso
fortemente favorevole data l'incertezza sui parametri. `KELLY_FRACTION = 0.5` è
il default di questo motore.

**Perché la diversificazione non è "anche una buona idea" ma il vero moltiplicatore
di leva sicura:** combinare N scommesse scorrelate ciascuna alla propria frazione
di Kelly dà una crescita di portafoglio molto più alta di qualunque singola
scommessa levereggiata, perché la diversificazione riduce la varianza di
portafoglio senza ridurre proporzionalmente il rendimento atteso. È lo stesso
principio per cui Convex include già managed futures (DBMFE) come "crisis alpha".
Kelly Stack lo sfrutta più a fondo: è la leva sicura che la diversificazione
autentica (non solo nominale) permette di prendere.

**Limite strutturale — le correlazioni non sono stabili:** in una crisi reale
(2008, marzo 2020) quasi tutti gli asset rischiosi convergono a correlazione ~1,
tranne trend-following (per costruzione "long volatilità") e talvolta oro/cash.
Usare la correlazione media storica per calibrare la leva sarebbe quindi
esattamente sbagliato nel momento in cui conta di più. Per questo `Σ` va stimata
(o quantomeno stress-testata) con **correlazioni da regime di crisi**, non solo
la media storica — vedi §7, non ancora fatto in questo motore.

---

## 3. Governatore di leva (il vero controllo del rischio di rovina)

La rovina, in pratica, non è "la matematica di Kelly si sbaglia" — è la
**deleva forzata al momento peggiore possibile** (margin call, vendita in panico)
che blocca permanentemente una perdita e rompe la catena di compounding. Per
questo motivo il controllo del rischio qui è a **due livelli indipendenti**,
entrambi necessari:

**Livello 1 — Vincolo statico (hard cap), indipendente dalla matematica Kelly:**
```
MAX_GROSS_LEVERAGE = 1.50   (150% nozionale sul capitale)
```
Un tetto assoluto applicato DOPO il calcolo di `f_kelly`, qualunque cosa dica
l'ottimizzatore. Motivazione: `f*` è sensibile in modo estremo a errori di stima
di `μ`/`Σ` (un fatto ben documentato — piccoli errori nell'attesa di rendimento
producono grandi errori nei pesi Kelly). Il tetto è un argine contro l'errore di
modello, non contro il rischio "normale" già gestito dal Livello 2. **Impostato
solo leggermente sopra il 122.5% già validato in produzione da Convex** (non un
salto arbitrario a leve aggressive tipo 2-3x) — finché questo motore non ha un
backtest point-in-time con lo stesso rigore di Apex (§7), non c'è base per
autorizzare più leva di quanta già validata altrove nel progetto.

**Livello 2 — Governatore dinamico (vol-target + drawdown), applicato ogni mese:**
```
vol_target = 15%  (vedi KELLY_VOL_TARGET)
scala_vol  = min(1.0, vol_target / vol_portafoglio_stimata_12w)

se drawdown_da_picco > KELLY_DD_DERISK_TRIGGER (25%):
    scala_dd = KELLY_DD_DERISK_FLOOR (0.5)   # dimezza l'esposizione lorda
altrimenti:
    scala_dd = 1.0

fattore_finale = min(scala_vol, scala_dd)
pesi_finali = pesi_dopo_cap_leva × fattore_finale
```

**Nota di onestà intellettuale, per coerenza con la cultura di questo progetto:**
`APEX_V2_SPEC.md` §8.1 ha testato e **respinto** un "kill-switch di portafoglio su
drawdown" per il design Apex — non scattava mai entro soglie sensate perché il
vol-targeting di Apex (senza leva) teneva già il MaxDD sotto controllo. Questo
non si applica automaticamente qui: Apex ha leva=1 sempre (il caso peggiore è
"perdo il capitale investito, non di più in proporzione"), mentre Kelly Stack ha
leva variabile fino a 150% (il caso peggiore con leva è strutturalmente diverso:
la stessa perdita percentuale sul sottostante è amplificata, e una deleva tardiva
può bloccare una perdita che il sottostante da solo avrebbe recuperato). Riusare
la conclusione di Apex senza ri-testarla nel contesto della leva sarebbe
esattamente l'errore di generalizzazione che l'audit di Apex v1 ha già punito una
volta (selezione titoli per momentum, valida in teoria, falsificata sui dati
reali). Il governatore drawdown per Kelly Stack **deve essere validato
indipendentemente** (§7), non ereditato per analogia.

---

## 4. Universo delle sleeve — ora esplicitamente aperto

**Revisione su richiesta esplicita dell'utente:** l'universo non è più vincolato
ai 5 strumenti di Convex. Ciò che conta è CAGR/alpha/expectancy, e sono ammesse
strategie diverse, incluso long/short — non solo diversificazione beta. Restano
**non negoziabili** due principi già stabiliti (motivati dall'obiettivo stesso di
"rischio di rovina sotto controllo" che l'utente ha fissato all'origine di questo
motore, §0):

1. **Mai margine di broker personale.** Il caso peggiore per l'investitore deve
   sempre essere "il NAV di un fondo scende", mai "arriva una richiesta di
   margine che forza una liquidazione fuori dal proprio controllo". Vale anche
   per l'esposizione long/short: si ottiene comprando un **fondo che shorta
   internamente** (gestito da un terzo con il proprio risk management), non
   aprendo posizioni corte a leva sul proprio conto.
2. **Mai ETP a leva/inversi a reset giornaliero come posizione di lungo
   periodo.** Decadono per compounding in mercati laterali (volatility decay
   ben documentato) — incompatibili con l'orizzonte "buy&hold generazionale,
   turnover minimo" di questo intero progetto. Se serve esposizione short,
   si cerca un fondo che la implementa con un orizzonte multi-mese/anno, non
   uno strumento tattico giornaliero.

Ogni nuovo strumento aggiunto qui segue lo stesso standard di verifica già
applicato in `convex_engine.py`: ISIN/ticker confermati contro fonti reali,
mai inventati. `compute_kelly_weights()` accetta `mu`/`sigma`/`corr` come
parametri — l'universo cresce editando `KELLY_SLEEVES`/`KELLY_CORR_PRIOR`,
non riscrivendo la logica di ottimizzazione.

| Sleeve | Strumento | Ruolo nel framework Kelly | μ atteso (prior, annuo, ecc. eccesso su cash) | σ atteso (prior, annuo) |
|---|---|---|---|---|
| Equity core (a leva implicita) | NTSG | Motore di crescita principale | 5.5% | 16% |
| Small cap value | AVWS | Diversificazione dentro l'equity, premio fattoriale | 6.5% | 20% |
| Managed futures / trend | DBMFE | **Crisis alpha** — ciò che rende sicura più leva sull'equity | 3.5% | 10% |
| Oro fisico | PPFB | Hedge di coda / inflazione, bassa correlazione in stagflazione | 1.0% | 15% |
| Bitcoin | WBTC | Convessità asimmetrica — bet piccolo, upside potenzialmente enorme | 15% | 60% |
| Equity long/short | JELS | **Alpha market-neutral-ish**, bassa correlazione col beta azionario per costruzione | 3.0% | 8% |

### 4.1 Equity Long/Short — JPMorgan Equity Long-Short UCITS ETF (JELS)

**Verificato (ricerca web, settembre 2026):** ISIN `IE00BF4G7308`, ticker
`JELS` (quotato LSE come `JELS.L`, anche varianti Xetra `JLEE`/`JLEA` e una
classe GBP-hedged `IE00BDDRF254`). Fondo attivo, non un indice passivo:
"exploiting pricing inefficiencies between global developed market equity
securities by maintaining long and short positions... based on a systematic
investment process." TER 0.67%. Il gestore implementa lo short internamente
(derivati/swap a livello di fondo) — l'investitore non apre mai una posizione
a margine.

**Rischio dichiarato, non ipotetico:** l'AUM rilevato è **~€10 milioni** — un
fondo molto piccolo. Rischio concreto di chiusura/fusione (visto realizzarsi
nella ricerca sotto per un prodotto concorrente), spread bid-ask
potenzialmente largo, tracking/execution risk più alto di un ETF passivo
grande. Va monitorato esplicitamente, non trattato come rischio trascurabile
solo perché il wrapper è "solo un ETF".

**Scartato per lo stesso ruolo, con motivazione — Xtrackers db (Equity
Strategies) Hedge Fund Index UCITS ETF** (varie classi, es. `DBX0DD`/
ISIN `LU0434446117`, multi-strategy: Equity Hedge, Equity Market Neutral,
Systematic Macro, Event Driven, Credit & Convertible Arbitrage, Global Macro):
la ricerca ha trovato **più classi della stessa famiglia già liquidate o
fuse** (1C EUR-hedged, 2C, 3C GBP-hedged, 5C CHF-hedged, e le varianti "Equity
Strategies" 1C/2C/5C). Un segnale strutturale di fragilità dell'intera
famiglia di prodotto, non di una singola share class isolata — coerente con
il principio già seguito in Apex di non adottare un candidato solo perché
sembra buono su carta (`APEX_V2_SPEC.md` §8.4, sleeve commodity DBC: buono nel
campione breve, non robusto). Non incluso nell'universo.

**μ/σ prior per JELS:** i fondi equity market-neutral/long-short hanno storicamente
rendimenti in eccesso modesti (letteratura su hedge fund equity market-neutral:
tipicamente 2-4%/anno) con volatilità bassa rispetto all'azionario long-only
(per costruzione, gran parte del beta di mercato è neutralizzato) — ma con
rischio di manager/esecuzione più alto di un indice passivo, e correlazione
che può salire bruscamente in eventi di deleveraging dei fattori quantitativi
(es. "quant crash" agosto 2007) invece di restare vicina a zero come nei
periodi normali. Prior deliberatamente conservativo: μ=3.0%, σ=8%, correlazione
positiva piccola (non zero) con le altre sleeve azionarie per riflettere
questo rischio di coda, non la correlazione media "tranquilla".

**I prior di μ/σ sono stime di letteratura accademica generiche (equity risk
premium storico, momentum/trend-following CTA, oro reale, small-cap value
premium), FORTEMENTE compresse verso il basso rispetto a qualunque numero
trailing recente — deliberatamente conservative.** Non sono calibrate sui dati
storici specifici di questi 5 strumenti (nessun backtest point-in-time ancora
fatto per Kelly Stack — vedi §7). Il motore accetta questi valori come default
sostituibile, non come costanti nascoste: `compute_kelly_weights()` prende
`mu`/`sigma`/`corr` come parametri, esattamente come `evaluate_convex_stack()`
prende prezzi/quote dall'esterno invece di leggerli da disco.

**Bitcoin — nota esplicita sul dimensionamento asimmetrico:** un prior μ così alto
sembrerebbe giustificare un peso enorme via Kelly puro. Non è quello che succede
qui: `σ=60%` implica `f*_BTC` isolato già moderato, e la correlazione (anche
bassa) con le altre sleeve nel calcolo matriciale lo comprime ulteriormente. Il
motore non applica un cap ad-hoc su BTC — lascia che sia la matematica Kelly
completa (che include già l'effetto di σ² al denominatore) a determinarne la
taglia, coerente con l'approccio "niente aggiustamenti ad-hoc non giustificati"
già seguito in Apex.

---

## 5. Calendario operativo e fiscalità

Stessa disciplina di Convex, per lo stesso motivo (orizzonte generazionale =
turnover minimo = drag fiscale minimo composto su decenni):

- **Versamento**: PAC mensile "water-filling" verso la sleeve più sottopesata
  rispetto al target Kelly corrente (stesso algoritmo di
  `evaluate_convex_stack`, riusato — non reinventato).
- **Ribilanciamento per trim**: solo quando una sleeve supera la propria banda
  di tolleranza, e solo per strumenti a "reddito diverso" (WBTC/PPFB) dove la
  minusvalenza è compensabile — stessa logica di `convex_engine.py`.
- **Ricalcolo dei pesi target Kelly**: mensile (in sincronia con l'aggiornamento
  del governatore di leva §3), non più frequente — un orizzonte generazionale
  non richiede reattività settimanale, e più frequenza aumenterebbe solo
  turnover/tasse senza beneficio dimostrato (stesso principio della "banda di
  non-negoziazione" respinta in Apex, ma applicato qui alla frequenza di stima
  invece che alla soglia di ribilanciamento).
- **Nessuna vendita totale della posizione core per motivi tattici** — coerente
  con l'obiettivo di trasferimento intergenerazionale: l'unico evento di uscita
  totale da una sleeve è un cambio strutturale del design stesso (es. lo
  strumento viene liquidato/sostituito), mai una decisione di timing.

---

## 6. Cosa questo motore NON fa (per essere espliciti)

- Non promette un numero di leva massima "aggressivo" finché non è validato —
  vedi il tetto conservativo in §3.
- Non usa margine di broker personale — solo leva implicita a livello di
  prodotto (stesso principio di Convex): il caso peggiore per l'investitore è il
  NAV del fondo che scende, mai una richiesta di margine personale che forza una
  liquidazione fuori dal proprio controllo.
- Non ottimizza la fiscalità successoria italiana (imposta di successione,
  intestazione, trust) — questo è un problema di struttura patrimoniale/legale,
  distinto dalla strategia di allocazione. Il motore ottimizza l'accumulo pre-
  successione con la stessa efficienza fiscale (redditi diversi vs redditi di
  capitale) già validata in Convex; l'ottimizzazione dell'evento successorio
  stesso è fuori scope di questo documento.

---

## 7. Stato di validazione

### 7.1 Risultati di validazione reali (walk-forward + DSR/PBO, su richiesta esplicita dell'utente)

**Metodologia:** `kelly_backtest.py` calibra μ/σ/Σ SOLO sulla prima parte del
campione storico (dati reali via Yahoo Finance, rendimenti mensili adjusted-
for-dividend) e applica i pesi risultanti SENZA ri-ottimizzare sul resto —
stesso principio del walk-forward gia' validato in Apex (`APEX_V2_SPEC.md`
§8.4). `kelly_validation.py` implementa Deflated Sharpe Ratio e PBO via CSCV
(Bailey/Lopez de Prado) da zero (nessuna dipendenza da scipy, coerente con
`requirements.txt`) — verificati su dati sintetici a comportamento noto
(`test_kelly_validation.py`) e incrociati contro l'algoritmo di `pypbo`
(libreria open-source di riferimento dopo che mlfinlab e' diventata a
pagamento): stessa struttura combinatoria, stesso criterio rank-based.

Le sleeve UCITS reali (NTSG/AVWS/DBMFE/PPFB) hanno storico troppo corto o non
tradabile per un backtest robusto — si usano PROXY a storico lungo, stesso
principio con cui Apex usa SPY come proxy di segnale (§1): NTSG →
`0.9×SPY + 0.6×IEF` (la stessa decomposizione di leva gia' documentata in
`convex_engine.py`), AVWS → VBR (small-cap value), DBMFE → DBMF (sorella USA
di DBMFE, storico dal 2019), PPFB → GLD, WBTC → BTC-USD. **JELS non ha storico
sufficiente ed e' escluso dal backtest** — resta validato solo dal prior
strutturale di §4.1, limite dichiarato, non nascosto.

**Risultato 1 — un solo split e' fuorviante.** Il primo walk-forward
(50/50, campione 2019-2026 con DBMFE+WBTC) dava CAGR netto 28.7%, quasi il
target. Un walk-forward a **5 finestre mobili** (invece di un solo split)
rivela perche' quel numero non e' affidabile:

| Campione | Finestre OOS | CAGR netto: media | CAGR netto: min | CAGR netto: max | MaxDD netto peggiore |
|---|---|---|---|---|---|
| Completo (2019-2026, con DBMFE+WBTC) | 4 | **17.1%** | **-10.0%** | **+45.9%** | -27.3% |
| Lungo (2005-2026, senza DBMFE/WBTC) | 5 | **12.9%** | **-0.3%** | **+26.4%** | -24.2% |

Il 28.7% iniziale era un artefatto del punto di split: cadeva subito dopo il
grosso del bear 2022 e catturava in pieno il rally IA/Bitcoin 2023-2025 —
esattamente il tipo di bias gia' identificato da Apex per BTC
(`APEX_V2_SPEC.md` §8.2 test 4: "la maggior parte del rendimento... viene dal
campione breve... periodo di bull secolare"). La media onesta su piu' finestre
e' 13-17%, con una finestra realmente osservata **vicina allo zero o
negativa** (2012-2015 nel campione lungo, complice il crollo dell'oro 2013;
Apr 2022-Ago 2023 nel campione completo, il bear rialzo-tassi).

**Risultato 2 — alzare `KELLY_FRACTION` oltre ~0.5 non cambia nulla.** Test
diretto (0.25/0.5/0.75/1.0) sul campione lungo: a 0.5 il segnale Kelly satura
gia' il cap di concentrazione per singola sleeve (§3, Livello 1bis) su
NTSG_proxy e PPFB_proxy — 0.75 e 1.0 producono **pesi finali identici** a 0.5.
Conferma sperimentale, non solo teorica, del fatto dichiarato in §2: oltre un
certo punto la leva non e' vincolata dalla propria propensione al rischio, e'
vincolata dai governatori — "alzare il rischio" cambiando `KELLY_FRACTION` da
solo non fa nulla finche' non si alza anche `MAX_SLEEVE_WEIGHT`/
`MAX_GROSS_LEVERAGE`, il che significa esplicitamente accettare un rischio di
rovina piu' alto, non un pasto gratis.

**Risultato 3 — DSR/PBO.** DSR sullo Sharpe netto del campione completo
(1.76, 44 mesi OOS, contando conservativamente 3 varianti di universo provate)
= 1.00 — ma questo corregge solo per multiple-testing, non per il bias di
regime del Risultato 1 (sono diagnostiche complementari, non sostituibili).
PBO tra le varianti di `KELLY_FRACTION` sul campione lungo = 26% (sotto il
50% di puro rumore, ma con solo 2 varianti realmente distinte a causa della
saturazione del Risultato 2 — informativo ma non conclusivo).

**Risultato 4 — il governatore dinamico (§3, Livello 2) aiuta, ma solo dove
c'e' qualcosa da contenere.** Attivato mese per mese nel walk-forward
(`compute_dynamic_target_weights`, nessun lookahead: vol/drawdown calcolati
sulla storia gia' trascorsa, warm-up dagli ultimi mesi di calibrazione) e
confrontato direttamente con lo stesso disegno a pesi fissi:

| Campione | CAGR netto medio: fisso → governato | MaxDD netto peggiore: fisso → governato |
|---|---|---|
| Completo (con DBMFE/WBTC) | 17.1% → **17.6%** | -27.3% → **-14.7%** |
| Lungo (senza DBMFE/WBTC) | 12.9% → **11.3%** | -24.2% → **-24.0%** |

Sul campione che include le sleeve a coda grassa (DBMFE/WBTC — il disegno
realmente deployato), il governatore quasi dimezza il worst-case drawdown
**senza costare rendimento** (anzi con un piccolo guadagno). Sul campione
senza quelle sleeve non aiuta affatto — stesso identico pattern gia' trovato
da Apex per il proprio vol-targeting (`APEX_V2_SPEC.md`, apex_v2_engine.py:
"il beneficio viene specificamente dal contenere i picchi di volatilita' di
BTC... sullo stesso disegno senza crypto... non aiuta"). **Adottato per
questo motivo specifico e misurato — non perche' Apex lo usa.** Se il design
venisse mai deployato senza DBMFE/WBTC, andrebbe ri-verificato se tenerlo
ancora ha senso.

**Risultato 5 — quanto si può "spingere" alzando la leva col governatore
attivo? Dipende dal campione, e la differenza è la lezione principale.** Sweep
di `MAX_GROSS_LEVERAGE`/`MAX_SLEEVE_WEIGHT` da 150%/60% a 400%/130%, governatore
sempre attivo:

| Leva max | Campione completo (con DBMFE/WBTC): CAGR medio / MaxDD peggiore / Sharpe | Campione lungo (senza): CAGR medio / MaxDD peggiore / Sharpe |
|---|---|---|
| 150% | 17.6% / -14.7% / 1.17 | 11.3% / -24.0% / 0.83 |
| 200% | 20.3% / -15.0% / 1.16 | 12.2% / -26.2% / 0.81 |
| 250% | 22.6% / -17.3% / 1.16 | 13.9% / -28.3% / 0.80 |
| 300% | 24.6% / -18.9% / 1.17 | 14.9% / -29.9% / 0.79 |
| 400% | 27.4% / -22.6% / 1.16 | 16.2% / -33.0% / 0.80 |

Sul campione completo lo Sharpe resta quasi costante alzando la leva (il
governatore normalizza il rischio, quindi CAGR e drawdown scalano quasi
insieme) — un quadro che sembrerebbe quasi un pasto gratis fino al 400%. **Sul
campione lungo, il quadro reale, questo non regge**: lo stesso aumento di leva
compra molto meno CAGR (11.3%→16.2%, non 17.6%→27.4%) a fronte di un drawdown
peggiore che sale fino al **-33%**, con fold worst-case che diventano
NEGATIVI in modo crescente (-0.5%→-5.2%). La differenza tra le due tabelle È
il punto: il primo quadro amplifica la fortuna del campione breve (Risultato
1), il secondo mostra il vero trade-off leva/rischio quando quella fortuna non
c'è. **Spingere la leva oltre 150-200% non è raccomandato**: il guadagno di
CAGR nel caso onesto (lungo) è modesto rispetto al peggioramento di drawdown,
esattamente il tipo di scommessa che il criterio di Kelly (§2) dice di evitare
quando non si è certi che l'edge sia reale e non un artefatto del campione.

**Risultato 6 — ricerca di nuovi candidati diversificatori, uno alla volta.**
Su richiesta esplicita dell'utente ("puoi cercarne altre?"), 7 asset class
liquide aggiuntive (ognuna un ticker reale, storico verificato via Yahoo)
testate UNA ALLA VOLTA sopra l'universo base (NTSG/AVWS/PPFB proxy), stesso
walk-forward multi-finestra, governatore attivo, stessa leva 150%/60%:

| Candidato | Sharpe: base→+cand | CAGR: base→+cand | MaxDD: base→+cand | Verdetto |
|---|---|---|---|---|
| EEM (mercati emergenti) | 0.96→0.81 | 12.8%→10.8% | -15.9%→-26.1% | Peggiora tutto |
| QUAL (fattore qualita') | 1.24→1.21 | 9.6%→12.5% | invariato | Marginale (campione corto, dal 2013) |
| MTUM (fattore momentum) | 1.38→1.27 | 9.5%→17.5% | -18.6%→-24.3% | **Sospetto**: stesso pattern di fortuna da campione breve gia' visto per BTC/IA (dal 2013) |
| HYG (credito high yield) | 0.80→0.78 | 10.5%→10.2% | invariato | Non aiuta |
| **VNQ (REIT)** | **0.96→0.97** | **12.8%→13.2%** | **-15.9%→-15.3%** | **Unico che migliora Sharpe, CAGR e MaxDD insieme** (modesto, non trasformativo) |
| MNA (merger arbitrage) | 0.99→1.07 | 8.3%→9.3% | -18.7%→-20.3% | Promettente, campione piu' corto (dal 2010) |
| TIP (inflation-linked) | 0.96→0.89 | 12.8%→11.5% | -15.9%→-21.3% | Peggiora tutto |

**Nessuno di questi 7 e' stato adottato nell'universo di produzione
(`kelly_engine.py`)** — un singolo test additivo non basta (stesso principio
di §7.2 punto 2: serve DSR/PBO prima di trattare un risultato come edge reale,
non rumore di un singolo confronto). VNQ e MNA sono i candidati piu' credibili
per un prossimo giro di validazione; MTUM va trattato con lo stesso sospetto
gia' riservato a BTC (il salto di CAGR coincide con l'unico campione
disponibile, non con piu' finestre indipendenti). Nessuno di questi 7 cambia
la conclusione sul target 30-35% (sotto).

**Risultato 7 — tentativo di battere Apex con un filtro di trend per sleeve
(su richiesta esplicita dell'utente: "deve essere migliori di Apex").**
Diagnosi di partenza: il governatore di Kelly Stack finora è solo REATTIVO a
livello di portafoglio (vol-target + drawdown) — mai un segnale di trend PER
SLEEVE come quello che dà ad Apex il suo Sharpe/Calmar superiori (isteresi su
MA, `apex_v2_engine.compute_v2_macro_signal`). Implementato lo stesso
meccanismo (`compute_trend_gate`/`compute_trend_gated_weights`, isteresi
mensile su indice di prezzo sintetico per sleeve, nessun lookahead — 4 nuovi
test) e confrontato su un singolo split:

| | CAGR lordo | Sharpe lordo | MaxDD lordo | CAGR netto | Sharpe netto |
|---|---|---|---|---|---|
| Campione completo, banda 2% | **29.1%** | **2.00** | **-8.0%** | 15.0% | 1.08 |
| Campione lungo, banda 2% | **19.5%** | **1.72** | **-10.1%** | 8.4% | 0.66 |
| Apex deployato (rif.) | 16.0% | 1.49 | 12.3% | — | — |

**Al lordo il trend-gate batte Apex nettamente su entrambi i campioni.** Ma
il netto CROLLA (Sharpe 2.00→1.08, 1.72→0.66) — causa diagnosticata, non
generica: il trend-gate aumenta il turnover (ogni cambio di trend è una
vendita) e le sleeve proxy sono tutte ETF a "reddito di capitale" (non
compensabile). **È esattamente il problema che Apex ha già risolto** usando
titoli individuali per la gamba azionaria (redditi diversi, compensabili,
`APEX_V2_SPEC.md` §1) — non ancora replicato qui.

Sweep della banda di isteresi (2%→20%) per ridurre il turnover: un singolo
split a banda 12% sembrava recuperare l'edge (Sharpe netto 0.96, meglio della
baseline 0.83) — ma **verificato con walk-forward multi-finestra, non
regge**: nessuna banda testata (2/8/12%) batte in modo robusto il governatore
semplice senza trend-gate su Sharpe netto, su nessuno dei due campioni. Lo
stesso identico pattern del Risultato 1 (un singolo split mente, il
multi-finestra dice la verità) si ripete qui una quarta volta.

**Risultato 7b — implementazione tax-efficient testata, effetto reale ma
piccolo.** Su decisione esplicita dell'utente ("opzione 1"), NTSG_proxy e
AVWS_proxy riclassificate a REDDITO_DIVERSO (come se implementate via basket
di titoli individuali, sul modello dell'equity leg di Apex) — DBMFE_proxy
resta REDDITO_CAPITALE: un'esposizione a managed futures/CTA non ha un
equivalente "titoli individuali", quindi per quella sleeve il problema fiscale
non è risolvibile con questa leva, limite dichiarato non aggirabile.

| Campione | Banda | Sharpe netto: ETF → tax-efficient |
|---|---|---|
| Completo | 2% | 1.08 → **1.13** |
| Completo | 12% | 1.13 → **1.14** |
| Lungo | 2% | 0.66 → **0.71** |
| Lungo | 8% | 0.86 → **0.88** |

Il miglioramento è reale (mai peggiora) ma **piccolo** — non chiude il divario
con Apex (Sharpe 1.49). Motivo probabile, distinto dalla tassazione: la
compensazione di redditi diversi riduce la tassa SOLO quando c'è un pool di
minusvalenze pregresse da cui attingere — con un trend-gate che realizza
prevalentemente guadagni (non un'alternanza equilibrata perdita/guadagno), il
beneficio della compensazione è strutturalmente limitato. La causa più
probabile del divario residuo non è più la tassazione, ma la QUALITÀ del
segnale: il trend-gate qui usa isteresi a banda fissa su una MA mensile
semplice, mentre Apex usa isteresi ADATTIVA alla volatilità di ciascun asset
più una conferma multi-timeframe (`V2_HYSTERESIS_K`, `V2_SHORT_MA_WEEKS`,
§8.9 di `APEX_V2_SPEC.md`) — un segnale più raffinato, validato da Apex per
ridurre i whipsaw senza perdere Sharpe/Calmar. Non ancora testato per Kelly
Stack: prossimo passo naturale, non ancora intrapreso senza una decisione
esplicita dell'utente vista la scala di lavoro già investita su questo filone.

**Risultato 8 — ispirazione dai CTA sistematici (Winton/Dunn Capital/AHL) e
dal paper accademico che ne formalizza il metodo (Moskowitz/Ooi/Pedersen 2012,
"Time Series Momentum"): una sleeve di trend multi-mercato INDIPENDENTE,
non un gate su sleeve esistenti.** Su richiesta esplicita dell'utente
("ispirati ai migliori trader"). A differenza del trend-gate (Risultato 7,
respinto per il turnover fiscale), questa è una sleeve AGGIUNTIVA con pesi
Kelly propri, ribilanciata alla stessa cadenza mensile di tutte le altre —
nessun turnover extra, nessun problema fiscale nuovo. Segnale: long/flat per
mercato in base al segno del rendimento cumulato a 12 mesi, scalato a
vol-target comune (SPY/IEF/GLD/DBC — 4 mercati liquidi e scorrelati),
`compute_tsmom_sleeve_returns`, 3 nuovi test (nessun lookahead, segnale
coerente su trend sostenuti).

| Campione | Sharpe netto: base→+TSMOM | CAGR netto: base→+TSMOM | MaxDD netto: base→+TSMOM |
|---|---|---|---|
| Completo (con BTC/DBMFE) | 1.17→**1.26** | 17.6%→19.5% | -14.7%→-15.9% |
| Lungo (senza) | 0.83→**1.16** | 11.3%→12.2% | **-24.0%→-16.1%** |

Miglioramento reale su entrambi i campioni, non un singolo split fortunato.
DSR sullo Sharpe netto, contando conservativamente **20 varianti** provate
in questa intera sessione (leva, bande di isteresi, 7 diversificatori,
riclassificazione fiscale, TSMOM stesso) = 1.00 — resiste anche a una
correzione severa per multiple-testing.

**Due limiti onesti, non aggirabili:**
1. **Correlazione 0.55 con DBMFE_proxy** — non è una fonte di edge
   indipendente, è più esposizione allo stesso tipo di premio
   (trend-following), costruita diversamente. Diversificazione parziale, non
   piena.
2. **Non è un prodotto acquistabile.** È una regola di trading mensile fatta
   in casa su 4 ETF (SPY/IEF/GLD/DBC), non un fondo con un ISIN verificabile
   come tutte le altre sleeve di questo documento. Implementarla per davvero
   richiede o (a) eseguirla manualmente ogni mese (costi di transazione non
   modellati, onere operativo reale, errore umano) o (b) trovare un fondo
   UCITS che replichi questo stile — non ancora cercato/verificato. **Per
   questo NON è stata aggiunta a `KELLY_SLEEVES` in produzione** — resta un
   segnale validato, non uno strumento pronto, stesso standard già applicato
   a JELS (AUM piccolo, dichiarato) e a Xtrackers Hedge Fund Index (scartato).

**Confronto finale onesto, lordo su lordo (la base comparabile con l'headline
di Apex):** Kelly Stack + TSMOM raggiunge Sharpe lordo 1.21-1.30 contro
l'1.49 di Apex — il gap si è ridotto sostanzialmente (da 1.17-1.24 pre-TSMOM)
ma **non è chiuso**.

**Conclusione onesta su "deve essere migliore di Apex":** con tutta la
validazione fatta finora (trend-gate + tax-efficient + TSMOM), **Kelly Stack
si avvicina ad Apex ma non lo supera ancora**, né al lordo né al netto, in
nessuna configurazione con strumenti realmente acquistabili. Tre cause
diagnosticate, non generiche: (1) tassazione — parzialmente risolta, effetto
piccolo; (2) qualità del segnale di trend (isteresi adattiva + multi-
timeframe di Apex) — non ancora affrontata; (3) TSMOM aggiunge un
miglioramento reale ma parzialmente ridondante con DBMFE e non ancora
implementabile con un prodotto verificato.

**Conclusione onesta sul target 30-35% CAGR:** nessuno dei walk-forward reali,
su nessun campione o combinazione di parametri provata, sostiene un CAGR netto
sostenuto del 30%+. La media piu' favorevole (17.1%, campione corto, gonfiato da bull BTC/IA)
resta ben sotto il 34.9% che servirebbe per 100k→2M in 10 anni senza nuovi
versamenti, ed e' comunque coerente con il tetto teorico assoluto di §2
(~19.2% a Kelly pieno illimitato, calcolato sui prior — i dati reali qui
confermano che quel tetto non era pessimistico).

### 7.2 Cosa manca ancora prima di capitale reale

1. ~~Backtest point-in-time~~ — fatto (§7.1), con il limite dichiarato che le
   sleeve UCITS reali sono sostituite da proxy a storico lungo e JELS resta
   non testato.
2. ~~Test di falsificazione stile Apex (DSR, PBO)~~ — fatto (§7.1), con lo
   stesso limite: la profondita' del multiple-testing testato qui e' modesta
   rispetto ai 16+ tentativi documentati per Apex (`APEX_V2_SPEC.md` §8.1).
3. ~~Il governatore dinamico vol-target/drawdown non era mai stato attivato
   nel backtest~~ — fatto (§7.1, Risultato 4): aiuta sul campione con
   DBMFE/WBTC (drawdown quasi dimezzato, CAGR invariato o leggermente
   migliore), non aiuta senza — comportamento coerente con quanto gia'
   osservato in Apex per lo stesso meccanismo, ma verificato qui
   indipendentemente, non ereditato per analogia.
4. **Solver Kelly vincolato (QP, f≥0)** al posto del clip a zero approssimato
   in `compute_kelly_weights` (§2).
5. **Stress test delle correlazioni in regime di crisi** (2008 incluso nella
   sola calibrazione del campione lungo, mai in una finestra out-of-sample
   dedicata).
6. **Verifica di liquidità/AUM aggiornata su JELS** (§4.1) — AUM ~€10M
   rilevato in ricerca, dato puntuale non monitorato in continuo.
7. **Implementazione tax-efficient del trend-gate per sleeve** (§7.1 Risultato
   7) — il segnale di trend batte Apex al lordo (Sharpe 1.72-2.00 vs 1.49) ma
   l'implementazione attuale a ETF (reddito di capitale, non compensabile)
   distrugge l'edge al netto. Serve l'equivalente di ciò che Apex già fa per
   la propria gamba azionaria (strumenti a reddito diverso/compensabile) —
   non ancora costruito per Kelly Stack. **Prerequisito prima di poter
   affermare che Kelly Stack batte Apex.**
8. **Segnale di trend adattivo/multi-timeframe** (§7.1 Risultato 8, causa
   diagnosticata #2 del gap residuo) — replicare per Kelly Stack
   `V2_HYSTERESIS_K`/`V2_SHORT_MA_WEEKS` di Apex, non ancora fatto.
9. **Prodotto reale per la sleeve TSMOM** (§7.1 Risultato 8) — o un fondo
   UCITS verificato con stile simile, o un piano operativo onesto per
   l'esecuzione manuale mensile (costi di transazione, disciplina) prima di
   poterla considerare più di un segnale validato in backtest.

Fino a quel punto, questo motore va trattato come un **framework di calcolo
pesi**, utile per capire la direzione e la logica dell'allocazione, non come un
segnale pronto per l'esecuzione con capitale reale.
