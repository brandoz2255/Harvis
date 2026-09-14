# Handoff — 2026-09-02

FreeToken session, continuing from the 2026-08-31 spike (`~/freetoken-spike/results.md`)
and yesterday's three-layer plan. **Layer 1 and Layer 2 are built, deployed and verified
live in the UI. Layer 3 is logged, not built. Committed on `fixes` (COMMIT_HASH), not pushed.**

Second half of the day (the "it messes up the chat rendering" follow-up) is at the
bottom: **Afternoon — what the first real run showed, and what changed**.

Headline: **Harvis now chats through a 35B-parameter model on the laptop's 8 GB card,
picked from the normal model picker, with the "Thought for N seconds" block working —
and the mechanism that does it is a general "inference nodes" plugin, so the next box
(desktop, lab machine, the 4090) is a one-line registration.**

Reference: `docs/inference-nodes.md` is the how-it-works document. This file is the
state of the world.

---

## Where things stand

| Branch | State |
|---|---|
| `fixes` | The running stack's checkout. This session's files are committed as COMMIT_HASH. Earlier uncommitted work (`discord_workspace_bot.py`, `chat_completion.py`, `fast_path.py`, `orchestration/{authz,runner}.py`, `agent_reach/provenance.py`, `owui_compat/system_prompt.py`, `test_reach_egress_guard.py`, `test_system_prompt_core.py`) was **not** touched and is still uncommitted. |
| `harvis1.3`, `main` | untouched |

Files from this session:

```
 M docker-compose.yaml                         forwards HARVIS_INFERENCE_NODES, HARVIS_NODE_THINKING
 M docker-compose.override.yml (gitignored)    registers the laptop FreeToken node
 M python_back_end/main.py                     node models in list_models; router mount; attach at startup; migration 016 in the tuple
 M python_back_end/workspace/model_proxy.py    _resolve_route asks nodes first; node bodies skip Ollama munging; 503 on unknown
?? python_back_end/plugins/inference_nodes/    plugin.yaml, types, registry, store, probe, policy, provision, routes
?? python_back_end/migrations/016_inference_nodes.sql
?? python_back_end/tests/test_inference_nodes.py
?? scripts/freetoken/                          serve.sh (+FT_MAX_PREFILL), idle-stop.sh, units, env example, installer
?? docs/inference-nodes.md, docs/handoffs/2026-09-02-freetoken-inference-nodes.md
 M python_back_end/owui_compat/router.py       title/tag generation falls back to a node when Ollama fails
 M python_back_end/workspace/orchestration/model_router.py   node body shaping for side calls (reach classifier)
 M front_end/owui/src/lib/utils/marked/extension.ts          tokenize the unclosed <details type="reasoning"> while streaming
 M front_end/owui/src/lib/components/chat/Messages/ResponseMessage.svelte   typewriter lets the open reasoning block through
    plugins/inference_nodes/taskgen.py        (new) node_complete(): thinking-off short completion on the first reachable node
    plugins/inference_nodes/probe.py          kv_capacity(), ctx_for(): cap ctx to the node's KV cache
    plugins/inference_nodes/policy.py         estimate_prompt_tokens(), headroom(): thinking off when the cache has no room
```

Host-side (not in the repo): `~/.config/freetoken.env`, `~/.config/systemd/user/
freetoken.service` + idle units, `~/.local/bin/freetoken-{serve,idle-stop}`;
`~/freetoken-spike/restore-stacks.sh` now starts databases before backends.

---

## What was verified, and how

All against the live stack on `localhost:9000`, backend recreated with
`docker compose up -d backend` (bind-mounted code, no image rebuild).

| Check | Result |
|---|---|
| Plugin + host tests in the container | **26 passed** (13 new, 13 existing `test_ollama_hosts.py`) |
| Picker (`/api/models/native`) | log: `Added 1 models from inference node freetoken`; UI shows `Qwen3.6-35B-A3B-NVFP4 · 256K ctx` under Local with label *FreeToken (laptop 5070)* |
| Plain chat via `/v1/chat/completions` (proxy route, in-container) | routed to node; 576 completion tokens, 2,328 chars of `reasoning_content`, correct one-sentence answer |
| Streaming | reasoning deltas stream through; an 800-token cap was consumed entirely by thinking (→ policy threshold raised to 1024) |
| Tool-call request | `auto` policy set `enable_thinking=false`; clean `get_weather({"city":"Boston"})` in 26 tokens, 0 reasoning |
| **Real chat from the signed-in UI (user `cisco`, Chrome)** | badge *Qwen3.6-35B-A3B-NVFP4 (FreeToken) · laptop 5070*; **"Thought for 32 seconds"** collapsible; answer streamed; footer `1.9k / 262k · 1%`; backend log shows the node route; FreeToken journal shows the POST 200 |
| systemd user service | `freetoken.service` active, bound `172.17.0.1:1919` only, healthy 33 s after start; idle timer installed and **disabled** |

Not verified: the admin POST/DELETE endpoints against a real admin session (exercised
only by code review), the provision script on a second machine (it is generated text),
`FT_MEMORY_RATIO=0.8`, and the hybrid-graphics switch (needs a reboot).

---

## The one deviation from the plan, and why

The plan said "point `HARVIS_LLM_BASE_URL` at FreeToken". Doing that would have broken
the picker, task detection and the default-model resolver at once, because all three
assume Ollama's native `/api/tags` / `/api/generate`, which FreeToken does not serve.
Instead Ollama stays as `OLLAMA_URL` and FreeToken is the first **inference node**:
`model_proxy._resolve_route` asks the node registry before anything else and returns
an OpenAI-dialect route when a node reports the model. Layer 1 is therefore delivered
*through* the Layer 2 mechanism rather than before it. Every existing lane is
untouched when no node is configured.

---

## Things that bit, so they do not bite twice

* **`pkill -f "[f]t serve"` killed my own shell** because a later `echo` in the same
  command contained the words. Use `pkill -f "venv/bin/[f]t"` and keep the phrase out
  of the rest of the line.
* **`docker compose restart backend` does not re-read compose env.** New variables need
  `docker compose up -d backend` (recreate).
* **Ollama returns 500 while FreeToken holds the card.** 6.2 GB of 8 GB is FreeToken;
  the title-model load fails and Harvis falls back to a heuristic title. Documented
  with options in `docs/inference-nodes.md` ("Sharing one 8 GB GPU").
* **`migrations/` is baked into the image**, so the container logs "Migration file
  missing: 016" — harmless, the store creates the table on first use.
* The earlier `restore-stacks.sh` started `harvis-backend` before `pgsql-db`
  alphabetically, which was the sign-in database error from 2026-09-01. Fixed.
* Pre-existing and unrelated: startup logs `Core schema (all_schemas_safe.sql) did not
  apply: cannot drop columns from view` on every boot.

---

## Next

1. ~~Commit~~ — done (COMMIT_HASH on `fixes`). Not pushed; `main`/`harvis1.3` untouched.
2. Decide the GPU split: `FT_MEMORY_RATIO` is 0.90 now (measured, see the afternoon
   section); going lower to fit a small Ollama title model is untested, and
   `sudo system76-power graphics hybrid` + reboot is still on hold per you.
3. Second machine: run the provision script on the desktop/lab box behind a Caddy
   token, register it with a lower `priority`.
4. Lazy start (`freetoken.socket` + `systemd-socket-proxyd`) so the idle timer can be
   turned on without the model vanishing from the picker until someone starts it.
5. Still open from before: rotate the Kimi key and `OPENCLAW_GATEWAY_TOKEN` (plaintext
   in `workspace_events` run `67155356`, seq 14) — deferred by you, still true.

## Layer 3 — logged

Kubernetes + the RTX 4090: see the last section of `docs/inference-nodes.md`. Summary:
FreeToken as a Deployment on a PVC with `--max-running-requests 4–8`, a token-checking
front (FreeToken has no auth), per-user quotas at the Harvis layer, registered as a
node with a lower priority than the laptop so the cluster wins when up; then prefix/KV
sharing, model-swap scheduling, multi-GPU, scraping `/v1/stats`. The csusb.edu
cluster's outbound-DNS block will hit the checkpoint download first.

---

## Afternoon — what the first real run showed, and what changed

### The run you asked me to document (4:14 PM, "tell me why lebron is goated")

The chat worked, but everything around it showed the seams:

| Stage | What happened |
|---|---|
| task detection | Ollama `/api/chat` → HTTP 500 (card held by FreeToken) → heuristic, harmless |
| reach classifier | one side request to FreeToken with the chat model: 237 prompt tokens, **~560 completion tokens of thinking, 17 s** — for a yes/no |
| main request | 859 prompt tokens; FreeToken clipped `max_tokens` to 3,239 (`4098 − 859`); 999 completion tokens; UI showed *Thought for 21 seconds*, then ~27 s of streaming at ~35 tok/s; ~1 min wall |
| rendering | during the 21 s of thinking the bubble was a bare cursor dot — the unclosed reasoning block was not tokenized |
| title | Ollama 500 → heuristic: the sidebar said *"In two sentences, why does a"* |
| footer | `1.9k / 262k`, which is a lie: the KV cache was 4,098 tokens |

FreeToken counters after that run (7 requests since start): prompt 6,463 / completion
3,391 tokens, p95 29.1 s, TTFT mean 2.27 s, decode mean 33.9 tok/s over 36 samples,
VRAM 6.75 GB.

### Root causes, in the order they were found

1. **Unclosed `<details type="reasoning" done="false">` rendered as nothing** — two
   gates: `extension.ts` `detailsTokenizer` bailed without a closing tag, and the
   typewriter in `ResponseMessage.svelte` holds any `<details` until `</details>`
   (right for tool cards, wrong for reasoning). Both fixed; the OWUI bundle in
   `front_end/owui/build` was rebuilt on the host (`npx vite build`, FreeToken
   stopped for RAM; nginx restarted because the bind mount went stale — 403s
   otherwise). Verified 2026-09-02 evening, after the session that built it hit its
   limit mid-check: the bundle nginx serves at `:9000` is byte-identical to
   `front_end/owui/build` (index and both fix chunks, `reasoningOpen` and the
   `done==="false"` tokenizer path present), and a live stream straight from the
   node returned 127 `reasoning_content` deltas before content. The 32 backend
   tests still pass. The one thing not re-done is the visual click-through in a
   browser (the Chrome automation from the original session was gone); if the
   Thinking card still misbehaves live, suspect a third gate in
   `MarkdownTokens.svelte`/`Collapsible.svelte`, not these two.
2. **The reach classifier thought for 17 s** because `ModelRouter.complete` bypassed
   the node policy. Fixed: it now shapes the body like the proxy does. Verified ~1 s,
   24 tokens.
3. **Titles fell back to heuristics.** Fixed with `taskgen.node_complete` behind the
   Ollama attempt. Verified twice (*Pick And Roll Origin*, *Jump Shot Invention*).
4. **The KV cache was 4,098 tokens.** A grounded turn (sources injected, 3,260-token
   prompt) left 838 tokens, thinking used them all, the answer was empty with only a
   Sources footer. Two fixes: the policy now turns thinking off when the probed cache
   leaves ≤ 1024 tokens (verified: `body shaped (thinking=False)` in the log), and the
   prober caps `ctx` to the cache so the picker/meter show `16K`.
5. **Then the prompt outgrew the cache entirely** (`4310 > 4098`) — no policy can fix
   that, so `FT_KV_RESERVE` went 4096 → 16384 (0.31 GB, ten expert slots).
6. **Then the first 4.3k-token prefill OOM-killed FreeToken's scheduler**
   (`gdn_prefill_chunk_fla`, 41 MB free). The API process kept the port open with
   nothing behind it; systemd saw a healthy unit. `FT_MEMORY_RATIO` 0.95 → 0.90 and a
   new `FT_MAX_PREFILL=2048` (`--max-prefill-length`) fixed it: 0.43 GB free after
   CUDA graphs, a 6,628-token prompt prefilled in 8.8 s.

### Verified after the changes (4:46 PM, "who invented the jump shot in basketball")

Reach fired (gate=maybe, 5 sources), the chat streamed a cited answer naming Kenny
Sailors with Cooper/Fulks/Smawley/Palmer as co-pioneers, *Thought for 20 seconds*,
5.3K prompt tokens, 49 s wall, footer **`5.3k / 16k · 32%`**, sidebar title **Jump
Shot Invention** generated by the node while Ollama 500'd. FreeToken after four
requests: prompt 11,508 / completion 932 tokens, p95 33.6 s, TTFT mean 5.2 s (cold
MoE cache after the restart), VRAM 5.9 GB. Tests: **32 passed** in the container.

Cost of the new settings: expert slots 1,457 → 1,165 (more PCIe fetches on a cold
cache). Decode speed after warm-up not yet re-measured — that is the next thing to
look at if chats feel slower than this morning's ~34 tok/s.

