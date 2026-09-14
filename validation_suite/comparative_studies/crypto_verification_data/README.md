# Crypto verification data — cosa e' e cosa NON e'

40 serie OHLCV giornaliere (Yahoo Finance, `fetch_yahoo_history` — la stessa funzione
usata in produzione da `backend.py`), fetchate il 2026-09-14 con `period="10y"`.
Copertura: dal listing su Yahoo di ciascun token (da 2016-09 per BTC/LTC a 2024-04
per ENA) fino al 2026-09-14.

Rigenerabile con `fetch_crypto_verification_cache.py` in questa stessa cartella.

## A cosa serve

Costruita per colmare, ai fini di verifica quantitativa indipendente, l'assenza in
repo di `research/crypto_ohlcv_extended_cache/` (mai committata da chi ha introdotto
`crypto_frontier_venture_engine.py` — vedi commit `e0451ad`). Permette di eseguire
`run_crypto_venture_backtest` su dati di mercato reali, non sintetici, per misurare
l'impatto reale dei 3 bug corretti nel commit `a12382b` e ottenere una lettura
corrente (seppur parziale) delle performance del motore.

## Limite metodologico esplicito — NON e' il dataset "118 asset, survivorship-bias-free"

Questo e' un **universo statico**: i 40 token piu' grandi e longevi **ancora
quotati oggi**, con tutta la loro storia disponibile. Non replica la metodologia
punto-nel-tempo descritta in `CRYPTO_VENTURE_SPEC.md` (118 asset, universo
trimestrale ricostruito da `cmc_altcoin_pointintime_snapshots.json`): i token
delistati/morti (es. LUNA, FTT) sono semplicemente assenti, perche' Yahoo Finance
non ne conserva il ticker. Questo introduce un survivorship bias residuo di segno
opposto a quello che la metodologia point-in-time del progetto punta a eliminare.

Le uscite meccaniche del motore (stop ATR, circuit breaker -50%, time-stop) mitigano
parzialmente il problema quando un token e' incluso e poi crolla, ma non compensano
l'assenza totale dei token che sono usciti di scena. I numeri ottenuti da questo
dataset vanno quindi letti come una verifica di impatto/regressione (bug-fix
before/after, ordine di grandezza delle metriche), non come una riproduzione
autorevole delle cifre di `CRYPTO_VENTURE_SPEC.md`.

Per una verifica piena serve ancora la cache reale usata per produrre
`apex_full_historical_trades.json`/`kelly_and_monte_carlo_results.json` (crypto
sleeve) — cache che, alla data di questo audit, non risulta recuperabile da questo
repository.
