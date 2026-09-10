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

The power switch (below) has its own:

| Variable | Default | What it does |
|---|---|---|
| `HARVIS_FREETOKEN_CONTROL_DIR` | `/tmp/harvis-freetoken` | Directory the container and the host agent pass notes in. Must be bind-mounted into the backend. |
| `HARVIS_FREETOKEN_NODE` | `freetoken` | The one node this channel controls. |
| `HARVIS_FREETOKEN_AUTO_WAKE` | `1` | Start a sleeping node when a chat picks a model it serves, instead of 503. |
| `HARVIS_FREETOKEN_WAKE_TIMEOUT_S` | `120` | How long to wait for the checkpoint to load before giving up. |
| `HARVIS_FREETOKEN_AGENT_STALE_S` | `20` | How long the host agent may ignore a request before the UI calls the channel dead. |
| `HARVIS_MOE_SHOW_TIMEOUT_S` / `_CONCURRENCY` | `6` / `4` | Ollama `/api/show` scan for MoE detection. |

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
  autotune.sh              measures this box and writes freetoken.env (--write)
  idle-stop.sh             stops the service after FT_IDLE_MIN idle minutes (opt-in)
  watchdog.sh              restarts a node that is up but not answering (on by default)
  limits.sh                measures the real ceiling of this box (see below)
  freetoken.service        the unit; Restart=on-failure, Nice=10, TimeoutStartSec=300
  freetoken-idle.service / .timer       5-minute idle check (installed, disabled by default)
  freetoken-watchdog.service / .timer   2-minute health check (installed and enabled)
  control-agent.sh         host half of the power switch (installed as ~/.local/bin/freetoken-control-agent)
  freetoken-control.service / .path     watches desired.json; starts/stops the unit on request
  freetoken.env.example    the annotated reference; a real node gets autotune's output
  install-user-units.sh    idempotent installer; --retune re-measures, --idle adds the idle timer
```

```bash
systemctl --user status freetoken          # state
journalctl --user -u freetoken -f          # logs (model load ≈ 35–40 s)
systemctl --user stop freetoken            # give the GPU back
curl http://172.17.0.1:1919/health         # {"status":"ok", ..., "maintenance":"serving"}
journalctl --user -u freetoken-watchdog    # silent unless it had to act
scripts/freetoken/limits.sh                # what this box can actually take
scripts/freetoken/autotune.sh              # what this box should be set to
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

### Watchdog: the node that is up but not answering

`freetoken-watchdog.timer` runs every two minutes and is **on by default**. It exists
for one failure mode, seen for real on 2026-09-02: the scheduler subprocess dies (CUDA
OOM during prefill), the API process keeps the port open, systemd keeps the unit
`active`, and `Restart=on-failure` never fires because nothing exited. Harvis then
routes chats to a node that answers nothing.

Three checks, cheapest first, in `scripts/freetoken/watchdog.sh`:

| Check | Catches |
|---|---|
| `/health` 200 and `maintenance=serving` | process gone, port dead, node still loading (that one is not a failure) |
| a scheduler worker still under the main PID | **the OOM case, within one tick, before anyone sends a request** |
| a real one-token completion, idle only, at most every `FT_WATCHDOG_PROBE_MIN` | anything that leaves the server accepting requests it never finishes |

Two consecutive failures restart the unit; one is a blip and only arms the next check.
Restarts are budgeted at `FT_WATCHDOG_MAX_RESTARTS` per rolling hour — past that it
stops restarting and just logs, because a node dying four times an hour has a
configuration problem another restart will not fix. It never *starts* a stopped
service, so the idle timer still works.

```bash
journalctl --user -u freetoken-watchdog    # silent when healthy
systemctl --user disable --now freetoken-watchdog.timer   # to turn it off
```

### The measured envelope (8 GB laptop, 5070)

`scripts/freetoken/limits.sh` produces this table; re-run it after any `FT_*` change
rather than trusting the numbers below. Measured 2026-09-02 at `FT_KV_RESERVE=16384`,
`FT_MEMORY_RATIO=0.90`, `FT_MAX_PREFILL=2048`:

| | |
|---|---|
| advertised context | 262,144 tokens — **ignore this** |
| real ceiling | **16,414 tokens**, prompt + generation together |
| largest prompt that prefilled | 11,925 tokens in 10.9 s |
| first refusal | 16,526 tokens → clean `prompt is too long`, no crash |
| decode, shallow context (723 tokens) | 24.1 tok/s end to end |
| decode, deep context (11,924 tokens) | 22.8 tok/s end to end — depth barely costs anything |
| decode, pure (journal `gen throughput`) | ~30 tok/s |
| two concurrent requests, warm | 2.7 s wall for both |
| two concurrent requests, cold MoE cache | 12.9 s wall — the first minute after a restart is slow |
| VRAM in use | 7.3 GB of 8.15, of which ~0.8 GB is the desktop |

The stability result that matters: an oversized prompt now **refuses cleanly** instead
of OOM-killing the scheduler. That was the whole point of `FT_MAX_PREFILL=2048`.

Practical rules that fall out of it:

* Keep a chat's prompt under **~12,000 tokens**. Harvis already caps the picker's ctx
  to the KV capacity and turns thinking off when the headroom drops under 1,024.
* The reach lane is the only thing that can produce a prompt near the ceiling; it caps
  each source at 4,000 characters, so five sources is about 6 K tokens.
* Nothing here is a per-user limit. Two people chatting at once share one 16 K cache.

### Getting the desktop off the 5070 (iGPU offload)

This laptop (Gigabyte AERO X16, BIOS FB05) also has a Radeon 860M.
`system76-power graphics` says **`nvidia`**, so every GPU-accelerated desktop process
rents VRAM the model wants — **~0.8 GB measured**, not the ~350 MB estimated earlier:

| process | VRAM |
|---|---|
| firefox | 282 MB |
| claude-desktop | 183 MB |
| cosmic-comp / panel / app-library / portal | 219 MB |
| brave | 88 MB |
| cosmic-term | 46 MB |

Roughly 10% of the card, or ~2,500 more MoE expert slots if it came back.

**Will hybrid mode work here?** The wiring says probably, with a real black-screen
risk. Evidence gathered 2026-09-02:

* `card1-eDP-2` (NVIDIA) is **connected and enabled**; `card0-eDP-1` (AMD) exists but
  is **disconnected**. The internal panel therefore has an eDP connector on *both*
  GPUs — that is a mux, and it is currently pointed at the discrete card.
* A laptop hard-wired to the dGPU would have no eDP connector on the iGPU at all, so
  switching is physically possible here rather than impossible.
* `amdgpu` is loaded and `card0` is live, so the iGPU is not disabled in firmware.
* `system76-power graphics switchable` answers `switchable`.

The risk is that the mux does not follow the software switch (it is BIOS or Advanced
Optimus controlled, and this is Gigabyte hardware driven by Pop's System76 tooling), in
which case the internal panel comes up black. Before trying it, have a way back:
another machine that can SSH in, or a known BIOS key to reach the firmware menu.
`sudo system76-power graphics nvidia` + reboot is the undo.

**Harvis itself is not the risk.** Both `hybrid` and `compute` keep the dGPU available
for CUDA, so FreeToken, `harvis-ollama` (which uses `runtime: nvidia`) and ComfyUI keep
working; only the display path changes. `compute` mode ("like integrated, but the dGPU
is available for compute") is the more conservative choice if you never want the 5070
driving pixels.

```bash
sudo system76-power graphics hybrid     # or: compute
# reboot, then:
nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv
```

Only `freetoken-serve`'s python should appear afterwards. An app that still needs the
discrete card can be launched with `__NV_PRIME_RENDER_OFFLOAD=1
__GLX_VENDOR_LIBRARY_NAME=nvidia app`. Still not done — it needs a reboot and it is
your call on a laptop you are using.

---

## Putting a node on another machine

Nothing in `scripts/freetoken/` is specific to this laptop any more. Every FT_* value
lives in `~/.config/freetoken.env`, and that file is **measured, not copied** — the
settings that keep FreeToken alive are a property of the box. An 8 GB card needs a
2048-token prefill chunk and a 0.90 memory ratio or the scheduler is OOM-killed
mid-prompt; a 24 GB card is being wasted at those numbers.

Two ways in, and they run the same arithmetic:

**If the box already has the Harvis repo** — copy `scripts/freetoken/` over and run
`install-user-units.sh`. With no env file it measures the machine, writes one, and
stops so you can point `FT_HOME` and `FT_MODEL` at the checkpoint. `--retune` re-measures
an existing node after a GPU or RAM change.

**If it does not** — `GET /api/inference-nodes/provision-script?name=rig&host=0.0.0.0`
returns a self-contained bash script: uv venv, `freetoken` from PyPI, the NVFP4
checkpoint from Hugging Face (~22 GB), the same sizing block inlined, a systemd user
unit that reads the generated env file, a health wait. Read it before running it — it
says at the top what it will listen on. Run it over an existing SSH host with the
`remote/ssh_manager.py` exec endpoint, or paste it in.

Pass `memory_ratio`, `kv_reserve_tokens`, `max_running` or `moe_cpu_threads` on that
URL only to *pin* one against what the machine measured; each pin is appended to the
env file after the measured block, with a comment saying an operator put it there.

What autotune measures and what it decides:

| Input | Feeds |
|---|---|
| total VRAM | `FT_MAX_PREFILL` (2048 / 4096 / 8192 by card size), `FT_MEMORY_RATIO`, `FT_KV_RESERVE` (~4% of the card), `FT_MAX_RUNNING` |
| physical cores | `FT_MOE_THREADS` (cores − 2, clamped 4–12) |
| RAM vs checkpoint size | a warning, not a setting — see below |
| VRAM held by other processes | reported only; `--moe-cache-auto` already sizes itself from *free* VRAM |

The number people get wrong is RAM, not VRAM. **The expert weights live in host RAM**,
so the box needs the whole checkpoint resident plus room for everything else. This
laptop holds 17.8 GB of shared anonymous memory for a 20 GB checkpoint on a 30 GB box,
which is why it swaps and why autotune warns at `checkpoint + 4 GB`.

Then, on the new box:

1. **Put a token in front.** FreeToken has no auth, so on anything but a private
   link put Caddy on the box (the script prints a Caddyfile that answers 401 without
   `Authorization: Bearer …`) and register the Caddy port with `token_env=RIG_NODE_TOKEN`.
   Or reach it over Tailscale/WireGuard and bind `127.0.0.1` on the tailnet interface.
2. **Install the watchdog.** A node whose scheduler is OOM-killed keeps its port open
   and stays `active` to systemd. `install-user-units.sh` enables it by default; the
   provision script prints a reminder because it cannot copy the repo for you.
3. **Register it**: env shorthand in the override, or `POST /api/inference-nodes` as
   admin. The picker shows `Qwen3.6-35B-A3B-NVFP4 (Desktop 5080)` beside the laptop's
   entry when both are up, and chat goes to the lower `priority`.
4. **Re-measure**: `scripts/freetoken/limits.sh` against the new node. Autotune's
   numbers are calibrated starting points; the measured ceiling is the one to document.

Nothing in this document scans the network; a node is only ever the URL you typed.

## Which models this actually carries

The reason a 35B model runs on an 8 GB card is **sparsity, not compression**. Qwen3.6-35B-A3B
has 35B parameters but activates about 3B per token. FreeToken keeps every expert bank in
host RAM and streams the handful the router picks over PCIe, per token. On this laptop
that is 17.8 GB of host memory feeding roughly 6 GB of VRAM.

That trick does not generalise to dense models, and FreeToken says so itself.
`engine.py:385` creates the MoE backend only when `config.model_config.is_moe`, and
`engine.py:1101` drops every offload knob for a dense model with the comment that the
offload family "is worse than inert" there — engine init would build an expert cache
for a model that has no experts. The nine settings it discards (`moe_cache_size`,
`moe_cache_auto`, `moe_cpu_layers`, `moe_cpu_threads`, `expert_load`, …) are the
entire small-card mechanism.

So there are three tiers, and only the first one is magic:

| Model shape | FreeToken support | Fits an 8 GB card? |
|---|---|---|
| **MoE** (qwen3_moe, qwen3_5_moe, glm4_moe, deepseek_v4, gpt_oss, minimax_m2/m3, gemma4-MoE) | full offload path | yes, far above VRAM — bounded by host RAM |
| **Dense** (llama, mistral, qwen2, qwen3, gemma4-dense) | runs, no offload | only if the weights fit in VRAM |
| **GGUF** (`models/gguf`, dequantised at load) | runs | quantisation is the only lever; still VRAM-bound |

Could dense models be made to work the same way? Not usefully, and the reason is
arithmetic rather than missing code. A dense model needs *every* weight for *every*
token, so streaming it would mean moving the whole checkpoint across PCIe once per
token. A 20 GB model over ~25 GB/s of PCIe 4.0 x16 is well under one token per second,
and this laptop's link is narrower than that. The MoE path works because it moves
maybe a twentieth of the weights per token and can prefetch the next layer's experts
while the current one computes. For a dense model the lever is quantisation — a 4-bit
7B fits an 8 GB card outright — not offload.

The practical consequence for Harvis: the node is worth pointing at another MoE
checkpoint (a bigger GLM or DeepSeek on a box with more RAM), and is not a way to make
the existing dense Ollama models better. Ollama already handles those, and it is what
`OLLAMA_URL` stays wired to.

---

## The power switch, and how a container starts a host service

FreeToken runs as a `systemd --user` service on the host. The Harvis backend runs in a
container: no bus, no PID namespace, no way in. Every direct fix hands the container
more authority than "please start the GPU service" deserves — SSH back to the host,
a privileged socket, `docker.sock`.

So the channel is a **file**, and the host decides what a request means:

```
container                       shared dir                    host
──────────                      ──────────                    ────
control.request("on")   ───►    desired.json                  freetoken-control.path
                                                                  │ (fires on write)
                                                                  ▼
                                                              freetoken-control-agent
                                                              systemctl --user start freetoken
                        ◄───    status.json   ◄───────────────  publishes what happened
```

The protocol carries a state (`on`/`off`) and nothing else — there is no field that
says *what* to run, so the container cannot ask the agent to run anything but the one
unit it was configured with. The two sides run as different uids (1001 in the
container, 1000 on the host), so the directory is `1777` like `/tmp` itself and each
side writes only its own file.

`/tmp` is already bind-mounted into the backend on this box, so no compose change was
needed. On a machine where it is not, mount whatever `HARVIS_FREETOKEN_CONTROL_DIR`
points at.

**Install the host half** (idempotent; already done by `install-user-units.sh`):

```bash
./scripts/freetoken/install-user-units.sh
systemctl --user status freetoken-control.path      # should be active
```

**If the agent is not installed**, `GET /api/inference-nodes/power` answers
`controllable: false` with a hint — never `running: false`. "There is no switch here"
and "the node is off" are different facts and the settings pane draws them differently.

### Loading is not running

FreeToken opens its HTTP port and answers `/v1/models` **while the checkpoint is still
loading** — measured at 38.9 s cold on this laptop. A probe calls that reachable, so
`probe.reachable` alone is a false positive for readiness: a chat routed there sits
and waits. `/health` is the honest signal:

```
loading   {"status":"loading","phase":"other","progress":{…}}    ← no `maintenance` key
serving   {"status":"ok",…,"maintenance":"serving"}
```

`control.serving()` requires that, and both `wake()` and the settings switch use it. A
node with no `/health` at all (vLLM, llama-server) is taken at its word — for those the
open port really is the whole story.

### Auto-wake

With `HARVIS_FREETOKEN_AUTO_WAKE=1` (the default), `model_proxy._resolve_route` no
longer answers 503 for a model whose only node is asleep: it asks the host to start it,
waits for `serving`, re-probes, and routes. Only for the one local node, and only when
the control agent is installed — everything else still 503s honestly.

### API

| Route | Who | What |
|---|---|---|
| `GET /api/inference-nodes/power` | any signed-in user | `controllable`, `running`, `loading`, `unit_state`, `desired`, `agent_error`, `agent_stale` |
| `POST /api/inference-nodes/power` | admin | `{"state":"on"\|"off"}`. `on` blocks until the node actually answers, so the caller gets the real outcome and not an optimistic 200. |
| `GET /api/inference-nodes/moe-candidates` | any signed-in user | installed Ollama models classified (below) |

---

## Detecting which installed models are worth a node

A node earns its keep on **sparsity**. `moe.py` reads that off the GGUF metadata Ollama
already surfaces at `POST /api/show` — `<family>.expert_count` and
`<family>.expert_used_count` — rather than pattern-matching names, because `mixtral` is
MoE and so is `gpt-oss`, and neither says so in its name.

Four verdicts, only one of which is an action:

| Verdict | Meaning |
|---|---|
| `node_would_help` | Sparse and over ~12B params. The shape FreeToken exists for. |
| `served_by_node` | A node already serves this exact name; chat routes there. |
| `fits_anyway` | Sparse but small enough that Ollama is fine. |
| `dense` | No routed experts — the offload path does not apply at all. |

Measured on this laptop (2026-09-03), 14 installed models: three `node_would_help`
(the 35B-A3B uncensored Qwen at 8/256 experts, `gpt-oss:20b` and `gpt-oss:latest` at
4/32), eleven `dense`.

**`node_would_help` is not one click away**, and the endpoint says so in its `note`.
FreeToken loads its own checkpoint, and its GGUF reader understands exactly one
architecture — `freetoken/models/gguf/config.py` maps `gemma4` and nothing else. So it
cannot take over Ollama's blob for `gpt-oss` or `qwen35moe`; the verdict means "worth
getting a checkpoint for", not "press the button".

---

## The settings pane

**Admin → Settings → Inference Nodes** (`/admin/settings/inference-nodes`) — visible
only while **Developer Mode** is on (see below).

Two things: the power switch for the local node, and the MoE scan. The switch is bound
to *intent*, not to observed state — while the checkpoint loads the node is neither on
nor off, and a switch that snapped back would read as a failure. It polls only while
something is in flight.

Files: `front_end/owui/src/lib/components/admin/Settings/InferenceNodes.svelte`,
`front_end/owui/src/lib/apis/inference-nodes/index.ts`, wired into `Settings.svelte`
(import, tab whitelist, tabs array, icon, pane).

> **Rebuild gotcha.** nginx bind-mounts `front_end/owui/build`, and `vite build`
> *deletes and recreates* that directory — which breaks the mount, and every page goes
> 500 until `docker restart nginx-proxy` re-resolves it. Always restart nginx after a
> frontend build.

> **Build memory gotcha.** The SSR bundle step needs roughly 6-8 GB of heap. FreeToken
> holds its expert banks as ~16 GB of *shared* memory, which does not show up against
> any one process in `ps`, so a build on a loaded box dies with
> `FATAL ERROR: Ineffective mark-compacts near heap limit` and no obvious culprit. Stop
> the node first (`systemctl --user stop freetoken`), build, then start it again — about
> 40 s to come back.

---

## Developer Mode

The Inference Nodes pane is experimental, and a Harvis handed to someone else should not
present it as finished. **Admin → Settings → General → Developer Mode** is the switch
that decides whether it exists at all.

| Layer | Where |
|---|---|
| Storage | `instance_settings` key `dev_mode` (TEXT `"true"`/`"false"`) |
| Default | env `HARVIS_DEV_MODE`, **on** in code pre-1.0 |
| Resolution | `owui_compat/admin_config.py` — `dev_mode_enabled{,_via_pool}` |
| Published as | `/api/config` → `features.enable_dev_mode` |
| Enforced in | `front_end/owui/src/lib/components/admin/Settings.svelte` |
| Read/write API | `GET`/`POST /api/v1/auths/admin/config`, key `DEV_MODE` (admin only) |

A stored row beats the env default, because that is the value an admin last chose on
purpose; a blank row counts as unset, not as off. A cold or unreachable database falls
back to the **env default rather than to off**, so a DB blip cannot blank a developer's
panels mid-session.

Turning it off removes the tab from the settings list, from the settings **search index**
(so typing "freetoken" cannot surface a hidden pane), and from the URL whitelist — a deep
link to `/admin/settings/inference-nodes` falls back to General. Saving refetches the boot
config, so the tab appears and disappears without a reload.

The default is `True` in code deliberately: everything it gates shipped in the last few
weeks, and defaulting to off would make an existing install lose the panel on a pull with
no message. Flipping that literal to `False` in `_env_dev_mode_default` is the 1.0 gate.
Until then, set `HARVIS_DEV_MODE=false` on a machine that should look shipped.

`features.enable_sidebar_more` covers the same idea for the sidebar's internal surfaces
(Agent Studio, Neural Map, Model Comparison) and stays env-only for now — folding it
behind the same switch changes the behaviour of a flag that already ships, which is a
separate call.

Tests: `python_back_end/tests/test_admin_config.py` (11).

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
  queues inside FreeToken. Two at once is cheap when warm (2.7 s for both) and
  expensive on a cold MoE cache (12.9 s) — the first minute after a restart is slow
  because the experts have to come over PCIe again.
* **The whole box shares one 16 K cache.** There is no per-user or per-chat budget; a
  long chat and a grounded chat at the same time compete for the same pages.
* **A dead scheduler looks alive.** When the GPU worker OOMs, FreeToken's API process
  logs `Backend worker is gone … stopping the API server` but keeps the port open;
  `/health` returns an empty body, the unit stays `active`, and `Restart=on-failure`
  never fires. Symptom in Harvis: `Inference node freetoken unreachable: ConnectError`
  and the model gone from the picker. **Now handled by `freetoken-watchdog.timer`**
  (above), which catches it within about two minutes; the manual fix is still
  `systemctl --user restart freetoken`.
* **The sizing arithmetic exists twice.** `scripts/freetoken/autotune.sh` is the
  canonical copy; `plugins/inference_nodes/provision.py` inlines it because the box
  being provisioned does not have the repo. A test pins the two to the same outputs
  for an 8 GB and a 24 GB card, so a drift shows up as a failure rather than as a
  node that dies under load.
* **Autotune is calibrated, not measured, on cards it has never seen.** The formula was
  fitted to this 5070 and sanity-checked against 12/16/24/48 GB shapes on paper. Run
  `limits.sh` on a new node before trusting the ceiling.
* **The offload path is MoE-only** (see above). A dense checkpoint runs but must fit
  in VRAM; FreeToken drops every MoE knob for it at `engine.py:1101`.
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

31 tests for the plugin (env parsing, spec validation, thinking policy incl. the
KV-headroom rule, KV capacity capping, `node_complete` fallback, absent vs unknown,
priority, URL ownership; the provisioning script: valid bash, no placeholder left
behind, no hardcoded tuning value, and the sizing block reproducing this laptop's
measured settings while a 24 GB card gets its own; the power channel: `serving` vs a
merely-open port, no-agent reading as uncontrollable rather than off, the
desired/status round-trip through a tmpdir, loading distinguished from running, and
the staleness grace period; and MoE detection: expert counts from metadata, the "1
expert is dense" spelling, parameter parsing, and all four verdicts) plus the 13
existing Ollama-host tests — **44 pass**, plus `tests/test_admin_config.py` for the
Developer Mode gate (11) for **55** across the three suites. The
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
