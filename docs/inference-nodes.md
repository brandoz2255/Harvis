# Inference nodes

Other model servers Harvis can send a chat to. The first one is **FreeToken** on this
laptop's RTX 5070, serving Qwen3.6-35B-A3B (NVFP4) — a 35B-parameter model that an
8 GB card cannot hold in any other runtime we have tried. The same mechanism registers
a desktop, a lab box, or a rented GPU running FreeToken, vLLM, SGLang or llama-server.

Code: `python_back_end/plugins/inference_nodes/`. Scripts: `scripts/freetoken/`.
Handoff with the verification record: `docs/handoffs/2026-09-02-freetoken-inference-nodes.md`.

---

## Why a plugin, and not `HARVIS_LLM_BASE_URL`

The obvious move — point Harvis's Ollama URL at FreeToken — breaks three things at
once, because everything behind `OLLAMA_URL` assumes Ollama's *native* API:

| Lane | Needs | FreeToken has |
|---|---|---|
| Model picker (`/api/models/native`) | `/api/tags` | `/v1/models` only |
| Task detection, title/tag generation | `/api/generate`, small local models | one big model, no `/api/generate` |
| Default-model resolver (`plugins/models/resolver.py`) | `/api/tags` to verify a saved pick | — |

So Ollama stays exactly where it is, and a node is **an additional, OpenAI-dialect
server that `model_proxy` asks first**. Nothing that works today changes when no node
is configured: every entry point is a no-op on an empty node list.

---

## How a chat reaches a node

```
picker  → /api/models/native lists node models  (provider "inference-node", host = node name)
chat    → owui_compat → model_proxy.execute_chat_completion
            → _resolve_route(model)
                1. inference node that reports this model     ← new, first
                2. OpenClaw config / cloud facades / Ollama    ← unchanged
            → body shaped for the node (policy.py)
            → POST {node}/v1/chat/completions, streamed back unchanged
```

* **Reachability is honest.** The prober keeps the same *absent* / *unknown* split as
  `owui_compat/ollama_hosts.py`: a node that answered and does not have the model is
  *absent* and routing falls through; a node that did **not** answer but served the
  model last time is *unknown*, and chat returns **503 "node X is unreachable"** rather
  than handing the name to Ollama and reporting "model not found" for a box that is
  merely asleep. The picker keeps the model, greyed out, with the node's error.
* **Precedence.** A node that reports a model wins over Ollama for that name. Two nodes
  reporting the same model: lowest `priority` wins, then name.
* **Streaming needs no changes.** FreeToken emits `delta.reasoning_content`; the
  frontend already reads `delta.reasoning ?? delta.reasoning_content` (since the
  2026-08-19 "Thinking…" fix), so the collapsible *Thought for N seconds* block works.

---

## Configuration

### Environment (operator, static)

```yaml
# docker-compose.override.yml → backend.environment
HARVIS_INFERENCE_NODES: "freetoken=http://host.docker.internal:1919|dialect=openai|label=FreeToken (laptop 5070)|hw=RTX 5070 Laptop 8GB"
HARVIS_NODE_THINKING: auto          # auto | on | off
```

Shorthand grammar: entries separated by `,`; attributes by `|`; the first attribute is
always `name=url`. Attributes: `dialect` (`openai` default, or `ollama`), `label`,
`hw`/`hardware`, `priority` (default 100, lower wins), `enabled`, `token_env`.
Anything containing a comma goes in the JSON form:

```yaml
HARVIS_INFERENCE_NODES: '[{"name":"rig","base_url":"http://192.168.5.58:1919","label":"Desktop 5080","token_env":"RIG_NODE_TOKEN"}]'
```

`token_env` names the **variable** holding a bearer token; the token itself never
goes in this string, so it stays out of `docker inspect` and out of git. A trailing
`/v1` on a URL is stripped.

Other knobs: `HARVIS_NODE_PROBE_TTL_S` (10), `HARVIS_NODE_PROBE_TIMEOUT_S` (4),
`HARVIS_NODE_THINKING_MIN_TOKENS` (1024, see below).

### Database (admin API, dynamic)

Admins can register nodes without a restart. Rows live in `inference_nodes`
(migration `016_inference_nodes.sql`; the store also creates the table on first use,
because `migrations/` is baked into the image and the running container predates
016). A DB node overrides an env node with the same name. Tokens are Fernet-encrypted
with `main.encrypt_api_key`, the same path SSH credentials take, and are never returned.

| Method | Path | Who | Does |
|---|---|---|---|
| GET | `/api/inference-nodes` | signed in | every node's state: reachable, models, ctx, `/health`, `/v1/stats` |
| POST | `/api/inference-nodes/refresh` | signed in | re-probe now (the picker's refresh) |
| GET | `/api/inference-nodes/{name}/stats` | signed in | fresh `/health` + `/v1/stats` for one node |
| GET | `/api/inference-nodes/provision-script?name=&model=&port=&host=` | signed in | bash bootstrap for a new FreeToken box (text/plain) |
| POST | `/api/inference-nodes` | **admin** | upsert `{name, base_url, dialect, label, token?, hardware, enabled, priority}` — `token` omitted keeps the stored one, `""` clears it |
| DELETE | `/api/inference-nodes/{name}` | **admin** | remove a DB node |

Admin = `owui_compat.authz.is_admin`, same gate as the rest of the compat layer.

---

## Thinking policy

Qwen3.6 thinks before it answers — in the verified run, **2,328 characters of
reasoning for a one-sentence answer**, and a request capped at 800 tokens spent all
800 thinking and produced no answer at all. Thinking is wanted where the UI shows it
and wasted where nobody reads it. `HARVIS_NODE_THINKING`:

| Mode | Behaviour |
|---|---|
| `auto` (default) | **off** when the request carries `tools`/`functions`, when `max_tokens` ≤ `HARVIS_NODE_THINKING_MIN_TOKENS` (1024), when `metadata.task` is set, or when the node's probed KV cache leaves ≤ 1024 tokens after the estimated prompt (`HARVIS_NODE_CHARS_PER_TOKEN`, default 3.5 chars/token); otherwise the model's own default (Qwen3.6: on) |
| `on` / `off` | force it |

A caller that already set `chat_template_kwargs.enable_thinking` (or `thinking`,
`thinking_mode`, `reasoning_effort`) is never overridden. The switch travels as
`chat_template_kwargs: {"enable_thinking": bool}`, which FreeToken reads
(`server/model_meta.py`) and vLLM/SGLang honour for the same family. The policy also
drops Ollama-only keys (`options`, `keep_alive`, `format`, …) — FreeToken ignores
them, vLLM would reject them — and maps `max_completion_tokens` to `max_tokens`.

Verified: a tool-call request routed with thinking off produced a clean
`get_weather({"city":"Boston"})` call in 26 completion tokens and zero reasoning.

The same shaping runs for **every** request the backend sends to a node, not only
the chat proxy: `ModelRouter.complete` (used by the reach classifier, the hedge
rescue and other side calls) asks `node_for_url` and applies `shape_body_for_node`.
Before that, the reach classifier — a 600-token yes/no call — thought for 17 s
(~560 tokens) in front of every FreeToken chat; now it answers in ~1 s and 24 tokens.

### The real context is the KV cache, not 262K

FreeToken's `/v1/models` reports the model's `context_length` (262,144). On an 8 GB
card the usable context is whatever `--kv-reserve-tokens` left room for:
`/v1/stats` → `kv.total_pages × page_size`. The prober reads that and caps the
model's `ctx` to it, so the picker says **`16K ctx`** and the usage meter says
`5.3k / 16k` instead of `/ 262k`. Two consequences:

* `kv` is `null` in `/v1/stats` until the node has served one request, so the first
  probe after a restart still shows 256K. **Refresh Models** after the first chat.
* FreeToken clips `max_tokens` to `cache − prompt` (journal: `Adjust max_tokens to N`)
  and rejects a prompt larger than the cache outright (`prompt is too long: 4310
  tokens > 4098 maximum`). A grounded reach turn injects ~3,300 tokens of sources,
  which is why the cache moved from 4,096 to 16,384 tokens (below).

---

## FreeToken on this laptop

### Service

FreeToken runs as a **systemd user service**, not a `nohup` in a terminal.

```
scripts/freetoken/
  serve.sh                 env-driven launcher (installed as ~/.local/bin/freetoken-serve)
  idle-stop.sh             stops the service after FT_IDLE_MIN idle minutes (opt-in)
  freetoken.service        the unit; Restart=on-failure, Nice=10, TimeoutStartSec=300
  freetoken-idle.service / .timer   5-minute idle check (installed, disabled by default)
  freetoken.env.example    → copy to ~/.config/freetoken.env
  install-user-units.sh    idempotent installer; --idle also enables the timer
```

```bash
systemctl --user status freetoken          # state
journalctl --user -u freetoken -f          # logs (model load ≈ 35–40 s)
systemctl --user stop freetoken            # give the GPU back
curl http://172.17.0.1:1919/health         # {"status":"ok", ...}
loginctl enable-linger $USER               # keep it running after logout (off today)
```

`~/.config/freetoken.env` on this machine: `FT_HOME=/home/ommblitz/freetoken-spike`,
`FT_MODEL=models/Qwen3.6-35B-A3B-NVFP4`, `FT_HOST=172.17.0.1`, `FT_MAX_RUNNING=2`,
`FT_KV_RESERVE=16384`, `FT_MEMORY_RATIO=0.90`, `FT_MOE_THREADS=6`, `FT_MAX_PREFILL=2048`.
How those were arrived at, all on 2026-09-02 and all with `systemctl --user restart
freetoken` (no reboot):

| Setting | Effect measured in the journal |
|---|---|
| `FT_KV_RESERVE=4096` (spike default) | 4,098-token cache, K+V 0.08 GB, 1,457 expert slots. A grounded chat (prompt 3,260) had 838 tokens left and thinking ate them: empty answer. |
| `FT_KV_RESERVE=16384` | 16,453-token cache for **0.31 GB** — this GDN-hybrid model keeps ~20 KB/token, so the bigger cache cost 10 expert slots (1,447). |
| …with `FT_MEMORY_RATIO=0.95` | 0.28 GB free after init. The first 4,300-token prefill hit `torch.OutOfMemoryError` in `gdn_prefill_chunk_fla`; the scheduler died and the API kept answering `/health` with nothing behind it. |
| `FT_MEMORY_RATIO=0.90` + `FT_MAX_PREFILL=2048` | 1,165 expert slots, 0.43 GB free after CUDA graphs; a 6,628-token prompt prefilled in 8.8 s, a 5.3k grounded chat answered with citations. |

`FT_MAX_PREFILL` is `--max-prefill-length`, the chunk size the prefill kernels get
scratch memory for; 8,192 (FreeToken's default) is what blew up. The MoE cache is
`--moe-cache-auto`: it fills whatever the ratio leaves after the KV floor, so raising
the KV reserve is nearly free and lowering the ratio is what actually buys headroom.

### Where it listens, and why

FreeToken **has no authentication**. On a campus network that rules out `0.0.0.0`.
It binds **`172.17.0.1`, the Docker bridge**: the Harvis container reaches it as
`host.docker.internal` (which resolves to that address), the laptop reaches it at
`172.17.0.1:1919`, and no other host on the LAN can see the port. Do not change
`FT_HOST` to `0.0.0.0` without putting a token proxy in front (below).

### Sharing one 8 GB GPU with Ollama — read this

While FreeToken is up it holds ~6–6.7 GB of the 8 GB card. **Ollama cannot load
anything beside it**: the title-generation call to the local Ollama `/api/generate`
returns HTTP 500, and so does task detection's `/api/chat`.

**Titles and tags now fall back to the node.** `owui_compat/router.py` tries Ollama
first (unchanged), and when that yields nothing it calls
`plugins.inference_nodes.node_complete` (`taskgen.py`): the first reachable
OpenAI-dialect node, thinking forced off, 24 tokens for a title, temperature 0.
Verified: chats titled *Pick And Roll Origin* and *Jump Shot Invention* while Ollama
was returning 500. `workspace/task_detector.py` still goes heuristic — it wants
Ollama's native `/api/chat` and nothing else consumes its result badly.

Options for getting a small Ollama model back beside FreeToken, in cost order:

1. Accept it: chat on the 35B model, node-generated titles. This is today's state.
2. Lower `FT_MEMORY_RATIO` further (0.90 today; each 0.05 is ~0.37 GB, roughly 110
   expert slots). Untested below 0.90; llama3.1:8b needs ~5 GB, so this alone will
   not fit it — a 1–2B title model might.
3. Move the desktop off the NVIDIA card (next section) — buys ~350 MB today.
4. Second machine for FreeToken (below) — the real answer.

### Getting the desktop off the 5070 (iGPU offload)

This laptop also has a Radeon 860M. `system76-power graphics` currently says
**`nvidia`**, so every GPU-accelerated desktop process (Brave, Claude Desktop, the
COSMIC shell — ~350 MB in `nvidia-smi`) rents VRAM the model wants. Switching to hybrid
puts the desktop on the iGPU and leaves the 5070 for CUDA:

```bash
sudo system76-power graphics hybrid     # then reboot
nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv
```

After the reboot only `freetoken-serve`'s python should appear. If a specific app
still needs the discrete card, launch it with `__NV_PRIME_RENDER_OFFLOAD=1
__GLX_VENDOR_LIBRARY_NAME=nvidia app`. Not done in this session — it needs a reboot
and it is your call on a laptop you are using.

---

## Adding a second machine

1. `GET /api/inference-nodes/provision-script?name=rig&host=0.0.0.0` returns a bash
   script that reproduces the laptop install: uv venv, `freetoken` from PyPI, the NVFP4
   checkpoint from Hugging Face (~22 GB), a systemd user unit, a health wait. Read it
   before running it — it says at the top what it will listen on. Run it over an
   existing SSH host with the `remote/ssh_manager.py` exec endpoint, or paste it in.
2. **Put a token in front.** FreeToken has no auth, so on anything but a private
   link put Caddy on the box (the script prints a Caddyfile that answers 401 without
   `Authorization: Bearer …`) and register the Caddy port with `token_env=RIG_NODE_TOKEN`.
   Or reach it over Tailscale/WireGuard and bind `127.0.0.1` on the tailnet interface.
3. Register it: env shorthand in the override, or `POST /api/inference-nodes` as admin.
   The picker shows `Qwen3.6-35B-A3B-NVFP4 (Desktop 5080)` beside the laptop's entry
   when both are up, and chat goes to the lower `priority`.

Nothing in this document scans the network; a node is only ever the URL you typed.

---

## Limits and known gaps

* **No lazy start.** A stopped service shows as unreachable until
  `systemctl --user start freetoken`; the container cannot start host units. The
  systemd recipe for it is `freetoken.socket` + `systemd-socket-proxyd` on
  `172.17.0.1:1919` fronting FreeToken on `127.0.0.1:1920`, at the cost of a 40 s
  first request. Logged, not built. The idle-stop timer is therefore **opt-in**
  (`install-user-units.sh --idle`).
* **Resolver lanes stay Ollama-only.** `resolve_default_local_model` and the
  task-detection lanes verify against `/api/tags` and will never pick a node model
  as a default. Intentional for now — those lanes want a small fast model.
* **`migrations/016_inference_nodes.sql` is not in the running image** (`migrations/`
  is baked, not bind-mounted). The store self-heals with `CREATE TABLE IF NOT EXISTS`;
  the next image build carries the file.
* **`max_tokens` under ~1000 with thinking on gets you thinking and no answer.**
  `auto` turns thinking off below 1024; raise `HARVIS_NODE_THINKING_MIN_TOKENS` if a
  lane sends larger budgets and still starves.
* **Two requests per chat turn hit the node** in the verified run: the chat itself and
  one ~960-prompt-token side request from a Harvis lane that uses the selected model.
  Both returned 200; worth a look if the node's `requests.completed` counter matters.
* One user service, one model, `--max-running-requests 2`. Concurrency beyond that
  queues inside FreeToken.
* **A dead scheduler looks alive.** When the GPU worker OOMs, FreeToken's API process
  logs `Backend worker is gone … stopping the API server` but keeps the port open;
  `/health` returns an empty body, the unit stays `active`, and `Restart=on-failure`
  never fires. Symptom in Harvis: `Inference node freetoken unreachable: ConnectError`
  and the model gone from the picker. Fix: `systemctl --user restart freetoken`.
* **The picker shows 256K until the node has served one request** (`kv` is `null`
  in `/v1/stats` before that). Cosmetic; Refresh Models after the first chat.
* **`/v1/stats.throughput.decode_tps` is not a mean** — it is the last sample. Use the
  `Decode` journal lines or your own timing.

## The live "Thinking…" block in the chat UI

The OWUI frontend streams reasoning as `<details type="reasoning" done="false">` and
closes it with `done="true" duration=N` when the answer starts. The markdown
`detailsTokenizer` (`front_end/owui/src/lib/utils/marked/extension.ts`) returned
nothing for an *unclosed* block, and the typewriter in
`Messages/ResponseMessage.svelte` (`smoothStep`) deliberately holds every `<details`
back until its `</details>` arrives (so tool cards land whole). Together: a 20–30 s
thinking phase rendered as a bare cursor dot and the text appeared only when it
closed. Fixed in both places: an unclosed block with `done="false"` is tokenized as
far as it goes, and the typewriter lets a `<details type="reasoning"` block through
while it is open (tool cards keep the atomic behaviour).

That bundle is **static**: nginx serves `front_end/owui/build` (see
`nginx-harvis.conf`), not the `frontend` compose service (that is the legacy Next
app, profile `legacy`). To ship a change: `cd front_end/owui && npx vite build`
(needs ~6 GB of RAM — stop FreeToken first on this laptop), or clear the build dir and
run the `owui-builder` service. **Then `docker compose restart nginx`**: vite replaces
the `build` directory and the container's bind mount keeps pointing at the deleted
inode — every route returns 403 until nginx is restarted. Then hard-reload the tab.

## Tests

```bash
docker cp python_back_end/tests/test_inference_nodes.py harvis-backend:/app/tests/
docker exec harvis-backend python -m pytest tests/test_inference_nodes.py tests/test_ollama_hosts.py -q
```

19 tests for the plugin (env parsing, spec validation, thinking policy incl. the
KV-headroom rule, KV capacity capping, `node_complete` fallback, absent vs unknown,
priority, URL ownership) plus the 13 existing Ollama-host tests — **32 pass**. The
`plugins/` bind mount is read-only inside the container, so `docker cp` into it
fails; host edits are already live, only the test file needs copying.

---

## Layer 3 — logged for later (not built)

The centralized version: Harvis as one tenant of a shared inference service instead
of the owner of a laptop process. Hardware on the table: an **RTX 4090** (24 GB), a
Kubernetes cluster (the csusb.edu one has the outbound-DNS block documented in
`K8S_DNS_WORKAROUND.md`, which will bite the Hugging Face download and PyPI).

What it would need, roughly in order:

1. FreeToken as a Deployment with the checkpoint on a PVC, `--max-running-requests 4–8`
   (24 GB has room for a real KV budget; the 8 GB laptop is capped at 2), readiness
   probe on `/health`, `nvidia.com/gpu: 1`.
2. A token-checking front (Caddy/Traefik/ingress annotation) — FreeToken has none —
   and per-user quotas at the Harvis layer, since the node cannot tell users apart.
3. Register it as a node with `priority` below the laptop's so the cluster wins when
   up and the laptop is the fallback, which the plugin already does.
4. Prefix/KV sharing across users (FreeToken's cache endpoints exist: `/v1/cache/status`,
   `/v1/cache/rebuild`), model-swap scheduling if more than one checkpoint, multi-GPU
   when the 4090 stops being alone.
5. Metrics: `/v1/stats` already reports p95, TTFT, throughput and VRAM — scrape it.

Nothing above changes the plugin's contract; a cluster node is one more entry.
