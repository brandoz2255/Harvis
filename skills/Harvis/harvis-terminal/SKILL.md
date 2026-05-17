---
name: harvis-terminal
description: 'Use the Harvis dedicated dockerized terminal whenever the user asks for a terminal, shell, bash session, or asks you to "run", "execute", "spawn", or "open" anything that involves a shell. Use it for: "open a terminal", "run X in a terminal", "run a script", "execute this command", multi-step shell flows, hashcat/john runs, decoding pipelines, anything that benefits from a persistent /workspace. The endpoint is auth-gated, on an internal-only docker network, with a named volume that survives container restarts. Do NOT respond by spawning a literal bash subshell (e.g. `bash -lc ''cd … && bash''`) — that opens a non-interactive shell that exits on EOF and returns no output, leading to retry loops. Always call the endpoint instead.'
metadata:
  {
    "openclaw":
      {
        "emoji": "🐚",
        "requires": { "anyBins": ["curl"] }
      }
  }
---

# Harvis Persistent Terminal Skill

## When to use this

Trigger on any of these user phrasings — they are all asking for the same thing:

- "open a terminal", "give me a terminal", "spawn a shell"
- "run X in a terminal", "run a script and execute it"
- "make a script that does Y and run it"
- "decode/decrypt/crack this …" (anything that benefits from a real shell)
- "execute these commands", "bash this", "/workspace/…"

Do **not** trigger on read-only questions about commands ("how do I `grep`?") — those are conversational.

## The endpoint

The Harvis backend exposes a per-workspace dockerized ubuntu container at:

```
POST  http://<host>:8000/api/tools/terminal/<workspace_id>/exec
Header  Authorization: Bearer $OPENCLAW_GATEWAY_TOKEN
Header  Content-Type: application/json
Body    {"cmd":"<shell command>", "workdir":"/workspace", "timeout_s":120}
Resp    {"stdout":"…","stderr":"…","exit_code":0,"duration_ms":N,"truncated":false,"container":"harvis-ws-term-<id>"}
```

`<host>` and `<workspace_id>` are baked into your task brief by the orchestrator. The host is `localhost` when you are running on the developer's box (BYO openclaw) and `backend` when you are the dockerized openclaw. Use whichever appears in your brief.

## How to call it — copy this template

Use the bundled `exec` tool to run `curl`. **One call per shell command.** Example:

```bash
curl -sS -X POST http://localhost:8000/api/tools/terminal/<WSID>/exec \
  -H "Authorization: Bearer $OPENCLAW_GATEWAY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"cmd":"date && uname -a"}'
```

Replace `<WSID>` with the literal workspace_id from your task brief. Do not invent IDs.

## Properties that matter

- **Persistent `/workspace`.** Files you write there survive across calls, across container stops, across redeploys. Only an explicit teardown wipes them.
- **Stateful between calls in the same session.** If you `echo hi > /workspace/a.txt` in one call, the next call's `cat /workspace/a.txt` returns `hi`.
- **No internet.** The container has zero outbound network. Don't try `curl https://example.com` from inside — it will fail. (Public-internet fetches go through the orchestrator's web tools, not this shell.)
- **Resource-limited.** 512 MB RAM, 1 CPU, default 30 s timeout per call (cap 600 s). Pass `"timeout_s":120` for longer.
- **Output truncated at ~64 KB.** Don't `cat` huge files; `head`/`tail`/`grep` first.

## Antipatterns — do NOT do these

| Don't | Why | Do instead |
|---|---|---|
| `bash --noprofile --norc -lc 'cd /…/workspace && bash'` | Opens a non-interactive shell-inside-a-shell that exits immediately on EOF; output is empty, you'll loop retrying. | One concrete command per call: `"cmd":"echo hi > /workspace/a.sh && bash /workspace/a.sh"`. |
| Calling the endpoint with no body or with `{}` as body | Endpoint rejects empty `cmd` with HTTP 400. | Always include a real `cmd`. |
| Calling the endpoint repeatedly with identical args | The orchestrator's loop guard will abort the run after 3 identical calls. | If a call returned no output, change the call — don't repeat it. |
| Hardcoding the workspace_id | Each session has a different ID. | Read `<WSID>` from the task brief. |
| Putting secrets/keys in the `cmd` string | Whole JSON gets logged. | Reference env vars by name. |

## Examples

### "Make a script that prints the date and run it"

```bash
curl -sS -X POST http://localhost:8000/api/tools/terminal/<WSID>/exec \
  -H "Authorization: Bearer $OPENCLAW_GATEWAY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"cmd":"printf \"#!/bin/bash\\ndate\\n\" > /workspace/printdate.sh && chmod +x /workspace/printdate.sh && /workspace/printdate.sh"}'
```

Then report the `stdout` value back to the user.

### "Decode this base64: SGVsbG8gd29ybGQ="

```bash
curl -sS -X POST http://localhost:8000/api/tools/terminal/<WSID>/exec \
  -H "Authorization: Bearer $OPENCLAW_GATEWAY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"cmd":"echo SGVsbG8gd29ybGQ= | base64 -d"}'
```

### "Install hashcat and crack this hash"

```bash
# First call: install (apt won't reach the internet, so use the pre-baked image
# tools that ARE available — or call this via the orchestrator's package skill)
curl -sS -X POST … -d '{"cmd":"which hashcat || apt list --installed 2>/dev/null | grep hash","timeout_s":30}'
```

Network is internal-only — if `apt install` fails, that is expected behavior, not a bug.

## Reporting back

After the call, summarize the result to the user. Lead with the actual `stdout` (or `stderr` on failure), not the JSON wrapper. Example:

> Ran your script. Output:
> ```
> Mon May 11 17:30:00 UTC 2026
> ```
> Exit code 0, took 38 ms. File saved to `/workspace/printdate.sh`.

Do not paste the `{stdout, stderr, exit_code, duration_ms, …}` JSON envelope — the user wants the result, not the wire format.
