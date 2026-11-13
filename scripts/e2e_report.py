"""Taxa de acerto dos cenários e2e em várias rodadas gravadas com E2E_RECORD_DIR.

Uso: uv run python scripts/e2e_report.py e2e-runs/<data-hora>
     (a pasta tem uma subpasta por rodada, run-1, run-2..., cada uma com <cenário>.jsonl)

Um cenário passa numa rodada se todos os turnos foram gravados com ok=true (o teste para no
primeiro turno que falha). Grava report.md na pasta e imprime o mesmo conteúdo.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.e2e.scenarios import SCENARIOS  # noqa: E402


def load(run: Path, scenario_id: str) -> list[dict]:
    path = run / f"{scenario_id}.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def outcome(rows: list[dict], expected_turns: int) -> tuple[str, str]:
    """('ok' | 'falhou' | 'sem dado', motivo da 1ª falha)."""
    if not rows:
        return "sem dado", "nenhum turno gravado (erro antes da resposta?)"
    failed = next((r for r in rows if not r["ok"]), None)
    if failed:
        return "falhou", f"turno {failed['turn']}: {failed['error']}"
    if len(rows) < expected_turns:
        return "falhou", f"parou no turno {len(rows) + 1} sem gravar"
    return "ok", ""


def main(root: Path) -> str:
    runs = sorted(p for p in root.iterdir() if p.is_dir() and p.name.startswith("run-"))
    # só os cenários que rodaram em alguma rodada (uma rodada parcial não lista os demais como falha)
    scenarios = [s for s in SCENARIOS if any((run / f"{s.id}.jsonl").exists() for run in runs)]
    lines = [f"# Linha de base e2e: {root.name}", "", f"{len(runs)} rodadas, {len(scenarios)} cenários.", "",
             "| cenário | " + " | ".join(r.name for r in runs) + " | acerto |",
             "|---|" + "---|" * len(runs) + "---|"]
    failures = []
    totals = [0] * len(runs)
    for scenario in scenarios:
        marks, passed = [], 0
        for k, run in enumerate(runs):
            status, reason = outcome(load(run, scenario.id), len(scenario.turns))
            marks.append({"ok": "✅", "falhou": "❌", "sem dado": "⚠️"}[status])
            if status == "ok":
                passed += 1
                totals[k] += 1
            else:
                failures.append(f"- **{scenario.id}** ({run.name}) {reason}")
        lines.append(f"| {scenario.id} | " + " | ".join(marks) + f" | {passed}/{len(runs)} |")
    lines.append("| **total** | " + " | ".join(f"{t}/{len(scenarios)}" for t in totals) + " | |")
    lines += ["", "## Falhas", ""] + (failures or ["nenhuma"])
    report = "\n".join(lines) + "\n"
    (root / "report.md").write_text(report, encoding="utf-8")
    return report


if __name__ == "__main__":
    print(main(Path(sys.argv[1])))
