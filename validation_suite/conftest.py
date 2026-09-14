"""
conftest.py — Configurazione e fixture centralizzate per l'intera suite di validazione.
====================================================================================
Garantisce:
1. Risoluzione dei percorsi di modulo (root del repository e validation_suite/framework/)
   in modo trasparente, eliminando la necessità di configurazioni PYTHONPATH manuali.
2. Fixture robuste, performanti (session-scoped) e portabili per tutti i dataset point-in-time,
   i dataset macroeconomici estesi, i registri storici e le configurazioni di produzione.
3. Assenza di percorsi assoluti hardcoded in tutta la suite di test.
====================================================================================
"""

from __future__ import annotations
import json
import sys
from pathlib import Path
from typing import Any, Dict, List
import pytest

# Registrazione percorsi di import
_REPO_ROOT = Path(__file__).resolve().parent.parent
_FRAMEWORK_DIR = Path(__file__).resolve().parent / "framework"

if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if str(_FRAMEWORK_DIR) not in sys.path:
    sys.path.insert(0, str(_FRAMEWORK_DIR))


# ==============================================================================
# PERCORSI DEL REPOSITORY E DEI DATASET (SESSION SCOPE)
# ==============================================================================

@pytest.fixture(scope="session")
def repo_root() -> Path:
    """Restituisce il percorso radice del repository come oggetto Path."""
    return _REPO_ROOT


@pytest.fixture(scope="session")
def pointintime_dir(repo_root: Path) -> Path:
    """Restituisce la cartella dei dataset point-in-time."""
    return repo_root / "validation_suite" / "pointintime_data"


@pytest.fixture(scope="session")
def macro_data_dir(repo_root: Path) -> Path:
    """Restituisce la cartella delle serie storiche macroeconomiche estese."""
    return repo_root / "validation_suite" / "comparative_studies" / "apex_macro_extended_data"


@pytest.fixture(scope="session")
def historical_trades_json_path(repo_root: Path) -> Path:
    """Restituisce il percorso del registro storico completo in formato JSON."""
    return repo_root / "apex_full_historical_trades.json"


@pytest.fixture(scope="session")
def historical_trades_csv_path(repo_root: Path) -> Path:
    """Restituisce il percorso del registro storico completo in formato CSV."""
    return repo_root / "apex_full_historical_trades.csv"


# ==============================================================================
# CARICAMENTO DATI PERSISTITI (SESSION SCOPE, CACHED)
# ==============================================================================

@pytest.fixture(scope="session")
def delisted_proxy_map(pointintime_dir: Path) -> Dict[str, Any]:
    """Carica la mappa point-in-time dei 195 proxy per i titoli delistati/acquisiti."""
    file_path = pointintime_dir / "delisted_proxy_map.json"
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="session")
def sp500_pit_snapshots(pointintime_dir: Path) -> Dict[str, List[str]]:
    """Carica gli snapshot point-in-time trimestrali dei costituenti reali dell'S&P 500."""
    file_path = pointintime_dir / "sp500_pointintime_snapshots.json"
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="session")
def cmc_altcoin_pit_snapshots(pointintime_dir: Path) -> Dict[str, List[str]]:
    """Carica gli snapshot point-in-time trimestrali del ranking reale altcoin CoinMarketCap."""
    file_path = pointintime_dir / "cmc_altcoin_pointintime_snapshots.json"
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="session")
def full_historical_trades(historical_trades_json_path: Path) -> List[Dict[str, Any]]:
    """Carica l'archivio storico certificato dei trade eseguiti (1987-Oggi)."""
    with open(historical_trades_json_path, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="session")
def live_prices_cache(repo_root: Path) -> Dict[str, Any]:
    """Carica la cache dei prezzi live Convex e benchmark SPY."""
    cache_path = repo_root / "live_prices_cache.json"
    if cache_path.exists():
        with open(cache_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


@pytest.fixture(scope="session")
def app_config() -> Dict[str, Any]:
    """Carica la configurazione applicativa persistita o i default istituzionali."""
    import portfolio_manager
    return portfolio_manager.load_config()


@pytest.fixture(scope="session")
def convex_metadata() -> Dict[str, Any]:
    """Restituisce i metadati ufficiali dei 5 strumenti UCITS di Convex Stack."""
    import portfolio_manager
    return portfolio_manager.CONVEX_INSTRUMENTS_METADATA
