"""O agente: `respond(phone, text, thread_id)`, o mesmo par que um webhook do WhatsApp entrega.

Fluxo (if/else explícitos, sem framework):
  identificar o cliente pelo telefone -> loop de tool use (SDK anthropic) -> output_guard
  (1 retry com feedback; reprovou de novo -> safe_fallback abre um chamado) -> gravar histórico.
O input_guard (classificador Haiku) roda antes do agente: mensagem barrada recebe um template e para ali.
"""

import json
import os
import threading
import time
from contextlib import closing
from dataclasses import dataclass, field

import anthropic
from dotenv import load_dotenv

from agent import audit, db, guards, ingest, policies, prompts, tools

load_dotenv()

HISTORY_TURNS = 10
OMITTED_TOOL_RESULT = "[resultado de consulta anterior omitido]"
MAX_OUTPUT_TOKENS = 2048
STORE_PHONE = "(67) 3341-4444"  # mesmo número das políticas (seção 1.2)


def _max_iterations() -> int:
    return int(os.environ.get("MAX_TOOL_ITERATIONS") or 5)


# ---------- histórico ----------


def _is_user_text(message: dict) -> bool:
    return message["role"] == "user" and isinstance(message["content"], str)


def build_history(thread_id: str) -> list[dict]:
    """A visão do histórico que vai ao modelo (o banco guarda tudo e não é alterado).

    Só os últimos HISTORY_TURNS turnos do cliente, cortando sempre numa mensagem do usuário em texto
    (nunca separa um tool_use do seu tool_result). Nos turnos anteriores ao atual, o conteúdo dos
    tool_result vira um marcador; os blocos continuam, porque a API exige o par.
    """
    messages = db.load_messages(thread_id)
    starts = [i for i, m in enumerate(messages) if _is_user_text(m)]
    if not starts:
        return messages
    window = messages[starts[-HISTORY_TURNS]:] if len(starts) > HISTORY_TURNS else messages
    current = starts[-1] - (len(messages) - len(window))  # início do turno atual dentro da janela
    history = []
    for i, message in enumerate(window):
        content = message["content"]
        if i < current and isinstance(content, list):
            content = [{**b, "content": OMITTED_TOOL_RESULT} if b.get("type") == "tool_result" else b for b in content]
        history.append({"role": message["role"], "content": content})
    return history


# ---------- resultado e trace ----------


@dataclass
class ToolCall:
    name: str
    args: dict
    result: dict


@dataclass
class Trace:
    guard_category: str = "in_scope"
    guard_tone: str = "neutral"
    guard_reason: str = ""
    blocked: bool = False
    tool_calls: list[ToolCall] = field(default_factory=list)
    iterations: int = 0
    output_verdict: str | None = None  # "approved" | "fallback" | None (barrado na entrada)
    retries: int = 0
    violations: list[str] = field(default_factory=list)


@dataclass
class Reply:
    text: str
    trace: Trace


# ---------- loop de tool use ----------

_client: anthropic.Anthropic | None = None


def client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


def _blocks(response) -> list[dict]:
    """Blocos da resposta como dicts. Os de thinking ficam só em memória, durante o turno."""
    return [b.model_dump(exclude_none=True) for b in response.content]


def reply_text(new: list[dict]) -> str | None:
    """O texto enviado ao cliente: o de TODAS as mensagens do assistente no turno, em ordem.

    Inclui o que o modelo escreveu antes de um tool_use; senão essa parte sumiria para o cliente
    e escaparia do output_guard, embora fique no histórico como dita.
    """
    parts = []
    for message in new:
        if message["role"] != "assistant":
            continue
        text = "".join(b["text"] for b in message["content"] if b["type"] == "text").strip()
        if text:
            parts.append(text)
    return "\n\n".join(parts) or None


def run_agent_loop(messages: list[dict], system: list[dict], *, customer_id, phone, thread_id, trace: Trace):
    """Loop clássico: chama o modelo; enquanto pedir tools, executa e devolve os tool_result.

    `messages` é alterada no lugar (mensagens do assistente e dos tool_result do turno).
    Devolve (texto de todo o turno, mensagens novas no formato do banco), ou (None, novas) se atingiu
    o limite de iterações.
    """
    new: list[dict] = []
    for _ in range(_max_iterations()):
        response = client().messages.create(
            model=os.environ.get("AGENT_MODEL") or "claude-haiku-5-5",
            max_tokens=MAX_OUTPUT_TOKENS,
            system=system,
            tools=tools.TOOL_SCHEMAS,
            thinking={"type": "adaptive"},
            output_config={"effort": "low"},
            messages=messages,
        )
        trace.iterations += 1
        blocks = _blocks(response)
        messages.append({"role": "assistant", "content": blocks})
        stored = [b for b in blocks if b["type"] != "thinking" and b["type"] != "redacted_thinking"]
        new.append({"role": "assistant", "content": stored})
        if response.stop_reason != "tool_use":
            return reply_text(new), new
        results = []
        for block in blocks:
            if block["type"] != "tool_use":
                continue
            result = tools.dispatch(block["name"], block["input"], customer_id=customer_id, phone=phone,
                                    thread_id=thread_id)
            trace.tool_calls.append(ToolCall(block["name"], block["input"], result))
            results.append({"type": "tool_result", "tool_use_id": block["id"],
                            "content": _dump(result), **({"is_error": True} if "error" in result else {})})
        messages.append({"role": "user", "content": results})
        new.append({"role": "user", "content": results})
    return None, new


def _dump(result: dict) -> str:
    return json.dumps(result, ensure_ascii=False, default=str)


# ---------- respond ----------

_ready: set = set()
_ready_lock = threading.Lock()


def _ensure_database() -> None:
    """Ingere os CSVs na primeira mensagem deste banco no processo (o app também chama no startup)."""
    path = db.db_path()
    with _ready_lock:
        if path not in _ready:
            ingest.startup()
            _ready.add(path)


def safe_fallback(summary: str, *, customer_id, phone, thread_id) -> str:
    """Resposta segura quando o output_guard reprova duas vezes: o código abre o chamado, não o modelo.

    Se a conversa já tem chamado aberto, reaproveita o protocolo dele (um caso, um protocolo).
    """
    with closing(db.connect_ro()) as conn:
        open_id = db.open_ticket_in_thread(conn, thread_id)
    if open_id is not None:
        ticket = {"protocol": tools.ticket_protocol(open_id), "return_deadline": tools.RETURN_DEADLINE}
    else:
        ticket = tools.escalate_to_team("outro", summary[:tools.MAX_SUMMARY_CHARS] or "Pergunta sem resposta verificada",
                                        customer_id=customer_id, phone=phone, thread_id=thread_id)
    protocol = ticket.get("protocol")
    deadline = ticket.get("return_deadline", tools.RETURN_DEADLINE)
    note = f" (protocolo {protocol})" if protocol else ""
    return (f"Não consegui confirmar essa informação com segurança, então encaminhei para a equipe{note}. "
            f"O retorno é {deadline}. Se preferir, fale com a loja pelo telefone {STORE_PHONE}.")


def respond(phone: str, text: str, thread_id: str) -> Reply:
    """Um turno: guard de entrada, agente, guard de saída. Cada turno vira uma linha no audit_log."""
    _ensure_database()
    started = time.monotonic()
    customer = tools.identify_customer(phone)
    customer_id = customer["customer_id"] if customer else None
    reply = _respond(phone, text, thread_id, customer)
    audit.log_turn(thread_id=thread_id, customer_id=customer_id, message=text, reply=reply.text, trace=reply.trace,
                   duration_ms=int((time.monotonic() - started) * 1000))
    return reply


def _respond(phone: str, text: str, thread_id: str, customer: dict | None) -> Reply:
    trace = Trace()
    customer_id = customer["customer_id"] if customer else None
    verdict = guards.input_guard(text, build_history(thread_id))
    trace.guard_category, trace.guard_tone, trace.guard_reason = verdict.category, verdict.tone, verdict.reason
    db.save_message(thread_id, "user", text)
    if verdict.category != "in_scope":  # barrado: template fixo, o agente nem é chamado
        trace.blocked = True
        refusal = guards.REFUSALS[verdict.category]
        db.save_message(thread_id, "assistant", [{"type": "text", "text": refusal}])
        return Reply(refusal, trace)

    system = prompts.build_system(policies.load_policies(), customer, tools.today(), trace.guard_tone)
    messages = build_history(thread_id)
    identity = {"customer_id": customer_id, "phone": phone, "thread_id": thread_id}
    turn_results: list[dict] = []  # fontes do output_guard: só as tools do turno atual

    answer = None
    for attempt in range(2):
        before = len(trace.tool_calls)
        answer, new = run_agent_loop(messages, system, trace=trace, **identity)
        for message in new:
            db.save_message(thread_id, message["role"], message["content"])
        turn_results += [c.result for c in trace.tool_calls[before:]]
        if answer is None:  # limite de iterações: nunca uma resposta pela metade
            break
        verdict = guards.output_guard(answer, turn_results, policies.load_policies(),
                                      known=tools.known_identifiers(**identity))
        if verdict.ok:
            trace.output_verdict = "approved"
            return Reply(answer, trace)
        trace.violations += verdict.violations
        if attempt == 0:
            trace.retries += 1
            feedback = ("Sua resposta foi reprovada na verificação de fatos:\n- " + "\n- ".join(verdict.violations)
                        + "\nRefaça a resposta ao cliente: consulte a ferramenta ou remova o que não tem fonte. "
                        "O cliente NÃO viu a resposta reprovada: escreva a mensagem de novo, do zero, sem pedir "
                        "desculpas por erro, sem falar em correção nem em verificação.")
            content = [{"type": "text", "text": feedback}]  # lista: não conta como nova pergunta do cliente
            messages.append({"role": "user", "content": content})
            db.save_message(thread_id, "user", content)

    reply = safe_fallback(text, **identity)
    trace.output_verdict = "fallback"
    db.save_message(thread_id, "assistant", [{"type": "text", "text": reply}])
    return Reply(reply, trace)
