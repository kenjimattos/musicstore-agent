"""Auditoria: uma linha por turno em `audit_log`, para revisar abuso (de clientes ou funcionários) e respostas ruins.

Grava as decisões do turno: o que o cliente escreveu, o que o input_guard decidiu, quais tools o agente
chamou (com os argumentos), o veredito do output_guard e a resposta enviada. Os resultados das tools ficam
de fora: estão no histórico (`messages`) e o log não duplica os dados da base.
"""

import json
from datetime import datetime, timezone

from agent import db


def log_turn(*, thread_id: str, customer_id, message: str, reply: str, trace, duration_ms: int | None) -> None:
    db.insert_audit({
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "thread_id": thread_id,
        "customer_id": customer_id,
        "message": message,
        "guard_category": trace.guard_category,
        "guard_tone": trace.guard_tone,
        "guard_reason": trace.guard_reason,
        "blocked": int(trace.blocked),
        "tools": json.dumps([{"name": c.name, "args": c.args} for c in trace.tool_calls], ensure_ascii=False),
        "iterations": trace.iterations,
        "retries": trace.retries,
        "violations": json.dumps(trace.violations, ensure_ascii=False),
        "output_verdict": trace.output_verdict,
        "reply": reply,
        "duration_ms": duration_ms,
    })
