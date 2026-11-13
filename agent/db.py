"""Conexões com o SQLite. Todo o SQL do agente (repositório) fica neste módulo.

Duas conexões, de propósito:
- `connect_rw()`: escrita (ingest, histórico, auditoria). O agente não a alcança.
- `connect_ro()`: somente leitura, a única que as tools usam. Nunca dispara ingest:
  os CSVs são lidos só no startup (ver `ingest.startup()`).

`DATA_DIR` e `DB_PATH` vêm do env e são lidos a cada chamada, para os testes poderem trocá-los.
"""

import os
import sqlite3
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def data_dir() -> Path:
    return Path(os.environ.get("DATA_DIR") or REPO_ROOT / "data")


def db_path() -> Path:
    return Path(os.environ.get("DB_PATH") or REPO_ROOT / "data" / "store.db")


def connect_rw() -> sqlite3.Connection:
    return sqlite3.connect(db_path())


def connect_ro() -> sqlite3.Connection:
    return sqlite3.connect(f"{db_path().resolve().as_uri()}?mode=ro", uri=True)
