# Guida per un audit indipendente

Questo documento esiste per un solo scopo: permettere a un agente (o una
persona) SENZA il contesto di questa sessione di rieseguire gli stessi
test, con gli stessi metodi e parametri, e verificare autonomamente le
conclusioni riportate in `validation_suite/README.md` — senza doversi
fidare della mia parola, e senza dover rileggere l'intera conversazione
che le ha prodotte.

**Principio guida**: ogni numero citato in `README.md` è riproducibile
lanciando UNO script preciso, con dati che sono già nel repository (non
serve rigenerare nulla per iniziare). Se un numero non torna, il primo
sospetto è un bug in QUESTO audit di verifica, non necessariamente
nell'originale — ma è esattamente il tipo di discrepanza che vale la pena
segnalare.

## 1. Ambiente

```bash
git clone <questo repository>
cd apex-engine
pip install -r requirements.txt -r validation_suite/requirements-test.txt
```

Nessuna altra dipendenza. Convenzione deliberata del progetto: **niente
scipy** — tutta la statistica (Deflated Sharpe Ratio, inversa della
normale) è implementata a mano in `validation_suite/framework/statistical_validation.py`
con solo `math.erf` e l'algoritmo di Acklam. Se un fix o un'estensione
tenta di importare scipy, è già un segnale che sta deviando dalla
convenzione del progetto, non un dettaglio neutro.

## 2. Passo 1 — la suite di regressione (secondi, nessuna rete)

```bash
./validation_suite/run_fast_suite.sh
# equivalente esplicito:
PYTHONPATH=. python -m pytest validation_suite/ -v
```

**Atteso: 141 passed, 0 failed** (12 settembre 2026 — se il numero è
diverso, o `validation_suite/comparative_studies/` è cresciuta con nuovi
test da promuovere, o qualcosa si è rotto: controllare quale). Questa
suite copre `framework/` (metriche, motore fiscale, validazione
statistica), `kelly_stack/` (Kelly Stack, esplorato e scartato) e
`core_regression/` (motore Apex V2/Convex/PortfolioManager LIVE — questa
parte gira anche in CI ad ogni push, vedi `.github/workflows/ci.yml`).

Non copre `comparative_studies/` (troppo lenta/dipendente da input per un
gate automatico) — è il Passo 2.

## 3. Passo 2 — la serie canonica di produzione

La fonte di verità per OGNI metrica mostrata in dashboard
(`portfolio_manager.get_apex_metrics()`, `get_combined_dual_engine_metrics()`)
è generata da un solo script:

```bash
python validation_suite/comparative_studies/apex_dashboard_stat_regeneration.py
```

Rigira l'intero backtest Apex 4-classi (1987-06 → oggi, ~471 mesi:
proxy storici pre-2012, selezione azionaria low-beta reale point-in-time
dal 2012) e scrive `apex_monthly_returns_extended_gross.csv` /
`apex_monthly_returns_extended.csv` nella root del repo. Stampa a schermo
le statistiche del periodo TEST (72 mesi, walk-forward, mai usato per
scegliere i parametri) — **confrontale riga per riga con i valori
hardcoded nel docstring/return-dict di `portfolio_manager.get_apex_metrics()`**:
se non coincidono, o il codice di produzione è stato cambiato senza
rigenerare la serie, o viceversa.

Impiega qualche minuto (~600 titoli, 471 settimane, selezione beta ricalcolata
ogni trimestre) — non è un test, è la pipeline di ricerca reale.

## 4. I dati: cosa è tracciato, cosa si rigenera da solo

**Tutto quello che serve è già nel repository** (nessun fetch a reti
esterne necessario per riprodurre i numeri esistenti byte-per-byte):

| Cartella | Contenuto | Stato |
|---|---|---|
| `validation_suite/pointintime_data/` | Composizione REALE S&P 500 per anno (2012-2026, da Wikipedia via Wayback Machine) e classifica REALE altcoin per market cap (2019-2026, da CoinMarketCap via Wayback) | **Tracciata in git, NON rigenerabile banalmente** — è la difesa strutturale contro il survivorship bias, non un dato di mercato qualunque |
| `validation_suite/comparative_studies/apex_stocks_data/` | Cache prezzi settimanali di 705 titoli (universo storico completo, non solo i membri attuali) | Tracciata in git (~16MB) — su richiesta esplicita dell'utente di salvare sempre i dati riutilizzabili in modo durevole |
| `.../altcoin_data/`, `altcoin_daily_data/`, `convex_grid_data/`, `carry_funding_data/`, `apex_macro_extended_data/`, `apex_country_etf_data/`, `apex_quality_data/`, `convex_extended_data/`, `apex_sensitivity_series/` | Cache prezzi/dati per gli script comparativi corrispondenti | Tutte tracciate in git (vedi `.gitignore`, sezione "ora TRACCIATE") |
| `apex_monthly_returns_extended*.csv`, `convex_monthly_returns.csv` (root) | Serie canoniche già rigenerate | Tracciate — sono l'OUTPUT del Passo 2, non un input |

Se una cache manca o è vuota, ogni script comparativo la rigenera da solo
al primo avvio (pattern `if not DATA_DIR.exists(): fetch_...()`), scaricando
da:
- **Yahoo Finance chart API** (`query2.finance.yahoo.com/v8/finance/chart/<ticker>`) — prezzi storici, la fonte primaria ovunque in questo progetto.
- **Kraken Futures API** (`futures.kraken.com/derivatives/api/v4/historicalfundingrates`) — funding rate perpetual, solo ~1 anno di storico reale disponibile (limite dell'API, dichiarato ovunque venga usato).
- **Wikipedia/CoinMarketCap via Wayback Machine** — SOLO per ricostruire `pointintime_data/` da zero (raro: quei file sono già tracciati e stabili, non vanno rigenerati a meno che non si stia estendendo la copertura storica).

**Avvertenza onesta**: un fetch fresco da Yahoo potrebbe restituire prezzi
leggermente diversi da quelli cacheati (aggiustamenti per dividendi/split
successivi, o nuovo storico se il ticker ha continuato a tradare) — uno
scostamento di qualche decimo di punto percentuale sui CAGR è normale e
non indica un errore; uno scostamento grande sì.

## 5. Script prioritari da riverificare (sessione del 12 settembre 2026)

In ordine di rilevanza per le conclusioni più recenti e più consequenziali.
Ognuno stampa a schermo i numeri citati nella sezione di `README.md`
indicata — confrontali direttamente, non serve altro strumento.

| # | Script | Cosa verifica | Risultato atteso (sintesi) | Sezione README |
|---|---|---|---|---|
| 1 | `apex_dashboard_stat_regeneration.py` | Serie canonica corretta (survivorship bias, same-bar leak, costo turnover basket — 3 bug reali trovati e corretti in questa sessione) | CAGR lordo TEST ~19,6%, Sharpe ~1,36, MaxDD storico ~-14,7% | "Test di robustezza e invalidazione istituzionale completo" |
| 2 | `apex_v2_vs_v3_full_comparison.py` | v3 (low-beta+Kelly, produzione) vs v2 (low-vol, no Kelly) sulla STESSA pipeline corretta | CAGR statisticamente pari in entrambe le finestre (mai un CI90 che esclude lo zero); v3 meglio su Sharpe/Ulcer, non uniformemente su MaxDD | "Confronto diretto v2 ... vs v3 completo" |
| 3 | `apex_bab_long_short_quantified_test.py` | Esperimento "rimuoviamo i vincoli" — vero BAB long/short a leva (Frazzini-Pedersen), quantificato con costi/tasse | Fallisce nel periodo recente: Sharpe~0,09, CAGR lordo -0,60%, MaxDD -48,66% (piu' del triplo del peggior calo in 39 anni del sistema attuale) | "Esperimento mentale: rimuoviamo i vincoli" |
| 4 | `apex_tax_loss_harvesting_test.py` | Raccolta minusvalenze nella zona cuscinetto del ribasket — l'unica idea testata che non tocca CAGR/rischio | Segno corretto (meno tasse pagate, CAGR lordo invariato) ma magnitudine non significativa (CI90 include lo zero) nella versione conservativa | "Tax-loss harvesting sul basket" |
| 5 | `convex_threshold_vs_calendar_rebalance_test.py` | Ribilanciamento a soglia vs calendario su Convex (Daryanani 2008) | Batte il mensile (CI90 esclude lo zero), non prova il vantaggio su "mai ribilanciare" (campione corto, 81 mesi) | "Convex — ribilanciamento a soglia di tolleranza" |
| 6 | `apex_kelly_vs_flat_bootstrap_robustness.py` | Robustezza del CI bootstrap sul confronto Kelly vs sistema precedente, su 4 dimensioni di blocco diverse | CAGR: non significativo su NESSUna delle 4 scelte di block_size; Sharpe: significativo su TUTTE — conclusione stabile, non un artefatto metodologico | "Addendum — Kelly frazionario vs sistema precedente" |
| 7 | `fetch_delisted_sp500_prices.py` | Il fix del survivorship bias stesso — quanti titoli storici mancavano e quanti sono stati recuperati | Copertura storica 60,9% → 77,8% (non 100%: alcuni titoli delistati troppo vecchi non sono più serviti da Yahoo) | "Scoperta più grave: survivorship bias..." |

Per QUALUNQUE altro script in `comparative_studies/` (75 in totale): ogni
file ha una docstring di apertura che spiega la domanda, il metodo, e i
limiti dichiarati — e ogni risultato rilevante è narrato in
`README.md`, sezione "Storia delle scoperte rilevanti" (in ordine
cronologico) o nelle sezioni tematiche più recenti in fondo al file.

## 6. Convenzioni da conoscere prima di revisionare il codice

- **No-lookahead discipline**: qualunque decisione (basket, gate di trend,
  peso) calcolata con dati fino alla settimana/mese T si applica al
  rendimento di T+1, MAI a quello di T stesso — pattern `shift(1)` o
  riordino esplicito "prima il rendimento, poi la decisione". Una fuga
  same-bar è stata trovata e corretta 3 volte in questa sessione
  (`kelly_backtest.py`, il ribasket trimestrale di Apex, e va sempre
  cercata in ogni nuovo script che decide-poi-guadagna nello stesso ciclo.
- **Tassazione italiana** (`tax_engine.apply_italian_tax`): aliquota
  flat 26%; `REDDITO_CAPITALE` (ETF/fondi) non compensa minusvalenze,
  `REDDITO_DIVERSO` (titoli/ETC/ETP/crypto) sì, con pool di minusvalenze
  condiviso. Nessun limite FIFO a 4 anni modellato (dichiarato,
  verificato irrilevante su orizzonti di questa lunghezza). NAV e valore
  nozionale delle posizioni SEMPRE tenuti separati (con leva, sommarli è
  un bug reale già trovato e corretto — vedi commenti in
  `tax_engine.py`).
- **PBO-CSCV / Deflated Sharpe Ratio / block bootstrap** (`statistical_validation.py`):
  il framework anti-overfitting usato per validare (o falsificare) ogni
  candidato. PBO vicino al 50% = rumore; vicino a 0% = segnale robusto tra
  i fold. Un block bootstrap ripetuto su PIÙ dimensioni di blocco (non una
  sola) è la barra minima per dire che una conclusione statistica non è
  un artefatto del parametro scelto — vedi punto 6 della tabella sopra
  per un esempio diretto.
- **Nessuna leva, nessuno short in produzione**: vincolo di design
  esplicito di Apex/Convex, non un limite tecnico. Un candidato che
  richiede l'uno o l'altro per funzionare (vedi BAB, punto 3 sopra) va
  quantificato PRIMA di essere scartato o adottato, non deciso a priori —
  ma quantificato finora ha sempre perso.

## 7. Come segnalare una discrepanza

Se un numero riprodotto non coincide con quanto scritto in `README.md`
oltre la tolleranza attesa per un fetch di dati fresco (punto 4 sopra):
1. Verifica prima che la versione del codice sia la stessa (`git log -1`
   sullo script in questione, confronta con il commit citato se
   disponibile).
2. Controlla se la cache dati usata è quella tracciata in git o una
   rigenerata da zero (un fetch fresco da Yahoo può differire).
3. Se la discrepanza persiste, è un finding reale — documentalo con lo
   stesso standard di rigore già in uso in questo repository: numero
   preciso, script/riga, ipotesi sulla causa. Non c'è un processo
   automatico di segnalazione: è per uso umano o del prossimo agente che
   riprende in mano questa sessione.
