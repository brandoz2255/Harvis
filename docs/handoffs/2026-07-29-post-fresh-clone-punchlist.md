# Handoff — 2026-07-29 → next session

**Where we are:** the fresh-clone install works. VM 900 (`harvis-clean`, Ubuntu 24.04, 8 GB, no GPU,
**192.168.20.95**) came up from nothing, the setup wizard walks a user from no model server to a pulled
and verified model, and the whole free/Ollama path is proven live end to end. The user's read after
walking the running stack: *"it looks fine but just needs those things."*

**Nothing is committed. Nothing is pushed.** The working tree on `deploy-optimize-test` is dirty and
everything below was deployed to the VM by rsync + restart, not by a build.

Session write-up: `~/Nexusys/code/harvis/2026-07-29-setup-wizard-model-step-and-the-ollama-path.md`

---

## Tomorrow's list — the four things the user called out

These are in the user's words first, then what I found while looking for the root cause. **None of
these were fixed today**; the user's instruction was explicitly "we will fix it up tomorrow."

### 1. TTS should be enabled by default

> "tts should be enabled by default"

Right now it is off in two independent places, and both probably need to move:

- **Per-user playback** — `front_end/owui/src/lib/components/chat/Settings/Audio.svelte:22` initialises
  `responseAutoPlayback = false`, and `:142` reads `$settings.responseAutoPlayback ?? false`. That `??`
  is the actual default for anyone who has never touched the toggle.
- **The engine itself** — `ResponseMessage.svelte:242` and `CallOverlay.svelte:541,587` all bail when
  `$config.audio.tts.engine === ''`, which is the shipped default in the admin panel
  (`admin/Settings/Audio.svelte:32`).

Worth noting `voice-onnx` **is** in the core service set (it's running on the VM, healthy), so there is
a working engine to point at out of the box. Flipping the user toggle without also defaulting the
engine would change nothing. Decide whether "enabled by default" means auto-playback on every reply or
just the speaker button working without a trip to Settings — those are different products and the
first one is intrusive.

### 2. OpenClaw needs a look

> "openclaw is another thing we have to take a look at afterwards"

Explicitly deferred by the user — "afterwards," not now, and no symptom was given. `harvis-openclaw` is
up and healthy on the main box (4 days) and is **not** in the VM's default service set. Ask what
specifically looked wrong before digging.

### 3. The open-notebook container is down

> "the open notebook container is down which is not good though"

Here is what I measured, and it points at something bigger than a crashed container.

On the **main box** both `open-notebook` and `harvis-open-notebook` are `Up 4 days`. On **VM 900** they
do not exist at all. The VM's complete default set is:

```
pgsql  artifact-init  backend  browser-runner  llmfit  voice-onnx  harvis-mcp  owui-builder  nginx
```

Notebooks is a shipped, linked-to feature (`/onb`, backed by `onb_compat`), and on a fresh clone
**nothing serves it**. So "down" on the fresh install is really "was never in the core set" — same
class of bug as the openclaw/config one from the Windows E2E, where a fresh clone starts nothing.

Two questions to settle before fixing: (a) does Notebooks belong in core, or does it get an honest
"not installed" state plus a one-click enable; and (b) it costs `surrealdb` + the lfnovo image, which
lands directly on the ≤7 GB budget. If the user meant the container on the *main* box instead, check
that first — but the VM gap is real either way.

### 4. `llama3.1:8b` is a name with nothing behind it in the Build coding area

> "the llama3.1b model is there by default but just in name only not in the actual list when were in
> the build coding area its a name bug if anything"

Confirmed as a hardcoded-default problem, not a display problem. The Build/orchestration lane carries
`llama3.1:8b` as a literal fallback in at least seven places, while the model *list* comes from whatever
the live provider actually has — so the label shows a model that isn't installed:

| File | Line | What it hardcodes |
|---|---|---|
| `python_back_end/workspace/orchestration/profiles.py` | 32, 62 | `"model_name": "llama3.1:8b"` |
| `python_back_end/workspace/orchestration/planner.py` | 35, 44 | pool + planner defaults |
| `python_back_end/workspace/orchestration/session_turn.py` | 274, 346 | `model_name or "llama3.1:8b"` |
| `python_back_end/workspace/orchestration/review.py` | 235 | `model_name or "llama3.1:8b"` |
| `front_end/owui/src/routes/(app)/harvis/vibecode/+page.svelte` | 806 | `usageModel` fallback |

There is already a precedent for the fix in this tree — `deep_research/router.py:62` and
`workspace/task_detector.py:82` both carry comments about removing exactly this kind of import-time
`llama3.1:8b` literal because most boxes don't have it. Do the same here: resolve against the installed
list, and if nothing matches, say so rather than naming a model.

---

## State you need before touching anything

**Uncommitted files** (main tree `/home/ommblitz/Projects/Recent-EX/Harvis`, branch `deploy-optimize-test`):

```
nginx.conf
install.sh
docker-compose.yaml
front_end/owui/src/routes/setup/+page.svelte          ← today's wizard work
front_end/owui/src/lib/agent-studio/adaptive/RepoRunnerSurface.svelte
python_back_end/main.py
python_back_end/setup_flow.py                          ← today's probe fix
python_back_end/cookbook/config.py
python_back_end/n8n/automation_service.py
python_back_end/n8n/workflow_builder.py
python_back_end/n8n_automation_system.py
python_back_end/ollama_cli/main.py
python_back_end/ollama_n8n_optimizer.py
python_back_end/workspace/orchestration/engine_adapter.py
```

**Still open from today:**

- The backend image has **not** been rebuilt. The five files that aren't bind-mounted
  (`n8n/automation_service.py`, `n8n/workflow_builder.py`, `n8n_automation_system.py`,
  `ollama_cli/main.py`, `ollama_n8n_optimizer.py`) are edited on disk but stale in the container.
- User E2E of the wizard in a browser hasn't happened yet.
- Whether to keep the setup-code gate is still the user's call. VM 900's code is `1d4d-7e88-40e2`.
- The push of 41 commits stays blocked on the credential rotation (the 51 MB `embedding/database_backup.dump`
  in the history of all three pushed branches of a public repo). `.dockerignore embedding/` is already
  committed as `3d28c8f4`.

**Deploy shortcuts that work:**

- owui — build locally (`npm run build` in `front_end/owui`), rsync to `~/harvis/front_end/owui/build`
  on the VM (root-owned, passwordless sudo), restart nginx. Do **not** run the Docker build on the VM;
  it takes ~25 minutes and nearly OOMs at 8 GB.
- backend — `harvis-backend` has 42 bind mounts, so rsync the file and `docker restart harvis-backend`.

**Standing rules still in force:** never `grep`/`Grep` on this box (it resolves to `ugrep` and wedges —
use Python `pathlib` + `re`; `docker exec … grep` and grep on remote hosts are fine); the user enters
all credentials, never the assistant; `origin/harvis1.1` stays untouched; one commit per task; hold
commits and pushes until the user verifies E2E, then ask.

---

## Suggested order

1. **#4, the `llama3.1:8b` name bug** — smallest, fully diagnosed above, and it makes the Build area
   stop lying about what's installed.
2. **#1, TTS defaults** — one decision (auto-playback vs. engine-available) then two small edits.
3. **#3, open-notebook** — needs a scope decision from the user because of the 7 GB budget, so raise
   the question early even if the work lands later.
4. **#2, OpenClaw** — the user deferred it and gave no symptom; ask what they saw first.
