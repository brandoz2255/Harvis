---
name: harvis-terminal
description: >
  Per-workspace dedicated Linux terminal — run any shell command in your
  own isolated Docker container that persists across this workspace's
  lifetime. Use this when the regular `exec` tool is too constrained,
  when you need to install a package, run a multi-step script, or keep
  state (cwd, env, files) across multiple commands.
metadata:
  openclaw:
    emoji: "\U0001f4bb"
    always: false
---

# Harvis Workspace Terminal

You have your own dedicated Linux box for this workspace. It's a fresh
`ubuntu:24.04` container that comes up on first use, lives until the
workspace is done (or 30 min idle), and gets cleanly torn down after.

Use this when the built-in `exec` tool isn't enough — when you need to:
- Install packages (`apt install jq`, `pip install requests`, etc.)
- Persist state across commands (`cd`, env vars, files in `/workspace`)
- Run multi-step scripts that build on each other
- Compile/run code in a real Linux environment

## How to call it — USE THE `/raw` ENDPOINT

The terminal lives at the laptop backend. There are two endpoints; **use
`/raw` whenever possible** because it avoids the JSON-quote-inside-shell
escape hell that breaks `/exec`.

### `/raw` (recommended) — command goes in the raw request body

```bash
curl -sS -X POST --data-binary 'YOUR SHELL COMMAND HERE' \
  http://backend:8000/api/tools/terminal/<workspace_id>/raw
```

That's it. **No JSON. No nested quoting.** Whatever you put after
`--data-binary '...'` is run verbatim as a shell command in your container.
Optional timeout: append `?timeout_s=120` to the URL.

### `/exec` (only if you really need JSON)

```bash
curl -sS -X POST -H 'Content-Type: application/json' \
  -d '{"cmd":"echo hi"}' \
  http://backend:8000/api/tools/terminal/<workspace_id>/exec
```

**Avoid `/exec` when your command contains double-quotes or `$(...)`** —
the layered escaping (JSON inside shell single-quotes inside a docker exec)
is treacherous and frequently produces "Expecting , delimiter" errors.
If you do hit a JSON 422 from `/exec`, **switch to `/raw` immediately** —
do NOT retry the same broken command.

Response is JSON:

```json
{
  "stdout": "...",
  "stderr": "...",
  "exit_code": 0,
  "duration_ms": 142,
  "truncated": false,
  "container": "harvis-ws-term-<id>"
}
```

## The three-step pattern

1. **Run a probe** to see what's available: `which python3 jq curl awk`
2. **Install whatever's missing** (apt is preconfigured): `apt-get update && apt-get install -y jq`
3. **Do the actual work** — and parse the JSON `stdout` to give the user a real answer.

## Examples

### Count unique IPs in an attached log (file inlined into your brief)

```bash
# Use a heredoc with single-quoted EOF to write the inlined content verbatim:
curl -sS -X POST --data-binary @- http://backend:8000/api/tools/terminal/<workspace_id>/raw <<'CMD'
cat > /workspace/access.log <<'EOF'
LOG CONTENT PASTED VERBATIM HERE
EOF
echo "wrote $(wc -l < /workspace/access.log) lines"
CMD

# Then process — the file persists across calls:
curl -sS -X POST --data-binary "awk '{print \$1}' /workspace/access.log | sort -u | wc -l" \
  http://backend:8000/api/tools/terminal/<workspace_id>/raw
```

### Install + use a tool not on the base image

```bash
curl -sS -X POST --data-binary 'command -v jq >/dev/null || apt-get update -qq && apt-get install -y -qq jq; echo ready' \
  http://backend:8000/api/tools/terminal/<workspace_id>/raw

curl -sS -X POST --data-binary 'jq .firmware_updates[0].version /workspace/firmware_log.json' \
  http://backend:8000/api/tools/terminal/<workspace_id>/raw
```

### The original test (uname / id / date)

```bash
curl -sS -X POST --data-binary 'uname -a && id' \
  http://backend:8000/api/tools/terminal/<workspace_id>/raw

curl -sS -X POST --data-binary 'apt list --installed 2>/dev/null | wc -l' \
  http://backend:8000/api/tools/terminal/<workspace_id>/raw

curl -sS -X POST --data-binary "echo \"harvis terminal works at \$(date -u +%Y-%m-%dT%H:%M:%SZ)\"" \
  http://backend:8000/api/tools/terminal/<workspace_id>/raw
```

## Limits

- Default per-command timeout: **30 s** (override with `timeout_s` in the JSON body, max 600 s)
- Output cap: **64 KB** per stream — exceeding produces `truncated: true`
- Resource cap: **1 CPU, 512 MB RAM**
- Persistent dir: `/workspace` (cwd by default)
- Network: only the internal Docker network (no public internet from the
  container itself — fetch external content via the existing `harvis-research`
  / `harvis-file` paths through the backend instead)

## When NOT to use

- If a single `exec` tool call is enough (no state, no install) — just use `exec` and skip the HTTP overhead
- For small inlined-file tasks: read the inlined block from your brief
  directly. Only escalate to the terminal when you need a real shell.
