"""Ingestão dos CSVs da loja no SQLite. Sem LLM.

É um adaptador de protótipo: em produção, este módulo seria substituído pela leitura do
sistema da loja (ERP/e-commerce). O que sobrevive é a interface de `db.py`.

Regras:
- roda só no startup (`startup()`); consultar o banco nunca reingere;
- por CSV, compara o mtime com o da última importação (`ingest_meta`): mais novo reingere,
  igual não faz nada, mais antigo é erro (a loja sempre cola um export novo);
- valida tudo em memória antes de escrever; a gravação das 6 tabelas (mais `product_specs`,
  derivada de `products.specs`) é uma única transação,
  então um CSV ruim nunca deixa o banco pela metade;
- só as tabelas dos CSVs (e `ingest_meta`) são recriadas: `messages`, `audit_log`,
  `data_requests` e `support_tickets` nunca são tocadas.
"""

import csv
import json
import logging
import math
import sqlite3
from pathlib import Path

from agent import db

log = logging.getLogger(__name__)


class IngestError(ValueError):
    """CSV ausente, coluna faltando, valor inválido, chave duplicada ou arquivo mais antigo."""


# Coluna: (nome, tipo, obrigatória). Tipos: int, real, text.
# `key` é a chave primária; `computed` são colunas derivadas, preenchidas aqui.
TABLES = {
    "categories": {
        "csv": "categories.csv",
        "key": ("category_id",),
        "columns": [("category_id", "int", True), ("name", "text", True), ("description", "text", False)],
    },
    "customers": {
        "csv": "customers.csv",
        "key": ("customer_id",),
        "columns": [
            ("customer_id", "int", True),
            ("name", "text", True),
            ("phone", "text", True),
            ("email", "text", False),
            ("city", "text", False),
        ],
        "indexes": [("customers_phone", "phone")],
    },
    "products": {
        "csv": "products.csv",
        "key": ("product_id",),
        "columns": [
            ("product_id", "int", True),
            ("price_brl", "real", True),
            ("name", "text", True),
            ("category_id", "int", True),
            ("description", "text", False),
            ("stock_quantity", "int", True),
            ("status", "text", True),
            ("specs", "text", False),
            ("created_at", "text", False),
        ],
        "computed": [("search_text", "text")],
        "indexes": [("products_category", "category_id")],
    },
    "orders": {
        "csv": "orders.csv",
        "key": ("order_id",),
        "columns": [
            ("order_id", "int", True),
            ("customer_id", "int", True),
            ("order_date", "text", True),
            ("status", "text", True),
            ("total_brl", "real", True),
            ("payment_method", "text", False),
            ("tracking_code", "text", False),
            ("estimated_delivery", "text", False),
            ("notes", "text", False),
        ],
        "indexes": [("orders_customer_date", "customer_id, order_date")],
    },
    "order_items": {
        "csv": "order_items.csv",
        "key": ("order_id", "product_id"),
        "columns": [("order_id", "int", True), ("quantity", "int", True), ("product_id", "int", True)],
    },
    "promotions": {
        "csv": "promotions.csv",
        "key": ("promotion_id",),
        "columns": [
            ("promotion_id", "int", True),
            ("product_id", "int", True),
            ("discount_percent", "real", True),
            ("description", "text", False),
            ("is_active", "int", True),
        ],
        "indexes": [("promotions_product", "product_id")],
    },
}

SQL_TYPES = {"int": "INTEGER", "real": "REAL", "text": "TEXT"}


# ---------- localizar e ler os CSVs ----------


def find_csvs() -> dict[str, Path]:
    """Acha cada CSV pelo sufixo (`*products.csv`), então o nome do export do Sheets também serve."""
    folder = db.data_dir()
    found = {}
    for table, spec in TABLES.items():
        exact = folder / spec["csv"]
        if exact.is_file():
            found[table] = exact
            continue
        matches = sorted(p for p in folder.glob(f"*{spec['csv']}") if p.is_file())
        if not matches:
            raise IngestError(f"{spec['csv']}: arquivo não encontrado em {folder}")
        if len(matches) > 1:
            names = ", ".join(p.name for p in matches)
            raise IngestError(f"{spec['csv']}: mais de um arquivo candidato ({names})")
        found[table] = matches[0]
    return found


def _to_int(text: str):
    try:
        return int(text)
    except ValueError:
        number = float(text)  # aceita "12.0" de um export de planilha
        if not number.is_integer():
            raise
        return int(number)


def _to_real(text: str):
    number = float(text)
    if not math.isfinite(number):
        raise ValueError(text)
    return number


_normalize = db.normalize  # a mesma forma normalizada que a busca usa


def _spec_rows(products: list[tuple], path_name: str) -> list[tuple]:
    """Explode o JSON de `products.specs` em (product_id, key, value), sem acento e em minúsculas.

    As chaves variam por categoria, então chave/valor guarda tudo sem colunas vazias e sem
    funções de JSON do SQLite. JSON inválido é erro, não silêncio.
    """
    names = [n for n, *_ in TABLES["products"]["columns"]]
    id_at, specs_at = names.index("product_id"), names.index("specs")
    rows = []
    for product in products:
        raw = product[specs_at]
        if raw is None:
            continue
        try:
            pairs = json.loads(raw)
            if not isinstance(pairs, dict):
                raise ValueError("não é um objeto")
        except ValueError as exc:
            raise IngestError(
                f"{path_name}, coluna specs, produto {product[id_at]}: JSON inválido ({exc})"
            ) from None
        rows += [(product[id_at], _normalize(str(k)), _normalize(str(v))) for k, v in pairs.items()]
    return rows


def _load(table: str, path: Path) -> list[tuple]:
    """Lê, valida e limpa um CSV. Devolve as linhas já na ordem das colunas da tabela."""
    spec = TABLES[table]
    columns = spec["columns"]
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        header = [h.strip() for h in (reader.fieldnames or [])]
        missing = [name for name, _, _ in columns if name not in header]
        if missing:
            raise IngestError(f"{path.name}: coluna obrigatória ausente: {', '.join(missing)}")
        reader.fieldnames = header
        rows, seen = [], set()
        for line, raw in enumerate(reader, start=2):
            values = {}
            for name, kind, required in columns:
                text = (raw.get(name) or "").strip()
                if not text:
                    if required:
                        raise IngestError(f"{path.name}, linha {line}, coluna {name}: valor vazio")
                    values[name] = None
                    continue
                if kind == "text":
                    values[name] = text.lower() if name == "email" else text
                    continue
                try:
                    values[name] = _to_int(text) if kind == "int" else _to_real(text)
                except ValueError:
                    raise IngestError(
                        f"{path.name}, linha {line}, coluna {name}: valor '{text}' não é número"
                    ) from None
            key = tuple(values[k] for k in spec["key"])
            if key in seen:
                raise IngestError(
                    f"{path.name}, linha {line}: chave {', '.join(spec['key'])} duplicada ({', '.join(map(str, key))})"
                )
            seen.add(key)
            if table == "products":
                values["search_text"] = _normalize(f"{values['name']} {values['description'] or ''}")
            rows.append(tuple(values[name] for name, *_ in columns) + tuple(
                values[name] for name, _ in spec.get("computed", [])
            ))
    return rows


# ---------- gravar ----------


def _create_sql(table: str) -> str:
    spec = TABLES[table]
    cols = [f"{name} {SQL_TYPES[kind]}{' NOT NULL' if required else ''}" for name, kind, required in spec["columns"]]
    cols += [f"{name} {SQL_TYPES[kind]}" for name, kind in spec.get("computed", [])]
    cols.append(f"PRIMARY KEY ({', '.join(spec['key'])})")
    return f"CREATE TABLE {table} ({', '.join(cols)})"


def _write(
    conn: sqlite3.Connection,
    loaded: dict[str, list[tuple]],
    specs: list[tuple],
    mtimes: dict[str, int],
) -> None:
    for table, rows in loaded.items():
        spec = TABLES[table]
        names = [n for n, *_ in spec["columns"]] + [n for n, _ in spec.get("computed", [])]
        conn.execute(f"DROP TABLE IF EXISTS {table}")
        conn.execute(_create_sql(table))
        conn.executemany(
            f"INSERT INTO {table} ({', '.join(names)}) VALUES ({', '.join(':' + n for n in names)})",
            [dict(zip(names, row)) for row in rows],
        )
        for index, columns in spec.get("indexes", []):
            conn.execute(f"CREATE INDEX {index} ON {table} ({columns})")
    conn.execute("DROP TABLE IF EXISTS product_specs")
    conn.execute(
        "CREATE TABLE product_specs (product_id INTEGER NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL, "
        "PRIMARY KEY (product_id, key))"
    )
    conn.executemany("INSERT INTO product_specs (product_id, key, value) VALUES (?, ?, ?)", specs)
    conn.execute("CREATE INDEX product_specs_key_value ON product_specs (key, value)")
    db.create_request_tables(conn)  # data_requests e support_tickets: criadas se faltarem, nunca recriadas
    db.create_audit_table(conn)  # idem para o audit_log
    conn.execute("DROP TABLE IF EXISTS ingest_meta")
    conn.execute("CREATE TABLE ingest_meta (table_name TEXT PRIMARY KEY, mtime_ns INTEGER NOT NULL)")
    conn.executemany(
        "INSERT INTO ingest_meta (table_name, mtime_ns) VALUES (:table_name, :mtime_ns)",
        [{"table_name": t, "mtime_ns": m} for t, m in mtimes.items()],
    )


def ingest_all() -> None:
    """Lê os CSVs de DATA_DIR e recria as tabelas em DB_PATH, tudo ou nada."""
    files = find_csvs()
    mtimes = {table: path.stat().st_mtime_ns for table, path in files.items()}
    loaded = {table: _load(table, path) for table, path in files.items()}  # valida antes de escrever
    specs = _spec_rows(loaded["products"], files["products"].name)
    conn = db.connect_rw()
    try:
        conn.execute("BEGIN")  # DDL também entra na transação: ou troca as 6 tabelas, ou nenhuma
        try:
            _write(conn, loaded, specs, mtimes)
        except BaseException:
            conn.rollback()
            raise
        conn.commit()
    finally:
        conn.close()


# ---------- startup ----------


def _last_import() -> dict[str, int]:
    """mtime de cada CSV na última importação; vazio se ainda não houve nenhuma."""
    if not db.db_path().exists():
        return {}
    conn = db.connect_ro()
    try:
        return dict(conn.execute("SELECT table_name, mtime_ns FROM ingest_meta"))
    except sqlite3.OperationalError:  # banco sem ingest_meta: nunca foi importado
        return {}
    finally:
        conn.close()


def ensure_fresh() -> bool:
    """Reingere se algum CSV é mais novo que a última importação. True se ingeriu.

    CSV mais antigo que a última importação, ou inválido, levanta IngestError, com o banco anterior intacto.
    """
    files = find_csvs()
    previous = _last_import()
    changed = not previous
    for table, path in files.items():
        mtime = path.stat().st_mtime_ns
        before = previous.get(table)
        if before is None or mtime > before:
            changed = True
        elif mtime < before:
            raise IngestError(
                f"{path.name}: mais antigo que a última importação; confira se o arquivo certo foi colado"
            )
    if changed:
        ingest_all()
    return changed


def startup() -> bool:
    """Chamada no startup do app. CSV rejeitado vai para o log e o agente segue com os dados anteriores.

    Sem importação anterior não há o que servir, e o erro sobe.
    """
    try:
        return ensure_fresh()
    except IngestError as exc:
        if not _last_import():
            raise
        log.error("CSV rejeitado, mantendo os dados anteriores: %s", exc)
        return False
