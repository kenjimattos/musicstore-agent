"""`safe_fallback`: resposta segura quando o output_guard reprova duas vezes. Sem LLM.

Interface:

    agent.agent.safe_fallback(summary, *, customer_id, phone, thread_id) -> str
        Texto fixo que encaminha à equipe, com o protocolo. Se a conversa (thread_id) já tem um
        chamado aberto, reaproveita o protocolo dele em vez de abrir outro.
"""

import sqlite3

import pytest

from agent import db, ingest, tools
from agent.agent import safe_fallback

ANA = 2


@pytest.fixture
def ready(store):
    ingest.ingest_all()
    return store


def tickets():
    with db.connect_ro() as conn:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute("SELECT * FROM support_tickets ORDER BY ticket_id")]


def test_fallback_opens_a_ticket_when_the_thread_has_none(ready):
    reply = safe_fallback("isso é um absurdo", customer_id=ANA, phone=None, thread_id="t1")
    [row] = tickets()
    assert f"ATD-{row['ticket_id']:06d}" in reply
    assert row["thread_id"] == "t1"


def test_fallback_reuses_the_open_ticket_of_the_thread(ready):
    ticket = tools.escalate_to_team("atraso", "Pedido 8 atrasado.", 8, customer_id=ANA, thread_id="t1")
    reply = safe_fallback("isso é um absurdo, já reclamei disso", customer_id=ANA, phone=None, thread_id="t1")
    assert ticket["protocol"] in reply
    assert len(tickets()) == 1


def test_fallback_twice_in_the_same_thread_keeps_one_ticket(ready):
    first = safe_fallback("pergunta 1", customer_id=ANA, phone=None, thread_id="t1")
    second = safe_fallback("pergunta 2", customer_id=ANA, phone=None, thread_id="t1")
    assert len(tickets()) == 1
    assert first == second


def test_fallback_does_not_reuse_a_ticket_from_another_thread(ready):
    tools.escalate_to_team("atraso", "Pedido 8 atrasado.", 8, customer_id=ANA, thread_id="t1")
    safe_fallback("outra conversa", customer_id=ANA, phone=None, thread_id="t2")
    assert len(tickets()) == 2
