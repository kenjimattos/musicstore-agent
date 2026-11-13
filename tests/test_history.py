"""Janela de histórico da conversa (`build_history`). Sem LLM.

Interface esperada (commit 13):

    db.save_message(thread_id, role, content, created_at=None) -> None
        Grava uma linha em `messages` (cria a tabela se faltar). `content` é str ou lista de blocos
        da API (dicts), gravado como JSON. O banco guarda tudo, inclusive tool_use/tool_result.

    agent.agent.build_history(thread_id) -> list[{"role": str, "content": str | list[dict]}]
        A visão do histórico que vai ao modelo, na ordem da conversa:
        - só os últimos HISTORY_TURNS (10) turnos do cliente; um turno começa numa mensagem do
          usuário em texto (content str) e vai até a anterior ao próximo texto do usuário. O corte é
          sempre numa mensagem do usuário, nunca separa um tool_use do seu tool_result;
        - o turno atual (o último, do último texto do usuário em diante) vai intacto;
        - nos turnos anteriores, o conteúdo de cada tool_result vira OMITTED_TOOL_RESULT; os blocos
          tool_use e tool_result continuam (a API exige o par) e o texto da conversa é mantido;
        - o banco não é alterado.

    agent.agent.HISTORY_TURNS == 10
    agent.agent.OMITTED_TOOL_RESULT == "[resultado de consulta anterior omitido]"
"""

import json
import sqlite3

from agent import db
from agent.agent import HISTORY_TURNS, OMITTED_TOOL_RESULT, build_history

THREAD = "t1"
FULL_RESULT = json.dumps({"products": [{"name": "Takamine GD20", "price_brl": 2199.0}]})


def say(thread, role, content):
    db.save_message(thread, role, content)


def plain_turn(n, thread=THREAD):
    say(thread, "user", f"pergunta {n}")
    say(thread, "assistant", [{"type": "text", "text": f"resposta {n}"}])


def tool_turn(n, thread=THREAD, parallel=False):
    """Turno com uma ida às tools (ou duas tools em paralelo) antes da resposta."""
    calls = [("search_products", {"query": f"violao {n}"})]
    if parallel:
        calls.append(("list_categories", {}))
    say(thread, "user", f"pergunta {n}")
    say(thread, "assistant", [{"type": "tool_use", "id": f"toolu_{n}_{i}", "name": name, "input": args}
                              for i, (name, args) in enumerate(calls)])
    say(thread, "user", [{"type": "tool_result", "tool_use_id": f"toolu_{n}_{i}", "content": FULL_RESULT}
                         for i in range(len(calls))])
    say(thread, "assistant", [{"type": "text", "text": f"resposta {n}"}])


def user_texts(history):
    return [m["content"] for m in history if m["role"] == "user" and isinstance(m["content"], str)]


def blocks(history, kind):
    return [b for m in history if isinstance(m["content"], list) for b in m["content"] if b["type"] == kind]


def stored_messages(thread=THREAD):
    with sqlite3.connect(db.db_path()) as conn:
        return conn.execute("SELECT role, content FROM messages WHERE thread_id = ? ORDER BY rowid", (thread,)).fetchall()


# ---------- conversa curta e isolamento ----------


def test_constants():
    assert HISTORY_TURNS == 10
    assert OMITTED_TOOL_RESULT == "[resultado de consulta anterior omitido]"


def test_empty_thread_has_no_history(store):
    assert build_history("nao-existe") == []


def test_short_conversation_is_returned_whole_and_in_order(store):
    plain_turn(1)
    plain_turn(2)
    assert build_history(THREAD) == [
        {"role": "user", "content": "pergunta 1"},
        {"role": "assistant", "content": [{"type": "text", "text": "resposta 1"}]},
        {"role": "user", "content": "pergunta 2"},
        {"role": "assistant", "content": [{"type": "text", "text": "resposta 2"}]},
    ]


def test_threads_are_isolated(store):
    plain_turn(1, "ana")
    plain_turn(2, "bruno")
    assert user_texts(build_history("ana")) == ["pergunta 1"]
    assert user_texts(build_history("bruno")) == ["pergunta 2"]


# ---------- janela de 10 turnos ----------


def test_window_keeps_only_the_last_ten_customer_turns(store):
    for n in range(1, 13):
        plain_turn(n)
    assert user_texts(build_history(THREAD)) == [f"pergunta {n}" for n in range(3, 13)]


def test_exactly_ten_turns_are_all_kept(store):
    for n in range(1, 11):
        plain_turn(n)
    assert len(user_texts(build_history(THREAD))) == 10


def test_window_counts_customer_turns_not_messages(store):
    # turnos com tool_use/tool_result têm 4 mensagens cada; ainda assim a janela é de 10 turnos
    for n in range(1, 13):
        tool_turn(n)
    assert user_texts(build_history(THREAD)) == [f"pergunta {n}" for n in range(3, 13)]


def test_history_always_starts_at_a_user_text_message(store):
    for n in range(1, 14):
        tool_turn(n, parallel=n % 2 == 0)
    history = build_history(THREAD)
    assert history[0]["role"] == "user" and isinstance(history[0]["content"], str)
    assert history[0]["content"] == "pergunta 4"


def test_cut_never_separates_tool_use_from_tool_result(store):
    for n in range(1, 14):
        tool_turn(n, parallel=n % 2 == 0)
    history = build_history(THREAD)
    use_ids = [b["id"] for b in blocks(history, "tool_use")]
    result_ids = [b["tool_use_id"] for b in blocks(history, "tool_result")]
    assert use_ids and sorted(use_ids) == sorted(result_ids)


# ---------- resultados de tools antigos ----------


def test_old_tool_results_become_the_marker(store):
    tool_turn(1)
    plain_turn(2)
    history = build_history(THREAD)
    results = blocks(history, "tool_result")
    assert [r["content"] for r in results] == [OMITTED_TOOL_RESULT]
    assert FULL_RESULT not in json.dumps(history)


def test_old_parallel_tool_results_are_all_replaced(store):
    tool_turn(1, parallel=True)
    plain_turn(2)
    results = blocks(build_history(THREAD), "tool_result")
    assert len(results) == 2
    assert all(r["content"] == OMITTED_TOOL_RESULT for r in results)


def test_old_tool_use_blocks_are_kept_with_their_ids(store):
    tool_turn(1)
    plain_turn(2)
    uses = blocks(build_history(THREAD), "tool_use")
    assert uses == [{"type": "tool_use", "id": "toolu_1_0", "name": "search_products",
                     "input": {"query": "violao 1"}}]
    assert blocks(build_history(THREAD), "tool_result")[0]["tool_use_id"] == "toolu_1_0"


def test_conversation_text_of_old_turns_is_kept(store):
    # "e no PIX?" precisa continuar entendendo de qual produto se fala
    tool_turn(1)
    plain_turn(2)
    history = build_history(THREAD)
    assert user_texts(history) == ["pergunta 1", "pergunta 2"]
    texts = [b["text"] for b in blocks(history, "text")]
    assert texts == ["resposta 1", "resposta 2"]


def test_current_turn_tool_results_are_intact(store):
    tool_turn(1)
    tool_turn(2)  # turno atual: é o último
    results = blocks(build_history(THREAD), "tool_result")
    assert [r["content"] for r in results] == [OMITTED_TOOL_RESULT, FULL_RESULT]


def test_turn_in_progress_keeps_its_tool_result_intact(store):
    # durante o loop: o usuário perguntou, o modelo pediu a tool e o resultado ainda não teve resposta
    plain_turn(1)
    say(THREAD, "user", "pergunta 2")
    say(THREAD, "assistant", [{"type": "tool_use", "id": "toolu_x", "name": "search_products", "input": {}}])
    say(THREAD, "user", [{"type": "tool_result", "tool_use_id": "toolu_x", "content": FULL_RESULT}])
    history = build_history(THREAD)
    assert history[-1] == {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "toolu_x", "content": FULL_RESULT}]}


def test_previous_current_turn_is_summarised_once_a_new_question_arrives(store):
    tool_turn(1)
    assert blocks(build_history(THREAD), "tool_result")[0]["content"] == FULL_RESULT
    say(THREAD, "user", "e no PIX?")
    assert blocks(build_history(THREAD), "tool_result")[0]["content"] == OMITTED_TOOL_RESULT


# ---------- o banco guarda tudo ----------


def test_database_keeps_full_results_after_building_history(store):
    tool_turn(1)
    plain_turn(2)
    build_history(THREAD)
    stored = [json.loads(content) for _, content in stored_messages()]
    assert stored[2][0]["content"] == FULL_RESULT
    assert len(stored) == 6


def test_window_does_not_delete_old_messages(store):
    for n in range(1, 13):
        plain_turn(n)
    build_history(THREAD)
    assert len(stored_messages()) == 24
