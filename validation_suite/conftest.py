"""
conftest.py — permette a `pytest validation_suite/` (o a un sotto-percorso)
di trovare i moduli di produzione alla radice del repo (backend, apex_v2_engine,
convex_engine, portfolio_manager, ...) da cui core_regression/ dipende, senza
dover editare l'import di ogni singolo file di test. In CI (ci.yml) lo stesso
risultato e' garantito da PYTHONPATH=. — questo conftest serve per l'uso
locale via pytest.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
