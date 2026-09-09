"""
conftest.py — permette a `pytest validation_suite/` (o a un sotto-percorso) di
trovare due categorie di moduli senza dover editare l'import di ogni singolo
file di test:
1. I moduli di produzione alla radice del repo (backend, apex_v2_engine,
   convex_engine, portfolio_manager, ...) da cui core_regression/ dipende.
   In CI (ci.yml) lo stesso risultato e' garantito anche da PYTHONPATH=. —
   questo conftest serve soprattutto per l'uso locale via pytest.
2. validation_suite/framework/ (metrics, tax_engine, statistical_validation)
   da cui QUALSIASI file di test in questa cartella (non solo kelly_stack/,
   dove framework/ e' nato) puo' voler importare — es.
   core_regression/test_apex_v2_institutional_validation.py. Gli script
   standalone in comparative_studies/ (eseguiti direttamente con `python`,
   non via pytest) fanno il proprio sys.path.insert perche' questo conftest
   non si applica fuori da pytest.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / "framework"))
