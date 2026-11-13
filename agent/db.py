"""Conexões com o SQLite. Todo o SQL do agente (repositório) fica neste módulo.

Duas conexões, de propósito:
- `connect_rw()`: escrita (ingest, histórico, auditoria). O agente não a alcança.
- `connect_ro()`: somente leitura, a única que as tools usam. Nunca dispara ingest:
  os CSVs são lidos só no startup (ver `ingest.startup()`).

`DATA_DIR` e `DB_PATH` vêm do env e são lidos a cada chamada, para os testes poderem trocá-los.
"""

import json
import os
import sqlite3
import unicodedata
from datetime import datetime, timezone
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


def get_product_names(conn) -> list[str]:
    """Nome de todo produto do catálogo (qualquer status), para o output_guard reconhecer menções."""
    return [r[0] for r in conn.execute("SELECT name FROM products")]


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


# ---------- repositório de clientes e pedidos (só leitura) ----------

_OPEN_STATUSES = "'pending', 'confirmed', 'shipped'"
_ORDER_SELECT = """
SELECT o.order_id, o.customer_id, o.order_date, o.status, o.total_brl, o.payment_method,
       o.tracking_code, o.estimated_delivery, o.notes, c.city
  FROM orders o JOIN customers c ON c.customer_id = o.customer_id
"""


def find_customer_by_phone(conn, digits: str) -> dict | None:
    """Compara só os dígitos: o telefone da base vem formatado, '(67) 99654-7821'."""
    rows = _rows(conn.execute(
        "SELECT customer_id, name FROM customers WHERE "
        "replace(replace(replace(replace(replace(phone, ' ', ''), '(', ''), ')', ''), '-', ''), '+', '') = :digits "
        "ORDER BY customer_id LIMIT 1",
        {"digits": digits},
    ))
    return rows[0] if rows else None


def get_order_owner_contact(conn, order_id: int) -> dict | None:
    """E-mail e telefone do dono do pedido. Só para conferir a identidade do visitante; nunca sai da tool."""
    rows = _rows(conn.execute(
        "SELECT c.email, c.phone FROM orders o JOIN customers c ON c.customer_id = o.customer_id "
        "WHERE o.order_id = :order_id",
        {"order_id": order_id},
    ))
    return rows[0] if rows else None


def get_order(conn, order_id: int, customer_id: int | None = None) -> dict | None:
    """Um pedido; com `customer_id`, só se for dele."""
    rows = _rows(conn.execute(
        _ORDER_SELECT + " WHERE o.order_id = :order_id AND (:customer_id IS NULL OR o.customer_id = :customer_id)",
        {"order_id": order_id, "customer_id": customer_id},
    ))
    return rows[0] if rows else None


def ranked_orders(conn, customer_id: int, recent_cutoff: str, limit: int = 6) -> list[dict]:
    """Pedidos do cliente por relevância: em aberto > entregue desde `recent_cutoff` > o resto.

    Dentro de cada grupo, do mais recente para o mais antigo.
    """
    sql = (
        _ORDER_SELECT
        + " WHERE o.customer_id = :customer_id ORDER BY CASE"
        f" WHEN o.status IN ({_OPEN_STATUSES}) THEN 0"
        " WHEN o.status = 'delivered' AND o.estimated_delivery >= :cutoff THEN 1"
        " ELSE 2 END, o.order_date DESC, o.order_id DESC LIMIT :limit"
    )
    return _rows(conn.execute(sql, {"customer_id": customer_id, "cutoff": recent_cutoff, "limit": limit}))


def count_orders(conn, customer_id: int) -> int:
    return conn.execute("SELECT COUNT(*) FROM orders WHERE customer_id = :c", {"c": customer_id}).fetchone()[0]


def get_order_items(conn, order_id: int) -> list[dict]:
    return _rows(conn.execute(
        "SELECT i.product_id, p.name, i.quantity FROM order_items i "
        "JOIN products p ON p.product_id = i.product_id WHERE i.order_id = :order_id ORDER BY i.product_id",
        {"order_id": order_id},
    ))


# ---------- escritas restritas (simulação de exclusão de dados e encaminhamento) ----------
# Únicas escritas que o agente alcança, e só `INSERT` em tabelas próprias: nenhuma altera
# customers, orders, order_items, products nem promotions. Ficam fora das 6 tabelas dos CSVs,
# então um novo ingest nunca as apaga (ver `create_request_tables`, chamado pelo ingest).

_REQUEST_TABLES = (
    "CREATE TABLE IF NOT EXISTS data_requests ("
    "request_id INTEGER PRIMARY KEY AUTOINCREMENT, customer_id INTEGER NOT NULL, thread_id TEXT, "
    "requested_at TEXT NOT NULL, status TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS support_tickets ("
    "ticket_id INTEGER PRIMARY KEY AUTOINCREMENT, customer_id INTEGER, phone TEXT, order_id INTEGER, "
    "reason TEXT NOT NULL, summary TEXT NOT NULL, thread_id TEXT, created_at TEXT NOT NULL, status TEXT NOT NULL)",
)


def create_request_tables(conn) -> None:
    for ddl in _REQUEST_TABLES:
        conn.execute(ddl)


def insert_data_request(customer_id: int, thread_id: str | None, requested_at: str) -> tuple[int, bool]:
    """Registra o pedido de exclusão. Devolve (request_id, já_existia): idempotente por cliente."""
    conn = connect_rw()
    try:
        conn.execute("BEGIN IMMEDIATE")
        create_request_tables(conn)
        row = conn.execute(
            "SELECT request_id FROM data_requests WHERE customer_id = :customer_id AND status = 'pending' "
            "ORDER BY request_id LIMIT 1",
            {"customer_id": customer_id},
        ).fetchone()
        if row:
            conn.commit()
            return row[0], True
        cursor = conn.execute(
            "INSERT INTO data_requests (customer_id, thread_id, requested_at, status) "
            "VALUES (:customer_id, :thread_id, :requested_at, 'pending')",
            {"customer_id": customer_id, "thread_id": thread_id, "requested_at": requested_at},
        )
        conn.commit()
        return cursor.lastrowid, False
    finally:
        conn.close()


def insert_ticket(*, customer_id: int | None, phone: str | None, order_id: int | None, reason: str,
                  summary: str, thread_id: str | None, created_at: str) -> tuple[int, bool]:
    """Abre o chamado. Devolve (ticket_id, já_existia): idempotente por (cliente ou telefone, pedido, motivo)."""
    params = {"customer_id": customer_id, "phone": phone, "order_id": order_id, "reason": reason,
              "summary": summary, "thread_id": thread_id, "created_at": created_at}
    conn = connect_rw()
    try:
        conn.execute("BEGIN IMMEDIATE")
        create_request_tables(conn)
        row = conn.execute(
            "SELECT ticket_id FROM support_tickets WHERE status = 'open' AND customer_id IS :customer_id "
            "AND phone IS :phone AND order_id IS :order_id AND reason = :reason ORDER BY ticket_id LIMIT 1",
            params,
        ).fetchone()
        if row:
            conn.commit()
            return row[0], True
        cursor = conn.execute(
            "INSERT INTO support_tickets (customer_id, phone, order_id, reason, summary, thread_id, created_at, status) "
            "VALUES (:customer_id, :phone, :order_id, :reason, :summary, :thread_id, :created_at, 'open')",
            params,
        )
        conn.commit()
        return cursor.lastrowid, False
    finally:
        conn.close()


# ---------- histórico da conversa ----------
# Tabela fora das 6 dos CSVs: um novo ingest nunca a apaga. Guarda tudo, inclusive tool_use/tool_result;
# o que vai ao modelo é uma visão montada por `agent.agent.build_history`.

_MESSAGES_TABLE = (
    "CREATE TABLE IF NOT EXISTS messages ("
    "id INTEGER PRIMARY KEY AUTOINCREMENT, thread_id TEXT NOT NULL, role TEXT NOT NULL, "
    "content TEXT NOT NULL, created_at TEXT NOT NULL)"
)
_MESSAGES_INDEX = "CREATE INDEX IF NOT EXISTS idx_messages_thread ON messages (thread_id, id)"


def create_messages_table(conn) -> None:
    conn.execute(_MESSAGES_TABLE)
    conn.execute(_MESSAGES_INDEX)


def save_message(thread_id: str, role: str, content, created_at: str | None = None) -> None:
    """Grava uma mensagem. `content` é str ou lista de blocos da API, gravado como JSON."""
    created_at = created_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn = connect_rw()
    try:
        create_messages_table(conn)
        conn.execute(
            "INSERT INTO messages (thread_id, role, content, created_at) VALUES (:thread_id, :role, :content, :created_at)",
            {"thread_id": thread_id, "role": role, "content": json.dumps(content, ensure_ascii=False),
             "created_at": created_at},
        )
        conn.commit()
    finally:
        conn.close()


def load_messages(thread_id: str) -> list[dict]:
    """Mensagens da thread na ordem em que foram gravadas."""
    conn = connect_rw()
    try:
        create_messages_table(conn)
        rows = conn.execute(
            "SELECT role, content FROM messages WHERE thread_id = :thread_id ORDER BY id", {"thread_id": thread_id}
        ).fetchall()
    finally:
        conn.close()
    return [{"role": role, "content": json.loads(content)} for role, content in rows]
