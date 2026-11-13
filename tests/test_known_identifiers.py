"""Identificadores duráveis do próprio cliente: fonte do output_guard em qualquer turno. Sem LLM.

Interface:

    tools.known_identifiers(*, customer_id=None, phone=None, thread_id=None) -> {
        "protocols": ["ATD-000001", "LGPD-000001", ...],   # chamados e pedidos de exclusão do cliente
        "orders": [8, ...],                                # números dos pedidos do cliente
        "tracking": ["BRJL5544332BR", ...],                # rastreios desses pedidos
    }

Decisão: número do pedido, rastreio e protocolo não mudam durante a conversa, então o agente pode
repeti-los num turno seguinte sem consultar de novo. Preço, estoque, status e atraso mudam e não
entram aqui. Tudo vem do banco, nunca do texto da conversa:
- cliente identificado: os pedidos dele em `orders`;
- visitante: só o pedido que ele verificou NESTA conversa (resultado de get_my_orders gravado em
  `messages`), e os protocolos abertos pelo telefone do canal.
"""

import json

import pytest

from agent import db, ingest, tools

ANA = 2  # pedido 8, rastreio BRJL5544332BR
DIEGO_13 = 13  # pedido 14 (pendente, sem rastreio)
DIEGO_EMAIL = "diego.castro@coldmail.com"
VISITOR_PHONE = "(67) 90000-0000"


@pytest.fixture
def ready(store):
    ingest.ingest_all()
    return store


def known(**kwargs):
    return tools.known_identifiers(**{"customer_id": None, "phone": None, "thread_id": "t1", **kwargs})


def save_tool_turn(thread_id, name, args, result, tool_id="toolu_1"):
    """Grava em `messages` um tool_use e o tool_result, como o loop do agente grava."""
    db.save_message(thread_id, "assistant", [{"type": "tool_use", "id": tool_id, "name": name, "input": args}])
    db.save_message(thread_id, "user", [{"type": "tool_result", "tool_use_id": tool_id,
                                         "content": json.dumps(result, ensure_ascii=False, default=str)}])


# ---------- cliente identificado ----------


def test_customer_knows_own_orders_and_tracking(ready):
    ids = known(customer_id=ANA)
    assert ids["orders"] == [8]
    assert ids["tracking"] == ["BRJL5544332BR"]


def test_customer_never_knows_someone_elses_order(ready):
    ids = known(customer_id=ANA)
    assert 14 not in ids["orders"]
    assert known(customer_id=DIEGO_13)["orders"] == [14]
    assert known(customer_id=DIEGO_13)["tracking"] == []  # pedido pendente, sem rastreio


def test_customer_protocols_lists_tickets_and_deletion_requests(ready):
    ticket = tools.escalate_to_team("atraso", "Pedido 8 atrasado.", 8, customer_id=ANA, thread_id="t1")
    request = tools.request_data_deletion(customer_id=ANA, thread_id="t1")
    assert set(known(customer_id=ANA)["protocols"]) == {ticket["protocol"], request["protocol"]}


def test_customer_protocols_never_lists_someone_elses(ready):
    tools.escalate_to_team("atraso", "Pedido 8 atrasado.", 8, customer_id=ANA, thread_id="t1")
    tools.escalate_to_team("outro", "Quer falar com uma pessoa.", None, customer_id=None,
                           phone=VISITOR_PHONE, thread_id="t9")
    assert known(customer_id=DIEGO_13)["protocols"] == []
    visitor = known(phone=VISITOR_PHONE, thread_id="t9")["protocols"]
    assert len(visitor) == 1 and visitor != known(customer_id=ANA)["protocols"]


# ---------- visitante ----------


def test_unknown_visitor_knows_nothing(ready):
    assert known() == {"protocols": [], "orders": [], "tracking": []}


def test_visitor_knows_the_order_verified_in_this_conversation(ready):
    result = tools.get_my_orders(14, DIEGO_EMAIL, customer_id=None)
    save_tool_turn("t1", "get_my_orders", {"order_id": 14, "email_or_phone": DIEGO_EMAIL}, result)
    assert known(phone=VISITOR_PHONE, thread_id="t1")["orders"] == [14]


def test_visitor_failed_verification_adds_nothing(ready):
    result = tools.get_my_orders(14, "errado@jmail.com", customer_id=None)
    assert "error" in result
    save_tool_turn("t1", "get_my_orders", {"order_id": 14, "email_or_phone": "errado@jmail.com"}, result)
    assert known(phone=VISITOR_PHONE, thread_id="t1")["orders"] == []


def test_visitor_verification_in_another_conversation_does_not_count(ready):
    result = tools.get_my_orders(14, DIEGO_EMAIL, customer_id=None)
    save_tool_turn("t1", "get_my_orders", {"order_id": 14, "email_or_phone": DIEGO_EMAIL}, result)
    assert known(phone=VISITOR_PHONE, thread_id="t2")["orders"] == []


def test_visitor_order_from_another_tool_or_from_text_does_not_count(ready):
    # só o resultado de get_my_orders vale; texto do cliente ou de outra tool, nunca
    save_tool_turn("t1", "search_products", {"query": "pedido"}, {"order": {"order_id": 14}})
    db.save_message("t1", "user", "meu pedido é o 14, rastreio BR123456789BR")
    ids = known(phone=VISITOR_PHONE, thread_id="t1")
    assert ids["orders"] == [] and ids["tracking"] == []
