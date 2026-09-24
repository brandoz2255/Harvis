# Spec — Node reachability & SSH transport for Harvis inference nodes

Status: **draft / design** — not implemented
Owner: David (dulc3)
Related goal: #2 (Inference — Harvis runs models across machines it can reach)
Date drafted: 2026-09-24

---

## 1. Why this doc exists

We wanted "set up SSH to my laptop" during a **Claude Code cloud session**. That
surfaced a hard constraint worth writing down permanently, because it decides
*where* this feature can live.

### The cloud-session reality (the constraint)

A Claude Code web/cloud session runs in an **isolated, ephemeral Anthropic cloud
container** — not on David's machine and not on his LAN. Practical facts:

- **Ephemeral:** the container is reclaimed after inactivity/session end. Only
  what's committed and pushed survives. (That's why this is a committed doc.)
- **Egress is an HTTPS allowlist proxy**, not open networking. Non-allowlisted
  hosts are blocked (e.g. `huggingface.co` was blocked mid-session). Arbitrary
  outbound TCP such as **SSH/22 is not a normal egress path**.
- **No route to the home LAN.** Private ranges (10/8, 172.16/12, 192.168/16)
  bypass the proxy and connect *directly from the container* — but the container
  sits in Anthropic's cloud, so `172.17.0.1` there is the container's own docker
  bridge, **not** David's laptop. There is no path from a cloud session to a
  machine on the home network.

**Conclusion:** SSH-from-the-cloud-session to the laptop cannot work and should
not be attempted. SSH reachability belongs to **Harvis running on David's own
infra** (LAN box, k3s node, or Proxmox VM), where the target machines are
actually routable. This session's job is to *build and statically verify* that
code; it runs at home.

The only way a cloud session could ever reach the laptop is if the laptop had a
**public endpoint / tunnel** (Tailscale, Cloudflare Tunnel, ngrok, forwarded
public IP) *and* the environment network policy were widened to allow it. That's
out of scope here and not the intended design.

---

## 2. Problem

Harvis should run models across the machines it can reach (laptop, desktop/rig,
Pi cluster, future 4090 box). Today reachability is a single hard-coded HTTPS
pattern:

- `model_proxy.py` probes a `laptop` Ollama (`OLLAMA_URL`, default
  `http://ollama:11434`) and an optional `desktop` Ollama (`DESKTOP_OLLAMA_URL`)
  via `GET /api/tags`, and routes GPU-heavy models (e.g. `gemma4`) to the desktop
  via `HARVIS_DESKTOP_PREFERRED_MODELS`.

Gaps:

1. Only two nodes, both by env var — no general node registry.
2. HTTPS-to-Ollama is the *only* transport. There's no control plane to **wake a
   node, start/stop `ollama serve`, pull a model, or read `free -m`** before
   dispatching a large model. (FreeToken's 35B model has OOM-crashed the laptop
   before — we need a memory check *before* load.)
3. No health/liveness beyond a `/api/tags` probe at request time.

SSH is the missing **control-plane transport**: HTTPS carries inference
requests; SSH carries node management (health, model pulls, `free -m`, waking a
node's Ollama).

---

## 3. Goals / non-goals

### Goals
- A **node registry** (config file + env override) describing each reachable
  machine: name, addresses, transports, and per-node limits.
- Two transports per node, used for different jobs:
  - **HTTPS → Ollama** (`/api/tags`, `/api/chat`, `/api/generate`) — inference.
  - **SSH** — control plane: `free -m` gate, `ollama list/pull/ps`, start/stop
    the daemon, liveness.
- A **pre-dispatch memory gate**: never load a model whose footprint would OOM
  the node. Special-case: keep FreeToken's 35B pinned to `172.17.0.1` and check
  `free -m` first.
- Named hosts only. **No network scanning / discovery sweeps** (standing rule).

### Non-goals
- Not reachable from a cloud session (see §1). Runs on David's infra only.
- Not a scheduler/queue — that's the future 4090/k8s inference layer, logged
  only.
- Not the router decision model (Laya/SemIf, goal #5) — this layer *executes* a
  routing decision; it doesn't *make* it.

---

## 4. Design

### 4.1 Node registry

A config file (`config/inference_nodes.yaml` or JSON), overridable by env for
secrets. Never commit real keys/hosts — see §5.

```yaml
nodes:
  - name: laptop
    ollama_url: http://172.17.0.1:11434     # HTTPS/HTTP inference transport
    ssh:
      host: 172.17.0.1
      user: dulc3
      key_ref: HARVIS_SSH_KEY_LAPTOP        # env var / secret name, NOT the key
      port: 22
    limits:
      max_model_gib: 20                      # refuse models above this
      free_mem_gate: true                    # run `free -m` before large loads
    pinned_models: []                        # models that MUST run here
  - name: desktop            # the rig / 4090
    ollama_url: ${DESKTOP_OLLAMA_URL}
    ssh: { host: ..., user: ..., key_ref: HARVIS_SSH_KEY_DESKTOP }
    limits: { max_model_gib: 48, free_mem_gate: false }
    preferred_prefixes: [gemma4]             # subsumes HARVIS_DESKTOP_PREFERRED_MODELS
  - name: freetoken
    ollama_url: http://172.17.0.1:11434      # pinned to 172.17.0.1 per memory
    ssh: { host: 172.17.0.1, user: ..., key_ref: HARVIS_SSH_KEY_FREETOKEN }
    limits: { max_model_gib: 40, free_mem_gate: true }   # 35B OOM'd before
    unreachable: true                        # currently down; skip in selection
```

### 4.2 Transports

- **`OllamaTransport`** — thin async HTTPS client (reuse the existing `httpx`
  async pattern in `model_proxy.py` / `research_agent.py`, not blocking
  `requests`). Methods: `tags()`, `chat()`, `generate()`, `ps()`.
- **`SSHTransport`** — async SSH (recommend `asyncssh`; falls back to a
  subprocess `ssh` call). Methods: `run(cmd, timeout)`, plus helpers:
  `free_mem_mib()`, `ollama_list()`, `ollama_pull(model)`, `ollama_up()`,
  `alive()`. Key material comes from a secret ref (§5), never inline.

### 4.3 Node manager (`NodeManager`)

- `nodes()` → registry, skipping `unreachable`.
- `healthy_nodes()` → parallel liveness (HTTPS `/api/tags`, optional SSH ping),
  short timeout, cached briefly.
- `node_for(model_name)` → applies `pinned_models`, then `preferred_prefixes`,
  then availability (`/api/tags` contains the model) — this replaces and
  generalizes the current two-node `_prefers_desktop` logic in `model_proxy.py`.
- `can_load(node, model)` → if `free_mem_gate`, SSH `free -m`, compare available
  RAM/VRAM against the model's footprint and `limits.max_model_gib`; refuse (and
  fall through to another node) if it wouldn't fit. **This is the OOM guard.**

### 4.4 Integration point

`model_proxy.py` is the seam. Its request path already chooses laptop vs desktop
and probes `/api/tags`; swap that block to call `NodeManager.node_for(model)` +
`can_load(...)`. Keep the existing env vars working as a compatibility shim
(`OLLAMA_URL` → laptop node, `DESKTOP_OLLAMA_URL` → desktop node) so nothing
breaks if the registry file is absent.

### 4.5 Health / discovery
- Liveness only against **named** nodes. No scanning.
- A node that fails N consecutive probes is marked degraded and skipped until it
  recovers.

---

## 5. Security

- **No secrets in git.** `key_ref` names an env var / k8s Secret / mounted file;
  the spec and config carry the *name*, never the private key or a real host.
- SSH keys are per-node, least-privilege. Prefer a dedicated `harvis` user on
  each node whose authorized command set is limited (an SSH `ForceCommand`
  wrapper allowing only `free -m`, `ollama …`, service start/stop) rather than a
  general shell, so a compromised Harvis backend can't get arbitrary RCE on the
  laptop.
- Host key verification on (`known_hosts` pinned), not `StrictHostKeyChecking=no`.
- This layer is control-plane for *local* inference nodes only. It must not
  become a general remote-exec tool exposed to agents/OpenClaw. OpenClaw's tool
  allowlist stays as in the root CLAUDE.md; SSH transport is backend-internal.

---

## 6. What exists today (prior art in-tree)

- `python_back_end/workspace/model_proxy.py`
  - `LOCAL_OLLAMA_URL` / `DESKTOP_OLLAMA_URL`, `_DESKTOP_PREFERRED_PREFIXES`,
    `_prefers_desktop()`, and the `/api/tags` dual-probe (~lines 42–247). This is
    the block `NodeManager` generalizes.
- Async HTTPS pattern to copy: `research/research_agent.py`,
  `agent_research.py` (`async_make_ollama_request` with `httpx.AsyncClient`).
- Goal-list references `python_back_end/plugins/inference_nodes/` (control.py,
  moe.py) — **not present in this checkout.** Confirm whether that landed on
  another branch or is still to be built; if it exists, fold this design into it
  rather than duplicating.

---

## 7. Open questions (decide before building)

1. **SSH library:** `asyncssh` (clean async, extra dep) vs shelling out to the
   system `ssh` (no dep, clunkier)? Lean `asyncssh`.
2. **Config format & location:** YAML under `config/` vs JSON alongside existing
   `*.json`? Match whatever the backend already loads.
3. **Where does the memory footprint per model come from** — a static table, or
   `ollama show`/`/api/show`? Static table is simplest to start.
4. **Does `inference_nodes/` already exist on another branch?** (see §6) — avoid
   duplication.
5. **Wake-on-LAN / node power-on** for a sleeping rig — in scope later, or manual
   for now? Manual for now.

---

## 8. Suggested phasing

- **P1 (cloud-doable now):** registry loader + `OllamaTransport` +
  `NodeManager.node_for` as a drop-in for the current `model_proxy` block, env
  shim for back-compat. Unit-testable here without any node.
- **P2 (needs a node to verify):** `SSHTransport` + `free_mem_gate` OOM guard.
  Code here, verify at home against the laptop.
- **P3 (later):** degraded-node tracking, wake-on-LAN, hand-off to the future
  4090/k8s inference layer.
