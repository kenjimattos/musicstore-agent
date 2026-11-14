"""Gera as conversas de exemplo do README em `examples/`, com o trace visível.

Uso: uv run python scripts/generate_examples.py   (precisa de ANTHROPIC_API_KEY; ~1 min)

Usa os mesmos cenários dos testes e2e (`tests/e2e/scenarios.py`, campo `example`), numa cópia
temporária de `data/` com REFERENCE_DATE=2026-03-25: o `data/` e o `store.db` reais não mudam.
Cada turno passa pelos critérios de aceite do e2e, e o arquivo diz se passou. No fim, imprime o
resumo do `audit_log` da rodada, para revisar as decisões.
"""

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TITLES = {
    1: "Descoberta: violão até R$ 1.000",
    2: "Preço e PIX em duas mensagens",
    3: "Arrependimento com pedido atrasado",
    4: "Produto sem estoque, cliente irritado",
    5: "Guardrails",
}
SLUGS = {1: "descoberta", 2: "preco_e_pix", 3: "arrependimento_pedido_atrasado", 4: "sem_estoque_irritado",
         5: "guardrails"}


def prepare_store() -> Path:
    """Cópia de data/ com os pedidos extras dos cenários, como a fixture do e2e."""
    from tests.e2e.conftest import _append_rows
    from tests.e2e.scenarios import EXTRA_ORDER_ITEMS, EXTRA_ORDERS, REFERENCE_DATE

    tmp = Path(tempfile.mkdtemp(prefix="examples-"))
    shutil.copytree(ROOT / "data", tmp / "data", ignore=shutil.ignore_patterns("*.db", "*.db-*"))
    _append_rows(tmp / "data" / "orders.csv", EXTRA_ORDERS)
    _append_rows(tmp / "data" / "order_items.csv", EXTRA_ORDER_ITEMS)
    os.environ.update(DATA_DIR=str(tmp / "data"), DB_PATH=str(tmp / "store.db"), REFERENCE_DATE=REFERENCE_DATE)
    from agent import ingest

    ingest.startup()
    return tmp


def short(result: dict, limit: int = 600) -> str:
    text = json.dumps(result, ensure_ascii=False, default=str)
    return text if len(text) <= limit else text[:limit] + " …"


def who(phone: str) -> str:
    from agent import tools

    customer = tools.identify_customer(phone)
    return f"{customer['first_name']} (cliente identificado pelo telefone)" if customer else "visitante (número não cadastrado)"


def render_turn(text: str, reply, verdict: str) -> list[str]:
    t = reply.trace
    lines = [f"**Cliente:** {text}", "", f"**Léo:** {reply.text}", "", "<details><summary>Trace</summary>", "",
             f"- input_guard: `{t.guard_category}`, tom `{t.guard_tone}` ({t.guard_reason})"]
    if t.blocked:
        lines.append("- barrada no input_guard: resposta fixa, o agente não foi chamado")
    for call in t.tool_calls:
        lines.append(f"- tool `{call.name}` `{json.dumps(call.args, ensure_ascii=False)}` → `{short(call.result)}`")
    if not t.blocked:
        lines.append(f"- output_guard: `{t.output_verdict}`, retries {t.retries}, idas ao modelo {t.iterations}")
        lines += [f"  - reprovado no 1º rascunho: {v}" for v in t.violations]
    lines += [f"- critérios de aceite do e2e: {verdict}", "", "</details>", ""]
    return lines


def main() -> None:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY ausente: os exemplos chamam a API")
    tmp = prepare_store()
    try:
        from agent import db
        from agent.agent import respond
        from tests.e2e.scenarios import SCENARIOS
        from tests.e2e.test_conversations import check_turn

        out = ROOT / "examples"
        out.mkdir(exist_ok=True)
        for number, title in TITLES.items():
            lines = [f"# Exemplo {number}: {title}", "",
                     "Gerado por `scripts/generate_examples.py` com os cenários de `tests/e2e/scenarios.py` "
                     "(data simulada 25/03/2026). Abra o trace de cada resposta para ver os guardrails e as "
                     "ferramentas.", ""]
            for scenario in [s for s in SCENARIOS if s.example == number]:
                thread_id = f"example-{scenario.id}"
                lines += [f"## {scenario.title}", "", f"_Quem escreve: {who(scenario.phone)}._", ""]
                for i, turn in enumerate(scenario.turns, start=1):
                    reply = respond(scenario.phone, turn.text, thread_id)
                    try:
                        check_turn(turn.expect, reply, f"{scenario.id} turno {i}")
                        verdict = "✅ passou"
                    except AssertionError as exc:
                        verdict = f"❌ {str(exc).splitlines()[0]}"
                    lines += render_turn(turn.text, reply, verdict)
                    print(f"[{number}] {scenario.id} turno {i}: {verdict}")
            path = out / f"{number}_{SLUGS[number]}.md"
            path.write_text("\n".join(lines), encoding="utf-8")
            print(f"-> {path.relative_to(ROOT)}")

        rows = db.load_audit()
        blocked = sum(r["blocked"] for r in rows)
        retries = sum(r["retries"] for r in rows)
        fallbacks = sum(r["output_verdict"] == "fallback" for r in rows)
        print(f"\naudit_log: {len(rows)} turnos, {blocked} barrados no input_guard, {retries} retries do "
              f"output_guard, {fallbacks} fallbacks")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
