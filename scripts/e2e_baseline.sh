#!/usr/bin/env bash
# Roda o e2e completo N vezes (padrão 3), grava cada turno e gera o relatório de acerto.
# Uso: scripts/e2e_baseline.sh [N]    (precisa de ANTHROPIC_API_KEY; cada rodada leva ~10 min)
# Saída: e2e-runs/<data-hora>/run-<k>/<cenário>.jsonl, pytest.log por rodada e report.md
set -u
cd "$(dirname "$0")/.."
runs="${1:-3}"
root="e2e-runs/$(date +%Y%m%d-%H%M%S)"
for k in $(seq 1 "$runs"); do
  dir="$root/run-$k"
  mkdir -p "$dir"
  echo "rodada $k/$runs -> $dir"
  E2E_RECORD_DIR="$dir" uv run pytest -m e2e -q -p no:cacheprovider tests/e2e/test_conversations.py > "$dir/pytest.log" 2>&1
  tail -1 "$dir/pytest.log"
done
uv run python scripts/e2e_report.py "$root"
