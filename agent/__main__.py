"""CLI mínima para depurar sem UI: python -m agent "pergunta" [--phone 67996547821] [--thread id]."""

import argparse
import json

from agent import ingest
from agent.agent import respond


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m agent")
    parser.add_argument("text")
    parser.add_argument("--phone", default="", help="telefone do canal; vazio = visitante")
    parser.add_argument("--thread", default="cli")
    args = parser.parse_args()
    ingest.startup()
    reply = respond(args.phone, args.text, args.thread)
    print(reply.text)
    trace = reply.trace
    print(f"\n[guard: {trace.guard_category}/{trace.guard_tone} | idas ao modelo: {trace.iterations} | "
          f"output_guard: {trace.output_verdict} | retries: {trace.retries}]")
    for call in trace.tool_calls:
        print(f"[tool] {call.name}({json.dumps(call.args, ensure_ascii=False)})")


if __name__ == "__main__":
    main()
