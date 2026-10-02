#!/usr/bin/env bash
#
# verify-fresh-install.sh — the two checks that only a clean machine can answer.
#
# The Docker phase has one finish line: "fresh clone → working Harvis in one
# command, no questions asked, under 7 GB." Everything else in that phase was
# verified on a development box. These two were not, because they need a machine
# with no Harvis images, no warm build cache, and no LLM server running:
#
#   1. The measured one-command claim. What a fresh clone plus ./install.sh
#      actually costs on disk, with nothing pre-pulled to hide behind.
#   2. The no-engine case. No GPU, no model server anywhere: the stack still
#      comes up and says so plainly instead of erroring. This is the check that
#      proves "plug-and-play" rather than merely "smaller".
#
# HOW TO RUN, on a machine that has never run Harvis:
#
#   git clone -b deploy-optimize-test <repo> harvis && cd harvis
#   ./install.sh            # the one command under test — time it
#   ./scripts/verify-fresh-install.sh
#
# Do NOT start Ollama, LM Studio, llama.cpp or vLLM first. Their absence is the
# point of check 2. If the machine happens to have one running, stop it, or the
# no-engine assertions below are measuring nothing.
#
# Exits non-zero if the footprint is over budget or an assertion fails. Two
# steps at the end need human eyes and are printed, not asserted.

set -uo pipefail

BUDGET_GB="${BUDGET_GB:-7.0}"
UI_URL="${UI_URL:-http://localhost:9000}"
FAILED=0

say()  { printf '\n\033[1m%s\033[0m\n' "$*"; }
pass() { printf '  \033[32mok\033[0m    %s\n' "$*"; }
fail() { printf '  \033[31mFAIL\033[0m  %s\n' "$*"; FAILED=1; }
note() { printf '        %s\n' "$*"; }

# ---------------------------------------------------------------- preconditions

say "Preconditions"

[ -f docker-compose.yaml ] || { fail "run this from the repo root (no docker-compose.yaml here)"; exit 1; }
command -v docker >/dev/null || { fail "docker not on PATH"; exit 1; }
docker compose version >/dev/null 2>&1 || { fail "docker compose v2 not available"; exit 1; }
pass "docker and compose v2 present"

if [ -f .env ]; then
  pass ".env exists (install.sh wrote it)"
else
  fail ".env missing — did ./install.sh run and finish?"
fi

# A warm image store makes every number below a lie. This is the single most
# common way a "fresh install" measurement comes out wrong.
PRE_IMAGES=$(docker images -q | sort -u | wc -l)
note "images currently on this host: ${PRE_IMAGES}"
note "(on a genuinely clean machine these are all Harvis's — if this box had"
note " unrelated images before the install, the footprint below is inflated.)"

# ------------------------------------------------------------------- footprint

say "Check 1 — the measured one-command claim"

# Whole tree minus .git, rather than `du --exclude`: macOS and busybox du have
# no --exclude, and an empty REPO_KB crashed the footprint check below.
REPO_KB=$(du -sk . 2>/dev/null | cut -f1)
GIT_KB=0
[ -d .git ] && GIT_KB=$(du -sk .git 2>/dev/null | cut -f1)
REPO_KB=$(( ${REPO_KB:-0} - ${GIT_KB:-0} ))

python3 - "$BUDGET_GB" "$REPO_KB" <<'PY'
import json, subprocess, sys

budget = float(sys.argv[1])
repo_gb = int(sys.argv[2]) / 1024 / 1024

def to_gb(s):
    s = s.split("(")[0].strip()
    for unit, mult in (("TB", 1024), ("GB", 1), ("MB", 1/1024),
                       ("kB", 1/1024**2), ("B", 1/1024**3)):
        if s.endswith(unit):
            return float(s[:-len(unit)].strip()) * mult
    raise SystemExit(f"could not parse docker size {s!r}")

# `docker system df`, never `docker image inspect --format '{{.Size}}'`. Under
# the containerd snapshotter that field reports unique-layer bytes; it said
# 5.07 GB for a 15.4 GB image during this phase and was believed for a while.
rows = [json.loads(l) for l in subprocess.run(
    ["docker", "system", "df", "--format", "json"],
    capture_output=True, text=True, check=True).stdout.splitlines() if l.strip()]
by_type = {r["Type"]: r for r in rows}

images_gb  = to_gb(by_type["Images"]["Size"])
volumes_gb = to_gb(by_type["Local Volumes"]["Size"])
total = images_gb + volumes_gb + repo_gb

print(f"  images          {images_gb:6.2f} GB   ({by_type['Images']['TotalCount']} images)")
print(f"  local volumes   {volumes_gb:6.2f} GB")
print(f"  repo checkout   {repo_gb:6.2f} GB   (excluding .git)")
print(f"  {'-'*38}")
print(f"  on-disk total   {total:6.2f} GB   budget {budget:.2f} GB")

if total > budget:
    print(f"\n  FAIL  over budget by {total - budget:.2f} GB")
    sys.exit(1)
print(f"\n  ok    {budget - total:.2f} GB under budget")
PY
[ $? -ne 0 ] && FAILED=1

say "  per-image breakdown (what to blame if the total moved)"
docker images --format '{{.Repository}}:{{.Tag}}\t{{.Size}}' | sort | sed 's/^/        /'

note ""
note "Model weights are deliberately NOT in the number above. A fresh install"
note "downloads none: ml-models-cache stays empty until something pulls, and"
note "voice-models fills on the first speech request (~1.1 GB). Re-run this"
note "script after exercising voice if you want the warmed-up figure."

# --------------------------------------------------------------- liveness

say "Check 2a — the default set is actually up"

# What a clean deploy gets. Grew from 8 to 10 on 2026-09-15: `llmfit` arrived
# with the FreeToken inference-node work and `preview-runner` with the
# multi-file build preview. Both are unprofiled in docker-compose.yaml, so a
# fresh `./install.sh` starts them. `repo-sandbox-image` (2026-09-30) only builds
# the per-chat sandbox image. `owui-builder` left on 2026-10-01 when Hermes
# became the only frontend. Update this list when that file changes.
EXPECTED="artifact-init backend browser-runner harvis-mcp hermes-ui-builder llmfit nginx pgsql preview-runner repo-sandbox-image voice-onnx"
# -f pins this to the file we SHIP. Without it Compose silently merges
# docker-compose.override.yml, which is gitignored and personal — on a
# developer box that makes this check measure their machine, not the deploy.
RENDERED=$(docker compose -f docker-compose.yaml config --services 2>/dev/null | sort | tr '\n' ' ' | sed 's/ $//')
if [ "$RENDERED" = "$(echo $EXPECTED | tr ' ' '\n' | sort | tr '\n' ' ' | sed 's/ $//')" ]; then
  pass "compose renders exactly the $(echo $EXPECTED | wc -w) default services"
else
  fail "default service set changed"
  note "expected: $EXPECTED"
  note "rendered: $RENDERED"
fi

# artifact-init and hermes-ui-builder are one-shot: they populate a bind mount and
# exit 0. Treating their absence from `ps` as a failure would be wrong.
for svc in backend browser-runner harvis-mcp llmfit nginx pgsql preview-runner voice-onnx; do
  state=$(docker compose ps --format '{{.Service}} {{.State}}' 2>/dev/null | awk -v s="$svc" '$1==s {print $2}')
  case "$state" in
    running) pass "$svc running" ;;
    "")      fail "$svc is not present at all" ;;
    *)       fail "$svc is '$state'" ;;
  esac
done

for svc in artifact-init hermes-ui-builder repo-sandbox-image; do
  code=$(docker compose ps -a --format '{{.Service}} {{.ExitCode}}' 2>/dev/null | awk -v s="$svc" '$1==s {print $2}')
  if [ "$code" = "0" ]; then pass "$svc completed (exit 0)"
  else fail "$svc exit code '$code' (expected 0)"; fi
done

say "Check 2b — the UI loads"

# `/harvis/` serves the Hermes shell to everyone. Sign-in is a screen inside
# Hermes, and the backend checks every API and WebSocket call, so nginx no longer
# gates the page itself. A 200 alone proves little (an empty dist dir still
# answers), so the body must reference the built asset bundle.
BODY=$(curl -fsS --max-time 20 "$UI_URL/harvis/" 2>/dev/null || true)
if printf '%s' "$BODY" | grep -q '/harvis/assets/'; then
  pass "$UI_URL/harvis/ serves the Hermes shell"
else
  fail "$UI_URL/harvis/ did not serve the Hermes shell — check hermes-ui-builder's bind mount (front_end/hermes-desktop-ui/dist)"
fi

# The bundle the shell points at must load, or the page is blank.
ASSET=$(printf '%s' "$BODY" | grep -o '/harvis/assets/[^"]*\.js' | head -n1)
if [ -n "$ASSET" ] && curl -fsS -o /dev/null --max-time 20 "$UI_URL$ASSET" 2>/dev/null; then
  pass "the Hermes bundle loads ($ASSET)"
else
  fail "the Hermes bundle '${ASSET:-none found}' did not load"
fi

# Signed out, the session endpoint must say 401 (the shell shows its sign-in
# screen on that) rather than 500 or a proxy error page.
SESSION=$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 "$UI_URL/api/v1/auths/" 2>/dev/null)
case "$SESSION" in
  401) pass "signed-out session check answers 401 (the sign-in screen shows)" ;;
  *)   fail "/api/v1/auths/ answered '$SESSION' signed out — expected 401" ;;
esac

# The bare address and old OWUI and /hermes/ addresses (bookmarks, /auth,
# /c/<id>) must land on the shell, not 404.
for old in / /auth /c/old-chat /hermes/; do
  GOT=$(curl -s -o /dev/null -w '%{http_code} %{redirect_url}' --max-time 20 "$UI_URL$old" 2>/dev/null)
  case "$GOT" in
    30[12]*"$UI_URL/harvis/") pass "$old redirects to /harvis/" ;;
    *)                        fail "$old answered '$GOT' — expected a redirect to /harvis/" ;;
  esac
done

# ------------------------------------------------------- the no-engine case

say "Check 2c — no model provider, and Harvis is honest about it"

PORTS_CLEAR=1
for port in 11434 1234 8080 8000; do
  if curl -fsS --max-time 2 "http://localhost:${port}" -o /dev/null 2>/dev/null; then
    fail "something is listening on :${port} — stop it, this check needs NO provider"
    PORTS_CLEAR=0
  fi
done
[ "$PORTS_CLEAR" -eq 1 ] && pass "no model server on :11434 :1234 :8080 :8000"

# The container must be able to resolve the host even when nothing is there to
# answer. If this fails, provider detection would break the moment the user
# DOES start a model server, and the failure would look like "Harvis can't see
# my Ollama" rather than a DNS problem.
if docker compose exec -T backend getent hosts host.docker.internal >/dev/null 2>&1; then
  pass "backend resolves host.docker.internal (extra_hosts wired)"
else
  fail "backend cannot resolve host.docker.internal — extra_hosts missing on this service"
fi

MODELS=$(curl -fsS --max-time 30 "$UI_URL/api/ollama-models" 2>/dev/null)
if [ -n "$MODELS" ]; then
  pass "/api/ollama-models answered 200 rather than erroring"
  note "body: $(printf '%s' "$MODELS" | head -c 200)"
else
  fail "/api/ollama-models did not answer — the API should degrade, not fall over"
fi

# Two different faults were sharing one assertion. The old grep matched
# "traceback" OR "unhandled", so a routine `unhandled RPC <method>` warning from
# the Hermes facade reported itself as "backend logs contain a traceback" — a
# real finding wearing the wrong name, which is how it went unread. Split.
LOGS=$(docker compose logs --tail 400 backend 2>/dev/null)

if printf '%s' "$LOGS" | grep -qi "traceback"; then
  fail "backend logs contain a traceback"
  printf '%s' "$LOGS" | grep -i -A4 "traceback" | head -20 | sed 's/^/        /'
else
  pass "no traceback in the last 400 backend log lines"
fi

# The Hermes UI speaks JSON-RPC to a facade that answers only the methods it
# implements (python_back_end/plugins/hermes_ui/ws.py). Anything else logs an
# unhandled warning and returns -32601 to a UI that asked in earnest, so the
# feature behind it is simply dead on screen. Name the methods.
MISSING_RPC=$(printf '%s' "$LOGS" \
  | grep -o "unhandled RPC [A-Za-z0-9._-]*" \
  | awk '{print $3}' | sort -u | tr '\n' ' ' | sed 's/ $//')
if [ -n "$MISSING_RPC" ]; then
  fail "the Hermes facade does not implement every RPC the UI calls"
  note "unimplemented: $MISSING_RPC"
  note "each one is a -32601 to the UI — the feature behind it cannot work"
else
  pass "no unimplemented RPC calls in the last 400 backend log lines"
fi

# ------------------------------------------------------------- human steps

say "Two things this script cannot judge — look at them yourself"

cat <<'EOF'
  1. Open the UI and try to pick a model.

     The bar to clear is that Harvis SAYS no model provider was found. An
     empty dropdown with no explanation is a FAIL, not a pass.

     Be skeptical here. /api/ollama-models builds its list by contacting each
     backend in turn and swallowing every connection error as a warning
     (python_back_end/main.py:7132, :7147, :7164), so "nothing reachable"
     and "reachable but no models installed" produce the same empty list.
     This repo has a documented history of that exact shape — an error
     rendered as an empty state. If the picker is just empty, the honest
     message is missing and that is a real finding worth reporting.

  2. Re-read what ./install.sh printed.

     It should have said, near the end:
       "Model server: none detected — Harvis will start and report no provider."
     (install.sh:512, with the WARN row at :197.)

     And it should have asked you NOTHING. A single prompt is a failure of
     "one command, no questions asked."
EOF

say "Verdict"
if [ "$FAILED" -eq 0 ]; then
  printf '  \033[32mAll automated checks passed.\033[0m Record the footprint table above.\n\n'
  exit 0
fi
printf '  \033[31mOne or more checks failed.\033[0m See the FAIL lines above.\n\n'
exit 1
