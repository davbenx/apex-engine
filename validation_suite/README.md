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
│   ├── apex_add_commodities_test.py       <- aggiungere Commodities (DBC beta vs PDBC carry) ad Apex: correlazione + backtest (nessun miglioramento robusto)
│   ├── apex_diversifier_candidates_test.py <- Currency (UUP) / TIPS (TIP) / Managed Futures (DBMF) / Trend (KMLM) / Commodity Carry (UEQC) / FX Carry (DBV) come 5a classe (negativi significativi: TIP, DBV)
│   ├── apex_risk_parity_signal_test.py    <- peso inversamente proporzionale alla volatilita' invece di nozionale uguale (risultato: peggiora nettamente, non adottare)
│   ├── apex_bond_value_signal_test.py     <- value tilt su Bonds via percentile rendimento Treasury 10Y (nessun miglioramento robusto)
│   ├── apex_beta_basket_selection_test.py <- basket azionario selezionato per basso BETA (Betting Against Beta) invece che bassa volatilita' (candidato piu' promettente della sessione, non ancora significativo)
│   ├── apex_momentum_crash_stress_test.py <- diagnostico: le uscite dell'isteresi sono seguite da rimbalzi anomali? (risultato: no, isteresi robusta)
│   ├── apex_theory1_theory5_second_round_test.py <- secondo giro di verifica per Teoria #1/#5: sensibilita' parametro, stacking, train/test split (nessuna delle due confermata in modo pulito)
│   ├── apex_theory1_rolling_attribution_test.py <- terzo giro Teoria #1: Sharpe rolling + attribuzione per classe (risultato: falsificata, edge quasi interamente da BTC 2017-2022, non riproporre)
│   ├── apex_theory5_lookback_finegrid_test.py <- terzo giro Teoria #5: griglia fine di 9 lookback (risultato: rafforzata, vantaggio consistente su banda 16-33 settimane, non un punto isolato)
│   ├── apex_stable_beta_basket_test.py    <- quarto giro Teoria #5: beta medio su 4 finestre (13/26/39/52 sett.) invece di un singolo lookback (risultato: piu' debole dei migliori lookback singoli, l'edge sembra specifico a una banda di medio termine)
│   ├── apex_theory5_band_ensemble_test.py <- quinto giro Teoria #5: ensemble di 6 basket indipendenti scoped sulla banda 22-33 sett. (risultato: effetto reale e consistente ma al limite della risoluzione statistica di ~11 anni di dati, valore marginale decrescente per ulteriori giri sullo stesso parametro)
│   ├── apex_theory5_walkforward_selection_test.py <- checklist produzione Teoria #5, gap #1: selezione del lookback walk-forward (mai guardando dati futuri) — banda confermata stabile, ma la selezione adattiva non batte un lookback fisso
│   ├── apex_theory5_composition_turnover_test.py <- checklist produzione Teoria #5, gap #3/#4: turnover e composizione settoriale quasi identici tra low-vol e low-beta, ma sovrapposizione titoli effettivi solo 6.9%
│   ├── apex_theory5_crash_and_signal_test.py <- checklist produzione Teoria #5, gap #5/#6: low-beta meno correlato a SPY (-0.067) e protegge nei bear market lenti (2022, +6.46pp) ma non nei panici acuti (COVID 2020, leggermente peggio)
│   ├── apex_theory5_exit_criterion_test.py <- checklist produzione Teoria #5, gap #7: switching adattivo low-vol/low-beta basato su Sharpe rolling (risultato: peggiora rispetto a una scelta fissa, non adottare un interruttore automatico)
│   ├── apex_beta_basket_size_grid_test.py <- numero di titoli nel basket low-beta (risultato: 15, il valore attuale, e' gia' il migliore)
│   ├── apex_beta_class_weight_test.py     <- pesare le classi macro per beta vs SPY invece che per volatilita' assoluta (risultato: falsificato nettamente, stesso meccanismo di fallimento della risk parity)
│   ├── altcoin_low_beta_weekly_test.py    <- low-beta pick sulle altcoin a granularita' weekly con finestre beta piu' lunghe (risultato: batte BTC con finestra 26 sett., ma segnale statistico debolissimo, PBO ~45%)
│   ├── apex_equity_qqq_swap_test.py       <- sostituire SPY con QQQ (segnale/basket/tasse isolati) per la gamba Equity
│   ├── apex_equity_long_short_overlay_test.py <- long/short su Equities con SH reale invece di long/flat (risultato: peggiora in modo significativo, non adottare)
│   ├── apex_continuous_trend_signal_test.py <- peso continuo scalato per forza del trend invece di binario (promettente ma non ancora significativo)
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

- **DSR sul campione pieno (471 mesi, esteso a 1987-06 con proxy
  VFINX/VUSTX/GC=F dopo il passaggio a select_low_beta_basket — vedi Storia
  sotto)**: >0.999 anche assumendo 100 varianti testate prima di questa (il
  numero esatto di trial non è ricostruibile con precisione dalla storia
  documentata in `APEX_V2_SPEC.md` §8 — riportiamo una griglia 20/50/100
  invece di un numero taroccato di precisione).
- **DSR sul periodo TEST fuori campione (72 mesi, 2020-09-30 in poi, mai
  usato per scegliere i parametri, INVARIATO dall'estensione storica)**:
  Sharpe netto osservato 0.96, DSR >0.999 anche a 100 trial.
- **CI 90% (block bootstrap) sullo Sharpe TEST**: [0.23, 1.58] — esclude
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
- **Aggiungere una 5a classe macro ad Apex — Commodities (DBC/PDBC) e altri
  candidati di diversificazione**, richiesta diretta dell'utente,
  `apex_add_commodities_test.py` (DBC/PDBC) e
  `apex_diversifier_candidates_test.py` (Currency/TIPS/Managed Futures/
  Trend/Commodity Carry). Tecnica di test comune: `V2_CLASS_TICKER` e' un
  dict globale di modulo (non un parametro di `compute_v2_macro_signal`) —
  sovrascritto a runtime negli script di test, mai modificato in modo
  permanente in `apex_v2_engine.py`. Ogni candidato con storico piu' corto
  del resto del paniere Apex viene confrontato con un baseline a 4 classi
  RICALCOLATO sulla stessa identica finestra (mai un confronto tra finestre
  diverse, stesso approccio di `apex_crypto_execution_venue_test.py`).
  - **DBC (Invesco DB Commodity Index Tracking Fund, beta ingenuo,
    front-month)**: correlazione con l'Equity 0,33 (PIU' alta di
    Gold-Equities 0,13 — non un diversificatore "pulito"). Aggiunto a
    588/586 settimane, PBO-CSCV (6 configurazioni incl. PDBC) **62,9%**
    (zona di allerta overfitting, peggio del caso base). Nessun
    miglioramento robusto.
  - **PDBC (Invesco Optimum Yield, "carry" long-only — sceglie il
    contratto migliore lungo la curva)**: standalone quasi identico a DBC
    (correlazione DBC-PDBC **0,99** — stesso rischio, tilt di carry
    marginale), CAGR/Sharpe standalone leggermente PEGGIORI di DBC (4,77%/
    0,35 contro 4,91%/0,36). Dentro Apex, pero', il PUNTO STIMATO e'
    costantemente migliore di DBC in ogni configurazione confrontabile
    (Sharpe 1,14-1,17 contro 1,08-1,12) — un pattern consistente, non
    isolato. **Ma non regge il test statistico**: confronto diretto PDBC
    meno DBC (stesso 40%/22%, isola l'effetto del tilt) = +0,48pp/anno,
    CI 90% **[-0,46; +0,53] include lo zero** (per un pelo). Miglior
    variante PDBC contro baseline: +0,10pp/anno, CI 90% [-3,66; +1,85].
    **Verdetto: il carry PDBC sembra sistematicamente migliore del beta
    DBC guardando i punti stimati, ma la differenza non e' distinguibile
    dal rumore su questo campione (~11 anni)** — non abbastanza per
    adottarlo, ma un pattern piu' interessante di un beta puro.
  - **UEQC.DE (UBS CMCI Commodity Carry, vero indice di carry, non
    long-only optimum-yield)** — l'ETF chiesto direttamente dall'utente:
    correlazione **~0,00 con l'Equity** (SPY +0,00, IEF +0,10, GLD -0,04,
    BTC -0,03) — il profilo di correlazione piu' pulito di qualunque
    candidato commodity testato, conferma netta della tesi di carry.
    Storico reale corto (2020-10+, 308 settimane, EUR->USD via EURUSD=X).
    Nel backtest: CAGR quasi invariato (12,04%->12,01%), Sharpe +0,05
    (0,89->0,94), MaxDD migliora (-21,60%->-17,75%). Confronto accoppiato:
    -0,15pp/anno, CI 90% [-2,35; +1,33], include lo zero. Nessun
    miglioramento statisticamente robusto, ma nessun danno nemmeno — e la
    correlazione quasi nulla lo rende il candidato piu' interessante da
    ri-testare quando avra' piu' storico (fondo lanciato nel 2020).
  - **UUP (Invesco DB US Dollar Index Bullish, valuta)**: correlazione
    negativa con TUTTO il paniere esistente (SPY -0,26, IEF -0,27, GLD
    -0,48, BTC -0,14) — profilo di diversificazione strutturalmente
    diverso dalle commodity. MaxDD migliora molto (-21,60%->-16,05%),
    Sharpe +0,07, ma CAGR leggermente peggiore (-0,68pp/anno, CI 90%
    [-2,22; +0,76], include lo zero). Nessun miglioramento robusto.
  - **TIP (iShares TIPS Bond, inflation-linked)**: correlazione 0,77 con
    Bonds/IEF esistente (quasi ridondante), overperformance -1,44pp/anno,
    CI 90% **[-2,81; -0,36] ESCLUDE lo zero**. Aggiungere TIP diluisce il
    budget di vol-target su una classe gia' rappresentata senza aggiungere
    diversificazione reale. **Verdetto: non aggiungere.**
  - **DBV (Invesco DB G10 Currency Harvest, FX carry classico — long le
    valute alto rendimento, short le basso rendimento)**: completa insieme
    a UEQC il test della teoria del carry cross-asset unificato
    (Koijen-Moskowitz-Pedersen-Vrugt 2018). **Due problemi, non uno**: (1)
    il fondo e' stato LIQUIDATO — lo storico dati finisce 2023-03-17, non
    e' piu' investibile oggi, dichiarato non nascosto; (2) anche
    storicamente il risultato e' negativo e statisticamente significativo,
    -1,93pp/anno, CI 90% **[-3,67; -0,49] ESCLUDE lo zero**. Coerente con
    la letteratura: il carry FX ha correlazione positiva con l'equity
    (+0,34 qui, la piu' alta di tutti i candidati commodity/valuta
    testati) perche' si "smonta" violentemente negli stessi episodi di
    risk-off in cui l'equity crolla — non e' un buon diversificatore per
    costruzione, oltre a non essere piu' disponibile. **Verdetto: non
    aggiungere, doppiamente squalificato.**
  - **DBMF (iMGP DBi Managed Futures, stesso proxy US di DBMFE in Convex)**
    e **KMLM (KFA/Mount Lucas, trend-following puro)**: profili di
    correlazione interessanti — KMLM negativo sia con SPY (-0,21) sia con
    IEF (-0,39) simultaneamente, il piu' pulito di tutta l'indagine dopo
    UEQC. Storico corto (DBMF 2020+/344 sett., KMLM 2021+/262 sett.) su
    una finestra Apex particolarmente debole (baseline ricalcolato:
    CAGR 12,21%/7,49% contro 16,50% storico completo — 2022 e' un anno
    duro sia per equity sia per bond). Entrambi mostrano MaxDD migliore
    e Sharpe leggermente migliore, ma differenze paired minuscole e
    ampiamente dentro l'intervallo di rumore (DBMF -0,06pp CI [-2,59;
    +2,54], KMLM +0,18pp CI [-4,31; +3,89]). Campione troppo corto per
    un verdetto definitivo in un senso o nell'altro.
  - **Pattern trasversale su TUTTI i candidati "neutri" (DBC/PDBC/UUP/DBMF/
    KMLM/UEQC)**: riduzione consistente del MaxDD e Sharpe leggermente
    migliore, MAI un miglioramento di CAGR/paired-test statisticamente
    significativo. Le eccezioni statisticamente significative sono TIP e
    DBV, entrambe negative. **Nessuna nuova classe testata finora giustifica
    un cambio di produzione sulla sola base del rendimento**; l'ipotesi
    di un beneficio di coda (drawdown) resta plausibile ma non provata dal
    test principale.
- **Sostituire SPY con QQQ per la gamba Equity di Apex**, richiesta diretta
  dell'utente, `apex_equity_qqq_swap_test.py`. Il basket attuale di titoli
  S&P 500 a bassa volatilita' NON e' mai stato scelto per l'alpha (il suo
  stesso docstring lo dichiara) — e' stato scelto per ottenere il
  trattamento fiscale REDDITO_DIVERSO (compensabile). QQQ e' un ETF/UIT,
  tassato REDDITO_CAPITALE (non compensabile, come IEF/TIP). Per non
  confondere tre effetti diversi (segnale, beta sottostante, tasse), testate
  3 varianti sulla stessa finestra (586 settimane, correlazione settimanale
  SPY-QQQ 0,921):
  - **A) Baseline**: segnale SPY + basket S&P500 low-vol, REDDITO_DIVERSO —
    CAGR 16,50%/Sharpe 1,08/MaxDD -21,60%.
  - **B) Solo segnale QQQ** (basket e tasse INVARIATI): CAGR 17,08%/Sharpe
    1,15/MaxDD -18,60% — migliore su OGNI metrica rispetto al baseline.
    A->B: +0,43pp/anno, CI 90% [-0,42; +1,36], include lo zero (ma il
    limite inferiore e' il piu' vicino allo zero di tutta l'indagine sulle
    varianti di segnale).
  - **C) Pacchetto completo richiesto** (segnale QQQ + esposizione diretta
    QQQ, no basket, REDDITO_CAPITALE): CAGR 16,92%/Sharpe 1,10/MaxDD
    -20,95% — meglio del baseline ma PEGGIO di B su ogni metrica: passare
    da basket a QQQ diretto restituisce la maggior parte del guadagno
    ottenuto dal solo cambio di segnale. B->C: -0,04pp/anno, CI 90%
    [-1,91; +1,73], include lo zero. A->C: +0,39pp/anno, CI 90%
    [-1,57; +2,24], include lo zero.
  - PBO-CSCV (3 varianti): 25,7% (basso, ma con solo 3 configurazioni il
    test e' poco stabile/informativo — non sovra-interpretare).
  - **Verdetto**: nessuna variante e' statisticamente significativa, ma il
    pattern e' chiaro e coerente su ogni metrica: **usare QQQ SOLO come
    segnale di timing, mantenendo il basket S&P500 low-vol e il suo
    trattamento fiscale**, sembra la combinazione migliore delle tre — non
    ancora abbastanza forte per un cambio di produzione, ma il pacchetto
    completo richiesto (sostituire anche il basket) NON e' la scelta
    migliore delle opzioni testate.
- **Long/short su Equities invece di long/flat** (usare un -1x reale,
  ProShares Short S&P500/SH, quando il trend e' ribassista, invece di
  andare Cash) — idea diretta dell'utente ("avere sempre qualcosa da cui
  guadagnare"), `apex_equity_long_short_overlay_test.py`. Segnale
  simmetrico costruito SOLO nello script di test (stessa isteresi +
  conferma multi-timeframe della produzione, mai modificata
  `apex_v2_engine.py`), stati {LONG, SHORT, CASH}. Rendimento SHORT
  realizzato con dati REALI di SH (non un -1x sintetico del basket/SPY) —
  incorpora fee e decadimento da ribilanciamento giornaliero reali.
  - **Risultato: FALSIFICATO in modo statisticamente significativo.**
    CAGR netto 14,56% (contro 16,50% baseline), Sharpe 0,96 (contro 1,08),
    e soprattutto **MaxDD PEGGIORE, non migliore** (-28,42% contro
    -21,60% — l'esatto opposto dell'intuizione "avere sempre qualcosa da
    cui guadagnare"). Confronto accoppiato: **-1,65pp/anno, CI 90%
    [-3,35; -0,07] ESCLUDE lo zero.**
  - **Causa identificata**: Equities e' rimasta LONG 75,4% delle settimane,
    SHORT solo 15,2%, ma con **14 cambi di lato diretti** (LONG->SHORT o
    viceversa senza passare da Cash) in 586 settimane — la banda di
    isteresi di Apex e' stata calibrata e validata per un mondo long/flat;
    in un mondo long/short lo stesso whipsaw che prima costava "stare in
    Cash inutilmente" ora costa "essere dal lato sbagliato di un mercato
    che si muove", un costo strutturalmente piu' alto. Confermata l'analisi
    ex-ante: raddoppiare le decisioni della strategia senza ricalibrare la
    banda di isteresi per il caso simmetrico peggiora, non migliora.
- **Teorie accademiche da sondare — Teoria #1: segnale di trend CONTINUO
  invece che BINARIO** (Moskowitz-Ooi-Pedersen 2012 "Time Series Momentum";
  Baltas & Kosowski 2013), `apex_continuous_trend_signal_test.py`. Stessa
  identica logica di ingresso/uscita (isteresi + conferma multi-timeframe)
  della produzione — l'UNICA differenza e' che il peso, una volta attivo,
  e' scalato dalla forza del trend (clip(distanza/banda, 1.0, 2.0), 1x alla
  soglia fino a 2x a trend forte) invece di essere sempre fisso a
  base_weight_per_class. Risultato: CAGR 17,09% (contro 16,50%), Sharpe
  1,09 (contro 1,08), MaxDD sostanzialmente invariato (-21,75% contro
  -21,60%). Confronto accoppiato: **+0,57pp/anno, CI 90% [-0,17; +1,44]**
  — include lo zero, ma per il margine PIU' STRETTO di tutta questa
  indagine (limite inferiore quasi a zero) — il candidato di modifica al
  segnale core piu' promettente trovato finora, da riverificare con un
  campione piu' lungo o un disegno alternativo (es. cap di forza diverso)
  prima di considerarlo per produzione.
- **Teoria #3: RISK PARITY vero (peso inversamente proporzionale alla
  volatilita' di ciascuna classe attiva) invece del peso nozionale uguale
  attuale** (Qian 2005; Maillard-Roncalli-Teiletche 2010),
  `apex_risk_parity_signal_test.py`. Naive risk parity (1/volatilita', non
  la vera ERC con covarianza) applicata SOLO alla distribuzione del peso
  TRA le classi attive — stessa identica logica di ingresso/uscita e
  stessa esposizione lorda totale pre-vol-target del baseline.
  - **Risultato: FALSIFICATO in modo netto e ampiamente significativo —
    il piu' grande effetto (in valore assoluto) di tutta questa indagine.**
    CAGR crolla da 16,50% a **9,57%**, Sharpe peggiora (1,08->0,97)
    NONOSTANTE il MaxDD migliori molto (-21,60%->-11,31%) — il rendimento
    perso e' piu' che proporzionale al rischio ridotto. Confronto
    accoppiato: **-6,79pp/anno, CI 90% [-12,00; -2,50] ESCLUDE lo zero
    ampiamente.**
  - **Causa identificata**: la redistribuzione del peso quando tutte le
    classi sono attive mostra il meccanismo — Crypto (la piu' volatile)
    passa da 26,7% a **10,9%** di esposizione media, mentre Bonds (la meno
    volatile) passa da 31,2% a **56,4%**. Crypto e' stato storicamente il
    driver di rendimento risk-adjusted piu' forte di Apex in questo
    campione — la risk parity naive presume implicitamente che ogni classe
    offra lo stesso Sharpe per unita' di rischio, un'assunzione FALSA qui:
    penalizzare Crypto solo perche' e' volatile getta via una fonte di
    edge reale, non solo diversifica.
  - **Lezione generale**: la risk parity e' uno strumento di
    diversificazione del rischio, non di massimizzazione del rendimento —
    su un menu di asset con Sharpe storicamente molto diseguali (come
    quello di Apex, dove Crypto ha sovraperformato risk-adjusted rispetto
    a Bonds/Gold), forzare un contributo al rischio uguale combatte contro
    l'edge esistente della strategia invece di proteggerlo.
- **Teoria #4: VALUE su Bonds** (Asness-Moskowitz-Pedersen 2013, "Value
  and Momentum Everywhere"), `apex_bond_value_signal_test.py`. Limite di
  dati dichiarato: un value equity vero richiederebbe CAPE/P-E storico non
  disponibile in modo pulito da Yahoo Finance — testata SOLO la gamba
  Bonds, con un proxy di value reale e nativo nei dati: il rendimento del
  Treasury 10Y (^TNX) — percentile trailing a 3 anni del rendimento attuale
  scala il peso Bonds da 0.5x (rendimento basso, bond costoso) a 1.5x
  (rendimento alto, bond a sconto). Risultato: overperformance +0,34pp/anno,
  CI 90% [-0,29; +0,80] — include lo zero ma spostata verso il positivo,
  il campione utile e' piu' corto (470 settimane, vincolato dallo storico
  ^TNX+warmup). Nessun miglioramento robusto, ma nessun segnale negativo.
- **Teoria #5: QUALITY/Betting-Against-Beta sul basket azionario**
  (Frazzini-Pedersen 2014; Asness-Frazzini-Pedersen 2019),
  `apex_beta_basket_selection_test.py`. Limite di dati dichiarato: una vera
  Quality richiede fondamentali (ROE, leva) non disponibili da Yahoo
  Finance — testato il pezzo effettivamente disponibile coi soli dati di
  prezzo: selezione per BETA (regressione contro SPY, 26 settimane) invece
  di volatilita' realizzata assoluta, stesso buffer di rank e vincolo
  settoriale del basket di produzione. Risultato: CAGR 17,71% (contro
  16,50%), Sharpe 1,14 (contro 1,08), MaxDD sostanzialmente invariato.
  Confronto accoppiato: **+1,07pp/anno, CI 90% [-0,10; +2,09]** — include
  lo zero per il margine PIU' STRETTO di TUTTA questa indagine (limite
  inferiore -0,10, il piu' vicino a zero tra ogni candidato testato in
  questa intera sessione, incluso il segnale continuo della Teoria #1).
  **Il candidato singolo piu' promettente trovato finora** — non ancora
  sufficiente per produzione, ma il primo a meritare un secondo giro di
  verifica dedicato (campione piu' lungo, o combinato con la Teoria #1).
- **Teoria #6: stress test "Momentum Crash"** (Daniel & Moskowitz 2016),
  `apex_momentum_crash_stress_test.py`. Non un confronto baseline-vs-
  candidato come gli altri — un DIAGNOSTICO sul segnale di produzione
  INVARIATO: per ciascuna classe, isola tutte le uscite (attivo->Cash) e
  misura il rendimento dell'asset nelle K settimane successive contro il
  rendimento K-settimane medio incondizionato sull'intero campione. Se le
  uscite sono seguite sistematicamente da rimbalzi sopra media, l'isteresi
  e' vulnerabile al pattern "esce prima del rimbalzo". **Risultato:
  NON CONFERMATO — anzi l'opposto.** Per OGNI classe e OGNI finestra (K=4/
  8/12 settimane) il rendimento post-uscita e' PIU' BASSO della media
  incondizionata, mai piu' alto. Particolarmente netto per Crypto (-4,64pp/
  -8,65pp/-4,37pp alle tre finestre) — le uscite Crypto sono seguite da
  prezzi sistematicamente PIU' deboli della norma, non da rimbalzi persi.
  **Verdetto: l'isteresi attuale non mostra vulnerabilita' al pattern
  momentum-crash su questo campione — un risultato rassicurante sulla
  robustezza strutturale del segnale, non solo un'assenza di miglioramento.**
- **Sintesi delle 6 teorie accademiche sondate**: nessuna giustifica ancora
  un cambio di produzione da sola, ma il quadro e' informativo — **Teoria
  #5 (basket low-beta)** e **Teoria #1 (segnale continuo)** sono i due
  candidati piu' vicini alla significativita' statistica e meritano
  approfondimento dedicato; **Teoria #3 (risk parity)** e' chiaramente
  falsificata (non riprovare senza un ripensamento del design); **Teoria
  #6 (momentum crash)** e' un risultato rassicurante sulla robustezza
  esistente, non un'opportunita' di miglioramento; **Teoria #2 (carry
  cross-asset)** e **Teoria #4 (value bonds)** sono nella zona neutra,
  nessun danno ma nessuna evidenza sufficiente.
- **Secondo giro di verifica — Teorie #1 e #5**, richiesto direttamente
  dall'utente, `apex_theory1_theory5_second_round_test.py`. Un singolo
  punto stimato non basta a livello istituzionale: tre controlli aggiuntivi
  per ciascuna teoria — sensibilita' al parametro scelto arbitrariamente,
  stacking (le due si combinano?), e uno split TRAIN/TEST temporale (prima
  meta' vs seconda meta' del campione, mai casuale) per vedere se l'effetto
  e' stabile nel tempo o guidato da un sotto-periodo.
  - **Teoria #1 (segnale continuo, sensibilita' a STRENGTH_CAP)**: pattern
    MONOTONO e pulito — cap=1.5 (+0,33pp, CI include zero), cap=2.0
    originale (+0,57pp, CI include zero), cap=3.0 (**+1,04pp, CI 90%
    [+0,17; +2,01] ESCLUDE lo zero**). L'effetto non e' un artefatto di un
    singolo valore di parametro — cresce in modo coerente con la
    "convinzione" massima permessa al segnale.
  - **MA train/test rivela un problema serio**: lo Sharpe di TUTTE le
    configurazioni crolla dalla prima meta' del campione (~1,4-1,5) alla
    seconda (~0,5-0,7) — un effetto di regime generale, non specifico a
    nessuna variante. Nella seconda meta' (il periodo piu' recente e
    difficile), la Teoria #1 NON tiene: baseline 0,59, cap=2.0 0,56,
    cap=3.0 0,58 — leggermente PEGGIORE del baseline, nonostante la
    significativita' sull'intero campione. **L'apparente edge della
    Teoria #1 e' concentrato nella prima meta' (regime piu' favorevole),
    non un vantaggio che si replica in modo consistente nel tempo —
    significativita' full-sample non equivale a robustezza out-of-sample.**
  - **Teoria #5 (basket low-beta, sensibilita' al lookback)**: pattern
    NON monotono — lookback=13 sett. quasi nullo (-0,01pp), lookback=26
    (originale) il migliore (+1,07pp, CI include zero per un pelo),
    lookback=52 leggermente negativo (-0,55pp). Il risultato e' piu'
    sensibile alla scelta esatta del parametro di quanto sarebbe
    rassicurante — non generalizza in modo pulito a finestre vicine.
  - **MA il train/test e' piu' incoraggiante qui**: nella seconda meta'
    (regime difficile), lookback=26 ottiene Sharpe 0,67 — MEGLIO del
    baseline (0,59), a differenza della Teoria #1. Il meccanismo catturato
    dalla selezione low-beta sembra continuare a funzionare anche nel
    periodo piu' recente, anche se il valore esatto ottimale del lookback
    resta incerto.
  - **Stacking (Teoria1 cap=2.0 + Teoria5 lookback=26 insieme)**:
    **+1,77pp/anno, CI 90% [+0,23; +3,21] ESCLUDE lo zero** — il risultato
    piu' forte di tutta l'indagine. Ma l'effetto combinato (+1,77pp) e'
    vicino alla SOMMA dei due effetti individuali (0,57+1,07=1,64pp),
    quindi sembra additivo/indipendente, non sinergico — e il train/test
    del combinato (Sharpe 0,67 nella seconda meta', identico a Teoria #5
    da sola) suggerisce che il miglioramento nel periodo recente venga
    soprattutto dalla componente basket low-beta, non dal segnale continuo.
    PBO-CSCV su 8 configurazioni: 21,4% (basso, incoraggiante ma con solo
    8 config potenza limitata).
  - **Verdetto onesto**: **nessuna delle due teorie e' ora confermata in
    modo pulito.** Teoria #1 ha un profilo di sensibilita' migliore
    (monotono) ma FALLISCE il test out-of-sample piu' importante (train/
    test). Teoria #5 ha un profilo di sensibilita' peggiore (non
    monotono) ma REGGE meglio il test out-of-sample. Lo stacking e'
    statisticamente il piu' forte ma e' trainato principalmente dalla
    Teoria #5.
- **Terzo giro di verifica — richiesto direttamente dall'utente ("dobbiamo
  vederci chiaro")**: un solo split train/test e una griglia di 3 punti
  non bastavano a chiudere la domanda. Due diagnostici mirati, uno per
  teoria, hanno risolto l'ambiguita' in direzioni OPPOSTE.
  - **Teoria #1 — RISOLTA, NON ADOTTARE**,
    `apex_theory1_rolling_attribution_test.py`. Sharpe ROLLING a 104
    settimane (2 anni), ricalcolato ogni 26 settimane lungo tutto il
    campione (non un solo prima/dopo): la differenza (continuo meno
    binario) e' positiva e consistente da metà 2017 a meta' 2023 (+0,01 a
    +0,15), poi si INVERTE in modo netto e SOSTENUTO da fine 2023 in poi
    (-0,11, -0,06, -0,10, -0,05, -0,03 su 5 finestre consecutive, ~2,5
    anni) — non rumore, una vera rottura strutturale. **Attribuzione per
    classe spiega il perche'**: il vantaggio cumulato della Teoria #1
    (+18,26% sull'intero campione) viene per **il 63% da Crypto da sola**
    (+11,46% nella prima meta', appena +0,13% nella seconda) — i trend
    pluriennali eccezionali di BTC nel 2017-2022 hanno reso il meccanismo
    "scala il peso con la forza del trend" straordinariamente redditizio
    in quel periodo specifico, un evento storico non ripetibile, non un
    meccanismo generale. **Verdetto: la significativita' full-sample della
    Teoria #1 era quasi interamente un artefatto della storia di BTC, non
    un edge strutturale — non adottare.**
  - **Teoria #5 — RAFFORZATA**, `apex_theory5_lookback_finegrid_test.py`.
    Griglia fine a 9 lookback (16/20/22/24/26/28/30/33/39 settimane)
    invece dei soli 3 punti del secondo giro: il vantaggio low-beta su
    low-vol (a parita' di lookback) e' **positivo su OGNI punto da 16 a
    33 settimane** (+0,80 a +1,58pp/anno, tre di questi — 22/30/33 —
    ESCLUDONO lo zero), crollando solo agli estremi (39 sett. quasi
    nullo). **Non e' un singolo punto fortunato come temuto dal secondo
    giro** — e' un vantaggio consistente su tutta una banda ragionevole
    di specificazione, che insieme alla tenuta out-of-sample gia' trovata
    nel secondo giro rende la Teoria #5 il candidato di gran lunga piu'
    credibile delle due. Confrontato pero' SEMPRE contro il preciso
    baseline di produzione (low-vol, lookback=26), nessun lookback
    raggiunge la significativita' individualmente (il confronto piu'
    rilevante per una decisione di produzione) — quindi ancora non
    sufficiente da solo per un cambio, ma la base per proseguire e'
    solida, non fragile.
  - **Sintesi aggiornata**: la Teoria #1 e' ora chiusa (falsificata con
    causa identificata, non riprovare in questa forma). La Teoria #5
    resta l'unica direzione viva di questa indagine — il prossimo passo
    naturale, se si vuole insistere, sarebbe testare la selezione low-beta
    con un vincolo di stabilita' temporale piu' esplicito (es. media
    mobile del beta su piu' finestre) invece di continuare a cercare un
    singolo lookback ottimale.
- **Quarto giro — beta stabilizzato su piu' finestre**, richiesta diretta
  dell'utente ("insistiamo con il prossimo passo naturale"),
  `apex_stable_beta_basket_test.py`. Invece di un singolo lookback, il
  beta di ranking e' la MEDIA del beta calcolato su 4 finestre insieme
  (13/26/39/52 settimane, da 3 mesi a 1 anno) — un classico strumento di
  riduzione della varianza di stima (media di piu' orizzonti invece di
  fidarsi di uno solo). Risultato: **PIU' DEBOLE, non piu' forte, dei
  migliori lookback singoli della griglia fine.** Overperformance
  +0,64pp/anno, CI 90% [-0,48; +1,54] — un intervallo PIU' ampio e un
  punto stimato PIU' basso dei lookback singoli piu' forti (22/30/33
  settimane, che arrivavano a +1,27/+1,35pp con CI quasi o del tutto
  fuori dallo zero). Train/test: entrambe le meta' migliorano leggermente
  rispetto al baseline (1,47->1,53 e 0,59->0,60) — nessuna inversione
  come nella Teoria #1, ma un margine minimo nella seconda meta'.
  **Interpretazione**: la stabilizzazione per media ha DILUITO l'effetto
  invece di rafforzarlo — mescolare finestre piu' corte (13 sett.,
  rumorose) e piu' lunghe (39-52 sett., piu' deboli nella griglia fine)
  con quelle centrali (22-33 sett., le piu' forti) ha tirato la stima
  verso la media invece di isolare la parte di segnale concentrata nella
  banda centrale. **Se l'edge del basket low-beta e' reale, sembra
  specifico di un orizzonte di stima di medio termine (~5-8 mesi), non
  un effetto beta generico presente su qualunque finestra** — un
  risultato che restringe ulteriormente, ma non chiude, la Teoria #5.
- **Quinto giro — ensemble scoped sulla banda 22-33 settimane**, richiesta
  diretta dell'utente ("procedi"), `apex_theory5_band_ensemble_test.py`.
  A differenza del quarto giro (media del CRITERIO beta su un range ampio
  13-52, che diluiva il segnale), qui si costruisce un ENSEMBLE dei
  RISULTATI — 6 basket indipendenti selezionati ciascuno col proprio
  lookback SOLO nella banda interna forte (22/24/26/28/30/33 sett.),
  poi si media la SERIE DI RENDIMENTO netta dei 6 portafogli (un "fondo
  di fondi" che preserva la selezione titoli distinta di ciascun lookback
  invece di appiattirla in un unico criterio medio). Statistica scoped
  SOLO su questa banda (8 configurazioni: baseline + 6 lookback + ensemble),
  non sulla griglia intera di 9+ punti, per non riprodurre lo stesso
  rischio di selezione post-hoc gia' segnalato nei giri precedenti.
  - **Risultato: conferma l'ipotesi del quarto giro E stringe ulteriormente
    il quadro.** Ensemble: CAGR 17,62% (contro 16,50%), Sharpe 1,14
    (contro 1,08). Confronto accoppiato: **+0,98pp/anno, CI 90%
    [-0,18; +1,98]** — PIU' vicino a escludere lo zero del quarto giro
    (stable-beta ampio: [-0,48;+1,54]), ma ANCORA PIU' DEBOLE dei singoli
    lookback piu' forti della banda (30 e 33 settimane, che da soli
    escludevano lo zero). PBO-CSCV su questo set scoped: 31,4% (moderato,
    ne' allarmante ne' rassicurante).
  - **Train/test — il segnale piu' incoraggiante di tutta l'indagine
    Teoria #5**: l'ensemble migliora in ENTRAMBE le meta' rispetto al
    baseline (1a meta' 1,47->1,50; 2a meta' 0,59->0,67) — nessuna
    inversione in nessun test su nessuna variante di questa teoria,
    a differenza della Teoria #1.
  - **Verdetto dopo 5 giri di verifica indipendenti**: la Teoria #5 mostra
    un effetto REALE, modesto e consistente (mai un'inversione, sempre lo
    stesso ordine di grandezza ~1pp/anno, concentrato in una banda di
    lookback riproducibile 22-33 settimane), ma la sua magnitudine si
    colloca esattamente al limite di risoluzione statistica di un
    campione di ~11 anni — nessuna singola configurazione supera la
    soglia di significativita' del 90% in modo scontato E robusto allo
    stesso tempo. **Ulteriori giri di ricerca sulla stessa banda hanno
    ora un valore marginale decrescente — la prossima verifica utile
    non e' un altro parametro, ma un campione diverso (es. universo
    azionario europeo o un'altra borsa) per vedere se l'effetto si
    replica fuori da questo specifico storico S&P 500.** Se adottata,
    andrebbe trattata come una posizione di convinzione moderata, non
    come un cambio a piena confidenza.
- **Checklist di produzione per la Teoria #5**, richiesta diretta
  dell'utente dopo la domanda "quali verifiche mancano per essere
  approvato per la produzione?" — 7 gap identificati, chiusi punto per
  punto ("procedi punto per punto").
  - **Gap #1 — selezione del lookback con look-ahead, RISOLTO**,
    `apex_theory5_walkforward_selection_test.py`. La banda 22-33 settimane
    era stata identificata E testata sullo stesso campione completo — un
    vero walk-forward (4 ere consecutive ~2,6 anni ciascuna, il lookback
    scelto per ogni era SOLO con lo Sharpe delle ere precedenti, mai
    quella corrente) mostra: (a) la selezione adattiva converge in modo
    stabile su 22-24 settimane (mai un valore fuori dalla banda gia'
    identificata — la banda non era un artefatto del guardare tutto il
    campione insieme), ma (b) **la selezione ADATTIVA non batte un
    lookback fisso a 26 settimane scelto a priori** (walk-forward
    +1,16pp/anno CI 90% [-0,66;+2,55] contro fisso-26 +1,24pp/anno CI
    [-0,32;+2,43] — il fisso e' leggermente MIGLIORE). **Implicazione
    diretta per la produzione: se adottata, va implementata con un
    lookback fisso, mai con ri-selezione adattiva — la sofisticazione
    aggiuntiva non paga.** Il quadro sostanziale (positivo, non
    significativo al 90%) e' confermato anche nel disegno piu' rigoroso
    possibile fin qui: la banda non e' un artefatto del look-ahead, ma
    nemmeno diventa piu' forte eliminandolo.
  - **Gap #3/#4 — turnover e composizione, CHIUSI**,
    `apex_theory5_composition_turnover_test.py`. Turnover quasi identico
    (low-vol 8,5/15 titoli sostituiti a trimestre = 57%, low-beta 8,9/15
    = 60% — differenza trascurabile, nessun costo di transazione
    aggiuntivo rilevante). Concentrazione settoriale quasi identica
    (13,3% nel settore piu' rappresentato per entrambi); 4 dei 6 settori
    piu' comuni coincidono (Consumer Defensive, Utilities, Healthcare,
    Industrials, Consumer Cyclical), low-beta preferisce leggermente Real
    Estate al posto di Financial Services rispetto a low-vol — nessuna
    concentrazione anomala in nessuno dei due. **Scoperta piu' rilevante,
    non anticipata**: la sovrapposizione di titoli EFFETTIVI tra i due
    basket, stessa data, e' solo **6,9% in media** (range 0-30%) — i due
    criteri, pur simili su turnover/settore, selezionano quasi sempre
    titoli COMPLETAMENTE DIVERSI. L'edge, se reale, viene da una
    meccanica di selezione sostanzialmente diversa, non da un
    aggiustamento marginale dello stesso basket.
  - **Gap #5/#6 — CHIUSI, con una scoperta sostanziale**,
    `apex_theory5_crash_and_signal_test.py`.
    - **Gap #6 (interazione col segnale)**: il basket low-beta e' REALMENTE
      meno correlato a SPY del basket low-vol (0,708 contro 0,775,
      differenza -0,067) — un disallineamento reale col segnale di timing
      (che usa SPY), ma modesto, non drammatico (0,708 resta comunque
      un'alta correlazione).
    - **Gap #5 (crash specifici) — la scoperta piu' importante di questo
      giro**: il comportamento e' OPPOSTO tra un panico rapido e un bear
      market lento. Nel crollo COVID 2020 (7 settimane, panico acuto),
      low-beta e' STATO LEGGERMENTE PEGGIORE di low-vol (-30,16% contro
      -29,21%, entrambi peggio di SPY -23,27% — in un panico le
      correlazioni vanno tutte a 1, il beta storico non protegge). Nel
      bear market 2022 (41 settimane, ribasso lento da rialzo tassi),
      low-beta ha fatto MOLTO MEGLIO (-7,10% contro -13,56% di low-vol,
      entrambi molto meglio di SPY -23,83%) — **+6,46pp di differenza**.
      **Implicazione**: l'edge del basket low-beta NON e' "protezione dai
      crash" in generale — e' specificamente protezione nei ribassi
      lenti e strutturali (come 2022), non nei panici improvvisi (come
      COVID). Questo spiega in modo coerente perche' la Teoria #5 ha
      sempre retto meglio del baseline nella seconda meta' del campione
      nei test precedenti (train/test, walk-forward) — quella finestra e'
      dominata dal 2022, esattamente il tipo di regime in cui low-beta
      funziona meglio.
  - **Gap #7 — criterio di uscita, CHIUSO (l'utente lo ha voluto testato
    empiricamente, non lasciato solo come policy)**,
    `apex_theory5_exit_criterion_test.py`. Regola testata: monitoraggio
    dello Sharpe rolling a 104 settimane di low-beta contro low-vol,
    controllato ogni 13 settimane, switch REVERSIBILE con costo di
    transazione realistico (0,90%, coerente con la sovrapposizione
    titoli solo 6,9% misurata nel gap #4). **Risultato: lo switching
    adattivo PEGGIORA rispetto a una scelta fissa, non migliora.** Sempre
    low-beta: +1,36pp/anno contro sempre low-vol (CI 90% [-0,16;+2,39],
    coerente col resto dell'indagine). Switching adattivo: +0,06pp/anno
    (CI [-1,03;+0,91], sostanzialmente NULLO) e MaxDD peggiore di
    ENTRAMBE le alternative fisse (-24,10% contro -21,53/-21,60%) — gli 8
    cambi nella finestra monitorata (2017-2026) costano piu' di quanto
    guadagnino, stesso pattern gia' visto nel gap #1 (la selezione
    adattiva del lookback non batteva un valore fisso). **Verdetto: se si
    adotta low-beta, adottarlo in modo permanente — un interruttore
    automatico basato su Sharpe rolling e' controproducente, non un
    paracadute.**
  - **Basket low-beta: quanti titoli?**, richiesta diretta dell'utente,
    `apex_beta_basket_size_grid_test.py` — stessa griglia {10,12,15,18,
    20,25} gia' usata per low-vol. **15 titoli (il valore attuale di
    produzione) e' gia' il migliore per Sharpe** (1,14, a pari merito
    con 18 ma con CAGR piu' alto), PBO-CSCV 18,6% (basso, nessun segnale
    di overfitting). **Nessun cambio necessario sul numero di titoli.**
  - **Beta-weighting sulle CLASSI macro invece che sui titoli — domanda
    diretta dell'utente ("low beta si puo' testare anche sulle asset
    class?"), FALSIFICATO in modo netto**,
    `apex_beta_class_weight_test.py`. Ipotesi: la Teoria #3 (risk parity
    per volatilita' assoluta) era stata bocciata perche' penalizzava
    Crypto per la sua vol alta indipendentemente dalla sua bassa
    correlazione con l'equity (0,09-0,17) — pesare per BETA vs SPY
    invece che per volatilita' assoluta avrebbe potuto evitare questo
    meccanismo di fallimento. **Non l'ha evitato**: -4,31pp/anno, CI 90%
    **[-7,82;-1,26] ESCLUDE lo zero** — quasi lo stesso ordine di
    grandezza della Teoria #3. Causa identica: Bonds ha beta vicino a
    zero rispetto a SPY quanto la sua volatilita' assoluta e' bassa,
    quindi domina comunque l'inverse-weighting (floor 0,10 raggiunto,
    esposizione Bonds 31,2%->55,4%, Crypto 26,7%->19,4%). **Lezione
    generalizzata**: qualunque schema che pesi le classi inversamente a
    una misura di rischio (vol O beta) sovrappesa strutturalmente
    Bonds/Gold e sottopesa Crypto/Equity, indipendentemente dalla misura
    scelta — il problema non era la metrica, e' il principio stesso.
  - **Low-beta sulle altcoin (invece che sui titoli S&P 500) — domanda
    diretta dell'utente, risultato in DUE tempi**,
    `altcoin_strategy_families_pointintime_test.py` (esteso con la
    modalita' `low_beta_pick`) e `altcoin_low_beta_weekly_test.py`.
    - **Daily, finestra beta ~6 settimane (equivalente ai 30gg usati per
      vol_alt): FALLISCE nettamente.** Sharpe netto 0,39 (top-5)/0,07
      (top-3) contro 0,84 di BTC buy&hold, che resta il migliore assoluto
      su 11 candidati testati (PBO-CSCV 11,4%, robusto). L'effetto
      low-beta NON si trasferisce all'universo altcoin con una finestra
      corta.
    - **Domanda di successivo dell'utente ("weekly sarebbe diverso?"),
      risposta: SI', ma non per la granularita' in se' — per la finestra
      di stima piu' lunga che la granularita' weekly permette di testare
      in modo naturale.** Con finestra beta di 26 settimane (la banda che
      ha funzionato per Apex equity), low-beta pick SUPERA BTC sia su
      Sharpe (0,85-0,88 contro 0,82) sia nettamente su CAGR (46-57%
      contro 37%) su entrambi gli universi top-3/top-5. **Ma il segnale
      statistico e' debolissimo**: PBO-CSCV 42,9-45,7% (vicino al 50%,
      nessun edge robusto rilevato), CI 90% sulla differenza vs BTC
      **enormi** (es. [-26,36;+61,24]pp/anno) — solo 18-22 cambi di
      posizione in tutto il campione (315 settimane, 2020-2026, molto
      piu' corto dei 12 anni azionari). **Verdetto: risultato intrigante
      ma NON validato — l'ipotesi "finestra piu' lunga, non
      granularita'" e' confermata qualitativamente, ma il campione
      crypto disponibile e' troppo corto per dire se e' un edge reale o
      un artefatto di poche osservazioni fortunate. Richiederebbe lo
      stesso trattamento a piu' giri gia' applicato alla Teoria #5
      azionaria prima di qualunque considerazione seria.**
  - **Approfondimento richiesto dall'utente ("walk-forward e piu'
    storico"), `altcoin_low_beta_weekly_walkforward_test.py`: FALSIFICA il
    risultato "intrigante" sopra.**
    - **Bug trovato e corretto, non nuova raccolta dati**: l'harness
      weekly costruiva i rendimenti con `.dropna()` sull'intero
      DataFrame a 15 colonne — una riga con anche un solo ticker
      mancante (TON-USD, inception reale 2020-08-24, la piu' tarda delle
      15) veniva scartata per intero, anche se TON non era mai eleggibile
      come "top alt" in quel periodo. La versione daily gia' usava
      correttamente `.fillna(0.0)` — applicato qui. Recupera il campione
      da 315 a 362 settimane (2019-10-11 → 2026-09-11, +47 settimane).
    - **Selezione walk-forward onesta della finestra beta** (stesso
      principio gia' applicato alla Teoria #5 azionaria): 3 ere non
      sovrapposte, finestra scelta per ogni era SOLO con lo Sharpe delle
      ere precedenti (griglia [4,8,13,20,26] settimane), valutata
      out-of-sample sull'era corrente. **Risultato: la finestra
      "vincente" cambia era per era (13→20 per top-3, 8→8 per top-5) e
      non e' mai la 26 settimane che sembrava buona full-sample —
      instabilita' classica da selezione in-sample.** OOS (ere 2+3, 242
      settimane): top-3 **-6,98pp/anno** vs BTC (CI 90%
      [-35,82;+27,67], segno invertito rispetto al preliminare), top-5
      +3,51pp/anno ma CI 90% [-24,00;+40,75] (include ampiamente lo
      zero); solo 40% delle settimane migliori di BTC in entrambi i casi.
      **PBO-CSCV full-sample 55,0-60,0% — peggio di un lancio di moneta,
      segnale attivo di overfitting, non solo assenza di edge.**
      **Verdetto: il preliminare "26 settimane batte BTC" non sopravvive
      alla selezione onesta — era rumore in-sample. BTC buy & hold resta
      ottimale per lo slot Crypto. Nessuna modifica in produzione.**
  - **Estensioni richieste dall'utente nonostante la falsificazione sopra
    ("il numero di posizioni altcoin, l'universo e le percentuali —
    sostituiscono Bitcoin o sono extra?"),
    `altcoin_crypto_slot_basket_satellite_test.py`** — vol_window=13
    settimane FISSO (valore centrale della griglia, non ottimizzato, per
    non impilare un altro livello di selezione in-sample sopra
    basket-size/satellite-pct):
    - **Parte A — basket (sostituzione, livello-strumento)**: invece del
      singolo pick, N=2 (universo top-3) e N=2/3/5 (universo top-5) alt a
      beta piu' basso vs BTC, equal-weight. Nessuna configurazione batte
      BTC in modo robusto (CAGR 17,80-32,91% contro 38,25% di BTC su
      tutte le varianti; CI 90% sulla differenza sempre enormi e sempre
      includenti lo zero, es. [-36,40;+15,16]; PBO-CSCV 40,0% su
      entrambi gli universi). Diversificare su piu' altcoin non recupera
      il segnale perso col walk-forward — come atteso, aggiunge gradi di
      liberta' su un campione gia' corto.
    - **Parte B — satellite (extra, livello-portafoglio Apex intero)**:
      lo slot Crypto resta BTC (produzione attuale invariata); sleeve
      satellite separata, attiva solo quando il segnale di trend Apex per
      Crypto e' ON (stesso timing, nessun segnale nuovo), dimensionata a
      satellite_pct del NAV fisso {10%,25%,50%} sul singolo alt a beta
      piu' basso vs BTC, tassata REDDITO_DIVERSO come BTC. **Risultato
      iniziale sorprendente (+3,21/+8,20/+16,97pp/anno, CI 90% sempre
      ESCLUDENTI lo zero, PBO-CSCV 15,0%) — in netto contrasto con Parte
      A. Contrasto cosi' netto da richiedere un controfattuale prima di
      crederci.**
    - **Controllo di confondimento (`altcoin_satellite_btc_confound_test.py`,
      stesso harness, satellite invertito in BTC invece del pick
      low-beta): FALSIFICA il risultato della Parte B come "vantaggio
      della selezione low-beta".** Il satellite in BTC puro batte quello
      in altcoin low-beta a OGNI livello (+5,17/+13,31/+27,88pp/anno
      contro +3,21/+8,20/+16,97pp/anno, CI 90% sempre escludenti lo
      zero). La selezione low-beta non aggiunge nulla — e' inferiore a
      BTC semplice, coerente con la Parte A. **L'intero guadagno della
      Parte B viene dall'aggiungere ESPOSIZIONE CRYPTO IN GENERALE (il
      vol-target lasciava capacita' di rischio inutilizzata sulla classe
      Crypto), non dalla scelta di QUALE moneta.** Questo chiude
      definitivamente l'intera linea "altcoin low-beta" (pick, walk-
      forward, basket, satellite: falliti in ogni forma testata, o la
      loro apparente riuscita e' interamente spiegata da un
      confondimento estraneo alla selezione).
    - **Effetto collaterale da NON confondere con un edge validato**:
      l'esposizione crypto extra (in QUALUNQUE forma) migliora il
      backtest in modo monotono con CI 90% sempre significative — ma e'
      il pattern classico "piu' leva su cio' che e' andato meglio nel
      campione storico" (BTC CAGR 38,25% standalone in questo periodo),
      non necessariamente skill. Segnali d'allarme concreti nella
      versione BTC: Sharpe netto piatto/in calo (1,14→1,11) mentre il
      MaxDD raddoppia (-21,54%→-52,18%) al 50% — il guadagno e' quasi
      tutto leva, non miglioramento risk-adjusted — e PBO-CSCV 70,0%
      (sopra il 50%, instabile) sulla versione BTC, che non e' nemmeno
      robusto in senso overfitting-adjusted nonostante le CI strette.
      **Non validato per produzione**: richiederebbe come minimo lo
      stesso trattamento walk-forward gia' applicato altrove in questa
      sezione (mai fatto qui) prima di qualunque considerazione seria —
      concettualmente e' un test di "class-weight asimmetrico" (solo
      Crypto sopra il 50% base, non tutte le classi uniformemente come
      in `apex_class_size_grid_test.py`), distinto ma imparentato con la
      Storia sul sizing per classe qui sopra, e va trattato con lo stesso
      sospetto.
    - **Fatto — approfondimento richiesto dall'utente ("sì
      approfondisci"), `apex_crypto_asymmetric_weight_walkforward_test.py`:
      FALSIFICA anche questo.** Non un satellite bolt-on ma
      `base_weight_per_class` asimmetrico (Crypto sopra il 50% base, le
      altre 3 classi invariate), con selezione walk-forward onesta del
      valore (griglia [0.50,0.65,0.75,0.90,1.00], 3 ere, scelta per ogni
      era SOLO con lo Sharpe delle ere precedenti) — stessa disciplina
      mai applicata prima su questo asse. Efficienza: is_active/vol per
      classe non dipendono da crypto_base_weight, quindi un solo giro
      costoso su trend/basket precede l'intera griglia.
      Full-sample (non il test principale, solo contesto): CAGR/Sharpe
      migliorano in modo monotono con crypto_base_weight (17,71%/1,14 a
      0,50 fino a 19,68%/1,12 a 1,00) — ma **PBO-CSCV 65,7%** (sopra il
      50%, instabile) gia' segnala il pattern "leva su cio' che e' andato
      bene storicamente" temuto. **Walk-forward OOS (ere 2+3, 391
      settimane, 2019-2026): Sharpe netto PEGGIORE (0,96 contro 0,98
      baseline), overperformance +0,23pp/anno con CI 90% [-0,74;+1,40]
      (include lo zero), solo 17% delle settimane migliori della
      baseline** — il guadagno e' concentrato in poche settimane
      eccezionali, non un vantaggio consistente. **La selezione
      walk-forward stessa e' rivelatrice**: l'Era 2 sceglie 0,90
      (aggressivo) ma l'Era 3 — la piu' recente e informata — torna a
      0,50, cioe' l'attuale, nessun cambio. Sensibilita' aggiuntiva:
      escludendo 2023-2026 (il bull run piu' recente), crypto_base_weight
      1,00 batte la baseline in modo significativo pre-2023 (+2,20pp/anno,
      CI 90% [+0,33;+4,70]) — ma questo non si traduce in un vantaggio
      walk-forward-onesto sull'intero campione OOS, confermando che
      l'effetto e' concentrato in episodi specifici, non strutturale.
      **Verdetto: nessuna modifica in produzione.** Chiude l'intero asse
      "dare piu' spazio a Crypto" (satellite, basket, class-weight
      asimmetrico): nessuna forma sopravvive al walk-forward onesto — il
      sizing uniforme 50%/22% attuale resta l'unico validato.
  - **Gap rimanenti**: #2 (campione indipendente, non fattibile senza
    dati point-in-time di un altro mercato).
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
- **Costo della policy "mai vendere" di Convex Stack — domanda diretta
  dell'utente** (`convex_never_sell_cost_test.py`), letteratura di
  riferimento: rebalancing premium/variance harvesting (Willenbrock 2011,
  Chambers-Zdanowicz).
  - **Bug trovato e corretto durante lo sviluppo**: `apply_italian_tax`
    (framework/tax_engine.py) aveva un parametro `rebalance_every` nella
    firma MAI letto nel corpo della funzione — ribilanciava
    incondizionatamente ogni periodo a prescindere dal valore passato.
    Significa che `convex_weights_grid_test.py` (sopra) ha testato i PESI
    assumendo implicitamente ribilanciamento MENSILE per tutte le 9
    combinazioni — un'assunzione diversa dalla policy reale di Convex (mai
    vendere se non con nuovi versamenti). Quella conclusione resta valida
    COME TEST SUI PESI SOTTO RIBILANCIAMENTO MENSILE IPOTETICO, non prova
    nulla sulla frequenza. Implementato correttamente (`None` = mai
    ribilanciare dopo l'allocazione iniziale, N = ogni N periodi;
    default=1 invariato, zero regressioni per i chiamanti esistenti — 3
    nuovi test in `test_tax_engine.py`).
  - **Risultato, stessi pesi 45/15/25/7.5/7.5, 4 frequenze (mensile/
    trimestrale/annuale/mai)**: nessun vincitore chiaro e netto — trade-off
    reale, non un pranzo gratis in nessuna direzione. Campione pieno (81
    mesi, limitato dallo storico DBMFE come nel test sui pesi): MAI ha
    Sharpe netto PIU' BASSO (0,87 contro 0,91-1,00 delle frequenze
    periodiche) e MaxDD nettamente PEGGIORE (-23,06% contro -15,69/-16,74%)
    — il drift lascia correre i vincitori, concentrando rischio. Ma il CAGR
    netto di MAI (16,71%) e' competitivo con Annuale (16,89%) e batte
    Mensile (15,21%) — nel periodo TEST (piu' recente, 41 mesi) MAI ha
    perfino il CAGR netto piu' alto in assoluto (17,49%, con "drag
    fiscale" NEGATIVO: la tassa quasi nulla del non-vendere piu' che
    compensa il vantaggio teorico del ribilanciamento in un campione a
    forte trend, coerente con la letteratura — il rebalancing premium e'
    piu' forte in mercati range-bound/mean-reverting, puo' sottoperformare
    in mercati fortemente trend). **Confronto diretto MAI meno MENSILE:
    +2,01pp/anno campione pieno, +3,63pp/anno su TEST, ma CI 90% include
    SEMPRE lo zero in entrambi i casi** — non statisticamente distinguibile
    dal rumore su un campione di questa lunghezza. PBO-CSCV 45,0% (vicino
    al 50%, nessuna frequenza batte le altre in modo robusto).
  - **Verdetto**: nessuna modifica alla policy — il trade-off reale
    (rischio di coda peggiore per MAI, drag fiscale reale ma modesto per le
    frequenze periodiche, 0,24-2,02pp/anno a seconda della frequenza) e'
    ora quantificato ma non risolve a favore di un cambiamento
    statisticamente difendibile. Il MaxDD peggiore di MAI e' il segnale piu'
    concreto contro un cambiamento di policy nel senso opposto (piu'
    frequente), ma nemmeno quello raggiunge significativita' netta su
    questo campione corto.
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
- **Dashboard rimasta su dati/testi della vecchia strategia low-vol dopo il
  passaggio a low-beta (§8.29) — domanda diretta dell'utente ("i grafici
  mi sembrano identici")**:
  - **Diagnosi**: `apex_data.json`/`portfolio.json` (stato live) erano
    fermi all'ultimo run di produzione reale, precedente allo switch — non
    un bug, si autocorreggono al prossimo giro schedulato (nessuna azione
    possibile da questa sandbox: quel giro fa fetch live e muove stato di
    portafoglio/ordini reali, fuori scope). Le CARD STATISTICHE
    (`get_apex_metrics`/`get_combined_dual_engine_metrics` in
    `portfolio_manager.py`) erano invece numeri STATICI, fermi al 3
    settembre (verificato via `git log`), sourced da
    `apex_monthly_returns_extended*.csv` prodotti da una pipeline esterna
    (`research/`) — **verificata irraggiungibile da questa sessione**: mai
    committata su nessun branch (storia completa cercata, vuota) ed
    esclusa da `.gitignore`, quindi ne' su GitHub ne' su questo sandbox.
    Testo "philosophy" ancora letteralmente "Low-Vol" — prova diretta
    della staleness. Trovati e corretti anche 4 testi hardcoded in
    `home_app.py`/`page_apex.py` (badge/sottotitoli "Low-Vol") che non
    si sarebbero MAI autocorretti, indipendentemente dal refresh dei dati.
  - **Rigenerazione in-repo** (`apex_dashboard_stat_regeneration.py`,
    scelta esplicita dell'utente rispetto a rifare la pipeline esterna),
    **estesa il piu' indietro possibile con i migliori proxy** (richiesta
    esplicita successiva): Equities = VFINX (total return dal 1986-09)
    raccordato con SPY reale dal 1993-01; Bonds = VUSTX (Treasury lungo
    termine, dal 1986-09) raccordato con IEF dal 2002-08 (duration diversa,
    approssimazione dichiarata); Gold = GC=F (futures oro COMEX, dal
    2000-08) raccordato con GLD dal 2004-11 — scartati proxy piu' vecchi
    (indici/fondi di azioni minerarie aurifere, disponibili dagli anni '80)
    perche' espongono a rischio azionario, contaminando proprio la classe
    pensata per esserne indipendente; Crypto = solo BTC-USD reale dal
    2014-09, nessun proxy prima (nessun mercato liquido affidabile).
    Raccordo per RENDIMENTO (non prezzo grezzo), nessuna discontinuita'.
    **Vincolo di onesta' point-in-time mantenuto**: la selezione per
    singolo titolo resta 2012+ (limite dati costituenti S&P 500); prima
    del 2012 lo slot Equity rende come l'indice proxy stesso, non come un
    basket selezionato (userlo prima sarebbe look-ahead — comporrebbe un
    basket con dati di composizione non noti all'epoca).
  - **Risultato**: serie estesa da 142 a **471 mesi (1987-06 → 2026-08)**.
    Le cifre del periodo TEST mostrate in dashboard (2020-09-30 → 2026-08,
    72 mesi, INVARIATO) sono risultate numericamente identiche prima/dopo
    l'estensione storica (split a valle, nessun effetto) — cambiano SOLO
    per effetto del criterio low-beta: CAGR lordo 20,34% (era 14,16%
    low-vol), Sharpe 1,25 (era 1,08), MaxDD -14,52% (era -10,12%), Sortino
    2,58, Ulcer Index 6,19; combinato Apex(nuovo)/Convex 50/50: CAGR lordo
    18,85% (correttamente tra 16,88% Convex e 20,34% Apex), MaxDD -7,88%
    (inferiore a entrambe le componenti — il beneficio di diversificazione
    resta nel rischio, non nel rendimento, coerente con quanto gia'
    documentato). DSR pieno-campione (471 mesi) e periodo TEST restano
    entrambi >0,999 anche a 100 trial ipotetici; CI 90% bootstrap sullo
    Sharpe TEST [0,23; 1,58], esclude lo zero — l'estensione storica non
    ha indebolito la robustezza statistica gia' verificata.
  - **Convenzione lordo-primario confermata** (richiesta esplicita
    dell'utente "voglio... al lordo di tasse"): gia' lo standard esistente
    del resto della dashboard ("Crescita Annua Lorda" e' gia' la cifra
    primaria mostrata, netto stimato secondario) — nessun cambiamento di
    logica UI necessario, solo numeri aggiornati.
  - **Benchmark SPY esteso per coerenza** (`spy_monthly_history.csv`,
    usato per la linea di confronto sul grafico NAV combinato): stessa
    tecnica di raccordo VFINX/SPY, da 1993 a 1986-09, altrimenti la linea
    di benchmark sarebbe apparsa solo a meta' del grafico ora piu' lungo.
  - **Bug trovato in `home_app.py`**: la didascalia del grafico NAV
    combinato ("Serie mensile dal backtest comune...") aveva l'intervallo
    di date e il conteggio mesi HARDCODED nel testo — sarebbe rimasta
    sbagliata ad ogni futuro aggiornamento dati. Resa dinamica (calcolata
    da `df_comb`), non solo corretta una volta.
  - Aggiunte `sortino_ratio`/`ulcer_index` a `framework/metrics.py` (con
    test), mancanti e necessarie per rigenerare quei due campi.
  - Nuove asserzioni strutturali aggiornate (142→471 mesi) in
    `test_apex_v2_institutional_validation.py` e `test_apex_convex.py` —
    tutte le verifiche statistiche sostanziali (DSR, bootstrap CI,
    drawdown impossibile, netto≤lordo) restano invariate e verdi.
- **RSP al posto di SPY — idea proposta direttamente dall'utente**
  (`apex_rsp_vs_spy_test.py`): SPY (S&P 500 cap-weighted, dominato dalle
  mega-cap) e' usato in due punti indipendenti — il segnale di TIMING
  della classe Equities e il BENCHMARK per il ranking beta nel basket.
  RSP (equal-weight) testato su entrambi, separatamente e insieme, per
  isolare quale effetto guida un eventuale risultato (stessa disciplina
  "isola la variabile" di tutta questa sessione). **Falsificato in tutte
  le combinazioni**, degrado monotono: baseline SPY/SPY 18,98% CAGR
  netto/Sharpe 1,25 → solo timing=RSP 18,77%/1,22 (-0,14pp/anno) → solo
  beta=RSP 18,46%/1,22 (-0,45pp/anno) → entrambi=RSP 17,92%/1,17
  (-0,87pp/anno). Nessuna singola differenza esclude lo zero alla CI 90%,
  ma **PBO-CSCV 4,3%** — non "nessun segnale" (che darebbe ~50%), il
  ranking si riproduce in modo stabile tra gli split: SPY vince in modo
  riproducibile, non per caso campionario. Nessuna modifica in produzione.
- **Dual Momentum tra classi macro (Antonacci 2014) — idea #4 della lista
  di approfondimento richiesta dall'utente**
  (`apex_dual_momentum_class_weight_test.py`): tra le classi ATTIVE (trend
  assoluto invariato), il peso nominale base viene inclinato dal momentum
  RELATIVO (z-score del rendimento trailing 12 settimane), non da una
  misura di rischio — meccanismo diverso da risk parity/class-weight
  beta-pesato (entrambi falliti per la stessa dominanza di Bonds
  sull'inverse-weighting), ma con un rischio speculare esplicitamente
  anticipato in fase di design: Bonds ha tipicamente momentum piu' debole,
  quindi potrebbe finire strutturalmente sotto-pesato. **Il rischio si e'
  materializzato**: peso medio Bonds 14,3%→5,4% da alpha 0,0 a 1,0, CAGR
  full-sample sale in modo monotono (17,71%→19,87%) ma Sharpe scende
  (1,14→1,01) e MaxDD peggiora (-21,53%→-27,33%) — stesso pattern "leva su
  Crypto, il vincitore storico" gia' visto nell'asymmetric class-weight.
  **Walk-forward decisivo**: sia l'Era 2 sia l'Era 3, usando solo
  informazione passata, selezionano SEMPRE alpha=0,0 — il meccanismo
  libero di scegliere non si discosta mai dalla produzione attuale.
  Risultato OOS quindi identico al baseline (differenza 0,00pp/anno, 0%
  delle settimane migliori — letteralmente la stessa serie). PBO-CSCV
  2,9%, coerente: alpha=0,0 vince in modo robusto su ogni split. Nessuna
  modifica in produzione.
- **Skip-month sul segnale di trend (Jegadeesh-Titman 1993, "12-1
  momentum") — idea #5 della lista di approfondimento**
  (`apex_skip_month_signal_test.py`): la distanza dalla MA lunga e il
  confronto con la MA corta usano il prezzo di `skip_weeks` settimane fa
  invece dell'ultima disponibile, escludendo il mese piu' recente dalla
  formazione del segnale — adattamento dichiarato non letterale (12-1 e'
  nato per il ranking cross-sectional di momentum, non per un incrocio di
  medie mobili su un singolo asset). Ipotesi nulla dichiarata in anticipo:
  "nessun effetto" (la banda di isteresi adattiva gia' assorbe parte del
  rumore). **Falsificato in modo piu' netto del previsto — non solo
  nessun effetto, un danno diretto e monotono**: CAGR 20,08%/Sharpe 1,32
  (skip=0, attuale) → 14,49%/0,96 (skip=4) → 8,35%/0,69 (skip=8).
  Ritardare il prezzo di riferimento di un mese significa entrare piu'
  tardi nei trend e assorbire piu' reversal — l'opposto di cosa fa il
  skip-month accademico per il momentum cross-sectional (li' evita di
  pesare titoli per un mese-fluke; qui ritarda la reazione al trend
  dell'asset stesso, meccanismo diverso, l'analogia non regge). Walk-
  forward sceglie sempre skip_weeks=0 in ogni era, risultato OOS identico
  al baseline. **PBO-CSCV 0,0%** — il segnale piu' forte di stabilita' del
  ranking visto in questa sessione. Nessuna modifica in produzione.
- **Regime filter indipendente dal prezzo: curva dei rendimenti 10Y-3M
  (Estrella-Mishkin 1996) — idea #6 della lista di approfondimento**
  (`apex_yield_curve_regime_filter_test.py`): a differenza di tutto il
  segnale Apex (sempre derivato da MA/volatilita' del prezzo), filtro
  ADDITIVO (AND) SOLO su Equities — attiva solo se il trend di prezzo lo
  conferma E la curva 10Y-3M (^TNX-^IRX) non e' invertita in quel momento
  (contemporaneo, nessun ritardo aggiunto apposta per non introdurre
  un'altra dimensione da ottimizzare). Rischio dichiarato in anticipo: la
  curva invertita predice la recessione con un RITARDO tipico di 6-18
  mesi (spesso le azioni salgono ancora dopo l'inversione, "l'ultimo
  rally") — un filtro contemporaneo rischia di disattivare Equities
  troppo presto. **Risultato misto, non una falsificazione netta come le
  precedenti**: CAGR 19,17% (filtrato) contro 18,98% (baseline, leggermente
  meglio) ma Sharpe 1,22 contro 1,25 e MaxDD -19,29% contro -18,49%
  (entrambi leggermente peggiori) — il rischio anticipato si e' concretizzato:
  il filtro taglia l'esposizione in anticipo rispetto al vero punto di
  svolta. CI 90% sulla differenza CAGR [-0,48;+1,01], include lo zero.
  PBO-CSCV 0,0%, coerente con "baseline vince in modo stabile sullo
  Sharpe" (non con "il filtro e' validato" — con solo 2 configurazioni un
  PBO basso premia chi ha lo Sharpe pieno-campione piu' alto in modo
  consistente sugli split, qui il baseline). Nessuna modifica in
  produzione — curva 10Y-3M dichiaratamente non lo strumento giusto in
  questa forma contemporanea, un filtro con lag potrebbe comportarsi
  diversamente ma introdurrebbe un altro parametro da walk-forward-are,
  non testato qui.
- **Ricalibrazione Kelly della leva di Convex Stack — idea #8 della lista
  di approfondimento**: domanda di calibrazione (la leva 1,225x embedded
  di NTSG e' vicina all'ottimo?), non una riproposta di Kelly Stack come
  pilastro (gia' esplorato e scartato) — calcolo diretto, nessun backtest
  necessario. Sulla serie reale di produzione (312 mesi, 2000-2026):
  Sharpe 0,879, volatilita' annualizzata 11,36%. **Kelly ottimale
  (f*=μ/σ², log-utility): 7,74x — la leva attuale rappresenta solo il
  15,8% del Kelly pieno.** Non e' un errore di calibrazione: il Kelly
  pieno assume rendimenti log-normali IID senza errore di stima su μ (in
  pratica lo Sharpe stimato su un campione storico ha un errore standard
  enorme rispetto a quanto servirebbe per fidarsi di f* alla lettera),
  ignora code grasse/vol clustering, e massimizza la crescita geometrica
  assumendo infinite scommesse ripetibili — un singolo percorso storico
  reale non ha questa proprieta' (un episodio di leva estrema puo'
  azzerare il capitale, dopo di che "il lungo periodo" non esiste piu').
  I praticanti professionali usano tipicamente il 5-25% del Kelly pieno
  proprio per questi motivi — il 15,8% attuale cade esattamente in
  questo intervallo standard. **Nessuna modifica**: la leva 1,225x e'
  coerente con la pratica prudente standard ed e' strutturalmente sicura
  (leva istituzionale via NTSG, non a margine personale — nessun rischio
  di richiamo margine); muoversi verso il Kelly implicito comprometterebbe
  deliberatamente quella garanzia per un guadagno teorico che il calcolo
  stesso avverte di non prendere alla lettera.
- **Diversificazione geografica reale (home bias, Ilmanen/Asness) — idea
  #7 della lista di approfondimento, l'ultima del giro**
  (`apex_international_equities_class_test.py`): Apex e' oggi 100%
  azionario USA. Testata una QUINTA classe macro indipendente,
  "IntlEquities" su EFA (MSCI EAFE — Europa + Giappone + Australasia +
  Estremo Oriente), stesso meccanismo di trend/isteresi delle altre 4,
  nessuna selezione titolo-per-titolo (esposizione ampia via ETF, aggira
  deliberatamente il limite point-in-time che blocca l'idea #1 non-US
  ancora in coda). **Risultato sfumato, non una falsificazione netta**:
  CAGR 17,77% (5 classi) contro 18,98% (baseline) ma CI 90%
  [-2,64;+0,32] include lo zero — non significativo; Sharpe praticamente
  identico (1,24 contro 1,25); **il MaxDD MIGLIORA davvero** (-17,23%
  contro -18,49%) — un genuino beneficio di diversificazione nella coda
  del rischio, coerente con la letteratura home-bias. Campione limitato
  (626 settimane, 2014-2026, dominato dalla sovraperformance USA post-2014
  — "US exceptionalism" — che probabilmente penalizza International nel
  breve/medio termine rispetto al caso strutturale di lungo periodo che la
  letteratura sostiene). PBO-CSCV 0,0% riflette il piccolo vantaggio
  Sharpe del baseline, non una bocciatura netta del meccanismo. **Nessuna
  modifica in produzione ora**, ma tra tutte le idee di questo giro e'
  quella con l'esito meno negativo — non chiusa, solo non abbastanza forte
  da giustificare un cambio subito. **AGGIORNAMENTO — capovolto
  dall'approfondimento su storico piu' lungo qui sotto: il miglioramento
  MaxDD era un artefatto della finestra 2014-2026, non regge su un
  campione piu' lungo. Vedi voce successiva.**
- **Verdetto complessivo del giro di approfondimento (idee #4-8 della
  lista, richiesto dall'utente)**: su 5 idee testate con piena disciplina
  walk-forward/PBO/bootstrap, 3 falsificate in modo netto (dual momentum,
  skip-month, entrambe con lo stesso pattern "leva su Crypto il vincitore
  storico" o danno diretto), 1 confermata come gia' ben calibrata (leva
  Kelly), 2 con risultato inizialmente sfumato (regime filter curva dei
  rendimenti, diversificazione geografica) — **entrambe poi falsificate
  con approfondimenti successivi** (lag sulla curva, storico piu' lungo
  su IntlEquities — vedi voci sotto). Restano bloccate per dati
  insufficienti: campione BAB non-US (idea #1) e quality overlay (idea
  #2) — da riprovare con altre fonti.
- **Kelly tra Apex e Convex (mix a 2 asset) — domanda diretta dell'utente
  dopo il controllo di calibrazione della leva di Convex**
  (`apex_convex_kelly_mix_test.py`): NON una riproposta di Kelly Stack
  (che ha gia' applicato Kelly alle sleeve INTERNE di Convex in modo
  esaustivo, 8 round di risultati — vedi `KELLY_STACK_SPEC.md`) — qui il
  MIX tra i due motori interi (oggi 50/50 di default), mai testato prima.
  Calcolo diretto, nessun backtest, sulle serie reali di produzione (312
  mesi comuni, 2000-2026): Apex mu=15,39%/sigma=12,94%/Sharpe 1,19,
  Convex mu=9,98%/sigma=11,36%/Sharpe 0,88, correlazione 0,270 (CI 90%
  [0,155;0,357], stima ragionevolmente stabile).
  - **Due ottimizzazioni diverse danno risposte diverse — la divergenza
    stessa e' l'informazione utile.** Massimizzare lo SHARPE del mix
    (nessuna leva extra) da' un punto teorico ~60% Apex/40% Convex,
    confermato dal confronto empirico diretto sulle serie reali (Sharpe
    picca 1,31 a 50/50-70/30, contro 1,19 di Apex puro). Massimizzare
    invece la CRESCITA GEOMETRICA attesa (la vera metrica Kelly, non lo
    Sharpe) vincolata al simplesso (100% investito, niente leva
    aggiuntiva) da' una soluzione d'angolo: **100% Apex, 0% Convex** —
    non un errore, ma la conseguenza matematica di essere vincolati a
    stare tutti investiti: oltre il punto Sharpe-ottimale conviene ancora
    spostarsi verso l'asset col mu assoluto piu' alto, dato che non si
    puo' scalare la leva per sfruttare il rapporto ottimale.
  - **Perche' NON prendere la soluzione d'angolo alla lettera**: il
    vantaggio di Apex su Convex in questo campione e' +5,41pp/anno ma con
    **CI 90% [+0,37;+10,65]** — esclude lo zero per un soffio, intervallo
    enorme. La spinta verso "100% Apex" dipende quasi interamente da
    quanto quel vantaggio storico e' reale e persistente; al bordo
    inferiore della CI sparirebbe quasi del tutto. Stessa fragilita' gia'
    vista nel controllo sulla leva di Convex, qui amplificata dal fatto
    di confrontare solo 2 asset invece di distribuire l'incertezza su un
    portafoglio diversificato.
  - **Verdetto**: il segnale piu' solido e' quello Sharpe-based (50/50 a
    70/30 Apex, coerente sia in teoria sia sui dati reali) — il 50/50
    attuale sta gia' dentro la zona ragionevole, con margine plausibile
    per uno spostamento leggero verso Apex (60/40) se si volesse
    ottimizzare, ma nessuna base solida per un cambio drastico. **Nessuna
    modifica al mix di default** sulla base di questo calcolo da solo.
  - **Seguito — decisione esplicita dell'utente: mix di default cambiato
    da 50/50 a 70/30 Apex/Convex.** `config.json` (stato reale
    dell'utente), i default di `load_config()`/`compute_unified_portfolio`/
    `home_app.py` e le cifre di `get_combined_dual_engine_metrics()`
    aggiornati insieme, per coerenza — altrimenti la card "standard" e il
    grafico personalizzato dell'utente avrebbero mostrato numeri
    disallineati. **Nota onesta emersa SOLO ricalcolando sul periodo TEST
    (72 mesi, 2020-2026, la finestra standard di dashboard — piu' corta e
    piu' recente del campione 2000-2026 usato per il calcolo Kelly)**: su
    questa finestra 70/30 ha CAGR lordo piu' alto (19,53% contro 18,85%)
    ma Sharpe (1,42 contro 1,49) e MaxDD (-8,90% contro -7,88%)
    leggermente PEGGIORI del 50/50 — il tradeoff dipende dalla finestra
    osservata, non e' univoco nella direzione "70/30 sempre meglio". Il
    beneficio di diversificazione resta comunque intatto rispetto a
    ciascuna componente isolata. Segnalato esplicitamente all'utente prima
    di confermare l'implementazione.
- **Approfondimento regime filter curva rendimenti CON RITARDO — richiesto
  dall'utente dopo il risultato sfumato del filtro contemporaneo**
  (`apex_yield_curve_lagged_filter_test.py`): Equities forzata a 0% se la
  curva 10Y-3M ERA invertita `lag_weeks` fa (non ora) — griglia [0
  (contemporaneo, test precedente), 26 (~6 mesi), 52 (~12 mesi), il range
  tipico di ritardo recessione-dopo-inversione in letteratura). **Nessun
  miglioramento robusto — la conclusione precedente si conferma, non si
  ribalta.** Full-sample il lag a 12 mesi sembra il migliore (Sharpe 1,33
  contro 1,29 del contemporaneo), ma il walk-forward smentisce: selezionando
  il lag SOLO con informazione passata (Era 2→26 sett., Era 3→52 sett.), il
  risultato OOS combinato (356 settimane) e' leggermente PEGGIORE del
  semplice lag=0 gia' testato (CAGR 15,13% contro 15,47%, Sharpe 1,04
  contro 1,06) — differenza -0,28pp/anno, CI 90% include lo zero, solo 31%
  delle settimane migliori. PBO-CSCV 4,3% conferma che il ranking
  full-sample e' riproducibile (lag=52 vince spesso sui singoli split) ma
  questo non si traduce in un vantaggio OOS onesto quando la selezione
  avviene senza guardare al futuro — aggiungere un ritardo deliberato
  sposta dove il filtro sbaglia, non risolve il problema. **Nessuna
  modifica in produzione**: il filtro sulla curva dei rendimenti, in
  nessuna forma testata (contemporaneo o con lag), supera la produzione
  attuale (nessun filtro) in modo robusto — linea di indagine chiusa.
- **Approfondimento diversificazione geografica su storico più lungo —
  richiesto dall'utente dopo il risultato "meno negativo" del test
  precedente (limitato al 2014-2026)** (`apex_international_equities_long_history_test.py`):
  stessa tecnica di raccordo proxy gia' validata per l'estensione storica
  dashboard (splice per rendimento) — Equities=VFINX→SPY, Bonds=VUSTX→IEF,
  Gold=GC=F→GLD, IntlEquities=VGTSX (Vanguard Total International Stock
  Index, fondo ampio non growth-tilted, dal 1996-05)→EFA dal 2001-08.
  Campione quasi raddoppiato: 1355 settimane (2000-2026) contro 626
  (2014-2026) del test precedente. **Il risultato SI RIBALTA — ora e' una
  falsificazione netta, non piu' sfumata.** Sia Sharpe (0,92 contro 0,97)
  sia MaxDD (-23,15% contro -20,96%) PEGGIORANO con IntlEquities — l'esatto
  opposto del miglioramento MaxDD che sembrava il punto di forza del test
  precedente. Isolando SOLO il periodo 2001-2014 (escluso dal test
  precedente, teoricamente favorevole a un beneficio di diversificazione:
  dot-com bust, crisi 2008) il risultato resta negativo su entrambe le
  metriche (Sharpe 0,63 contro 0,72, MaxDD -23,15% contro -20,96%) — non
  e' un effetto specifico del periodo recente che si stava correggendo,
  il meccanismo non regge in nessuna sotto-finestra testata. CI 90%
  [-1,82;+0,39] include lo zero, solo 44% delle settimane migliori,
  PBO-CSCV 0,0% (baseline vince in modo stabile). **Correzione esplicita
  della lettura precedente**: il miglioramento MaxDD osservato nel primo
  test non era un beneficio strutturale di diversificazione geografica,
  era un artefatto della finestra 2014-2026 usata li'. Nessuna modifica in
  produzione — linea di indagine chiusa, a differenza della valutazione
  precedente ("non chiuderei la porta").
- **Kelly sulle classi macro di Apex — testato nonostante la bassa
  priorita' dichiarata e la prior fortemente negativa (stesso meccanismo
  di risk parity/class-weight beta-pesato, entrambi gia' falliti)**
  (`apex_kelly_class_weight_test.py`). **La prior si e' rivelata
  sbagliata — correzione esplicita.** Risk parity e class-weight
  beta-pesato pesano PURAMENTE inversamente al rischio (1/vol, 1/beta):
  qualunque asset con rischio vicino a zero ottiene un peso enorme a
  prescindere dal rendimento atteso — per questo Bonds dominava in
  entrambi. Kelly (f*=Sigma^-1 mu, effettivamente mu/sigma^2 su una
  Sigma quasi diagonale) pesa per RENDIMENTO diviso rischio al quadrato —
  un asset a basso rischio ottiene un peso grande solo se il rendimento
  atteso lo giustifica. Qui non ha sovrappesato Bonds in modo patologico:
  ha invece RIDOTTO Crypto (peso medio 12,4%→~5%, la sua volatilita'
  enorme pesa piu' del suo mu elevato), Bonds sostanzialmente stabile —
  meccanismo diverso, non lo stesso fallimento.
  - **Design**: mu/Sigma annualizzati stimati su finestra trailing di 156
    settimane (3 anni, stessa convenzione Kelly Stack/bond-value theory di
    questa sessione), f* clippato a >=0 (long-only), frazione di Kelly
    testata su griglia [0,0=controllo, 0,25, 0,5, 1,0] — sostituisce il
    50% nominale SOLO per le classi gia' attive per trend (invariato).
  - **Risultato full-sample**: tutte le frazioni non-zero migliorano
    Sharpe (1,09-1,10 contro 1,01) E dimezzano quasi il MaxDD (-13,6/13,8%
    contro -21,53%) mantenendo CAGR sostanzialmente invariato o
    leggermente migliore (14,59% a frac=1,0 contro 14,55%).
  - **Walk-forward — per la prima volta in questa sessione su questo
    asse, il meccanismo si discosta davvero dal controllo**: Era 2
    seleziona frac=0,50, Era 3 frac=1,00 (mai 0,0) — a differenza di
    OGNI altro test di class-weighting/asymmetric-weight/dual-momentum di
    questa sessione, dove il walk-forward tornava sempre al controllo.
    OOS (314 settimane): Sharpe 1,05 contro 0,98, MaxDD quasi dimezzato
    (-13,77% contro -21,53%), CAGR sostanzialmente invariato.
  - **Ma non ancora statisticamente provato**: CI 90% sulla differenza
    [-6,97;+7,26] — enorme, include ampiamente lo zero; PBO-CSCV 48,6%,
    praticamente al livello del rumore. Il miglioramento di MaxDD e'
    economicamente grande e il meccanismo ha una spiegazione sensata, ma
    il campione OOS (314 settimane) non basta per escludere la fortuna.
  - **Verdetto: NON falsificato — il risultato piu' promettente di questo
    intero giro di approfondimento Kelly, capovolge la prior iniziale.**
    Non pronto per produzione (CI troppo ampia), ma merita un secondo
    giro di verifica indipendente (campione piu' lungo se possibile,
    stress su finestra mu/Sigma, robustezza della frazione) prima di
    scartarlo o adottarlo — trattato come "promettente ma non ancora
    validato", non come chiuso.
- **Secondo giro di verifica — Kelly sulle classi macro di Apex**
  (`apex_kelly_class_weight_second_round_test.py`): stress-test su griglia
  finestra mu/Sigma [104, 156, 208] settimane (2/3/4 anni) x frazione Kelly
  [0,0; 0,25; 0,5; 1,0] (12 combinazioni), walk-forward esteso da 3 a 5 ere
  (335 settimane OOS contro 314).
  - **Il beneficio NON e' uniforme su tutte le finestre**: a 104 settimane
    (2 anni) Kelly non batte il controllo (Sharpe 0,91-0,95 contro
    baseline 0,95, MaxDD invariato -21,3% contro -21,53%) — nessun
    beneficio reale. A 156 e 208 settimane il beneficio del primo giro si
    conferma pienamente (Sharpe 1,02-1,15, MaxDD -13,6/15,1% contro
    -21,53%). Spiegazione plausibile e coerente con la letteratura: a
    finestra corta l'errore di stima di mu (il termine a cui Kelly e' piu'
    sensibile) e' troppo alto — non e' un'obiezione ad hoc, e' un
    limite noto del criterio di Kelly con campioni piccoli. Implicazione
    pratica: la finestra di stima non e' arbitraria, va fissata a priori
    (156 o 208 settimane), non scelta a posteriori sul risultato migliore.
  - **Walk-forward su tutte le 12 combinazioni congiuntamente**: seleziona
    quasi sempre finestra=208/frac=0,25 (3 ere su 4), mai frac=0,0. OOS (5
    ere, 335 settimane): Sharpe 1,14 contro baseline 1,00, MaxDD -15,10%
    contro -21,53%, CAGR 16,36% contro 13,95% — risultato piu' forte del
    primo giro (che era 1,05 contro 0,98).
  - **PBO-CSCV sceso da 48,6% (rumore) a 7,1%** sulle 12 combinazioni —
    cambio di categoria statistica, non piu' indistinguibile dal rumore.
  - **Ma il CI 90% sulla differenza accoppiata OOS include ancora lo
    zero**: [-4,10;+7,84] pp/anno (overperformance media +2,12pp/anno),
    settimane migliori 50% (166/335) — a livello settimanale il
    vantaggio non e' visibile testa a testa, emerge solo nella coda
    sinistra (drawdown) accumulata nel tempo.
  - **Verdetto aggiornato: sostanzialmente rafforzato, ancora non provato
    in modo definitivo.** Il PBO basso e la coerenza su 2 finestre su 3
    (con una spiegazione di principio, non post-hoc, per la terza)
    spostano la confidenza da "al livello del rumore" a "moderata,
    meccanismo credibile" — ma il CI largo sulla differenza pareggiata
    impedisce ancora di dichiararlo statisticamente provato. Raccomandazione:
    se si decide di adottarlo in produzione, fissare la finestra a 208
    settimane (la piu' robusta nei due test) e una frazione moderata
    (0,25-0,5) come scelta pre-registrata, non ottimizzata sul risultato;
    in alternativa, continuare a monitorarlo come promettente senza
    ancora implementarlo. Nessuna modifica in produzione applicata da
    questo secondo giro — decisione lasciata all'utente.
- **Campione indipendente non-US per BAB — idea #1 della lista originale,
  finora bloccata** (`apex_international_bab_country_etf_test.py`).
  Blocco dichiarato: replicare la Teoria #5 (beta-selection titolo-per-
  titolo, gia' in produzione sul basket USA) su FTSE100/STOXX600
  richiederebbe uno storico datato delle variazioni di composizione
  dell'indice, non disponibile in forma pulita per gli indici europei
  (a differenza di Wikipedia per l'S&P 500). **Altra strada**: testare
  BAB a livello di PAESE invece che di singolo titolo — 15 ETF Paese
  sviluppato di iShares MSCI con storico dal 1996 (Giappone, Germania,
  UK, Francia, Australia, Canada, Svizzera, Svezia, Spagna, Italia,
  Paesi Bassi, Austria, Belgio, Singapore, Hong Kong), beta trailing 26
  settimane (stessa finestra di produzione) vs un benchmark equal-weight
  auto-costruito sugli stessi 15, ribilanciamento trimestrale. Nessun
  problema di point-in-time membership: l'ETF-paese e' l'unita'
  investibile stessa dal lancio, non un proxy di un indice che cambia
  composizione.
  - **Risultato: l'anomalia BAB NON si replica a livello di paese — anzi
    si inverte.** Low-beta (7/15) Sharpe 0,25 contro High-beta (7/15)
    Sharpe 0,33 contro Equal-weight Sharpe 0,29, su 1530 settimane
    (1996-2026). Spread classico BAB (low-beta meno high-beta):
    **-2,88pp/anno, CI 90% [-5,35;-0,14] ESCLUDE lo zero** — nella
    direzione OPPOSTA a quella prevista. Nei 4 sotto-periodi testati
    (1997-2004, 2004-2012, 2012-2019, 2019-2026) l'high-beta ha Sharpe
    uguale o superiore al low-beta in OGNI singolo sotto-periodo, mai
    un'eccezione. PBO-CSCV 18,6% (sotto la soglia di rumore, ma piu' alto
    delle falsificazioni piu' nette di questa sessione).
  - **Interpretazione**: questo NON invalida la Teoria #5 sul basket
    azionario USA (Frazzini-Pedersen 2014 e' specificamente una storia di
    investitori vincolati dalla leva che comprano AZIONI SINGOLE ad alto
    beta per ottenere leva sintetica — un meccanismo idiosincratico a
    livello di titolo, non necessariamente un principio universale "il
    rischio sistematico piu' basso vince sempre" applicabile a qualunque
    unita' di analisi). A livello di PAESE, 30 anni di dati mostrano
    l'esatto contrario: i mercati piu' "beta" (piu' legati al ciclo
    growth/tech globale) hanno sovraperformato in modo consistente. La
    validazione indipendente NON CORROBORA una generalizzazione
    geografica del meccanismo — la Teoria #5 resta valida (e in
    produzione) come fenomeno specifico del basket azionario USA
    titolo-per-titolo, non come legge universale. Nessuna modifica in
    produzione (Apex non investe per paese). Linea di indagine chiusa
    con esito onesto: negativo/invertito, non solo "non significativo".
  - **Approfondimento richiesto dall'utente: e' colpa della BETA
    specificamente, o low-VOLATILITA' (assoluta, non contro benchmark)
    sarebbe piu' robusta a livello di paese?**
    (`apex_international_lowvol_vs_beta_country_test.py`, stesso
    universo/finestra/cache, nessun nuovo download). Risposta: **low-vol
    e' leggermente MEGLIO di low-beta ma non e' robusta in senso
    assoluto**. Sharpe: High-beta 0,33 > Equal-weight 0,29 ~ Low-vol
    0,28 ~ High-vol 0,28 > Low-beta 0,25. Low-vol batte low-beta di
    +0,61pp/anno (CI 90% [-0,37;+1,52], include lo zero) ma NON vince mai
    in nessuno dei 4 sotto-periodi testati (sempre sotto high-beta o
    equal-weight) e perde leggermente contro l'equal-weight sull'intero
    campione (-0,71pp/anno). **Causa della somiglianza tra le due
    classifiche**: sovrapposizione media 5,9/7 paesi tra i basket
    low-beta e low-vol per ribilanciamento — a livello di paese, a
    differenza del singolo titolo USA (dove il rischio idiosincratico
    crea vera separazione tra beta e volatilita' assoluta), le due
    misure sono quasi ridondanti perche' gran parte della varianza di un
    indice-paese e' comunque covarianza col resto del mondo sviluppato.
    PBO-CSCV sale a 25,7% su 5 varianti (piu' alto del test a 3 varianti,
    riflette l'ambiguita' reale tra le 3 opzioni centrali quasi
    equivalenti). **High-beta risulta il piu' forte in modo consistente**
    (vince o pareggia in 3 sotto-periodi su 4), ma la lettura piu'
    plausibile non e' "l'anomalia si inverte davvero": su un campione di
    30 anni in cui i mercati sviluppati sono saliti per la gran parte del
    tempo, un basket a beta piu' alto verso il fattore azionario globale
    comune ottiene semplicemente PIU' esposizione a un fattore con drift
    storicamente positivo — coerente con differenze di Sharpe modeste
    (0,25-0,33) a fronte di differenze di CAGR piu' vistose (2,92% contro
    4,96%), non con una vera "leva a sconto" stile BAB. Nessuna modifica
    in produzione (nessuna delle due metriche giustifica un cambio; Apex
    non investe per paese comunque). Estensione a un universo di paesi
    piu' ampio (es. mercati emergenti, storico piu' corto dal 2000) resta
    disponibile come ulteriore verifica ma valutata a bassa priorita': data
    l'alta sovrapposizione gia' osservata e la consistenza across-era del
    risultato attuale, e' improbabile che cambi la conclusione qualitativa.
- **Quality overlay sul basket low-beta — idea #4 della lista originale,
  finora bloccata** (`apex_quality_tilt_low_beta_basket_test.py`).
  Blocco dichiarato: una vera Quality richiede fondamentali storici
  (ROE, leva) che Yahoo Finance non offre, e senza un dato genuinamente
  point-in-time il test sarebbe viziato da look-ahead. **Altra strada**:
  SEC EDGAR XBRL Company Facts API (gratuita) riporta per ogni dato il
  campo `filed` — la data REALE di deposito, non la fine del periodo
  contabile — quindi e' autenticamente point-in-time. Costruita una
  cache locale di ROE annuale (NetIncomeLoss/StockholdersEquity, solo
  10-K/10-K/A, tag XBRL tra i piu' universali) per 477/503 ticker
  dell'universo S&P 500 usato dal basket (`apex_quality_data/`). La
  SELEZIONE del basket resta identica a produzione (beta vs SPY, cap
  settoriale) — la qualita' inclina solo il PESO tra i 15 titoli gia'
  selezionati, equal-weight con alpha=0 (controllo esatto).
  - **Risultato full-sample**: miglioramento piccolo ma monotono con
    alpha — Sharpe 1,14→1,16, CAGR 17,71%→18,05%, MaxDD sostanzialmente
    invariato (-21,53% a -21,12/21,63% a seconda di alpha, nessun
    beneficio di coda paragonabile alla Teoria #5 o al Kelly di classe).
  - **Walk-forward (3 ere)**: Era 2 seleziona alpha=0,0 (controllo), Era
    3 seleziona alpha=1,0. OOS (391 settimane): Sharpe 1,00 contro 0,98,
    CAGR 14,56% contro 14,24% — miglioramento reale ma piccolo.
  - **CI 90% sulla differenza pareggiata [-0,14;+0,78]pp/anno — include
    lo zero per un margine molto stretto** (il limite inferiore e' quasi
    a zero). PBO-CSCV 12,9%, sotto la soglia di rumore.
  - **Dettaglio interessante**: solo il 26% delle settimane il tilt fa
    meglio del controllo, nonostante la differenza media sia positiva —
    profilo di rendimento asimmetrico coerente con la letteratura
    quality/safety (piccolo costo nella maggioranza delle settimane
    "normali", guadagni rari ma piu' ampi nelle settimane di stress),
    non un errore di calcolo: la distribuzione della differenza e'
    spostata a destra da poche settimane di forte protezione.
  - **Verdetto: NON falsificato, ma marginale** — direzione giusta,
    PBO accettabile, ma magnitudine economica piccola e nessun
    beneficio di drawdown paragonabile agli altri candidati promettenti
    di questa sessione (Teoria #5, Kelly di classe). Non giustifica un
    cambio in produzione ora ne' un secondo giro dedicato con la stessa
    priorita' del Kelly di classe — resta un candidato disponibile ma
    a bassa priorita' per un eventuale approfondimento futuro (es. doppio
    ordinamento beta+quality, o fattore quality alternativo).

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
