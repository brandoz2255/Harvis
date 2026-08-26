# MCP credentials work for any stdio server now — runtime still gated off

**Date:** 2026-08-22
**Branch:** `harvis1.2` in the main checkout at `/home/user/Harvis`
(**not** the `jolly-dhawan-5babcd` worktree — that one is behind and has none of this code)
**Head:** `b7f70eb5`. **Nothing from this pass is committed.** Everything below is on disk and
deployed to the running stack at `http://localhost:9000`.

---

## Pick up here (in order)

1. **Turn the runtime on.** Add to `.env` in the repo root — I can't write that file:

   ```
   HARVIS_MCP_RUNTIME_ENABLED=true
   ```

   then:

   ```bash
   cd /home/user/Harvis && docker compose up -d --no-deps backend
   ```

   Compose already reads it as `${HARVIS_MCP_RUNTIME_ENABLED:-false}`. **Do not edit
   `docker-compose.yaml`** — its 12 MCP lines are your own uncommitted work.

2. **Connect Higgsfield through the UI with your real key.** Settings → Connectors, or
   `/harvis/agent-studio/mcp-shop`. This is the one link I couldn't test — I proved the server
   starts and lists 20 tools with a sealed *placeholder* key; whether the vendor accepts a real
   one is between you and your account.

3. **Then** the Discord + Harvis setup-steps write-up, which you deferred until a second MCP was
   connected by hand.

---

## What got built

Three things in one pass. All deployed, none committed.

### 1. The credential adapter (the main event)

**The bug was a policy decision nobody revisited.** `mcp_servers.env` is plain JSONB, so the
connections wizard *declined to collect secrets at all* — an amber "credential storage pending
review" card and a button labelled **"Connect (limited)"**. The row saved fine, then the server
failed at spawn with no key and no explanation. Every secret-bearing server in the catalogue
(GitHub, Slack, Notion, and anything third-party) had been unusable since the runtime landed.

`python_back_end/plugins/mcp/credentials.py` (**new, untracked**, ~130 lines) seals secret values
with the same Fernet cipher every other Harvis credential uses — `main.encrypt_api_key`, derived
from `JWT_SECRET` — and stores them **inline in the existing `env` column**:

```json
{"COMFYUI_URL": {"__harvis_enc__": "Z0FBQUFB…"}, "COMFYUI_DEFAULT_CKPT": "sd15.safetensors"}
```

No new table, no new column, no migration. Plain and sealed config coexist in one dict and
`is_sealed()` tells them apart by shape.

Two rules, both enforced by *where* the functions are called rather than by discipline:

- **Sealed at rest, everywhere but the spawn.** `McpServerConfig.env` carries the sealed shape
  unchanged through the registry, so a config read and written back can never downgrade a secret
  to plaintext. Exactly one unseal site — `runtime._spawn_container`, building the sandbox env.
- **A saved secret never travels back to a browser.** The read path masks to a fixed `••••••••`
  (never a length) and returns a `credential_keys` list so the UI can say *which* variables hold
  a secret. `merge_env` keeps the stored value when the client omits a field or echoes the mask,
  which is what lets you edit a connection's command without retyping its token.

Deliberate failure mode: `unseal` returns `""` on decrypt failure and logs
`"mcp: a stored credential could not be decrypted (key rotated?)"`. Rotating `JWT_SECRET`
invalidates every stored credential — an empty variable fails loudly at the vendor, which beats
silently half-working.

### 2. Notebook nav separated from the main tabs

`NotebookNav.svelte` now sits in its own block behind a `border-t` with a small uppercase
`Notebooks` label, so a new notebook no longer reads as a child of CAD Studio. The full-width
"New notebook" button left the top slot; Recents grew a compact `+ New` on its header.

### 3. Knowledge attach parked with CAD

New flag `enable_knowledge_attach` (`HARVIS_OWUI_KNOWLEDGE_ATTACH`, default off) hides the row in
the chat `+` menu. The picker component and its routes stay in the tree — the flag brings them
back. The `#` command picker is untouched.

---

## Proof it works (live, twice)

**ComfyUI**, with `--comfyui-url` *deliberately deleted from the command line* so the sealed
variable was the only way the server could function:

```
stored env keys          : ['COMFYUI_DEFAULT_CKPT', 'COMFYUI_URL']
ciphertext leaks?        : NO
API returns env          : {'COMFYUI_URL': '••••••••', 'COMFYUI_DEFAULT_CKPT': 'sd15.safetensors'}
API credential_keys      : ['COMFYUI_URL']
survives a re-save?      : OK
registry env stays sealed: {'COMFYUI_URL': {'__harvis_enc__': 'Z0FBQUFB…'}, …}
tools/list -> 15 tool(s) in 6.7s
list_models -> "checkpoints (1):\n  1. sd15.safetensors"
```

**Higgsfield**, picked because it is a vendor with zero lines of code anywhere in the repo —
`npx -y higgsfield-mcp` with sealed placeholder `HF_API_KEY` / `HF_SECRET`:

```
mcp: connected higgsfield-probe (Higgsfield AI) — 20 tools
generate_image, generate_video, generate_talking_head, create_character, list_styles, …
```

Both test rows deleted; both sandbox containers (`harvis-mcp-2-comfyui-sealed`,
`harvis-mcp-2-higgsfield-probe`) removed.

---

## Will service X work?

**Yes** — any MCP server that is **stdio**, launches with `npx` / `uvx` / `uv` / `node` /
`python` / `python3`, and authenticates through **environment variables**. That is the whole
registry plus servers not in the catalogue at all, because the UI grew "Add environment variable"
rows where you name any variable and tick a Secret box. There is no per-vendor code anywhere.

**No** — remote/SSE/HTTP transports (`plugins/mcp/runtime.py:242` refuses anything but stdio,
which rules out the one `sse` catalogue entry and all 15 `remote_oauth` storefront cards),
Docker-launched servers (`docker` is not in `_ALLOWED_COMMANDS` at `runtime.py:151`), and servers
needing host filesystem mounts (the sandbox has none by design).

---

## Traps worth not re-discovering

- **★ `McpWizard.svelte` is imported by nothing — dead code.** I patched it first and the build
  came out with `'Add environment variable': 0`. The live surfaces are **`McpShop.svelte`** and
  **`ConnectorsPanel.svelte`** (both reached through `ConnectorsPanel` from Settings and
  `/harvis/agent-studio/mcp-shop`). I patched the wizard anyway for consistency, but changing it
  alone changes nothing on screen.
- **`ConnectorsPanel` has a second copy of the button label** at line ~680; the first rebuild
  still shipped `'Connect (limited)'` because of it.
- **Svelte reactivity:** the readiness statement in `ConnectorsPanel` must read `credValues` and
  `extraVars` **directly**, not through a helper function — otherwise Svelte doesn't track them
  and Connect stays disabled after you type a key.

---

## Files changed (all uncommitted)

**Backend**

| File | State |
|---|---|
| `python_back_end/plugins/mcp/credentials.py` | **new, untracked** — the adapter |
| `python_back_end/plugins/mcp/runtime.py` | `unseal_env` import + the one unseal site |
| `python_back_end/owui_compat/connections.py` | `mask_env` + `credential_keys` on read; `merge_env` on write; `ConnForm` gained `credentials` / `drop_credentials` |
| `python_back_end/owui_compat/mcp_wizard.py` | docstring; `pending_review` → `supported` |
| `python_back_end/owui_compat/mcp_catalog.py` | same |
| `python_back_end/owui_compat/config.py` | `enable_knowledge_attach` flag |

**Frontend**

| File | State |
|---|---|
| `.../customize/McpShop.svelte` | credential inputs, `credsReady` / `needsForm`, `body.credentials` |
| `.../customize/ConnectorsPanel.svelte` | same + the extra-vars editor (arbitrary `ENV_NAME` + Secret checkbox) |
| `.../customize/McpWizard.svelte` | patched for consistency — **dead code, imported by nothing** |
| `.../layout/Sidebar/NotebookNav.svelte` | bordered block, `+ New` on Recents |
| `.../chat/MessageInput/InputMenu.svelte` | Knowledge row wrapped in the new flag |

Deploy commands used: `npm run build` in `front_end/owui/` then
`docker compose restart nginx`; `docker compose restart backend` for the Python side
(`owui_compat/` and `plugins/` are bind-mounted `:ro`).

---

## Still open

- **`HARVIS_MCP_RUNTIME_ENABLED` is `false` on the running backend.** Nothing above matters in
  production until step 1 at the top.
- **MCP tools reach only the Build/agent lane.** `plugins/mcp/tool_bridge.py:48 mcp_tool_specs`
  has exactly two callers, both `workspace/orchestration/runner.py:600,603`. **Plain chat has no
  MCP tools at all** — that is the real remaining gap behind the word "universal."
- **`plugins/mcp/routes.py` is unregistered dead code** — 10 routes under `/api/mcp`, every
  handler defaulting `user_id: int = 1` (no auth), absent from the live 662-route table. Do not
  register it as-is; `owui_compat/connections.py` is the owner-scoped replacement.
- **MCP containers leak on backend restart.** Sessions die with the process, the sibling
  containers do not. `_spawn_container` removes a same-named one on next connect, so it
  self-heals rather than duplicating. Manual sweep:
  `docker rm -f $(docker ps -aq --filter label=harvis.mcp=1)`.
- **Keys still to rotate (yours, told before):** the Kimi/Anthropic key, `OPENCLAW_GATEWAY_TOKEN`,
  the Gemini key, and the OpenRouter key you pasted into chat.
- **OpenRouter as a `FREE_PROVIDERS` row** — you said "we'll tackle that next," so it's untouched.
  When it happens it must set `models_endpoint_public: True`, or the credential check reports
  "Connected" for any garbage string.

## Documented in the vault

`notes-vault/code/harvis/2026-08-22-the-field-that-refused-to-take-your-key.md`, with `index.md`
and `log.md` updated.
