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
│   ├── sector_cap_grid_test.py            <- grid search reale su V2_MAX_PER_SECTOR (2 vs 3 vs 4 vs 5 vs nessuno)
│   ├── apex_stocks_data/                  <- cache prezzi (rigenerabile, gitignored)
│   ├── altcoin_data/                      <- cache prezzi settimanali (rigenerabile, gitignored)
│   └── altcoin_daily_data/                <- cache prezzi daily (rigenerabile, gitignored)
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
(`apex_stocks_vs_etf_backtest.py`: 3.59%/3.38% CAGR netto, invariati).
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
  indistinguibili su tutta la griglia (CAGR entro 3bps, Sharpe identico a 2
  decimali); l'unica variabile che cambia in modo monotono è la
  concentrazione peggiore (13,3%→80% allentando il cap). Confermato: il
  valore adottato in produzione (2) non è mai stato altro nella storia del
  codice (`git log -S "V2_MAX_PER_SECTOR"`), e resta la scelta corretta
  (stesso rendimento, massima protezione).
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
  point-in-time, 15 anni: CAGR netto 3,59% / Sharpe 0,52 / Calmar 0,17
  contro SPY 3,38% / 0,49 / 0,13 — il basket vince su ogni metrica netta di
  tasse italiane (redditi diversi compensabili vs redditi di capitale non
  compensabili).
- **Altcoin vs BTC (settimanale, universo fisso ETH/SOL)**: nessun candidato
  testato (equal-weight, inverse-vol, rotazione momentum, rotazione di
  regime "altseason") batte BTC buy&hold a parità o minor rischio; la
  strategia di regime più promettente concentra il 100% del suo apparente
  edge in 2 soli episodi su un campione di 6 anni (2021 e 2023-24) — non è
  un edge robusto.
- **Altcoin vs BTC (daily, universo point-in-time reale, top-3/top-5 alt per
  trimestre)**: confermato e rafforzato il risultato settimanale con un
  design molto più esigente (5 candidati, incl. uno switch "BTC rallenta ->
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
