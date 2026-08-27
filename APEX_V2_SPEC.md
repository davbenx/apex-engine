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

**Nota metodologica:** dopo 10 tentativi di miglioramento testati sullo stesso
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
