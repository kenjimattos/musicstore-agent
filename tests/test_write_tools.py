"""Tools de escrita simuladas (exclusão de dados e encaminhamento à equipe) e o dispatch. Sem LLM.

Interface esperada (commit 10c). Toda tool devolve um dict; erro vira `{"error": "..."}`:

    tools.request_data_deletion(*, customer_id=None, thread_id=None) -> {
        "registered": True, "protocol": "LGPD-000001", "status": "pending", "already_requested": bool,
    }   # visitante (customer_id None): {"registered": False, "guidance": "..."} e nada é gravado

    tools.escalate_to_team(reason, summary, order_id=None, *, customer_id=None, phone=None,
                           thread_id=None) -> {
        "protocol": "ATD-000001", "status": "open", "return_deadline": "até 24 horas úteis",
        "already_open": bool, "note_added": bool,
    }   # reason: atraso | reclamacao | valor_contestado | outro; summary: texto de até 300 caracteres
        # idempotente por (cliente ou telefone, pedido): com chamado aberto para o pedido, devolve o mesmo
        # protocolo, qualquer que seja o motivo, e anota nele o resumo novo (note_added), se for diferente

    tools.customer_protocols(*, customer_id=None, phone=None) -> ["ATD-000001", "LGPD-000001", ...]
        # protocolos do próprio cliente (chamados e pedidos de exclusão); fonte do output_guard

    tools.dispatch(name, args, *, customer_id=None, phone=None, thread_id=None) -> dict
    tools.TOOL_SCHEMAS -> [{"name", "description", "input_schema"}, ...]

`customer_id`, `phone` e `thread_id` vêm do código (telefone do canal), nunca do modelo: não existem
nos schemas e o dispatch recusa esses nomes nos argumentos.

Tabelas (criadas pelo `ingest_all`, que nunca as apaga ao reimportar os CSVs):
    data_requests(request_id, customer_id, thread_id, requested_at, status)
    support_tickets(ticket_id, customer_id, phone, order_id, reason, summary, thread_id, created_at, status)
    ticket_notes(note_id, ticket_id, reason, summary, thread_id, created_at)

Escritas só com `INSERT`; nenhuma altera customers, orders, order_items, products nem promotions,
e o chamado original nunca é alterado (a informação nova vai para ticket_notes).
"""

import re
import sqlite3

import pytest

from agent import db, ingest, tools

ANA = 2  # (67) 99654-7821; pedido 8 (enviado, atrasado)
DIEGO_13 = 13  # pedido 14
CAMILA = 10  # pedido 16 (pendente)
VISITOR_PHONE = "(67) 90000-0000"  # não está em customers.csv

READ_ONLY_TABLES = ("customers", "orders", "order_items", "products", "promotions", "categories")


@pytest.fixture
def ready(store):
    ingest.ingest_all()
    return store


def query(sql, **params):
    with db.connect_ro() as conn:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def snapshot():
    """Conteúdo das tabelas da loja, para provar que as tools de escrita não as alteram."""
    with db.connect_ro() as conn:
        return {t: conn.execute(f"SELECT * FROM {t} ORDER BY 1, 2").fetchall() for t in READ_ONLY_TABLES}


def escalate(**overrides):
    args = {"reason": "atraso", "summary": "Pedido 8 enviado e fora da previsão.", "order_id": 8}
    args.update(overrides)
    return tools.escalate_to_team(args.pop("reason"), args.pop("summary"), args.pop("order_id"),
                                  **{"customer_id": ANA, "thread_id": "t1", **args})


# ---------- as tabelas ----------


def test_tables_exist_after_ingest_and_start_empty(ready):
    assert query("SELECT * FROM data_requests") == []
    assert query("SELECT * FROM support_tickets") == []


def test_reingest_keeps_requests_and_tickets(ready):
    tools.request_data_deletion(customer_id=ANA, thread_id="t1")
    escalate()
    ingest.ingest_all()
    assert len(query("SELECT * FROM data_requests")) == 1
    assert len(query("SELECT * FROM support_tickets")) == 1


def test_read_connection_cannot_write(ready):
    with db.connect_ro() as conn:
        for sql in (
            "INSERT INTO data_requests (customer_id, status) VALUES (2, 'pending')",
            "UPDATE products SET price_brl = 1",
            "DELETE FROM customers",
        ):
            with pytest.raises(sqlite3.OperationalError):
                conn.execute(sql)


# ---------- exclusão de dados (LGPD), simulada ----------


def test_deletion_registers_a_pending_request_and_returns_a_protocol(ready):
    result = tools.request_data_deletion(customer_id=ANA, thread_id="t1")
    assert result["registered"] is True
    assert re.fullmatch(r"LGPD-\d{6}", result["protocol"])
    assert result["status"] == "pending"
    assert result["already_requested"] is False
    [row] = query("SELECT * FROM data_requests")
    assert (row["customer_id"], row["thread_id"], row["status"]) == (ANA, "t1", "pending")
    assert row["requested_at"]
    assert result["protocol"] == f"LGPD-{row['request_id']:06d}"


def test_deletion_does_not_change_any_customer_data(ready):
    before = snapshot()
    tools.request_data_deletion(customer_id=ANA, thread_id="t1")
    assert snapshot() == before  # nada foi apagado: é só o registro de um pedido


def test_deletion_is_idempotent(ready):
    first = tools.request_data_deletion(customer_id=ANA, thread_id="t1")
    again = tools.request_data_deletion(customer_id=ANA, thread_id="outra-conversa")
    assert again["protocol"] == first["protocol"]
    assert again["already_requested"] is True
    assert len(query("SELECT * FROM data_requests")) == 1


def test_each_customer_has_their_own_request(ready):
    a = tools.request_data_deletion(customer_id=ANA, thread_id="t1")
    b = tools.request_data_deletion(customer_id=DIEGO_13, thread_id="t2")
    assert a["protocol"] != b["protocol"]
    assert {r["customer_id"] for r in query("SELECT * FROM data_requests")} == {ANA, DIEGO_13}


def test_visitor_gets_guidance_and_nothing_is_written(ready):
    result = tools.request_data_deletion(customer_id=None, thread_id="t1")
    assert result["registered"] is False
    assert result["guidance"]
    assert "protocol" not in result
    assert query("SELECT * FROM data_requests") == []


# ---------- encaminhamento para a equipe, simulado ----------


def test_escalation_opens_a_ticket_with_protocol_and_deadline(ready):
    result = escalate()
    assert re.fullmatch(r"ATD-\d{6}", result["protocol"])
    assert result["status"] == "open"
    assert "24 horas úteis" in result["return_deadline"]
    assert result["already_open"] is False
    [row] = query("SELECT * FROM support_tickets")
    assert row["customer_id"] == ANA
    assert (row["order_id"], row["reason"], row["status"], row["thread_id"]) == (8, "atraso", "open", "t1")
    assert row["summary"] == "Pedido 8 enviado e fora da previsão."
    assert row["created_at"]
    assert result["protocol"] == f"ATD-{row['ticket_id']:06d}"


def test_same_complaint_returns_the_same_protocol(ready):
    first = escalate()
    again = escalate(summary="A cliente reclamou de novo do mesmo atraso.", thread_id="t2")
    assert again["protocol"] == first["protocol"]
    assert again["already_open"] is True
    assert len(query("SELECT * FROM support_tickets")) == 1


def test_another_reason_for_the_same_order_reuses_the_open_ticket(ready):
    # "já reclamei disso" sobre o pedido atrasado não abre um 2º chamado: a equipe já cuida do pedido
    first = escalate()
    other = escalate(reason="reclamacao", summary="A cliente reclamou do atraso.")
    assert other["protocol"] == first["protocol"]
    assert other["already_open"] is True
    assert len(query("SELECT * FROM support_tickets")) == 1


# ---------- anotações no chamado aberto ----------
# Com chamado aberto, a informação nova vira uma anotação nele (INSERT em ticket_notes);
# o chamado original não muda. Assim, "registrei sua reclamação no chamado" é verdade.


def test_new_ticket_has_no_notes(ready):
    result = escalate()
    assert result["note_added"] is False
    assert query("SELECT * FROM ticket_notes") == []


def test_follow_up_on_open_ticket_adds_a_note(ready):
    first = escalate()
    again = escalate(reason="reclamacao", summary="Diz que já reclamou antes do mesmo atraso.", thread_id="t2")
    assert again["note_added"] is True
    [note] = query("SELECT * FROM ticket_notes")
    assert note["ticket_id"] == int(first["protocol"].removeprefix("ATD-"))
    assert (note["reason"], note["summary"], note["thread_id"]) == ("reclamacao", "Diz que já reclamou antes do mesmo atraso.", "t2")
    assert note["created_at"]


def test_follow_up_does_not_change_the_original_ticket(ready):
    escalate()
    [before] = query("SELECT * FROM support_tickets")
    escalate(reason="reclamacao", summary="Diz que já reclamou antes.")
    assert query("SELECT * FROM support_tickets") == [before]


def test_repeated_identical_summary_adds_no_duplicate_note(ready):
    escalate()
    escalate(reason="reclamacao", summary="Diz que já reclamou antes.")
    repeat = escalate(reason="reclamacao", summary="Diz que já reclamou antes.")
    assert repeat["note_added"] is False
    assert len(query("SELECT * FROM ticket_notes")) == 1
    same_as_ticket = escalate()  # mesmo resumo do chamado original
    assert same_as_ticket["note_added"] is False
    assert len(query("SELECT * FROM ticket_notes")) == 1


def test_follow_up_on_someone_elses_order_adds_nothing(ready):
    tools.escalate_to_team("atraso", "Pedido 14 atrasado.", 14, customer_id=DIEGO_13, thread_id="t9")
    result = escalate(order_id=14, summary="Quero saber do pedido do Diego.")
    assert "error" in result
    assert query("SELECT * FROM ticket_notes") == []


def test_notes_do_not_change_store_tables(ready):
    before = snapshot()
    escalate()
    escalate(reason="reclamacao", summary="Diz que já reclamou antes.")
    assert snapshot() == before


def test_reingest_keeps_ticket_notes(ready):
    escalate()
    escalate(reason="reclamacao", summary="Diz que já reclamou antes.")
    ingest.ingest_all()
    assert len(query("SELECT * FROM ticket_notes")) == 1


def test_another_order_opens_another_ticket(ready):
    first = escalate()
    other = escalate(order_id=None, reason="outro", summary="Dúvida sobre garantia.")
    assert other["protocol"] != first["protocol"]
    assert len(query("SELECT * FROM support_tickets")) == 2


# ---------- protocolos do cliente (fonte do output_guard em turnos seguintes) ----------


def test_customer_protocols_lists_tickets_and_deletion_requests(ready):
    ticket = escalate()
    request = tools.request_data_deletion(customer_id=ANA, thread_id="t1")
    assert set(tools.customer_protocols(customer_id=ANA)) == {ticket["protocol"], request["protocol"]}


def test_customer_protocols_never_lists_someone_elses(ready):
    escalate()  # chamado da Ana
    tools.escalate_to_team("outro", "Quer falar com uma pessoa.", None, customer_id=None,
                           phone=VISITOR_PHONE, thread_id="t9")
    assert tools.customer_protocols(customer_id=DIEGO_13) == []
    visitor = tools.customer_protocols(customer_id=None, phone=VISITOR_PHONE)
    assert len(visitor) == 1 and visitor != tools.customer_protocols(customer_id=ANA)


def test_customer_protocols_of_unknown_visitor_is_empty(ready):
    assert tools.customer_protocols(customer_id=None, phone=None) == []


def test_customer_cannot_escalate_someone_elses_order(ready):
    result = escalate(order_id=14)  # pedido do Diego (13)
    assert "error" in result
    assert "protocol" not in result
    assert query("SELECT * FROM support_tickets") == []


def test_other_customers_order_looks_the_same_as_one_that_does_not_exist(ready):
    assert escalate(order_id=14) == escalate(order_id=9999)


def test_customer_can_escalate_without_an_order(ready):
    result = escalate(order_id=None, reason="outro", summary="Dúvida sobre garantia.")
    assert re.fullmatch(r"ATD-\d{6}", result["protocol"])
    assert query("SELECT order_id FROM support_tickets") == [{"order_id": None}]


def test_visitor_opens_a_ticket_with_the_channel_phone_and_no_order(ready):
    result = tools.escalate_to_team("outro", "Quer falar com uma pessoa.", 14, customer_id=None,
                                    phone=VISITOR_PHONE, thread_id="t1")
    assert re.fullmatch(r"ATD-\d{6}", result["protocol"])
    [row] = query("SELECT * FROM support_tickets")
    assert row["customer_id"] is None
    assert re.sub(r"\D", "", row["phone"]) == "67900000000"
    assert row["order_id"] is None  # o visitante não vincula pedido; o número vai no resumo


def test_visitor_ticket_is_idempotent_by_phone_and_reason(ready):
    kwargs = {"customer_id": None, "phone": VISITOR_PHONE, "thread_id": "t1"}
    first = tools.escalate_to_team("outro", "Quer falar com uma pessoa.", None, **kwargs)
    again = tools.escalate_to_team("outro", "Insiste em falar com uma pessoa.", None, **kwargs)
    assert again["protocol"] == first["protocol"]
    assert len(query("SELECT * FROM support_tickets")) == 1


@pytest.mark.parametrize("reason", ["atraso", "reclamacao", "valor_contestado", "outro"])
def test_every_reason_in_the_enum_is_accepted(ready, reason):
    assert "error" not in escalate(reason=reason, order_id=None)


@pytest.mark.parametrize("reason", ["troca", "", None, "ATRASO", 1])
def test_reason_outside_the_enum_is_an_error(ready, reason):
    result = escalate(reason=reason)
    assert "error" in result
    assert "atraso" in result["error"]  # lista as opções válidas
    assert query("SELECT * FROM support_tickets") == []


def test_summary_is_limited_to_300_characters(ready):
    assert "error" not in escalate(summary="x" * 300)
    assert "error" in escalate(reason="reclamacao", summary="x" * 301)
    assert len(query("SELECT * FROM support_tickets")) == 1


@pytest.mark.parametrize("summary", ["", "   ", None, 5])
def test_summary_must_be_text(ready, summary):
    assert "error" in escalate(summary=summary)


@pytest.mark.parametrize("order_id", ["1 OR 1=1", 1.5, -1, True, [8]])
def test_invalid_order_id_is_a_validation_error(ready, order_id):
    assert "error" in escalate(order_id=order_id)
    assert query("SELECT * FROM support_tickets") == []


def test_summary_is_stored_as_data(ready):
    nasty = "'); DROP TABLE support_tickets; --"
    escalate(summary=nasty)
    assert query("SELECT summary FROM support_tickets") == [{"summary": nasty}]
    assert query("SELECT COUNT(*) AS n FROM orders") == [{"n": 20}]


def test_escalation_does_not_change_any_customer_data(ready):
    before = snapshot()
    escalate()
    assert snapshot() == before


# ---------- schemas e dispatch: a identidade vem do código ----------


def schemas():
    return {s["name"]: s for s in tools.TOOL_SCHEMAS}


def test_every_tool_has_a_schema():
    assert set(schemas()) == {
        "search_products", "get_product_details", "get_my_orders", "list_categories",
        "request_data_deletion", "escalate_to_team",
    }
    for schema in schemas().values():
        assert schema["description"]
        assert schema["input_schema"]["type"] == "object"


def test_identity_is_not_in_any_schema():
    for name, schema in schemas().items():
        properties = set(schema["input_schema"]["properties"])
        assert not properties & {"customer_id", "phone", "thread_id"}, name


def test_schema_arguments_of_the_write_and_order_tools():
    props = {n: set(s["input_schema"]["properties"]) for n, s in schemas().items()}
    assert props["request_data_deletion"] == set()
    assert props["get_my_orders"] == {"order_id", "email_or_phone"}
    assert props["escalate_to_team"] == {"reason", "summary", "order_id"}
    assert set(schemas()["escalate_to_team"]["input_schema"]["required"]) == {"reason", "summary"}
    reason = schemas()["escalate_to_team"]["input_schema"]["properties"]["reason"]
    assert set(reason["enum"]) == {"atraso", "reclamacao", "valor_contestado", "outro"}


def test_dispatch_injects_the_identity_from_the_channel(ready):
    result = tools.dispatch("request_data_deletion", {}, customer_id=ANA, phone="67996547821", thread_id="t9")
    assert result["registered"] is True
    assert query("SELECT customer_id, thread_id FROM data_requests") == [{"customer_id": ANA, "thread_id": "t9"}]


def test_dispatch_refuses_identity_in_the_model_arguments(ready):
    """Mesmo um modelo manipulado não escolhe de quem é o pedido de exclusão."""
    before = snapshot()
    for name, args in (
        ("request_data_deletion", {"customer_id": DIEGO_13}),
        ("escalate_to_team", {"reason": "outro", "summary": "x", "customer_id": DIEGO_13}),
        ("get_my_orders", {"order_id": 14, "customer_id": DIEGO_13}),
    ):
        result = tools.dispatch(name, args, customer_id=ANA, phone="67996547821", thread_id="t1")
        assert "error" in result, name
        assert "order" not in result
    assert query("SELECT * FROM data_requests") == []
    assert query("SELECT * FROM support_tickets") == []
    assert snapshot() == before


def test_dispatch_keeps_orders_isolated(ready):
    result = tools.dispatch("get_my_orders", {"order_id": 14}, customer_id=ANA, phone="67996547821", thread_id="t1")
    assert "error" in result
    assert tools.dispatch("get_my_orders", {}, customer_id=ANA, phone="67996547821", thread_id="t1")["order"]["order_id"] == 8


def test_dispatch_visitor_order_lookup_needs_the_owner_contact(ready):
    args = {"order_id": 14, "email_or_phone": "diego.castro@coldmail.com"}
    assert tools.dispatch("get_my_orders", args, customer_id=None, phone=VISITOR_PHONE, thread_id="t1")["order"]["order_id"] == 14


def test_dispatch_unknown_tool_and_bad_arguments_are_errors(ready):
    assert "error" in tools.dispatch("drop_everything", {}, customer_id=ANA, phone="x", thread_id="t")
    assert "error" in tools.dispatch("search_products", {"nome_errado": 1}, customer_id=None, phone="x", thread_id="t")
    assert "error" in tools.dispatch("escalate_to_team", {}, customer_id=ANA, phone="x", thread_id="t")  # faltam argumentos


def test_dispatch_reaches_the_product_tools(ready):
    result = tools.dispatch("search_products", {"query": "Takamine GD20"}, customer_id=None, phone="x", thread_id="t")
    assert result["count"] == 1
    assert tools.dispatch("list_categories", {}, customer_id=None, phone="x", thread_id="t")["categories"]
