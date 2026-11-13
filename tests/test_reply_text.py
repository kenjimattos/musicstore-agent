"""Texto da resposta ao cliente a partir das mensagens do turno (`reply_text`). Sem LLM.

Interface esperada:

    agent.agent.reply_text(new) -> str | None
        `new` são as mensagens que o loop de tool use gerou no turno (formato do banco).
        Junta, na ordem, o texto de TODAS as mensagens do assistente, inclusive o que veio
        antes de um tool_use, separado por linha em branco. Sem texto nenhum -> None.

Motivo: o modelo pode escrever parte da resposta no mesmo bloco em que pede uma tool
("achei seu pedido, rastreio X; vou abrir um chamado" + tool_use). Se só o texto da
última ida ao modelo vira resposta, essa parte some para o cliente e escapa do output_guard.
"""

from agent.agent import reply_text


def _assistant(*blocks):
    return {"role": "assistant", "content": list(blocks)}


def _text(t):
    return {"type": "text", "text": t}


def _tool_use(name="get_my_orders"):
    return {"type": "tool_use", "id": "toolu_1", "name": name, "input": {}}


def _tool_result():
    return {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_1", "content": "{}"}]}


def test_text_before_tool_use_is_kept():
    new = [
        _assistant(_text("Achei seu pedido 8, rastreio BRJL5544332BR. Vou abrir um chamado."), _tool_use()),
        _tool_result(),
        _assistant(_text("Chamado aberto: ATD-000001.")),
    ]
    assert reply_text(new) == "Achei seu pedido 8, rastreio BRJL5544332BR. Vou abrir um chamado.\n\nChamado aberto: ATD-000001."


def test_single_answer_without_tools():
    assert reply_text([_assistant(_text("  Oi! Abrimos às 9h.  "))]) == "Oi! Abrimos às 9h."


def test_tool_use_without_text_adds_nothing():
    new = [_assistant(_tool_use()), _tool_result(), _assistant(_text("Seu pedido foi enviado."))]
    assert reply_text(new) == "Seu pedido foi enviado."


def test_no_text_at_all_is_none():
    assert reply_text([_assistant(_tool_use()), _tool_result()]) is None
    assert reply_text([_assistant(_text("   "))]) is None
