#!/usr/bin/env bash
# Offline SkillOpt — mine real Build runs, propose a revised skill, write a draft.
# Never on the chat hot path, never in the default image's startup.
#
# Usage:
#   HARVIS_SKILLOPT_ENABLED=1 ./scripts/skillopt-offline.sh
#   HARVIS_SKILLOPT_ENABLED=1 ./scripts/skillopt-offline.sh --limit 200 --min-tool-calls 3
#   HARVIS_SKILLOPT_ENABLED=1 ./scripts/skillopt-offline.sh --publish-draft 1
#
# Reads Postgres and the local model endpoint directly from the host — both are
# published (pgsql 5432, Ollama 11434). Nothing leaves the machine.
#
# Output lands in data/skillopt/out/ (gitignored — the corpus holds real task briefs):
#   trajectories.jsonl        the mined corpus
#   best_skill.candidate.md   the proposed skill
#   proposal.json             evidence + every structural check
#   evidence.md               human-readable summary
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export HARVIS_SKILLOPT_ENABLED="${HARVIS_SKILLOPT_ENABLED:-0}"
export PYTHONPATH="${ROOT}/python_back_end:${PYTHONPATH:-}"

# Host-side defaults. Inside a container these are already set to service names.
export HARVIS_SKILLOPT_DSN="${HARVIS_SKILLOPT_DSN:-${DATABASE_URL:-postgresql://pguser:pgpassword@localhost:5432/database}}"
export HARVIS_SKILLOPT_LLM_URL="${HARVIS_SKILLOPT_LLM_URL:-${HARVIS_LLM_BASE_URL:-http://localhost:11434}}"

exec python3 -m skills_training \
  --from-db \
  --skill "${ROOT}/skills/Harvis/harvis-build/SKILL.md" \
  --trajectories "${HARVIS_SKILLOPT_TRAJECTORIES:-${ROOT}/data/skillopt}" \
  --out "${HARVIS_SKILLOPT_OUT:-${ROOT}/data/skillopt/out}" \
  "$@"
