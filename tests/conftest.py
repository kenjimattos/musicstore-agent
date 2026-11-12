"""Fixtures compartilhadas. Nenhum teste escreve em `data/`: tudo roda sobre uma cópia."""

import shutil
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO_DATA = Path(__file__).resolve().parent.parent / "data"


@dataclass
class Store:
    data_dir: Path  # cópia temporária dos CSVs e do PDF (a loja substituiria estes arquivos)
    db_path: Path  # SQLite temporário; ainda não existe até a primeira ingestão


@pytest.fixture
def store(tmp_path, monkeypatch) -> Store:
    """Cópia de `data/` em tmp, com DATA_DIR, DB_PATH e REFERENCE_DATE apontando para ela.

    Não ingere nada: quem precisa do banco chama `ingest` (ou `db.connect_ro`), e o e2e
    ainda acrescenta pedidos aos CSVs antes disso.
    """
    data_dir = tmp_path / "data"
    shutil.copytree(REPO_DATA, data_dir, ignore=shutil.ignore_patterns("*.db", "*.db-*"))
    db_path = tmp_path / "store.db"
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("DB_PATH", str(db_path))
    monkeypatch.setenv("REFERENCE_DATE", "2026-03-25")
    return Store(data_dir=data_dir, db_path=db_path)
