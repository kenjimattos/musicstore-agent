"""Fixtures do e2e.

Depende da fixture `store` de `tests/conftest.py` (commit 3): cópia temporária de
`data/` com DATA_DIR, DB_PATH e REFERENCE_DATE apontando para ela. `store` não
pode importar os CSVs antes do teste, porque aqui acrescentamos pedidos a eles.
"""

import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

from tests.e2e.scenarios import EXTRA_ORDER_ITEMS, EXTRA_ORDERS


def _append_rows(path: Path, rows: list[str]) -> None:
    text = path.read_text(encoding="utf-8")
    if not text.endswith("\n"):  # os CSVs originais não terminam com quebra de linha
        text += "\n"
    path.write_text(text + "\n".join(rows) + "\n", encoding="utf-8")


@pytest.fixture
def e2e_store(store):
    """`store` com os pedidos extras, só na cópia temporária (data/ fica intacto)."""
    load_dotenv()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY ausente: os testes e2e chamam a API")
    _append_rows(store.data_dir / "orders.csv", EXTRA_ORDERS)
    _append_rows(store.data_dir / "order_items.csv", EXTRA_ORDER_ITEMS)
    return store
