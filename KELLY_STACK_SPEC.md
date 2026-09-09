# Kelly Stack — Specifica Operativa (Terzo Pilastro: Ricchezza Generazionale)

Documento di riferimento per **Kelly Stack**, terzo motore quantitativo del progetto,
indipendente da Apex Engine (timing tattico, leva zero) e Convex Stack (accumulo
sistematico a leva fissa 122.5%). Segue la stessa disciplina di `APEX_V2_SPEC.md`:
ogni parametro ha una giustificazione esplicita, i limiti dichiarati sono onesti, e
niente viene presentato come "pronto per capitale reale" finché non è validato con
backtest point-in-time e test di robustezza — esattamente lo standard che ha già
prodotto due bug di produzione corretti in Apex (§8.5, §8.8 di `APEX_V2_SPEC.md`).

**Stato di questo documento: DESIGN, non ancora backtestato.** Vedi §7.

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

## 4. Universo delle sleeve

Riusa gli **stessi strumenti UCITS/ETC già verificati** in `convex_engine.py`
(ISIN e ticker confermati contro fonti reali, con la cronologia di bug di
identificazione prodotto già corretti — vedi commenti in quel file) invece di
introdurne di nuovi non verificati. La differenza di Kelly Stack rispetto a
Convex non è l'universo di strumenti, è **come vengono pesati**.

| Sleeve | Strumento | Ruolo nel framework Kelly | μ atteso (prior, annuo, ecc. eccesso su cash) | σ atteso (prior, annuo) |
|---|---|---|---|---|
| Equity core (a leva implicita) | NTSG | Motore di crescita principale | 5.5% | 16% |
| Small cap value | AVWS | Diversificazione dentro l'equity, premio fattoriale | 6.5% | 20% |
| Managed futures / trend | DBMFE | **Crisis alpha** — ciò che rende sicura più leva sull'equity | 3.5% | 10% |
| Oro fisico | PPFB | Hedge di coda / inflazione, bassa correlazione in stagflazione | 1.0% | 15% |
| Bitcoin | WBTC | Convessità asimmetrica — bet piccolo, upside potenzialmente enorme | 15% | 60% |

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

## 7. Stato di validazione — cosa manca prima di capitale reale

**Questo è un motore di design, non ancora backtestato.** In coerenza con la
disciplina di `APEX_V2_SPEC.md` (mai dichiarare pronto qualcosa di non
verificato), prima di allocare capitale reale a Kelly Stack servono, nello
stesso ordine di rigore usato per Apex:

1. **Solver Kelly vincolato (QP, f≥0)** al posto del clip a zero approssimato
   attualmente in `compute_kelly_weights` (§2) — il clip è conservativo ma non
   esatto: non ridistribuisce il peso "risparmiato" da un vincolo attivo.
2. **Backtest point-in-time** dei 5 strumenti (o dei loro proxy storici più
   lunghi, come già fatto in Apex per il basket azionario) per stimare
   `μ`/`σ`/`Σ` **fuori campione** invece di usare i prior di letteratura di §4.
3. **Stress test delle correlazioni in regime di crisi** (2008, 2020, 2022) —
   verificare che il governatore di leva (§3) si attivi in tempo utile nei
   drawdown storici reali, non solo in simulazione teorica.
4. **Test di falsificazione stile Apex** (Deflated Sharpe Ratio, ingresso
   casuale, walk-forward) sulla scelta di `KELLY_FRACTION` e `MAX_GROSS_LEVERAGE`
   — evitare lo stesso errore di data-snooping già commesso (e corretto) nel
   motore di selezione titoli v1 di Apex.
5. **Validazione del governatore drawdown indipendente da quello di Apex**
   (§3, nota di onestà intellettuale) — non ereditare la conclusione "il
   kill-switch non serve" senza ritestarla in presenza di leva.

Fino a quel punto, questo motore va trattato come un **framework di calcolo
pesi**, utile per capire la direzione e la logica dell'allocazione, non come un
segnale pronto per l'esecuzione con capitale reale.
