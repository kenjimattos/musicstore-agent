"""Ingestão dos CSVs no SQLite. Sem LLM.

Interface esperada (commit 4):
    ingest.ingest_all()      # lê os CSVs de DATA_DIR e recria as tabelas em DB_PATH
    ingest.ensure_fresh()    # chamada só no startup; compara o mtime de cada CSV com o da última importação:
                             #   mais novo -> reingere (True); igual -> nada (False);
                             #   mais antigo ou inválido -> IngestError, com o banco anterior intacto
    ingest.startup()         # ensure_fresh() + log: CSV rejeitado mantém o banco anterior e o agente segue;
                             #   sem banco anterior, o IngestError sobe (não há o que servir)
    ingest.IngestError       # ValueError com mensagem clara (arquivo, coluna ou linha)
    db.connect_rw()          # conexão de escrita (ingest, histórico, auditoria)
    db.connect_ro()          # conexão somente leitura, a única que as tools usam; nunca reingere
    tabela product_specs     # (product_id, key, value), explodida de products.specs (commit 4c)
"""

import csv
import logging
import os
import sqlite3
import time

import pytest

from agent import db, ingest

# tabela -> (sufixo do CSV, chave primária)
TABLES = {
    "categories": ("categories.csv", "category_id"),
    "customers": ("customers.csv", "customer_id"),
    "products": ("products.csv", "product_id"),
    "orders": ("orders.csv", "order_id"),
    "promotions": ("promotions.csv", "promotion_id"),
}


def csv_rows(store, name):
    with open(store.data_dir / name, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(store, name, rows):
    with open(store.data_dir / name, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def bump_mtime(store, name, seconds=60):
    """Simula o CSV novo que a loja colou (mtime mais novo que o da última importação)."""
    path = store.data_dir / name
    later = time.time() + seconds
    os.utime(path, (later, later))


def query(store, sql, *params):
    """Lê o banco direto, sem passar por db.py nem disparar reingestão."""
    conn = sqlite3.connect(store.db_path)
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


# ---------- criação das tabelas ----------


def test_creates_every_table_with_every_row(store):
    ingest.ingest_all()
    for table, (csv_name, _) in TABLES.items():
        expected = len(csv_rows(store, csv_name))
        assert query(store, f"SELECT COUNT(*) FROM {table}")[0][0] == expected, table
    assert query(store, "SELECT COUNT(*) FROM order_items")[0][0] == len(csv_rows(store, "order_items.csv"))


def test_finds_csvs_by_suffix_so_google_sheets_exports_work(store):
    (store.data_dir / "products.csv").rename(store.data_dir / "Emporio da Musica - products.csv")
    ingest.ingest_all()
    assert query(store, "SELECT COUNT(*) FROM products")[0][0] > 0


# ---------- validação: erro claro, em vez de o agente responder errado ----------


def test_missing_column_raises_a_clear_error(store):
    rows = [{k: v for k, v in r.items() if k != "price_brl"} for r in csv_rows(store, "products.csv")]
    write_csv(store, "products.csv", rows)
    with pytest.raises(ingest.IngestError, match=r"products\.csv.*price_brl"):
        ingest.ingest_all()


def test_missing_file_raises_a_clear_error(store):
    (store.data_dir / "orders.csv").unlink()
    with pytest.raises(ingest.IngestError, match=r"orders\.csv"):
        ingest.ingest_all()


def test_invalid_number_raises_a_clear_error(store):
    rows = csv_rows(store, "products.csv")
    rows[0]["price_brl"] = "barato"
    write_csv(store, "products.csv", rows)
    with pytest.raises(ingest.IngestError, match=r"products\.csv.*price_brl.*barato"):
        ingest.ingest_all()


def test_duplicate_primary_key_raises_a_clear_error(store):
    rows = csv_rows(store, "products.csv")
    rows.append(dict(rows[0]))
    write_csv(store, "products.csv", rows)
    with pytest.raises(ingest.IngestError, match=r"products\.csv.*product_id.*duplicad"):
        ingest.ingest_all()


# ---------- limpeza (feita em código, então todo export novo recebe o mesmo tratamento) ----------


def test_empty_cells_become_null_not_empty_strings(store):
    ingest.ingest_all()
    # pedidos ainda não despachados não têm rastreio nem previsão
    assert query(store, "SELECT tracking_code, estimated_delivery, notes FROM orders WHERE order_id = 9") == [
        (None, None, None)
    ]
    assert query(store, "SELECT COUNT(*) FROM orders WHERE tracking_code = ''")[0][0] == 0


def test_numbers_are_stored_as_numbers(store):
    ingest.ingest_all()
    assert query(store, "SELECT typeof(price_brl), typeof(stock_quantity) FROM products WHERE product_id = 95") == [
        ("real", "integer")
    ]
    assert query(store, "SELECT typeof(total_brl) FROM orders WHERE order_id = 8") == [("real",)]


def test_text_is_trimmed_and_emails_are_lowercased(store):
    rows = csv_rows(store, "customers.csv")
    rows[1]["email"] = "  AnaCarol.Ferreira@Coldmail.com "
    rows[1]["name"] = "  Ana Carolina Ferreira "
    write_csv(store, "customers.csv", rows)
    ingest.ingest_all()
    assert query(store, "SELECT name, email FROM customers WHERE customer_id = 2") == [
        ("Ana Carolina Ferreira", "anacarol.ferreira@coldmail.com")
    ]


def test_search_text_is_lowercase_and_accent_free(store):
    ingest.ingest_all()
    (text,) = query(store, "SELECT search_text FROM products WHERE product_id = 81")[0]
    assert "violao classico" in text  # descrição: "Violão clássico..."
    assert "yamaha c40" in text  # nome
    assert text == text.lower() and text.isascii()


# ---------- product_specs: o JSON de specs explodido em chave/valor, para filtrar ----------
# Interface esperada (commit 4c): tabela product_specs (product_id, key, value), índice em (key, value),
# gravada na mesma transação das demais. products.specs continua sendo o JSON original.


def specs_of(store, product_id):
    return dict(query(store, "SELECT key, value FROM product_specs WHERE product_id = ?", product_id))


def test_product_specs_has_one_row_per_key_value_pair(store):
    ingest.ingest_all()
    assert specs_of(store, 111) == {
        "top": "spruce solido",
        "back_sides": "jacaranda",
        "neck": "cedro",
        "strings": "nylon",
        "scale": "650mm",
        "electronics": "yes",
        "color": "natural",
    }
    assert specs_of(store, 82)["electronics"] == "no"


def test_product_specs_values_are_lowercase_and_accent_free(store):
    ingest.ingest_all()
    values = [v for (v,) in query(store, "SELECT value FROM product_specs")]
    assert values and all(v == v.lower() and v.isascii() for v in values)


def test_product_specs_keeps_the_original_json_in_products(store):
    ingest.ingest_all()
    (specs,) = query(store, "SELECT specs FROM products WHERE product_id = 111")[0]
    assert '"Spruce Sólido"' in specs  # fonte intacta, só a tabela de filtro é normalizada


def test_product_specs_can_be_filtered_by_key_and_value(store):
    ingest.ingest_all()
    ids = {i for (i,) in query(store, "SELECT product_id FROM product_specs WHERE key = 'strings' AND value = 'nylon'")}
    assert {81, 82, 111} <= ids


def test_product_specs_has_an_index_on_key_and_value(store):
    ingest.ingest_all()
    (sql,) = query(store, "SELECT sql FROM sqlite_master WHERE type = 'index' AND tbl_name = 'product_specs' AND sql IS NOT NULL")[0]
    assert "key" in sql and "value" in sql


def test_invalid_specs_json_raises_a_clear_error(store):
    rows = csv_rows(store, "products.csv")
    for r in rows:
        if r["product_id"] == "82":
            r["specs"] = '{"strings": "nylon"'  # chave fechada faltando
    write_csv(store, "products.csv", rows)
    with pytest.raises(ingest.IngestError, match=r"products\.csv.*specs.*82"):
        ingest.ingest_all()


def test_reingest_rebuilds_product_specs(store):
    ingest.ensure_fresh()
    rows = csv_rows(store, "products.csv")
    for r in rows:
        if r["product_id"] == "82":
            r["specs"] = '{"strings": "steel"}'
    write_csv(store, "products.csv", rows)
    bump_mtime(store, "products.csv")
    assert ingest.ensure_fresh() is True
    assert specs_of(store, 82) == {"strings": "steel"}


def test_failed_reingest_keeps_the_previous_product_specs(store):
    ingest.ensure_fresh()
    before = query(store, "SELECT product_id, key, value FROM product_specs ORDER BY 1, 2")
    rows = csv_rows(store, "products.csv")
    rows[0]["specs"] = "não é json"
    write_csv(store, "products.csv", rows)
    bump_mtime(store, "products.csv")
    with pytest.raises(ingest.IngestError, match="specs"):
        ingest.ensure_fresh()
    assert query(store, "SELECT product_id, key, value FROM product_specs ORDER BY 1, 2") == before


# ---------- re-ingestão por mtime: "colar o CSV novo e pronto" ----------


def test_ensure_fresh_ingests_when_the_database_does_not_exist_yet(store):
    assert not store.db_path.exists()
    assert ingest.ensure_fresh() is True
    assert query(store, "SELECT COUNT(*) FROM products")[0][0] == len(csv_rows(store, "products.csv"))


def test_ensure_fresh_does_nothing_when_no_csv_changed(store):
    ingest.ensure_fresh()
    assert ingest.ensure_fresh() is False


def test_reingests_when_a_csv_changes(store):
    ingest.ensure_fresh()
    rows = csv_rows(store, "products.csv")
    for r in rows:
        if r["product_id"] == "95":
            r["price_brl"] = "1999.9"
    write_csv(store, "products.csv", rows)
    bump_mtime(store, "products.csv")
    assert ingest.ensure_fresh() is True
    assert query(store, "SELECT price_brl FROM products WHERE product_id = 95") == [(1999.9,)]


def test_rejects_a_csv_older_than_the_last_import(store):
    """A loja sempre cola um export novo: data anterior à da última importação indica o arquivo
    errado (ex.: um backup antigo). O ingest acusa o erro e o banco anterior continua intacto."""
    ingest.ensure_fresh()
    path = store.data_dir / "promotions.csv"
    imported_mtime = path.stat().st_mtime
    rows = csv_rows(store, "promotions.csv")
    rows[0]["is_active"] = "1"
    write_csv(store, "promotions.csv", rows)
    os.utime(path, (imported_mtime - 3600, imported_mtime - 3600))
    with pytest.raises(ingest.IngestError, match=r"promotions\.csv.*mais antigo"):
        ingest.ensure_fresh()
    assert query(store, "SELECT is_active FROM promotions WHERE promotion_id = 1") == [(0,)]


def test_failed_reingest_keeps_the_previous_data(store):
    """CSV errado colado pela loja: erro claro, e o banco anterior continua intacto."""
    ingest.ensure_fresh()
    before = query(store, "SELECT COUNT(*), SUM(price_brl) FROM products")
    rows = [{k: v for k, v in r.items() if k != "stock_quantity"} for r in csv_rows(store, "products.csv")]
    write_csv(store, "products.csv", rows)
    bump_mtime(store, "products.csv")
    with pytest.raises(ingest.IngestError, match="stock_quantity"):
        ingest.ensure_fresh()
    assert query(store, "SELECT COUNT(*), SUM(price_brl) FROM products") == before


# ---------- startup: o ingest só roda aqui ----------


def test_startup_ingests_on_first_run(store):
    ingest.startup()
    assert query(store, "SELECT COUNT(*) FROM products")[0][0] == len(csv_rows(store, "products.csv"))


def test_startup_keeps_the_previous_data_and_logs_when_a_csv_is_rejected(store, caplog):
    """CSV ruim não derruba o agente: o erro vai para o log e as consultas seguem com os últimos dados válidos."""
    ingest.startup()
    before = query(store, "SELECT COUNT(*), SUM(price_brl) FROM products")
    rows = [{k: v for k, v in r.items() if k != "stock_quantity"} for r in csv_rows(store, "products.csv")]
    write_csv(store, "products.csv", rows)
    bump_mtime(store, "products.csv")
    with caplog.at_level(logging.ERROR):
        ingest.startup()  # não levanta
    assert "stock_quantity" in caplog.text
    assert query(store, "SELECT COUNT(*), SUM(price_brl) FROM products") == before


def test_startup_without_a_previous_database_raises(store):
    """Sem dados válidos anteriores não há o que servir: aí o erro tem que subir."""
    rows = [{k: v for k, v in r.items() if k != "stock_quantity"} for r in csv_rows(store, "products.csv")]
    write_csv(store, "products.csv", rows)
    with pytest.raises(ingest.IngestError, match="stock_quantity"):
        ingest.startup()


# ---------- conexões ----------


def test_connect_ro_does_not_reingest_after_startup(store):
    """Colar um CSV novo só vale na próxima inicialização: consultar o banco nunca dispara ingest."""
    ingest.startup()
    rows = csv_rows(store, "products.csv")
    for r in rows:
        if r["product_id"] == "95":
            r["price_brl"] = "1999.9"
    write_csv(store, "products.csv", rows)
    bump_mtime(store, "products.csv")
    conn = db.connect_ro()
    try:
        assert conn.execute("SELECT price_brl FROM products WHERE product_id = 95").fetchone() == (2199.0,)
    finally:
        conn.close()


def test_readonly_connection_rejects_writes(store):
    ingest.ensure_fresh()
    conn = db.connect_ro()
    try:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            conn.execute("UPDATE products SET price_brl = 1 WHERE product_id = 95")
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            conn.execute("DROP TABLE products")
    finally:
        conn.close()
    assert query(store, "SELECT price_brl FROM products WHERE product_id = 95") == [(2199.0,)]


def test_readwrite_connection_can_write(store):
    ingest.ensure_fresh()
    conn = db.connect_rw()
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS scratch (x INTEGER)")
        conn.execute("INSERT INTO scratch VALUES (1)")
        conn.commit()
    finally:
        conn.close()
    assert query(store, "SELECT x FROM scratch") == [(1,)]


# ---------- banco criado por uma versão anterior ----------

OWN_TABLES = ("messages", "audit_log", "data_requests", "support_tickets", "ticket_notes")


def tables(store) -> set[str]:
    return {r[0] for r in query(store, "SELECT name FROM sqlite_master WHERE type = 'table'")}


def test_startup_creates_missing_own_tables_without_reimporting(store):
    # banco de uma versão anterior: CSVs importados, sem as tabelas próprias criadas depois
    ingest.ingest_all()
    conn = db.connect_rw()
    conn.execute("INSERT INTO support_tickets (customer_id, phone, order_id, reason, summary, thread_id, created_at, status) "
                 "VALUES (2, NULL, 8, 'atraso', 'chamado antigo', 't1', '2026-03-25', 'open')")
    for table in ("ticket_notes", "audit_log", "messages"):
        conn.execute(f"DROP TABLE IF EXISTS {table}")
    conn.commit()
    conn.close()

    assert ingest.startup() is False  # CSVs não mudaram: nada a reimportar
    assert set(OWN_TABLES) <= tables(store)
    assert query(store, "SELECT summary FROM support_tickets") == [("chamado antigo",)]  # nada foi apagado


def test_startup_creates_own_tables_even_when_a_csv_is_rejected(store):
    ingest.ingest_all()
    conn = db.connect_rw()
    conn.execute("DROP TABLE IF EXISTS ticket_notes")
    conn.commit()
    conn.close()
    rows = csv_rows(store, "products.csv")
    write_csv(store, "products.csv", [{k: v for k, v in r.items() if k != "price_brl"} for r in rows])
    bump_mtime(store, "products.csv")

    ingest.startup()  # CSV rejeitado: vai para o log e o agente segue com os dados anteriores
    assert "ticket_notes" in tables(store)
