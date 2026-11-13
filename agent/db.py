"""Conexões com o SQLite. Todo o SQL do agente (repositório) fica neste módulo.

Duas conexões, de propósito:
- `connect_rw()`: escrita (ingest, histórico, auditoria). O agente não a alcança.
- `connect_ro()`: somente leitura, a única que as tools usam. Nunca dispara ingest:
  os CSVs são lidos só no startup (ver `ingest.startup()`).

`DATA_DIR` e `DB_PATH` vêm do env e são lidos a cada chamada, para os testes poderem trocá-los.
"""

import os
import sqlite3
import unicodedata
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


def normalize(text: str) -> str:
    """Minúsculas e sem acento: a forma em que `search_text` e `product_specs` são gravados."""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return stripped.lower().encode("ascii", "ignore").decode("ascii")


# ---------- repositório de produtos (só leitura) ----------
# SQL fixo e parametrizado: valores sempre como parâmetros nomeados, nunca por concatenação.
# O que se monta dinamicamente são fragmentos escritos aqui, com nomes de parâmetro gerados.

_PRODUCT_SELECT = """
SELECT p.product_id, p.name, p.description, p.price_brl, p.stock_quantity, p.status, p.specs,
       p.category_id, c.name AS category,
       (SELECT MAX(discount_percent) FROM promotions
         WHERE product_id = p.product_id AND is_active = 1) AS discount_percent,
       (SELECT description FROM promotions
         WHERE product_id = p.product_id AND is_active = 1
         ORDER BY discount_percent DESC, promotion_id LIMIT 1) AS promotion_description
  FROM products p JOIN categories c ON c.category_id = p.category_id
"""


def _rows(cursor: sqlite3.Cursor) -> list[dict]:
    names = [d[0] for d in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def _like_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _product_filters(
    query: str | None,
    category_id: int | None,
    specs: dict[str, str] | None,
    min_price: float | None,
    max_price: float | None,
    only_available: bool,
) -> tuple[str, dict]:
    """WHERE parametrizado. `query` e `specs` já vêm normalizados (ver `normalize`)."""
    where, params = [], {}
    for i, term in enumerate((query or "").split()):
        where.append(f"p.search_text LIKE :term{i} ESCAPE '\\'")
        params[f"term{i}"] = f"%{_like_escape(term)}%"
    if category_id is not None:
        where.append("p.category_id = :category_id")
        params["category_id"] = category_id
    for i, (key, value) in enumerate((specs or {}).items()):
        where.append(
            f"EXISTS (SELECT 1 FROM product_specs s WHERE s.product_id = p.product_id "
            f"AND s.key = :spec_key{i} AND s.value = :spec_value{i})"
        )
        params[f"spec_key{i}"], params[f"spec_value{i}"] = key, value
    if min_price is not None:
        where.append("p.price_brl >= :min_price")
        params["min_price"] = min_price
    if max_price is not None:
        where.append("p.price_brl <= :max_price")
        params["max_price"] = max_price
    if only_available:
        where.append("p.status = 'active' AND p.stock_quantity > 0")
    return (" WHERE " + " AND ".join(where)) if where else "", params


def find_products(conn, *, query=None, category_id=None, specs=None, min_price=None,
                  max_price=None, only_available=True, limit=10) -> list[dict]:
    where, params = _product_filters(query, category_id, specs, min_price, max_price, only_available)
    sql = _PRODUCT_SELECT + where + " ORDER BY p.price_brl, p.product_id LIMIT :limit"
    return _rows(conn.execute(sql, {**params, "limit": limit}))


def count_products(conn, *, query=None, category_id=None, specs=None, min_price=None,
                   max_price=None, only_available=True) -> int:
    where, params = _product_filters(query, category_id, specs, min_price, max_price, only_available)
    sql = "SELECT COUNT(*) FROM products p" + where
    return conn.execute(sql, params).fetchone()[0]


def get_product(conn, product_id: int) -> dict | None:
    rows = _rows(conn.execute(_PRODUCT_SELECT + " WHERE p.product_id = :product_id", {"product_id": product_id}))
    return rows[0] if rows else None


def find_alternatives(conn, product: dict, limit: int = 3) -> list[dict]:
    """Mesma categoria, disponíveis, os de preço mais próximo do produto."""
    sql = (
        _PRODUCT_SELECT
        + " WHERE p.category_id = :category_id AND p.product_id != :product_id"
        " AND p.status = 'active' AND p.stock_quantity > 0"
        " ORDER BY ABS(p.price_brl - :price), p.product_id LIMIT :limit"
    )
    params = {"category_id": product["category_id"], "product_id": product["product_id"],
              "price": product["price_brl"], "limit": limit}
    return _rows(conn.execute(sql, params))


def get_categories(conn) -> list[dict]:
    """Todas as categorias, com a contagem de produtos ativos (zero incluído)."""
    return _rows(conn.execute(
        "SELECT c.category_id, c.name, COUNT(p.product_id) AS product_count "
        "FROM categories c LEFT JOIN products p ON p.category_id = c.category_id AND p.status = 'active' "
        "GROUP BY c.category_id, c.name ORDER BY c.category_id"
    ))


def spec_options(conn, category_id: int | None = None) -> dict[str, set[str]]:
    """Chaves e valores de specs que existem nos dados (da categoria, se informada)."""
    cursor = conn.execute(
        "SELECT DISTINCT s.key, s.value FROM product_specs s JOIN products p ON p.product_id = s.product_id "
        "WHERE :category_id IS NULL OR p.category_id = :category_id",
        {"category_id": category_id},
    )
    options: dict[str, set[str]] = {}
    for key, value in cursor:
        options.setdefault(key, set()).add(value)
    return options
