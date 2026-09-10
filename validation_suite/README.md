# Validation Suite — indice unico di test, invalidazione istituzionale e dati point-in-time

Questa cartella centralizza tutto quello che serve per **verificare** (non per
far girare in produzione) le strategie di questo repository: Apex V2,
Convex Stack e Kelly Stack (quest'ultima esplorata e poi scartata — vedi
`kelly_stack/KELLY_STACK_SPEC.md` §7). Prima di questa riorganizzazione
(settembre 2026) questi file vivevano sparsi nella root del repo insieme al
codice di produzione (`backend.py`, `app.py`, `apex_v2_engine.py`,
`convex_engine.py`, ...), che **resta in root** — questa cartella raccoglie
solo la parte di test/ricerca/validazione e i dataset point-in-time.

> **Regola di manutenzione — leggi prima di aggiungere qualcosa:**
> ogni volta che aggiungi un test, uno script di backtest comparativo, un
> nuovo dataset point-in-time, o cambi la struttura di questa cartella,
> **aggiorna questo README nella stessa modifica** (nuova riga nella tabella
> giusta, nuova voce in "Storia delle scoperte" se il risultato è
> rilevante). Non lasciare che questo documento invecchia rispetto al
> contenuto reale della cartella — è l'unico punto in cui chiunque (umano o
> agente) può capire cosa esiste senza dover rileggere l'intera sessione che
> l'ha prodotto.

## Mappa della cartella

```
validation_suite/
├── README.md                    <- questo file
├── conftest.py                  <- risolve per pytest gli import dei moduli di produzione in root + framework/
├── pytest.ini                   <- testpaths = framework, kelly_stack, core_regression (comparative_studies escluso: lento)
├── requirements-test.txt        <- dipendenze SOLO per eseguire questa cartella (pytest)
├── run_fast_suite.sh            <- comando unico: tutta la suite veloce/deterministica, da qualunque cwd
├── framework/                    <- TOOLKIT GENERICO, riusabile da QUALSIASI strategia (non specifico a Kelly Stack)
│   ├── metrics.py                <- cagr/sharpe/max_drawdown/calmar
│   ├── tax_engine.py              <- apply_italian_tax (redditi capitale/diversi, PMC, NAV/nozionale separati)
│   ├── statistical_validation.py <- Deflated Sharpe Ratio, PBO/CSCV, block bootstrap CI (Bailey/Lopez de Prado)
│   └── test_*.py                 <- 19 test sui 3 moduli sopra
├── core_regression/              <- suite di non-regressione per il sistema LIVE (in CI, .github/workflows/ci.yml)
│   ├── test_apex_convex.py                        <- integrazione Apex+Convex+PortfolioManager (16 test)
│   ├── test_apex_v2_engine.py                     <- motore di segnale/basket Apex V2 canonico (13 test)
│   ├── test_backend.py                            <- NAV/tassazione/rotazione/calendario/fetch_sector (19 test)
│   └── test_apex_v2_institutional_validation.py   <- DSR/PBO/bootstrap sulla VERA serie di rendimenti Apex V2 (6 test)
├── kelly_stack/                  <- modulo di ricerca "Kelly Stack" (3° pilastro esplorato, NON adottato)
│   ├── KELLY_STACK_SPEC.md       <- spec/diario di validazione completo, incl. perché è stato scartato (§7)
│   ├── kelly_engine.py           <- pesi Kelly vincolati (QP long-only), governor di rischio
│   ├── kelly_optimization.py     <- solver QP (projected gradient ascent)
│   ├── kelly_backtest.py         <- fetch universo, walk-forward (usa framework/metrics.py e tax_engine.py)
│   └── test_kelly_*.py           <- 36 test (pytest) sui 3 moduli sopra
├── comparative_studies/          <- script di backtest indipendenti, uno-per-domanda, non un motore persistente
│   ├── apex_stocks_vs_etf_backtest.py     <- basket azionario Apex vs ETF, netto tasse, point-in-time
│   ├── altcoin_vs_btc_backtest.py         <- altcoin vs BTC, SETTIMANALE/universo fisso ETH+SOL — superata dalla successiva
│   ├── altcoin_vs_btc_daily_backtest.py   <- altcoin vs BTC, DAILY + universo point-in-time reale (5 candidati, PBO/DSR/bootstrap)
│   ├── altcoin_vs_btc_weekly_pointintime_backtest.py  <- stesso universo point-in-time, ma WEEKLY — isola granularità da universo
│   ├── altcoin_strategy_families_pointintime_test.py  <- momentum/mean-reversion/low-vol/trend-following/stop-loss, point-in-time, daily
│   ├── altcoin_carry_funding_rate_test.py             <- carry (funding rate perpetual), campione corto (~1 anno, limite API reale)
│   ├── sector_cap_grid_test.py            <- grid search reale su V2_MAX_PER_SECTOR (2 vs 3 vs 4 vs 5 vs nessuno)
│   ├── apex_basket_size_grid_test.py      <- grid search su V2_EQUITY_TOP_N (10/12/15/18/20/25 titoli)
│   ├── apex_class_size_grid_test.py       <- grid search su base_weight_per_class/vol_target (dimensione posizioni per classe macro)
│   ├── apex_profit_trailing_stop_test.py  <- trailing stop attivato dal profitto su BTC/Oro (risultato: peggiora, non adottare)
│   ├── apex_crypto_execution_venue_test.py <- perp vs spot vs ETP (proxy IBIT) per la gamba Crypto: costi reali + effetto ore/giorni di mercato chiuso
│   ├── convex_weights_grid_test.py        <- grid search sui pesi target di Convex Stack (9 combinazioni vs 45/15/25/7.5/7.5)
│   ├── apex_stocks_data/                  <- cache prezzi (rigenerabile, gitignored)
│   ├── altcoin_data/                      <- cache prezzi settimanali (rigenerabile, gitignored)
│   ├── altcoin_daily_data/                <- cache prezzi daily (rigenerabile, gitignored)
│   ├── convex_grid_data/                  <- cache prezzi mensili proxy Convex (rigenerabile, gitignored)
│   └── carry_funding_data/                <- cache funding rate orari Kraken Futures (rigenerabile, gitignored, ~1 anno)
└── pointintime_data/             <- DATASET POINT-IN-TIME REALI, tracciati in git (non rigenerabili banalmente)
    ├── sp500_pointintime_snapshots.json          <- composizione reale S&P 500 per anno, 2012-2026
    └── cmc_altcoin_pointintime_snapshots.json    <- classifica reale altcoin per market cap, 2019-2026
```

**Perche' `framework/` e' separato da `kelly_stack/`**: `metrics.py`,
`tax_engine.py` e `statistical_validation.py` sono nati dentro Kelly Stack
(rispettivamente come `_cagr`/`_sharpe`/`_max_drawdown`/`_apply_italian_tax`
private in `kelly_backtest.py`, e come `kelly_validation.py`) ma non hanno
NULLA di specifico a Kelly Stack — erano gia' importati da tre script
indipendenti in `comparative_studies/` con nomi "privati" (prefisso `_`),
un segnale chiaro che il posto era sbagliato. Promossi qui (settembre 2026,
audit "lean/frictionless/institutional" — vedi sotto) come API pubblica,
senza cambiare una riga di logica: verificato che ogni backtest gia'
riportato in questo file produce numeri IDENTICI post-spostamento
(nota: i numeri di CAGR/Sharpe di `apex_stocks_vs_etf_backtest.py` citati
nella prima versione di questa nota, 3.59%/3.38%, erano gia' corretti
*rispetto allo spostamento* ma sono stati poi trovati SBAGLIATI per un
motivo indipendente — vedi il bug periods_per_year più sotto in "Storia
delle scoperte": i numeri veri sono 16.52%/15.50%).
`kelly_backtest.py` mantiene un thin wrapper `_apply_italian_tax` per
compatibilita' con le proprie chiamate interne (fallback implicito alle
sleeve di Kelly Stack) — la versione in `framework/` richiede `tax_types`
esplicito, non ha senso che un modulo generico conosca nomi di sleeve.

## Perché esiste questa cartella (il problema che risolve)

Il rischio metodologico più insidioso in tutto questo progetto è il
**survivorship bias / point-in-time bias**: testare una strategia di
selezione titoli/monete usando l'universo di ELIGIBILITÀ di OGGI applicato
retroattivamente al passato. È il "finding critico #1" che ha bocciato
l'audit originale di Apex v1 (vedi `APEX_V2_SPEC.md` §8.23 in root) — e lo
stesso errore, in classe, che si commetterebbe testando l'altseason con
"ETH e SOL" del 2026 applicati al 2020, o l'universo S&P 500 di oggi
applicato al 2013. `pointintime_data/` esiste per eliminare strutturalmente
questo errore: non contiene prezzi, contiene **chi era davvero eleggibile
quando**.

## Come eseguire tutto

Dalla root del repo (o da qualunque cwd — lo script risolve il percorso):

```bash
# UN comando per tutta la suite veloce/deterministica (framework + kelly_stack + core_regression, 103 test):
./validation_suite/run_fast_suite.sh

# equivalente esplicito, se preferisci pytest direttamente:
PYTHONPATH=. python -m pytest validation_suite/ -v

# Studi comparativi (lenti — minuti, non secondi; scaricano/cacheano prezzi reali alla prima esecuzione;
# esclusi apposta da pytest.ini/CI — vedi sotto):
python validation_suite/comparative_studies/apex_stocks_vs_etf_backtest.py
python validation_suite/comparative_studies/altcoin_vs_btc_backtest.py
python validation_suite/comparative_studies/sector_cap_grid_test.py
```

Installazione: `pip install -r requirements.txt -r validation_suite/requirements-test.txt`
(il secondo file aggiunge solo `pytest`, non richiesto dall'app in produzione).

In CI (`.github/workflows/ci.yml`) `run_fast_suite.sh`-equivalente gira
automaticamente su ogni push/PR verso `main`, tranne gli studi comparativi
in `comparative_studies/` (troppo lenti/dipendenti da rete per un gate di
CI — restano strumenti da lanciare a mano quando serve rispondere a una
domanda specifica).

## Il framework di invalidazione istituzionale (`framework/statistical_validation.py`)

Kit generico di statistica anti-overfitting, implementato da zero senza
scipy (solo `math.erf` e l'algoritmo di Acklam per l'inversa della normale),
pensato per essere riusato su QUALSIASI backtest di questo repository:

- `deflated_sharpe_ratio(...)` — corregge lo Sharpe osservato per il numero
  di varianti/parametri testati (senza, un Sharpe "buono" è spesso solo il
  massimo di una ricerca su molte configurazioni: il classico overfitting
  da backtest).
- `pbo_cscv(...)` — Probability of Backtest Overfitting via Combinatorially
  Symmetric Cross-Validation (rif. Bailey/Lopez de Prado): stima quanto è
  probabile che la configurazione "migliore" in-sample sia la peggiore
  out-of-sample.
- `block_bootstrap_ci(...)` — intervalli di confidenza via block bootstrap
  (preserva l'autocorrelazione seriale, a differenza di un bootstrap i.i.d.
  naive) — usato più volte in questa sessione per scoprire che differenze
  di Sharpe che sembravano decisive su un solo split erano dentro l'errore
  campionario.

Se prossimamente si vuole validare un'altra strategia (o un'altra variante
di Apex/Convex) con lo stesso rigore, **importare da qui**, non
reimplementare — vedi `framework/test_statistical_validation.py` per
esempi d'uso, e `core_regression/test_apex_v2_institutional_validation.py`
per un'applicazione reale (non su dati sintetici).

### Applicato per la prima volta alla strategia LIVE (Apex V2), non solo a Kelly Stack

Fino a settembre 2026 questo framework era stato usato SOLO su Kelly Stack
(un pilastro esplorato e scartato) — mai sulla strategia che gestisce
davvero soldi. `test_apex_v2_institutional_validation.py` chiude il gap,
leggendo la vera serie di rendimenti mensili di Apex V2
(`apex_monthly_returns_extended.csv`/`_gross.csv` in root, la stessa dietro
le cifre di dashboard):

- **DSR sul campione pieno (142 mesi)**: >0.999 anche assumendo 100 varianti
  testate prima di questa (il numero esatto di trial non è ricostruibile con
  precisione dalla storia documentata in `APEX_V2_SPEC.md` §8 — riportiamo
  una griglia 20/50/100 invece di un numero taroccato di precisione).
- **DSR sul periodo TEST fuori campione (72 mesi, 2020-09-30 in poi, mai
  usato per scegliere i parametri)**: Sharpe osservato 0.80, DSR >0.999
  anche a 100 trial.
- **CI 90% (block bootstrap) sullo Sharpe TEST**: [0.15, 1.41] — esclude
  comodamente lo zero.

Verdetto: l'alpha di Apex V2 fuori campione **resiste** a questi strumenti —
DSR alto e CI che esclude lo zero anche sotto ipotesi pessimistiche sul
numero di tentativi fatti. Non è una prova di verità assoluta (il numero di
trial resta una stima, non un conteggio esatto, e nessuno di questi
strumenti puo' escludere un regime futuro diverso dal campione storico) ma
è la prova più severa che questo progetto abbia applicato alla propria
strategia live, e il risultato è positivo.

## I dataset point-in-time

### `sp500_pointintime_snapshots.json`
Composizione reale dell'indice S&P 500 per ciascun anno 2012-2026,
ricostruita scaricando le revisioni storiche della pagina Wikipedia "List
of S&P 500 companies" (non l'elenco di oggi applicato al passato). Formato:
`{"<anno>": ["TICKER", ...]}`. Alcuni anni (rate-limit Wikipedia al momento
dello scraping) usano il fallback dell'anno più vicino disponibile — vedi
`eligible_universe_for_year()` in `comparative_studies/apex_stocks_vs_etf_backtest.py`.
Rigenerazione: non banale (soggetta a rate-limit 429 pesante), lo script di
scraping non è nel repo — se va rifatto, ripartire dal principio (revisioni
`action=query&prop=revisions` + `action=raw&oldid=X`, parsing dei template
`{{NyseSymbol|X}}`/`{{NasdaqSymbol|X}}`, salvataggio incrementale anno per
anno con backoff lungo ed escalation sui retry).

### `cmc_altcoin_pointintime_snapshots.json`
Classifica reale delle criptovalute per capitalizzazione di mercato in
istanti storici (trimestrali, 2019-2026), scaricata dalle pagine storiche
di CoinMarketCap (`coinmarketcap.com/historical/YYYYMMDD/`) via Wayback
Machine — stesso principio del dataset S&P 500: quali erano davvero le
altcoin più rilevanti in un dato momento, non ETH/SOL di oggi applicate
retroattivamente al 2020. Formato: `{"<data_target>": {"actual_capture_date":
"<YYYYMMDD della cattura reale usata>", "coins": [{"rank", "symbol", "name",
"market_cap"}, ...]}}` — non tutte le date target hanno una cattura
Wayback esatta, quindi si usa la cattura archiviata più vicina (differenza
in giorni riportata implicitamente dal campo `actual_capture_date`).
Rigenerazione: `comparative_studies/../fetch_cmc_pointintime_v3.py` (script
di raccolta, vive fuori dal repo nello scratchpad di sessione — se serve
rifarlo: 1 query CDX Wayback per anno con `matchType=prefix` per elencare
le date realmente archiviate, poi scelta della più vicina alla data target,
poi fetch della pagina e parsing del JSON `__NEXT_DATA__` embedded, campo
`props.initialState.cryptocurrency.listingHistorical.data`).

**Uso previsto**: definire, per ogni trimestre, l'universo delle "top N
altcoin per market cap" realmente eleggibili in quel momento (escludendo
stablecoin e wrapped/staked token), da usare per ricostruire una strategia
di rotazione/altseason senza il bias del "le altcoin di oggi sono sempre
state ETH e SOL" — lavoro in corso, vedi "Storia delle scoperte" sotto.

## Storia delle scoperte rilevanti (aggiornare ad ogni risultato nuovo)

- **Audit "lean/frictionless/institutional" (settembre 2026)**: promosse a
  `framework/` le funzioni generiche nate dentro Kelly Stack (vedi sopra);
  aggiunto `pytest.ini` + `conftest.py` + `run_fast_suite.sh` (un comando
  per tutta la suite veloce, prima servivano 4+ comandi diversi); aggiunta
  `test_apex_v2_institutional_validation.py` (DSR/PBO/bootstrap sulla vera
  strategia live, non solo su Kelly Stack — vedi sopra). Verificato che nel
  codice esistente le uniche `except Exception` "silenziose" trovate sono
  fail-open deliberati e documentati (es. `fetch_sector`), non bug.
- **Cap settore (`V2_MAX_PER_SECTOR`)**: grid search reale {nessun vincolo,
  2, 3, 4, 5}/settore (`sector_cap_grid_test.py`) — performance
  indistinguibili su tutta la griglia (CAGR netto 16,4-16,5%, Sharpe 1,08
  su tutte le configurazioni); l'unica variabile che cambia in modo
  monotono è la concentrazione peggiore (13,3%→80% allentando il cap).
  Confermato: il valore adottato in produzione (2) non è mai stato altro
  nella storia del codice (`git log -S "V2_MAX_PER_SECTOR"`), e resta la
  scelta corretta (stesso rendimento, massima protezione).
- **Dimensione del basket azionario (`V2_EQUITY_TOP_N`)**: grid search reale
  {10, 12, 15, 18, 20, 25} titoli, buffer_rank=N+5
  (`apex_basket_size_grid_test.py`) — completa il singolo confronto
  15-vs-20 già in APEX_V2_SPEC.md §8.27. Performance indistinguibili
  (CAGR netto 16,1-16,6%, Sharpe 1,06-1,09); PBO-CSCV 51,4% (esattamente
  al livello del "lancio di moneta" — nessuna taglia batte le altre in modo
  robusto). Il "migliore" nominale (top_n=12, Sharpe 1,09) ha una CI 90%
  bootstrap [0,61; 1,58] che include comodamente lo Sharpe dell'attuale
  (1,08) — nessun cambiamento consigliato.
- **Dimensione delle posizioni per classe macro (`base_weight_per_class`/
  `vol_target`)**: griglia di 9 combinazioni attorno all'attuale 50%/22%
  ("Percorso B", §8.25/§8.28), incl. il valore precedente 25%/13% e —
  richiesto esplicitamente dall'utente ("hai provato senza tetto?") — 2
  configurazioni "nessun tetto" (`base_weight_per_class=1.0`, l'unico
  limite resta la rinormalizzazione strutturale "mai a leva" sempre attiva
  in `compute_v2_macro_signal`, non un tetto nominale per classe)
  (`apex_class_size_grid_test.py`) — richiesto esporre `base_weight_per_class`/
  `vol_target` come parametri della funzione (prima letterali hardcoded,
  default invariati, 3 nuovi test di regressione).
  Risultato: Sharpe netto sostanzialmente PIATTO su tutta la griglia
  (1,00-1,11), **incluso "nessun tetto" (100%/22%): Sharpe 1,07, CAGR
  16,71%, MaxDD -22,46% — praticamente indistinguibile dall'attuale 50%**
  (Sharpe 1,08, CAGR 16,50%, MaxDD -21,60%). PBO-CSCV 52,9% su tutte e 9
  (nessuna combinazione batte le altre in modo robusto), CI 90% sul
  "migliore" nominale (25%/13%, Sharpe 1,11) [0,65; 1,59] include
  comodamente l'attuale. CAGR e MaxDD invece SALGONO insieme in modo
  monotono con l'esposizione (25%/13%: CAGR 10,2%/MaxDD -12,5% → 50%/35%:
  CAGR 20,7%/MaxDD -28,0%) — un vero trade-off rischio/rendimento lungo
  una frontiera, non un pasto gratis. **Perché "nessun tetto" non cambia
  nulla**: con 4 classi e volatilità realizzata tipica, la rinormalizzazione
  strutturale (mai superare 100% aggregato) interviene comunque quasi
  sempre — il tetto nominale per classe (35%, 50%, 75%, o assente) conta
  molto meno di quanto ci si aspetterebbe, perché il vincolo aggregato fa
  già il lavoro reale di controllo del rischio. **Conferma indipendente**,
  con strumenti mai usati nella ricerca originale (PBO/DSR/bootstrap), di
  quanto §8.19/§8.21/§8.25 avevano già trovato con la ricerca originale:
  "Percorso B" è una scelta di rischio esplicita su un plateau reale, non
  un punto Sharpe-ottimo nascosto — e nessun punto della griglia (tetto
  rimosso incluso) lo batte su Sharpe in modo che regga a un controllo di
  overfitting.
- **Trailing stop attivato dal profitto su BTC e Oro** — domanda diretta
  dell'utente ("una volta andati un po' in profitto, ha senso uno stop?"),
  mai testato prima (`apex_profit_trailing_stop_test.py`, nuovo overlay
  `apply_profit_activated_trailing_stop`: lo stop resta disarmato finché il
  guadagno dall'ingresso non supera una soglia, poi traccia il picco e
  esce se il prezzo scende oltre una distanza dal picco — verificato prima
  su un caso sintetico per il timing corretto, nessun lookahead). Risultato
  **negativo e netto, non marginale**: OGNI configurazione testata (arma
  10-20% / trail 10-15%) PEGGIORA sensibilmente rispetto a nessuno stop —
  Sharpe crolla da 1,08 a 0,61-0,75, Calmar da 0,76 a 0,34-0,53. PBO-CSCV
  17,1% (basso: il risultato "nessuno stop vince" è consistente tra i
  sotto-periodi, non un caso isolato). Causa identificata: le settimane
  BTC attive crollano da 332 a 132-188 — lo stop scatta spesso e tiene BTC
  FUORI dal portafoglio proprio durante le sue tipiche correzioni-dentro-
  il-trend (BTC può correggere 15-20%+ senza che il rialzo di fondo sia
  finito), tagliando fuori il resto del rally. L'Oro non ne risente quasi
  (329-330 settimane attive contro 330 di base — troppo poco volatile
  perché uno stop 10-15% scatti spesso). **Verdetto: no, non ha senso** —
  almeno con questa formulazione (trailing dal picco post-attivazione);
  il costo di uscire da un trend BTC ancora valido supera ampiamente il
  beneficio di protezione dal drawdown.
- **Veicolo di esecuzione della gamba Crypto: perp vs spot vs ETP (WBTC)**
  — due domande dirette dell'utente ("perp è la scelta peggiore secondo le
  mie analisi, WBTC/ETP sarebbe la migliore per costi, ma non tratta 24/7:
  rischio di rompere la strategia?"), `apex_crypto_execution_venue_test.py`.
  Segnale invariato (BTC-USD continuo, come in produzione) in tutti e tre
  gli scenari — cambia solo come si realizza il rendimento della classe
  Crypto una volta che il segnale dice di essere dentro. WBTC-ETFP.MI su
  Yahoo non ha storico utilizzabile (un solo punto dati) — usato IBIT
  (iShares Bitcoin Trust) come proxy strutturale onesto (stessa meccanica:
  NAV tracking, arbitraggio creation/redemption, chiuso weekend/festivi),
  storico reale dal 2024-01 (~2,7 anni).
  - **Sulle ore/giorni di mercato chiuso**: MaxDD IDENTICO tra perp/spot/ETP
    (-10,74% nella finestra comune) — il wrapper ETP non introduce drawdown
    aggiuntivo dal fatto di non tradare 24/7 (conferma, dentro il backtest
    vero di Apex, quanto già trovato in astratto con IBIT vs BTC: il
    wrapper insegue il prezzo senza deriva sistematica). La differenza di
    CAGR ETP vs perp è -0,96pp (14,39% contro 15,35%) sulla finestra IBIT.
    **Confronto accoppiato diretto** (perp meno ETP, stessa settimana,
    stesso indice — più potente delle due CI separate, che si sovrappongono
    anche a fronte di una differenza sistematica): overperformance media
    del perp +0,82pp/anno, ma CI 90% (block bootstrap) [-0,02; +1,35]pp/anno
    — **include lo zero per un pelo**, e il perp ha fatto meglio dell'ETP
    solo in 53/139 settimane (38%) — la sua overperformance aggregata viene
    da poche settimane con scarti grandi, non da un vantaggio settimanale
    diffuso. **Risposta: no, non rompe la strategia** — un costo reale ma
    modesto (~1pp/anno, in gran parte il TER 0,15%), alla soglia della
    significatività statistica su questo campione corto (~2,7 anni), non
    un problema strutturale.
  - **Sui costi, risultato che CONTRADDICE l'ipotesi di partenza
    dell'utente**: il perpetual su Kraken NON è la scelta peggiore in
    questo backtest — è la MIGLIORE o alla pari. Sample completo (586
    settimane): perp CAGR netto 17,02%/Sharpe 1,11 > spot 26% 16,57%/1,09 >
    spot 33% 13,83%/0,96. La fee taker perp (0,05%) è molto più bassa di
    quella spot (0,26%), e il funding REALE osservato su Kraken Futures
    (~1 anno di dati, non stimato) è stato leggermente NEGATIVO
    (-3,30%/anno, cioè i long sono stati PAGATI, non hanno pagato) in
    questo periodo — un vantaggio aggiuntivo per il perp, non un costo.
    **Limite dichiarato**: il funding è stimato su un solo anno di storico
    reale disponibile (limite dell'API Kraken, vedi anche
    `altcoin_carry_funding_rate_test.py`) — se in periodi diversi il
    funding fosse stato tipicamente positivo (i long pagano, comune nei
    bull market con eccesso di posizioni long), il vantaggio del perp
    sarebbe minore o potrebbe invertirsi. La componente fee (0,05% vs
    0,26%) resta invece un vantaggio strutturale del perp indipendente dal
    regime di funding. Lo spot al 33% (nota dell'utente, non l'aliquota
    26% "redditi diversi" standard già usata ovunque in questo progetto
    per crypto — mostrato come scenario alternativo, non validato in modo
    indipendente) è in ogni caso il peggiore delle tre vie.
  - **Durata delle posizioni Crypto (funding vs TER)**, in risposta alla
    domanda diretta dell'utente "hai calcolato anche quanto stanno aperte
    le posizioni?": il modello di costo non usa un conteggio esplicito di
    giorni aperti — moltiplica il drag (funding continuo o TER annuale)
    per il peso Crypto vol-target-scalato prima di sommare, cosa che
    proporziona automaticamente entrambi i costi all'esposizione reale
    (zero quando la classe è chiusa, ~27% quando attiva) invece che a un
    conteggio forfettario giorni-aperti × costo/giorno — più corretto
    perché due episodi di pari durata calendariale ma vol-target diverso
    pagano costi diversi, come nella realtà. Numeri effettivi (storico
    Apex completo, 586 settimane): **56,7%** delle settimane con Crypto
    attiva, **12 episodi continui** di durata media **27,7 settimane**
    (mediana 20, range 2-121), esposizione media quando attiva **26,7%**.
    Sulla finestra IBIT (139 settimane): 54,0% attiva, 5 episodi, durata
    media 15,0 settimane (mediana 22). Con episodi mediani di ~20
    settimane, il funding Kraken (che matura ora per ora) si accumula per
    mesi consecutivi di esposizione continua — l'orizzonte corretto per
    confrontarlo con il TER annuale, non giorni isolati.
- **Pesi target di Convex Stack**: 9 combinazioni alternative contro
  l'attuale 45/15/25/7.5/7.5 (`convex_weights_grid_test.py`), su proxy a
  storico lungo (SPY/IEF/VBR/DBMF/GLD/BTC-USD) con TER e tassazione reali.
  **Correzione FX trovata durante lo sviluppo** (domanda diretta
  dell'utente su DBMFE): tutti gli strumenti reali di Convex sono quotati
  in EUR ma UNHEDGED (verificato empiricamente sui prezzi reali, anche se
  corti, di DBMFE.PA: la sua crescita reale combacia con DBMF convertito
  via EURUSD — 28,42% contro 28,47% reale — non con DBMF grezzo in USD,
  30,87%) — tutti i proxy USD vanno quindi convertiti in EUR prima del
  blend, non solo DBMFE. Con la correzione: PBO-CSCV 68,6% (sopra la soglia
  del 50% — un segnale ATTIVO di overfitting se si scegliesse il
  "migliore" nominale, che comunque ha una CI 90% [0,39; 1,98] che include
  ampiamente lo Sharpe attuale). **Nessuna combinazione di pesi batte
  l'attuale in modo statisticamente robusto.** La stessa correzione FX
  varrebbe anche per il backtest di Kelly Stack (usa gli stessi proxy),
  non applicata li' per non alterare silenziosamente numeri già pubblicati
  in KELLY_STACK_SPEC.md (Kelly Stack è comunque già scartata).
- **Bug fetch_sector 401**: Yahoo richiede da fine 2024 un cookie di
  sessione + crumb anche su `quoteSummary` — l'endpoint rispondeva 401 su
  ogni richiesta, disattivando silenziosamente (fail-open by design) il cap
  settoriale in produzione. Corretto in `backend.py` (root, non qui: è
  codice di produzione) con handshake `fc.yahoo.com` →
  `v1/test/getcrumb`, cache in-process. Verificato: il basket live attuale
  rispettava comunque il cap per coincidenza (max 2/settore reale su 15
  posizioni), quindi nessuna correzione necessaria al track record già
  mostrato in dashboard.
- **Titoli individuali vs ETF (Apex)**: sul basket reale a 15 titoli,
  point-in-time, 12 anni: CAGR netto 16,52% / Sharpe 1,08 / Calmar 0,77
  contro SPY 15,50% / 1,02 / 0,62 — il basket vince su ogni metrica netta
  di tasse italiane (redditi diversi compensabili vs redditi di capitale
  non compensabili). (Numeri corretti — vedi il bug `periods_per_year`
  qui sotto: la prima versione riportava erroneamente 3,59%/0,52 e
  3,38%/0,49.)
- **Bug reale: `periods_per_year` mancante sui backtest settimanali**:
  `framework/metrics.py` (`cagr`/`sharpe`) assume di default rendimenti
  MENSILI (`periods_per_year=12`, per compatibilità con l'uso originale in
  Kelly Stack). `apex_stocks_vs_etf_backtest.py`, `sector_cap_grid_test.py`
  e `altcoin_vs_btc_backtest.py` (la versione settimanale) chiamavano
  queste funzioni su serie **settimanali** senza passare `periods_per_year=52`
  — il conteggio implicito degli anni risultava gonfiato di un fattore
  ~4,3x (52/12), sottostimando sistematicamente sia il CAGR sia lo Sharpe.
  Scoperto per caso mentre si costruiva `apex_class_size_grid_test.py` (i
  numeri di CAGR erano sospettosamente bassi per un basket azionario a 12
  anni). **Non cambia le conclusioni relative** (basket ancora meglio di
  SPY, cap settore ancora indifferente) ma cambia sostanzialmente l'entità
  assoluta di ogni numero riportato in questa sessione per quei tre script
  prima della correzione — vedi le voci sopra per i valori corretti. La
  versione daily di altcoin-vs-BTC e i backtest mensili (Kelly Stack,
  Convex, Apex institutional validation) non erano affetti (già passavano
  o non necessitavano `periods_per_year` esplicito).
- **Altcoin vs BTC (settimanale, universo fisso ETH/SOL)**: numeri corretti
  dopo il fix `periods_per_year` (era erroneamente riportato "nessun
  candidato batte BTC" — FALSO, era un artefatto del bug). Numeri veri
  (2020-04→2026-09, 336 settimane): BTC CAGR netto 45,95%/Sharpe 0,93;
  equal-weight BTC/ETH/SOL 72,89%/**1,11**; inverse-vol 58,12%/**1,02**;
  rotazione di regime 67,32%/**1,05** — TUTTI con Sharpe netto SUPERIORE a
  BTC (anche se con MaxDD peggiore su ognuno, quindi non "rischio pari o
  minore"). **Perché questo risultato non è affidabile quanto quello
  daily/point-in-time sotto**: l'universo qui è FISSO a ETH+SOL, scelti a
  memoria — esattamente il tipo di bias che il dataset point-in-time
  altcoin è stato costruito per eliminare (SOL è oggi un vincitore
  evidente, ma non esisteva prima di aprile 2020 ed era irrilevante come
  "alt principale" fino al 2021 Q4 — vedi la tabella dei top-5 per
  trimestre più sopra). L'edge del candidato di regime resta comunque
  concentrato in 2 soli episodi (CAGR netto 67,32%→14,35% escludendoli,
  16% delle settimane) — la fragilità è confermata anche coi numeri giusti.
- **Altcoin vs BTC (daily, universo point-in-time reale, top-3/top-5 alt per
  trimestre) — LA VERSIONE AFFIDABILE**: non conferma il risultato
  settimanale (v. sopra) — con l'universo REALE point-in-time invece di
  ETH/SOL fissi, il quadro si ribalta di nuovo. Design molto più esigente
  (5 candidati, incl. uno switch "BTC rallenta ->
  singola alt migliore" mai testato prima, PBO-CSCV + DSR + bootstrap CI).
  BTC buy&hold resta il migliore su ogni metrica netta (CAGR 38,0%, Sharpe
  0,84, MaxDD -76,6%, 2019-2026). Il candidato più vicino (inverse-vol
  BTC+top-3) arriva a CAGR netto 31,2%/Sharpe 0,75 — sotto BTC su
  CAGR e Sharpe, con MaxDD di poco migliore ma non abbastanza da qualificarsi
  come "rischio pari o minore CON rendimento pari o migliore". Rotazione
  momentum e switch su rallentamento BTC sono attivamente dannosi (CAGR
  netto negativo in 3 configurazioni su 4): l'alta frequenza di liquidazioni
  totali su un asset molto volatile realizza l'intera plusvalenza accumulata
  ad ogni cambio di posizione, un drag fiscale che si compone e che i
  whipsaw di momentum non ripagano. L'edge del candidato "regime altseason"
  resta concentrato in 2 episodi (~5% dei giorni, 2021 e 2025) — escluderli
  fa crollare il CAGR netto (top-3: 2,71%→-6,66%; top-5: 10,73%→2,75%),
  stessa fragilità già trovata in settimanale. **Bug reale trovato e corretto
  durante lo sviluppo**: la prima versione applicava il peso deciso al giorno
  t al rendimento dello STESSO giorno t (nessun `.shift(1)`, nonostante il
  docstring lo dichiarasse) — un look-ahead che produceva CAGR lordi
  assurdi (423%-1093%) prima della correzione; buon esempio del perché
  ogni risultato numerico va sanity-checked per plausibilità, non solo
  fatto girare. Vedi `altcoin_vs_btc_daily_backtest.py` per il codice e
  l'output completo.
- **Altcoin vs BTC (weekly, universo point-in-time reale) — isola la vera
  causa del ribaltamento sopra**: il confronto settimanale-fisso vs
  daily-point-in-time cambiava DUE variabili insieme (granularità E
  universo), quindi non diceva quale delle due spiegasse il ribaltamento.
  `altcoin_vs_btc_weekly_pointintime_backtest.py` tiene fisso l'universo
  reale point-in-time e cambia SOLO la granularità (settimanale invece di
  daily, finestre di lookback riscalate a parità di arco di calendario).
  Risultato: **torna a essere BTC il migliore** (Sharpe 0,82, esattamente
  come il candidato migliore in assoluto su 5, PBO-CSCV 10-21% — un segnale
  di edge robusto, ma il "vincitore" è BTC stesso, non un'alternativa).
  Conferma in modo pulito che **la causa del ribaltamento nel test
  settimanale originale era l'universo fisso ETH/SOL (survivorship bias),
  non la granularità del segnale** — a parità di universo corretto,
  settimanale e daily concordano. L'edge del candidato "regime altseason"
  resta concentrato in 2 episodi anche qui (CAGR netto 10,36%→0,65% (top-3)
  e 12,41%→1,03% (top-5) escludendoli) — la fragilità è quindi una
  proprietà del candidato, non della granularità o dell'universo.
  **Verdetto (aggiornato dalla voce successiva)**: nessuna granularità,
  nessun universo (fisso o point-in-time) tra i candidati provati FINO A
  QUESTO PUNTO produce un'alternativa a BTC buy&hold che sia
  contemporaneamente migliore E meno rischiosa in modo robusto — l'unico
  modo in cui un'alternativa "vince" è scegliere a memoria un universo che
  include, col senno di poi, i vincitori (ETH/SOL).
- **Famiglie di strategia sistematiche su altcoin (momentum, mean
  reversion, low volatility, trend following, stop-loss)** — richiesto
  esplicitamente dall'utente, `altcoin_strategy_families_pointintime_test.py`:
  10 candidati (i 3 già noti + momentum/mean-reversion/low-vol/trend-following
  nuovi + stop-loss -15% su momentum e mean-reversion), stesso universo
  point-in-time daily, PBO-CSCV su tutti e 10 insieme (14,3%/11,4% —
  basso, cioè un segnale di edge non spurio: BTC vince in modo consistente
  tra i fold, non per coincidenza di un singolo periodo).
  - **Momentum** (rotazione sul vincitore) e **mean reversion** (contrarian
    sul più scaduto): entrambi PEGGIO di BTC e spesso CAGR netto negativo
    (-23,9%/-33,8% momentum; -11,5%/-23,3% mean reversion) — l'alta
    liquidazione totale su un asset volatile realizza l'intera plusvalenza
    ad ogni cambio (stesso meccanismo già visto), e la mean reversion in
    particolare sembra "comprare il coltello che cade" più che un vero
    rimbalzo.
  - **Low volatility** (possiede il singolo asset a vol più bassa nel
    pool): il candidato più interessante dei nuovi — MaxDD netto
    REALMENTE migliore di BTC (-65,8%/-64,4% contro -76,6%), ma CAGR netto
    molto più basso (15,1%/13,1% contro 38,0%) — su Sharpe/Calmar BTC vince
    comunque perché il suo rendimento compensa ampiamente il rischio
    maggiore. Non è un'alternativa "migliore", ma è l'unico candidato con
    un profilo di rischio genuinamente diverso (utile se l'obiettivo fosse
    minimizzare il drawdown assoluto, non massimizzare Sharpe).
  - **Trend following** (filtro di media mobile per asset, può andare CASH
    se nessuno è in uptrend): vol realizzata inferiore a BTC in entrambe le
    configurazioni (57-59% contro 59,5%) ma Sharpe comunque sotto
    (0,47/0,40 contro 0,84) — il costo dei whipsaw all'entrata/uscita del
    trend supera il beneficio di stare fuori mercato nei ribassi.
  - **Stop-loss (-15%) su momentum e mean reversion**: effetto MISTO, non
    un miglioramento pulito. Su momentum aiuta leggermente (Sharpe
    0,08→0,13 e -0,01→0,05) ma resta negativo. Su mean reversion
    PEGGIORA (0,29→0,22 e 0,18→0,03) — uno stop-loss su una strategia
    contrarian rischia di uscire proprio nel momento di massimo
    ipervenduto, tagliando fuori il rimbalzo che la strategia sta
    scommettendo di catturare. Lo stop-loss non è quindi un miglioramento
    universale: dipende dalla natura della strategia sottostante.
  - **Carry** (funding rate dei perpetual, `altcoin_carry_funding_rate_test.py`):
    **limite dichiarato** — lo storico reale disponibile via API pubblica
    (Kraken Futures) copre SOLO ~1 anno (2025-09/2026-09), non i 6-7 anni
    degli altri test; il verdetto è quindi molto meno solido. Su questo
    campione corto: il funding annualizzato è piccolo per tutti gli asset
    testati (BTC -3,3%, ETH -3,1%, SOL +0,2%, XRP -0,8%, ADA +2,0%, DOGE
    -2,1% — "yield al long", negativo quando i long pagano di più di
    quanto ricevono), e un tilt direzionale verso il funding più
    favorevole ha fatto MOLTO peggio di BTC semplice (CAGR -65,7% contro
    -29,1% su questo specifico anno, entrambi negativi perché il campione
    cade in una fase di mercato debole) — il segnale di funding non ha
    protetto né sovraperformato. Non testato: un vero carry market-neutral
    (long spot + short perpetual, che richiederebbe modellare anche la
    gamba short, non presente altrove in questo framework long-only).
  - **Verdetto complessivo aggiornato**: su TUTTE le famiglie di
    strategia sistematica provate finora (momentum, mean reversion, low
    vol, trend following, regime/switch su BTC, inverse-vol, stop-loss,
    carry) — nessuna batte BTC buy&hold in modo robusto su Sharpe/Calmar,
    netto tasse e costi reali, su nessun universo (point-in-time incluso)
    o granularità testata. Questo NON dimostra che sia impossibile in
    assoluto, ma il campo di ricerca esplorato è ormai ampio e coerente
    con un solo esito.

## Cosa NON è (ancora) qui, e perché

- I moduli di produzione (`apex_v2_engine.py`, `convex_engine.py`,
  `backend.py`, `app.py`, `portfolio_manager.py`, le pagine Streamlit) sono
  **volutamente rimasti in root**: sono importati da CI per path esplicito
  e servono al sistema live — spostarli avrebbe un raggio d'azione molto
  più ampio di questa riorganizzazione, puramente di test/validazione/dati.
- `.github/workflows/ci.yml` è stato aggiornato per puntare ai nuovi
  percorsi (`validation_suite/core_regression/...`) e aggiunge
  `PYTHONPATH=.` così i test qui dentro continuano a importare i moduli di
  produzione dalla root senza modificarne il codice; ha anche aggiunto
  l'esecuzione della suite Kelly Stack, che prima non era in CI.
