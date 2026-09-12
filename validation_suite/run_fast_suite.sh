#!/usr/bin/env bash
# run_fast_suite.sh — comando unico per la parte veloce/deterministica della
# validation suite (framework/ + kelly_stack/ + core_regression/, tutta via
# pytest, incl. le suite unittest — pytest le raccoglie senza bisogno di
# `python -m unittest`). Non lancia comparative_studies/ (lento, dipende
# dalla rete, va eseguito a mano quando serve rispondere a una domanda
# specifica — vedi validation_suite/README.md).
#
# Uso: ./validation_suite/run_fast_suite.sh   (dalla root del repo, o da ovunque)
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

if [ -f "$REPO_ROOT/.venv/bin/python" ]; then
    PYTHON="$REPO_ROOT/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON="python3"
else
    PYTHON="python"
fi

PYTHONPATH=. "$PYTHON" -m pytest validation_suite/ -v
