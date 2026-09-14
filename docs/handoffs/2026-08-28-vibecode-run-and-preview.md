# Handoff — 2026-08-28

Build/Code tab session. Two things shipped and were verified live; nothing was
committed. The one unverified step is a browser click that needs a login.

Headline: **you can now write a web page in the Build/Code tab and run it inside
Harvis.** Pick any model, have it write the files, press **Run**, see the app.

---

## Where the branches stand

| Branch | Head | State |
|---|---|---|
| `fixes` | `46a0285e` | The running stack's checkout. All of today's edits are uncommitted on top of it. |
| `harvis1.3` | `a0329d7b` | Untouched today. |
| `main` | `d2480fc7` | Untouched today. Still separate from `harvis1.3` on purpose. |

Every change below is dirty in the working tree. **Nothing was committed or
pushed.** The `.env` flag that switches the new feature on is untracked and
must stay that way.

---

## 1. SHIPPED — cloud models work in the Build/Code tab again

**Symptom:** pick OpenRouter in the Build/Code tab, send anything, get
`400 Bad Request`. Local Ollama worked. Model discovery worked, so the API key
and the plumbing were provably fine.

**Cause:** OpenAI's function-calling spec constrains tool names to
`^[a-zA-Z0-9_-]{1,64}$` — **no dots**. Harvis was sending five tools named
`agent_reach.web_search`, `agent_reach.web_read`, `agent_reach.yt_transcript`,
`agent_reach.gh_view`, `agent_reach.rss_read`. Every strict OpenAI-compatible
provider rejects that: OpenRouter, Groq, Cerebras, Mistral, NVIDIA, OpenAI.
Local Ollama does not enforce the grammar, which is why it survived — the lane
we develop against is the one lane that tolerates it.

**Why nobody could see it:** `model_router._post_with_backoff` called
`resp.raise_for_status()` without reading `resp.text`. The provider explained
the problem in the response body on every failure and Harvis discarded it.

**Fix:** wire names are now underscored (`agent_reach_web_search`, …) in
`workspace/orchestration/tools.py`, `runner.py`, `authz.py`,
`skills_training/proposer.py`, `agent_reach/tools.py`,
`skills/Harvis/harvis-agent-reach/SKILL.md` and `scripts/agent-reach-e2e.py`.
A legacy normalizer accepts the dotted form at dispatch so an older model
prompt still resolves. A module-level grammar guard logs an error (never
raises) if a wire name ever breaks the pattern again. The router logs
`resp.text[:1200]` before raising.

**Verified:** the same 15-tool schema that returned 400 now returns HTTP 200
from `inclusionai/ling-3.0-flash-fin:free`.

---

## 2. SHIPPED — Run & Preview for a Build/Code session

### What it is

`owui_compat/workspace_sandbox.py` (new) subclasses the existing
`RepoSandboxManager`. Same image, same isolated network, same dropped
capabilities, same idle reaper. The only difference is the source of the code:

```
repo_sandbox      : empty container  →  git clone <public url> /repo
workspace_sandbox : bind-mount THIS session's directory at /repo
```

Bind mount, not copy: a copy goes stale the moment the agent writes another
file (and HMR would have nothing to watch), and `npm install` needs somewhere
to leave `node_modules` so the second Run is fast.

### Surfaces

- `GET  /api/workspace/vibecode/session/{id}/preview` — what Run would do, and
  what it is doing.
- `POST /api/workspace/vibecode/session/{id}/run` — requires `{"approved": true}`.
- `POST /api/workspace/vibecode/session/{id}/stop`
- New **Run** tab in the Build/Code workspace, rendered by
  `front_end/owui/src/lib/agent-studio/build/VibecodeRunSurface.svelte` (new).
- Idle sweeper started from `main.py` only when the flag is on; 30-minute idle
  timeout, inherited from the Repo Runner.

### Static-page detection

Most of what a chat model writes is one `index.html` plus a script. No
manifest, nothing to install. `fab_repo.detect_stack` gained a static tail: if
no manifest branch claimed the directory and there is an `index.html` in the
root or in `public` / `dist` / `site` / `www` / `static` / `build`, the plan is
`python3 -u -m http.server 3000 --bind 0.0.0.0` with **no install step**. The
UI ladder omits the "Installing" rung in that case rather than announcing a
phase that never runs.

### Why the preview is a 127.0.0.1 port and not an nginx path

`auth_optimized.py` accepts the JWT from an `access_token` **cookie**. If the
model's page were served from Harvis's own origin, its JavaScript could call
`/api/…` as the signed-in user. So the sandbox's dev port is published to an
auto-assigned port bound to 127.0.0.1, and the iframe loads that origin
directly.

The deliberate cost: **the iframe only embeds when the browser is on the Docker
host over plain http.** Anywhere else the surface says so and prints the port
to open on that machine — it does not render a broken frame and call it a
preview. This was the agreed scope ("laptop only, for now").

### Configuration

```yaml
# docker-compose.yaml, backend environment
HARVIS_VIBECODE_RUN_ENABLED: "${HARVIS_VIBECODE_RUN_ENABLED:-false}"
HARVIS_VIBECODE_MAX_SANDBOXES: "${HARVIS_VIBECODE_MAX_SANDBOXES:-3}"
```

Default **off**, for the same reason the Repo Runner is: it executes code.
It is currently on in the local untracked `.env`. An env change needs
`docker compose up -d backend` — a plain `restart` will not pick it up.

---

## 3. The bug that cost the most — root without CAP_DAC_OVERRIDE

Worth reading even if you never touch this feature again.

The first real run reported `dev server did not become reachable`, which sounds
like networking. It was not.

```
$ id                  → uid=0(root) gid=0(root)
$ ls -la /repo        → drwxr-xr-x 3 1001 1001 … index.html game.js
$ touch /repo/.wtest  → Permission denied
```

**`cap_drop=["ALL"]` removes CAP_DAC_OVERRIDE**, the capability that lets root
ignore file-permission bits. Without it root is just another uid with no
matching owner or group, so a `755` directory owned by 1001 grants it `r-x` and
nothing more. Session directories are created by the backend as `appuser`
(1001), so every one of them looks like that.

The start command is `exec <dev_cmd> > /repo/.harvis-dev.log 2>&1`. It failed at
the redirect, before the server was ever launched, and `npm install` writing
`node_modules` would have failed the same way. The failure could not reach the
log because the log was the thing that could not be created.

**Fix, entirely additive:**

- `repo_sandbox.py` — `_spawn` takes an optional `user="uid:gid"` (default
  `None`, so the Repo Runner's root-based `uv pip install --system` path is
  unchanged), and the dev-log path is now a `_LOG_PATH` class attribute.
- `workspace_sandbox.py` — passes the session directory's own owner from
  `os.stat`, sets `HOME=/tmp` plus `npm_config_cache` and `XDG_CACHE_HOME`
  (that uid has no home in the image), and writes the log to
  `/tmp/harvis-dev.log`. Inside `/repo` it would have appeared in the diff the
  agent and the editor both read.

`cap_drop=["ALL"]` and `security_opt=["no-new-privileges"]` are unchanged.

**General rule:** a capability-stripped root cannot write a bind mount owned by
another uid. Run as the directory's owner rather than reaching for privilege.

---

## 4. Verification actually performed

Run against the real backend, real database rows and a real session directory —
no stubs.

| Check | Result |
|---|---|
| Static lane (`python3 -m http.server`) | `running`, host port 32770, `curl` returns the page and its script, both 200 |
| Node lane (`npm install` + Vite) | `running`, Vite 5.4.21 serving, 19 MB `node_modules` written, owned by `appuser` |
| Container identity | `uid=1001 gid=1001` |
| Isolation | `/repo/..` is the container root — a session's box sees only its own directory |
| Host-path mapping | resolved by self-inspecting the backend's own mount table; never hardcoded |
| Tool rename | HTTP 200 from a live OpenRouter model with the full 15-tool schema |
| `POST /run` without approval | 403 "Running the app needs your explicit approval" |
| `GET /preview` as a different user | 404 "Session not found" |
| `POST /stop` | container removed, published ports refuse connections |
| Deployed bundle | contains the Run surface and all three API calls |

---

## 5. Next steps

1. **The click-through, which needs your login.** Open the Build/Code tab on the
   Docker host, pick any model, have it write an Asteroids page, press **Run**,
   play it. Then a Vite app, to confirm the Node path in the browser too.
2. **Decide what to commit.** Today's work spans `repo_sandbox.py`,
   `workspace_sandbox.py` (new), `workspace_router.py`, `fab_repo.py`,
   `main.py`, the five `agent_reach_*` renames, `VibecodeRunSurface.svelte`
   (new), `WorkspaceMainPanel.svelte`, the VibeCode page, the agent-runs API
   client and `docker-compose.yaml`. The working tree also carries unrelated
   earlier work — the model-picker rework, `hermes_skills.py`, the staged MCP
   deletions — so it wants grouping, not one commit.
3. **Small honesty gap.** After Stop, the manager drops the box from its table,
   so `state()` returns `None` and the UI ladder never shows a "Stopped" rung;
   it falls back to the approval card. Harmless, worth closing.

## 6. Carried over, still open

- Three dead files staged as deleted but uncommitted: `McpShop.svelte`,
  `McpWizard.svelte`, `plugins/mcp/routes.py`.
- The HTTPS single-port change.
- Wiring MCP tools into plain chat.
- Uncommenting `NODE_OPTIONS` in `front_end/owui/Dockerfile:31`.
- `screenshot_preview` is offered while `HARVIS_VISION_SELF_CHECK_ENABLED=false`.
